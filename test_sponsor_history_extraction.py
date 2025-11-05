#!/usr/bin/env python3
"""
Test: Systematic Sponsor History Extraction from SEC EDGAR
Proof of concept for Option B - build sponsor_spac_history from 8-K filings
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, List, Optional
from database import SessionLocal, SPAC

class SponsorHistoryExtractor:
    """Extract historical sponsor SPAC deals from SEC EDGAR"""

    def __init__(self):
        self.base_url = "https://www.sec.gov"
        self.headers = {'User-Agent': 'SPAC Research Platform admin@spacresearch.com'}
        self.db = SessionLocal()

    def close(self):
        self.db.close()

    def get_sponsor_history_from_our_db(self, sponsor_normalized: str) -> List[Dict]:
        """
        Step 1: Get all SPACs by this sponsor from our existing database
        This gives us: ticker, ipo_date, announcement_date, target
        """
        spacs = self.db.query(SPAC).filter(
            SPAC.sponsor.ilike(f'%{sponsor_normalized}%')
        ).all()

        history = []
        for spac in spacs:
            history.append({
                'ticker': spac.ticker,
                'sponsor': spac.sponsor,
                'ipo_date': spac.ipo_date,
                'announcement_date': spac.announced_date,
                'target': spac.target,
                'deal_value': spac.deal_value,
                'completion_date': spac.completion_date if hasattr(spac, 'completion_date') else None,
                'is_completed': spac.deal_status == 'COMPLETED'
            })

        return history

    def verify_8k_announcement_exists(self, ticker: str, cik: str) -> Optional[Dict]:
        """
        Step 2: Verify we can find 8-K Item 1.01 for announced deals
        This confirms our extraction method works
        """
        try:
            # Query SEC for 8-K filings
            search_url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik.zfill(10),
                'type': '8-K',
                'count': 50,  # Check last 50 8-Ks
                'dateb': ''  # All dates
            }

            response = requests.get(search_url, params=params, headers=self.headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', {'class': 'tableFile2'})
            if not table:
                return None

            # Look for 8-K with Item 1.01 (business combination agreement)
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    filing_date = cols[3].text.strip()

                    # Get filing details
                    doc_link = cols[1].find('a', {'id': 'documentsbutton'})
                    if doc_link:
                        filing_url = self.base_url + doc_link['href']

                        # Fetch filing to check for Item 1.01
                        time.sleep(0.3)  # Rate limiting
                        filing_response = requests.get(filing_url, headers=self.headers, timeout=30)

                        if 'Item 1.01' in filing_response.text or 'Item 1.1' in filing_response.text:
                            return {
                                'filing_date': filing_date,
                                'filing_url': filing_url,
                                'has_item_101': True
                            }

            return None

        except Exception as e:
            print(f"   Error checking 8-K: {e}")
            return None

    def test_sponsor_history_extraction(self, sponsor_keyword: str, limit: int = 5):
        """
        Test: Can we systematically build sponsor history?

        Steps:
        1. Query our DB for all SPACs by this sponsor
        2. For each announced deal, verify 8-K Item 1.01 exists
        3. Show we have: ticker, sponsor, announcement date, target
        4. Confirm this data is sufficient for performance tracking
        """
        print(f"\n{'='*80}")
        print(f"TESTING: Sponsor History Extraction for '{sponsor_keyword}'")
        print(f"{'='*80}\n")

        # Step 1: Get history from our database
        print(f"Step 1: Querying our database for {sponsor_keyword} SPACs...")
        history = self.get_sponsor_history_from_our_db(sponsor_keyword)

        print(f"   Found {len(history)} SPACs by this sponsor\n")

        if not history:
            print(f"   ⚠️  No SPACs found for sponsor '{sponsor_keyword}'")
            return

        # Step 2: Verify 8-K filings exist for announced deals
        print(f"Step 2: Verifying 8-K Item 1.01 filings exist...\n")

        deals_with_announcement = [s for s in history if s['announcement_date']]
        print(f"   {len(deals_with_announcement)} deals with announcement dates")

        # Test on first few deals
        checked_count = 0
        verified_count = 0

        for spac_data in deals_with_announcement[:limit]:
            ticker = spac_data['ticker']

            # Get CIK for this SPAC
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac or not spac.cik:
                print(f"   ⚠️  {ticker}: No CIK available")
                continue

            checked_count += 1
            print(f"\n   Checking {ticker}...")
            print(f"      Announced: {spac_data['announcement_date']}")
            print(f"      Target: {spac_data['target']}")

            # Verify 8-K exists
            result = self.verify_8k_announcement_exists(ticker, spac.cik)

            if result:
                verified_count += 1
                print(f"      ✅ Found 8-K Item 1.01: {result['filing_date']}")
            else:
                print(f"      ⚠️  8-K Item 1.01 not found (may be pre-IPO or missing)")

        # Step 3: Summary
        print(f"\n{'='*80}")
        print(f"SUMMARY: Sponsor History for '{sponsor_keyword}'")
        print(f"{'='*80}\n")

        print(f"Total SPACs by sponsor: {len(history)}")
        print(f"Announced deals: {len(deals_with_announcement)}")
        print(f"8-K filings checked: {checked_count}")
        print(f"8-K Item 1.01 verified: {verified_count}")

        print(f"\n{'='*80}")
        print(f"CONCLUSION")
        print(f"{'='*80}\n")

        if verified_count > 0:
            print("✅ SUCCESS: We can systematically extract sponsor history from SEC EDGAR")
            print(f"   - Our database already has: ticker, sponsor, announcement date, target")
            print(f"   - SEC EDGAR has: 8-K Item 1.01 filings for verification")
            print(f"   - Next step: Fetch historical prices around announcement dates")
        else:
            print("⚠️  WARNING: Could not verify 8-K filings")
            print("   - May need to check different filing types or time periods")

        print(f"\n{'='*80}")
        print(f"SPONSOR DEALS SUMMARY")
        print(f"{'='*80}\n")

        for i, spac_data in enumerate(history, 1):
            status = "✅ ANNOUNCED" if spac_data['announcement_date'] else "⏳ SEARCHING"
            print(f"{i}. {spac_data['ticker']:<8} | {status:<15} | Target: {spac_data['target'] or 'N/A'}")
            if spac_data['announcement_date']:
                print(f"              Announced: {spac_data['announcement_date']}")


def main():
    """Test sponsor history extraction"""

    extractor = SponsorHistoryExtractor()

    try:
        # Test on Klein (has 11 SPACs, 3 announced)
        print("\n" + "="*80)
        print("TEST: Systematic Sponsor History Extraction (Option B)")
        print("="*80)
        print("\nTesting with 'Klein Sponsor' (has multiple SPACs)...\n")

        extractor.test_sponsor_history_extraction('Klein', limit=3)

        print("\n" + "="*80)
        print("NEXT STEPS IF SUCCESSFUL:")
        print("="*80)
        print("""
1. Build sponsor_spac_history table from our existing database
2. For each announced deal, fetch historical prices (Yahoo Finance)
3. Calculate sponsor performance metrics:
   - avg_7day_pop, avg_14day_pop, avg_30day_pop
4. Store in sponsor_performance table

Storage requirements:
- Sponsors: ~150 unique sponsors (~10KB)
- Price history: 66 deals × 30 days = 1,980 rows (~60KB)
- Total: < 100KB

Time to backfill:
- Yahoo Finance API: 66 SPACs × 0.5 sec = 33 seconds
""")

    finally:
        extractor.close()


if __name__ == '__main__':
    main()
