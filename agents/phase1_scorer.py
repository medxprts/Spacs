#!/usr/bin/env python3
"""
Phase 1 "Loaded Gun" Scoring Agent
===================================
Calculates pre-deal SPAC quality scores across 6 components:

1. Market Cap Score (0-10): Based on IPO size (liquidity proxy)
2. Banker Score (0-15): Based on underwriter tier (Goldman, JPM, etc.)
3. Sponsor Score (0-15): Based on sponsor track record (TODO: pending historical data)
4. Sector Score (0-10): Based on hot sector classification
5. Dilution Score (0-15): Based on founder shares dilution
6. Promote Score (0-10): Based on vesting alignment

Total: 0-75 points (Loaded Gun Score)

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

    TODO: Implement once historical sponsor performance database is built.
    Currently returns 0 for all sponsors (pending 2016-2019 deal research).

    Future implementation:
    - 15 points: Top-tier sponsors (3+ successful SPACs, avg >20% returns)
    - 10 points: Proven sponsors (2 successful SPACs, avg >10% returns)
    - 5 points: One previous SPAC with positive returns
    - 0 points: First-time sponsor or negative track record
    """
    # Placeholder until historical data is available
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


def calculate_phase1_score(spac):
    """
    Calculate total Phase 1 score for a SPAC.

    Returns:
        dict with component scores and total (max 75 points)
    """
    # Parse IPO proceeds
    ipo_millions = parse_ipo_proceeds(spac.ipo_proceeds)

    # Calculate component scores
    market_cap = score_market_cap(ipo_millions)
    banker = score_banker(spac.banker_tier)
    sponsor = score_sponsor(spac.sponsor)  # TODO: Will be >0 once historical data added
    sector = score_sector(spac.is_hot_sector)
    dilution = score_dilution(spac.founder_shares, spac.shares_outstanding_base)
    promote = score_promote_vesting(spac.promote_vesting_type)

    # Total (max 75: 10+15+15+10+15+10)
    total = market_cap + banker + sponsor + sector + dilution + promote

    return {
        'market_cap_score': market_cap,
        'banker_score': banker,
        'sponsor_score': sponsor,
        'sector_score': sector,
        'dilution_score': dilution,
        'promote_score': promote,
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
                loaded_gun_score = :loaded_gun,
                last_calculated = :now,
                calculation_version = '1.1'
            WHERE ticker = :ticker
        """), {
            'ticker': ticker,
            'market_cap': scores['market_cap_score'],
            'banker': scores['banker_score'],
            'sponsor': scores['sponsor_score'],
            'sector': scores['sector_score'],
            'dilution': scores['dilution_score'],
            'promote': scores['promote_score'],
            'loaded_gun': scores['loaded_gun_score'],
            'now': datetime.now()
        })
    else:
        # Insert new
        db.execute(text("""
            INSERT INTO opportunity_scores (
                ticker, market_cap_score, banker_score, sponsor_score, sector_score,
                dilution_score, promote_score, loaded_gun_score,
                last_calculated, calculation_version
            ) VALUES (
                :ticker, :market_cap, :banker, :sponsor, :sector,
                :dilution, :promote, :loaded_gun,
                :now, '1.1'
            )
        """), {
            'ticker': ticker,
            'market_cap': scores['market_cap_score'],
            'banker': scores['banker_score'],
            'sponsor': scores['sponsor_score'],
            'sector': scores['sector_score'],
            'dilution': scores['dilution_score'],
            'promote': scores['promote_score'],
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
            scores = calculate_phase1_score(spac)
            save_score(db, spac.ticker, scores)

            total_scores.append(scores['loaded_gun_score'])
            scored_count += 1

            # Print progress every 10 SPACs
            if scored_count % 10 == 0:
                print(f"✅ Scored {scored_count}/{len(spacs)} SPACs...")

        print(f"\n✅ Scoring complete!")
        print(f"\nResults:")
        print(f"  Total SPACs scored: {scored_count}")
        print(f"  Average Phase 1 score: {sum(total_scores)/len(total_scores):.1f}/75")
        print(f"  Highest score: {max(total_scores)}/75")
        print(f"  Lowest score: {min(total_scores)}/75")

        # Show top 10
        top_spacs = db.execute(text("""
            SELECT s.ticker, s.company, o.loaded_gun_score,
                   o.market_cap_score, o.banker_score, o.sponsor_score, o.sector_score,
                   o.dilution_score, o.promote_score
            FROM spacs s
            JOIN opportunity_scores o ON s.ticker = o.ticker
            WHERE s.deal_status = 'SEARCHING'
            ORDER BY o.loaded_gun_score DESC
            LIMIT 10
        """)).fetchall()

        print(f"\n🔫 Top 10 Loaded Guns:\n")
        for i, spac in enumerate(top_spacs, 1):
            ticker, company, total, mkt, bank, spon, sect, dil, prom = spac
            print(f"{i:2d}. {ticker:5s} {total:2d}/75  " +
                  f"[Mkt:{mkt:2d} Bank:{bank:2d} Spon:{spon:2d} Sect:{sect:2d} Dil:{dil:2d} Prom:{prom:2d}]  " +
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

        scores = calculate_phase1_score(spac)
        save_score(db, ticker, scores)

        print(f"\n📊 Phase 1 'Loaded Gun' Score for {ticker}\n")
        print(f"Company: {spac.company}")
        print(f"Sponsor: {spac.sponsor or 'N/A'}")
        print(f"Banker: {spac.banker or 'N/A'}")
        print(f"\nComponent Scores:")
        print(f"  Market Cap:      {scores['market_cap_score']:2d}/10  (IPO: ${scores['ipo_millions']:.0f}M)" if scores['ipo_millions'] else f"  Market Cap:      {scores['market_cap_score']:2d}/10  (IPO: N/A)")
        print(f"  Banker Quality:  {scores['banker_score']:2d}/15  ({spac.banker_tier or 'N/A'})")
        print(f"  Sponsor Quality: {scores['sponsor_score']:2d}/15  (Track record: TODO)")
        print(f"  Sector:          {scores['sector_score']:2d}/10  ({'Hot' if spac.is_hot_sector else 'Not hot'})")
        print(f"  Dilution:        {scores['dilution_score']:2d}/15  ({(spac.founder_shares/spac.shares_outstanding_base*100):.1f}% founder)" if spac.founder_shares and spac.shares_outstanding_base else f"  Dilution:        {scores['dilution_score']:2d}/15  (N/A)")
        print(f"  Promote Vesting: {scores['promote_score']:2d}/10  ({spac.promote_vesting_type or 'N/A'})")
        print(f"\n🔫 Total Loaded Gun Score: {scores['loaded_gun_score']}/75")

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
