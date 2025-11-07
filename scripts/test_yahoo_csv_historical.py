#!/usr/bin/env python3
"""
Test Yahoo Finance CSV Scraping for Delisted SPACs
===================================================
Attempts to recover historical prices for SPACs that yfinance can't fetch
"""

import pandas as pd
import time
from datetime import datetime, timedelta

def get_yahoo_historical_csv(ticker, date, days_offset=0):
    """
    Get historical price using direct Yahoo CSV download (bypasses yfinance library)

    Args:
        ticker: Stock ticker (e.g., "CCIV")
        date: Target date (datetime object)
        days_offset: Days to offset from target date (0 for T+0, 30 for T+30)

    Returns:
        float: Closing price, or None if failed
    """
    target_date = date + timedelta(days=days_offset)

    # Download 20-day window around target (to handle non-trading days)
    start_date = target_date - timedelta(days=10)
    end_date = target_date + timedelta(days=10)

    # Convert to Unix timestamps (Yahoo Finance API format)
    start_ts = int(time.mktime(start_date.timetuple()))
    end_ts = int(time.mktime(end_date.timetuple()))

    url = f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}?" \
          f"period1={start_ts}&period2={end_ts}&interval=1d&events=history&includeAdjustedClose=true"

    try:
        # Download CSV directly
        df = pd.read_csv(url)

        if df.empty:
            return None

        df['Date'] = pd.to_datetime(df['Date'])

        # Find closest trading day to target
        closest_date = min(df['Date'], key=lambda d: abs((d.date() - target_date.date()).days))
        closest_row = df[df['Date'] == closest_date]

        if closest_row.empty:
            return None

        price = closest_row['Close'].values[0]

        return float(price)

    except Exception as e:
        print(f"      ⚠️  Yahoo CSV error: {e}")
        return None


def test_failed_spacs():
    """
    Test Yahoo CSV method on SPACs that failed with yfinance
    """
    # List of failed tickers from our previous run
    failed_deals = [
        {'ticker': 'CCIV', 'deal': 'Lucid', 'date': datetime(2021, 2, 22)},
        {'ticker': 'GHIV', 'deal': 'UWM', 'date': datetime(2020, 9, 23)},
        {'ticker': 'GHVI', 'deal': 'Matterport', 'date': datetime(2021, 2, 8)},
        {'ticker': 'DMYD', 'deal': 'Genius Sports', 'date': datetime(2020, 10, 27)},
        {'ticker': 'DMYI', 'deal': 'IonQ', 'date': datetime(2021, 3, 8)},
        {'ticker': 'DMYQ', 'deal': 'Planet Labs', 'date': datetime(2021, 7, 7)},
        {'ticker': 'IPOB', 'deal': 'Opendoor', 'date': datetime(2020, 9, 15)},
        {'ticker': 'IPOC', 'deal': 'Clover Health', 'date': datetime(2020, 10, 6)},
        {'ticker': 'IPOE', 'deal': 'SoFi', 'date': datetime(2021, 1, 7)},
        {'ticker': 'RTP', 'deal': 'Joby Aviation', 'date': datetime(2021, 2, 24)},
        {'ticker': 'RICE', 'deal': 'Archaea Energy', 'date': datetime(2021, 4, 7)},
        {'ticker': 'RONI', 'deal': 'NET Power', 'date': datetime(2022, 12, 14)},
        {'ticker': 'CFVI', 'deal': 'Rumble', 'date': datetime(2021, 12, 1)},
        {'ticker': 'CFII', 'deal': 'View', 'date': datetime(2020, 11, 30)},
        {'ticker': 'OAC', 'deal': 'Hims & Hers', 'date': datetime(2020, 9, 30)},
        {'ticker': 'OACB', 'deal': 'Alvotech', 'date': datetime(2021, 10, 7)},
    ]

    print("="*100)
    print("TESTING YAHOO FINANCE CSV SCRAPING FOR DELISTED SPACs")
    print("="*100)
    print(f"\nTesting {len(failed_deals)} previously failed tickers...\n")

    success_count = 0
    failed_count = 0
    results = []

    for i, deal in enumerate(failed_deals, 1):
        ticker = deal['ticker']
        target = deal['deal']
        ann_date = deal['date']

        print(f"[{i}/{len(failed_deals)}] {ticker} → {target} (announced {ann_date.date()})...")

        # Get T+0 and T+30 prices
        price_t0 = get_yahoo_historical_csv(ticker, ann_date, days_offset=0)
        time.sleep(0.5)  # Rate limiting

        price_t30 = get_yahoo_historical_csv(ticker, ann_date, days_offset=30)
        time.sleep(0.5)  # Rate limiting

        if price_t0 and price_t30:
            # Calculate returns
            return_pct = ((price_t30 - price_t0) / price_t0) * 100
            pop_pct = ((price_t30 - 10.0) / 10.0) * 100

            print(f"    ✅ SUCCESS: T+0=${price_t0:.2f}, T+30=${price_t30:.2f}, Return: {return_pct:+.1f}%, POP: {pop_pct:+.1f}%")
            success_count += 1
            results.append({
                'ticker': ticker,
                'target': target,
                'status': 'SUCCESS',
                'price_t0': price_t0,
                'price_t30': price_t30,
                'return_pct': return_pct,
                'pop_pct': pop_pct
            })
        else:
            print(f"    ❌ FAILED: Yahoo CSV could not retrieve data")
            failed_count += 1
            results.append({
                'ticker': ticker,
                'target': target,
                'status': 'FAILED',
                'price_t0': price_t0,
                'price_t30': price_t30
            })

        print()

    # Summary
    print("="*100)
    print("SUMMARY:")
    print("="*100)
    print(f"\n  Total tested: {len(failed_deals)}")
    print(f"  ✅ Success: {success_count} ({success_count/len(failed_deals)*100:.1f}%)")
    print(f"  ❌ Failed: {failed_count} ({failed_count/len(failed_deals)*100:.1f}%)")

    if success_count > 0:
        print(f"\n🎯 TOP PERFORMERS (from recovered data):")
        successful = [r for r in results if r['status'] == 'SUCCESS']
        sorted_results = sorted(successful, key=lambda x: x['return_pct'], reverse=True)

        for i, r in enumerate(sorted_results[:10], 1):
            print(f"  {i:2d}. {r['ticker']:6s} → {r['target']:20s} | T+30 Return: {r['return_pct']:+6.1f}% | POP: {r['pop_pct']:+6.1f}%")

    if failed_count > 0:
        print(f"\n⚠️  STILL FAILED (need Polygon.io or SEC extraction):")
        for r in results:
            if r['status'] == 'FAILED':
                print(f"  - {r['ticker']:6s} → {r['target']}")

    # Recommendation
    print(f"\n{'='*100}")
    print("RECOMMENDATION:")
    print(f"{'='*100}\n")

    success_rate = success_count / len(failed_deals) * 100

    if success_rate >= 80:
        print("  ✅ Yahoo CSV method is HIGHLY effective!")
        print("  → Use this as primary method for all historical price fetching")
        print("  → No need for paid APIs")
    elif success_rate >= 50:
        print("  🟡 Yahoo CSV method is MODERATELY effective")
        print(f"  → Recovered {success_count}/{len(failed_deals)} tickers")
        print("  → Consider Polygon.io ($29/mo) for remaining tickers")
    else:
        print("  ❌ Yahoo CSV method is NOT effective enough")
        print(f"  → Only recovered {success_count}/{len(failed_deals)} tickers")
        print("  → Recommend Polygon.io ($29/mo) for comprehensive coverage")

    print()

    return results


if __name__ == '__main__':
    test_failed_spacs()
