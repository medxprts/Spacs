#!/usr/bin/env python3
"""
Phase 2 "Deal Quality" Scoring Agent
====================================
Evaluates announced SPAC deals across 6 components:

1. Market Reception (0-20): Premium and price performance since announcement
2. Financing Structure (0-20): PIPE quality, min cash conditions
3. Valuation Quality (0-15): Deal size appropriateness
4. Timeline (0-15): Days to close (faster = better execution)
5. Redemption Risk (0-15): Estimated redemption exposure
6. Loaded Gun Carryover (0-15): Phase 1 quality score (scaled down)

Total: 0-100 points (Deal Quality Score)

Usage:
    python3 phase2_scorer.py --all           # Score all announced deals
    python3 phase2_scorer.py --ticker CCCX   # Score single deal
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from sqlalchemy import text
import re
from datetime import datetime, date
import argparse
from utils.expected_close_normalizer import normalize_expected_close


def parse_deal_value(deal_value_str):
    """
    Parse deal value string to numeric value in millions.

    Examples:
        "$500M" -> 500.0
        "$1.5B" -> 1500.0
        "$275 million" -> 275.0
    """
    if not deal_value_str:
        return None

    deal_value_str = deal_value_str.replace('$', '').replace(',', '').strip().upper()

    match = re.match(r'([\d.]+)\s*([MB])?', deal_value_str)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2)

    if unit == 'B':
        value *= 1000

    return value


def score_market_reception(premium, return_since_announcement):
    """
    Score based on market reception (0-20 points).

    Premium (0-15 points):
        >40%: 15 points (strong market demand)
        30-40%: 12 points
        20-30%: 9 points
        10-20%: 6 points
        0-10%: 3 points
        <0%: 0 points (trading below NAV = distressed)

    Return since announcement (0-5 points):
        >20%: 5 points
        10-20%: 4 points
        0-10%: 3 points
        -10-0%: 1 point
        <-10%: 0 points
    """
    premium_score = 0
    if premium is not None:
        if premium >= 40:
            premium_score = 15
        elif premium >= 30:
            premium_score = 12
        elif premium >= 20:
            premium_score = 9
        elif premium >= 10:
            premium_score = 6
        elif premium >= 0:
            premium_score = 3
        else:
            premium_score = 0

    return_score = 0
    if return_since_announcement is not None:
        if return_since_announcement >= 20:
            return_score = 5
        elif return_since_announcement >= 10:
            return_score = 4
        elif return_since_announcement >= 0:
            return_score = 3
        elif return_since_announcement >= -10:
            return_score = 1

    return premium_score + return_score


def score_financing_structure(pipe_size, min_cash, trust_cash):
    """
    Score based on financing structure (0-20 points).

    PIPE Quality (0-12 points):
        No PIPE needed: 12 points (fully trust-funded = strong)
        PIPE < 20% of trust: 9 points (small PIPE = good)
        PIPE 20-50% of trust: 6 points (moderate)
        PIPE > 50% of trust: 3 points (heavy reliance)
        PIPE > 100% of trust: 0 points (excessive dilution)

    Min Cash Condition (0-8 points):
        No min cash: 8 points (no redemption risk)
        Min cash < 50% trust: 6 points (moderate buffer)
        Min cash 50-80% trust: 3 points (tight)
        Min cash > 80% trust: 0 points (high redemption risk)
    """
    pipe_score = 0
    if pipe_size is None or pipe_size == 0:
        pipe_score = 12  # No PIPE = strongest
    elif trust_cash and trust_cash > 0:
        pipe_ratio = (pipe_size / trust_cash) * 100
        if pipe_ratio < 20:
            pipe_score = 9
        elif pipe_ratio < 50:
            pipe_score = 6
        elif pipe_ratio < 100:
            pipe_score = 3
        else:
            pipe_score = 0
    else:
        # Can't calculate ratio, assume moderate
        pipe_score = 6

    min_cash_score = 0
    if min_cash is None or min_cash == 0:
        min_cash_score = 8  # No min cash requirement
    elif trust_cash and trust_cash > 0:
        min_cash_ratio = (min_cash / trust_cash) * 100
        if min_cash_ratio < 50:
            min_cash_score = 6
        elif min_cash_ratio < 80:
            min_cash_score = 3
        else:
            min_cash_score = 0
    else:
        min_cash_score = 3  # Unknown, assume moderate

    return pipe_score + min_cash_score


def score_valuation_quality(deal_value_millions, trust_cash):
    """
    Score based on valuation appropriateness (0-15 points).

    Deal size relative to trust:
        5-15x trust: 15 points (appropriate leverage)
        3-5x or 15-25x: 12 points (acceptable)
        1-3x or 25-50x: 6 points (too small or stretched)
        <1x or >50x: 0 points (inappropriate)
        Unknown: 7 points (neutral)
    """
    if deal_value_millions is None or trust_cash is None or trust_cash == 0:
        return 7  # Neutral for unknown

    leverage_ratio = deal_value_millions / trust_cash

    if 5 <= leverage_ratio <= 15:
        return 15
    elif (3 <= leverage_ratio < 5) or (15 < leverage_ratio <= 25):
        return 12
    elif (1 <= leverage_ratio < 3) or (25 < leverage_ratio <= 50):
        return 6
    else:
        return 0


def score_timeline(expected_close_str):
    """
    Score based on days to close (0-15 points).

    Faster close = better execution confidence:
        <90 days: 15 points (imminent)
        90-180 days: 12 points (near-term)
        180-270 days: 9 points (moderate)
        270-365 days: 6 points (distant)
        >365 days or unknown: 3 points (uncertain)
    """
    if not expected_close_str:
        return 3

    # Normalize to date
    close_date_str = normalize_expected_close(expected_close_str)
    if not close_date_str:
        return 3

    try:
        close_date = datetime.strptime(close_date_str, '%Y-%m-%d').date()
        days_to_close = (close_date - date.today()).days

        if days_to_close < 0:
            return 0  # Past expected close = problem
        elif days_to_close < 90:
            return 15
        elif days_to_close < 180:
            return 12
        elif days_to_close < 270:
            return 9
        elif days_to_close < 365:
            return 6
        else:
            return 3
    except:
        return 3


def score_redemption_risk(estimated_redemptions, trust_cash, min_cash):
    """
    Score based on redemption risk (0-15 points).

    Lower redemption exposure = better:
        <10% estimated redemptions: 15 points (low risk)
        10-30%: 12 points (moderate risk)
        30-50%: 9 points (elevated risk)
        50-70%: 6 points (high risk)
        >70% or would violate min cash: 0 points (critical risk)
    """
    if estimated_redemptions is None:
        return 10  # Neutral for unknown

    if trust_cash and trust_cash > 0:
        redemption_pct = (estimated_redemptions / trust_cash) * 100

        # Check if redemptions would violate min cash
        if min_cash and (trust_cash - estimated_redemptions) < min_cash:
            return 0  # Min cash violation = critical

        if redemption_pct < 10:
            return 15
        elif redemption_pct < 30:
            return 12
        elif redemption_pct < 50:
            return 9
        elif redemption_pct < 70:
            return 6
        else:
            return 0

    return 10  # Unknown


def score_loaded_gun_carryover(loaded_gun_score):
    """
    Carry over Phase 1 "Loaded Gun" score (0-15 points).

    Scales 0-80 Phase 1 score down to 0-15:
        60-80: 15 points (elite SPAC)
        40-60: 12 points (strong)
        25-40: 9 points (average)
        15-25: 6 points (below average)
        <15: 3 points (weak)
        No score: 7 points (neutral)
    """
    if loaded_gun_score is None:
        return 7

    if loaded_gun_score >= 60:
        return 15
    elif loaded_gun_score >= 40:
        return 12
    elif loaded_gun_score >= 25:
        return 9
    elif loaded_gun_score >= 15:
        return 6
    else:
        return 3


def calculate_phase2_score(spac, db=None):
    """
    Calculate total Phase 2 score for an announced SPAC deal.

    Returns:
        dict with component scores and total (max 100 points)
    """
    # Get Phase 1 score if available
    loaded_gun_score = None
    if db:
        try:
            result = db.execute(
                text("SELECT loaded_gun_score FROM opportunity_scores WHERE ticker = :ticker"),
                {'ticker': spac.ticker}
            ).fetchone()
            if result:
                loaded_gun_score = result[0]
        except:
            pass

    # Parse deal value
    deal_value_millions = parse_deal_value(spac.deal_value) if spac.deal_value else None

    # Calculate component scores
    market_reception = score_market_reception(spac.premium, spac.return_since_announcement)
    financing = score_financing_structure(spac.pipe_size, spac.min_cash, spac.trust_cash)
    valuation = score_valuation_quality(deal_value_millions, spac.trust_cash)
    timeline = score_timeline(spac.expected_close)
    redemption = score_redemption_risk(spac.estimated_redemptions, spac.trust_cash, spac.min_cash)
    loaded_gun = score_loaded_gun_carryover(loaded_gun_score)

    # Total (max 100: 20+20+15+15+15+15)
    total = market_reception + financing + valuation + timeline + redemption + loaded_gun

    return {
        'market_reception_score': market_reception,
        'financing_score': financing,
        'valuation_score': valuation,
        'timeline_score': timeline,
        'redemption_score': redemption,
        'loaded_gun_carryover': loaded_gun,
        'deal_quality_score': total,
        'deal_value_millions': deal_value_millions
    }


def save_phase2_score(db, ticker, scores):
    """
    Save or update Phase 2 deal quality score in opportunity_scores table.
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
            SET market_reception_score = :market,
                financing_score = :financing,
                valuation_score = :valuation,
                timeline_score = :timeline,
                redemption_score = :redemption,
                loaded_gun_carryover = :carryover,
                deal_quality_score = :deal_quality,
                last_calculated = :now
            WHERE ticker = :ticker
        """), {
            'ticker': ticker,
            'market': scores['market_reception_score'],
            'financing': scores['financing_score'],
            'valuation': scores['valuation_score'],
            'timeline': scores['timeline_score'],
            'redemption': scores['redemption_score'],
            'carryover': scores['loaded_gun_carryover'],
            'deal_quality': scores['deal_quality_score'],
            'now': datetime.now()
        })
    else:
        # Insert new
        db.execute(text("""
            INSERT INTO opportunity_scores (
                ticker, market_reception_score, financing_score, valuation_score,
                timeline_score, redemption_score, loaded_gun_carryover, deal_quality_score,
                last_calculated
            ) VALUES (
                :ticker, :market, :financing, :valuation,
                :timeline, :redemption, :carryover, :deal_quality,
                :now
            )
        """), {
            'ticker': ticker,
            'market': scores['market_reception_score'],
            'financing': scores['financing_score'],
            'valuation': scores['valuation_score'],
            'timeline': scores['timeline_score'],
            'redemption': scores['redemption_score'],
            'carryover': scores['loaded_gun_carryover'],
            'deal_quality': scores['deal_quality_score'],
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

        print(f"\n📊 Scoring {len(spacs)} announced deals for Phase 2 'Deal Quality'...\n")

        scored_count = 0
        total_scores = []

        for spac in spacs:
            scores = calculate_phase2_score(spac, db)
            save_phase2_score(db, spac.ticker, scores)

            total_scores.append(scores['deal_quality_score'])
            scored_count += 1

            # Print progress every 10
            if scored_count % 10 == 0:
                print(f"✅ Scored {scored_count}/{len(spacs)} deals...")

        print(f"\n✅ Scoring complete!")
        print(f"\nResults:")
        print(f"  Total deals scored: {scored_count}")
        print(f"  Average Phase 2 score: {sum(total_scores)/len(total_scores):.1f}/100")
        print(f"  Highest score: {max(total_scores)}/100")
        print(f"  Lowest score: {min(total_scores)}/100")

        # Show top 10
        top_deals = db.execute(text("""
            SELECT s.ticker, s.target, o.deal_quality_score,
                   o.market_reception_score, o.financing_score, o.valuation_score,
                   o.timeline_score, o.redemption_score, o.loaded_gun_carryover
            FROM spacs s
            JOIN opportunity_scores o ON s.ticker = o.ticker
            WHERE s.deal_status = 'ANNOUNCED'
            ORDER BY o.deal_quality_score DESC
            LIMIT 10
        """)).fetchall()

        print(f"\n💎 Top 10 Deal Quality:\n")
        for i, deal in enumerate(top_deals, 1):
            ticker, target, total, mkt, fin, val, time, red, gun = deal
            print(f"{i:2d}. {ticker:5s} {total:3d}/100  " +
                  f"[Mkt:{mkt:2d} Fin:{fin:2d} Val:{val:2d} Time:{time:2d} Red:{red:2d} Gun:{gun:2d}]  " +
                  f"{target[:40]}")

    finally:
        db.close()


def score_single(ticker):
    """
    Score a single announced deal and display breakdown.
    """
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()

        if not spac:
            print(f"❌ SPAC {ticker} not found")
            return

        if spac.deal_status != 'ANNOUNCED':
            print(f"⚠️  {ticker} has not announced a deal (status: {spac.deal_status})")
            return

        scores = calculate_phase2_score(spac, db)
        save_phase2_score(db, ticker, scores)

        print(f"\n📊 Phase 2 'Deal Quality' Score for {ticker}\n")
        print(f"Target: {spac.target}")
        print(f"Deal Value: {spac.deal_value or 'N/A'}")
        print(f"\nComponent Scores:")
        print(f"  Market Reception:  {scores['market_reception_score']:2d}/20  (Premium: {spac.premium:.1f}%)")
        print(f"  Financing:         {scores['financing_score']:2d}/20  (PIPE: ${spac.pipe_size}M" if spac.pipe_size else f"  Financing:         {scores['financing_score']:2d}/20  (No PIPE)")
        print(f"  Valuation:         {scores['valuation_score']:2d}/15  (Deal: ${scores['deal_value_millions']:.0f}M)" if scores['deal_value_millions'] else f"  Valuation:         {scores['valuation_score']:2d}/15  (Unknown)")
        print(f"  Timeline:          {scores['timeline_score']:2d}/15  (Close: {spac.expected_close or 'Unknown'})")
        print(f"  Redemption Risk:   {scores['redemption_score']:2d}/15  (Est: {spac.estimated_redemptions or 0})")
        print(f"  Loaded Gun:        {scores['loaded_gun_carryover']:2d}/15  (Phase 1 carryover)")
        print(f"\n💎 Total Deal Quality Score: {scores['deal_quality_score']}/100")

    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Phase 2 Deal Quality Scoring')
    parser.add_argument('--all', action='store_true', help='Score all announced deals')
    parser.add_argument('--ticker', type=str, help='Score single deal')

    args = parser.parse_args()

    if args.all:
        score_all_announced()
    elif args.ticker:
        score_single(args.ticker.upper())
    else:
        print("Usage: python3 phase2_scorer.py --all OR --ticker <TICKER>")
        sys.exit(1)
