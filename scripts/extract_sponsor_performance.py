#!/usr/bin/env python3
"""
Extract Sponsor Historical Performance

Calculates price performance for each sponsor family's previous deals:
- Price on announcement day
- Price 1 day, 1 week, 1 month after announcement
- Average "price pop" for the sponsor

This data feeds into Phase 1 scoring for pre-deal SPACs.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from sqlalchemy import text
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import time
import pandas as pd


class SponsorPerformanceExtractor:
    """Extract historical price performance for sponsor families"""

    def __init__(self):
        self.db = SessionLocal()
        self.results = {}

    def close(self):
        self.db.close()

    def get_announced_deals_by_sponsor(self) -> Dict[str, List[SPAC]]:
        """Group announced deals by sponsor family"""

        deals = self.db.query(SPAC).filter(
            SPAC.deal_status.in_(['ANNOUNCED', 'COMPLETED']),
            SPAC.sponsor_normalized != None,
            SPAC.announced_date != None
        ).all()

        sponsor_deals = {}
        for deal in deals:
            sponsor = deal.sponsor_normalized
            if sponsor not in sponsor_deals:
                sponsor_deals[sponsor] = []
            sponsor_deals[sponsor].append(deal)

        return sponsor_deals

    def fetch_price_on_date(self, ticker: str, target_date: datetime) -> Optional[float]:
        """
        Fetch closing price for a ticker on a specific date.

        Returns None if data not available.
        """
        try:
            # Convert to date if datetime
            if isinstance(target_date, datetime):
                target_date = target_date.date()

            # Fetch a week of data around target date to handle weekends/holidays
            start_date = target_date - timedelta(days=5)
            end_date = target_date + timedelta(days=5)

            stock = yf.Ticker(ticker)
            hist = stock.history(start=start_date, end=end_date)

            if hist.empty:
                return None

            # Try to get exact date first
            if target_date in hist.index.date:
                return float(hist.loc[hist.index.date == target_date, 'Close'].iloc[0])

            # If exact date not found, get closest date after target
            future_dates = hist[hist.index.date >= target_date]
            if not future_dates.empty:
                return float(future_dates['Close'].iloc[0])

            # Fall back to closest date before target
            past_dates = hist[hist.index.date < target_date]
            if not past_dates.empty:
                return float(past_dates['Close'].iloc[-1])

            return None

        except Exception as e:
            print(f"   ⚠️  Error fetching {ticker} on {target_date}: {e}")
            return None

    def calculate_price_performance(self, spac: SPAC) -> Optional[Dict]:
        """
        Calculate price performance after deal announcement.

        Returns:
        {
            'ticker': 'CCIV',
            'target': 'Lucid Motors',
            'announced_date': '2021-01-11',
            'price_on_announcement': 12.50,
            'price_1d': 13.20,
            'price_1w': 18.50,
            'price_1m': 24.00,
            'pop_1d': 5.6%,
            'pop_1w': 48.0%,
            'pop_1m': 92.0%
        }
        """
        if not spac.announced_date:
            return None

        announced_date = spac.announced_date
        if isinstance(announced_date, datetime):
            announced_date = announced_date.date()

        print(f"\n   📊 {spac.ticker} → {spac.target}")
        print(f"      Announced: {announced_date}")

        # Fetch prices
        price_0d = self.fetch_price_on_date(spac.ticker, announced_date)
        if not price_0d:
            print(f"      ❌ No price data on announcement date")
            return None

        price_1d = self.fetch_price_on_date(spac.ticker, announced_date + timedelta(days=1))
        price_1w = self.fetch_price_on_date(spac.ticker, announced_date + timedelta(days=7))
        price_1m = self.fetch_price_on_date(spac.ticker, announced_date + timedelta(days=30))

        # Calculate pops
        pop_1d = ((price_1d - price_0d) / price_0d * 100) if price_1d else None
        pop_1w = ((price_1w - price_0d) / price_0d * 100) if price_1w else None
        pop_1m = ((price_1m - price_0d) / price_0d * 100) if price_1m else None

        print(f"      💰 Price on announcement: ${price_0d:.2f}")
        if price_1d:
            print(f"      📈 +1 day:  ${price_1d:.2f} ({pop_1d:+.1f}%)")
        if price_1w:
            print(f"      📈 +1 week: ${price_1w:.2f} ({pop_1w:+.1f}%)")
        if price_1m:
            print(f"      📈 +1 month: ${price_1m:.2f} ({pop_1m:+.1f}%)")

        return {
            'ticker': spac.ticker,
            'target': spac.target,
            'announced_date': str(announced_date),
            'price_on_announcement': price_0d,
            'price_1d': price_1d,
            'price_1w': price_1w,
            'price_1m': price_1m,
            'pop_1d': pop_1d,
            'pop_1w': pop_1w,
            'pop_1m': pop_1m
        }

    def calculate_sponsor_average_performance(self, deals: List[Dict]) -> Dict:
        """Calculate average performance metrics for a sponsor"""

        valid_deals = [d for d in deals if d.get('pop_1d') is not None]

        if not valid_deals:
            return {
                'deal_count': len(deals),
                'avg_pop_1d': None,
                'avg_pop_1w': None,
                'avg_pop_1m': None
            }

        # Calculate averages
        pops_1d = [d['pop_1d'] for d in valid_deals if d.get('pop_1d') is not None]
        pops_1w = [d['pop_1w'] for d in valid_deals if d.get('pop_1w') is not None]
        pops_1m = [d['pop_1m'] for d in valid_deals if d.get('pop_1m') is not None]

        avg_1d = sum(pops_1d) / len(pops_1d) if pops_1d else None
        avg_1w = sum(pops_1w) / len(pops_1w) if pops_1w else None
        avg_1m = sum(pops_1m) / len(pops_1m) if pops_1m else None

        return {
            'deal_count': len(deals),
            'tracked_deals': len(valid_deals),
            'avg_pop_1d': round(avg_1d, 1) if avg_1d else None,
            'avg_pop_1w': round(avg_1w, 1) if avg_1w else None,
            'avg_pop_1m': round(avg_1m, 1) if avg_1m else None
        }

    def extract_all_sponsors(self, limit_sponsors: int = None) -> Dict:
        """Extract performance for all sponsor families"""

        sponsor_deals = self.get_announced_deals_by_sponsor()

        print(f"Found {len(sponsor_deals)} unique sponsors with announced deals")
        print("=" * 80)

        results = {}
        sponsor_count = 0

        for sponsor, deals in sorted(sponsor_deals.items(), key=lambda x: len(x[1]), reverse=True):
            if limit_sponsors and sponsor_count >= limit_sponsors:
                break

            sponsor_count += 1
            print(f"\n🏢 {sponsor} ({len(deals)} deals)")
            print("=" * 80)

            deal_performances = []
            for spac in deals:
                perf = self.calculate_price_performance(spac)
                if perf:
                    deal_performances.append(perf)

                # Rate limit
                time.sleep(1)

            # Calculate sponsor averages
            sponsor_avg = self.calculate_sponsor_average_performance(deal_performances)

            results[sponsor] = {
                'sponsor_normalized': sponsor,
                'total_deals': len(deals),
                'tracked_deals': len(deal_performances),
                'deals': deal_performances,
                **sponsor_avg
            }

            print(f"\n   📊 SPONSOR AVERAGES:")
            if sponsor_avg['avg_pop_1d'] is not None:
                print(f"      +1 day:  {sponsor_avg['avg_pop_1d']:+.1f}%")
                if sponsor_avg['avg_pop_1w'] is not None:
                    print(f"      +1 week: {sponsor_avg['avg_pop_1w']:+.1f}%")
                if sponsor_avg['avg_pop_1m'] is not None:
                    print(f"      +1 month: {sponsor_avg['avg_pop_1m']:+.1f}%")
            else:
                print(f"      No price data available")

        self.results = results
        return results

    def save_to_json(self, filename: str = "sponsor_performance.json"):
        """Save results to JSON file"""
        with open(filename, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\n💾 Saved sponsor performance data to {filename}")

    def save_summary_to_csv(self, filename: str = "sponsor_performance_summary.csv"):
        """Save sponsor averages to CSV"""

        rows = []
        for sponsor, data in self.results.items():
            rows.append({
                'sponsor_normalized': sponsor,
                'total_deals': data['total_deals'],
                'tracked_deals': data['tracked_deals'],
                'avg_pop_1d': data.get('avg_pop_1d'),
                'avg_pop_1w': data.get('avg_pop_1w'),
                'avg_pop_1m': data.get('avg_pop_1m')
            })

        df = pd.DataFrame(rows)
        df = df.sort_values('avg_pop_1w', ascending=False)
        df.to_csv(filename, index=False)
        print(f"💾 Saved sponsor summary to {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Extract sponsor historical performance')
    parser.add_argument('--sponsor', help='Extract for specific sponsor family')
    parser.add_argument('--limit', type=int, help='Limit number of sponsors to process')
    parser.add_argument('--test', action='store_true', help='Test on top 3 sponsors only')
    args = parser.parse_args()

    extractor = SponsorPerformanceExtractor()

    try:
        if args.sponsor:
            # Extract for single sponsor
            sponsor_deals = extractor.get_announced_deals_by_sponsor()
            if args.sponsor not in sponsor_deals:
                print(f"❌ Sponsor '{args.sponsor}' not found")
                return

            deals = sponsor_deals[args.sponsor]
            print(f"Extracting performance for {args.sponsor} ({len(deals)} deals)")

            deal_performances = []
            for spac in deals:
                perf = extractor.calculate_price_performance(spac)
                if perf:
                    deal_performances.append(perf)
                time.sleep(1)

            avg = extractor.calculate_sponsor_average_performance(deal_performances)
            print(f"\n📊 SPONSOR AVERAGES:")
            print(f"   +1 day:  {avg['avg_pop_1d']:+.1f}%")
            print(f"   +1 week: {avg['avg_pop_1w']:+.1f}%")
            print(f"   +1 month: {avg['avg_pop_1m']:+.1f}%")

        elif args.test:
            print("Testing on top 3 sponsors with most deals...")
            results = extractor.extract_all_sponsors(limit_sponsors=3)
            extractor.save_to_json("sponsor_performance_test.json")
            extractor.save_summary_to_csv("sponsor_performance_test.csv")

        else:
            limit = args.limit if args.limit else None
            results = extractor.extract_all_sponsors(limit_sponsors=limit)
            extractor.save_to_json("sponsor_performance.json")
            extractor.save_summary_to_csv("sponsor_performance_summary.csv")

    finally:
        extractor.close()


if __name__ == '__main__':
    main()
