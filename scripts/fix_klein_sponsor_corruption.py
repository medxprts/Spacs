#!/usr/bin/env python3
"""
Fix Klein Sponsor LLC Data Corruption

10 SPACs have "Klein Sponsor LLC" but their company names don't contain
Churchill or Klein, suggesting incorrect data.

Strategy:
1. Clear sponsor data for affected SPACs
2. Re-extract from SEC filings using filing processor
3. Manual review for any that can't be auto-extracted
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from agents.filing_processor import FilingProcessor
import time


# SPACs identified with incorrect "Klein Sponsor LLC" assignment
AFFECTED_TICKERS = [
    'DYNX',  # Dynamix Corporation
    'MBAV',  # M3-Brigade Acquisition V
    'PELI',  # Pelican Acquisition
    'AIIA',  # AI Infrastructure Acquisition
    'RAAQ',  # Real Asset Acquisition
    'DAAQ',  # Digital Asset Acquisition
    'KCHV',  # Kochav Defense Acquisition
    'CRA',   # Cal Redwood Acquisition
    'AXIN',  # Axiom Intelligence Acquisition
    'CGCT',  # Cartesian Growth Corporation
]


class KleinSponsorFixer:
    """Fix incorrect Klein Sponsor LLC assignments"""

    def __init__(self):
        self.db = SessionLocal()
        self.processor = FilingProcessor()

    def close(self):
        self.db.close()

    def clear_bad_sponsor_data(self, dry_run=True):
        """Clear sponsor data for affected SPACs"""

        print(f"{'DRY RUN: ' if dry_run else ''}Clearing incorrect Klein Sponsor LLC data")
        print("=" * 80)

        for ticker in AFFECTED_TICKERS:
            spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                print(f"  ❌ {ticker}: Not found in database")
                continue

            print(f"\n  {ticker}: {spac.company}")
            print(f"    Current sponsor: {spac.sponsor}")
            print(f"    Current normalized: {spac.sponsor_normalized}")

            if not dry_run:
                spac.sponsor = None
                spac.sponsor_normalized = None
                print(f"    ✅ Cleared sponsor data")

        if not dry_run:
            self.db.commit()
            print(f"\n✅ Committed changes to database")
        else:
            print(f"\nℹ️  DRY RUN - Use --commit to apply changes")

    def re_extract_sponsor(self, ticker: str):
        """Re-extract sponsor from SEC filing for a single SPAC"""

        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            print(f"❌ {ticker}: Not found")
            return None

        print(f"\n{'=' * 80}")
        print(f"{ticker} - {spac.company}")
        print(f"{'=' * 80}")

        filing_url = spac.prospectus_424b4_url or spac.s1_filing_url
        if not filing_url:
            print(f"  ❌ No SEC filing URL")
            return None

        print(f"  📄 Fetching {filing_url[:70]}...")
        filing_text = self.processor._fetch_document(filing_url)

        if not filing_text:
            print(f"  ❌ Could not fetch filing")
            return None

        print(f"  ✅ Fetched {len(filing_text):,} characters")

        # Extract sponsor section
        sponsor_section = self.processor._extract_section(
            filing_text,
            ['PRINCIPAL STOCK', 'Our Sponsor', 'The Sponsor'],
            max_length=15000
        )

        if not sponsor_section:
            print(f"  ⚠️  Could not find sponsor section")
            return None

        print(f"  📋 Extracted {len(sponsor_section):,} chars from sponsor section")

        # Use AI to extract sponsor
        prompt = f"""Extract sponsor information from this SPAC filing.

SPAC: {ticker} - {spac.company}

Look for:
- Sponsor LLC entity name (e.g., "XYZ Sponsor LLC")
- Managing members of sponsor
- If no explicit sponsor entity name found, infer from company name pattern

Return valid JSON:
{{
  "sponsor": "Entity name or null if not found",
  "sponsor_normalized": "Family name for grouping",
  "managing_members": ["Name 1", "Name 2"],
  "confidence": 0-100,
  "reasoning": "Brief explanation"
}}

Filing excerpt:
{sponsor_section[:8000]}
"""

        result = self.processor._call_ai(prompt)

        if result and result.get('sponsor'):
            print(f"  ✅ AI extracted:")
            print(f"     Sponsor: {result['sponsor']}")
            print(f"     Normalized: {result['sponsor_normalized']}")
            print(f"     Managing members: {result.get('managing_members', [])}")
            print(f"     Confidence: {result.get('confidence')}%")
            print(f"     Reasoning: {result.get('reasoning')}")
            return result
        else:
            print(f"  ⚠️  AI could not extract sponsor")
            return None

    def fix_all(self, dry_run=True):
        """Re-extract sponsor for all affected SPACs"""

        print(f"Re-extracting sponsor data for {len(AFFECTED_TICKERS)} SPACs")
        print("=" * 80)

        results = {}
        for ticker in AFFECTED_TICKERS:
            result = self.re_extract_sponsor(ticker)
            results[ticker] = result

            if result and not dry_run:
                # Update database
                spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
                if spac:
                    spac.sponsor = result['sponsor']
                    spac.sponsor_normalized = result['sponsor_normalized']
                    print(f"  💾 Updated database")

            # Rate limit
            time.sleep(2)

        if not dry_run:
            self.db.commit()
            print(f"\n✅ Committed all changes to database")
        else:
            print(f"\nℹ️  DRY RUN - Use --commit to apply changes")

        return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fix Klein Sponsor LLC data corruption')
    parser.add_argument('--clear', action='store_true', help='Clear bad sponsor data')
    parser.add_argument('--extract', action='store_true', help='Re-extract sponsor from filings')
    parser.add_argument('--ticker', help='Process single ticker')
    parser.add_argument('--commit', action='store_true', help='Commit changes (default is dry run)')
    args = parser.parse_args()

    fixer = KleinSponsorFixer()

    try:
        if args.clear:
            fixer.clear_bad_sponsor_data(dry_run=not args.commit)

        elif args.extract:
            if args.ticker:
                fixer.re_extract_sponsor(args.ticker.upper())
            else:
                fixer.fix_all(dry_run=not args.commit)

        else:
            print("Usage:")
            print("  --clear: Clear incorrect Klein Sponsor LLC data")
            print("  --extract: Re-extract sponsor from SEC filings")
            print("  --ticker DYNX: Process single ticker")
            print("  --commit: Apply changes (default is dry run)")

    finally:
        fixer.close()


if __name__ == '__main__':
    main()
