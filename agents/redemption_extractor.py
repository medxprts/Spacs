#!/usr/bin/env python3
"""
Redemption Extractor - Universal redemption data extraction from SEC filings

Handles:
- 8-K Item 5.07 (vote results + redemptions)
- 8-K Item 8.01 (extension redemptions)
- DEFM14A/DEFR14A/PREM14A (merger proxy redemptions)
- 10-Q/10-K (subsequent events redemption notes)

Routes extracted data to redemption_tracker for proper database updates
"""

import os
import sys
import json
from datetime import datetime, date
from typing import Dict, Optional

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from database import SessionLocal, SPAC
from utils.redemption_tracker import add_redemption_event, mark_no_redemptions_found
from dotenv import load_dotenv

load_dotenv()

# DeepSeek AI for extraction
from openai import OpenAI

AI_CLIENT = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


class RedemptionExtractor(BaseAgent):
    """
    Universal redemption extractor for all filing types

    Workflow:
    1. Identify filing type
    2. Extract redemption data with AI
    3. Call redemption_tracker to update database
    4. Log results
    """

    def __init__(self, name: str = 'redemption_extractor'):
        super().__init__(name)
        self.db = SessionLocal()

    async def can_process(self, filing: Dict) -> bool:
        """Check if this filing type can contain redemption data"""
        filing_type = filing.get('type', '').upper().strip()
        return any([
            filing_type == '8-K',
            '14A' in filing_type,  # All proxy types
            filing_type in ['10-Q', '10-K'],
            filing_type == '8-K/A'
        ])

    async def process(self, filing: Dict) -> Optional[Dict]:
        """Route to appropriate extractor based on filing type"""
        filing_type = filing.get('type', '').upper().strip()

        if filing_type in ['8-K', '8-K/A']:
            return await self.extract_8k_redemptions(filing)
        elif filing_type in ['DEFM14A', 'DEFR14A', 'PREM14A', 'DEF 14A']:
            return await self.extract_proxy_redemptions(filing)
        elif filing_type in ['10-Q', '10-K', '10-Q/A', '10-K/A']:
            return await self.extract_quarterly_redemptions(filing)
        else:
            print(f"   ⚠️  Unknown filing type for redemption extraction: {filing_type}")
            return None

    # ========================================================================
    # 8-K REDEMPTION EXTRACTION
    # ========================================================================

    async def extract_8k_redemptions(self, filing: Dict) -> Optional[Dict]:
        """
        Extract redemptions from 8-K filing

        Handles:
        - Item 5.07: Shareholder vote results (MOST COMMON)
        - Item 8.01: Other events (extensions, updates)
        - Item 2.01: Merger completion
        """
        ticker = filing.get('ticker')
        filing_url = filing.get('url')
        filing_date_str = filing.get('date')

        print(f"\n🔍 {ticker} - Extracting redemptions from 8-K...")

        # Get filing content
        content = filing.get('content')
        if not content:
            print(f"   ❌ No filing content available")
            return None

        # Extract with AI
        redemption_data = await self._extract_8k_redemptions_with_ai(content, ticker)

        if not redemption_data or not redemption_data.get('redemptions_checked'):
            print(f"   ⚠️  Could not check for redemptions")
            return None

        # Convert filing date string to date object
        try:
            if isinstance(filing_date_str, str):
                filing_date = datetime.strptime(filing_date_str, '%Y-%m-%d').date()
            else:
                filing_date = filing_date_str
        except:
            filing_date = date.today()

        # Update database via redemption tracker
        if redemption_data.get('redemptions_found') and redemption_data.get('shares_redeemed', 0) > 0:
            # Redemptions occurred
            add_redemption_event(
                db_session=self.db,
                ticker=ticker,
                shares_redeemed=redemption_data['shares_redeemed'],
                redemption_amount=redemption_data.get('redemption_amount', 0.0),
                filing_date=filing_date,
                source='8-K',
                reason=f"Redemptions from 8-K {redemption_data.get('item_number', 'unknown item')}"
            )

            print(f"   ✅ Recorded {redemption_data['shares_redeemed']:,} shares redeemed")
            return {'success': True, 'shares_redeemed': redemption_data['shares_redeemed']}

        else:
            # No redemptions found (explicitly marked)
            mark_no_redemptions_found(
                db_session=self.db,
                ticker=ticker,
                source='8-K',
                filing_date=filing_date,
                reason=f"Checked 8-K {redemption_data.get('item_number', '')}, no redemptions"
            )

            print(f"   ✅ Confirmed zero redemptions")
            return {'success': True, 'shares_redeemed': 0}

    async def _extract_8k_redemptions_with_ai(self, content: str, ticker: str) -> Optional[Dict]:
        """Use AI to extract redemption data from 8-K"""

        prompt = f"""
Extract redemption data from this 8-K filing for {ticker}:

CRITICAL: Look for redemptions FIRST (most important!):
- "X shares were redeemed" or "X shares exercised redemption rights"
- "shareholders holding X shares elected to redeem"
- "redemption of X shares" or "X shares subject to redemption"
- "no redemptions" or "zero redemptions" or "no shareholders elected to redeem"

Also identify:
- Item number (5.07 for votes, 8.01 for extensions, 2.01 for completions)
- Total shares outstanding before redemptions (if mentioned)
- Redemption price (if mentioned)

IMPORTANT: Set redemptions_checked=true even if zero redemptions!

Return JSON:
{{
  "redemptions_checked": true/false,
  "redemptions_found": true/false,
  "item_number": "5.07",
  "shares_redeemed": <number or 0>,
  "redemption_amount": <dollars or 0>,
  "redemption_price": <price per share>,
  "shares_outstanding_before": <number>,
  "reason": "Brief description of context"
}}

Filing content (first 15000 chars):
{content[:15000]}
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an SEC filing expert specializing in SPAC redemption data extraction. Be thorough and accurate."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )

            data = json.loads(response.choices[0].message.content)

            print(f"   🤖 AI extraction:")
            print(f"      Checked: {data.get('redemptions_checked')}")
            print(f"      Found: {data.get('redemptions_found')}")
            if data.get('shares_redeemed'):
                print(f"      Shares: {data['shares_redeemed']:,}")

            return data

        except Exception as e:
            print(f"   ❌ AI extraction failed: {e}")
            return None

    # ========================================================================
    # PROXY REDEMPTION EXTRACTION (DEFM14A, DEFR14A, PREM14A)
    # ========================================================================

    async def extract_proxy_redemptions(self, filing: Dict) -> Optional[Dict]:
        """
        Extract redemptions from merger proxy

        Notes:
        - DEFM14A: Definitive proxy (filed before vote)
        - DEFR14A: Revised proxy (updated redemption numbers)
        - PREM14A: Preliminary proxy (early estimates)

        May contain:
        - Actual redemptions (if revised proxy or post-vote)
        - Estimated redemptions (pro forma scenarios)
        - Redemption mechanics and deadline
        """
        ticker = filing.get('ticker')
        filing_type = filing.get('type')
        filing_date_str = filing.get('date')

        print(f"\n📋 {ticker} - Extracting redemptions from {filing_type}...")

        # Get filing content
        content = filing.get('content')
        if not content:
            print(f"   ❌ No filing content available")
            return None

        # Extract with AI
        redemption_data = await self._extract_proxy_redemptions_with_ai(content, ticker, filing_type)

        if not redemption_data or not redemption_data.get('redemptions_checked'):
            print(f"   ⚠️  Could not check for redemptions")
            return None

        # Convert filing date
        try:
            if isinstance(filing_date_str, str):
                filing_date = datetime.strptime(filing_date_str, '%Y-%m-%d').date()
            else:
                filing_date = filing_date_str
        except:
            filing_date = date.today()

        # Only record ACTUAL redemptions, not estimates
        if redemption_data.get('is_actual') and not redemption_data.get('is_estimate'):
            if redemption_data.get('redemptions_found') and redemption_data.get('shares_redeemed', 0) > 0:
                # Actual redemptions disclosed
                add_redemption_event(
                    db_session=self.db,
                    ticker=ticker,
                    shares_redeemed=redemption_data['shares_redeemed'],
                    redemption_amount=redemption_data.get('redemption_amount', 0.0),
                    filing_date=filing_date,
                    source=filing_type,
                    reason=f"Redemptions from {filing_type} (actual, not estimate)"
                )

                print(f"   ✅ Recorded {redemption_data['shares_redeemed']:,} actual shares redeemed")
                return {'success': True, 'shares_redeemed': redemption_data['shares_redeemed']}

            else:
                # Proxy explicitly states no redemptions
                mark_no_redemptions_found(
                    db_session=self.db,
                    ticker=ticker,
                    source=filing_type,
                    filing_date=filing_date,
                    reason=f"Checked {filing_type}, no actual redemptions"
                )

                print(f"   ✅ Confirmed zero redemptions")
                return {'success': True, 'shares_redeemed': 0}

        else:
            # Only estimates available, don't record
            print(f"   ℹ️  Only estimated redemptions found, not recording")
            print(f"      Estimates: {redemption_data.get('estimated_scenarios', [])}")
            return {'success': True, 'shares_redeemed': 0, 'has_estimates': True}

    async def _extract_proxy_redemptions_with_ai(self, content: str, ticker: str, filing_type: str) -> Optional[Dict]:
        """Use AI to extract redemption data from proxy"""

        prompt = f"""
Extract redemption data from this {filing_type} proxy for {ticker}:

CRITICAL DISTINCTION - ACTUAL vs ESTIMATED:
1. ACTUAL redemptions (what we want!):
   - "As of [date], shareholders holding X shares have redeemed"
   - "X shares were redeemed prior to the vote"
   - "redemption requests totaling X shares"

2. ESTIMATED redemptions (pro forma scenarios - DON'T record):
   - "Assuming 0%, 25%, 50% redemptions..."
   - "If X% of shareholders redeem..."
   - "Pro forma scenarios"

Also look for:
- Redemption deadline date
- Minimum cash condition
- "no redemptions" or "minimal redemptions"

IMPORTANT:
- Set is_actual=true ONLY if actual redemptions disclosed
- Set is_estimate=true if only pro forma scenarios
- Set redemptions_checked=true always

Return JSON:
{{
  "redemptions_checked": true/false,
  "redemptions_found": true/false,
  "is_actual": true/false,
  "is_estimate": true/false,
  "shares_redeemed": <number or 0>,
  "redemption_amount": <dollars or 0>,
  "redemption_deadline": "YYYY-MM-DD",
  "estimated_scenarios": [0, 25, 50],
  "minimum_cash_condition": <dollars>,
  "reason": "Brief description"
}}

Filing content (first 20000 chars):
{content[:20000]}
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an SEC filing expert. Distinguish carefully between ACTUAL redemptions and ESTIMATED scenarios."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )

            data = json.loads(response.choices[0].message.content)

            print(f"   🤖 AI extraction:")
            print(f"      Checked: {data.get('redemptions_checked')}")
            print(f"      Found: {data.get('redemptions_found')}")
            print(f"      Actual: {data.get('is_actual')}, Estimate: {data.get('is_estimate')}")
            if data.get('shares_redeemed'):
                print(f"      Shares: {data['shares_redeemed']:,}")

            return data

        except Exception as e:
            print(f"   ❌ AI extraction failed: {e}")
            return None

    # ========================================================================
    # QUARTERLY REPORT REDEMPTION EXTRACTION (10-Q, 10-K)
    # ========================================================================

    async def extract_quarterly_redemptions(self, filing: Dict) -> Optional[Dict]:
        """
        Extract redemptions from 10-Q/10-K subsequent events notes

        Example:
        "Note 10: Subsequent Events
         On November 15, 2025, shareholders holding 5,000,000 shares
         exercised redemption rights at $10.10 per share."
        """
        ticker = filing.get('ticker')
        filing_type = filing.get('type')
        filing_date_str = filing.get('date')

        print(f"\n📊 {ticker} - Checking {filing_type} for redemption notes...")

        # Get filing content
        content = filing.get('content')
        if not content:
            print(f"   ❌ No filing content available")
            return None

        # Extract with AI (focus on subsequent events section)
        redemption_data = await self._extract_quarterly_redemptions_with_ai(content, ticker, filing_type)

        if not redemption_data or not redemption_data.get('redemptions_checked'):
            print(f"   ℹ️  No redemption notes found in subsequent events")
            return None

        # Convert filing date
        try:
            if isinstance(filing_date_str, str):
                filing_date = datetime.strptime(filing_date_str, '%Y-%m-%d').date()
            else:
                filing_date = filing_date_str
        except:
            filing_date = date.today()

        # Record if found
        if redemption_data.get('redemptions_found') and redemption_data.get('shares_redeemed', 0) > 0:
            add_redemption_event(
                db_session=self.db,
                ticker=ticker,
                shares_redeemed=redemption_data['shares_redeemed'],
                redemption_amount=redemption_data.get('redemption_amount', 0.0),
                filing_date=redemption_data.get('redemption_date_actual', filing_date),
                source=filing_type,
                reason=f"Post-quarter redemption disclosed in {filing_type} subsequent events"
            )

            print(f"   ✅ Recorded {redemption_data['shares_redeemed']:,} shares from subsequent events")
            return {'success': True, 'shares_redeemed': redemption_data['shares_redeemed']}

        return {'success': True, 'shares_redeemed': 0}

    async def _extract_quarterly_redemptions_with_ai(self, content: str, ticker: str, filing_type: str) -> Optional[Dict]:
        """Use AI to extract redemption data from 10-Q/10-K notes"""

        prompt = f"""
Extract redemption data from this {filing_type} for {ticker}:

FOCUS ON: "Subsequent Events" or "Note X: Subsequent Events" section

Look for:
- Post-quarter redemptions: "On [date], shareholders holding X shares redeemed..."
- Extension redemptions: "In connection with the extension, X shares were redeemed"
- "no redemptions occurred" or "no redemptions after quarter end"

Return JSON:
{{
  "redemptions_checked": true/false,
  "redemptions_found": true/false,
  "shares_redeemed": <number or 0>,
  "redemption_amount": <dollars or 0>,
  "redemption_date_actual": "YYYY-MM-DD",
  "reason": "Brief description"
}}

Filing content (searching for subsequent events):
{content[:25000]}
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an SEC filing expert. Focus on subsequent events sections for post-quarter redemptions."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )

            data = json.loads(response.choices[0].message.content)

            if data.get('redemptions_found'):
                print(f"   🤖 Found redemption in subsequent events: {data.get('shares_redeemed', 0):,} shares")

            return data

        except Exception as e:
            print(f"   ❌ AI extraction failed: {e}")
            return None

    def __del__(self):
        """Cleanup database connection"""
        if hasattr(self, 'db'):
            self.db.close()


if __name__ == "__main__":
    """Test the redemption extractor"""
    import asyncio

    print("="*70)
    print("REDEMPTION EXTRACTOR TEST")
    print("="*70)

    # Test 8-K extraction
    test_filing = {
        'ticker': 'CEP',
        'type': '8-K',
        'date': '2025-11-01',
        'url': 'https://www.sec.gov/...',
        'content': """
        Item 5.07. Submission of Matters to a Vote of Security Holders

        On November 1, 2025, the Company held a special meeting of shareholders.
        As of the record date, 50,000,000 shares were outstanding.

        Shareholders holding 5,000,000 shares exercised their redemption rights
        at a price of $10.10 per share, for a total redemption amount of
        $50,500,000.

        Following the redemptions, 45,000,000 shares remain outstanding.
        """
    }

    extractor = RedemptionExtractor()
    result = asyncio.run(extractor.extract_8k_redemptions(test_filing))

    print(f"\n{'='*70}")
    print(f"TEST RESULT: {result}")
    print(f"{'='*70}")
