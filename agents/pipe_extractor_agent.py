#!/usr/bin/env python3
"""
PIPE Extractor Agent - Extract PIPE financing data from 8-K deal announcements

PIPE (Private Investment in Public Equity) is critical for Phase 2 "Lit Fuse" scoring:
- Shows institutional commitment to the deal
- Larger PIPE = more confidence from sophisticated investors
- PIPE pricing relative to SPAC price shows deal attractiveness

Data Sources (per DATA_SOURCE_MATRIX.md):
- Primary: 8-K Item 1.01 (Business Combination Agreement)
- Exhibits: EX-10.1 (PIPE subscription agreement), EX-99.1 (press release)
- Timeliness: 0-4 days after deal announcement

Extracts:
- has_pipe: Boolean flag if PIPE exists
- pipe_size: Total PIPE amount (in millions)
- pipe_price: Price per share
- pipe_percentage: PIPE as % of total deal
- pipe_lockup_months: Lockup period

Uses SECFilingFetcher for all API calls.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

import re
import json
from typing import Dict, Optional, List
from datetime import datetime
from bs4 import BeautifulSoup

from utils.sec_filing_fetcher import SECFilingFetcher
from database import SessionLocal, SPAC
from utils.number_parser import parse_numeric_value, sanitize_ai_response

# DeepSeek AI for extraction
try:
    from openai import OpenAI
    import os
    AI_CLIENT = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com"
    )
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False


class PIPEExtractorAgent:
    """
    Extract PIPE financing data from 8-K deal announcements

    Strategy:
    1. Check if 8-K is a deal announcement (Item 1.01)
    2. Extract exhibit URLs (EX-10.1, EX-99.1)
    3. Parse exhibits for PIPE mentions
    4. Use AI to extract structured PIPE data
    5. Apply number parsing to avoid format errors
    """

    def __init__(self):
        self.fetcher = SECFilingFetcher()
        self.db = SessionLocal()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    async def process_filing(self, filing: Dict, ticker: str) -> Optional[Dict]:
        """
        Process 8-K filing for PIPE data

        Args:
            filing: Filing dict with type, url, date
            ticker: SPAC ticker

        Returns:
            Dict with PIPE data if found, None otherwise
        """
        filing_type = filing.get('type', '').strip()  # Strip whitespace
        filing_url = filing.get('url')

        if filing_type != '8-K':
            return None

        print(f"\n🔍 Processing {ticker} 8-K for PIPE data...")
        print(f"   URL: {filing_url}")

        # Fetch filing content
        filing_html = self.fetcher.fetch_document(filing_url)
        if not filing_html:
            print(f"   ❌ Could not fetch filing")
            return None

        soup = BeautifulSoup(filing_html, 'html.parser')

        # Check if this is a deal announcement
        if not self._is_deal_announcement(soup):
            print(f"   ℹ️  Not a deal announcement, skipping PIPE extraction")
            return None

        # First, try extracting from 8-K body text (some deals include full BCA text)
        body_text = soup.get_text()
        if 'pipe' in body_text.lower():
            print(f"   🔍 PIPE mentioned in 8-K body, checking...")
            body_pipe = await self._ai_extract_pipe(body_text[:8000], ticker)
            # Only return if we got actual PIPE amounts (confidence > 70%)
            if body_pipe and body_pipe.get('has_pipe') and body_pipe.get('pipe_size') and body_pipe.get('confidence', 0) > 70:
                updated = self._update_database(ticker, body_pipe)
                if updated:
                    print(f"   ✅ Updated {ticker} with PIPE data from 8-K body")
                    return {'success': True, 'pipe_data': body_pipe}
            elif body_pipe and body_pipe.get('has_pipe'):
                print(f"   ℹ️  PIPE detected in body but no amounts, checking exhibits...")

        # Extract exhibits using SEC fetcher (handles index pages properly)
        exhibits = self.fetcher.extract_exhibits(filing_url)

        # Convert to our exhibit format
        formatted_exhibits = []
        for ex in exhibits:
            formatted_exhibits.append({
                'text': f"EX-{ex['exhibit_number']} - {ex['description']}",
                'url': ex['url'],
                'type': self._classify_exhibit(f"EX-{ex['exhibit_number']}")
            })

        if not formatted_exhibits:
            print(f"   ⚠️  No exhibits found")
            return None

        # Sort by priority (Press Release > Institutional PIPE > Other PIPE > BCA)
        priority_order = {'press_release': 1, 'pipe_institutional': 2, 'pipe_agreement': 3, 'bca': 4, 'other': 5}
        formatted_exhibits.sort(key=lambda x: priority_order.get(x['type'], 999))

        exhibits = formatted_exhibits

        print(f"   📎 Found {len(exhibits)} exhibits")

        # Extract PIPE data from exhibits
        pipe_data = await self._extract_pipe_from_exhibits(exhibits, ticker)

        if pipe_data:
            # Update database
            updated = self._update_database(ticker, pipe_data)
            if updated:
                print(f"   ✅ Updated {ticker} with PIPE data")
                return {'success': True, 'pipe_data': pipe_data}
            else:
                print(f"   ⚠️  Failed to update database")
                return {'success': False, 'error': 'Database update failed'}
        else:
            print(f"   ℹ️  No PIPE data found in exhibits")
            return None

    def _is_deal_announcement(self, soup: BeautifulSoup) -> bool:
        """Check if 8-K is a deal announcement (Item 1.01 or Item 8.01 with press release)"""
        text = soup.get_text().lower()

        # Look for Item 1.01 (Entry into Material Definitive Agreement)
        has_item_101 = 'item 1.01' in text or 'item 1.1' in text
        has_deal_keywords = any(keyword in text for keyword in [
            'business combination agreement',
            'merger agreement',
            'definitive agreement',
            'agreement and plan of merger'
        ])

        # Item 1.01 with deal keywords = definitive deal announcement
        if has_item_101 and has_deal_keywords:
            return True

        # Item 8.01 (Other Events) often used for deal press releases
        # Check if it has press release exhibits
        has_item_801 = 'item 8.01' in text
        has_press_release = 'press release' in text.lower()

        return has_item_801 and has_press_release

    def _extract_exhibits(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """
        Extract exhibit URLs from 8-K

        Priority order (per DATA_SOURCE_MATRIX):
        1. EX-10.1 - PIPE subscription agreement
        2. EX-99.1 - Press release
        3. EX-2.1 - Business combination agreement
        """
        exhibits = []

        # Find exhibit links
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().strip().upper()

            # Match exhibit patterns
            if any(pattern in text for pattern in ['EX-10.1', 'EX-99.1', 'EX-2.1', 'EXHIBIT']):
                # Convert relative URL to absolute
                if href.startswith('/'):
                    href = f'https://www.sec.gov{href}'
                elif not href.startswith('http'):
                    href = base_url.rsplit('/', 1)[0] + '/' + href

                exhibits.append({
                    'text': text,
                    'url': href,
                    'type': self._classify_exhibit(text)
                })

        # Sort by priority (Press Release > Institutional PIPE > Other PIPE > BCA)
        # Press release has total PIPE summary, forms/BCAs often have incomplete data
        priority_order = {'press_release': 1, 'pipe_institutional': 2, 'pipe_agreement': 3, 'bca': 4, 'other': 5}
        exhibits.sort(key=lambda x: priority_order.get(x['type'], 999))

        return exhibits

    def _classify_exhibit(self, text: str) -> str:
        """Classify exhibit by type with priority for institutional PIPE"""
        text_upper = text.upper()

        # Prioritize institutional PIPE subscription agreements
        if 'EX-10.1' in text_upper or ('SUBSCRIPTION' in text_upper and 'INSTITUTIONAL' in text_upper):
            return 'pipe_institutional'
        elif 'EX-10' in text_upper or 'SUBSCRIPTION' in text_upper or 'PIPE' in text_upper:
            return 'pipe_agreement'
        elif 'EX-99.1' in text_upper or ('PRESS' in text_upper and 'RELEASE' in text_upper):
            return 'press_release'
        elif 'EX-2' in text_upper or 'BUSINESS COMBINATION' in text_upper:
            return 'bca'
        else:
            return 'other'

    async def _extract_pipe_from_exhibits(self, exhibits: List[Dict], ticker: str) -> Optional[Dict]:
        """Extract PIPE data from exhibits using AI"""

        if not AI_AVAILABLE:
            print(f"   ⚠️  AI not available, skipping PIPE extraction")
            return None

        # Try each exhibit in priority order
        for exhibit in exhibits[:3]:  # Check top 3 exhibits
            print(f"   📄 Checking {exhibit['type']}: {exhibit['text']}")

            # Fetch exhibit content
            exhibit_html = self.fetcher.fetch_document(exhibit['url'])
            if not exhibit_html:
                continue

            soup = BeautifulSoup(exhibit_html, 'html.parser')
            text = soup.get_text()

            # Check if PIPE is mentioned
            if not self._has_pipe_mentions(text):
                print(f"      ℹ️  No PIPE mentions found")
                continue

            print(f"      🔍 PIPE mentioned, extracting with AI...")

            # Extract relevant section (around PIPE mentions)
            pipe_section = self._extract_pipe_section(text)

            # Use AI to extract structured data
            pipe_data = await self._ai_extract_pipe(pipe_section, ticker)

            if pipe_data and pipe_data.get('has_pipe'):
                return pipe_data

        return None

    def _has_pipe_mentions(self, text: str) -> bool:
        """Check if text mentions PIPE financing"""
        text_lower = text.lower()
        pipe_keywords = [
            'pipe',
            'private investment in public equity',
            'pipe financing',
            'pipe investors',
            'subscription agreement',
            'committed financing'
        ]
        return any(keyword in text_lower for keyword in pipe_keywords)

    def _extract_pipe_section(self, text: str, max_length: int = 8000) -> str:
        """Extract section around PIPE mentions"""
        text_lower = text.lower()

        # Find PIPE mention location
        pipe_keywords = ['pipe financing', 'private investment in public equity', 'pipe investors']
        best_start = 0
        for keyword in pipe_keywords:
            pos = text_lower.find(keyword)
            if pos != -1:
                # Get 3000 chars before and 5000 chars after
                best_start = max(0, pos - 3000)
                break

        if best_start == 0:
            # Fallback: search for "subscription agreement"
            pos = text_lower.find('subscription agreement')
            if pos != -1:
                best_start = max(0, pos - 2000)

        return text[best_start:best_start + max_length]

    async def _ai_extract_pipe(self, text: str, ticker: str) -> Optional[Dict]:
        """Use AI to extract structured PIPE data"""

        prompt = f"""Extract PIPE financing data from this SPAC deal document.

SPAC Ticker: {ticker}

CRITICAL: Extract TOTAL institutional PIPE amount, NOT sponsor PIPE:
- Look for "PIPE Investment", "Subscription Agreement", "Private Placement"
- Focus on third-party investors (institutions, funds, individuals)
- IGNORE sponsor PIPE / sponsor contributions
- If document lists multiple PIPE tranches, SUM them for total

IMPORTANT: Return ONLY numeric values (NO formatted strings like "275M" or "$10.00"):
- pipe_size: Raw number in millions (e.g., 275 not "275M")
- pipe_price: Raw number (e.g., 10 not "$10.00")

Return valid JSON with these fields:
{{
  "has_pipe": true/false,
  "pipe_size": <number in millions, e.g., 275>,
  "pipe_price": <number, e.g., 10.00>,
  "pipe_percentage": <number 0-100, e.g., 15.5>,
  "pipe_lockup_months": <number, e.g., 6>,
  "pipe_investors": ["Investor1", "Investor2"],
  "confidence": 0-100,
  "reasoning": "Brief explanation"
}}

Examples of CORRECT format:
{{
  "pipe_size": 275,     ← CORRECT (not "275M")
  "pipe_price": 10.00,  ← CORRECT (not "$10.00")
  "pipe_percentage": 15.5
}}

If no PIPE found, return:
{{
  "has_pipe": false,
  "confidence": 100,
  "reasoning": "No PIPE financing mentioned"
}}

Document excerpt:
{text[:6000]}
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1000
            )

            response_text = response.choices[0].message.content.strip()

            # Try to extract JSON from response (AI sometimes adds extra text)
            if not response_text.startswith('{'):
                # Find first { and last }
                start = response_text.find('{')
                end = response_text.rfind('}')
                if start != -1 and end != -1:
                    response_text = response_text[start:end+1]

            result = json.loads(response_text)

            # Apply number parsing to sanitize AI output
            numeric_fields = ['pipe_size', 'pipe_price', 'pipe_percentage', 'pipe_lockup_months']
            result = sanitize_ai_response(result, numeric_fields)

            print(f"      ✅ AI extracted: has_pipe={result.get('has_pipe')}, size=${result.get('pipe_size')}M, price=${result.get('pipe_price')}")
            return result

        except json.JSONDecodeError as e:
            print(f"      ❌ AI returned invalid JSON: {e}")
            print(f"      Response preview: {response_text[:200] if 'response_text' in locals() else 'N/A'}")
            return None
        except Exception as e:
            print(f"      ❌ AI extraction failed: {e}")
            return None

    def _update_database(self, ticker: str, pipe_data: Dict) -> bool:
        """Update SPAC record with PIPE data"""
        try:
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                print(f"   ⚠️  SPAC {ticker} not found in database")
                return False

            # Update PIPE fields
            spac.has_pipe = pipe_data.get('has_pipe', False)

            if pipe_data.get('pipe_size'):
                spac.pipe_size = pipe_data['pipe_size']
            if pipe_data.get('pipe_price'):
                spac.pipe_price = pipe_data['pipe_price']
            if pipe_data.get('pipe_percentage'):
                spac.pipe_percentage = pipe_data['pipe_percentage']
            if pipe_data.get('pipe_lockup_months'):
                spac.pipe_lockup_months = pipe_data['pipe_lockup_months']

            self.db.commit()
            return True

        except Exception as e:
            print(f"   ❌ Database update error: {e}")
            self.db.rollback()
            return False


async def main():
    """Test PIPE extractor on recent 8-Ks"""
    import asyncio
    from utils.sec_filing_fetcher import SECFilingFetcher

    fetcher = SECFilingFetcher()
    extractor = PIPEExtractorAgent()

    try:
        # Get recent 8-Ks for announced deals
        db = SessionLocal()
        spacs = db.query(SPAC).filter(
            SPAC.deal_status == 'ANNOUNCED',
            SPAC.announced_date.isnot(None)
        ).order_by(SPAC.announced_date.desc()).limit(5).all()
        db.close()

        print(f"🔍 Testing PIPE extraction on {len(spacs)} recent deals...")
        print("=" * 80)

        for spac in spacs:
            print(f"\n{spac.ticker} → {spac.target}")

            if not spac.cik:
                print(f"   ⚠️  No CIK found")
                continue

            # Get 8-Ks around announcement date
            after_date = spac.announced_date - timedelta(days=7) if spac.announced_date else datetime.now() - timedelta(days=30)
            filings = fetcher.get_8ks_after_date(
                cik=spac.cik,
                after_date=after_date,
                count=5
            )

            if not filings:
                print(f"   ⚠️  No 8-Ks found")
                continue

            # Process each 8-K
            for filing in filings[:3]:  # Check last 3 8-Ks
                result = await extractor.process_filing(filing, spac.ticker)
                if result and result.get('success'):
                    break

    finally:
        extractor.close()


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
