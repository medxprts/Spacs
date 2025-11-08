#!/usr/bin/env python3
"""
"Lit Fuse" Early Momentum Scorer
=================================
Scores post-announcement SPACs in the first days after deal announcement
(before redemption data is available).

Focus: PIPE quality, sector hype, and volume turnover as arb investors sell
and retail buys based on excitement.

Components (0-100 points):
1. PIPE Size (0-20): Large PIPE relative to trust (signals deal quality)
2. PIPE Quality (0-20): Tier-1 institutional investors (smart money validation)
3. Hot Sector (0-20): AI, EV, FinTech, etc. (market narrative appeal)
4. Volume Turnover (0-20): High volume = retail excitement vs. arb selling
5. Loaded Gun Bonus (0-20): Pre-deal SPAC quality (momentum carry-forward)

Usage:
    python3 lit_fuse_scorer.py --all           # Score all announced deals
    python3 lit_fuse_scorer.py --ticker CCCX   # Score single deal
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from sqlalchemy import text
import re
from datetime import datetime
import argparse


def parse_pipe_size(pipe_str):
    """
    Parse PIPE size string to numeric millions.

    Examples:
        "$275M" -> 275.0
        "$1.5B" -> 1500.0
        "50000000" -> 50.0
        "275" -> 275.0
    """
    if not pipe_str:
        return None

    pipe_str = str(pipe_str).replace('$', '').replace(',', '').strip().upper()

    # Handle "M" or "B" suffix
    match = re.match(r'([\d.]+)\s*([MB])?', pipe_str)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2)

    if unit == 'B':
        value *= 1000
    elif unit == 'M':
        pass  # Already in millions
    elif value > 1000000:
        # Likely raw dollars (e.g., 50000000)
        value = value / 1_000_000

    return value


def score_pipe_size(pipe_size_millions, trust_cash):
    """
    Score PIPE size relative to trust (0-20 points).

    Large PIPE = strong institutional validation + deal credibility.

    PIPE as % of trust:
        ≥100%: 20 points (exceptional backing)
        75-100%: 17 points (strong)
        50-75%: 14 points (good)
        25-50%: 10 points (moderate)
        10-25%: 5 points (weak)
        <10%: 2 points (minimal)
        No PIPE: 0 points (no validation)
    """
    if not pipe_size_millions or not trust_cash or trust_cash <= 0:
        return 0

    pipe_pct = (pipe_size_millions / trust_cash) * 100

    if pipe_pct >= 100:
        return 20
    elif pipe_pct >= 75:
        return 17
    elif pipe_pct >= 50:
        return 14
    elif pipe_pct >= 25:
        return 10
    elif pipe_pct >= 10:
        return 5
    else:
        return 2


def score_pipe_quality(tier1_count, total_investors):
    """
    Score PIPE quality based on institutional presence (0-20 points).

    Tier-1 investors (BlackRock, Fidelity, etc.) = smart money validation.

    Scoring:
        ≥3 Tier-1: 20 points (elite validation)
        2 Tier-1: 17 points (strong)
        1 Tier-1: 14 points (good)
        ≥5 total investors: 10 points (diversified)
        ≥3 total investors: 5 points (moderate)
        <3 investors: 0 points (weak/unknown)
    """
    if tier1_count >= 3:
        return 20
    elif tier1_count == 2:
        return 17
    elif tier1_count == 1:
        return 14
    elif total_investors >= 5:
        return 10
    elif total_investors >= 3:
        return 5
    else:
        return 0


def score_hot_sector(sector_classified):
    """
    Score based on sector narrative appeal (0-20 points).

    Hot sectors with strong retail appetite and market narrative:
        AI & Machine Learning: 20 points (maximum hype)
        Healthcare Technology: 17 points (strong demand)
        Electric Vehicles: 17 points (strong demand)
        FinTech: 14 points (good interest)
        Cybersecurity: 14 points (good interest)
        Space Technology: 14 points (good interest)
        Clean Energy: 14 points (good interest)
        Blockchain & Crypto: 14 points (good interest)
        Other sectors: 5 points (baseline)
        Unknown: 0 points
    """
    if not sector_classified:
        return 0

    elite_sectors = ['AI & Machine Learning']
    strong_sectors = ['Healthcare Technology', 'Electric Vehicles']
    good_sectors = ['FinTech', 'Cybersecurity', 'Space Technology', 'Clean Energy', 'Blockchain & Crypto']

    if sector_classified in elite_sectors:
        return 20
    elif sector_classified in strong_sectors:
        return 17
    elif sector_classified in good_sectors:
        return 14
    else:
        return 5  # Baseline for any identified sector


def score_volume_turnover(volume, public_float, days_since_announcement):
    """
    Score trading volume/turnover since announcement (0-20 points).

    High volume = retail excitement vs. arb selling pressure.
    Measures daily volume as % of public float.

    Scoring (daily volume as % of float):
        >10%: 20 points (explosive turnover)
        7-10%: 17 points (very high)
        5-7%: 14 points (high)
        3-5%: 10 points (good)
        2-3%: 7 points (moderate)
        1-2%: 4 points (low)
        <1%: 2 points (minimal)
        No data: 0 points

    Note: Uses current daily volume as proxy. Ideally would calculate
    average volume since announcement.
    """
    if not volume or not public_float or public_float <= 0:
        return 0

    # Calculate daily volume as % of public float
    daily_volume_pct = (volume / public_float) * 100

    if daily_volume_pct >= 10.0:
        return 20
    elif daily_volume_pct >= 7.0:
        return 17
    elif daily_volume_pct >= 5.0:
        return 14
    elif daily_volume_pct >= 3.0:
        return 10
    elif daily_volume_pct >= 2.0:
        return 7
    elif daily_volume_pct >= 1.0:
        return 4
    else:
        return 2


def score_loaded_gun_bonus(loaded_gun_score):
    """
    Carry forward Phase 1 "Loaded Gun" score as momentum bonus (0-20 points).

    Strong pre-deal SPAC quality often translates to post-deal momentum.

    Loaded Gun Score → Bonus:
        70-80: 20 points (elite pre-deal quality)
        60-70: 17 points (strong)
        50-60: 14 points (good)
        40-50: 10 points (moderate)
        30-40: 5 points (weak)
        <30: 2 points (minimal)
        Unknown: 0 points
    """
    if not loaded_gun_score:
        return 0

    if loaded_gun_score >= 70:
        return 20
    elif loaded_gun_score >= 60:
        return 17
    elif loaded_gun_score >= 50:
        return 14
    elif loaded_gun_score >= 40:
        return 10
    elif loaded_gun_score >= 30:
        return 5
    else:
        return 2


def calculate_lit_fuse_score(spac, db=None):
    """
    Calculate "Lit Fuse" early momentum score (0-100 points).

    Focuses on factors available in first days after announcement:
    - PIPE size/quality
    - Sector appeal
    - Volume turnover
    - Pre-deal quality (Loaded Gun)

    Returns:
        dict with component scores and total
    """
    # Parse PIPE size
    pipe_size_millions = parse_pipe_size(spac.pipe_size)
    trust_cash_millions = spac.trust_cash / 1_000_000 if spac.trust_cash else None

    # Get PIPE investor counts and Loaded Gun score
    tier1_count = 0
    total_investors = 0
    loaded_gun_score = None

    if db:
        try:
            result = db.execute(
                text("""
                    SELECT
                        COUNT(*) FILTER (WHERE is_tier1 = TRUE) as tier1,
                        COUNT(*) as total
                    FROM pipe_investors
                    WHERE ticker = :ticker
                """),
                {'ticker': spac.ticker}
            ).fetchone()
            if result:
                tier1_count = result[0] or 0
                total_investors = result[1] or 0
        except:
            pass

        try:
            result = db.execute(
                text("SELECT loaded_gun_score FROM opportunity_scores WHERE ticker = :ticker"),
                {'ticker': spac.ticker}
            ).fetchone()
            if result:
                loaded_gun_score = result[0]
        except:
            pass

    # Calculate days since announcement
    days_since_announcement = None
    if spac.announced_date:
        from datetime import datetime
        days_since_announcement = (datetime.now() - spac.announced_date).days

    # Calculate component scores
    pipe_size_score = score_pipe_size(pipe_size_millions, trust_cash_millions)
    pipe_quality_score = score_pipe_quality(tier1_count, total_investors)
    sector_score = score_hot_sector(spac.sector_classified)
    volume_score = score_volume_turnover(spac.volume, spac.public_float, days_since_announcement)
    loaded_gun_bonus = score_loaded_gun_bonus(loaded_gun_score)

    # Total (max 100: 20+20+20+20+20)
    total = pipe_size_score + pipe_quality_score + sector_score + volume_score + loaded_gun_bonus

    return {
        'pipe_size_score': pipe_size_score,
        'pipe_quality_score': pipe_quality_score,
        'sector_score': sector_score,
        'volume_score': volume_score,
        'loaded_gun_bonus': loaded_gun_bonus,
        'lit_fuse_score': total,
        'pipe_size_millions': pipe_size_millions,
        'pipe_pct_of_trust': round((pipe_size_millions / trust_cash_millions * 100), 1) if pipe_size_millions and trust_cash_millions and trust_cash_millions > 0 else None,
        'tier1_count': tier1_count,
        'total_pipe_investors': total_investors,
        'days_since_announcement': days_since_announcement
    }


def save_lit_fuse_score(db, ticker, scores):
    """
    Save or update Lit Fuse score in opportunity_scores table.
    """
    # Check if record exists
    existing = db.execute(
        text("SELECT id FROM opportunity_scores WHERE ticker = :ticker"),
        {'ticker': ticker}
    ).fetchone()

    if existing:
        # Update existing
        db.execute(text("""
            UPDATE opportunity_scores
            SET pipe_size_score = :pipe_size,
                pipe_quality_score = :pipe_quality,
                sector_score = :sector,
                volume_score = :volume,
                lit_fuse_score = :lit_fuse,
                last_calculated = :now
            WHERE ticker = :ticker
        """), {
            'ticker': ticker,
            'pipe_size': scores['pipe_size_score'],
            'pipe_quality': scores['pipe_quality_score'],
            'sector': scores['sector_score'],
            'volume': scores['volume_score'],
            'lit_fuse': scores['lit_fuse_score'],
            'now': datetime.now()
        })
    else:
        # Insert new
        db.execute(text("""
            INSERT INTO opportunity_scores (
                ticker, pipe_size_score, pipe_quality_score, sector_score,
                volume_score, lit_fuse_score, last_calculated
            ) VALUES (
                :ticker, :pipe_size, :pipe_quality, :sector,
                :volume, :lit_fuse, :now
            )
        """), {
            'ticker': ticker,
            'pipe_size': scores['pipe_size_score'],
            'pipe_quality': scores['pipe_quality_score'],
            'sector': scores['sector_score'],
            'volume': scores['volume_score'],
            'lit_fuse': scores['lit_fuse_score'],
            'now': datetime.now()
        })

    db.commit()


def score_all_announced():
    """
    Score all announced deals and save to database.
    """
    db = SessionLocal()
    try:
        # Get all announced SPACs
        spacs = db.query(SPAC).filter(SPAC.deal_status == 'ANNOUNCED').all()

        print(f"\n🔥 Scoring {len(spacs)} announced deals for 'Lit Fuse' early momentum...\n")

        scored_count = 0
        total_scores = []

        for spac in spacs:
            scores = calculate_lit_fuse_score(spac, db)
            save_lit_fuse_score(db, spac.ticker, scores)

            total_scores.append(scores['lit_fuse_score'])
            scored_count += 1

            if scored_count % 10 == 0:
                print(f"✅ Scored {scored_count}/{len(spacs)} deals...")

        print(f"\n✅ Scoring complete!\n")
        print(f"Results:")
        print(f"  Total deals scored: {scored_count}")
        print(f"  Average Lit Fuse score: {sum(total_scores)/len(total_scores):.1f}/100")
        print(f"  Highest score: {max(total_scores)}/100")
        print(f"  Lowest score: {min(total_scores)}/100")

        # Show top early momentum setups
        print(f"\n🔥 Top 10 Early Momentum Setups:\n")

        top_deals = db.execute(text("""
            SELECT
                s.ticker,
                o.lit_fuse_score,
                o.pipe_size_score,
                o.pipe_quality_score,
                o.sector_score,
                o.volume_score,
                s.target,
                s.sector_classified
            FROM spacs s
            INNER JOIN opportunity_scores o ON s.ticker = o.ticker
            WHERE s.deal_status = 'ANNOUNCED'
              AND o.lit_fuse_score IS NOT NULL
            ORDER BY o.lit_fuse_score DESC
            LIMIT 10
        """)).fetchall()

        for idx, deal in enumerate(top_deals, 1):
            print(f"{idx:2d}. {deal.ticker:6s}  {deal.lit_fuse_score:2d}/100  "
                  f"[PIPE:{deal.pipe_size_score:2d} Qual:{deal.pipe_quality_score:2d} "
                  f"Sector:{deal.sector_score:2d} Vol:{deal.volume_score:2d}]  "
                  f"{deal.target[:35] if deal.target else 'TBD'}")

    finally:
        db.close()


def score_single(ticker):
    """
    Score a single deal and display detailed breakdown.
    """
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()

        if not spac:
            print(f"❌ SPAC {ticker} not found")
            return

        if spac.deal_status != 'ANNOUNCED':
            print(f"⚠️  {ticker} status is {spac.deal_status}, not ANNOUNCED")
            return

        scores = calculate_lit_fuse_score(spac, db)
        save_lit_fuse_score(db, ticker, scores)

        print(f"\n🔥 Lit Fuse Early Momentum Score for {ticker}\n")
        print(f"Target: {spac.target}")
        print(f"Sector: {spac.sector_classified or 'Unknown'}")
        print(f"Days Since Announcement: {scores['days_since_announcement'] or 'N/A'}")
        print(f"=" * 70)

        # PIPE details
        if scores['pipe_size_millions']:
            print(f"PIPE Size:         {scores['pipe_size_score']:2d}/20  (${scores['pipe_size_millions']:.0f}M = {scores['pipe_pct_of_trust']:.0f}% of trust)")
        else:
            print(f"PIPE Size:         {scores['pipe_size_score']:2d}/20  (No PIPE data)")

        print(f"PIPE Quality:      {scores['pipe_quality_score']:2d}/20  ({scores['tier1_count']} Tier-1, {scores['total_pipe_investors']} total investors)")
        print(f"Hot Sector:        {scores['sector_score']:2d}/20  ({spac.sector_classified or 'Unknown'})")

        # Volume details
        if spac.volume and spac.public_float and spac.public_float > 0:
            volume_pct = (spac.volume / spac.public_float) * 100
            print(f"Volume Turnover:   {scores['volume_score']:2d}/20  ({volume_pct:.1f}% of float)")
        else:
            print(f"Volume Turnover:   {scores['volume_score']:2d}/20  (No volume data)")

        print(f"Loaded Gun Bonus:  {scores['loaded_gun_bonus']:2d}/20  (Pre-deal quality)")
        print(f"=" * 70)
        print(f"TOTAL LIT FUSE:    {scores['lit_fuse_score']:2d}/100")
        print()

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description='Score SPAC squeeze potential')
    parser.add_argument('--all', action='store_true', help='Score all announced deals')
    parser.add_argument('--ticker', type=str, help='Score single deal by ticker')
    args = parser.parse_args()

    if args.all:
        score_all_announced()
    elif args.ticker:
        score_single(args.ticker.upper())
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
