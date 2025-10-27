#!/usr/bin/env python3
"""
SEC Filing Monitor - Real-time Autonomous Monitoring

Continuously polls SEC EDGAR for new filings from tracked SPACs
Routes filings to specialist agents for processing

Architecture:
    SEC RSS Feed → FilingDetector → Classifier → Agent Orchestrator → Database
"""

import os
import time
import json
import requests
import feedparser
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from database import SessionLocal, SPAC
from dotenv import load_dotenv
from sec_text_extractor import extract_filing_text
from orchestrator_trigger import get_accelerated_polling_tickers
from utils.sec_filing_fetcher import SECFilingFetcher

load_dotenv()

# DeepSeek AI for classification
try:
    from openai import OpenAI
    AI_CLIENT = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com"
    )
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False
    print("⚠️  DeepSeek AI not available - classification will be rule-based only")


class SECFilingMonitor:
    """
    Real-time SEC filing monitor using RSS feeds

    Polls SEC EDGAR every 15 minutes for new filings from tracked SPACs
    """

    def __init__(self, poll_interval_seconds: int = 900):  # 15 minutes
        self.poll_interval = poll_interval_seconds
        self.tracked_ciks = self._load_tracked_ciks()
        self.state_file = '.sec_filing_monitor_state.json'

        # Initialize SEC filing fetcher (centralized utility)
        self.sec_fetcher = SECFilingFetcher()

        # Load persisted state or initialize
        state = self._load_state()
        self.last_check = state.get('last_check', datetime.now() - timedelta(hours=24))  # Start 24 hours back if new
        self.seen_filings = set(state.get('seen_filings', []))

        print(f"✅ SEC Filing Monitor initialized")
        print(f"   Tracking {len(self.tracked_ciks)} SPACs")
        print(f"   Poll interval: {poll_interval_seconds}s ({poll_interval_seconds/60:.0f} min)")
        print(f"   Last check: {self.last_check.strftime('%Y-%m-%d %H:%M:%S')} ({(datetime.now() - self.last_check).total_seconds() / 3600:.1f}h ago)")

    def _load_state(self) -> Dict:
        """Load persisted state from disk"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    # Parse last_check from ISO string
                    if 'last_check' in state:
                        state['last_check'] = datetime.fromisoformat(state['last_check'])
                    return state
        except Exception as e:
            print(f"   ⚠️  Could not load state file: {e}")
        return {}

    def _save_state(self):
        """Persist state to disk"""
        try:
            state = {
                'last_check': self.last_check.isoformat(),
                'seen_filings': list(self.seen_filings)[-1000:]  # Keep last 1000 to prevent unbounded growth
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"   ⚠️  Could not save state file: {e}")

    def mark_filing_processed(self, filing_id: str):
        """
        Mark a single filing as successfully processed

        Called by orchestrator AFTER successful database insertion
        This prevents marking filings as "seen" if logging fails
        """
        self.seen_filings.add(filing_id)

    def mark_filings_processed(self, filing_ids: List[str]):
        """
        Mark multiple filings as successfully processed and save state

        Called by orchestrator AFTER processing all filings in a batch
        Only filings that were successfully logged to database should be passed here

        Args:
            filing_ids: List of filing IDs that were successfully processed
        """
        for filing_id in filing_ids:
            self.seen_filings.add(filing_id)

        # Now save state (includes updated last_check and seen_filings)
        self._save_state()
        print(f"   ✓ Marked {len(filing_ids)} filing(s) as processed and saved state")

    def _load_tracked_ciks(self) -> List[str]:
        """Load CIKs of all SPACs we're tracking"""
        db = SessionLocal()
        try:
            spacs = db.query(SPAC).filter(
                SPAC.cik.isnot(None)
            ).all()

            ciks = [spac.cik for spac in spacs if spac.cik]
            print(f"   ✓ Loaded {len(ciks)} CIKs from database")
            return ciks
        finally:
            db.close()


    def poll_sec_for_filing(self, cik: str) -> List[Dict]:
        """
        Poll SEC RSS feed for recent filings from a specific CIK

        SEC RSS URL format:
        https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=XXXXX&type=&dateb=&owner=exclude&count=40&output=atom
        """
        try:
            cik_padded = cik.zfill(10)
            rss_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_padded}&type=&dateb=&owner=exclude&count=40&output=atom"

            # Fetch RSS feed
            response = requests.get(rss_url, headers={
                'User-Agent': 'SPAC Research Platform admin@spacresearch.com'
            }, timeout=30)

            if response.status_code != 200:
                return []

            # Parse RSS feed
            feed = feedparser.parse(response.content)

            new_filings = []

            for entry in feed.entries:
                # Extract filing metadata
                # Try multiple date parsing methods (SEC uses 'updated' field)
                filing_date = None

                if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    # Primary: use updated_parsed (tuple format)
                    filing_date = datetime(*entry.updated_parsed[:6])
                elif hasattr(entry, 'updated'):
                    # Fallback: parse from string format
                    try:
                        filing_date = date_parser.parse(entry.updated)
                    except:
                        pass
                elif hasattr(entry, 'published_parsed') and entry.published_parsed:
                    filing_date = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'published'):
                    try:
                        filing_date = date_parser.parse(entry.published)
                    except:
                        pass

                if not filing_date:
                    # Skip entries without valid date
                    continue

                # Use 48-hour lookback window to prevent missing filings
                # (last_check can advance faster than filings are published)
                lookback_cutoff = datetime.now() - timedelta(hours=48)
                if filing_date < lookback_cutoff:
                    continue

                # Create unique filing ID
                filing_id = f"{cik}_{entry.title}_{filing_date.strftime('%Y%m%d')}"

                # Skip if already seen
                if filing_id in self.seen_filings:
                    continue

                # Extract filing type from title
                # Title format: "8-K - Current report"
                filing_type = entry.title.split(' - ')[0] if ' - ' in entry.title else entry.title

                # Resolve index page URL to primary document URL using centralized fetcher
                # This ensures we fetch the actual filing (e.g., 10-Q report) not just the index page
                primary_url = self.sec_fetcher.extract_document_url(entry.link, filing_type) or entry.link

                filing = {
                    'id': filing_id,
                    'cik': cik,
                    'type': filing_type,
                    'date': filing_date,
                    'title': entry.title,
                    'url': primary_url,  # Use resolved URL instead of entry.link
                    'summary': entry.summary if hasattr(entry, 'summary') else ''
                }

                new_filings.append(filing)
                # DON'T mark as seen yet - wait for successful DB insertion
                # self.seen_filings.add(filing_id)  # MOVED to mark_filing_processed()

            return new_filings

        except Exception as e:
            print(f"   ⚠️  Error polling CIK {cik}: {e}")
            return []

    def poll_all_spacs(self) -> List[Dict]:
        """Poll SEC for filings from all tracked SPACs"""
        print(f"\n🔍 Polling SEC for new filings...")
        print(f"   Last check: {self.last_check.strftime('%Y-%m-%d %H:%M:%S')}")

        all_filings = []

        for i, cik in enumerate(self.tracked_ciks):
            if i > 0 and i % 10 == 0:
                print(f"   Progress: {i}/{len(self.tracked_ciks)} CIKs checked")
                time.sleep(1)  # Rate limiting

            filings = self.poll_sec_for_filing(cik)
            all_filings.extend(filings)

            time.sleep(0.15)  # SEC rate limit: 10 requests/second

        print(f"   ✓ Found {len(all_filings)} new filings")

        # Fetch filing text content for each filing
        for filing in all_filings:
            filing['content'] = self.fetch_filing_content(filing)

        # Update last check time (but DON'T save state yet - wait for orchestrator confirmation)
        self.last_check = datetime.now()
        # DON'T save state here - orchestrator will call mark_filings_processed() after DB insertion
        # self._save_state()  # MOVED to mark_filings_processed()

        return all_filings

    def fetch_filing_content(self, filing: Dict) -> Optional[str]:
        """
        Fetch the actual filing text content

        This allows us to:
        1. Use filing text for better classification
        2. Pass text to agents (fetch once, use everywhere)
        3. Extract data from filing body, not just exhibits
        """
        filing_url = filing.get('url')

        if not filing_url:
            return None

        try:
            # Extract text using our universal extractor
            # Limit to 50k chars for efficiency (can increase if needed)
            content = extract_filing_text(filing_url, max_chars=50000)

            if content:
                print(f"      ✓ Fetched {len(content):,} chars of filing text")
            else:
                print(f"      ⚠️  Could not fetch filing text")

            return content

        except Exception as e:
            print(f"      ⚠️  Error fetching filing content: {e}")
            return None

    def _determine_priority(self, relevance_score: int) -> str:
        """Convert AI relevance score (0-100) to priority level"""
        if relevance_score >= 80:
            return 'CRITICAL'
        elif relevance_score >= 60:
            return 'HIGH'
        elif relevance_score >= 40:
            return 'MEDIUM'
        else:
            return 'LOW'

    def classify_filing(self, filing: Dict) -> Dict:
        """
        Classify filing priority and determine which agents to route to

        NEW: Uses Universal Filing Analyzer for comprehensive AI-powered analysis
        Falls back to rule-based classification if AI unavailable
        """
        # Try Universal Analyzer first (comprehensive AI analysis)
        try:
            from agents.universal_filing_analyzer import UniversalFilingAnalyzer

            # Ensure we have filing content
            content = filing.get('content')
            if content:
                analyzer = UniversalFilingAnalyzer()
                analysis = analyzer.analyze_filing_content(filing, content)

                # Convert AI analysis to classification format
                return {
                    'priority': self._determine_priority(analysis['relevance_score']),
                    'agents_needed': analysis['recommended_agents'],
                    'reason': analysis['summary'],
                    'data_types': analysis.get('data_types', {}),
                    'relevance_score': analysis['relevance_score']
                }
        except Exception as e:
            print(f"   ⚠️  Universal Analyzer failed: {e}")
            print(f"   ⏭️  Falling back to rule-based classification")

        # Fallback: Rule-based classification
        filing_type = filing['type']

        # High-priority filing types (rule-based pre-filter)
        high_priority_types = [
            '8-K',       # Current reports (deals, extensions, votes)
            '425',       # Merger communications
            'S-4',       # Merger registration
            'DEF 14A',   # Proxy statement (vote dates)
            'DEFM14A',   # Definitive merger proxy (deal terms)
            'DEFR14A',   # Revised merger proxy (updated redemptions)
            'PREM14A',   # Preliminary proxy (early deal terms)
            'SC TO',     # Tender offer schedule (no-vote deals)
            'SC TO-T',   # Third-party tender offer
            '424B4',     # Final prospectus (new IPOs)
            'S-1',       # IPO registration
            '10-Q',      # Quarterly report (trust account data)
            '10-K'       # Annual report (trust account data)
        ]

        # Quick rule-based routing for common cases
        if filing_type == '8-K':
            # Need to check 8-K item number - use AI
            return self._classify_8k_with_ai(filing)
        elif filing_type == '425':
            return {
                'priority': 'HIGH',
                'agents_needed': ['DealDetector'],
                'reason': 'Form 425 - Deal communication'
            }
        elif filing_type == 'S-4':
            return {
                'priority': 'HIGH',
                'agents_needed': ['S4Processor'],
                'reason': 'S-4 merger registration - deal terms'
            }
        elif filing_type == 'DEF 14A':
            return {
                'priority': 'HIGH',
                'agents_needed': ['FilingProcessor'],
                'reason': 'Proxy statement - shareholder vote'
            }
        elif filing_type in ['DEFM14A', 'DEFR14A', 'PREM14A']:
            return {
                'priority': 'HIGH',
                'agents_needed': ['FilingProcessor', 'RedemptionExtractor'],
                'reason': 'Merger proxy - comprehensive deal terms and redemptions'
            }
        elif filing_type in ['SC TO', 'SC TO-T']:
            return {
                'priority': 'HIGH',
                'agents_needed': ['FilingProcessor'],
                'reason': 'Tender offer - no-vote deal path'
            }
        elif filing_type in ['424B4', 'S-1']:
            return {
                'priority': 'MEDIUM',
                'agents_needed': ['IPODetector'],
                'reason': 'IPO filing - potential new SPAC'
            }
        elif filing_type == '10-Q':
            return {
                'priority': 'MEDIUM',
                'agents_needed': ['TrustAccountProcessor'],
                'reason': 'Quarterly report - trust account data update'
            }
        elif filing_type == '10-K':
            return {
                'priority': 'MEDIUM',
                'agents_needed': ['TrustAccountProcessor'],
                'reason': 'Annual report - trust account data update'
            }
        elif filing_type.startswith('25'):
            # Handle all Form 25 variants: 25, 25-NSE, 25-NSE/A, etc.
            return {
                'priority': 'CRITICAL',
                'agents_needed': ['DelistingDetector', 'CompletionMonitor'],
                'reason': f'Form {filing_type} - Delisting/liquidation/completion notification'
            }
        elif filing_type == 'DEFA14A':
            return {
                'priority': 'HIGH',
                'agents_needed': ['ProxyProcessor'],
                'reason': 'Definitive additional materials - proxy supplement'
            }
        elif filing_type == '8-K/A':
            return {
                'priority': 'MEDIUM',
                'agents_needed': ['DealDetector', 'RedemptionExtractor'],
                'reason': '8-K amendment - may correct deal terms or redemptions'
            }
        elif filing_type == 'S-4/A':
            return {
                'priority': 'HIGH',
                'agents_needed': ['S4Processor'],
                'reason': 'S-4 amendment - updated merger terms'
            }
        elif filing_type == 'EFFECT':
            return {
                'priority': 'MEDIUM',
                'agents_needed': ['EffectivenessMonitor'],
                'reason': 'S-4 effectiveness notice - merger registration effective'
            }
        elif filing_type in ['10-Q/A', '10-K/A']:
            return {
                'priority': 'MEDIUM',
                'agents_needed': ['TrustAccountProcessor'],
                'reason': f'{filing_type} amendment - corrected financial data'
            }
        elif filing_type == 'NT 10-Q' or filing_type == 'NT 10-K':
            return {
                'priority': 'LOW',
                'agents_needed': ['ComplianceMonitor'],
                'reason': 'Notice of late filing - compliance issue'
            }
        else:
            return {
                'priority': 'LOW',
                'agents_needed': [],
                'reason': f'Standard filing type: {filing_type}'
            }

    def _classify_8k_with_ai(self, filing: Dict) -> Dict:
        """
        Use AI to classify 8-K filing by determining Item number

        Critical Items:
        - Item 1.01: Material agreement (deal announcement)
        - Item 5.03: Articles amendment (deadline extension)
        - Item 2.01: Completion of acquisition (deal closed)
        - Item 7.01/8.01: Regulation FD (may contain important info)
        """
        if not AI_AVAILABLE:
            # Fallback: assume medium priority
            return {
                'priority': 'MEDIUM',
                'agents_needed': ['DealDetector', 'ExtensionMonitor'],
                'reason': '8-K filing - AI not available, checking all'
            }

        try:
            # Use filing content if available, otherwise use summary
            filing_text = filing.get('content', '')[:5000] if filing.get('content') else filing.get('summary', '')

            prompt = f"""
Classify this SEC 8-K filing to determine priority and routing:

Filing Type: {filing['type']}
Date: {filing['date']}
Title: {filing['title']}
Summary: {filing.get('summary', '')}

Filing Content (first 5000 chars):
{filing_text}

Determine:
1. Most likely Item number (1.01, 5.03, 2.01, etc.)
2. Priority (HIGH/MEDIUM/LOW)
3. Which agents should process it

Agents available:
- DealDetector: Detects business combination announcements
- ExtensionMonitor: Detects deadline extensions and redemptions
- RedemptionExtractor: Extracts vote results and redemption data
- CompletionMonitor: Detects deal closures

Return JSON:
{{
    "item_number": "1.01",
    "priority": "HIGH",
    "agents_needed": ["DealDetector"],
    "reason": "Likely business combination announcement"
}}

NOTE: If Item 5.07 (shareholder vote results), include RedemptionExtractor to extract redemptions.
"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an SEC filing classification expert. Analyze filings and route them correctly."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )

            classification = json.loads(response.choices[0].message.content)
            return classification

        except Exception as e:
            print(f"   ⚠️  AI classification failed: {e}")
            # Fallback
            return {
                'priority': 'MEDIUM',
                'agents_needed': ['DealDetector', 'ExtensionMonitor'],
                'reason': '8-K filing - AI classification failed'
            }

    def monitor_continuous(self):
        """
        Continuous monitoring loop

        Polls SEC every N seconds, classifies new filings, routes to agents
        """
        print(f"\n{'='*60}")
        print(f"STARTING CONTINUOUS SEC MONITORING")
        print(f"{'='*60}")
        print(f"Press Ctrl+C to stop\n")

        iteration = 0

        try:
            while True:
                iteration += 1
                print(f"\n[Iteration {iteration}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                # Check for accelerated polling tickers
                accelerated_tickers = get_accelerated_polling_tickers()
                if accelerated_tickers:
                    print(f"   🚀 Accelerated polling enabled for {len(accelerated_tickers)} ticker(s): {', '.join(accelerated_tickers)}")

                # Poll for new filings
                filings = self.poll_all_spacs()

                if not filings:
                    print(f"   No new filings - sleeping for {self.poll_interval}s")
                else:
                    # Classify and route each filing
                    for filing in filings:
                        classification = self.classify_filing(filing)

                        print(f"\n   📄 {filing['type']} filed {filing['date'].strftime('%Y-%m-%d')}")
                        print(f"      Priority: {classification['priority']}")
                        print(f"      Agents: {', '.join(classification['agents_needed'])}")
                        print(f"      Reason: {classification['reason']}")

                        # NOTE: filing_logger is called by orchestrator.process_filing()
                        # No need to log here (would be duplicate if standalone monitor was used)

                        # Route to agent orchestrator
                        if classification['agents_needed']:
                            print(f"      → Routing to agent orchestrator...")
                            # Import orchestrator (lazy load to avoid circular imports)
                            from agent_orchestrator import Orchestrator
                            orchestrator = Orchestrator()
                            orchestrator.process_filing(filing, classification)

                # Adaptive sleep: shorter intervals if we have accelerated tickers
                if accelerated_tickers:
                    sleep_interval = min(300, self.poll_interval)  # 5 minutes for accelerated
                    print(f"\n   ⚡ Accelerated mode: sleeping for {sleep_interval}s ({sleep_interval/60:.0f} min)...")
                else:
                    sleep_interval = self.poll_interval
                    print(f"\n   💤 Sleeping for {sleep_interval}s ({sleep_interval/60:.0f} min)...")

                time.sleep(sleep_interval)

        except KeyboardInterrupt:
            print(f"\n\n{'='*60}")
            print(f"MONITORING STOPPED")
            print(f"{'='*60}")
            print(f"Total iterations: {iteration}")
            print(f"Total filings seen: {len(self.seen_filings)}")


def main():
    """Main entry point - supports both test and continuous modes"""
    import argparse

    parser = argparse.ArgumentParser(description='SEC Filing Monitor')
    parser.add_argument('--continuous', action='store_true',
                       help='Run in continuous monitoring mode')
    parser.add_argument('--interval', type=int, default=900,
                       help='Poll interval in seconds (default: 900 = 15 min)')
    args = parser.parse_args()

    # Initialize monitor
    monitor = SECFilingMonitor(poll_interval_seconds=args.interval)

    if args.continuous:
        # Run continuous monitoring
        monitor.monitor_continuous()
    else:
        # Run one poll to test
        print("\nRunning single poll test...")
        filings = monitor.poll_all_spacs()

        if filings:
            print(f"\n{'='*60}")
            print(f"CLASSIFICATION TEST")
            print(f"{'='*60}")

            for filing in filings[:5]:  # Test first 5
                classification = monitor.classify_filing(filing)
                print(f"\n📄 {filing['type']} - {filing['date'].strftime('%Y-%m-%d')}")
                print(f"   Priority: {classification['priority']}")
                print(f"   Agents: {', '.join(classification['agents_needed'])}")
                print(f"   Reason: {classification['reason']}")


if __name__ == "__main__":
    main()
