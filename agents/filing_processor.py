#!/usr/bin/env python3
"""
Unified Filing Processor - Extracts data from SEC filings

Consolidates 3 separate agents into one:
- VoteExtractorAgent (DEF 14A)
- MergerProxyExtractor (DEFM14A)
- TenderOfferProcessor (Schedule TO)

Workflow:
1. Route to appropriate extractor based on filing type
2. Fetch document and extract relevant sections
3. Use AI to extract structured data
4. Update database
"""

import os
import sys
import re
import requests
from datetime import datetime, date
from typing import Dict, Optional
from bs4 import BeautifulSoup

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from database import SessionLocal, SPAC
from utils.deal_value_tracker import update_deal_value
from utils.deal_structure_tracker import update_deal_structure
from utils.trust_account_tracker import update_trust_cash, update_trust_value, update_shares_outstanding
from utils.redemption_tracker import add_redemption_event, mark_no_redemptions_found
from utils.expected_close_normalizer import normalize_expected_close
from dotenv import load_dotenv

load_dotenv()

# DeepSeek AI for structured extraction
from openai import OpenAI

AI_CLIENT = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


class FilingProcessor(BaseAgent):
    """
    Unified processor for all SEC filing types

    Supported filings:
    - DEF 14A / DEFA14A / PRE 14A: Vote dates
    - DEFM14A / PREM14A: Deal terms
    - Schedule TO / SC TO: Tender offers
    """

    def __init__(self, name: str = 'filing_processor'):
        super().__init__(name)
        self.base_url = "https://www.sec.gov"
        self.headers = {
            "User-Agent": "LEVP SPAC Platform fenil@legacyevp.com",
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov"
        }

    async def can_process(self, filing: Dict) -> bool:
        """Check if this is a processable filing type"""
        filing_type = filing.get('type', '').upper()
        return any([
            '14A' in filing_type,  # All proxy statements
            'S-4' in filing_type,  # Registration statements for business combinations
            'SC TO' in filing_type,  # Tender offers
            'SC 13E3' in filing_type  # Going private transactions
        ])

    async def process(self, filing: Dict) -> Optional[Dict]:
        """Route to appropriate processor based on filing type"""

        filing_type = filing.get('type', '').upper()

        # Route to specialized processor
        if filing_type in ['DEF 14A', 'DEFA14A', 'PRE 14A']:
            return await self._process_vote_proxy(filing)
        elif filing_type in ['DEFM14A', 'PREM14A']:
            return await self._process_merger_proxy(filing)
        elif 'S-4' in filing_type:
            return await self._process_s4_registration(filing)
        elif 'SC TO' in filing_type or 'SC 13E3' in filing_type:
            return await self._process_tender_offer(filing)
        else:
            print(f"   ⚠️  Unknown filing type: {filing_type}")
            return None

    # ========================================================================
    # COMMON UTILITIES (used by all processors)
    # ========================================================================

    def _get_document_url(self, filing_url: str, filing_type: str) -> Optional[str]:
        """Get actual document URL from filing index page"""

        try:
            response = requests.get(filing_url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')

            # Search patterns based on filing type
            if '14A' in filing_type:
                search_terms = ['def14a', 'formdef', 'prem14a', '14a']
            elif 'SC TO' in filing_type:
                search_terms = ['sc', 'to']
            else:
                search_terms = []

            # Find matching document link
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()

                if '.htm' in href and not '.xml' in href:
                    # Check if matches filing type
                    if any(term in href for term in search_terms):
                        if not href.startswith('http'):
                            return self.base_url + link['href']
                        return link['href']

            # Fallback: First .htm file that's not index and is in /Archives/edgar/data/
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                if '.htm' in href and not '.xml' in href and 'index' not in href and '/archives/edgar/data/' in href:
                    if not href.startswith('http'):
                        return self.base_url + link['href']
                    return link['href']

            return None

        except Exception as e:
            print(f"   ⚠️  Error getting document URL: {e}")
            return None

    def _fetch_document(self, doc_url: str) -> Optional[str]:
        """Fetch and parse document content"""

        try:
            response = requests.get(doc_url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(response.content, 'html.parser')

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            # Get text content
            text = soup.get_text()

            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            text = '\n'.join(line for line in lines if line)

            return text

        except Exception as e:
            print(f"   ⚠️  Error fetching document: {e}")
            return None

    def _extract_section(self, text: str, start_markers: list, max_length: int = 10000) -> Optional[str]:
        """Extract a specific section by finding start marker"""

        text_upper = text.upper()

        for marker in start_markers:
            marker_upper = marker.upper()
            start_pos = text_upper.find(marker_upper)

            if start_pos != -1:
                section = text[start_pos:start_pos + max_length]
                return section

        return None

    def _call_ai(self, prompt: str) -> Optional[Dict]:
        """Call AI with structured extraction prompt"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a financial document extraction expert specializing in SEC filings."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )

            result = response.choices[0].message.content
            import json
            return json.loads(result)

        except Exception as e:
            print(f"   ⚠️  AI extraction failed: {e}")
            return None

    # ========================================================================
    # VOTE PROXY PROCESSOR (DEF 14A)
    # ========================================================================

    async def _process_vote_proxy(self, filing: Dict) -> Optional[Dict]:
        """Extract vote date from DEF 14A filing"""

        ticker = filing.get('ticker')
        filing_url = filing.get('url')
        filing_date = filing.get('date')

        print(f"\n🗳️  {ticker} - Extracting vote date from DEF 14A...")

        # Get document
        doc_url = self._get_document_url(filing_url, 'DEF 14A')
        if not doc_url:
            print(f"   ❌ Could not find DEF 14A document")
            return None

        content = self._fetch_document(doc_url)
        if not content:
            print(f"   ❌ Could not fetch document")
            return None

        # Try regex first (faster)
        vote_data = self._extract_vote_date_regex(content)

        # Fallback to AI if regex failed
        if not vote_data:
            print(f"   🤖 Regex failed, trying AI extraction...")
            vote_data = self._extract_vote_date_with_ai(content[:10000], ticker)

        if not vote_data:
            print(f"   ⚠️  Could not extract vote date (regex and AI both failed)")
            return None

        # Update database
        self._update_vote_data(ticker, vote_data, filing_date)

        # Check if vote is urgent
        if vote_data.get('vote_date'):
            days_until = (vote_data['vote_date'] - date.today()).days
            if 0 < days_until <= 14:
                print(f"   ⚠️  URGENT: Vote in {days_until} days!")

        self.processed_count += 1
        return vote_data

    def _extract_vote_date_regex(self, content: str) -> Optional[Dict]:
        """Fast regex-based extraction"""

        patterns = [
            r'(?:meeting|held|scheduled).*?(?:on|for)\s+([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})',
            r'(?:special meeting|extraordinary meeting).*?([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})',
            r'BE HELD ON\s+([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})',
        ]

        found_dates = []
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                date_str = matches[0]
                try:
                    vote_date = datetime.strptime(date_str, '%B %d, %Y').date()
                    found_dates.append((vote_date, date_str))

                    # Validate date is reasonable
                    days_diff = (vote_date - date.today()).days
                    if -30 < days_diff < 180:
                        print(f"   ✅ Vote date (regex): {vote_date}")
                        return {'vote_date': vote_date}
                    else:
                        print(f"   ⚠️  Found date {vote_date} but outside valid range ({days_diff} days from today)")
                except Exception as e:
                    print(f"   ⚠️  Could not parse date string: {date_str}")
                    continue

        if found_dates:
            print(f"   ℹ️  Regex found {len(found_dates)} date(s) but none in valid range")

        return None

    def _extract_vote_date_with_ai(self, content: str, ticker: str) -> Optional[Dict]:
        """AI-powered vote date extraction"""

        prompt = f"""Extract shareholder meeting information from this DEF 14A for SPAC {ticker}.

Document excerpt:
{content}

Extract:
1. **Shareholder meeting date** - When is the meeting?
2. **Record date** - Who is eligible to vote?
3. **Meeting location** - Physical address or virtual?
4. **Expected transaction close date** - When will the deal close?

Return JSON:
{{
  "vote_date": "YYYY-MM-DD",
  "record_date": "YYYY-MM-DD",
  "meeting_location": "address or Virtual",
  "expected_close": "YYYY-MM-DD" or "Q1 2026" or "H2 2025" or null
}}

If cannot find vote date, return {{"vote_date": null}}.
"""

        data = self._call_ai(prompt)
        if not data:
            return None

        # Parse dates
        if data.get('vote_date'):
            try:
                data['vote_date'] = datetime.strptime(data['vote_date'], '%Y-%m-%d').date()
                print(f"   ✅ Vote date: {data['vote_date']}")
            except:
                data['vote_date'] = None

        if data.get('record_date'):
            try:
                data['record_date'] = datetime.strptime(data['record_date'], '%Y-%m-%d').date()
            except:
                data['record_date'] = None

        return data if data.get('vote_date') else None

    def _update_vote_data(self, ticker: str, vote_data: Dict, filing_date: date):
        """Update database with vote date"""

        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                print(f"   ⚠️  SPAC {ticker} not found")
                return

            updated_fields = []

            if vote_data.get('vote_date'):
                spac.shareholder_vote_date = vote_data['vote_date']
                updated_fields.append(f"vote_date={vote_data['vote_date']}")

            if not spac.proxy_filed_date:
                spac.proxy_filed_date = filing_date

            # Extract expected_close if found and not already set
            if vote_data.get('expected_close') and not spac.expected_close:
                normalized_close = normalize_expected_close(vote_data['expected_close'])
                if normalized_close:
                    spac.expected_close = normalized_close
                    updated_fields.append(f"expected_close={normalized_close}")

            if updated_fields:
                print(f"   ✅ Updated {ticker}: {', '.join(updated_fields)}")

            db.commit()

        except Exception as e:
            print(f"   ⚠️  Database update failed: {e}")
            db.rollback()
        finally:
            db.close()

    # ========================================================================
    # MERGER PROXY PROCESSOR (DEFM14A)
    # ========================================================================

    async def _process_merger_proxy(self, filing: Dict) -> Optional[Dict]:
        """Extract deal terms from DEFM14A filing"""

        ticker = filing.get('ticker')
        filing_url = filing.get('url')
        filing_date = filing.get('date')  # Get filing date for precedence

        print(f"\n📋 {ticker} - Extracting deal terms from DEFM14A...")

        # Get document
        doc_url = self._get_document_url(filing_url, 'DEFM14A')
        if not doc_url:
            print(f"   ❌ Could not find DEFM14A document")
            return None

        content = self._fetch_document(doc_url)
        if not content:
            print(f"   ❌ Could not fetch document")
            return None

        # Extract relevant sections only (saves AI costs)
        sections = {
            'summary': content[:15000],
            'questions_and_answers': self._extract_section(content, ['QUESTIONS AND ANSWERS', 'Q&A'], 10000),
            'transaction': self._extract_section(content, ['THE TRANSACTION', 'THE MERGER', 'BUSINESS COMBINATION'], 15000),
            'pro_forma': self._extract_section(content, ['PRO FORMA', 'UNAUDITED PRO FORMA'], 8000)
        }

        # Remove None sections
        sections = {k: v for k, v in sections.items() if v}

        print(f"   ✓ Extracted {len(sections)} sections")

        # Extract with AI
        deal_terms = self._extract_deal_terms_with_ai(sections, ticker)
        if not deal_terms:
            print(f"   ⚠️  Could not extract deal terms")
            return None

        # Update database with filing date for precedence tracking
        self._update_deal_terms(ticker, deal_terms, filing_date)

        self.processed_count += 1
        return deal_terms

    def _extract_deal_terms_with_ai(self, sections: Dict[str, str], ticker: str) -> Optional[Dict]:
        """AI extraction of deal terms"""

        combined_text = ""
        for section_name, section_text in sections.items():
            combined_text += f"\n\n=== {section_name.upper()} ===\n\n{section_text[:8000]}"

        prompt = f"""Extract vote date, trust account data, redemption data, and deal terms from this DEFM14A/DEF14A for SPAC {ticker}.

Document sections:
{combined_text[:25000]}

PRIORITY 0: SHAREHOLDER VOTE DATE (check first page!)
Look for:
- "Special Meeting of Stockholders" date
- "The special meeting will be held on [DATE]"
- Meeting date/time (e.g., "November 15, 2025 at 10:00 a.m. EST")
- Return as "YYYY-MM-DD" format

PRIORITY 0.5: PRE-VOTE TRUST ACCOUNT BALANCE (CRITICAL for redemption calculations!)
Look for trust account balance disclosure (usually in Summary, first page, or Q&A section):
- "As of [date], there was approximately $XX million in the trust account"
- "trust account contained $XX,XXX,XXX"
- "representing a per share pro rata amount of approximately $X.XX"
- "$X.XX per share" or "NAV of $X.XX"
- "per-share redemption price of $X.XX"

Extract:
- **pre_vote_trust_cash**: Total dollars in trust (e.g., "$72,452,618" or "$72.45M")
- **pre_vote_nav_per_share**: NAV/redemption price per share (e.g., "$10.50" or "$10.43")
- **trust_balance_date**: Date of trust balance (e.g., "September 17, 2025")

⚠️ This is CRITICAL - without pre-vote NAV, we cannot calculate post-redemption trust cash!

PRIORITY 1: REDEMPTIONS (most important!)
Look for ACTUAL redemptions (not estimates):
- "X shares were redeemed" or "X shares exercised redemption rights"
- "shareholders holding X shares elected to redeem"
- "as of [date], X shares had been redeemed"
- "no redemptions" or "zero shares redeemed"

⚠️  IGNORE estimates like "assumes X% redemptions" or "up to X shares may be redeemed"

PRIORITY 2: Deal Terms
1. **deal_value** - Enterprise or equity value as numeric dollars (e.g., 500000000 for "$500M", 1200000000 for "$1.2B")
2. **expected_close** - Expected closing date ("YYYY-MM-DD" or "Q1 2026")

Deal Structure (if mentioned):
3. **min_cash** - Minimum cash condition as numeric dollars (e.g., 200000000 for "$200M")
4. **min_cash_percentage** - Minimum cash as % (e.g., 25.0 for "25%")
5. **pipe_size** - PIPE investment amount as numeric dollars (e.g., 100000000 for "$100M")
6. **pipe_price** - PIPE share price as numeric dollars (e.g., 10.0 for "$10.00")
7. **earnout_shares** - Earnout/contingent shares as numeric count (e.g., 5000000 for "5M shares")
8. **forward_purchase** - Forward purchase agreement as numeric dollars (e.g., 50000000 for "$50M")

Return JSON (ALL DOLLAR AMOUNTS AS NUMERIC VALUES):
{{
  "shareholder_vote_date": "YYYY-MM-DD" or null,
  "pre_vote_trust_cash": 72452618 or null,
  "pre_vote_nav_per_share": 10.50 or null,
  "trust_balance_date": "YYYY-MM-DD" or null,
  "redemptions_checked": true/false,
  "redemptions_found": true/false,
  "shares_redeemed": <number or 0>,
  "redemption_amount": <dollars or 0>,
  "redemption_price": <price per share or null>,
  "deal_value": 500000000 or null,
  "expected_close": "2026-03-31" or null,
  "min_cash": 200000000 or null,
  "min_cash_percentage": 25.0 or null,
  "pipe_size": 100000000 or null,
  "pipe_price": 10.0 or null,
  "earnout_shares": 5000000 or null,
  "forward_purchase": 50000000 or null
}}

CRITICAL:
- Set redemptions_checked=true if you searched for redemption data (even if none found)
- ALWAYS try to extract pre_vote_trust_cash and pre_vote_nav_per_share - these are essential!
If any field is not found, return null for that field.
"""

        data = self._call_ai(prompt)
        if not data:
            return None

        found_fields = [k for k, v in data.items() if v]
        if found_fields:
            print(f"   ✅ Extracted: {', '.join(found_fields)}")
            return data

        return None

    def _update_deal_terms(self, ticker: str, deal_terms: Dict, filing_date: date = None):
        """Update database with deal terms"""

        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                print(f"   ⚠️  SPAC {ticker} not found")
                return

            updated_fields = []

            # Use date-based precedence for deal_value
            if deal_terms.get('deal_value'):
                if not filing_date:
                    filing_date = date.today()  # Fallback to today if not provided

                updated = update_deal_value(
                    db_session=db,
                    ticker=ticker,
                    new_value=deal_terms['deal_value'],
                    source='DEFM14A',
                    filing_date=filing_date,
                    reason='Extracted from merger proxy statement'
                )

                if updated:
                    updated_fields.append(f"deal_value={deal_terms['deal_value']}")

            # Use tracker for deal structure fields
            structure_fields = {
                'min_cash': deal_terms.get('min_cash'),
                'min_cash_percentage': deal_terms.get('min_cash_percentage'),
                'pipe_size': deal_terms.get('pipe_size'),
                'pipe_price': deal_terms.get('pipe_price'),
                'earnout_shares': deal_terms.get('earnout_shares'),
                'forward_purchase': deal_terms.get('forward_purchase')
            }

            # Filter out None values
            structure_fields = {k: v for k, v in structure_fields.items() if v is not None}

            if structure_fields:
                if not filing_date:
                    filing_date = date.today()

                updated = update_deal_structure(
                    db_session=db,
                    ticker=ticker,
                    structure_data=structure_fields,
                    source='DEFM14A',
                    filing_date=filing_date,
                    reason='Deal structure from merger proxy'
                )

                if updated:
                    updated_fields.extend([f"{k}={v}" for k, v in structure_fields.items()])

            # Update shareholder vote date
            if deal_terms.get('shareholder_vote_date'):
                try:
                    # Parse vote date string to date object
                    vote_date_str = deal_terms['shareholder_vote_date']
                    if isinstance(vote_date_str, str):
                        from datetime import datetime
                        vote_date = datetime.strptime(vote_date_str, '%Y-%m-%d').date()
                        spac.shareholder_vote_date = vote_date
                        updated_fields.append(f"vote_date={vote_date}")
                        print(f"   ✅ Vote date: {vote_date}")
                except Exception as e:
                    print(f"   ⚠️  Could not parse vote_date: '{deal_terms['shareholder_vote_date']}' - {e}")

            if deal_terms.get('expected_close'):
                # Normalize expected_close to proper date format
                normalized_close = normalize_expected_close(deal_terms['expected_close'])
                if normalized_close:
                    spac.expected_close = normalized_close
                    updated_fields.append(f"expected_close={normalized_close}")
                else:
                    print(f"   ⚠️  Could not normalize expected_close: '{deal_terms['expected_close']}'")

            # CRITICAL: Save pre-vote trust data (needed for post-redemption calculation)
            if deal_terms.get('pre_vote_trust_cash') or deal_terms.get('pre_vote_nav_per_share'):
                pre_trust_updated = self._save_pre_vote_trust_data(
                    spac, deal_terms, filing_date, updated_fields
                )
                if pre_trust_updated:
                    print(f"   ✅ Saved pre-vote trust data for redemption calculation")

            if updated_fields:
                db.commit()
                print(f"   ✅ Updated {ticker}: {', '.join(updated_fields)}")

            # Handle redemption data using tracker (AFTER commit for deal terms)
            if deal_terms.get('redemptions_checked'):
                if deal_terms.get('redemptions_found') and deal_terms.get('shares_redeemed', 0) > 0:
                    # Add redemption event (incremental)
                    redemption_amount = deal_terms.get('redemption_amount', 0)
                    if redemption_amount == 0 and deal_terms.get('redemption_price'):
                        # Calculate amount if not provided
                        redemption_amount = deal_terms['shares_redeemed'] * deal_terms['redemption_price']

                    add_redemption_event(
                        db_session=db,
                        ticker=ticker,
                        shares_redeemed=deal_terms['shares_redeemed'],
                        redemption_amount=redemption_amount,
                        filing_date=filing_date if filing_date else date.today(),
                        source='DEFM14A',
                        reason='Actual redemptions in merger proxy'
                    )
                    print(f"   ✓ Redemption: {deal_terms['shares_redeemed']:,.0f} shares redeemed")

                    # CRITICAL: Calculate post-redemption trust cash
                    self._calculate_post_redemption_trust(db, ticker, deal_terms, filing_date)
                else:
                    # Mark that we checked and found no redemptions (or only estimates)
                    mark_no_redemptions_found(
                        db_session=db,
                        ticker=ticker,
                        filing_date=filing_date if filing_date else date.today(),
                        source='DEFM14A'
                    )
                    print(f"   ✓ No actual redemptions found in proxy")

        except Exception as e:
            print(f"   ⚠️  Database update failed: {e}")
            db.rollback()
        finally:
            db.close()

    def _save_pre_vote_trust_data(self, spac: SPAC, deal_terms: Dict, filing_date: date, updated_fields: list) -> bool:
        """
        Save pre-vote trust account data from DEF14A/DEFM14A

        This data is CRITICAL for calculating post-redemption trust cash using:
        post_trust = pre_trust - (redeemed_shares × NAV) + deposits
        """
        try:
            saved_any = False

            # Parse and save pre-vote trust cash
            if deal_terms.get('pre_vote_trust_cash'):
                trust_cash_str = str(deal_terms['pre_vote_trust_cash'])
                # Parse: "$72,452,618" or "$72.45M"
                trust_cash_str = trust_cash_str.replace('$', '').replace(',', '')

                if 'M' in trust_cash_str.upper():
                    trust_cash = float(trust_cash_str.replace('M', '').replace('m', '')) * 1_000_000
                elif 'B' in trust_cash_str.upper():
                    trust_cash = float(trust_cash_str.replace('B', '').replace('b', '')) * 1_000_000_000
                else:
                    trust_cash = float(trust_cash_str)

                spac.pre_redemption_trust_cash = trust_cash
                updated_fields.append(f"pre_trust_cash=${trust_cash:,.0f}")
                saved_any = True

            # Parse and save pre-vote NAV per share
            if deal_terms.get('pre_vote_nav_per_share'):
                nav_str = str(deal_terms['pre_vote_nav_per_share'])
                # Parse: "$10.50" or 10.50
                nav_str = nav_str.replace('$', '').replace(',', '')
                nav = float(nav_str)

                spac.pre_redemption_nav = nav
                updated_fields.append(f"pre_nav=${nav:.2f}")
                saved_any = True

            # Save trust balance date
            if deal_terms.get('trust_balance_date'):
                try:
                    from datetime import datetime
                    balance_date_str = deal_terms['trust_balance_date']
                    if isinstance(balance_date_str, str):
                        balance_date = datetime.strptime(balance_date_str, '%Y-%m-%d').date()
                        spac.trust_balance_date = balance_date
                        updated_fields.append(f"trust_date={balance_date}")
                        saved_any = True
                except Exception as e:
                    print(f"   ⚠️  Could not parse trust_balance_date: {e}")

            # Save DEF14A filing metadata
            if filing_date:
                spac.def14a_filing_date = filing_date
                saved_any = True

            return saved_any

        except Exception as e:
            print(f"   ⚠️  Error saving pre-vote trust data: {e}")
            return False

    def _calculate_post_redemption_trust(self, db, ticker: str, deal_terms: Dict, filing_date: date = None):
        """
        Calculate post-redemption trust cash using DTSQ pattern:
        post_trust = pre_trust - (redeemed_shares × NAV) + deposits

        Only runs if we have:
        1. Pre-vote trust cash and NAV (from DEF14A)
        2. Shares redeemed (from post-vote disclosure)
        """
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                return False

            # Check we have all required data
            if not spac.pre_redemption_trust_cash or not spac.pre_redemption_nav:
                print(f"   ℹ️  Cannot calculate post-redemption trust: missing pre-vote data")
                return False

            if not deal_terms.get('shares_redeemed') or deal_terms['shares_redeemed'] == 0:
                print(f"   ℹ️  No redemptions to calculate")
                return False

            # Get data
            pre_vote_trust = float(spac.pre_redemption_trust_cash)
            nav_per_share = float(spac.pre_redemption_nav)
            shares_redeemed = deal_terms['shares_redeemed']
            extension_deposit = deal_terms.get('extension_deposit', 0)

            # Calculate
            cash_paid_out = shares_redeemed * nav_per_share
            post_redemption_trust = pre_vote_trust - cash_paid_out + extension_deposit

            print(f"\n   📊 Post-Redemption Trust Calculation:")
            print(f"      Pre-vote trust: ${pre_vote_trust:,.2f}")
            print(f"      NAV per share: ${nav_per_share:.2f}")
            print(f"      Shares redeemed: {shares_redeemed:,}")
            print(f"      Cash paid out: ${cash_paid_out:,.2f}")
            print(f"      Extension deposit: ${extension_deposit:,.2f}")
            print(f"      Post-redemption trust: ${post_redemption_trust:,.2f}")

            # Update trust_cash in database
            # Use trust_balance_date if available (more accurate than filing date)
            effective_date = spac.trust_balance_date if spac.trust_balance_date else (filing_date if filing_date else date.today())

            update_trust_cash(
                db_session=db,
                ticker=ticker,
                new_value=post_redemption_trust,
                source='DEFM14A',
                filing_date=effective_date
            )
            print(f"      Using date: {effective_date} (trust balance date)" if spac.trust_balance_date else f"      Using date: {effective_date} (filing date)")

            # Recalculate trust_value and premium
            if spac.shares_outstanding and spac.shares_outstanding > 0:
                spac.trust_value = round(post_redemption_trust / spac.shares_outstanding, 2)
                print(f"      New trust value: ${spac.trust_value:.2f} per share")

            from utils.trust_account_tracker import recalculate_premium
            recalculate_premium(db, ticker)

            db.commit()
            print(f"   ✅ Post-redemption trust calculation complete!")
            return True

        except Exception as e:
            print(f"   ⚠️  Post-redemption calculation failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ========================================================================
    # S-4 REGISTRATION PROCESSOR
    # ========================================================================

    async def _process_s4_registration(self, filing: Dict) -> Optional[Dict]:
        """Extract deal terms from S-4 registration statement"""

        ticker = filing.get('ticker')
        filing_url = filing.get('url')
        filing_date = filing.get('date')

        print(f"\n📄 {ticker} - Extracting deal terms from S-4...")

        # Get document
        doc_url = self._get_document_url_s4(filing_url)
        if not doc_url:
            print(f"   ❌ Could not find S-4 document")
            return None

        content = self._fetch_document(doc_url)
        if not content:
            print(f"   ❌ Could not fetch document")
            return None

        # Extract relevant sections (S-4s are long, focus on key areas)
        sections = {
            'prospectus_summary': content[:20000],  # Usually at the beginning
            'risk_factors': self._extract_section(content, ['RISK FACTORS'], 8000),
            'transaction_summary': self._extract_section(content, ['THE TRANSACTION', 'THE MERGER', 'BUSINESS COMBINATION PROPOSAL'], 15000),
            'questions_and_answers': self._extract_section(content, ['QUESTIONS AND ANSWERS ABOUT THE PROPOSALS', 'QUESTIONS AND ANSWERS'], 12000)
        }

        sections = {k: v for k, v in sections.items() if v}

        print(f"   ✓ Extracted {len(sections)} sections")

        # Extract with AI
        deal_terms = self._extract_s4_terms_with_ai(sections, ticker)
        if not deal_terms:
            print(f"   ⚠️  Could not extract deal terms")
            return None

        # Update database
        self._update_s4_terms(ticker, deal_terms, filing_date)

        self.processed_count += 1
        return deal_terms

    def _get_document_url_s4(self, filing_url: str) -> Optional[str]:
        """Get S-4 document URL from filing index page"""

        try:
            response = requests.get(filing_url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for the main S-4 document
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()

                if '.htm' in href and not '.xml' in href:
                    # S-4 documents often have 's4' or '424b3' in the name
                    if any(term in href for term in ['s4', '424b3', 'form']):
                        if not href.startswith('http'):
                            return self.base_url + link['href']
                        return link['href']

            # Fallback: First .htm file that's not index and is in /Archives/edgar/data/
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                if '.htm' in href and not '.xml' in href and 'index' not in href and '/archives/edgar/data/' in href:
                    if not href.startswith('http'):
                        return self.base_url + link['href']
                    return link['href']

            return None

        except Exception as e:
            print(f"   ⚠️  Error getting S-4 URL: {e}")
            return None

    def _extract_s4_terms_with_ai(self, sections: Dict[str, str], ticker: str) -> Optional[Dict]:
        """AI extraction of S-4 deal terms"""

        combined_text = ""
        for section_name, section_text in sections.items():
            combined_text += f"\n\n=== {section_name.upper()} ===\n\n{section_text[:10000]}"

        prompt = f"""Extract business combination details from this S-4 registration statement for SPAC {ticker}.

Document sections:
{combined_text[:30000]}

Extract:
1. **expected_close** - Expected closing date or quarter (e.g., "Q4 2025", "2026-06-30", "first half of 2026")
2. **deal_value** - Enterprise or equity value as numeric dollars (e.g., 500000000 for "$500M", 1200000000 for "$1.2B")
3. **target** - Target company name (if not already known)

Deal Structure (if mentioned):
4. **min_cash** - Minimum cash condition as numeric dollars (e.g., 200000000 for "$200M")
5. **min_cash_percentage** - Minimum cash as percentage (e.g., 25.0 for "25%")
6. **pipe_size** - PIPE investment amount as numeric dollars (e.g., 100000000 for "$100M")
7. **pipe_price** - PIPE share price as numeric dollars (e.g., 10.0 for "$10.00")
8. **earnout_shares** - Earnout/contingent shares as numeric count (e.g., 5000000 for "5M shares")
9. **forward_purchase** - Forward purchase agreement as numeric dollars (e.g., 50000000 for "$50M")

Return JSON (ALL DOLLAR AMOUNTS AS NUMERIC VALUES):
{{
  "expected_close": "Q1 2026" or "2026-03-31" or null,
  "deal_value": 500000000 or null,
  "target": "Target Company Inc." or null,
  "min_cash": 200000000 or null,
  "min_cash_percentage": 25.0 or null,
  "pipe_size": 100000000 or null,
  "pipe_price": 10.0 or null,
  "earnout_shares": 5000000 or null,
  "forward_purchase": 50000000 or null
}}

If any field is not found, return null for that field.
"""

        data = self._call_ai(prompt)
        if not data:
            return None

        found_fields = [k for k, v in data.items() if v]
        if found_fields:
            print(f"   ✅ Extracted: {', '.join(found_fields)}")
            return data

        return None

    def _update_s4_terms(self, ticker: str, deal_terms: Dict, filing_date: date):
        """Update database with S-4 deal terms"""

        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                print(f"   ⚠️  SPAC {ticker} not found")
                return

            updated_fields = []

            # Use date-based precedence for deal_value
            if deal_terms.get('deal_value'):
                updated = update_deal_value(
                    db_session=db,
                    ticker=ticker,
                    new_value=deal_terms['deal_value'],
                    source='S-4',
                    filing_date=filing_date,
                    reason='Extracted from S-4 registration statement'
                )

                if updated:
                    updated_fields.append(f"deal_value={deal_terms['deal_value']}")

            # Use tracker for deal structure fields
            structure_fields = {
                'min_cash': deal_terms.get('min_cash'),
                'min_cash_percentage': deal_terms.get('min_cash_percentage'),
                'pipe_size': deal_terms.get('pipe_size'),
                'pipe_price': deal_terms.get('pipe_price'),
                'earnout_shares': deal_terms.get('earnout_shares'),
                'forward_purchase': deal_terms.get('forward_purchase')
            }

            # Filter out None values
            structure_fields = {k: v for k, v in structure_fields.items() if v is not None}

            if structure_fields:
                updated = update_deal_structure(
                    db_session=db,
                    ticker=ticker,
                    structure_data=structure_fields,
                    source='S-4',
                    filing_date=filing_date,
                    reason='Deal structure from S-4 registration'
                )

                if updated:
                    updated_fields.extend([f"{k}={v}" for k, v in structure_fields.items()])

            # Update expected_close only if not already set (8-K takes precedence if earlier)
            if deal_terms.get('expected_close') and not spac.expected_close:
                normalized_close = normalize_expected_close(deal_terms['expected_close'])
                if normalized_close:
                    spac.expected_close = normalized_close
                    updated_fields.append(f"expected_close={normalized_close}")

            # Update target if found and not already set
            if deal_terms.get('target') and not spac.target:
                spac.target = deal_terms['target']
                spac.deal_status = 'ANNOUNCED'
                if not spac.announced_date:
                    spac.announced_date = filing_date
                updated_fields.append(f"target={deal_terms['target']}")

            if updated_fields:
                db.commit()
                print(f"   ✅ Updated {ticker}: {', '.join(updated_fields)}")

        except Exception as e:
            print(f"   ⚠️  Database update failed: {e}")
            db.rollback()
        finally:
            db.close()

    # ========================================================================
    # TENDER OFFER PROCESSOR (Schedule TO)
    # ========================================================================

    async def _process_tender_offer(self, filing: Dict) -> Optional[Dict]:
        """Extract tender offer terms"""

        ticker = filing.get('ticker')
        filing_url = filing.get('url')
        filing_date = filing.get('date')

        print(f"\n🤝 {ticker} - Extracting tender offer terms...")

        # Get document
        doc_url = self._get_document_url(filing_url, 'SC TO')
        if not doc_url:
            print(f"   ❌ Could not find Schedule TO document")
            return None

        content = self._fetch_document(doc_url)
        if not content:
            print(f"   ❌ Could not fetch document")
            return None

        # Extract relevant sections
        sections = {
            'summary': content[:10000],
            'terms': self._extract_section(content, ['TERMS OF THE OFFER', 'TERMS AND CONDITIONS'], 12000),
            'purpose': self._extract_section(content, ['PURPOSE', 'PURPOSE AND STRUCTURE'], 10000)
        }

        sections = {k: v for k, v in sections.items() if v}

        print(f"   ✓ Extracted {len(sections)} sections")

        # Extract with AI
        offer_terms = self._extract_tender_offer_with_ai(sections, ticker)
        if not offer_terms:
            print(f"   ⚠️  Could not extract offer terms")
            return None

        # Update database
        self._update_tender_offer(ticker, offer_terms, filing_date)

        self.processed_count += 1
        return offer_terms

    def _extract_tender_offer_with_ai(self, sections: Dict[str, str], ticker: str) -> Optional[Dict]:
        """AI extraction of tender offer terms"""

        combined_text = ""
        for section_name, section_text in sections.items():
            combined_text += f"\n\n=== {section_name.upper()} ===\n\n{section_text[:8000]}"

        prompt = f"""Extract tender offer terms from this Schedule TO for SPAC {ticker}.

Document sections:
{combined_text[:20000]}

Extract:
1. **offer_price** - Price per share as numeric dollars (e.g., 10.50 for "$10.50")
2. **offer_expiration** - When offer expires ("YYYY-MM-DD")
3. **minimum_condition** - Minimum shares needed ("50% of shares")
4. **deal_value** - Total transaction value as numeric dollars (e.g., 500000000 for "$500M")
5. **target** - Target company name

Return JSON (ALL DOLLAR AMOUNTS AS NUMERIC VALUES):
{{
  "offer_price": 10.50 or null,
  "offer_expiration": "2026-01-15" or null,
  "minimum_condition": "50%" or null,
  "deal_value": 500000000 or null,
  "target": "Company Name" or null
}}
"""

        data = self._call_ai(prompt)
        if not data:
            return None

        found_fields = [k for k, v in data.items() if v]
        if found_fields:
            print(f"   ✅ Extracted: {', '.join(found_fields)}")
            return data

        return None

    def _update_tender_offer(self, ticker: str, offer_terms: Dict, filing_date: date):
        """Update database with tender offer terms"""

        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                print(f"   ⚠️  SPAC {ticker} not found")
                return

            updated_fields = []

            # Mark as deal announced if we have a target
            if offer_terms.get('target') and not spac.target:
                spac.target = offer_terms['target']
                spac.deal_status = 'ANNOUNCED'
                spac.announced_date = filing_date
                updated_fields.append(f"target={offer_terms['target']}")

            # Use date-based precedence for deal_value
            if offer_terms.get('deal_value'):
                updated = update_deal_value(
                    db_session=db,
                    ticker=ticker,
                    new_value=offer_terms['deal_value'],
                    source='SC TO',
                    filing_date=filing_date,
                    reason='Extracted from tender offer statement'
                )

                if updated:
                    updated_fields.append(f"deal_value={offer_terms['deal_value']}")

            # Store tender offer details in notes
            if offer_terms:
                tender_note = "Tender Offer: "
                if offer_terms.get('offer_price'):
                    tender_note += f"${offer_terms['offer_price']}/share, "
                if offer_terms.get('offer_expiration'):
                    tender_note += f"Expires: {offer_terms['offer_expiration']}, "
                if offer_terms.get('minimum_condition'):
                    tender_note += f"Min: {offer_terms['minimum_condition']}"

                if spac.notes:
                    spac.notes += f" | {tender_note}"
                else:
                    spac.notes = tender_note

                updated_fields.append("tender_offer_terms")

            if updated_fields:
                db.commit()
                print(f"   ✅ Updated {ticker}: {', '.join(updated_fields)}")

        except Exception as e:
            print(f"   ⚠️  Database update failed: {e}")
            db.rollback()
        finally:
            db.close()


if __name__ == "__main__":
    """Test filing processor"""

    import asyncio

    async def test_filing_processor():
        processor = FilingProcessor()

        # Test with recent filings
        test_filings = [
            {
                'ticker': 'ATMC',
                'type': 'DEF 14A',
                'url': 'https://www.sec.gov/Archives/edgar/data/1889106/000149315225012831/0001493152-25-012831-index.htm',
                'date': date(2025, 9, 9)
            }
        ]

        for filing in test_filings:
            can_process = await processor.can_process(filing)
            print(f"\nCan process {filing['type']}: {can_process}")

            if can_process:
                result = await processor.process(filing)
                print(f"Result: {result}")

    asyncio.run(test_filing_processor())
