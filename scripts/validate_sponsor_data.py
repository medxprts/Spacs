#!/usr/bin/env python3
"""
Validate Sponsor Data Quality

Checks for suspicious sponsor assignments and data quality issues.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from collections import defaultdict
from typing import Dict, List


class SponsorDataValidator:
    """Validate sponsor data for quality issues"""

    def __init__(self):
        self.db = SessionLocal()

    def close(self):
        self.db.close()

    def check_for_duplicates(self) -> Dict:
        """Find SPACs with identical sponsor names but different tickers"""

        spacs = self.db.query(SPAC).filter(SPAC.sponsor != None).all()

        sponsor_to_tickers = defaultdict(list)
        for spac in spacs:
            sponsor_to_tickers[spac.sponsor].append(spac.ticker)

        # Sponsors with multiple SPACs
        multi_spac_sponsors = {k: v for k, v in sponsor_to_tickers.items() if len(v) > 1}

        print(f"📊 Found {len(multi_spac_sponsors)} sponsors with multiple SPACs")
        print("=" * 80)

        for sponsor, tickers in sorted(multi_spac_sponsors.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"\n{sponsor}")
            print(f"  {len(tickers)} SPACs: {', '.join(tickers)}")

        return multi_spac_sponsors

    def check_for_name_mismatches(self) -> List[Dict]:
        """
        Find SPACs where company name doesn't match sponsor name patterns.

        Common patterns:
        - Company: "Churchill Capital Corp IX" → Sponsor should have "Churchill"
        - Company: "Gores Holdings X" → Sponsor should have "Gores"
        - Company: "EGH Acquisition" → Sponsor should NOT have "Klein"
        """

        issues = []
        spacs = self.db.query(SPAC).filter(SPAC.sponsor != None, SPAC.company != None).all()

        print(f"\n\n🔍 Checking for company/sponsor name mismatches...")
        print("=" * 80)

        for spac in spacs:
            company_lower = spac.company.lower()
            sponsor_lower = spac.sponsor.lower() if spac.sponsor else ""

            # Extract key words from company name
            company_keywords = set()
            for word in company_lower.split():
                if len(word) > 3 and word not in ['corp', 'corporation', 'acquisition', 'holdings', 'capital', 'partners', 'sponsor', 'llc']:
                    company_keywords.add(word)

            # Extract key words from sponsor name
            sponsor_keywords = set()
            for word in sponsor_lower.split():
                if len(word) > 3 and word not in ['corp', 'corporation', 'acquisition', 'holdings', 'capital', 'partners', 'sponsor', 'llc']:
                    sponsor_keywords.add(word)

            # Check for mismatch: Company has keyword that sponsor doesn't have
            company_unique = company_keywords - sponsor_keywords
            sponsor_unique = sponsor_keywords - company_keywords

            # Flag if there's a complete mismatch (no shared keywords)
            if company_keywords and sponsor_keywords and not (company_keywords & sponsor_keywords):
                # Special case: Check for well-known franchise patterns
                is_franchise = self._is_known_franchise(spac.company, spac.sponsor)

                if not is_franchise:
                    issues.append({
                        'ticker': spac.ticker,
                        'company': spac.company,
                        'sponsor': spac.sponsor,
                        'sponsor_normalized': spac.sponsor_normalized,
                        'company_keywords': company_keywords,
                        'sponsor_keywords': sponsor_keywords,
                        'severity': 'HIGH'
                    })

        print(f"\n⚠️  Found {len(issues)} potential company/sponsor mismatches:\n")
        for issue in issues:
            print(f"  {issue['ticker']}: {issue['company']}")
            print(f"    Company keywords: {issue['company_keywords']}")
            print(f"    Sponsor: {issue['sponsor']}")
            print(f"    Sponsor keywords: {issue['sponsor_keywords']}")
            print(f"    Normalized: {issue['sponsor_normalized']}")
            print()

        return issues

    def _is_known_franchise(self, company: str, sponsor: str) -> bool:
        """Check if this is a known franchise pattern where names differ"""

        # Known franchise patterns where sponsor != company name
        franchise_patterns = [
            # Social Capital uses "IPOA", "IPOB" etc. in company name
            ('social capital', 'ipo'),
            # Churchill sometimes uses brand names
            ('churchill', 'klein'),
            # Some use founder names vs. company names
            ('klein', 'churchill'),
        ]

        company_lower = company.lower()
        sponsor_lower = sponsor.lower()

        for sponsor_keyword, company_keyword in franchise_patterns:
            if sponsor_keyword in sponsor_lower and company_keyword in company_lower:
                return True
            if company_keyword in company_lower and sponsor_keyword in sponsor_lower:
                return True

        return False

    def check_klein_vs_churchill(self) -> List[Dict]:
        """
        Specific check for Klein vs Churchill confusion.

        Klein Sponsor LLC should NOT be Churchill Capital unless the company
        name also has "Churchill" in it.
        """

        print(f"\n\n🔍 Checking Klein vs Churchill assignments...")
        print("=" * 80)

        klein_spacs = self.db.query(SPAC).filter(SPAC.sponsor.like('%Klein%')).all()

        issues = []
        for spac in klein_spacs:
            company_has_churchill = 'churchill' in spac.company.lower()
            company_has_klein = 'klein' in spac.company.lower()

            # If sponsor is "Klein Sponsor LLC" but company name doesn't have "Churchill" or "Klein",
            # this is suspicious
            if not company_has_churchill and not company_has_klein:
                issues.append({
                    'ticker': spac.ticker,
                    'company': spac.company,
                    'sponsor': spac.sponsor,
                    'sponsor_normalized': spac.sponsor_normalized,
                    'issue': 'Klein Sponsor LLC but no Churchill/Klein in company name'
                })

        print(f"\n⚠️  Found {len(issues)} Klein/Churchill assignment issues:\n")
        for issue in issues:
            print(f"  {issue['ticker']}: {issue['company']}")
            print(f"    Sponsor: {issue['sponsor']}")
            print(f"    Normalized: {issue['sponsor_normalized']}")
            print(f"    Issue: {issue['issue']}")
            print()

        return issues

    def check_all_spac_sources(self) -> Dict:
        """
        Check where sponsor data came from (S-1 URL presence indicates SEC scrape).
        """

        print(f"\n\n📊 Checking data sources...")
        print("=" * 80)

        spacs = self.db.query(SPAC).all()

        stats = {
            'total': len(spacs),
            'has_s1': 0,
            'has_424b4': 0,
            'has_sponsor': 0,
            'has_both_filing_and_sponsor': 0,
            'has_sponsor_no_filing': 0
        }

        no_filing_sponsors = []

        for spac in spacs:
            if spac.s1_filing_url:
                stats['has_s1'] += 1
            if spac.prospectus_424b4_url:
                stats['has_424b4'] += 1
            if spac.sponsor:
                stats['has_sponsor'] += 1

            if spac.sponsor and (spac.s1_filing_url or spac.prospectus_424b4_url):
                stats['has_both_filing_and_sponsor'] += 1

            if spac.sponsor and not spac.s1_filing_url and not spac.prospectus_424b4_url:
                stats['has_sponsor_no_filing'] += 1
                no_filing_sponsors.append((spac.ticker, spac.sponsor))

        print(f"Total SPACs: {stats['total']}")
        print(f"  Has S-1 URL: {stats['has_s1']}")
        print(f"  Has 424B4 URL: {stats['has_424b4']}")
        print(f"  Has sponsor data: {stats['has_sponsor']}")
        print(f"  Has both filing + sponsor: {stats['has_both_filing_and_sponsor']}")
        print(f"  Has sponsor but NO filing URLs: {stats['has_sponsor_no_filing']}")

        if no_filing_sponsors:
            print(f"\n⚠️  SPACs with sponsor but no filing URLs (may be manually entered):")
            for ticker, sponsor in no_filing_sponsors[:20]:
                print(f"    {ticker}: {sponsor}")

        return stats


def main():
    validator = SponsorDataValidator()

    try:
        print("SPONSOR DATA VALIDATION REPORT")
        print("=" * 80)

        # Check 1: Find duplicates
        validator.check_for_duplicates()

        # Check 2: Company/sponsor name mismatches
        issues = validator.check_for_name_mismatches()

        # Check 3: Klein vs Churchill specific check
        klein_issues = validator.check_klein_vs_churchill()

        # Check 4: Data sources
        sources = validator.check_all_spac_sources()

        print("\n\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Company/sponsor mismatches: {len(issues)}")
        print(f"Klein/Churchill issues: {len(klein_issues)}")
        print(f"SPACs with sponsor but no filing: {sources['has_sponsor_no_filing']}")

    finally:
        validator.close()


if __name__ == '__main__':
    main()
