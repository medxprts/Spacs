#!/usr/bin/env python3
"""
Add Repeat Sponsor Families with Historical Performance
========================================================
Uses user's comprehensive repeat sponsor list to:
1. Identify repeat sponsor families
2. Find their historical SPACs with deals in our database
3. Calculate T+30 price performance for each deal
4. Rank and score based on historical performance
5. Add to sponsor_performance table
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, engine, SPAC
from sqlalchemy import text
import csv
from collections import defaultdict
from datetime import datetime, timedelta
import yfinance as yf
import time

def load_repeat_sponsor_list():
    """Load user's comprehensive repeat sponsor list"""
    repeat_families = defaultdict(list)

    with open('/tmp/comprehensive_repeat_list.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['Repeat_Sponsor?'] == 'YES':
                family = row['Normalized_Family']
                ticker = row['Ticker']
                repeat_families[family].append(ticker)

    return repeat_families


def load_historical_deals():
    """Load historical deals from user's provided list"""
    historical_deals = {}

    with open('/home/ubuntu/spac-research/data/repeat_sponsor_deals.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            family = row['Sponsor Family']
            ticker = row['Ticker']
            target = row['Target']
            ann_date_str = row['Announcement Date']

            if ann_date_str and ann_date_str != 'TBD':
                try:
                    ann_date = datetime.strptime(ann_date_str, '%Y-%m-%d').date()

                    if family not in historical_deals:
                        historical_deals[family] = []

                    historical_deals[family].append({
                        'ticker': ticker,
                        'target': target,
                        'announced_date': ann_date,
                        'spac_name': row['SPAC']
                    })
                except:
                    pass

    return historical_deals


def find_family_deals(family_name, family_tickers, historical_deals, db):
    """Find all deals from this family (both historical and in database)"""
    # Get sponsor names from current tickers in DB
    sponsors = set()

    for ticker in family_tickers:
        result = db.execute(text("""
            SELECT sponsor
            FROM spacs
            WHERE ticker = :ticker
        """), {'ticker': ticker})

        row = result.fetchone()
        if row and row[0]:
            sponsors.add(row[0])

    # Get historical deals for this family
    deals_data = []

    # Try direct family name match
    if family_name in historical_deals:
        deals_data.extend(historical_deals[family_name])

    # Try alternative names (e.g., "Cantor EP Holdings" vs "Cantor / CF Acquisition")
    for hist_family, deals in historical_deals.items():
        # Check if families are related
        family_lower = family_name.lower()
        hist_lower = hist_family.lower()

        if (family_lower in hist_lower or hist_lower in family_lower or
            any(word in hist_lower for word in family_lower.split() if len(word) > 3)):
            deals_data.extend(deals)

    # Also check our database for any announced/completed deals
    for ticker in family_tickers:
        result = db.execute(text("""
            SELECT ticker, announced_date, target
            FROM spacs
            WHERE ticker = :ticker
              AND deal_status IN ('ANNOUNCED', 'COMPLETED')
              AND announced_date IS NOT NULL
        """), {'ticker': ticker})

        row = result.fetchone()
        if row:
            ticker, ann_date, target = row
            # Check if not already in historical deals
            if not any(d['ticker'] == ticker for d in deals_data):
                deals_data.append({
                    'ticker': ticker,
                    'target': target,
                    'announced_date': ann_date,
                    'spac_name': ticker
                })

    return list(sponsors), deals_data


def get_price_at_date(ticker, date, days_offset=0):
    """Get stock price at a specific date + offset"""
    try:
        target_date = date + timedelta(days=days_offset)

        # Download price data around target date (±10 days for buffer)
        start_date = target_date - timedelta(days=10)
        end_date = target_date + timedelta(days=10)

        data = yf.download(ticker, start=start_date, end=end_date, progress=False)

        if data.empty:
            return None

        # Find closest date
        closest_date = min(data.index, key=lambda d: abs(d.date() - target_date.date()))
        price = data.loc[closest_date]['Close']

        return float(price)

    except Exception as e:
        print(f"    ⚠️  Error getting price for {ticker} at {target_date}: {e}")
        return None


def calculate_deal_performance(spac_data):
    """Calculate T+30 performance for a deal"""
    ticker = spac_data['ticker']
    ann_date = spac_data['announced_date']

    print(f"    Calculating T+30 for {ticker} (announced {ann_date})...")

    # Get T+0 price (announcement date)
    price_t0 = get_price_at_date(ticker, ann_date, days_offset=0)
    if not price_t0:
        print(f"      ⚠️  Could not get T+0 price")
        return None

    # Get T+30 price (30 days after announcement)
    price_t30 = get_price_at_date(ticker, ann_date, days_offset=30)
    if not price_t30:
        print(f"      ⚠️  Could not get T+30 price")
        return None

    # Calculate POP (Price Over Par)
    # Assuming trust value of $10
    pop_pct = ((price_t30 - 10.0) / 10.0) * 100

    # Calculate return from announcement
    return_pct = ((price_t30 - price_t0) / price_t0) * 100

    print(f"      ✓ T+0: ${price_t0:.2f}, T+30: ${price_t30:.2f}, Return: {return_pct:+.1f}%, POP: {pop_pct:+.1f}%")

    return {
        'price_t0': price_t0,
        'price_t30': price_t30,
        'return_pct': return_pct,
        'pop_pct': pop_pct
    }


def calculate_sponsor_score_from_performance(avg_pop, total_deals, successful_rate):
    """Calculate sponsor score (0-15) based on performance"""
    score = 0

    # POP scoring (0-10 points)
    if avg_pop is not None:
        if avg_pop >= 30:
            score += 10
        elif avg_pop >= 20:
            score += 8
        elif avg_pop >= 10:
            score += 6
        elif avg_pop >= 5:
            score += 4
        elif avg_pop >= 0:
            score += 2

    # Track record (0-3 points)
    if total_deals >= 5:
        score += 3
    elif total_deals >= 3:
        score += 2
    elif total_deals >= 2:
        score += 1

    # Success rate (0-2 points)
    if successful_rate is not None:
        if successful_rate >= 0.75:
            score += 2
        elif successful_rate >= 0.50:
            score += 1

    return min(score, 15)


def classify_tier(score):
    """Classify sponsor tier"""
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


def add_sponsor_to_db(family_name, sponsors, performance_data, total_spacs):
    """Add sponsor family to performance database"""

    # Pick primary sponsor name (first one)
    primary_sponsor = list(sponsors)[0] if sponsors else family_name

    # Calculate metrics
    tracked_deals = len([p for p in performance_data if p])

    if tracked_deals > 0:
        avg_pop = sum(p['pop_pct'] for p in performance_data if p) / tracked_deals
        avg_return = sum(p['return_pct'] for p in performance_data if p) / tracked_deals
        successful_rate = tracked_deals / total_spacs if total_spacs > 0 else 0
    else:
        # No performance data - give minimal score for being repeat sponsor
        avg_pop = None
        avg_return = None
        successful_rate = 0

    # Calculate score
    if avg_pop is not None:
        sponsor_score = calculate_sponsor_score_from_performance(avg_pop, total_spacs, successful_rate)
    else:
        # Repeat sponsor with no deal data gets 1-2 points
        sponsor_score = 2 if total_spacs >= 3 else 1

    tier = classify_tier(sponsor_score)

    # Build aliases (all sponsor variations)
    aliases = list(sponsors)

    # Check if already exists
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT id FROM sponsor_performance WHERE sponsor_name = :name"),
            {'name': primary_sponsor}
        ).fetchone()

        if result:
            # Update
            conn.execute(text("""
                UPDATE sponsor_performance
                SET total_deals = :total,
                    completed_deals = :completed,
                    avg_30day_pop = :pop,
                    sponsor_score = :score,
                    performance_tier = :tier,
                    sponsor_aliases = :aliases,
                    successful_deal_pct = :success_pct,
                    data_sources = :sources,
                    data_quality = :quality,
                    last_updated = :now
                WHERE sponsor_name = :name
            """), {
                'name': primary_sponsor,
                'total': total_spacs,
                'completed': tracked_deals,
                'pop': avg_pop,
                'score': sponsor_score,
                'tier': tier,
                'aliases': aliases,
                'success_pct': successful_rate * 100 if successful_rate else None,
                'sources': 'database SPACs + yfinance pricing',
                'quality': 'complete' if tracked_deals > 0 else 'incomplete',
                'now': datetime.now()
            })
        else:
            # Insert
            conn.execute(text("""
                INSERT INTO sponsor_performance (
                    sponsor_name, total_deals, completed_deals,
                    avg_30day_pop, sponsor_score, performance_tier,
                    sponsor_aliases, successful_deal_pct,
                    data_sources, data_quality, last_updated
                ) VALUES (
                    :name, :total, :completed,
                    :pop, :score, :tier,
                    :aliases, :success_pct,
                    :sources, :quality, :now
                )
            """), {
                'name': primary_sponsor,
                'total': total_spacs,
                'completed': tracked_deals,
                'pop': avg_pop,
                'score': sponsor_score,
                'tier': tier,
                'aliases': aliases,
                'success_pct': successful_rate * 100 if successful_rate else None,
                'sources': 'database SPACs + yfinance pricing',
                'quality': 'complete' if tracked_deals > 0 else 'incomplete',
                'now': datetime.now()
            })

        conn.commit()

    return sponsor_score, tier, tracked_deals


def main():
    print("="*100)
    print("ADDING REPEAT SPONSOR FAMILIES WITH HISTORICAL PERFORMANCE")
    print("="*100)

    # Load repeat sponsor list
    print("\n📁 Loading repeat sponsor families...")
    repeat_families = load_repeat_sponsor_list()
    print(f"   Found {len(repeat_families)} repeat sponsor families")

    # Load historical deals
    print("\n📁 Loading historical deal data...")
    historical_deals = load_historical_deals()
    print(f"   Found {len(historical_deals)} sponsor families with historical deals")

    db = SessionLocal()
    try:
        added_count = 0
        with_performance = 0
        without_performance = 0

        results = []

        for family_name, family_tickers in sorted(repeat_families.items()):
            print(f"\n{'='*100}")
            print(f"🔍 {family_name} ({len(family_tickers)} SPACs in list)")

            # Find SPACs from this family in database
            sponsors, spacs_with_deals = find_family_deals(family_name, family_tickers, historical_deals, db)

            if not sponsors:
                print(f"  ⚠️  No SPACs found in database")
                continue

            print(f"  Found {len(spacs_with_deals)} SPACs with deals in database")

            # Calculate performance for each deal
            performance_data = []
            for spac in spacs_with_deals:
                perf = calculate_deal_performance(spac)
                performance_data.append(perf)
                time.sleep(0.5)  # Rate limiting for yfinance

            # Add to database
            score, tier, tracked = add_sponsor_to_db(
                family_name,
                sponsors,
                performance_data,
                len(family_tickers)
            )

            if tracked > 0:
                with_performance += 1
                avg_pop = sum(p['pop_pct'] for p in performance_data if p) / tracked
                print(f"\n  ✅ Added: {score}/15 ({tier}) | {tracked} deals tracked | Avg POP: {avg_pop:+.1f}%")
            else:
                without_performance += 1
                print(f"\n  ✅ Added: {score}/15 ({tier}) | Repeat sponsor, no deal data yet")

            added_count += 1

            results.append({
                'family': family_name,
                'score': score,
                'tier': tier,
                'tracked': tracked,
                'total': len(family_tickers)
            })

        print(f"\n{'='*100}")
        print(f"SUMMARY:")
        print(f"  Families processed: {len(repeat_families)}")
        print(f"  Added to database: {added_count}")
        print(f"  With performance data: {with_performance}")
        print(f"  Without performance data: {without_performance}")
        print(f"{'='*100}")

        # Show top performers
        print(f"\n🏆 TOP 15 REPEAT SPONSORS BY SCORE:\n")
        sorted_results = sorted(results, key=lambda x: (x['score'], x['tracked']), reverse=True)

        for i, r in enumerate(sorted_results[:15], 1):
            print(f"{i:2d}. {r['family'][:40]:40s} | {r['score']:2d}/15 ({r['tier']:15s}) | {r['tracked']}/{r['total']} deals tracked")

    finally:
        db.close()


if __name__ == '__main__':
    main()
