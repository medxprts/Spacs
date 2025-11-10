#!/usr/bin/env python3
"""
Test Volume/Turnover Integration in Phase 2 Scoring
====================================================
Demonstrates how daily_volume table data enhances the Volume/Liquidity score
for announced SPAC deals.

Current scoring: Uses single-day volume as proxy
Enhanced scoring: Uses historical turnover averages, spikes, and trends
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from sqlalchemy import text
from datetime import date, timedelta


def get_volume_metrics(db, ticker, announced_date=None, days=30):
    """
    Get volume/turnover metrics from daily_volume table.

    Args:
        ticker: SPAC ticker
        announced_date: Deal announcement date (for post-announcement metrics)
        days: Number of days to analyze

    Returns:
        dict with turnover metrics
    """
    if announced_date:
        # Get post-announcement metrics only
        start_date = announced_date
    else:
        # Get recent metrics
        start_date = date.today() - timedelta(days=days)

    result = db.execute(text("""
        SELECT
            AVG(turnover_rate) as avg_turnover,
            MAX(turnover_rate) as max_turnover,
            MIN(turnover_rate) as min_turnover,
            COUNT(*) as days_tracked,
            AVG(volume) as avg_volume
        FROM daily_volume
        WHERE ticker = :ticker
          AND trade_date >= :start_date
          AND turnover_rate IS NOT NULL
    """), {
        'ticker': ticker,
        'start_date': start_date
    }).fetchone()

    if not result or result.days_tracked == 0:
        return None

    # Get recent spike (highest turnover day in period)
    spike_result = db.execute(text("""
        SELECT trade_date, turnover_rate, volume
        FROM daily_volume
        WHERE ticker = :ticker
          AND trade_date >= :start_date
          AND turnover_rate IS NOT NULL
        ORDER BY turnover_rate DESC
        LIMIT 1
    """), {
        'ticker': ticker,
        'start_date': start_date
    }).fetchone()

    return {
        'avg_turnover': float(result.avg_turnover),
        'max_turnover': float(result.max_turnover),
        'min_turnover': float(result.min_turnover),
        'days_tracked': result.days_tracked,
        'avg_volume': int(result.avg_volume),
        'spike_date': spike_result.trade_date if spike_result else None,
        'spike_turnover': float(spike_result.turnover_rate) if spike_result else None,
        'spike_volume': int(spike_result.volume) if spike_result else None
    }


def score_volume_enhanced(metrics):
    """
    Enhanced volume scoring using historical turnover data (0-10 points).

    Uses average daily turnover since announcement:
        >5% daily: 10 points (very high liquidity)
        3-5% daily: 8 points (high liquidity)
        2-3% daily: 6 points (good liquidity)
        1-2% daily: 4 points (moderate liquidity)
        0.5-1% daily: 2 points (low liquidity)
        <0.5% daily: 0 points (very low liquidity)

    Bonus: +2 points if spike >10% (major event-driven interest)
    """
    if not metrics:
        return 0

    avg_turnover = metrics['avg_turnover']

    # Base score from average turnover
    if avg_turnover >= 5.0:
        base_score = 10
    elif avg_turnover >= 3.0:
        base_score = 8
    elif avg_turnover >= 2.0:
        base_score = 6
    elif avg_turnover >= 1.0:
        base_score = 4
    elif avg_turnover >= 0.5:
        base_score = 2
    else:
        base_score = 0

    # Bonus for major turnover spike (>10%)
    spike_bonus = 0
    if metrics.get('spike_turnover', 0) > 10.0:
        spike_bonus = 2

    # Cap at 10 points
    return min(base_score + spike_bonus, 10)


def test_announced_deals():
    """Test volume scoring for all announced SPAC deals"""
    db = SessionLocal()

    try:
        # Get all announced deals
        spacs = db.query(SPAC).filter(
            SPAC.deal_status.in_(['ANNOUNCED', 'RUMORED_DEAL'])
        ).order_by(SPAC.ticker).all()

        print("=" * 100)
        print("VOLUME/TURNOVER SCORING TEST - ANNOUNCED DEALS")
        print("=" * 100)
        print(f"Found {len(spacs)} announced deals\n")

        results = []

        for spac in spacs:
            # Get volume metrics since announcement
            metrics = get_volume_metrics(
                db,
                spac.ticker,
                announced_date=spac.announced_date if spac.announced_date else None,
                days=30
            )

            if not metrics:
                continue

            # Calculate enhanced score
            enhanced_score = score_volume_enhanced(metrics)

            # Calculate old score (using current volume only)
            old_score = 0
            if spac.volume and spac.public_float and spac.public_float > 0:
                daily_volume_pct = (spac.volume / spac.public_float) * 100
                if daily_volume_pct >= 5.0:
                    old_score = 10
                elif daily_volume_pct >= 3.0:
                    old_score = 8
                elif daily_volume_pct >= 2.0:
                    old_score = 6
                elif daily_volume_pct >= 1.0:
                    old_score = 4
                elif daily_volume_pct >= 0.5:
                    old_score = 2

            results.append({
                'ticker': spac.ticker,
                'target': spac.target or 'Unknown',
                'announced_date': spac.announced_date,
                'metrics': metrics,
                'old_score': old_score,
                'enhanced_score': enhanced_score,
                'improvement': enhanced_score - old_score
            })

        # Sort by improvement
        results.sort(key=lambda x: x['improvement'], reverse=True)

        print(f"{'Ticker':<8} {'Target':<25} {'Avg Turn':<10} {'Spike':<10} {'Old':<6} {'New':<6} {'Δ':<5}")
        print("─" * 100)

        for r in results:
            m = r['metrics']
            spike_str = f"{m['spike_turnover']:.1f}%" if m.get('spike_turnover') else "N/A"

            print(f"{r['ticker']:<8} {r['target'][:24]:<25} "
                  f"{m['avg_turnover']:>5.2f}%    {spike_str:<10} "
                  f"{r['old_score']:>3}/10  {r['enhanced_score']:>3}/10  "
                  f"{r['improvement']:>+3}")

        # Summary statistics
        print("\n" + "=" * 100)
        print("SUMMARY")
        print("=" * 100)

        if results:
            avg_old = sum(r['old_score'] for r in results) / len(results)
            avg_new = sum(r['enhanced_score'] for r in results) / len(results)
            improved_count = sum(1 for r in results if r['improvement'] > 0)

            print(f"Total deals analyzed: {len(results)}")
            print(f"Average old score: {avg_old:.1f}/10")
            print(f"Average enhanced score: {avg_new:.1f}/10")
            print(f"Deals with improved scores: {improved_count} ({improved_count/len(results)*100:.1f}%)")

            # Find best and worst
            best = max(results, key=lambda x: x['enhanced_score'])
            print(f"\n🏆 Highest liquidity: {best['ticker']} ({best['target']}) - {best['enhanced_score']}/10")
            print(f"   Avg turnover: {best['metrics']['avg_turnover']:.2f}%")
            if best['metrics'].get('spike_turnover'):
                print(f"   Spike: {best['metrics']['spike_turnover']:.2f}% on {best['metrics']['spike_date']}")

    finally:
        db.close()


def test_caep_example():
    """Detailed test for CAEP (recent deal announcement)"""
    db = SessionLocal()

    try:
        spac = db.query(SPAC).filter(SPAC.ticker == 'CAEP').first()

        if not spac:
            print("CAEP not found in database")
            return

        print("\n" + "=" * 100)
        print("DETAILED EXAMPLE: CAEP - AIR Limited Deal")
        print("=" * 100)

        print(f"\nBasic Info:")
        print(f"  Ticker: {spac.ticker}")
        print(f"  Target: {spac.target or 'Unknown'}")
        print(f"  Announced: {spac.announced_date or 'Unknown'}")
        print(f"  Public Float: {spac.public_float:,} shares" if spac.public_float else "  Public Float: Unknown")

        # Get volume metrics
        metrics = get_volume_metrics(
            db,
            'CAEP',
            announced_date=spac.announced_date if spac.announced_date else None,
            days=30
        )

        if metrics:
            print(f"\nVolume Metrics (since {spac.announced_date or 'recent'}):")
            print(f"  Days tracked: {metrics['days_tracked']}")
            print(f"  Avg daily turnover: {metrics['avg_turnover']:.2f}%")
            print(f"  Max turnover: {metrics['max_turnover']:.2f}%")
            print(f"  Min turnover: {metrics['min_turnover']:.2f}%")
            print(f"  Avg daily volume: {metrics['avg_volume']:,} shares")

            if metrics.get('spike_date'):
                print(f"\n  🔥 Turnover spike:")
                print(f"     Date: {metrics['spike_date']}")
                print(f"     Turnover: {metrics['spike_turnover']:.2f}%")
                print(f"     Volume: {metrics['spike_volume']:,} shares")

            # Calculate scores
            enhanced_score = score_volume_enhanced(metrics)

            # Old score
            old_score = 0
            if spac.volume and spac.public_float and spac.public_float > 0:
                current_turnover = (spac.volume / spac.public_float) * 100
                if current_turnover >= 5.0:
                    old_score = 10
                elif current_turnover >= 3.0:
                    old_score = 8
                elif current_turnover >= 2.0:
                    old_score = 6
                elif current_turnover >= 1.0:
                    old_score = 4
                elif current_turnover >= 0.5:
                    old_score = 2

            print(f"\nScoring Comparison:")
            print(f"  Old method (current volume only): {old_score}/10")
            print(f"  Enhanced method (avg turnover): {enhanced_score}/10")
            print(f"  Improvement: {enhanced_score - old_score:+d} points")

        else:
            print("\n⚠️  No volume data available in daily_volume table")
            print("   Run: python3 daily_volume_tracker.py --date 2025-11-07")

    finally:
        db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Test volume/turnover scoring integration')
    parser.add_argument('--all', action='store_true', help='Test all announced deals')
    parser.add_argument('--caep', action='store_true', help='Test CAEP example')
    args = parser.parse_args()

    if args.caep:
        test_caep_example()
    elif args.all:
        test_announced_deals()
    else:
        # Run both by default
        test_caep_example()
        print("\n")
        test_announced_deals()


if __name__ == '__main__':
    main()
