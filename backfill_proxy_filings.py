#!/usr/bin/env python3
"""
Backfill DEF 14A/DEFM14A/PREM14A filings for announced SPACs

This script searches SEC filings for all announced deals to find
proxy statements that may have been missed by the RSS monitor
(which only checks last 10 filings).
"""

import asyncio
import sys
import os
from datetime import datetime, date, timedelta
import requests
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, SPAC
from agents.filing_processor import FilingProcessor

class ProxyBackfiller:
    """Backfills proxy filings for announced deals"""

    def __init__(self):
        self.headers = {
            'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'
        }
        self.processor = FilingProcessor()

    def get_announced_spacs(self) -> List[Dict]:
        """Get all SPACs with announced deals"""
        db = SessionLocal()
        try:
            spacs = db.query(SPAC).filter(
                SPAC.deal_status == 'ANNOUNCED',
                SPAC.cik.isnot(None)
            ).all()

            return [{
                'ticker': spac.ticker,
                'cik': spac.cik,
                'target': spac.target,
                'announced_date': spac.announced_date,
                'vote_date': spac.shareholder_vote_date
            } for spac in spacs]
        finally:
            db.close()

    def search_proxy_filings(self, cik: str, lookback_days: int = 120) -> List[Dict]:
        """Search SEC for proxy filings (DEF 14A, DEFM14A, PREM14A)"""
        try:
            # Fetch more filings (count=100 instead of 10)
            cik_padded = cik.zfill(10)
            url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

            response = requests.get(url, headers=self.headers, timeout=30)
            if response.status_code != 200:
                return []

            data = response.json()
            filings = data['filings']['recent']

            # Filter for proxy filings in lookback window
            cutoff_date = datetime.now() - timedelta(days=lookback_days)
            proxy_filings = []

            for i in range(len(filings['form'])):
                form = filings['form'][i]
                filing_date_str = filings['filingDate'][i]
                accession = filings['accessionNumber'][i]

                # Check if proxy filing
                if form in ['DEF 14A', 'DEFM14A', 'PREM14A', 'DEFA14A', 'DEFR14A']:
                    filing_date = datetime.strptime(filing_date_str, '%Y-%m-%d')

                    # Check if within lookback window
                    if filing_date >= cutoff_date:
                        # Build filing URL
                        cik_no_lead_zeros = str(int(cik))
                        accession_no_dashes = accession.replace('-', '')
                        filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_lead_zeros}/{accession_no_dashes}/{accession}-index.htm"

                        proxy_filings.append({
                            'type': form,
                            'date': filing_date,
                            'url': filing_url,
                            'accession': accession
                        })

            return proxy_filings

        except Exception as e:
            print(f"   ⚠️  Error searching CIK {cik}: {e}")
            return []

    async def process_proxy_filing(self, spac: Dict, filing: Dict) -> bool:
        """Process a proxy filing to extract vote date and deal terms"""
        try:
            print(f"\n{'='*70}")
            print(f"Processing {spac['ticker']} - {filing['type']} filed {filing['date'].strftime('%Y-%m-%d')}")
            print(f"{'='*70}")

            # Prepare filing dict for processor
            filing_dict = {
                'ticker': spac['ticker'],
                'cik': spac['cik'],
                'type': filing['type'],
                'date': filing['date'],
                'url': filing['url']
            }

            # Process with FilingProcessor
            result = await self.processor.process(filing_dict)

            if result:
                print(f"✅ Successfully processed {spac['ticker']} {filing['type']}")
                return True
            else:
                print(f"⚠️  No data extracted from {spac['ticker']} {filing['type']}")
                return False

        except Exception as e:
            print(f"❌ Error processing {spac['ticker']} {filing['type']}: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def backfill_all(self, lookback_days: int = 120):
        """Backfill proxy filings for all announced SPACs"""
        print(f"\n🔍 PROXY FILING BACKFILL")
        print(f"   Lookback window: {lookback_days} days")
        print(f"   Target: DEF 14A, DEFM14A, PREM14A filings\n")

        # Get all announced SPACs
        spacs = self.get_announced_spacs()
        print(f"✓ Found {len(spacs)} SPACs with announced deals\n")

        total_processed = 0
        total_found = 0

        for spac in spacs:
            print(f"\n{'─'*70}")
            print(f"Checking {spac['ticker']} ({spac['target']})")
            print(f"   Announced: {spac['announced_date']}")
            print(f"   Vote date: {spac['vote_date'] or 'NOT SET'}")

            # Search for proxy filings
            proxy_filings = self.search_proxy_filings(spac['cik'], lookback_days)

            if not proxy_filings:
                print(f"   ℹ️  No proxy filings found in last {lookback_days} days")
                continue

            print(f"   ✓ Found {len(proxy_filings)} proxy filing(s)")
            total_found += len(proxy_filings)

            # Process each proxy filing
            for filing in proxy_filings:
                success = await self.process_proxy_filing(spac, filing)
                if success:
                    total_processed += 1

        print(f"\n{'='*70}")
        print(f"BACKFILL COMPLETE")
        print(f"   Proxy filings found: {total_found}")
        print(f"   Successfully processed: {total_processed}")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Backfill proxy filings for announced SPACs')
    parser.add_argument('--lookback', type=int, default=120,
                       help='Days to look back for proxy filings (default: 120)')
    parser.add_argument('--ticker', type=str,
                       help='Only process specific ticker (optional)')

    args = parser.parse_args()

    backfiller = ProxyBackfiller()

    if args.ticker:
        # Single ticker mode
        db = SessionLocal()
        spac = db.query(SPAC).filter(SPAC.ticker == args.ticker).first()
        db.close()

        if not spac:
            print(f"❌ SPAC {args.ticker} not found")
            sys.exit(1)

        if spac.deal_status != 'ANNOUNCED':
            print(f"⚠️  {args.ticker} does not have announced deal (status: {spac.deal_status})")
            sys.exit(1)

        spac_dict = {
            'ticker': spac.ticker,
            'cik': spac.cik,
            'target': spac.target,
            'announced_date': spac.announced_date,
            'vote_date': spac.shareholder_vote_date
        }

        print(f"Processing single SPAC: {args.ticker}")
        proxy_filings = backfiller.search_proxy_filings(spac.cik, args.lookback)

        if not proxy_filings:
            print(f"No proxy filings found for {args.ticker}")
            sys.exit(0)

        for filing in proxy_filings:
            asyncio.run(backfiller.process_proxy_filing(spac_dict, filing))
    else:
        # Batch mode
        asyncio.run(backfiller.backfill_all(args.lookback))
