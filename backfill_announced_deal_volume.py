#!/usr/bin/env python3
"""
Backfill Volume Data for Announced SPAC Deals
==============================================
Collects historical volume data since announcement date for all announced deals.

Analyzes cumulative turnover patterns:
- T+1: 1 day after announcement
- T+3: 3 days after announcement
- T+7: 7 days after announcement
- T+30: 30 days after announcement

Identifies successful deals by premium performance and volume patterns.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from daily_volume_tracker import DailyVolumeTracker
from sqlalchemy import text
from datetime import date, timedelta
import time


def backfill_announced_deal_volume(days_back=90, commit=True):
    """
    Backfill historical volume data for announced deals.

    Args:
        days_back: Number of days back to collect (default 90)
        commit: Whether to commit to database (default True)
    """
    db = SessionLocal()
    tracker = DailyVolumeTracker()

    try:
        # Get all announced deals with announcement dates
        spacs = db.query(SPAC).filter(
            SPAC.deal_status.in_(['ANNOUNCED', 'RUMORED_DEAL']),
            SPAC.announced_date.isnot(None)
        ).order_by(SPAC.announced_date.desc()).all()

        print("=" * 100)
        print("BACKFILL VOLUME DATA - ANNOUNCED DEALS")
        print("=" * 100)
        print(f"Found {len(spacs)} announced deals with announcement dates")
        print(f"Collecting volume data from announcement date through today\n")

        total_days_collected = 0
        total_spacs_processed = 0

        for i, spac in enumerate(spacs, 1):
            # Calculate date range
            start_date = spac.announced_date.date() if hasattr(spac.announced_date, 'date') else spac.announced_date
            end_date = date.today()

            # Skip if announcement is in the future
            if start_date > end_date:
                continue

            # Calculate days since announcement
            days_since = (end_date - start_date).days

            print(f"[{i}/{len(spacs)}] {spac.ticker} - {spac.target or 'Unknown'}")
            print(f"  Announced: {start_date} ({days_since} days ago)")

            if days_since == 0:
                print(f"  ⏭️  Announced today - no historical data yet\n")
                continue

            # Collect volume for each day since announcement
            days_collected = 0
            days_failed = 0

            current_date = start_date
            while current_date <= end_date:
                # Check if we already have this data
                existing = db.execute(text("""
                    SELECT id FROM daily_volume
                    WHERE ticker = :ticker AND trade_date = :trade_date
                """), {
                    'ticker': spac.ticker,
                    'trade_date': current_date
                }).fetchone()

                if existing:
                    # Skip if already exists
                    current_date += timedelta(days=1)
                    continue

                # Get volume data
                volume_data = tracker.get_volume_data(spac.ticker, current_date)

                if volume_data and volume_data.get('volume'):
                    # Record to database
                    shares_outstanding = spac.shares_outstanding
                    if shares_outstanding:
                        market_cap = volume_data['price_close'] * shares_outstanding

                        success = tracker.record_daily_volume(
                            ticker=spac.ticker,
                            trade_date=current_date,
                            volume=volume_data['volume'],
                            shares_outstanding=shares_outstanding,
                            price_close=volume_data['price_close'],
                            price_open=volume_data['price_open'],
                            price_high=volume_data['price_high'],
                            price_low=volume_data['price_low'],
                            market_cap=market_cap
                        )

                        if success:
                            days_collected += 1
                        else:
                            days_failed += 1
                else:
                    days_failed += 1

                current_date += timedelta(days=1)

                # Rate limiting
                time.sleep(0.15)

            if days_collected > 0:
                print(f"  ✅ Collected {days_collected} days of volume data")
                total_days_collected += days_collected
                total_spacs_processed += 1
            else:
                print(f"  ⚠️  No new volume data collected")

            if days_failed > 0:
                print(f"  ⚠️  {days_failed} days had no data (weekends/holidays)")

            print()

        print("=" * 100)
        print("BACKFILL COMPLETE")
        print("=" * 100)
        print(f"SPACs processed: {total_spacs_processed}")
        print(f"Total days collected: {total_days_collected}")

    finally:
        db.close()


def analyze_post_announcement_patterns():
    """
    Analyze cumulative turnover and price performance at key intervals after announcement.

    Shows which deals had strongest volume response and price appreciation.
    """
    db = SessionLocal()

    try:
        # Get all announced deals with dates
        spacs = db.query(SPAC).filter(
            SPAC.deal_status.in_(['ANNOUNCED', 'RUMORED_DEAL']),
            SPAC.announced_date.isnot(None)
        ).all()

        print("\n" + "=" * 120)
        print("POST-ANNOUNCEMENT VOLUME & PRICE ANALYSIS")
        print("=" * 120)
        print(f"Analyzing {len(spacs)} announced deals\n")

        results = []

        for spac in spacs:
            announced_date = spac.announced_date.date() if hasattr(spac.announced_date, 'date') else spac.announced_date
            days_since = (date.today() - announced_date).days

            if days_since < 1:
                continue

            # Get volume data for T+1, T+3, T+7, T+30
            intervals = {
                'T+1': min(1, days_since),
                'T+3': min(3, days_since),
                'T+7': min(7, days_since),
                'T+30': min(30, days_since)
            }

            # Calculate cumulative turnover and price change for each interval
            interval_data = {}

            for label, days in intervals.items():
                if days == 0:
                    continue

                end_date = announced_date + timedelta(days=days)

                # Get cumulative volume and price data
                result = db.execute(text("""
                    SELECT
                        SUM(volume) as cumulative_volume,
                        AVG(turnover_rate) as avg_daily_turnover,
                        MAX(turnover_rate) as max_turnover,
                        MIN(price_close) as low_price,
                        MAX(price_close) as high_price,
                        (SELECT price_close FROM daily_volume
                         WHERE ticker = :ticker AND trade_date = :end_date
                         LIMIT 1) as end_price,
                        (SELECT price_close FROM daily_volume
                         WHERE ticker = :ticker AND trade_date >= :start_date
                         ORDER BY trade_date ASC LIMIT 1) as start_price,
                        COUNT(*) as trading_days
                    FROM daily_volume
                    WHERE ticker = :ticker
                      AND trade_date > :start_date
                      AND trade_date <= :end_date
                """), {
                    'ticker': spac.ticker,
                    'start_date': announced_date,
                    'end_date': end_date
                }).fetchone()

                if result and result.trading_days > 0:
                    # Calculate cumulative turnover
                    if spac.shares_outstanding and result.cumulative_volume:
                        cumulative_turnover = (result.cumulative_volume / spac.shares_outstanding) * 100
                    else:
                        cumulative_turnover = None

                    # Calculate return
                    if result.start_price and result.end_price:
                        return_pct = ((result.end_price - result.start_price) / result.start_price) * 100
                    else:
                        return_pct = None

                    interval_data[label] = {
                        'cumulative_turnover': cumulative_turnover,
                        'avg_daily_turnover': float(result.avg_daily_turnover) if result.avg_daily_turnover else None,
                        'max_turnover': float(result.max_turnover) if result.max_turnover else None,
                        'return_pct': return_pct,
                        'high_price': float(result.high_price) if result.high_price else None,
                        'low_price': float(result.low_price) if result.low_price else None,
                        'trading_days': result.trading_days
                    }

            # Only include if we have at least T+1 data
            if 'T+1' in interval_data and interval_data['T+1']['cumulative_turnover']:
                results.append({
                    'ticker': spac.ticker,
                    'target': spac.target or 'Unknown',
                    'announced_date': announced_date,
                    'days_since': days_since,
                    'current_premium': spac.premium,
                    'intervals': interval_data
                })

        if not results:
            print("⚠️  No volume data available yet")
            print("   Run backfill_announced_deal_volume() first")
            return

        # Sort by T+30 return (or T+7 if T+30 not available)
        def sort_key(x):
            if 'T+30' in x['intervals'] and x['intervals']['T+30'].get('return_pct'):
                return x['intervals']['T+30']['return_pct']
            elif 'T+7' in x['intervals'] and x['intervals']['T+7'].get('return_pct'):
                return x['intervals']['T+7']['return_pct']
            elif 'T+3' in x['intervals'] and x['intervals']['T+3'].get('return_pct'):
                return x['intervals']['T+3']['return_pct']
            else:
                return -999

        results.sort(key=sort_key, reverse=True)

        # Print results
        print(f"{'Ticker':<8} {'Target':<25} {'Days':<6} {'Premium':<9} "
              f"{'T+1 Turn':<10} {'T+1 Ret':<9} {'T+3 Turn':<10} {'T+3 Ret':<9} "
              f"{'T+7 Turn':<10} {'T+7 Ret':<9} {'T+30 Turn':<11} {'T+30 Ret':<10}")
        print("─" * 150)

        for r in results[:30]:  # Top 30
            t1 = r['intervals'].get('T+1', {})
            t3 = r['intervals'].get('T+3', {})
            t7 = r['intervals'].get('T+7', {})
            t30 = r['intervals'].get('T+30', {})

            # Format values
            premium_str = f"{r['current_premium']:.1f}%" if r['current_premium'] else "N/A"

            t1_turn = f"{t1.get('cumulative_turnover', 0):.1f}%" if t1.get('cumulative_turnover') else "N/A"
            t1_ret = f"{t1.get('return_pct', 0):+.1f}%" if t1.get('return_pct') is not None else "N/A"

            t3_turn = f"{t3.get('cumulative_turnover', 0):.1f}%" if t3.get('cumulative_turnover') else "N/A"
            t3_ret = f"{t3.get('return_pct', 0):+.1f}%" if t3.get('return_pct') is not None else "N/A"

            t7_turn = f"{t7.get('cumulative_turnover', 0):.1f}%" if t7.get('cumulative_turnover') else "N/A"
            t7_ret = f"{t7.get('return_pct', 0):+.1f}%" if t7.get('return_pct') is not None else "N/A"

            t30_turn = f"{t30.get('cumulative_turnover', 0):.1f}%" if t30.get('cumulative_turnover') else "N/A"
            t30_ret = f"{t30.get('return_pct', 0):+.1f}%" if t30.get('return_pct') is not None else "N/A"

            print(f"{r['ticker']:<8} {r['target'][:24]:<25} {r['days_since']:<6} {premium_str:<9} "
                  f"{t1_turn:<10} {t1_ret:<9} {t3_turn:<10} {t3_ret:<9} "
                  f"{t7_turn:<10} {t7_ret:<9} {t30_turn:<11} {t30_ret:<10}")

        # Summary statistics
        print("\n" + "=" * 150)
        print("PATTERN ANALYSIS - TOP PERFORMERS")
        print("=" * 150)

        # Find best performers at each interval
        for interval in ['T+1', 'T+3', 'T+7', 'T+30']:
            deals_with_data = [r for r in results if interval in r['intervals']
                              and r['intervals'][interval].get('return_pct') is not None]

            if deals_with_data:
                best = max(deals_with_data, key=lambda x: x['intervals'][interval]['return_pct'])
                best_data = best['intervals'][interval]

                print(f"\n🏆 Best {interval} performer: {best['ticker']} ({best['target']})")
                print(f"   Return: {best_data['return_pct']:+.1f}%")
                print(f"   Cumulative turnover: {best_data['cumulative_turnover']:.1f}%")
                print(f"   Avg daily turnover: {best_data['avg_daily_turnover']:.2f}%")
                print(f"   Max daily turnover: {best_data['max_turnover']:.2f}%")

        # Calculate correlation between volume and returns
        print("\n" + "=" * 150)
        print("VOLUME-RETURN CORRELATION")
        print("=" * 150)

        for interval in ['T+1', 'T+3', 'T+7', 'T+30']:
            deals = [r for r in results if interval in r['intervals']
                    and r['intervals'][interval].get('cumulative_turnover') is not None
                    and r['intervals'][interval].get('return_pct') is not None]

            if len(deals) >= 3:
                # Split into high/low volume groups
                deals.sort(key=lambda x: x['intervals'][interval]['cumulative_turnover'], reverse=True)
                mid = len(deals) // 2

                high_vol = deals[:mid]
                low_vol = deals[mid:]

                avg_high_vol_return = sum(d['intervals'][interval]['return_pct'] for d in high_vol) / len(high_vol)
                avg_low_vol_return = sum(d['intervals'][interval]['return_pct'] for d in low_vol) / len(low_vol)

                avg_high_vol_turnover = sum(d['intervals'][interval]['cumulative_turnover'] for d in high_vol) / len(high_vol)
                avg_low_vol_turnover = sum(d['intervals'][interval]['cumulative_turnover'] for d in low_vol) / len(low_vol)

                print(f"\n{interval} ({len(deals)} deals):")
                print(f"  High volume group (n={len(high_vol)}):")
                print(f"    Avg cumulative turnover: {avg_high_vol_turnover:.1f}%")
                print(f"    Avg return: {avg_high_vol_return:+.1f}%")
                print(f"  Low volume group (n={len(low_vol)}):")
                print(f"    Avg cumulative turnover: {avg_low_vol_turnover:.1f}%")
                print(f"    Avg return: {avg_low_vol_return:+.1f}%")
                print(f"  📊 High volume outperformance: {avg_high_vol_return - avg_low_vol_return:+.1f}%")

    finally:
        db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Backfill and analyze volume data for announced deals')
    parser.add_argument('--backfill', action='store_true', help='Backfill historical volume data')
    parser.add_argument('--analyze', action='store_true', help='Analyze post-announcement patterns')
    parser.add_argument('--days-back', type=int, default=90, help='Days back to collect (default: 90)')
    args = parser.parse_args()

    if args.backfill:
        backfill_announced_deal_volume(days_back=args.days_back)

    if args.analyze or not args.backfill:
        analyze_post_announcement_patterns()


if __name__ == '__main__':
    main()
