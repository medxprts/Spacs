#!/usr/bin/env python3
"""
Extract Historical Sponsor Performance from Family Tree CSV

Supplements our current sponsor performance data with historical deals
from 2016-2023 that aren't in our database.

This gives us complete sponsor track records (e.g., Cantor's 2019-2022 deals,
Churchill's CCIV/Lucid legendary deal).
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import time


class HistoricalPerformanceExtractor:
    """Extract performance for historical deals from CSV"""

    def __init__(self, csv_path: str = "sponsor_family_tree_historical.csv"):
        self.csv_path = csv_path
        self.results = []

    def load_completed_deals(self) -> pd.DataFrame:
        """Load completed deals from CSV"""

        df = pd.read_csv(self.csv_path)

        # Filter for completed deals with announcement dates
        completed = df[
            (df['Status/Notes'] == 'Completed') &
            (df['Announced Date'].notna())
        ].copy()

        # Parse dates
        completed['Announced Date'] = pd.to_datetime(completed['Announced Date'], errors='coerce')

        # Remove rows where date parsing failed
        completed = completed[completed['Announced Date'].notna()]

        print(f"Loaded {len(completed)} completed deals with announcement dates")

        return completed

    def fetch_price_on_date(self, ticker: str, target_date: datetime) -> Optional[float]:
        """Fetch closing price for a ticker on a specific date"""
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

    def extract_deal_performance(self, row: pd.Series) -> Optional[Dict]:
        """Extract price performance for a single deal"""

        spac_ticker = row['SPAC Ticker']
        sponsor_raw = row['Sponsor Family']
        target = row['De-SPAC Target']
        announced_date = row['Announced Date']

        # Normalize sponsor names to match our database
        sponsor_mapping = {
            'Churchill Capital (Michael Klein)': 'Churchill Capital',
            'Foley / Cannae Holdings': 'Foley Trasimene / Cannae',
            'Eagle (Sloan & Sagansky)': 'Eagle (Jeff Sagansky)',
            'JAWS (Barry Sternlicht)': 'JAWS',
            'The Gores Group': 'Gores',
        }
        sponsor = sponsor_mapping.get(sponsor_raw, sponsor_raw)

        # Extract post-merger ticker from parentheses (e.g., "Lucid Group (LCID)" -> "LCID")
        # Use post-merger ticker for price fetching since SPAC ticker is delisted
        if '(' in target and ')' in target:
            post_merger_ticker = target.split('(')[1].split(')')[0].strip()
            target_clean = target.split('(')[0].strip()
        else:
            # No post-merger ticker available, try SPAC ticker (will likely fail for completed deals)
            post_merger_ticker = spac_ticker
            target_clean = target

        # Use post-merger ticker for price fetching
        ticker = post_merger_ticker

        print(f"\n   📊 {ticker} → {target_clean}")
        print(f"      Sponsor: {sponsor}")
        print(f"      Announced: {announced_date.date()}")

        # Fetch prices
        price_0d = self.fetch_price_on_date(ticker, announced_date)
        if not price_0d:
            print(f"      ❌ No price data on announcement date")
            return None

        price_1d = self.fetch_price_on_date(ticker, announced_date + timedelta(days=1))
        price_1w = self.fetch_price_on_date(ticker, announced_date + timedelta(days=7))
        price_1m = self.fetch_price_on_date(ticker, announced_date + timedelta(days=30))

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
            'sponsor_family': sponsor,
            'spac_ticker': spac_ticker,
            'ticker': post_merger_ticker,
            'target': target_clean,
            'announced_date': str(announced_date.date()),
            'price_on_announcement': price_0d,
            'price_1d': price_1d,
            'price_1w': price_1w,
            'price_1m': price_1m,
            'pop_1d': round(pop_1d, 1) if pop_1d else None,
            'pop_1w': round(pop_1w, 1) if pop_1w else None,
            'pop_1m': round(pop_1m, 1) if pop_1m else None,
            'source': 'historical_csv'
        }

    def extract_all_deals(self, limit: int = None) -> List[Dict]:
        """Extract performance for all historical deals"""

        df = self.load_completed_deals()

        print(f"\nExtracting historical performance for {len(df)} deals...")
        print("=" * 80)

        results = []
        count = 0

        for idx, row in df.iterrows():
            if limit and count >= limit:
                break

            perf = self.extract_deal_performance(row)
            if perf:
                results.append(perf)
                count += 1

            # Rate limit
            time.sleep(1)

        self.results = results
        return results

    def merge_with_existing_data(self) -> pd.DataFrame:
        """Merge historical data with existing sponsor performance data"""

        print("\n" + "=" * 80)
        print("MERGING HISTORICAL + CURRENT DATA")
        print("=" * 80)

        # Load existing data
        try:
            existing_json = json.load(open('sponsor_performance.json'))
        except FileNotFoundError:
            print("⚠️  No existing sponsor_performance.json found")
            existing_json = {}

        # Add historical deals to existing sponsor data
        for deal in self.results:
            sponsor = deal['sponsor_family']

            if sponsor not in existing_json:
                existing_json[sponsor] = {
                    'sponsor_normalized': sponsor,
                    'total_deals': 0,
                    'tracked_deals': 0,
                    'deals': []
                }

            # Add historical deal
            existing_json[sponsor]['deals'].append({
                'ticker': deal['ticker'],
                'target': deal['target'],
                'announced_date': deal['announced_date'],
                'price_on_announcement': deal['price_on_announcement'],
                'price_1d': deal['price_1d'],
                'price_1w': deal['price_1w'],
                'price_1m': deal['price_1m'],
                'pop_1d': deal['pop_1d'],
                'pop_1w': deal['pop_1w'],
                'pop_1m': deal['pop_1m']
            })

        # Recalculate averages for each sponsor
        summary_rows = []

        for sponsor, data in existing_json.items():
            deals = data.get('deals', [])

            if not deals:
                continue

            # Calculate averages
            pops_1d = [d['pop_1d'] for d in deals if d.get('pop_1d') is not None]
            pops_1w = [d['pop_1w'] for d in deals if d.get('pop_1w') is not None]
            pops_1m = [d['pop_1m'] for d in deals if d.get('pop_1m') is not None]

            avg_1d = round(sum(pops_1d) / len(pops_1d), 1) if pops_1d else None
            avg_1w = round(sum(pops_1w) / len(pops_1w), 1) if pops_1w else None
            avg_1m = round(sum(pops_1m) / len(pops_1m), 1) if pops_1m else None

            # Update sponsor data
            data['total_deals'] = len(deals)
            data['tracked_deals'] = len([d for d in deals if d.get('pop_1d') is not None])
            data['avg_pop_1d'] = avg_1d
            data['avg_pop_1w'] = avg_1w
            data['avg_pop_1m'] = avg_1m

            summary_rows.append({
                'sponsor_normalized': sponsor,
                'total_deals': len(deals),
                'tracked_deals': len([d for d in deals if d.get('pop_1d') is not None]),
                'avg_pop_1d': avg_1d,
                'avg_pop_1w': avg_1w,
                'avg_pop_1m': avg_1m
            })

        # Save updated data
        with open('sponsor_performance_merged.json', 'w') as f:
            json.dump(existing_json, f, indent=2)
        print(f"\n💾 Saved merged data to sponsor_performance_merged.json")

        # Save summary CSV
        df_summary = pd.DataFrame(summary_rows)
        df_summary = df_summary.sort_values('avg_pop_1m', ascending=False)
        df_summary.to_csv('sponsor_performance_summary_merged.csv', index=False)
        print(f"💾 Saved merged summary to sponsor_performance_summary_merged.csv")

        return df_summary

    def print_summary(self):
        """Print summary of extracted historical data"""

        print("\n" + "=" * 80)
        print("HISTORICAL EXTRACTION SUMMARY")
        print("=" * 80)

        df = pd.DataFrame(self.results)

        print(f"\nTotal Historical Deals Extracted: {len(df)}")

        # Group by sponsor
        sponsor_counts = df.groupby('sponsor_family').size().sort_values(ascending=False)

        print(f"\nDeals by Sponsor:")
        for sponsor, count in sponsor_counts.items():
            print(f"   {sponsor:40s}: {count} deals")

        # Top performers
        print(f"\n🏆 TOP HISTORICAL PERFORMERS (1-month pop):")
        top_1m = df.sort_values('pop_1m', ascending=False).head(10)
        for idx, row in top_1m.iterrows():
            if row['pop_1m']:
                print(f"   {row['ticker']:6s} → {row['target'][:30]:30s} | {row['pop_1m']:+6.1f}%")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Extract historical sponsor performance')
    parser.add_argument('--limit', type=int, help='Limit number of deals to extract')
    parser.add_argument('--test', action='store_true', help='Test on 5 deals only')
    args = parser.parse_args()

    extractor = HistoricalPerformanceExtractor()

    try:
        if args.test:
            print("Testing on 5 deals...")
            results = extractor.extract_all_deals(limit=5)
        else:
            limit = args.limit if args.limit else None
            results = extractor.extract_all_deals(limit=limit)

        extractor.print_summary()

        # Merge with existing data
        merged_df = extractor.merge_with_existing_data()

        print(f"\n✅ Complete! Added {len(results)} historical deals to sponsor performance data")

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        print(f"Extracted {len(extractor.results)} deals before interruption")


if __name__ == '__main__':
    main()
