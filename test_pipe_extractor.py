#!/usr/bin/env python3
"""
Test PIPE Extractor Agent on 10-15 recent deals

Runs in DRY-RUN mode (no database updates) to validate extraction accuracy
before integrating with orchestrator.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

import asyncio
from datetime import datetime, timedelta
from database import SessionLocal, SPAC
from agents.pipe_extractor_agent import PIPEExtractorAgent
from utils.sec_filing_fetcher import SECFilingFetcher


class PIPEExtractorTester:
    """Test PIPE extractor on multiple SPACs"""

    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.results = []

    async def test_multiple_spacs(self, limit=15):
        """Test PIPE extraction on recent deals"""

        db = SessionLocal()
        try:
            # Get recent deals
            spacs = db.query(SPAC).filter(
                SPAC.deal_status == 'ANNOUNCED',
                SPAC.announced_date.isnot(None),
                SPAC.announced_date >= datetime.now() - timedelta(days=180)
            ).order_by(SPAC.announced_date.desc()).limit(limit).all()

            print(f"🧪 Testing PIPE Extractor on {len(spacs)} recent deals")
            print(f"{'   Mode: DRY-RUN (no database updates)' if self.dry_run else '   Mode: LIVE (will update database)'}")
            print("=" * 80)

        finally:
            db.close()

        fetcher = SECFilingFetcher()

        for idx, spac in enumerate(spacs, 1):
            print(f"\n{'=' * 80}")
            print(f"Test {idx}/{len(spacs)}: {spac.ticker} → {spac.target}")
            print(f"Announced: {spac.announced_date.strftime('%Y-%m-%d')}")
            print(f"Current PIPE data: has_pipe={spac.has_pipe}, size={spac.pipe_size}, price={spac.pipe_price}")
            print("=" * 80)

            try:
                # Get 8-Ks around announcement date
                if not spac.cik:
                    print(f"   ⚠️  No CIK found for {spac.ticker}")
                    self.results.append({
                        'ticker': spac.ticker,
                        'target': spac.target,
                        'status': 'no_cik',
                        'pipe_data': None
                    })
                    continue

                # Get 8-Ks filed after announcement date (or 30 days before if no announcement)
                after_date = spac.announced_date if spac.announced_date else datetime.now() - timedelta(days=30)
                filings = fetcher.get_8ks_after_date(
                    cik=spac.cik,
                    after_date=after_date - timedelta(days=7),  # Get 8-Ks around announcement
                    count=5
                )

                if not filings:
                    print(f"   ⚠️  No 8-Ks found")
                    self.results.append({
                        'ticker': spac.ticker,
                        'target': spac.target,
                        'status': 'no_filings',
                        'pipe_data': None
                    })
                    continue

                print(f"   📄 Found {len(filings)} recent 8-Ks")

                # Test extractor (with dry-run mode)
                extractor = PIPEExtractorAgent()

                # Temporarily disable database updates for dry-run
                if self.dry_run:
                    original_update = extractor._update_database
                    extractor._update_database = lambda ticker, data: True  # Mock update

                pipe_found = False
                pipe_data = None

                for filing in filings[:3]:  # Check last 3 8-Ks
                    result = await extractor.process_filing(filing, spac.ticker)

                    if result and result.get('success'):
                        pipe_data = result.get('pipe_data')
                        pipe_found = True
                        break

                # Restore original method
                if self.dry_run:
                    extractor._update_database = original_update

                extractor.close()

                if pipe_found:
                    print(f"\n   ✅ PIPE DATA EXTRACTED:")
                    print(f"      has_pipe: {pipe_data.get('has_pipe')}")
                    print(f"      pipe_size: ${pipe_data.get('pipe_size')}M")
                    print(f"      pipe_price: ${pipe_data.get('pipe_price')}")
                    print(f"      pipe_percentage: {pipe_data.get('pipe_percentage')}%")
                    print(f"      pipe_lockup_months: {pipe_data.get('pipe_lockup_months')}")
                    print(f"      confidence: {pipe_data.get('confidence')}")
                    print(f"      reasoning: {pipe_data.get('reasoning')}")

                    self.results.append({
                        'ticker': spac.ticker,
                        'target': spac.target,
                        'status': 'success',
                        'pipe_data': pipe_data
                    })
                else:
                    print(f"   ℹ️  No PIPE data found")
                    self.results.append({
                        'ticker': spac.ticker,
                        'target': spac.target,
                        'status': 'no_pipe',
                        'pipe_data': None
                    })

            except Exception as e:
                print(f"   ❌ Error: {e}")
                import traceback
                traceback.print_exc()
                self.results.append({
                    'ticker': spac.ticker,
                    'target': spac.target,
                    'status': 'error',
                    'error': str(e)
                })

            # Rate limit
            await asyncio.sleep(2)

    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)

        total = len(self.results)
        success = len([r for r in self.results if r['status'] == 'success'])
        no_pipe = len([r for r in self.results if r['status'] == 'no_pipe'])
        errors = len([r for r in self.results if r['status'] == 'error'])
        no_filings = len([r for r in self.results if r['status'] == 'no_filings'])

        print(f"\nTotal Tests: {total}")
        print(f"   ✅ PIPE Extracted: {success}")
        print(f"   ℹ️  No PIPE Found: {no_pipe}")
        print(f"   ⚠️  No Filings: {no_filings}")
        print(f"   ❌ Errors: {errors}")

        if success > 0:
            print(f"\n🎯 SPACs with PIPE:")
            for r in self.results:
                if r['status'] == 'success':
                    pipe = r['pipe_data']
                    print(f"   {r['ticker']:6s} → {r['target'][:40]:40s} | ${pipe.get('pipe_size')}M @ ${pipe.get('pipe_price')}")

        if errors > 0:
            print(f"\n❌ Errors:")
            for r in self.results:
                if r['status'] == 'error':
                    print(f"   {r['ticker']:6s} → {r.get('error', 'Unknown error')}")

        # Validation checks
        print(f"\n📊 VALIDATION CHECKS:")

        format_errors = []
        for r in self.results:
            if r['status'] == 'success':
                pipe = r['pipe_data']

                # Check for format errors (strings instead of numbers)
                if pipe.get('pipe_size') and isinstance(pipe['pipe_size'], str):
                    format_errors.append(f"{r['ticker']}: pipe_size is string '{pipe['pipe_size']}'")
                if pipe.get('pipe_price') and isinstance(pipe['pipe_price'], str):
                    format_errors.append(f"{r['ticker']}: pipe_price is string '{pipe['pipe_price']}'")

        if format_errors:
            print(f"   ❌ Format Errors Found:")
            for err in format_errors:
                print(f"      {err}")
        else:
            print(f"   ✅ No format errors (all numeric fields are numbers)")

        # Confidence check
        low_confidence = [r for r in self.results if r['status'] == 'success' and r['pipe_data'].get('confidence', 100) < 70]
        if low_confidence:
            print(f"\n   ⚠️  Low Confidence Extractions (< 70%):")
            for r in low_confidence:
                print(f"      {r['ticker']}: {r['pipe_data'].get('confidence')}% - {r['pipe_data'].get('reasoning')}")

        print(f"\n{'✅ DRY-RUN COMPLETE - No database changes made' if self.dry_run else '⚠️  LIVE RUN - Database updated'}")


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='Test PIPE extractor')
    parser.add_argument('--live', action='store_true', help='Run in LIVE mode (update database)')
    parser.add_argument('--limit', type=int, default=15, help='Number of SPACs to test (default 15)')
    args = parser.parse_args()

    tester = PIPEExtractorTester(dry_run=not args.live)

    await tester.test_multiple_spacs(limit=args.limit)
    tester.print_summary()


if __name__ == '__main__':
    asyncio.run(main())
