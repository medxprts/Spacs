#!/usr/bin/env python3
"""
SEC Filing Verification Module
Verifies web search findings against official SEC filings

This provides a second layer of validation:
1. Web search finds potential deal info
2. SEC verification confirms via official filings
3. Only high-confidence + SEC-verified fixes get proposed

Integration: Called by Web Research Agent after web search analysis
"""

import sys
import re
from datetime import datetime, timedelta
from typing import Dict, Optional

sys.path.append('/home/ubuntu/spac-research')

from utils.sec_filing_fetcher import SECFilingFetcher, search_sec_filings


class SECVerifier:
    """
    Verifies web research findings against SEC filings
    """

    def __init__(self):
        self.fetcher = SECFilingFetcher()

    def verify_deal_announcement(self, ticker: str, web_research_findings: Dict) -> Dict:
        """
        Verify if a deal announcement found via web search is confirmed in SEC filings

        Args:
            ticker: SPAC ticker
            web_research_findings: Dict from Web Research Agent containing:
                - deal_status
                - target_company
                - announced_date
                - confidence

        Returns:
            Dict with:
                - sec_verified: bool
                - sec_filing_url: str or None
                - sec_filing_date: str or None
                - verification_confidence_boost: int (0-20 points to add)
                - reasoning: str
        """
        print(f"\n   🔍 [SEC VERIFICATION] Checking filings for {ticker}...")

        # If web research didn't find a deal, no need to verify
        if web_research_findings.get('deal_status') != 'ANNOUNCED':
            return {
                'sec_verified': True,  # No deal to verify
                'sec_filing_url': None,
                'sec_filing_date': None,
                'verification_confidence_boost': 0,
                'reasoning': 'No deal announced per web research - no SEC verification needed'
            }

        target = web_research_findings.get('target_company')
        announced_date = web_research_findings.get('announced_date')

        if not target:
            print("   ⚠️  No target company to verify")
            return {
                'sec_verified': False,
                'sec_filing_url': None,
                'sec_filing_date': None,
                'verification_confidence_boost': 0,
                'reasoning': 'No target company specified - cannot verify'
            }

        # Search SEC filings for 8-K (deal announcements)
        try:
            # Get CIK for this ticker
            from database import SessionLocal, SPAC
            db = SessionLocal()
            try:
                spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
                if not spac or not spac.cik:
                    print(f"   ⚠️  No CIK found for {ticker}")
                    return {
                        'sec_verified': False,
                        'sec_filing_url': None,
                        'sec_filing_date': None,
                        'verification_confidence_boost': 0,
                        'reasoning': 'No CIK available - cannot search SEC filings'
                    }
                cik = spac.cik
            finally:
                db.close()

            # Search for recent 8-K filings (last 20 should cover ±30 days)
            filings = search_sec_filings(
                cik=cik,
                filing_type='8-K',
                count=20
            )

            if not filings:
                print(f"   ⚠️  No 8-K filings found")
                return {
                    'sec_verified': False,
                    'sec_filing_url': None,
                    'sec_filing_date': None,
                    'verification_confidence_boost': -10,  # Reduce confidence
                    'reasoning': f'No 8-K filings found'
                }

            # Filter by date if announced_date provided (±30 days)
            if announced_date:
                search_date = datetime.fromisoformat(announced_date)
                start_date = search_date - timedelta(days=30)
                end_date = search_date + timedelta(days=7)

                filtered_filings = []
                for filing in filings:
                    filing_date_str = filing.get('date', '')
                    if filing_date_str:
                        try:
                            filing_date = datetime.strptime(filing_date_str, '%Y-%m-%d')
                            if start_date <= filing_date <= end_date:
                                filtered_filings.append(filing)
                        except:
                            pass
                filings = filtered_filings if filtered_filings else filings[:5]

            # Check each 8-K for deal keywords
            for filing in filings[:5]:  # Check most recent 5
                filing_url = filing.get('url', '')
                filing_date = filing.get('date', '')

                # Fetch filing content
                try:
                    content = self.fetcher.fetch_document(filing_url)

                    if not content:
                        continue

                    # Check for deal keywords
                    deal_keywords = [
                        'merger agreement',
                        'business combination agreement',
                        'definitive agreement',
                        'agreement and plan of merger'
                    ]

                    has_deal_keyword = any(keyword.lower() in content.lower() for keyword in deal_keywords)

                    # Check if target company mentioned (flexible matching)
                    # Extract key parts of target name (e.g., "VERAXA" from "VERAXA Biotech AG")
                    target_words = target.lower().replace(',', '').split()
                    # Filter out common words
                    significant_words = [w for w in target_words if w not in ['inc', 'corp', 'corporation', 'ltd', 'limited', 'ag', 'gmbh', 'llc', 'llp', 'the']]

                    print(f"      Looking for words: {significant_words} in filing...")

                    # Check if main company name appears
                    target_mentioned = any(word in content.lower() for word in significant_words if len(word) > 3)

                    if has_deal_keyword:
                        print(f"      Has deal keyword: {has_deal_keyword}, Target mentioned: {target_mentioned}")

                    if has_deal_keyword and target_mentioned:
                        print(f"   ✅ SEC VERIFIED: 8-K on {filing_date} mentions {target}")
                        return {
                            'sec_verified': True,
                            'sec_filing_url': filing_url,
                            'sec_filing_date': filing_date,
                            'verification_confidence_boost': 15,  # High confidence boost
                            'reasoning': f'SEC 8-K filing on {filing_date} confirms deal with {target}'
                        }

                    elif has_deal_keyword:
                        # Deal mentioned but different target - might be wrong target name
                        print(f"   ⚠️  8-K mentions deal but not {target}")
                        return {
                            'sec_verified': False,
                            'sec_filing_url': filing_url,
                            'sec_filing_date': filing_date,
                            'verification_confidence_boost': -15,  # Reduce confidence significantly
                            'reasoning': f'SEC 8-K on {filing_date} mentions deal but not target {target} - possible incorrect target name from web research'
                        }

                except Exception as e:
                    print(f"   ⚠️  Error fetching {filing_url}: {e}")
                    continue

            # Found 8-K filings but none mention the deal
            print(f"   ⚠️  Found {len(filings)} 8-K filings but none mention {target}")
            return {
                'sec_verified': False,
                'sec_filing_url': None,
                'sec_filing_date': None,
                'verification_confidence_boost': -5,
                'reasoning': f'Found {len(filings)} 8-K filings near {announced_date} but none mention {target}'
            }

        except Exception as e:
            print(f"   ✗ SEC verification error: {e}")
            return {
                'sec_verified': False,
                'sec_filing_url': None,
                'sec_filing_date': None,
                'verification_confidence_boost': 0,
                'reasoning': f'SEC verification failed: {e}'
            }


# Standalone test
if __name__ == "__main__":
    verifier = SECVerifier()

    # Test case: VACH with VERAXA Biotech
    test_findings = {
        'deal_status': 'ANNOUNCED',
        'target_company': 'VERAXA Biotech',
        'announced_date': '2025-04-23',
        'confidence': 85
    }

    print("🧪 Testing SEC Verification for VACH...\n")
    result = verifier.verify_deal_announcement('VACH', test_findings)

    print("\n📊 VERIFICATION RESULTS:")
    print(f"SEC Verified: {result['sec_verified']}")
    print(f"Filing URL: {result['sec_filing_url']}")
    print(f"Filing Date: {result['sec_filing_date']}")
    print(f"Confidence Boost: {result['verification_confidence_boost']:+d} points")
    print(f"Reasoning: {result['reasoning']}")
