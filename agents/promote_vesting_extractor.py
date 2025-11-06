#!/usr/bin/env python3
"""
Promote Vesting Extractor Agent

Extracts founder share vesting terms from S-1 filings to determine sponsor alignment.

Performance-based vesting (e.g., vest at $12, $15, $18) = strong alignment
Time-based vesting (e.g., vest over 3 years) = weaker alignment

Scoring Impact (Phase 1 "Loaded Gun"):
- Performance-based at $15+: 10 points
- Performance-based at $12+: 7 points
- Time-based: 3 points
- Immediate (no vesting): 0 points

Source: S-1 Section "Founder Shares" or "Sponsor Promote"
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

import json
import re
from typing import Dict, List, Optional
from datetime import datetime
from database import SessionLocal, SPAC
from utils.sec_filing_fetcher import SECFilingFetcher
from agents.orchestrator_agent_base import OrchestratorAgentBase
from openai import OpenAI
from dotenv import load_dotenv
import os
from bs4 import BeautifulSoup

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise Exception("DEEPSEEK_API_KEY required")

AI_CLIENT = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)


class PromoteVestingExtractor(OrchestratorAgentBase):
    """
    Extracts founder share vesting terms from S-1 filings

    Determines:
    - Vesting type: performance-based, time-based, or immediate
    - Price thresholds for performance vesting (e.g., [12.00, 15.00, 18.00])
    """

    def __init__(self):
        super().__init__('PromoteVestingExtractor')
        self.fetcher = SECFilingFetcher()

    def execute(self, task: Dict) -> Dict:
        """
        Execute vesting extraction task

        Task types:
        - 'extract_ticker': Extract vesting for specific ticker
        - 'extract_all': Extract vesting for all SPACs missing data
        """
        # Handle both dict and task object
        if hasattr(task, 'status'):
            self._start_task(task)
            task_dict = task.parameters or {}
        else:
            task_dict = task

        try:
            task_type = task_dict.get('task_type', 'extract_ticker')

            if task_type == 'extract_ticker':
                ticker = task_dict.get('ticker')
                result = self._extract_ticker_vesting(ticker)
            elif task_type == 'extract_all':
                limit = task_dict.get('limit', 50)
                result = self._extract_all_vesting(limit)
            else:
                raise ValueError(f"Unknown task type: {task_type}")

            if hasattr(task, 'status'):
                self._complete_task(task, result)
            return result

        except Exception as e:
            error_msg = f"Promote vesting extraction failed: {str(e)}"
            print(f"❌ {error_msg}")
            if hasattr(task, 'status'):
                self._fail_task(task, error_msg)
            return {'success': False, 'error': error_msg}

    def _extract_ticker_vesting(self, ticker: str) -> Dict:
        """Extract vesting terms for specific ticker"""
        if not ticker:
            return {'success': False, 'error': 'No ticker provided'}

        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                return {'success': False, 'error': f'SPAC {ticker} not found'}

            if not spac.cik:
                return {'success': False, 'error': f'{ticker} missing CIK'}

            print(f"\n🔍 Extracting vesting terms for {ticker}...")

            # Check if we have 424B4 URL in database
            if spac.prospectus_424b4_url and 'search.htm' not in spac.prospectus_424b4_url:
                print(f"   📄 Using 424B4 from database")
                print(f"   URL: {spac.prospectus_424b4_url}")
                vesting_data = self._extract_vesting_from_url(spac.prospectus_424b4_url, ticker)
            else:
                # Fallback: Search for 424B4 filing
                print(f"   🔍 Searching for 424B4 filing...")
                filings = self.fetcher.search_filings(
                    cik=spac.cik,
                    filing_type='424B4',
                    count=1
                )

                if not filings:
                    print(f"   ⚠️  No 424B4 filing found")
                    return {'success': False, 'error': 'No 424B4 filing found'}

                filing = filings[0]
                print(f"   📄 Found 424B4: {filing['date'].date()}")
                print(f"   URL: {filing['url']}")
                vesting_data = self._extract_vesting_from_filing(filing, ticker)

            if not vesting_data:
                return {'success': False, 'error': 'Could not extract vesting terms'}

            # Update database
            self._update_database(spac, vesting_data)
            db.commit()

            print(f"   ✅ Updated {ticker}:")
            print(f"      Type: {vesting_data['vesting_type']}")
            if vesting_data.get('vesting_prices'):
                print(f"      Prices: {vesting_data['vesting_prices']}")

            return {
                'success': True,
                'ticker': ticker,
                'vesting_data': vesting_data
            }

        finally:
            db.close()

    def _extract_all_vesting(self, limit: int = 50) -> Dict:
        """Extract vesting for all SPACs missing data"""
        db = SessionLocal()
        try:
            # Get SPACs without vesting data
            spacs = db.query(SPAC).filter(
                SPAC.promote_vesting_type.is_(None),
                SPAC.cik.isnot(None)
            ).limit(limit).all()

            print(f"\n🔍 Extracting vesting terms for {len(spacs)} SPACs...")

            extracted = 0
            failed = 0
            results = []

            for spac in spacs:
                result = self._extract_ticker_vesting(spac.ticker)
                if result['success']:
                    extracted += 1
                    results.append({
                        'ticker': spac.ticker,
                        'vesting_type': result['vesting_data']['vesting_type'],
                        'vesting_prices': result['vesting_data'].get('vesting_prices')
                    })
                else:
                    failed += 1

            print(f"\n✅ Extraction complete:")
            print(f"   Extracted: {extracted}")
            print(f"   Failed: {failed}")

            return {
                'success': True,
                'extracted': extracted,
                'failed': failed,
                'results': results
            }

        finally:
            db.close()

    def _extract_vesting_from_url(self, url: str, ticker: str) -> Optional[Dict]:
        """Extract vesting terms from a direct 424B4 URL"""
        try:
            # Fetch document content directly
            doc_content = self.fetcher.fetch_document(url)
            if not doc_content:
                print(f"   ⚠️  Could not fetch document content")
                return None

            soup = BeautifulSoup(doc_content, 'html.parser')
            text = soup.get_text()

            # Find section about founder shares / promote
            # Based on SEC filing patterns, these terms commonly appear:
            keywords = [
                'founder shares',
                'sponsor promote',
                'founder forfeiture',
                'earnout',
                'vesting',
                'founder share forfeiture',
                'performance-based vesting',
                'price-based vesting',
                'sponsor will forfeit',
                'shares will be forfeited',
                'price milestone',
                'trading day average'
            ]
            relevant_text = self._find_relevant_sections(text, keywords)

            if not relevant_text:
                print(f"   ⚠️  Could not find founder shares section")
                return None

            # Use AI to extract vesting terms
            vesting_data = self._ai_extract_vesting(relevant_text, ticker)
            return vesting_data

        except Exception as e:
            print(f"   ❌ Error extracting from URL: {e}")
            return None

    def _extract_vesting_from_filing(self, filing: Dict, ticker: str) -> Optional[Dict]:
        """Extract vesting terms from S-1 filing using AI"""
        try:
            # Fetch filing content
            doc_url = self.fetcher.extract_document_url(filing['url'], filing_type='S-1')
            if not doc_url:
                print(f"   ⚠️  Could not extract document URL")
                return None

            doc_content = self.fetcher.fetch_document(doc_url)
            if not doc_content:
                print(f"   ⚠️  Could not fetch document content")
                return None

            soup = BeautifulSoup(doc_content, 'html.parser')
            text = soup.get_text()

            # Find section about founder shares / promote
            # Search for relevant keywords in chunks
            keywords = ['founder shares', 'sponsor promote', 'founder forfeiture', 'earnout', 'vesting']
            relevant_text = self._find_relevant_sections(text, keywords)

            if not relevant_text:
                print(f"   ⚠️  Could not find founder shares section")
                return None

            # Use AI to extract vesting terms
            vesting_data = self._ai_extract_vesting(relevant_text, ticker)
            return vesting_data

        except Exception as e:
            print(f"   ❌ Error extracting from filing: {e}")
            return None

    def _find_relevant_sections(self, text: str, keywords: List[str], context_chars: int = 3000) -> str:
        """Find sections of text containing vesting information"""
        text_lower = text.lower()
        relevant_chunks = []

        for keyword in keywords:
            pos = text_lower.find(keyword)
            if pos != -1:
                # Extract context around keyword
                start = max(0, pos - context_chars)
                end = min(len(text), pos + context_chars)
                chunk = text[start:end]
                relevant_chunks.append(chunk)

        # Combine and deduplicate
        if relevant_chunks:
            return '\n\n'.join(relevant_chunks)[:12000]  # Limit to 12k chars for AI

        # Fallback: search for any mention of vesting in first 30k chars
        if 'vest' in text_lower[:30000]:
            return text[:12000]

        return ""

    def _ai_extract_vesting(self, text: str, ticker: str) -> Optional[Dict]:
        """Use AI to extract vesting terms"""
        try:
            prompt = f"""Extract founder share vesting terms from this SPAC 424B4 prospectus.

SPAC Ticker: {ticker}

VESTING TERMINOLOGY VARIATIONS (look for ALL):
- "Founder shares will be forfeited if..."
- "Sponsor will forfeit shares unless..."
- "Earnout shares vest at $X price"
- "Performance-based vesting at $X, $Y, $Z"
- "Shares vest when trading price reaches..."
- "Price milestones of $X, $Y, $Z"
- "No forfeiture" / "No vesting" = IMMEDIATE
- "Vest over X years" = TIME-BASED

VESTING TYPES:
1. PERFORMANCE-BASED: Founder shares vest/avoid forfeiture when stock hits price targets
   - Example: "1/3 forfeit if price doesn't reach $12.00, 1/3 at $15.00, 1/3 at $18.00"
   - Example: "Earnout shares vest at $12, $15, $18 trading day averages"

2. TIME-BASED: Vest over time regardless of stock performance
   - Example: "1/3 per year for 3 years"
   - Example: "Vest 12 months after business combination"

3. IMMEDIATE: No vesting restrictions
   - Example: "Founder shares have no forfeiture provisions"
   - Example: No vesting terms mentioned

EXTRACT FOUNDER SHARE COUNTS:
- Total founder shares: "14,785,714 founder shares" or "sponsor paid $25,000 for 12,321,429 Class B shares"
- Look for: "founder shares", "Class B shares", "sponsor shares", "initial shareholders holding"
- May be stated after overallotment: "Up to X shares will be surrendered"

EXTRACT VESTING DISTRIBUTION:
- If "one-third" or "1/3" → 0.33 (33.3%)
- If "one-half" or "50%" → 0.50
- If "25%" → 0.25
- Look for phrases like "one-third of such aggregate number of founder shares"
- Distribution should add up to 1.0 (100%)

Document Excerpt:
{text}

Return JSON:
{{
  "vesting_type": "performance" | "time-based" | "immediate",
  "vesting_prices": [12.00, 15.00, 18.00],  // ONLY if performance-based, otherwise null
  "founder_shares": 14785714,  // Total founder shares (numeric only, no commas)
  "vesting_distribution": [0.33, 0.33, 0.34],  // Distribution at each milestone (must sum to 1.0)
  "vesting_description": "Brief description of exact terms",
  "confidence": 0-100
}}

IMPORTANT:
- Return ONLY numeric values (no commas, no "$" signs)
- vesting_prices: [12.00, 15.00] NOT ["$12.00", "$15.00"]
- founder_shares: 14785714 NOT "14,785,714"
- vesting_distribution must sum to 1.0 (e.g., [0.33, 0.33, 0.34])
- If ANY price targets mentioned = "performance"
- If time-based only = "time-based"
- If no restrictions = "immediate"
"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an SEC filing analyst extracting vesting terms."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )

            response_text = response.choices[0].message.content.strip()

            # Extract JSON from response
            if not response_text.startswith('{'):
                start = response_text.find('{')
                end = response_text.rfind('}')
                if start != -1 and end != -1:
                    response_text = response_text[start:end+1]

            result = json.loads(response_text)

            # Validate and clean
            if result.get('vesting_type') not in ['performance', 'time-based', 'immediate']:
                print(f"   ⚠️  Invalid vesting type: {result.get('vesting_type')}")
                return None

            # Clean vesting_prices - ensure numeric array
            if result.get('vesting_prices'):
                try:
                    # Convert to list of floats
                    prices = []
                    for price in result['vesting_prices']:
                        if isinstance(price, str):
                            # Strip $ and convert
                            price = price.replace('$', '').replace(',', '').strip()
                        prices.append(float(price))
                    result['vesting_prices'] = sorted(prices)
                except Exception as e:
                    print(f"   ⚠️  Error parsing vesting prices: {e}")
                    result['vesting_prices'] = None

            # Clean founder_shares - ensure numeric
            if result.get('founder_shares'):
                try:
                    shares = result['founder_shares']
                    if isinstance(shares, str):
                        shares = shares.replace(',', '').strip()
                    result['founder_shares'] = float(shares)
                except Exception as e:
                    print(f"   ⚠️  Error parsing founder shares: {e}")
                    result['founder_shares'] = None

            # Clean vesting_distribution - ensure numeric array that sums to ~1.0
            if result.get('vesting_distribution'):
                try:
                    distribution = []
                    for pct in result['vesting_distribution']:
                        if isinstance(pct, str):
                            pct = pct.replace('%', '').strip()
                        distribution.append(float(pct))

                    # Validate distribution sums to ~1.0 (allow 0.99-1.01 for rounding)
                    total = sum(distribution)
                    if 0.99 <= total <= 1.01:
                        result['vesting_distribution'] = distribution
                    else:
                        print(f"   ⚠️  Vesting distribution doesn't sum to 1.0 (got {total})")
                        result['vesting_distribution'] = None
                except Exception as e:
                    print(f"   ⚠️  Error parsing vesting distribution: {e}")
                    result['vesting_distribution'] = None

            print(f"      🤖 AI extracted: {result['vesting_type']}")
            if result.get('vesting_prices'):
                print(f"         Prices: {result['vesting_prices']}")
            if result.get('founder_shares'):
                print(f"         Founder shares: {result['founder_shares']:,.0f}")
            if result.get('vesting_distribution'):
                print(f"         Distribution: {result['vesting_distribution']}")
            print(f"         Confidence: {result.get('confidence')}%")

            return result

        except json.JSONDecodeError as e:
            print(f"   ❌ AI returned invalid JSON: {e}")
            print(f"      Response: {response_text[:200] if 'response_text' in locals() else 'N/A'}")
            return None
        except Exception as e:
            print(f"   ❌ AI extraction error: {e}")
            return None

    def _update_database(self, spac: SPAC, vesting_data: Dict):
        """Update SPAC with vesting data"""
        spac.promote_vesting_type = vesting_data['vesting_type']

        # Store vesting_prices as Python list (PostgreSQL ARRAY column)
        if vesting_data.get('vesting_prices'):
            spac.promote_vesting_prices = vesting_data['vesting_prices']
        else:
            spac.promote_vesting_prices = None

        # Store founder_shares count
        if vesting_data.get('founder_shares'):
            spac.founder_shares = vesting_data['founder_shares']

        # Store vesting_distribution as Python list (PostgreSQL ARRAY column)
        if vesting_data.get('vesting_distribution'):
            spac.promote_vesting_distribution = vesting_data['vesting_distribution']
        else:
            spac.promote_vesting_distribution = None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Promote Vesting Extractor')
    parser.add_argument('--ticker', type=str, help='Extract vesting for specific ticker')
    parser.add_argument('--all', action='store_true', help='Extract vesting for all SPACs missing data')
    parser.add_argument('--limit', type=int, default=50, help='Max SPACs to process (default 50)')

    args = parser.parse_args()

    extractor = PromoteVestingExtractor()

    if args.ticker:
        task = {'task_type': 'extract_ticker', 'ticker': args.ticker}
        result = extractor.execute(task)

        if result['success']:
            print(f"\n✅ Extraction successful")
            print(f"   Type: {result['vesting_data']['vesting_type']}")
            if result['vesting_data'].get('vesting_prices'):
                print(f"   Prices: {result['vesting_data']['vesting_prices']}")
        else:
            print(f"\n❌ Extraction failed: {result.get('error')}")

    elif args.all:
        task = {'task_type': 'extract_all', 'limit': args.limit}
        result = extractor.execute(task)

        print(f"\n✅ Batch extraction complete:")
        print(f"   Extracted: {result['extracted']}")
        print(f"   Failed: {result['failed']}")

    else:
        parser.print_help()
