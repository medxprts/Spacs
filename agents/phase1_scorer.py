#!/usr/bin/env python3
"""
Phase 1 "Loaded Gun" Scoring Agent
===================================
Calculates pre-deal SPAC quality scores across 7 components:

1. Market Cap Score (0-10): Based on IPO size (liquidity proxy)
2. Banker Score (0-15): Based on underwriter tier (Goldman, JPM, etc.)
3. Sponsor Score (0-15): Based on sponsor track record (historical T+30 performance)
4. Sector Score (0-10): Based on hot sector classification
5. Dilution Score (0-15): Based on founder shares dilution
6. Promote Score (0-10): Based on vesting alignment
7. Social Buzz Score (0-5): Based on Reddit/social media mentions

Total: 0-80 points (Loaded Gun Score)

Usage:
    python3 phase1_scorer.py --all           # Score all pre-deal SPACs
    python3 phase1_scorer.py --ticker CEP    # Score single SPAC
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from sqlalchemy import text
import re
from datetime import datetime
import argparse


def parse_ipo_proceeds(proceeds_str):
    """
    Parse IPO proceeds string to numeric value in millions.

    Examples:
        "$300M" -> 300.0
        "$1.2B" -> 1200.0
        "$69M" -> 69.0
    """
    if not proceeds_str:
        return None

    # Remove dollar sign and whitespace
    proceeds_str = proceeds_str.replace('$', '').strip()

    # Extract number and unit
    match = re.match(r'([\d.]+)([MB]?)', proceeds_str, re.IGNORECASE)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2).upper()

    # Convert to millions
    if unit == 'B':
        value *= 1000
    elif unit == 'M':
        pass  # Already in millions
    else:
        # Assume millions if no unit
        pass

    return value


def score_market_cap(ipo_proceeds_millions):
    """
    Score based on IPO size (0-10 points).

    Thresholds:
        >= $500M: 10 points (mega SPAC)
        >= $300M: 8 points (large SPAC)
        >= $150M: 6 points (mid-size)
        >= $100M: 4 points (standard)
        >= $50M: 2 points (small)
        < $50M: 0 points (micro)
    """
    if ipo_proceeds_millions is None:
        return 0

    if ipo_proceeds_millions >= 500:
        return 10
    elif ipo_proceeds_millions >= 300:
        return 8
    elif ipo_proceeds_millions >= 150:
        return 6
    elif ipo_proceeds_millions >= 100:
        return 4
    elif ipo_proceeds_millions >= 50:
        return 2
    else:
        return 0


def score_banker(banker_tier):
    """
    Score based on investment banker/underwriter tier (0-15 points).

    Tier 1: 15 points (Goldman Sachs, JPMorgan, Citigroup, etc.)
    Tier 2: 10 points (Regional banks, mid-tier underwriters)
    Tier 3: 5 points (Small banks, boutique underwriters)
    None: 0 points
    """
    if banker_tier == 'Tier 1':
        return 15
    elif banker_tier == 'Tier 2':
        return 10
    elif banker_tier == 'Tier 3':
        return 5
    else:
        return 0


def score_sponsor(sponsor_name):
    """
    Score based on sponsor/founder team track record (0-15 points).

    Scoring based on historical SPAC performance:
    - Past SPACs with strong POP (7-day, 14-day, 30-day returns)
    - Number of successful deals completed
    - Average investor returns

    Scoring system:
    - 13-15 points: Top-tier sponsors (exceptional track record, >20% avg returns)
    - 9-12 points: Strong sponsors (proven track record, >10% avg returns)
    - 6-8 points: Average sponsors (moderate track record, >5% avg returns)
    - 3-5 points: Below average sponsors (limited track record or negative returns)
    - 0-2 points: Poor sponsors (poor track record or first-time sponsor)
    """
    if not sponsor_name:
        return 0

    from database import engine
    from sqlalchemy import text

    # Normalize sponsor name for matching (case-insensitive, strip whitespace)
    sponsor_normalized = sponsor_name.strip().lower()

    try:
        with engine.connect() as conn:
            # Try exact match first
            result = conn.execute(
                text("SELECT sponsor_score FROM sponsor_performance WHERE LOWER(sponsor_name) = :name"),
                {'name': sponsor_normalized}
            ).fetchone()

            if result:
                return result[0] or 0

            # Try alias match (check if sponsor name matches any alias)
            result = conn.execute(
                text("""
                    SELECT sponsor_score FROM sponsor_performance
                    WHERE :name = ANY(SELECT LOWER(unnest(sponsor_aliases)))
                    LIMIT 1
                """),
                {'name': sponsor_normalized}
            ).fetchone()

            if result:
                return result[0] or 0

            # Try fuzzy match (contains) on sponsor_name
            result = conn.execute(
                text("SELECT sponsor_score FROM sponsor_performance WHERE LOWER(sponsor_name) LIKE :pattern LIMIT 1"),
                {'pattern': f'%{sponsor_normalized}%'}
            ).fetchone()

            if result:
                return result[0] or 0

            # Try fuzzy match on aliases
            result = conn.execute(
                text("""
                    SELECT sponsor_score FROM sponsor_performance
                    WHERE EXISTS (
                        SELECT 1 FROM unnest(sponsor_aliases) AS alias
                        WHERE LOWER(alias) LIKE :pattern
                    )
                    LIMIT 1
                """),
                {'pattern': f'%{sponsor_normalized}%'}
            ).fetchone()

            if result:
                return result[0] or 0

            # No match found - first-time sponsor
            return 0

    except Exception as e:
        print(f"Warning: Error looking up sponsor '{sponsor_name}': {e}")
        return 0


def score_sector(is_hot_sector):
    """
    Score based on hot sector classification (0-10 points).

    Hot sector: 10 points
    Not hot: 0 points
    """
    if is_hot_sector:
        return 10
    else:
        return 0


def score_dilution(founder_shares, shares_outstanding):
    """
    Score based on founder dilution (0-15 points).

    Lower dilution = better for public shareholders

    Thresholds:
        < 15%: 15 points (excellent alignment)
        < 20%: 12 points (good alignment)
        < 25%: 8 points (moderate)
        < 30%: 4 points (high dilution)
        >= 30%: 0 points (excessive dilution)
    """
    if not founder_shares or not shares_outstanding or shares_outstanding == 0:
        return 0

    dilution_pct = (founder_shares / shares_outstanding) * 100

    if dilution_pct < 15:
        return 15
    elif dilution_pct < 20:
        return 12
    elif dilution_pct < 25:
        return 8
    elif dilution_pct < 30:
        return 4
    else:
        return 0


def score_promote_vesting(vesting_type):
    """
    Score based on promote vesting structure (0-10 points).

    Performance vesting: 10 points (best alignment)
    Time-based/Standard: 5 points (moderate alignment)
    Immediate: 0 points (no alignment)
    None/Unknown: 0 points
    """
    if not vesting_type:
        return 0

    vesting_type_lower = vesting_type.lower()

    if 'performance' in vesting_type_lower:
        return 10
    elif 'time' in vesting_type_lower or 'standard' in vesting_type_lower:
        return 5
    elif 'immediate' in vesting_type_lower:
        return 0
    else:
        return 0


def score_social_buzz(ticker, db):
    """
    Score based on social media buzz from Reddit (0-5 points).

    Fetches buzz_score from social_sentiment table.
    Returns 0 if no buzz data available.
    """
    try:
        result = db.execute(
            text("SELECT buzz_score FROM social_sentiment WHERE ticker = :ticker"),
            {'ticker': ticker}
        ).fetchone()

        if result:
            return result.buzz_score or 0
        else:
            return 0
    except Exception as e:
        # Table doesn't exist yet or other error
        return 0


def calculate_phase1_score(spac, db=None):
    """
    Calculate total Phase 1 score for a SPAC.

    Returns:
        dict with component scores and total (max 80 points)
    """
    # Parse IPO proceeds
    ipo_millions = parse_ipo_proceeds(spac.ipo_proceeds)

    # Calculate component scores
    market_cap = score_market_cap(ipo_millions)
    banker = score_banker(spac.banker_tier)
    sponsor = score_sponsor(spac.sponsor)
    sector = score_sector(spac.is_hot_sector)
    dilution = score_dilution(spac.founder_shares, spac.shares_outstanding_base)
    promote = score_promote_vesting(spac.promote_vesting_type)

    # Social buzz (requires database connection)
    buzz = score_social_buzz(spac.ticker, db) if db else 0

    # Total (max 80: 10+15+15+10+15+10+5)
    total = market_cap + banker + sponsor + sector + dilution + promote + buzz

    return {
        'market_cap_score': market_cap,
        'banker_score': banker,
        'sponsor_score': sponsor,
        'sector_score': sector,
        'dilution_score': dilution,
        'promote_score': promote,
        'buzz_score': buzz,
        'loaded_gun_score': total,
        'ipo_millions': ipo_millions
    }


def save_score(db, ticker, scores):
    """
    Save or update opportunity score in database.
    """
    # Check if score exists
    existing = db.execute(
        text("SELECT id FROM opportunity_scores WHERE ticker = :ticker"),
        {'ticker': ticker}
    ).fetchone()

    if existing:
        # Update existing
        db.execute(text("""
            UPDATE opportunity_scores
            SET market_cap_score = :market_cap,
                banker_score = :banker,
                sponsor_score = :sponsor,
                sector_score = :sector,
                dilution_score = :dilution,
                promote_score = :promote,
                buzz_score = :buzz,
                loaded_gun_score = :loaded_gun,
                last_calculated = :now,
                calculation_version = '1.2'
            WHERE ticker = :ticker
        """), {
            'ticker': ticker,
            'market_cap': scores['market_cap_score'],
            'banker': scores['banker_score'],
            'sponsor': scores['sponsor_score'],
            'sector': scores['sector_score'],
            'dilution': scores['dilution_score'],
            'promote': scores['promote_score'],
            'buzz': scores['buzz_score'],
            'loaded_gun': scores['loaded_gun_score'],
            'now': datetime.now()
        })
    else:
        # Insert new
        db.execute(text("""
            INSERT INTO opportunity_scores (
                ticker, market_cap_score, banker_score, sponsor_score, sector_score,
                dilution_score, promote_score, buzz_score, loaded_gun_score,
                last_calculated, calculation_version
            ) VALUES (
                :ticker, :market_cap, :banker, :sponsor, :sector,
                :dilution, :promote, :buzz, :loaded_gun,
                :now, '1.2'
            )
        """), {
            'ticker': ticker,
            'market_cap': scores['market_cap_score'],
            'banker': scores['banker_score'],
            'sponsor': scores['sponsor_score'],
            'sector': scores['sector_score'],
            'dilution': scores['dilution_score'],
            'promote': scores['promote_score'],
            'buzz': scores['buzz_score'],
            'loaded_gun': scores['loaded_gun_score'],
            'now': datetime.now()
        })

    db.commit()


def score_all_predeal():
    """
    Score all pre-deal SPACs and save to database.
    """
    db = SessionLocal()
    try:
        # Get all pre-deal SPACs
        spacs = db.query(SPAC).filter(SPAC.deal_status == 'SEARCHING').all()

        print(f"\n📊 Scoring {len(spacs)} pre-deal SPACs for Phase 1 'Loaded Gun'...\n")

        scored_count = 0
        total_scores = []

        for spac in spacs:
            scores = calculate_phase1_score(spac, db)
            save_score(db, spac.ticker, scores)

            total_scores.append(scores['loaded_gun_score'])
            scored_count += 1

            # Print progress every 10 SPACs
            if scored_count % 10 == 0:
                print(f"✅ Scored {scored_count}/{len(spacs)} SPACs...")

        print(f"\n✅ Scoring complete!")
        print(f"\nResults:")
        print(f"  Total SPACs scored: {scored_count}")
        print(f"  Average Phase 1 score: {sum(total_scores)/len(total_scores):.1f}/80")
        print(f"  Highest score: {max(total_scores)}/80")
        print(f"  Lowest score: {min(total_scores)}/80")

        # Show top 10
        top_spacs = db.execute(text("""
            SELECT s.ticker, s.company, o.loaded_gun_score,
                   o.market_cap_score, o.banker_score, o.sponsor_score, o.sector_score,
                   o.dilution_score, o.promote_score, o.buzz_score
            FROM spacs s
            JOIN opportunity_scores o ON s.ticker = o.ticker
            WHERE s.deal_status = 'SEARCHING'
            ORDER BY o.loaded_gun_score DESC
            LIMIT 10
        """)).fetchall()

        print(f"\n🔫 Top 10 Loaded Guns:\n")
        for i, spac in enumerate(top_spacs, 1):
            ticker, company, total, mkt, bank, spon, sect, dil, prom, buzz = spac
            print(f"{i:2d}. {ticker:5s} {total:2d}/80  " +
                  f"[Mkt:{mkt:2d} Bank:{bank:2d} Spon:{spon:2d} Sect:{sect:2d} Dil:{dil:2d} Prom:{prom:2d} Buzz:{buzz}]  " +
                  f"{company[:40]}")

    finally:
        db.close()


def score_single(ticker):
    """
    Score a single SPAC and display breakdown.
    """
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()

        if not spac:
            print(f"❌ SPAC {ticker} not found")
            return

        if spac.deal_status != 'SEARCHING':
            print(f"⚠️  {ticker} is not pre-deal (status: {spac.deal_status})")

        scores = calculate_phase1_score(spac, db)
        save_score(db, ticker, scores)

        print(f"\n📊 Phase 1 'Loaded Gun' Score for {ticker}\n")
        print(f"Company: {spac.company}")
        print(f"Sponsor: {spac.sponsor or 'N/A'}")
        print(f"Banker: {spac.banker or 'N/A'}")
        print(f"\nComponent Scores:")
        print(f"  Market Cap:      {scores['market_cap_score']:2d}/10  (IPO: ${scores['ipo_millions']:.0f}M)" if scores['ipo_millions'] else f"  Market Cap:      {scores['market_cap_score']:2d}/10  (IPO: N/A)")
        print(f"  Banker Quality:  {scores['banker_score']:2d}/15  ({spac.banker_tier or 'N/A'})")
        print(f"  Sponsor Quality: {scores['sponsor_score']:2d}/15  (Historical T+30 performance)")
        print(f"  Sector:          {scores['sector_score']:2d}/10  ({'Hot' if spac.is_hot_sector else 'Not hot'})")
        print(f"  Social Buzz:     {scores['buzz_score']}/ 5  (Reddit mentions)")
        print(f"  Dilution:        {scores['dilution_score']:2d}/15  ({(spac.founder_shares/spac.shares_outstanding_base*100):.1f}% founder)" if spac.founder_shares and spac.shares_outstanding_base else f"  Dilution:        {scores['dilution_score']:2d}/15  (N/A)")
        print(f"  Promote Vesting: {scores['promote_score']:2d}/10  ({spac.promote_vesting_type or 'N/A'})")
        print(f"\n🔫 Total Loaded Gun Score: {scores['loaded_gun_score']}/80")

    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Phase 1 Loaded Gun Scoring')
    parser.add_argument('--all', action='store_true', help='Score all pre-deal SPACs')
    parser.add_argument('--ticker', type=str, help='Score single SPAC')

    args = parser.parse_args()

    if args.all:
        score_all_predeal()
    elif args.ticker:
        score_single(args.ticker.upper())
    else:
        print("Usage: python3 phase1_scorer.py --all OR --ticker <TICKER>")
        sys.exit(1)
