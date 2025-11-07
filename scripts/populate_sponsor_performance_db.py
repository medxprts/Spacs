#!/usr/bin/env python3
"""
Populate sponsor_performance table from JSON data

Takes the sponsor_performance_merged.json file and loads it into
the PostgreSQL sponsor_performance table for use in Phase 1 scoring.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import engine
from sqlalchemy import text
import json
from datetime import datetime

def calculate_sponsor_score(avg_pop_30d, total_deals, successful_rate):
    """
    Calculate sponsor score (0-15 points) based on historical performance

    Scoring criteria:
    - 30-day POP performance (0-10 points)
    - Number of deals (0-3 points for track record)
    - Success rate (0-2 points for reliability)

    Returns:
        int: Score from 0-15
    """
    score = 0

    # 30-day POP scoring (0-10 points)
    if avg_pop_30d is not None:
        if avg_pop_30d >= 30:
            score += 10  # Exceptional (30%+ pop)
        elif avg_pop_30d >= 20:
            score += 8   # Excellent (20-30% pop)
        elif avg_pop_30d >= 10:
            score += 6   # Strong (10-20% pop)
        elif avg_pop_30d >= 5:
            score += 4   # Good (5-10% pop)
        elif avg_pop_30d >= 0:
            score += 2   # Positive (0-5% pop)
        # Negative pop = 0 points

    # Track record scoring (0-3 points)
    if total_deals >= 5:
        score += 3  # Proven sponsor (5+ deals)
    elif total_deals >= 3:
        score += 2  # Experienced sponsor (3-4 deals)
    elif total_deals >= 2:
        score += 1  # Some track record (2 deals)
    # First-time sponsor = 0 points

    # Success rate scoring (0-2 points)
    if successful_rate is not None:
        if successful_rate >= 0.75:  # 75%+ of deals completed
            score += 2
        elif successful_rate >= 0.50:  # 50-75% completed
            score += 1

    return min(score, 15)  # Cap at 15 points


def classify_tier(score):
    """Classify sponsor into performance tier"""
    if score >= 12:
        return 'Top Tier'
    elif score >= 9:
        return 'Strong'
    elif score >= 6:
        return 'Average'
    elif score >= 3:
        return 'Below Average'
    else:
        return 'Poor'


def load_json_to_database():
    """Load sponsor performance data from JSON into PostgreSQL"""

    print("="*80)
    print("LOADING SPONSOR PERFORMANCE DATA INTO DATABASE")
    print("="*80)

    # Load JSON data
    with open('/home/ubuntu/spac-research/sponsor_performance_merged.json', 'r') as f:
        data = json.load(f)

    print(f"\nLoaded data for {len(data)} sponsors")

    inserted = 0
    updated = 0
    skipped = 0

    with engine.connect() as conn:
        for sponsor_name, perf in data.items():
            try:
                total_deals = perf.get('total_deals', 0)
                tracked_deals = perf.get('tracked_deals', 0)

                # Skip if no deals tracked
                if total_deals == 0:
                    skipped += 1
                    continue

                avg_pop_7d = perf.get('avg_pop_1w')
                avg_pop_14d = None  # Not in our data
                avg_pop_30d = perf.get('avg_pop_1m')

                # Calculate success rate (deals with POP data / total deals)
                successful_rate = tracked_deals / total_deals if total_deals > 0 else None

                # Calculate sponsor score
                sponsor_score = calculate_sponsor_score(avg_pop_30d, total_deals, successful_rate)
                tier = classify_tier(sponsor_score)

                # Get best and worst performing deals
                deals = perf.get('deals', [])
                deals_with_pop = [d for d in deals if d.get('pop_1m') is not None]

                best_spac = None
                best_return = None
                worst_spac = None
                worst_return = None

                if deals_with_pop:
                    best = max(deals_with_pop, key=lambda d: d.get('pop_1m', -999))
                    worst = min(deals_with_pop, key=lambda d: d.get('pop_1m', 999))

                    best_spac = best.get('ticker')
                    best_return = best.get('pop_1m')
                    worst_spac = worst.get('ticker')
                    worst_return = worst.get('pop_1m')

                # Build deal ticker list
                deal_tickers = [d.get('ticker') for d in deals if d.get('ticker')]

                # Check if sponsor already exists
                result = conn.execute(
                    text("SELECT id FROM sponsor_performance WHERE sponsor_name = :name"),
                    {'name': sponsor_name}
                )
                existing = result.fetchone()

                if existing:
                    # Update existing
                    conn.execute(text("""
                        UPDATE sponsor_performance
                        SET total_deals = :total,
                            completed_deals = :completed,
                            avg_7day_pop = :pop_7d,
                            avg_14day_pop = :pop_14d,
                            avg_30day_pop = :pop_30d,
                            deal_tickers = :tickers,
                            best_performing_spac = :best_spac,
                            best_performing_return = :best_return,
                            worst_performing_spac = :worst_spac,
                            worst_performing_return = :worst_return,
                            successful_deal_pct = :success_rate,
                            sponsor_score = :score,
                            performance_tier = :tier,
                            data_sources = :sources,
                            last_updated = :now
                        WHERE sponsor_name = :name
                    """), {
                        'name': sponsor_name,
                        'total': total_deals,
                        'completed': tracked_deals,
                        'pop_7d': avg_pop_7d,
                        'pop_14d': avg_pop_14d,
                        'pop_30d': avg_pop_30d,
                        'tickers': deal_tickers,
                        'best_spac': best_spac,
                        'best_return': best_return,
                        'worst_spac': worst_spac,
                        'worst_return': worst_return,
                        'success_rate': successful_rate * 100 if successful_rate else None,
                        'score': sponsor_score,
                        'tier': tier,
                        'sources': 'sponsor_performance_merged.json + historical CSV',
                        'now': datetime.now()
                    })
                    updated += 1
                else:
                    # Insert new
                    conn.execute(text("""
                        INSERT INTO sponsor_performance (
                            sponsor_name, total_deals, completed_deals,
                            avg_7day_pop, avg_14day_pop, avg_30day_pop,
                            deal_tickers, best_performing_spac, best_performing_return,
                            worst_performing_spac, worst_performing_return,
                            successful_deal_pct, sponsor_score, performance_tier,
                            data_sources, last_updated, data_quality
                        ) VALUES (
                            :name, :total, :completed,
                            :pop_7d, :pop_14d, :pop_30d,
                            :tickers, :best_spac, :best_return,
                            :worst_spac, :worst_return,
                            :success_rate, :score, :tier,
                            :sources, :now, 'complete'
                        )
                    """), {
                        'name': sponsor_name,
                        'total': total_deals,
                        'completed': tracked_deals,
                        'pop_7d': avg_pop_7d,
                        'pop_14d': avg_pop_14d,
                        'pop_30d': avg_pop_30d,
                        'tickers': deal_tickers,
                        'best_spac': best_spac,
                        'best_return': best_return,
                        'worst_spac': worst_spac,
                        'worst_return': worst_return,
                        'success_rate': successful_rate * 100 if successful_rate else None,
                        'score': sponsor_score,
                        'tier': tier,
                        'sources': 'sponsor_performance_merged.json + historical CSV',
                        'now': datetime.now()
                    })
                    inserted += 1

                print(f"  ✓ {sponsor_name[:50]:50s} | Score: {sponsor_score:2d}/15 ({tier}) | {total_deals} deals | {avg_pop_30d:+.1f}% avg" if avg_pop_30d else f"  ✓ {sponsor_name[:50]:50s} | Score: {sponsor_score:2d}/15 ({tier}) | {total_deals} deals")

            except Exception as e:
                print(f"  ❌ Error processing {sponsor_name}: {e}")
                continue

        conn.commit()

    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"  Inserted: {inserted}")
    print(f"  Updated: {updated}")
    print(f"  Skipped (no deals): {skipped}")
    print(f"  Total: {inserted + updated + skipped}")
    print(f"{'='*80}")

    # Show top sponsors
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT sponsor_name, total_deals, avg_30day_pop, sponsor_score, performance_tier
            FROM sponsor_performance
            WHERE sponsor_score > 0
            ORDER BY sponsor_score DESC
            LIMIT 15
        """))

        print(f"\n🏆 TOP 15 SPONSORS BY SCORE:")
        print(f"{'='*80}")
        for row in result:
            name, deals, pop, score, tier = row
            pop_str = f"{pop:+.1f}%" if pop else "N/A"
            print(f"  {name[:45]:45s} | {score:2d}/15 ({tier:15s}) | {deals:2d} deals | {pop_str}")


if __name__ == '__main__':
    load_json_to_database()
    print("\n✅ Sponsor performance data loaded into database!")
