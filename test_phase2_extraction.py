#!/usr/bin/env python3
"""
Test: Phase 2 Data Extraction (PIPE, Projections, Lockup)
Tests extraction from 8-K exhibits at deal announcement

Integration: Will use existing filing agent architecture
- deal_detector_agent.py detects 8-K Item 1.01
- New agents extract from exhibits: PIPE extractor, Projection extractor
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

import requests
import time
import re
import json
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
from database import SessionLocal, SPAC
from utils.sec_filing_fetcher import SECFilingFetcher

try:
    from openai import OpenAI
    from dotenv import load_dotenv
    import os
    load_dotenv()

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    if DEEPSEEK_API_KEY:
        AI_CLIENT = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        AI_AVAILABLE = True
    else:
        AI_AVAILABLE = False
        print("⚠️  DEEPSEEK_API_KEY not found - AI extraction disabled")
except Exception as e:
    AI_AVAILABLE = False
    print(f"⚠️  AI not available: {e}")


class Phase2DataExtractor:
    """Test Phase 2 data extraction from 8-K exhibits"""

    def __init__(self):
        self.base_url = "https://www.sec.gov"
        self.headers = {'User-Agent': 'SPAC Research Platform admin@spacresearch.com'}
        self.db = SessionLocal()
        self.sec_fetcher = SECFilingFetcher()

    def close(self):
        self.db.close()

    def find_8k_deal_announcement(self, ticker: str, cik: str) -> Optional[str]:
        """Find 8-K Item 1.01 filing URL"""
        try:
            search_url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik.zfill(10),
                'type': '8-K',
                'count': 30,
                'dateb': ''
            }

            response = requests.get(search_url, params=params, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                return None

            # Look for 8-K with Item 1.01
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                    if doc_link:
                        filing_url = self.base_url + doc_link['href']

                        time.sleep(0.3)  # Rate limiting
                        filing_response = requests.get(filing_url, headers=self.headers, timeout=30)

                        if 'Item 1.01' in filing_response.text or 'Item 1.1' in filing_response.text:
                            print(f"   ✅ Found 8-K Item 1.01: {filing_url}")
                            return filing_url

            return None

        except Exception as e:
            print(f"   ❌ Error finding 8-K: {e}")
            return None

    def get_filing_exhibits(self, filing_index_url: str) -> Dict[str, str]:
        """Extract exhibit URLs from 8-K filing index page"""
        try:
            response = requests.get(filing_index_url, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            exhibits = {}

            # Find all exhibit links
            for row in soup.find_all('tr'):
                cols = row.find_all('td')
                if len(cols) >= 4:
                    # Column 3 usually has exhibit type
                    exhibit_type = cols[3].text.strip()

                    # Check if it's an exhibit we care about
                    if any(ex in exhibit_type for ex in ['EX-99.1', 'EX-10.1', 'EX-10.2', 'EX-99.2']):
                        doc_link = cols[2].find('a')
                        if doc_link:
                            exhibit_url = self.base_url + doc_link['href']
                            exhibits[exhibit_type] = exhibit_url

            return exhibits

        except Exception as e:
            print(f"   ❌ Error extracting exhibits: {e}")
            return {}

    def extract_pipe_data_from_press_release(self, exhibit_url: str) -> Dict:
        """
        Extract PIPE data from EX-99.1 (press release)

        Returns:
            {
                'pipe_size': 150000000,  # $150M
                'pipe_percentage': 65.2,  # 65.2% of trust
                'mentioned_investors': ['BlackRock', 'Fidelity']
            }
        """
        try:
            print(f"   📄 Fetching EX-99.1 (press release)...")

            # Fetch document
            html = self.sec_fetcher.fetch_document(exhibit_url)
            if not html:
                return {'error': 'Could not fetch exhibit'}

            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text()

            # Check if PIPE is mentioned
            if 'PIPE' not in text and 'private investment' not in text.lower():
                return {'has_pipe': False}

            if not AI_AVAILABLE:
                return {'error': 'AI not available for extraction'}

            # Use AI to extract structured data
            prompt = f"""Extract PIPE financing data from this press release.

Press Release Text (first 3000 chars):
{text[:3000]}

Extract ONLY these fields:
- pipe_size_millions: Dollar amount in millions (e.g., 150 for $150M)
- mentioned_investors: List of investor names mentioned (e.g., ["BlackRock", "Fidelity"])

Return ONLY valid JSON:
{{
    "pipe_size_millions": 150.0,
    "mentioned_investors": ["BlackRock", "Fidelity"]
}}

If no PIPE mentioned, return:
{{
    "pipe_size_millions": null,
    "mentioned_investors": []
}}
"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=200
            )

            result_text = response.choices[0].message.content.strip()
            result_text = re.sub(r'```json\s*|\s*```', '', result_text)

            data = json.loads(result_text)

            # Add sanitization for number formats
            if data.get('pipe_size_millions'):
                from utils.number_parser import parse_numeric_value
                data['pipe_size_millions'] = parse_numeric_value(data['pipe_size_millions'])

            return data

        except Exception as e:
            print(f"   ❌ Error extracting PIPE from press release: {e}")
            return {'error': str(e)}

    def extract_pipe_size_from_subscription(self, exhibit_url: str) -> Optional[float]:
        """
        Extract PIPE size from subscription agreement (EX-10.1/EX-10.2)

        Fallback when press release doesn't specify size.
        Looks for language like:
        - "agrees to purchase $50,000,000"
        - "subscription for 5,000,000 shares at $10.00 per share"
        """
        try:
            html = self.sec_fetcher.fetch_document(exhibit_url)
            if not html:
                return None

            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text()

            # Pattern matching for PIPE amounts
            patterns = [
                r'purchase\s+\$?([\d,]+(?:\.\d+)?)\s*million',
                r'\$\s*([\d,]+(?:\.\d+)?)\s*million.*?subscription',
                r'subscription.*?\$\s*([\d,]+(?:\.\d+)?)',
                r'aggregate.*?\$\s*([\d,]+(?:\.\d+)?)\s*million',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    amount_str = match.group(1).replace(',', '')

                    # Check if it's already in millions or needs conversion
                    if 'million' in match.group(0).lower():
                        return float(amount_str)
                    else:
                        # Likely full dollar amount, convert to millions
                        return float(amount_str) / 1_000_000

            # AI fallback if pattern matching fails
            if AI_AVAILABLE:
                prompt = f"""Extract total PIPE investment amount from this subscription agreement.

Agreement Text (first 2000 chars):
{text[:2000]}

Return ONLY valid JSON with amount in millions:
{{
    "pipe_size_millions": 150.0
}}

If no amount found, return: {{"pipe_size_millions": null}}
"""

                response = AI_CLIENT.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=100
                )

                result_text = response.choices[0].message.content.strip()
                result_text = re.sub(r'```json\s*|\s*```', '', result_text)

                data = json.loads(result_text)

                if data.get('pipe_size_millions'):
                    from utils.number_parser import parse_numeric_value
                    return parse_numeric_value(data['pipe_size_millions'])

            return None

        except Exception as e:
            print(f"   ❌ Error extracting PIPE size from subscription: {e}")
            return None

    def extract_pipe_lockup_from_subscription_agreement(self, exhibit_url: str) -> Dict:
        """
        Extract PIPE lockup period from EX-10.1/EX-10.2 (subscription agreement)

        Returns:
            {
                'lockup_months': 12,
                'lockup_description': 'Shares locked for 12 months from closing'
            }
        """
        try:
            print(f"   📄 Fetching EX-10.x (PIPE subscription agreement)...")

            html = self.sec_fetcher.fetch_document(exhibit_url)
            if not html:
                return {'error': 'Could not fetch exhibit'}

            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text()

            # Look for lockup language
            if 'lock' not in text.lower() and 'transfer restriction' not in text.lower():
                return {'lockup_months': None}

            # Pattern matching for lockup periods
            patterns = [
                r'(\d+)[\s-]?month[\s-]?lock[\s-]?up',
                r'locked for (\d+) months',
                r'lock[\s-]?up period of (\d+) months',
                r'transfer restrictions.*?(\d+) months'
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    lockup_months = int(match.group(1))
                    return {
                        'lockup_months': lockup_months,
                        'lockup_description': match.group(0)
                    }

            # Fallback: Check for date-based lockup (e.g., "until December 31, 2026")
            if not AI_AVAILABLE:
                return {'lockup_months': None, 'note': 'Could not parse lockup, AI unavailable'}

            # Use AI to extract if pattern matching fails
            prompt = f"""Extract PIPE share lockup period from this subscription agreement.

Agreement Text (relevant section):
{text[text.lower().find('lock'):text.lower().find('lock')+1000] if 'lock' in text.lower() else text[:2000]}

Return ONLY valid JSON with lockup period in months:
{{
    "lockup_months": 12
}}

If no lockup mentioned, return: {{"lockup_months": null}}
"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=100
            )

            result_text = response.choices[0].message.content.strip()
            result_text = re.sub(r'```json\s*|\s*```', '', result_text)

            data = json.loads(result_text)
            return data

        except Exception as e:
            print(f"   ❌ Error extracting lockup: {e}")
            return {'error': str(e)}

    def test_phase2_extraction(self, ticker: str):
        """
        Test Phase 2 extraction for a single SPAC

        Steps:
        1. Find 8-K Item 1.01 (deal announcement)
        2. Extract exhibits
        3. Test PIPE extraction from EX-99.1
        4. Test lockup extraction from EX-10.x
        """
        print(f"\n{'='*80}")
        print(f"TESTING: Phase 2 Data Extraction for {ticker}")
        print(f"{'='*80}\n")

        # Get SPAC from database
        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            print(f"❌ SPAC {ticker} not found in database")
            return

        if not spac.cik:
            print(f"❌ No CIK for {ticker}")
            return

        print(f"Ticker: {ticker}")
        print(f"Company: {spac.company}")
        print(f"Target: {spac.target}")
        print(f"Announced: {spac.announced_date}")
        print(f"Trust Cash: ${spac.trust_cash:,.0f}" if spac.trust_cash else "Trust Cash: N/A")

        # Step 1: Find 8-K Item 1.01
        print(f"\n{'─'*80}")
        print("Step 1: Finding 8-K Item 1.01 filing...")
        print(f"{'─'*80}\n")

        filing_url = self.find_8k_deal_announcement(ticker, spac.cik)
        if not filing_url:
            print(f"❌ Could not find 8-K Item 1.01 for {ticker}")
            return

        # Step 2: Extract exhibits
        print(f"\n{'─'*80}")
        print("Step 2: Extracting exhibits from 8-K...")
        print(f"{'─'*80}\n")

        exhibits = self.get_filing_exhibits(filing_url)
        print(f"   Found {len(exhibits)} relevant exhibits:")
        for exhibit_type, url in exhibits.items():
            print(f"      {exhibit_type}: {url}")

        # Step 3: Test PIPE extraction (with fallback)
        print(f"\n{'─'*80}")
        print("Step 3: Testing PIPE data extraction (EX-99.1 → EX-10.x fallback)...")
        print(f"{'─'*80}\n")

        pipe_size = None
        pipe_investors = []

        # Try EX-99.1 first
        if 'EX-99.1' in exhibits:
            print("   Attempting: EX-99.1 (press release)...")
            pipe_data = self.extract_pipe_data_from_press_release(exhibits['EX-99.1'])

            if 'error' in pipe_data:
                print(f"   ⚠️  {pipe_data['error']}")
            elif pipe_data.get('has_pipe') is False:
                print(f"   ℹ️  No PIPE mentioned in press release")
            else:
                pipe_size = pipe_data.get('pipe_size_millions')
                if pipe_size:
                    print(f"   ✅ PIPE Size from EX-99.1: ${pipe_size:.1f}M")
                else:
                    print(f"   ⚠️  PIPE mentioned but size not specified")

                pipe_investors = pipe_data.get('mentioned_investors', [])
                if pipe_investors:
                    print(f"   ✅ Mentioned Investors: {', '.join(pipe_investors)}")
        else:
            print(f"   ⚠️  EX-99.1 (press release) not found")

        # Fallback: Try EX-10.1/EX-10.2 if no size found
        if not pipe_size:
            print(f"\n   💡 FALLBACK: Trying EX-10.x (subscription agreements)...")

            subscription_exhibit = None
            for ex_type in ['EX-10.1', 'EX-10.2']:
                if ex_type in exhibits:
                    subscription_exhibit = exhibits[ex_type]
                    print(f"   Found {ex_type}, extracting PIPE size...")
                    break

            if subscription_exhibit:
                pipe_size_from_agreement = self.extract_pipe_size_from_subscription(subscription_exhibit)

                if pipe_size_from_agreement:
                    pipe_size = pipe_size_from_agreement
                    print(f"   ✅ PIPE Size from {ex_type}: ${pipe_size:.1f}M")
            else:
                print(f"   ⚠️  No subscription agreements found")

        # Display final PIPE analysis
        print(f"\n   {'─'*60}")
        print(f"   PIPE Analysis Summary:")
        print(f"   {'─'*60}")

        if pipe_size and spac.trust_cash:
            pipe_pct = (pipe_size * 1_000_000 / spac.trust_cash) * 100
            print(f"   💰 PIPE Size: ${pipe_size:.1f}M")
            print(f"   📊 PIPE Percentage: {pipe_pct:.1f}% of trust (${spac.trust_cash:,.0f})")

            # Scoring
            if pipe_pct > 100:
                score = 20
                print(f"   🔥 Score: {score}/20 (MEGA PIPE >100%)")
            elif pipe_pct >= 75:
                score = 15
                print(f"   🔥 Score: {score}/20 (Large PIPE 75-100%)")
            elif pipe_pct >= 50:
                score = 10
                print(f"   ✅ Score: {score}/20 (Solid PIPE 50-75%)")
            elif pipe_pct >= 25:
                score = 5
                print(f"   ⚠️  Score: {score}/20 (Small PIPE 25-50%)")
            else:
                score = 0
                print(f"   ❌ Score: {score}/20 (Minimal PIPE <25%)")
        else:
            print(f"   ⚠️  PIPE size not found in any exhibits")
            print(f"   ℹ️  Note: Some deals don't have PIPE, or it's in DEFM14A (filed later)")

        # Step 4: Test lockup extraction
        print(f"\n{'─'*80}")
        print("Step 4: Testing PIPE lockup extraction (EX-10.x)...")
        print(f"{'─'*80}\n")

        lockup_exhibit = None
        for ex_type in ['EX-10.1', 'EX-10.2']:
            if ex_type in exhibits:
                lockup_exhibit = exhibits[ex_type]
                break

        if lockup_exhibit:
            lockup_data = self.extract_pipe_lockup_from_subscription_agreement(lockup_exhibit)

            if 'error' in lockup_data:
                print(f"   ⚠️  {lockup_data['error']}")
            elif lockup_data.get('lockup_months'):
                print(f"   ✅ Lockup Period: {lockup_data['lockup_months']} months")
                if lockup_data.get('lockup_description'):
                    print(f"   ℹ️  Details: {lockup_data['lockup_description'][:100]}...")
            else:
                print(f"   ℹ️  No lockup period found")
        else:
            print(f"   ⚠️  EX-10.1/EX-10.2 (subscription agreement) not found")

        # Summary
        print(f"\n{'='*80}")
        print("SUMMARY: Integration with Existing Agent Architecture")
        print(f"{'='*80}\n")
        print("""
How Phase 2 extraction will integrate:

1. deal_detector_agent.py (EXISTING)
   - Detects 8-K Item 1.01 filings
   - Updates: deal_status='ANNOUNCED', target, announced_date

2. pipe_extractor_agent.py (NEW - to build)
   - Triggered when deal_status changes to 'ANNOUNCED'
   - Fetches 8-K exhibits (EX-99.1, EX-10.x)
   - Extracts: pipe_size, pipe_percentage, mentioned_investors, lockup_months
   - Updates database

3. projection_extractor_agent.py (NEW - to build)
   - Triggered when DEFA14A/425 filed (investor deck)
   - Extracts: projected_revenue_y1/y2/y3
   - Calculates: revenue_cagr (hockey stick detection)
   - Updates database

Agent orchestrator flow:
  8-K Item 1.01 detected → deal_detector_agent
                        ↓
        deal_status='ANNOUNCED' → pipe_extractor_agent (Phase 2)
                        ↓
     DEFA14A/425 detected → projection_extractor_agent (Phase 2)
                        ↓
         Phase 2 data complete → opportunity_scorer_agent (calculate scores)
""")


def main():
    """Test Phase 2 extraction on Klein deal"""

    extractor = Phase2DataExtractor()

    try:
        # Test on DYNX (Klein deal announced 2025-07-21)
        print("\n" + "="*80)
        print("TEST: Phase 2 Data Extraction (PIPE, Lockup)")
        print("="*80)
        print("\nTesting with DYNX (Klein Sponsor, announced deal with Ether Reserve)...\n")

        extractor.test_phase2_extraction('DYNX')

        print("\n" + "="*80)
        print("NEXT STEPS:")
        print("="*80)
        print("""
1. If successful, build production agents:
   - agents/pipe_extractor_agent.py
   - agents/projection_extractor_agent.py

2. Integrate with orchestrator:
   - Add agents to agent_orchestrator.py
   - Trigger on deal announcement

3. Database schema:
   - CREATE TABLE pipe_investors (...)
   - ALTER TABLE spacs ADD COLUMN pipe_lockup_months INT

4. Scoring algorithm:
   - agents/opportunity_scorer_agent.py
   - Calculate Phase 1 + Phase 2 scores
   - Send Telegram alerts for high scores
""")

    finally:
        extractor.close()


if __name__ == '__main__':
    main()
