#!/usr/bin/env python3
"""
CIK Resolver - Finds and populates missing CIK numbers
Ensures all SPACs in database have valid SEC CIK numbers
"""

import requests
import time
from bs4 import BeautifulSoup
import re
from typing import Optional, Dict

from database import SessionLocal, SPAC


class CIKResolver:
    """Finds CIK numbers for SPACs using multiple search strategies"""

    def __init__(self):
        self.base_url = "https://www.sec.gov"
        self.headers = {
            'User-Agent': 'Legacy EVP Spac Platform fenil@legacyevp.com'
        }
        self.db = SessionLocal()

    def search_cik_by_company_name(self, company_name: str) -> Optional[str]:
        """Search SEC EDGAR by exact company name"""
        try:
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'company': company_name,
                'action': 'getcompany',
                'owner': 'exclude'
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)

            # Look for CIK in response
            match = re.search(r'CIK.*?(\d{10})', response.text)
            if match:
                return match.group(1)

            return None

        except Exception as e:
            print(f"   Error searching: {e}")
            return None

    def search_cik_with_variations(self, company_name: str) -> Optional[str]:
        """Try multiple variations of company name"""

        # Generate variations
        variations = [
            company_name,  # Original
            company_name.replace(' Corp.', ''),  # Without Corp.
            company_name.replace(' Corp', ''),  # Without Corp
            company_name.replace(' Corporation', ''),  # Without Corporation
            company_name.replace(' Inc.', ''),  # Without Inc.
            company_name.replace(' Inc', ''),  # Without Inc
            company_name.replace(' plc', ''),  # Without plc
            company_name.replace(' LLC', ''),  # Without LLC
            company_name.replace(' Limited', ''),  # Without Limited
            company_name.replace(' Acquisition', ''),  # Without Acquisition
            re.sub(r'\s+I+$', '', company_name),  # Remove trailing I, II, III
            re.sub(r'\s+\d+$', '', company_name),  # Remove trailing numbers
        ]

        # Add variations with different punctuation
        for base_name in variations[:]:  # Make a copy to iterate
            variations.append(base_name.replace('.', ''))
            variations.append(base_name.replace(',', ''))

        # Remove duplicates
        variations = list(dict.fromkeys([v.strip() for v in variations if v.strip()]))

        for variation in variations:
            cik = self.search_cik_by_company_name(variation)
            if cik and self.verify_cik(cik):
                print(f"   ✓ Found with variation: '{variation}' -> CIK: {cik}")
                return cik
            time.sleep(0.2)  # Rate limiting

        return None

    def search_company_tickers_json(self, ticker: str) -> Optional[str]:
        """Search using SEC's company_tickers.json API (most reliable)"""
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            response = requests.get(url, headers=self.headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                ticker_upper = ticker.upper().replace('.', '')

                for entry in data.values():
                    if entry.get('ticker', '').upper() == ticker_upper:
                        cik = str(entry.get('cik_str', '')).zfill(10)
                        return cik
        except Exception as e:
            print(f"   Error with company_tickers.json: {e}")

        return None

    def search_cik_by_ticker(self, ticker: str) -> Optional[str]:
        """Search SEC EDGAR by ticker symbol"""
        # First try the JSON API (most reliable)
        cik = self.search_company_tickers_json(ticker)
        if cik:
            return cik

        # Fallback to browse-edgar
        try:
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'company': ticker,
                'action': 'getcompany',
                'owner': 'exclude'
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)

            # Look for CIK in response
            match = re.search(r'CIK.*?(\d{10})', response.text)
            if match:
                return match.group(1)

            return None

        except Exception as e:
            print(f"   Error searching by ticker: {e}")
            return None

    def verify_cik(self, cik: str) -> bool:
        """Verify that a CIK is valid and active"""
        try:
            url = f"{self.base_url}/cgi-bin/browse-edgar"
            params = {
                'action': 'getcompany',
                'CIK': cik.zfill(10),
                'owner': 'exclude'
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=30)

            # Check if we get a valid company page
            return 'companyName' in response.text and 'No matching' not in response.text

        except Exception as e:
            print(f"   Error verifying CIK: {e}")
            return False

    def resolve_cik_for_spac(self, spac: SPAC) -> Optional[str]:
        """Try all methods to find CIK for a SPAC"""

        print(f"\n[{spac.ticker}] {spac.company}")

        # If CIK already exists, verify it
        if spac.cik:
            if self.verify_cik(spac.cik):
                print(f"   ✓ Existing CIK valid: {spac.cik}")
                return spac.cik
            else:
                print(f"   ⚠️  Existing CIK invalid: {spac.cik}")

        # Strategy 1: Search by exact company name
        print(f"   Searching by company name...")
        cik = self.search_cik_by_company_name(spac.company)
        if cik and self.verify_cik(cik):
            return cik

        # Strategy 2: Search by ticker
        print(f"   Searching by ticker...")
        cik = self.search_cik_by_ticker(spac.ticker)
        if cik and self.verify_cik(cik):
            return cik

        # Strategy 3: Try company name variations
        print(f"   Searching with variations...")
        cik = self.search_cik_with_variations(spac.company)
        if cik and self.verify_cik(cik):
            return cik

        # Strategy 4: Try unit ticker variations
        if spac.unit_ticker:
            base_ticker = spac.unit_ticker.replace('U', '').replace('.U', '')
            print(f"   Trying base ticker: {base_ticker}...")
            cik = self.search_cik_by_ticker(base_ticker)
            if cik and self.verify_cik(cik):
                return cik

        print(f"   ❌ CIK not found after all strategies")
        return None

    def resolve_all_missing_ciks(self):
        """Find and populate CIKs for all SPACs missing them"""

        print("=" * 60)
        print("CIK RESOLVER")
        print("=" * 60)
        print("\nFinding SPACs with missing or invalid CIKs...\n")

        # Get all SPACs
        all_spacs = self.db.query(SPAC).all()

        missing_cik = []
        valid_cik = 0

        # Categorize SPACs
        for spac in all_spacs:
            if not spac.cik or spac.cik.strip() == '':
                missing_cik.append(spac)
            else:
                valid_cik += 1

        print(f"📊 Status:")
        print(f"   ✓ SPACs with CIK: {valid_cik}")
        print(f"   ⚠️  SPACs missing CIK: {len(missing_cik)}")

        if not missing_cik:
            print("\n✅ All SPACs have CIK numbers!")
            return

        print(f"\n🔍 Resolving {len(missing_cik)} missing CIKs...\n")

        found = 0
        not_found = []

        for i, spac in enumerate(missing_cik, 1):
            print(f"\n[{i}/{len(missing_cik)}] ", end='')

            cik = self.resolve_cik_for_spac(spac)

            if cik:
                # Update database
                spac.cik = cik
                self.db.commit()
                print(f"   ✅ Updated CIK: {cik}")
                found += 1
            else:
                not_found.append((spac.ticker, spac.company))

            time.sleep(0.5)  # Rate limiting

        # Summary
        print("\n" + "=" * 60)
        print("RESOLUTION COMPLETE")
        print("=" * 60)
        print(f"\n✅ Found and updated: {found}")
        print(f"❌ Could not find: {len(not_found)}")

        if not_found:
            print(f"\n⚠️  Manual review needed for {len(not_found)} SPACs:")
            for ticker, company in not_found[:10]:  # Show first 10
                print(f"   • {ticker}: {company}")
            if len(not_found) > 10:
                print(f"   ... and {len(not_found) - 10} more")

        # Final stats
        total_with_cik = self.db.query(SPAC).filter(SPAC.cik != None, SPAC.cik != '').count()
        total_spacs = self.db.query(SPAC).count()

        print(f"\n📊 Final Status:")
        print(f"   SPACs with CIK: {total_with_cik}/{total_spacs} ({total_with_cik/total_spacs*100:.1f}%)")

    def close(self):
        """Close database connection"""
        self.db.close()


if __name__ == "__main__":
    resolver = CIKResolver()
    try:
        resolver.resolve_all_missing_ciks()
    finally:
        resolver.close()
