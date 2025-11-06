#!/usr/bin/env python3
"""
Check actual sponsor in SEC filing vs database value
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from agents.filing_processor import FilingProcessor


def check_sponsor_in_filing(ticker: str):
    """Check what sponsor name appears in the actual SEC filing"""

    db = SessionLocal()
    processor = FilingProcessor()

    spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"❌ {ticker} not found")
        return

    print(f"\n{'=' * 80}")
    print(f"{ticker} - {spac.company}")
    print(f"{'=' * 80}")
    print(f"Database sponsor: {spac.sponsor}")
    print(f"Filing URL: {spac.prospectus_424b4_url}")

    if not spac.prospectus_424b4_url:
        print("❌ No 424B4 URL")
        return

    # Fetch filing
    print(f"\n📄 Fetching filing...")
    filing_text = processor._fetch_document(spac.prospectus_424b4_url)

    if not filing_text:
        print("❌ Could not fetch filing")
        return

    print(f"✅ Fetched {len(filing_text):,} characters")

    # Extract Principal Stockholders section
    print(f"\n📋 Extracting Principal Stockholders section...")
    principal_section = processor._extract_section(
        filing_text,
        ['PRINCIPAL STOCKHOLDERS', 'PRINCIPAL SHAREHOLDERS', 'SECURITY HOLDERS'],
        max_length=10000
    )

    if principal_section:
        print(f"✅ Found section ({len(principal_section):,} chars)")
        print(f"\n--- PRINCIPAL STOCKHOLDERS EXCERPT ---")
        # Show first 2000 chars to see sponsor mentions
        print(principal_section[:2000])
    else:
        print("⚠️  Principal Stockholders section not found")

    # Search for sponsor mentions
    print(f"\n\n🔍 Searching for sponsor mentions...")
    sponsor_keywords = ['sponsor', 'managed by', 'manager of', 'LLC']

    for keyword in sponsor_keywords:
        if keyword.lower() in filing_text.lower():
            # Find context around keyword
            idx = filing_text.lower().find(keyword.lower())
            context = filing_text[max(0, idx-200):min(len(filing_text), idx+200)]
            print(f"\nFound '{keyword}' at position {idx}:")
            print(f"  ...{context}...")

    db.close()


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
        check_sponsor_in_filing(ticker)
    else:
        # Check DYNX by default
        check_sponsor_in_filing('DYNX')
