#!/usr/bin/env python3
"""
Extract Managing Members from S-1/424B4 Filings

Uses existing FilingProcessor infrastructure for SEC filing extraction.

Extracts:
- Managing members of sponsor LLC
- Sponsor mailing address
- State of formation
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from agents.filing_processor import FilingProcessor
from sqlalchemy import text
import json
import time
from typing import Dict, List, Optional
from datetime import datetime


class SponsorManagerExtractor:
    """Extract sponsor managing members using FilingProcessor"""

    def __init__(self):
        self.db = SessionLocal()
        self.filing_processor = FilingProcessor()
        self.results = []

    def close(self):
        self.db.close()

    def extract_for_spac(self, ticker: str) -> Optional[Dict]:
        """Extract sponsor manager info for a single SPAC"""
        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()

        if not spac:
            print(f"❌ SPAC {ticker} not found")
            return None

        if not spac.sponsor:
            print(f"⚠️  {ticker}: No sponsor name in database")
            return None

        print(f"\n[{ticker}] {spac.company}")
        print(f"   Sponsor: {spac.sponsor}")

        # Get filing URL (prefer 424B4, fallback to S-1)
        filing_url = None
        filing_type = None

        if spac.prospectus_424b4_url:
            filing_url = spac.prospectus_424b4_url
            filing_type = '424B4'
        elif spac.s1_filing_url:
            filing_url = spac.s1_filing_url
            filing_type = 'S-1'

        if not filing_url:
            print(f"   ❌ No S-1/424B4 URL in database")
            return {"ticker": ticker, "error": "No filing URL", "sponsor": spac.sponsor}

        print(f"   📄 Fetching {filing_type} filing...")

        # Use FilingProcessor to fetch content
        # Note: Our database URLs are already direct document links, not index pages
        filing_text = self.filing_processor._fetch_document(filing_url)
        if not filing_text:
            print(f"   ❌ Could not fetch document")
            return {"ticker": ticker, "error": "Could not fetch document", "sponsor": spac.sponsor}

        print(f"   📝 Fetched {len(filing_text)} characters")

        # Extract relevant sections
        relevant_text = self._extract_sponsor_sections(filing_text)
        print(f"   📋 Extracted {len(relevant_text)} characters from sponsor sections")

        # Use AI to extract structured data
        print(f"   🤖 Extracting with AI...")
        result = self._extract_with_ai(relevant_text, ticker, spac.sponsor)

        if 'error' not in result:
            managing_members = result.get('managing_members') or []
            if managing_members:
                print(f"   ✅ Sponsor managers: {', '.join(managing_members)}")
            else:
                print(f"   ⚠️  No sponsor managers found")

            board_members = result.get('board_members') or []
            if board_members:
                print(f"   👔 Board members ({len(board_members)}): {', '.join(board_members[:3])}{'...' if len(board_members) > 3 else ''}")
            else:
                print(f"   ⚠️  No board members found")

            sponsor_address = result.get('sponsor_address')
            if sponsor_address:
                print(f"   📍 Address: {sponsor_address[:50]}...")
            else:
                print(f"   📍 Address: Not found")

            formation_state = result.get('formation_state')
            print(f"   🏛️  Formation: {formation_state or 'Not found'}")
            print(f"   💯 Confidence: {result.get('confidence', 0)}%")
        else:
            print(f"   ❌ Extraction failed: {result['error']}")

        result['ticker'] = ticker
        result['sponsor'] = spac.sponsor
        result['sponsor_normalized'] = spac.sponsor_normalized

        return result

    def _extract_sponsor_sections(self, filing_text: str) -> str:
        """Extract sections containing sponsor information"""

        sections = []

        # Section 1: Principal Stockholders
        principal_section = self.filing_processor._extract_section(
            filing_text,
            [
                'PRINCIPAL STOCKHOLDERS',
                'PRINCIPAL SHAREHOLDERS',
                'SECURITY HOLDERS',
                'SECURITY OWNERSHIP'
            ],
            max_length=15000
        )
        if principal_section:
            sections.append(principal_section)

        # Section 2: Certain Relationships
        relationships_section = self.filing_processor._extract_section(
            filing_text,
            [
                'CERTAIN RELATIONSHIPS AND RELATED TRANSACTIONS',
                'CERTAIN RELATIONSHIPS AND RELATED PARTY TRANSACTIONS',
                'RELATED PARTY TRANSACTIONS'
            ],
            max_length=15000
        )
        if relationships_section:
            sections.append(relationships_section)

        # Section 3: Management (increase length since board members are important)
        management_section = self.filing_processor._extract_section(
            filing_text,
            [
                'MANAGEMENT',
                'DIRECTORS AND EXECUTIVE OFFICERS',
                'EXECUTIVE OFFICERS AND DIRECTORS'
            ],
            max_length=15000
        )
        if management_section:
            sections.append(management_section)

        combined = "\n\n=== SECTION BREAK ===\n\n".join(sections)

        # Limit total to 30,000 chars (increased from 20k for board coverage)
        return combined[:30000] if combined else filing_text[:10000]

    def _extract_with_ai(self, filing_text: str, ticker: str, sponsor_name: str) -> Dict:
        """Use AI to extract sponsor managing members and board overlap"""

        prompt = f"""Extract sponsor and board member information from this S-1/424B4 filing excerpt.

SPAC Ticker: {ticker}
Sponsor Name: {sponsor_name}

Extract TWO separate lists:

1. MANAGING MEMBERS of the sponsor LLC:
   - Look in footnotes to "Principal Stockholders" table
   - "(1) The manager of {sponsor_name} is John Smith..."
   - "The sponsor is managed by..."
   - "Our sponsor, {sponsor_name}, a Delaware limited liability company managed by..."

2. BOARD MEMBERS / DIRECTORS of the SPAC:
   - Look in "Management" or "Directors and Executive Officers" section
   - Extract ALL director names (Chairman, Independent Director, etc.)
   - These are the people on the SPAC's board, not the sponsor entity

Also extract:
- Sponsor mailing address
- State of formation (Delaware, Cayman Islands, etc.)

Return ONLY valid JSON in this exact format:
{{
  "managing_members": ["FirstName LastName", ...],
  "board_members": ["FirstName LastName", ...],
  "sponsor_address": "Full mailing address",
  "formation_state": "Delaware",
  "confidence": 0-100,
  "reasoning": "Brief explanation of where you found this info"
}}

Rules:
- managing_members = people who MANAGE the sponsor LLC entity
- board_members = people on the SPAC's board of directors
- All names must be PERSON NAMES only, not company names
- Return null (not empty array) if field not found
- confidence should be high (80-100) if you find explicit mentions, low (10-30) if guessing
- Extract ALL board members you can find (aim for 3-7 names typically)

Filing excerpt:
{filing_text}
"""

        result = self.filing_processor._call_ai(prompt)

        if result:
            return result
        else:
            return {"error": "AI extraction failed", "confidence": 0}

    def extract_all_sponsors(self, limit: int = None) -> List[Dict]:
        """Extract for all unique sponsors"""

        # Get one SPAC per sponsor
        query = text("""
            SELECT DISTINCT ON (sponsor_normalized)
                ticker, sponsor, sponsor_normalized
            FROM spacs
            WHERE sponsor IS NOT NULL
              AND (prospectus_424b4_url IS NOT NULL OR s1_filing_url IS NOT NULL)
            ORDER BY sponsor_normalized, ipo_date DESC
        """ + (f" LIMIT {limit}" if limit else ""))

        results = self.db.execute(query).fetchall()

        print(f"Extracting managing members for {len(results)} unique sponsors")
        print("=" * 80)

        extracted = []
        for row in results:
            result = self.extract_for_spac(row.ticker)
            if result:
                extracted.append(result)
                self.results.append(result)

            # Rate limiting
            time.sleep(2)

        return extracted

    def save_results_to_json(self, filename: str = "sponsor_managers.json"):
        """Save extraction results to JSON file"""
        with open(filename, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"\n💾 Saved results to {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Extract sponsor managing members from S-1/424B4 filings')
    parser.add_argument('--ticker', help='Extract for specific ticker')
    parser.add_argument('--limit', type=int, help='Limit number of sponsors to process')
    parser.add_argument('--test', action='store_true', help='Test on 3 sponsors only')
    args = parser.parse_args()

    extractor = SponsorManagerExtractor()

    try:
        if args.ticker:
            result = extractor.extract_for_spac(args.ticker)
            if result:
                print("\n" + "=" * 80)
                print("RESULT:")
                print(json.dumps(result, indent=2, default=str))
        elif args.test:
            print("Testing on 3 sponsors...")
            results = extractor.extract_all_sponsors(limit=3)
            extractor.save_results_to_json("sponsor_managers_test.json")
        else:
            limit = args.limit if args.limit else None
            results = extractor.extract_all_sponsors(limit=limit)
            extractor.save_results_to_json("sponsor_managers.json")

    finally:
        extractor.close()


if __name__ == '__main__':
    main()
