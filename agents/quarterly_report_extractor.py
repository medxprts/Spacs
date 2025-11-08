#!/usr/bin/env python3
"""
Quarterly Report Extractor - Extract extensions, redemptions, trust data from 10-Q/10-K

Per user guidance:
1. "Latest 10-Q or 10-K, depending on whichever is latest" (Q4 is 10-K, not 10-Q)
2. "Check 8-Ks filed after the quarterly report" (may have more recent updates)
3. "Always extract relevant sections" (selective extraction, not entire document)

Extracts:
- Extensions (from "Subsequent Events" notes)
- Redemptions (from stockholders' equity notes)
- Trust balances (from trust account disclosures)
- Deal status updates (completed/liquidated indicators)

Uses SECFilingFetcher for all API calls (consolidation strategy).
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

import re
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

from utils.sec_filing_fetcher import SECFilingFetcher
from database import SessionLocal, SPAC
from utils.trust_account_tracker import update_trust_cash, update_shares_outstanding

# DeepSeek AI for extraction fallback
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


class QuarterlyReportExtractor:
    """
    Extract extensions, redemptions, and trust data from 10-Q/10-K filings

    Strategy (per user guidance):
    1. Get latest 10-Q or 10-K (whichever is most recent)
    2. Extract baseline data from quarterly report
    3. Check for 8-Ks filed after the quarterly report
    4. If 8-K has newer data, use that
    5. Use selective section extraction (not entire document)
    """

    def __init__(self):
        self.sec_fetcher = SECFilingFetcher()

    async def can_process(self, filing: Dict) -> bool:
        """Check if this agent can process the filing"""
        return filing['type'] in ['10-Q', '10-K', '10-Q/A', '10-K/A']

    async def process_filing(self, filing: Dict, ticker: str) -> Dict:
        """
        Process a 10-Q or 10-K filing

        Args:
            filing: Filing metadata dict from SECFilingFetcher
            ticker: SPAC ticker

        Returns:
            Dict with extraction results
        """
        print(f"\n📊 {ticker} - Processing {filing['type']} filed {filing['date'].strftime('%Y-%m-%d')}")

        # Extract actual document URL from index page
        doc_url = self.sec_fetcher.extract_document_url(filing['url'])
        if not doc_url:
            print(f"   ⚠️  Could not extract document URL from index page")
            return {'success': False, 'error': 'Could not extract document URL'}

        print(f"   ✓ Document URL: {doc_url[:80]}...")

        # Fetch document
        doc_content = self.sec_fetcher.fetch_document(doc_url)
        if not doc_content:
            return {'success': False, 'error': 'Failed to fetch document'}

        # Extract relevant sections
        sections = self._extract_relevant_sections(doc_content)

        if not sections:
            return {'success': False, 'error': 'No relevant sections found'}

        # Extract extension data
        extension_data = self._extract_extension_info(sections, ticker)

        # Extract redemption data
        redemption_data = self._extract_redemption_info(sections, ticker)

        # Extract trust balance
        trust_data = self._extract_trust_balance(sections, ticker)

        # Check for deal completion/liquidation indicators
        status_data = self._check_deal_status(sections, ticker)

        # Combine all extractions
        result = {
            'success': True,
            'filing_type': filing['type'],
            'filing_date': filing['date'],
            **extension_data,
            **redemption_data,
            **trust_data,
            **status_data
        }

        # AUTOMATIC REDEMPTION BACKFILL
        # If we detected a share count drop but no redemption disclosure, search 8-Ks
        if result.get('shares_outstanding') and not result.get('shares_redeemed'):
            backfill_redemptions = await self._check_for_share_count_drop(
                ticker=ticker,
                current_shares=result['shares_outstanding'],
                filing_date=filing['date']
            )
            if backfill_redemptions:
                result.update(backfill_redemptions)

        # Update database
        self._update_database(ticker, result)

        return result

    async def check_for_updates(self, cik: str, ticker: str) -> Dict:
        """
        Check for extension/redemption updates using user's strategy:
        1. Get latest 10-Q or 10-K (baseline)
        2. Check 8-Ks filed after that date
        3. Use whichever has most recent data

        Args:
            cik: Company CIK
            ticker: SPAC ticker

        Returns:
            Dict with update results
        """
        print(f"\n🔍 {ticker} - Checking for quarterly report updates")

        # Step 1: Get latest 10-Q or 10-K (whichever is most recent)
        print(f"   Step 1: Getting latest quarterly/annual report...")
        latest_report = self.sec_fetcher.get_latest_10q_or_10k(cik=cik)

        if not latest_report:
            return {'success': False, 'error': 'No quarterly reports found'}

        print(f"   ✓ Latest report: {latest_report['type']} filed {latest_report['date'].strftime('%Y-%m-%d')}")

        # Step 2: Extract data from quarterly report (baseline)
        print(f"   Step 2: Extracting baseline data from {latest_report['type']}...")
        baseline_data = await self.process_filing(latest_report, ticker)

        # Step 3: Check for 8-Ks filed after the quarterly report
        print(f"   Step 3: Checking for 8-Ks filed after {latest_report['date'].strftime('%Y-%m-%d')}...")
        recent_8ks = self.sec_fetcher.get_8ks_after_date(
            cik=cik,
            after_date=latest_report['date'],
            count=10
        )

        if recent_8ks:
            print(f"   ✓ Found {len(recent_8ks)} 8-Ks filed after quarterly report")

            # Check each 8-K for extension/redemption info
            for eight_k in recent_8ks:
                print(f"      Checking 8-K filed {eight_k['date'].strftime('%Y-%m-%d')}...")

                # Extract actual document URL from index page (same as 10-Q/10-K handling)
                doc_url = self.sec_fetcher.extract_document_url(eight_k['url'])
                if not doc_url:
                    print(f"         ⚠️  Could not extract document URL")
                    continue

                # Fetch 8-K document
                doc_content = self.sec_fetcher.fetch_document(doc_url)
                if not doc_content:
                    continue

                # Check for extension keywords
                if self._contains_extension_info(doc_content):
                    print(f"      ✓ Extension info found - extracting...")
                    extension_8k_data = self._extract_extension_from_8k(doc_content, ticker)

                    # Update baseline with more recent 8-K data
                    if extension_8k_data:
                        baseline_data.update(extension_8k_data)
                        baseline_data['data_source'] = f"8-K filed {eight_k['date'].strftime('%Y-%m-%d')}"
                        # Update database with new 8-K data
                        self._update_database(ticker, baseline_data)

        else:
            print(f"   ✓ No 8-Ks filed after quarterly report")
            baseline_data['data_source'] = f"{latest_report['type']} filed {latest_report['date'].strftime('%Y-%m-%d')}"

        return baseline_data

    def _extract_relevant_sections(self, doc_content: str) -> Dict[str, str]:
        """
        Extract ONLY relevant sections (not entire document)

        Per user guidance: "We should always try to identify relevant sections
        so we dont send the entire 10-q or 10-k to an LLM"

        Relevant sections for extensions/redemptions:
        1. Note on Subsequent Events (extensions announced here)
        2. Note on Commitments and Contingencies (extension deposits)
        3. Note on Stockholders' Equity (redemptions)
        4. Management's Discussion (trust balance updates)

        Returns:
            Dict mapping section names to section text
        """
        sections = {}

        # Use sec_fetcher's intelligent parsing (auto-detects XML vs HTML, suppresses warnings)
        # This handles both traditional HTML and iXBRL formats correctly
        text = self.sec_fetcher.extract_text(doc_content)

        # Store full clean text for robust pattern matching
        sections['full_clean_text'] = text

        # Section 1: Cover Page / Summary (first 5,000 chars)
        sections['cover_page'] = text[:5000]

        # Section 2: Balance Sheet (CRITICAL - trust cash, shares outstanding)
        balance_sheet = self._extract_section(
            text,
            start_markers=[
                'CONSOLIDATED BALANCE SHEET',
                'CONDENSED BALANCE SHEET',
                'BALANCE SHEET',
                'CONDENSED CONSOLIDATED BALANCE',
                'STATEMENT OF FINANCIAL POSITION'
            ],
            max_length=15000
        )
        if balance_sheet:
            sections['balance_sheet'] = balance_sheet

        # Section 3: Trust Account Note (NAV, trust value details)
        trust_note = self._extract_section(
            text,
            start_markers=[
                'NOTE',
                'TRUST ACCOUNT',
                'MARKETABLE SECURITIES HELD IN TRUST',
                'INVESTMENTS HELD IN TRUST',
                'CASH AND INVESTMENTS HELD IN TRUST'
            ],
            max_length=8000
        )
        if trust_note:
            sections['trust_note'] = trust_note

        # Section 4: Equity Statement (CRITICAL - redemptions, shares outstanding)
        # Updated markers based on testing (many SPACs use "Deficit" instead of "Equity")
        equity = self._extract_section(
            text,
            start_markers=[
                'STATEMENTS OF CHANGES IN SHAREHOLDERS',
                'STATEMENTS OF CHANGES IN STOCKHOLDERS',
                'STATEMENT OF CHANGES IN SHAREHOLDERS',
                'STATEMENT OF CHANGES IN STOCKHOLDERS',
                'CHANGES IN SHAREHOLDERS\' DEFICIT',
                'CHANGES IN STOCKHOLDERS\' EQUITY',
                'CONDENSED STATEMENTS OF CHANGES'
            ],
            max_length=12000
        )
        if equity:
            sections['equity_statement'] = equity

        # Section 5: Subsequent Events (extensions, deal announcements)
        subsequent_events = self._extract_section(
            text,
            start_markers=[
                'NOTE',
                'SUBSEQUENT EVENTS',
                'EVENTS AFTER',
                'POST-BALANCE SHEET EVENTS',
                'EVENTS OCCURRING AFTER'
            ],
            max_length=15000
        )
        if subsequent_events:
            sections['subsequent_events'] = subsequent_events

        # Section 6: Business Combination Note (deal announcements, PIPE, earnouts)
        business_combination = self._extract_section(
            text,
            start_markers=[
                'NOTE',
                'BUSINESS COMBINATION',
                'PROPOSED BUSINESS COMBINATION',
                'MERGER AGREEMENT',
                'DEFINITIVE AGREEMENT'
            ],
            max_length=12000
        )
        if business_combination:
            sections['business_combination'] = business_combination

        # Section 7: Shareholders' Equity Note (warrant terms, unit structure)
        equity_note = self._extract_section(
            text,
            start_markers=[
                'NOTE',
                'SHAREHOLDERS\' EQUITY',
                'STOCKHOLDERS\' EQUITY',
                'CLASS A ORDINARY SHARES',
                'ORDINARY SHARES'
            ],
            max_length=15000
        )
        if equity_note:
            sections['equity_note'] = equity_note

        # Section 8: Management's Discussion (MD&A - liquidity, trust balance commentary)
        mda = self._extract_section(
            text,
            start_markers=[
                'MANAGEMENT\'S DISCUSSION AND ANALYSIS',
                'MD&A',
                'LIQUIDITY AND CAPITAL RESOURCES',
                'RESULTS OF OPERATIONS'
            ],
            max_length=10000
        )
        if mda:
            sections['mda'] = mda

        # Section 9: Commitments and Contingencies (extension deposits)
        commitments = self._extract_section(
            text,
            start_markers=[
                'NOTE',
                'COMMITMENTS AND CONTINGENCIES',
                'COMMITMENTS',
                'CONTINGENCIES'
            ],
            max_length=10000
        )
        if commitments:
            sections['commitments'] = commitments

        return sections

    def _extract_section(self, text: str, start_markers: List[str], max_length: int = 15000) -> Optional[str]:
        """
        Extract a specific section from document text

        Args:
            text: Full document text
            start_markers: List of possible section start markers
            max_length: Maximum length of extracted section

        Returns:
            Section text or None if not found
        """
        text_upper = text.upper()

        for marker in start_markers:
            marker_upper = marker.upper()

            # Find marker position
            pos = text_upper.find(marker_upper)

            if pos != -1:
                # Extract from marker onwards
                section_text = text[pos:pos + max_length]
                return section_text

        return None

    def _extract_extension_info(self, sections: Dict[str, str], ticker: str) -> Dict:
        """
        Extract extension information from sections

        Looks for:
        - Extension dates
        - Number of extensions approved
        - Extension deposits (sponsor contributions)
        - Shareholder vote requirements

        Strategy:
        1. Search FULL clean text first (most robust - catches everything)
        2. Fall back to specific sections if needed

        Returns:
            Dict with keys: deadline_date, is_extended, extension_count, extension_deposit
        """
        result = {}

        # Strategy 1: Search FULL CLEAN TEXT first (most robust)
        # This catches extensions even if section extraction boundaries are off
        if 'full_clean_text' in sections:
            extension_data = self._parse_extension_text(sections['full_clean_text'], ticker)
            if extension_data:
                result.update(extension_data)
                return result  # Found in full text, no need to check sections

        # Strategy 2: Check Subsequent Events section (if full text search failed)
        if 'subsequent_events' in sections:
            extension_data = self._parse_extension_text(sections['subsequent_events'], ticker)
            if extension_data:
                result.update(extension_data)

        # Strategy 3: Check Commitments section (if still not found)
        if 'commitments' in sections and not result:
            extension_data = self._parse_extension_text(sections['commitments'], ticker)
            if extension_data:
                result.update(extension_data)

        return result

    def _parse_extension_text(self, text: str, ticker: str) -> Optional[Dict]:
        """
        Parse extension information from text using regex + AI fallback

        Patterns to look for:
        - "extended the deadline to [DATE]"
        - "approved extensions... up to [NUMBER] times"
        - "deposited $[AMOUNT] into trust"
        - "stockholders approved"
        """
        result = {}

        # Pattern 1: Extended deadline date
        # Made more robust to handle various phrasings
        deadline_patterns = [
            # "extended to October 17, 2025"
            r'extended?(?:[^.]{0,50})(?:to|until)\s+(\w+\s+\d{1,2},\s*20\d{2})',
            # "deadline to October 17, 2025"
            r'deadline(?:[^.]{0,50})(?:to|until|of)\s+(\w+\s+\d{1,2},\s*20\d{2})',
            # "business combination to October 17, 2025"
            r'business combination(?:[^.]{0,100})(?:by|to|until)\s+(\w+\s+\d{1,2},\s*20\d{2})',
            # "consummate a business combination to October 17, 2025"
            r'consummate\s+(?:a|its|the)\s+business combination(?:[^.]{0,50})(?:to|by|until)\s+(\w+\s+\d{1,2},\s*20\d{2})',
            # "complete initial business combination by October 17, 2025"
            r'complete(?:[^.]{0,50})business combination(?:[^.]{0,50})(?:by|to|until)\s+(\w+\s+\d{1,2},\s*20\d{2})',
            # More general: any sentence with "extension" and a future date
            r'extension(?:[^.]{0,100})(\w+\s+\d{1,2},\s*20\d{2})',
        ]

        # Track all found dates to pick the most recent/relevant one
        found_dates = []

        for pattern in deadline_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                date_str = match.group(1)
                try:
                    from dateutil import parser
                    deadline = parser.parse(date_str)

                    # Basic validation: date should be between 2020 and 2030
                    # (extensions for SPACs are in this range)
                    if 2020 <= deadline.year <= 2030:
                        found_dates.append(deadline)
                except:
                    pass

        # Pick the most recent (latest) deadline date found
        # This is usually the current/active extension deadline
        if found_dates:
            latest_deadline = max(found_dates)
            result['deadline_date'] = latest_deadline
            result['is_extended'] = True
            print(f"      ✓ Extension deadline: {latest_deadline.strftime('%Y-%m-%d')}")
            print(f"         (found {len(found_dates)} dates, using latest)")

        # Pattern 2: Number of extensions
        extension_count_patterns = [
            r'up to\s+(\d+|twenty-one|twenty-four|twelve)\s+(?:monthly\s+)?extensions?',
            r'approved\s+(?:to\s+extend\s+)?(?:.*?)(\d+)\s+times?',
            r'(\d+)\s+(?:month|one-month)\s+extensions?',
        ]

        for pattern in extension_count_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                count_str = match.group(1)
                # Convert written numbers
                number_map = {'twelve': 12, 'twenty-one': 21, 'twenty-four': 24}
                count = number_map.get(count_str.lower(), int(count_str) if count_str.isdigit() else 0)

                if count > 0:
                    result['extension_count'] = count
                    print(f"      ✓ Extensions approved: {count}")
                    break

        # Pattern 3: Extension deposits
        deposit_patterns = [
            r'deposited?\s+\$?([\d,]+(?:\.\d{2})?)\s+(?:million\s+)?(?:into|to)\s+(?:the\s+)?trust',
            r'sponsor.*?contribut(?:ed|ion)\s+\$?([\d,]+(?:\.\d{2})?)\s+(?:million)?',
        ]

        for pattern in deposit_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(',', '')
                try:
                    amount = float(amount_str)
                    # Check if amount is in millions
                    if 'million' in text[match.start():match.end() + 20].lower():
                        amount *= 1_000_000

                    result['extension_deposit'] = amount
                    print(f"      ✓ Extension deposit: ${amount:,.0f}")
                    break
                except:
                    pass

        # If no regex matches and AI available, use AI extraction
        if not result and AI_AVAILABLE:
            result = self._extract_extension_with_ai(text, ticker)

        return result if result else None

    def _extract_redemption_info(self, sections: Dict[str, str], ticker: str) -> Dict:
        """
        Extract redemption information using AI

        AI-based extraction is more reliable than regex because:
        - Handles narrative disclosures ("stockholders elected to redeem...")
        - Understands context (redemption events vs extension redemptions)
        - Can infer redemptions from share count changes
        - Validates extracted numbers for reasonableness
        """
        if not AI_AVAILABLE:
            print(f"      ⚠️  AI not available, skipping redemption extraction")
            return {}

        # Combine relevant sections
        equity_section = sections.get('equity', '')
        mda = sections.get('mda', '')
        subsequent_events = sections.get('subsequent_events', '')
        full_text = sections.get('full_clean_text', '')

        if not equity_section and not subsequent_events and not full_text:
            print(f"      ⚠️  No relevant sections found for redemption extraction")
            return {}

        return self._extract_redemptions_with_ai(
            equity_section,
            mda,
            subsequent_events,
            full_text[:30000],  # Include full text but limit size
            ticker
        )

    def _extract_redemptions_with_ai(
        self,
        equity_section: str,
        mda: str,
        subsequent_events: str,
        full_text: str,
        ticker: str
    ) -> Dict:
        """Use AI to extract redemption data from filing sections"""

        prompt = f"""You are analyzing a SPAC 10-Q/10-K filing for {ticker} to detect shareholder redemptions.

**CRITICAL INSTRUCTIONS:**

1. **Redemption Events** (HIGHEST PRIORITY):
   - Look for language like:
     * "stockholders elected to redeem"
     * "shares were redeemed"
     * "redemption of X shares"
     * "X shareholders exercised their redemption rights"
   - Extract NUMBER OF SHARES redeemed
   - Extract DOLLAR AMOUNT paid for redemptions (if mentioned)
   - Calculate redemption percentage if possible

2. **Context Understanding**:
   - **Extension Redemptions**: Small redemptions (usually <5%) during extension votes
   - **Merger Redemptions**: Large redemptions (often 30-90%) during business combination votes
   - Both are valid redemptions - extract them

3. **Share Count Changes** (Secondary Indicator):
   - If you see significant decrease in "shares subject to redemption" from prior period:
     * This MAY indicate redemptions occurred
     * Look for narrative disclosure explaining the decrease
     * Only report if explicitly mentioned as redemptions

4. **What NOT to Extract**:
   - DO NOT extract share forfeitures by sponsors
   - DO NOT extract shares "subject to possible redemption" (that's total outstanding)
   - DO NOT guess - only extract explicit redemption disclosures

**OUTPUT FORMAT (JSON):**
{{
    "shares_redeemed": <number of shares redeemed or null>,
    "redemption_amount": <total dollar amount paid or null>,
    "redemption_percentage": <percentage of shares redeemed or null>,
    "redemption_context": "EXTENSION|MERGER|UNKNOWN|null",
    "confidence": "high|medium|low",
    "notes": "brief explanation of where redemption data was found"
}}

**VALIDATION RULES:**
- shares_redeemed should be 6-8 digits (hundreds of thousands to tens of millions)
- redemption_amount should be in millions (7-9 digits)
- redemption_percentage should be 0-100
- If no redemptions found, return all nulls with notes explaining why

**TEXT TO ANALYZE:**

EQUITY SECTION:
{equity_section[:8000]}

MD&A SECTION:
{mda[:5000]}

SUBSEQUENT EVENTS:
{subsequent_events[:5000]}

FULL TEXT SEARCH (for "redemption" keyword):
{full_text[:12000]}

Return JSON only, no explanation."""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=800
            )

            data = json.loads(response.choices[0].message.content)

            result = {}

            # Extract shares redeemed
            if data.get('shares_redeemed'):
                shares = data['shares_redeemed']
                if isinstance(shares, (int, float)) and 1000 < shares < 100_000_000:
                    result['shares_redeemed'] = int(shares)
                    print(f"      ✓ Shares redeemed: {int(shares):,}")
                    print(f"         Context: {data.get('redemption_context', 'UNKNOWN')}")
                    print(f"         Confidence: {data.get('confidence', 'unknown')}")

            # Extract redemption amount
            if data.get('redemption_amount'):
                amount = data['redemption_amount']
                if isinstance(amount, (int, float)) and 10_000 < amount < 10_000_000_000:
                    result['redemption_amount'] = float(amount)
                    print(f"      ✓ Redemption amount: ${float(amount):,.0f}")

            # Extract redemption percentage
            if data.get('redemption_percentage'):
                pct = data['redemption_percentage']
                if isinstance(pct, (int, float)) and 0 < pct <= 100:
                    result['redemption_percentage'] = float(pct)
                    print(f"      ✓ Redemption %: {float(pct):.2f}%")

            # Log AI notes
            if data.get('notes'):
                print(f"      ℹ️  {data['notes'][:150]}")

            return result

        except Exception as e:
            print(f"      ⚠️  AI redemption extraction error: {e}")
            return {}

    def _extract_trust_balance(self, sections: Dict[str, str], ticker: str) -> Dict:
        """
        Extract current trust account balance using AI

        AI-based extraction is more reliable than regex because:
        - Understands balance sheet context (assets vs expenses)
        - Can differentiate between trust balance and transaction costs
        - Handles pre-IPO filings (checks balance sheet date vs IPO date)
        - Validates data before returning
        """
        if not AI_AVAILABLE:
            print(f"      ⚠️  AI not available, skipping trust balance extraction")
            return {}

        # Combine relevant sections for AI
        balance_sheet = sections.get('balance_sheet', '')
        equity_section = sections.get('equity', '')
        trust_note = sections.get('trust_note', '')

        if not balance_sheet and not trust_note:
            print(f"      ⚠️  No balance sheet or trust note sections found")
            return {}

        return self._extract_trust_with_ai(balance_sheet, equity_section, trust_note, ticker)

    def _extract_trust_with_ai(self, balance_sheet: str, equity_section: str, trust_note: str, ticker: str) -> Dict:
        """Extract trust data using AI with detailed prompting"""

        # Combine sections (limit to 25k chars total for efficiency)
        combined_text = f"""
BALANCE SHEET SECTION:
{balance_sheet[:10000]}

EQUITY STATEMENT SECTION:
{equity_section[:10000]}

TRUST ACCOUNT NOTE:
{trust_note[:8000]}
"""

        prompt = f"""You are extracting financial data from a SPAC 10-Q or 10-K filing for ticker {ticker}.

**CRITICAL INSTRUCTIONS:**

1. **Trust Account Balance** (HIGHEST PRIORITY):
   - Look for line items in the BALANCE SHEET (ASSETS section):
     * "Marketable securities held in Trust Account"
     * "Cash and investments held in trust"
     * "Investments held in Trust Account"
   - Extract the BALANCE SHEET ASSET VALUE
   - DO NOT extract:
     * Transaction costs or IPO expenses
     * Underwriting fees or deferred discounts
     * Any expense or liability items
   - IMPORTANT: Check if balance sheet date is BEFORE IPO date
     * If pre-IPO (no trust account established yet), return null

2. **Shares Subject to Redemption** (CRITICAL: Use Current Period):
   - Look for in equity section or balance sheet temporary equity:
     * "Ordinary shares subject to possible redemption"
     * "Class A shares subject to redemption"
   - **MUST extract from MOST RECENT COLUMN (current period)**, NOT prior period
   - If balance sheet has multiple columns (e.g., June 30, 2025 vs Dec 31, 2024):
     * Use the LATEST date (June 30, 2025)
     * Ignore prior period columns (Dec 31, 2024)
   - Extract NUMBER OF SHARES (not dollar value)
   - Usually 7-8 digit numbers (e.g., 11,500,000)

3. **NAV (Net Asset Value Per Share)**:
   - Look for redemption value per share:
     * "redemption value of $X.XX per share"
     * "$X.XX per public share"
   - Typically $10.00 to $10.50
   - Found in equity note or trust account disclosure

**VALIDATION RULES:**
- Trust cash should be in millions (7-9 digits)
- Shares should be in millions (7-8 digits)
- NAV should be around $10.00-$10.50
- If balance sheet date is before IPO, return all nulls
- CRITICAL: If multiple columns exist, ONLY use the MOST RECENT column (current period)
- Ignore "prior period" or "prior year" columns entirely

**FILING TEXT:**
{combined_text}

**OUTPUT FORMAT (JSON):**
{{
    "trust_cash": <integer or null>,
    "shares_outstanding": <integer or null>,
    "nav_per_share": <float or null>,
    "balance_sheet_date": "YYYY-MM-DD or null",
    "confidence": "high|medium|low",
    "notes": "brief explanation of what you found or why data is unavailable"
}}

Return null for values you cannot find confidently. DO NOT guess or extract wrong numbers."""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=500
            )

            import json
            result = json.loads(response.choices[0].message.content)

            # Display results
            if result.get('trust_cash'):
                print(f"      ✓ Trust cash: ${result['trust_cash']:,.0f}")
            if result.get('shares_outstanding'):
                print(f"      ✓ Shares outstanding: {result['shares_outstanding']:,}")
            if result.get('nav_per_share'):
                print(f"      ✓ NAV per share: ${result['nav_per_share']:.2f}")

            if result.get('notes'):
                print(f"      ℹ️  {result['notes']}")

            # Return only the data fields
            return {
                k: v for k, v in result.items()
                if k in ['trust_cash', 'shares_outstanding', 'nav_per_share']
            }

        except Exception as e:
            print(f"      ⚠️  AI extraction error: {e}")
            return {}

    def _check_deal_status(self, sections: Dict[str, str], ticker: str) -> Dict:
        """
        Check for deal announcements, completions, or liquidation using AI

        AI-based extraction is better than regex for:
        - Finding target company names in various formats
        - Understanding context (announced vs completed vs rumored)
        - Extracting deal details (valuation, structure, etc.)
        """
        if not AI_AVAILABLE:
            return self._check_deal_status_keywords(sections, ticker)

        # Check subsequent events and business combination sections
        relevant_sections = []
        for section_name in ['subsequent_events', 'business_combination', 'summary']:
            if section_name in sections:
                relevant_sections.append(sections[section_name])

        if not relevant_sections:
            return self._check_deal_status_keywords(sections, ticker)

        combined_text = '\n\n'.join(relevant_sections)[:15000]

        return self._extract_deal_with_ai(combined_text, ticker)

    def _extract_deal_with_ai(self, text: str, ticker: str) -> Dict:
        """Extract deal information using AI"""

        prompt = f"""You are analyzing a SPAC 10-Q/10-K filing for {ticker} to detect business combination status.

**INSTRUCTIONS:**

1. Check for BUSINESS COMBINATION ANNOUNCEMENTS:
   - Look for "entered into definitive agreement"
   - Look for "business combination agreement"
   - Look for "merger agreement"
   - Extract target company name if deal announced

2. Check for DEAL COMPLETION:
   - "business combination was completed"
   - "merger was consummated"
   - "closing of the business combination"

3. Check for LIQUIDATION:
   - "commenced liquidation"
   - "dissolution and liquidation"
   - "liquidating trust"

**FILING TEXT:**
{text}

**OUTPUT FORMAT (JSON):**
{{
    "status": "ANNOUNCED|COMPLETED|LIQUIDATED|SEARCHING|null",
    "target_company": "Company name or null",
    "announcement_date": "YYYY-MM-DD or null",
    "deal_value": "Deal value in millions (number) or null",
    "confidence": "high|medium|low",
    "notes": "brief explanation"
}}

If no deal activity found, return status null."""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=400
            )

            import json
            result = json.loads(response.choices[0].message.content)

            # Display results
            if result.get('status'):
                print(f"      ⚠️  Deal status: {result['status']}")
                if result.get('target_company'):
                    print(f"      📋 Target: {result['target_company']}")
                if result.get('deal_value'):
                    print(f"      💰 Deal value: ${result['deal_value']}M")

            if result.get('notes'):
                print(f"      ℹ️  {result['notes']}")

            # Convert to standard format
            output = {}
            if result.get('status'):
                output['status_indicator'] = result['status']
            if result.get('target_company'):
                output['target'] = result['target_company']
            if result.get('announcement_date'):
                from dateutil import parser
                output['announced_date'] = parser.parse(result['announcement_date'])
            if result.get('deal_value'):
                output['deal_value'] = result['deal_value']

            return output

        except Exception as e:
            print(f"      ⚠️  AI deal extraction error: {e}")
            return self._check_deal_status_keywords(sections, ticker)

    def _check_deal_status_keywords(self, sections: Dict[str, str], ticker: str) -> Dict:
        """Fallback keyword-based deal detection (when AI unavailable)"""
        result = {}

        text_all = ' '.join(sections.values()).lower()

        # Check for completion indicators
        completion_keywords = [
            'business combination was completed',
            'merger was completed',
            'transaction was consummated',
            'closing of the business combination'
        ]

        for keyword in completion_keywords:
            if keyword in text_all:
                result['status_indicator'] = 'COMPLETED'
                print(f"      ⚠️  Deal completion indicator found")
                break

        # Check for liquidation indicators
        liquidation_keywords = [
            'commenced liquidation',
            'liquidating trust',
            'winding down',
            'dissolution and liquidation'
        ]

        for keyword in liquidation_keywords:
            if keyword in text_all:
                result['status_indicator'] = 'LIQUIDATED'
                print(f"      ⚠️  Liquidation indicator found")
                break

        return result

    def _contains_extension_info(self, doc_content: str) -> bool:
        """Quick check if document contains extension information"""
        text = doc_content.lower()
        keywords = ['extension', 'extended', 'deadline', 'business combination']
        return any(keyword in text for keyword in keywords)

    def _extract_extension_from_8k(self, doc_content: str, ticker: str) -> Optional[Dict]:
        """Extract extension data from 8-K filing"""
        # Similar logic to _parse_extension_text but for 8-Ks
        text = BeautifulSoup(doc_content, 'html.parser').get_text()
        return self._parse_extension_text(text, ticker)

    def _extract_extension_with_ai(self, text: str, ticker: str) -> Optional[Dict]:
        """Use AI to extract extension data (fallback when regex fails)"""
        if not AI_AVAILABLE:
            return None

        try:
            prompt = f"""Extract extension information from this SPAC quarterly report excerpt:

{text[:5000]}

Extract:
1. New deadline date (if extended)
2. Number of extensions approved
3. Extension deposit amount (if any)

Return JSON:
{{
    "deadline_date": "YYYY-MM-DD" or null,
    "extension_count": number or null,
    "extension_deposit": number or null
}}

If no extension info found, return {{}}.
"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=200
            )

            import json
            data = json.loads(response.choices[0].message.content)

            result = {}
            if data.get('deadline_date'):
                from dateutil import parser
                result['deadline_date'] = parser.parse(data['deadline_date'])
                result['is_extended'] = True

            if data.get('extension_count'):
                result['extension_count'] = data['extension_count']

            if data.get('extension_deposit'):
                result['extension_deposit'] = data['extension_deposit']

            return result if result else None

        except Exception as e:
            print(f"      ⚠️  AI extraction error: {e}")
            return None

    async def _check_for_share_count_drop(
        self,
        ticker: str,
        current_shares: int,
        filing_date: datetime
    ) -> Optional[Dict]:
        """
        Automatically detect share count drops and search 8-Ks for redemption disclosure

        This implements the user's requested workflow:
        1. Detect significant share count drop in 10-Q
        2. Automatically search 8-Ks filed before this 10-Q
        3. Extract detailed redemption data from 8-Ks using AI

        Args:
            ticker: SPAC ticker
            current_shares: Current shares from this 10-Q
            filing_date: Date this 10-Q was filed

        Returns:
            Dict with redemption data if found, None otherwise
        """
        # Get previous share count from database
        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac or not spac.shares_outstanding:
                return None

            previous_shares = spac.shares_outstanding

            # Calculate drop
            share_drop = previous_shares - current_shares
            drop_percentage = (share_drop / previous_shares) * 100

            # Thresholds: 100k shares OR 5% drop
            if share_drop < 100_000 and drop_percentage < 5:
                return None

            print(f"\n      🔍 SHARE DROP DETECTED: {previous_shares:,} → {current_shares:,} ({drop_percentage:.1f}% drop)")
            print(f"      → Automatically searching 8-Ks for redemption disclosure...")

            # Get CIK from database
            if not spac.cik:
                print(f"      ⚠️  No CIK found for {ticker}, cannot search 8-Ks")
                return None

            # Search 8-Ks filed in the last 6 months before this 10-Q
            from datetime import timedelta
            search_start_date = filing_date - timedelta(days=180)

            eight_ks = self.sec_fetcher.search_filings(
                cik=spac.cik,
                filing_type='8-K',
                count=20  # Check last 20 8-Ks
            )

            # Filter to 8-Ks filed before this 10-Q but after search start date
            relevant_8ks = [
                filing for filing in eight_ks
                if search_start_date < filing['date'] < filing_date
            ]

            if not relevant_8ks:
                print(f"      → No 8-Ks found in redemption search window")
                return None

            print(f"      → Found {len(relevant_8ks)} 8-Ks to search")

            # Search each 8-K for redemption disclosure
            import time
            for i, filing in enumerate(relevant_8ks):
                print(f"      → [{i+1}/{len(relevant_8ks)}] Checking 8-K from {filing['date'].strftime('%Y-%m-%d')}...")

                time.sleep(2)  # Rate limiting

                # Extract document URL
                doc_url = self.sec_fetcher.extract_document_url(filing['url'])
                if not doc_url:
                    continue

                # Fetch 8-K
                doc_content = self.sec_fetcher.fetch_document(doc_url)
                if not doc_content:
                    continue

                # Extract text
                text = self.sec_fetcher.extract_text(doc_content)

                # Check for redemption keywords
                if 'redeem' not in text.lower():
                    continue

                print(f"         ✓ Redemption keywords found - extracting with AI...")

                # Use AI to extract redemption details
                redemption_data = self._extract_redemptions_from_8k_with_ai(
                    text=text[:15000],  # Limit to first 15k chars
                    ticker=ticker,
                    filing_date=filing['date'],
                    expected_drop=share_drop
                )

                if redemption_data and redemption_data.get('shares_redeemed'):
                    print(f"         🎯 FOUND REDEMPTIONS IN 8-K!")
                    print(f"            Shares: {redemption_data['shares_redeemed']:,}")
                    if redemption_data.get('redemption_amount'):
                        print(f"            Amount: ${redemption_data['redemption_amount']:,.0f}")
                    return redemption_data

            print(f"      → No redemption disclosure found in 8-Ks")
            return None

        except Exception as e:
            print(f"      ⚠️  Error checking for share drop: {e}")
            return None
        finally:
            db.close()

    def _extract_redemptions_from_8k_with_ai(
        self,
        text: str,
        ticker: str,
        filing_date: datetime,
        expected_drop: int
    ) -> Optional[Dict]:
        """Extract redemption details from 8-K using AI"""
        if not AI_AVAILABLE:
            return None

        prompt = f"""You are analyzing an 8-K filing for {ticker} filed {filing_date.strftime('%Y-%m-%d')} to find redemption disclosure.

**CRITICAL CONTEXT:**
- We detected a share count drop of approximately {expected_drop:,} shares
- This 8-K was filed BEFORE the quarterly report showing the drop
- It likely contains a shareholder vote result with redemption details

**INSTRUCTIONS:**

1. **Look for shareholder vote results:**
   - "X stockholders elected to redeem Y shares"
   - "redemption of X shares"
   - "shareholders redeemed X shares"
   - "X shares subject to redemption"

2. **Extract redemption details:**
   - Number of shares redeemed (should be close to {expected_drop:,})
   - Dollar amount paid for redemptions
   - Redemption price per share (usually ~$10-11)
   - Vote date (if mentioned)

3. **Calculate redemption percentage if possible:**
   - If you find total shares and redeemed shares, calculate percentage

**8-K TEXT:**
{text}

**OUTPUT FORMAT (JSON):**
{{
    "shares_redeemed": <number of shares or null>,
    "redemption_amount": <total dollars or null>,
    "redemption_percentage": <percentage 0-100 or null>,
    "redemption_price_per_share": <price per share or null>,
    "vote_date": "YYYY-MM-DD or null",
    "confidence": "high|medium|low",
    "notes": "brief explanation of what you found"
}}

Return null for fields you cannot find. If no redemptions found, return {{}}.
"""

        try:
            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=500
            )

            data = json.loads(response.choices[0].message.content)

            if not data or not data.get('shares_redeemed'):
                return None

            # Validate shares are reasonable
            shares = data.get('shares_redeemed')
            if not isinstance(shares, (int, float)) or shares < 1000:
                return None

            result = {
                'shares_redeemed': int(shares)
            }

            if data.get('redemption_amount'):
                result['redemption_amount'] = float(data['redemption_amount'])

            if data.get('redemption_percentage'):
                pct = data['redemption_percentage']
                if 0 < pct <= 100:
                    result['redemption_percentage'] = float(pct)

            if data.get('vote_date'):
                from dateutil import parser
                try:
                    result['shareholder_vote_date'] = parser.parse(data['vote_date'])
                except:
                    pass

            return result

        except Exception as e:
            print(f"            ⚠️  AI extraction error: {e}")
            return None

    def _update_database(self, ticker: str, data: Dict):
        """Update SPAC database with extracted data"""
        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                print(f"      ⚠️  SPAC {ticker} not found in database")
                return

            updated_fields = []

            # Update deadline if extended
            if 'deadline_date' in data and data['deadline_date']:
                spac.deadline_date = data['deadline_date']
                updated_fields.append(f"deadline_date={data['deadline_date'].strftime('%Y-%m-%d')}")

            if 'is_extended' in data:
                spac.is_extended = data['is_extended']
                updated_fields.append("is_extended=TRUE")

            if 'extension_count' in data:
                spac.extension_count = data['extension_count']
                updated_fields.append(f"extension_count={data['extension_count']}")

            # Update trust cash (using tracker for automatic trust_value and premium recalculation)
            if 'trust_cash' in data and data['trust_cash'] is not None:
                # Use tracker to ensure trust_value and premium are recalculated
                filing_type = '10-Q' if '10-Q' in str(data.get('filing_type', '')) else '10-K'
                filing_date = data.get('filing_date', datetime.now().date())

                update_trust_cash(
                    db_session=db,
                    ticker=ticker,
                    new_value=data['trust_cash'],
                    source=filing_type,
                    filing_date=filing_date,
                    quarter=f"Q{((filing_date.month-1)//3)+1} {filing_date.year}" if filing_type == '10-Q' else f"FY {filing_date.year}"
                )
                updated_fields.append(f"trust_cash=${data['trust_cash']:,.0f}")

            # Update shares outstanding (directly from filing, not just redemptions)
            if 'shares_outstanding' in data and data['shares_outstanding'] is not None:
                filing_type = '10-Q' if '10-Q' in str(data.get('filing_type', '')) else '10-K'
                filing_date = data.get('filing_date', datetime.now().date())

                update_shares_outstanding(
                    db_session=db,
                    ticker=ticker,
                    new_value=data['shares_outstanding'],
                    source=filing_type,
                    filing_date=filing_date,
                    reason=f"Updated from {filing_type} filing"
                )
                updated_fields.append(f"shares_outstanding={data['shares_outstanding']:,}")

            # Update shares if redemptions occurred (using tracker for automatic trust_value recalculation)
            elif 'shares_redeemed' in data and spac.shares_outstanding:
                new_shares = spac.shares_outstanding - data['shares_redeemed']
                filing_type = '10-Q' if '10-Q' in str(data.get('filing_type', '')) else '10-K'
                filing_date = data.get('filing_date', datetime.now().date())

                update_shares_outstanding(
                    db_session=db,
                    ticker=ticker,
                    new_value=new_shares,
                    source=filing_type,
                    filing_date=filing_date,
                    reason=f"Redemptions: {data['shares_redeemed']:,} shares redeemed"
                )
                updated_fields.append(f"shares_outstanding={new_shares:,}")

            # Update deal status if indicators found
            if 'status_indicator' in data:
                spac.deal_status = data['status_indicator']
                updated_fields.append(f"deal_status={data['status_indicator']}")

            # Update target company if found
            if 'target' in data and data['target']:
                spac.target = data['target']
                updated_fields.append(f"target={data['target']}")

            # Update deal value if found
            if 'deal_value' in data and data['deal_value']:
                # Deal value from AI is in millions, database expects raw value
                spac.deal_value = data['deal_value'] * 1_000_000
                updated_fields.append(f"deal_value=${data['deal_value']}M")

            # Update announced date if found
            if 'announced_date' in data and data['announced_date']:
                spac.announced_date = data['announced_date']
                updated_fields.append(f"announced_date={data['announced_date'].strftime('%Y-%m-%d')}")

            if updated_fields:
                db.commit()
                print(f"      ✓ Updated database: {', '.join(updated_fields)}")
            else:
                print(f"      → No database updates needed")

        except Exception as e:
            print(f"      ⚠️  Database update error: {e}")
            db.rollback()
        finally:
            db.close()
