#!/usr/bin/env python3
"""
Test Phase 1 "Loaded Gun" Scoring with Current Data

Scores pre-deal SPACs on available factors to identify best opportunities.

Available Factors:
1. Market Cap (smaller = more nimble)
2. Premium to NAV (closer to NAV = better risk/reward)
3. Days to Deadline (more time = better)
4. Sponsor Track Record (based on normalized sponsor families)
5. Trust Per Share (higher = more cash per share)

Missing Factors (to be added):
- Dilution (founder shares %)
- Promote vesting structure
- Sector focus
- Sponsor historical performance (price pops)
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from sqlalchemy import text
from datetime import datetime, date
from typing import Dict, List
import pandas as pd


class Phase1Scorer:
    """Score pre-deal SPACs on 'Loaded Gun' factors"""

    def __init__(self):
        self.db = SessionLocal()

    def close(self):
        self.db.close()

    def get_scorable_spacs(self) -> List[SPAC]:
        """Get pre-deal SPACs with sufficient data for scoring"""

        spacs = self.db.query(SPAC).filter(
            SPAC.deal_status == 'SEARCHING',
            SPAC.price != None,
            SPAC.trust_value != None,
            SPAC.shares_outstanding != None,
            SPAC.deadline_date != None
        ).all()

        return spacs

    def calculate_market_cap(self, spac: SPAC) -> float:
        """Calculate market cap in millions"""
        if not spac.shares_outstanding or not spac.price:
            return None

        # shares_outstanding is in actual shares, price is per share
        # Return market cap in millions
        return (spac.shares_outstanding * spac.price) / 1_000_000

    def calculate_days_to_deadline(self, spac: SPAC) -> int:
        """Calculate days remaining to deadline"""
        if not spac.deadline_date:
            return None

        today = datetime.now().date()
        # Convert deadline_date to date if it's datetime
        deadline = spac.deadline_date.date() if isinstance(spac.deadline_date, datetime) else spac.deadline_date
        delta = deadline - today
        return delta.days

    def score_market_cap(self, market_cap: float) -> Dict:
        """
        Score market cap (smaller = more nimble, easier to move)

        Scoring:
        - <$100M: 100 points
        - $100-200M: 80 points
        - $200-300M: 60 points
        - $300-500M: 40 points
        - >$500M: 20 points
        """
        if market_cap is None:
            return {'score': 0, 'reasoning': 'No market cap data'}

        if market_cap < 100:
            return {'score': 100, 'reasoning': f'Small cap (${market_cap:.1f}M) - very nimble'}
        elif market_cap < 200:
            return {'score': 80, 'reasoning': f'Medium cap (${market_cap:.1f}M) - nimble'}
        elif market_cap < 300:
            return {'score': 60, 'reasoning': f'Medium cap (${market_cap:.1f}M) - moderate'}
        elif market_cap < 500:
            return {'score': 40, 'reasoning': f'Large cap (${market_cap:.1f}M) - less nimble'}
        else:
            return {'score': 20, 'reasoning': f'Very large cap (${market_cap:.1f}M) - harder to move'}

    def score_premium(self, premium: float) -> Dict:
        """
        Score premium to NAV (closer to NAV = better risk/reward)

        Scoring:
        - <2%: 100 points (near NAV, minimal downside)
        - 2-5%: 80 points (slight premium, good risk/reward)
        - 5-10%: 60 points (moderate premium)
        - 10-20%: 40 points (high premium, more risk)
        - >20%: 20 points (very high premium, significant risk)
        """
        if premium is None:
            return {'score': 0, 'reasoning': 'No premium data'}

        if premium < 2:
            return {'score': 100, 'reasoning': f'{premium:.1f}% premium - near NAV, minimal downside'}
        elif premium < 5:
            return {'score': 80, 'reasoning': f'{premium:.1f}% premium - slight premium, good risk/reward'}
        elif premium < 10:
            return {'score': 60, 'reasoning': f'{premium:.1f}% premium - moderate premium'}
        elif premium < 20:
            return {'score': 40, 'reasoning': f'{premium:.1f}% premium - high premium, more risk'}
        else:
            return {'score': 20, 'reasoning': f'{premium:.1f}% premium - very high premium, significant risk'}

    def score_time_to_deadline(self, days: int) -> Dict:
        """
        Score time to deadline (more time = better optionality)

        Scoring:
        - >365 days: 100 points (plenty of time)
        - 180-365 days: 80 points (good time)
        - 90-180 days: 60 points (moderate urgency)
        - 30-90 days: 40 points (urgent)
        - <30 days: 20 points (very urgent, liquidation risk)
        """
        if days is None:
            return {'score': 0, 'reasoning': 'No deadline data'}

        if days > 365:
            return {'score': 100, 'reasoning': f'{days} days - plenty of time'}
        elif days > 180:
            return {'score': 80, 'reasoning': f'{days} days - good time to find deal'}
        elif days > 90:
            return {'score': 60, 'reasoning': f'{days} days - moderate urgency'}
        elif days > 30:
            return {'score': 40, 'reasoning': f'{days} days - urgent, needs deal soon'}
        else:
            return {'score': 20, 'reasoning': f'{days} days - very urgent, liquidation risk'}

    def score_sponsor_track_record(self, sponsor_normalized: str) -> Dict:
        """
        Score sponsor based on historical price performance after deal announcements.

        Uses sponsor_performance_summary.csv data to score based on avg month 1 performance.

        Scoring:
        - >50% avg: 100 points (exceptional - Cantor Fitzgerald)
        - 20-50%: 90 points (great)
        - 10-20%: 80 points (very good)
        - 5-10%: 70 points (good)
        - 1-5%: 60 points (moderate)
        - 0-1%: 50 points (flat)
        - <0%: 30 points (poor track record)
        - No data: 40 points (unproven)
        """
        if not sponsor_normalized:
            return {'score': 0, 'reasoning': 'No sponsor data'}

        # Load sponsor performance data
        try:
            import os
            perf_file = os.path.join(os.path.dirname(__file__), '..', 'sponsor_performance_summary.csv')
            df = pd.read_csv(perf_file)

            sponsor_row = df[df['sponsor_normalized'] == sponsor_normalized]

            if sponsor_row.empty:
                # No deal history yet
                return {'score': 40, 'reasoning': 'No deal history - unproven sponsor'}

            avg_pop_1m = sponsor_row['avg_pop_1m'].iloc[0]

            if pd.isna(avg_pop_1m):
                # Has deals but no 1-month data yet
                return {'score': 50, 'reasoning': 'Recent deals - performance not yet measured'}

            # Score based on performance
            if avg_pop_1m > 50:
                return {'score': 100, 'reasoning': f'+{avg_pop_1m:.1f}% avg - exceptional track record'}
            elif avg_pop_1m > 20:
                return {'score': 90, 'reasoning': f'+{avg_pop_1m:.1f}% avg - great track record'}
            elif avg_pop_1m > 10:
                return {'score': 80, 'reasoning': f'+{avg_pop_1m:.1f}% avg - very good track record'}
            elif avg_pop_1m > 5:
                return {'score': 70, 'reasoning': f'+{avg_pop_1m:.1f}% avg - good track record'}
            elif avg_pop_1m > 1:
                return {'score': 60, 'reasoning': f'+{avg_pop_1m:.1f}% avg - moderate track record'}
            elif avg_pop_1m >= 0:
                return {'score': 50, 'reasoning': f'+{avg_pop_1m:.1f}% avg - flat track record'}
            else:
                return {'score': 30, 'reasoning': f'{avg_pop_1m:.1f}% avg - poor track record'}

        except Exception as e:
            # Fallback to count-based scoring if performance data not available
            count = self.db.query(SPAC).filter(
                SPAC.sponsor_normalized == sponsor_normalized
            ).count()

            if count >= 5:
                return {'score': 80, 'reasoning': f'{count} SPACs - serial sponsor (no perf data)'}
            elif count >= 3:
                return {'score': 60, 'reasoning': f'{count} SPACs - experienced (no perf data)'}
            elif count == 2:
                return {'score': 50, 'reasoning': f'{count} SPACs - some track record (no perf data)'}
            else:
                return {'score': 40, 'reasoning': f'{count} SPAC - unproven (no perf data)'}

    def score_trust_per_share(self, trust_value: float) -> Dict:
        """
        Score trust value per share (higher = more cash backing)

        Scoring:
        - >$10.10: 100 points (high cash, interest accrued)
        - $10.00-10.10: 80 points (standard)
        - $9.90-10.00: 60 points (slightly below NAV)
        - <$9.90: 40 points (low cash, may have expenses)
        """
        if trust_value is None:
            return {'score': 0, 'reasoning': 'No trust value data'}

        if trust_value > 10.10:
            return {'score': 100, 'reasoning': f'${trust_value:.2f}/share - high cash backing'}
        elif trust_value >= 10.00:
            return {'score': 80, 'reasoning': f'${trust_value:.2f}/share - standard NAV'}
        elif trust_value >= 9.90:
            return {'score': 60, 'reasoning': f'${trust_value:.2f}/share - slightly below standard'}
        else:
            return {'score': 40, 'reasoning': f'${trust_value:.2f}/share - low cash, expenses taken'}

    def calculate_composite_score(self, spac: SPAC) -> Dict:
        """Calculate composite Phase 1 score"""

        # Calculate metrics
        market_cap = self.calculate_market_cap(spac)
        days_to_deadline = self.calculate_days_to_deadline(spac)

        # Score each factor
        scores = {
            'market_cap': self.score_market_cap(market_cap),
            'premium': self.score_premium(spac.premium),
            'time_to_deadline': self.score_time_to_deadline(days_to_deadline),
            'sponsor': self.score_sponsor_track_record(spac.sponsor_normalized),
            'trust_value': self.score_trust_per_share(spac.trust_value)
        }

        # Weights for each factor
        weights = {
            'market_cap': 0.20,      # 20% - size matters for movement potential
            'premium': 0.30,          # 30% - risk/reward is critical
            'time_to_deadline': 0.20, # 20% - time is important
            'sponsor': 0.20,          # 20% - track record matters
            'trust_value': 0.10       # 10% - cash backing is nice to have
        }

        # Calculate weighted score
        total_score = sum(scores[key]['score'] * weights[key] for key in scores)

        return {
            'ticker': spac.ticker,
            'company': spac.company,
            'sponsor_normalized': spac.sponsor_normalized,
            'total_score': round(total_score, 1),
            'market_cap': market_cap,
            'premium': spac.premium,
            'days_to_deadline': days_to_deadline,
            'trust_value': spac.trust_value,
            'price': spac.price,
            'scores': scores,
            'weights': weights
        }

    def score_all(self) -> List[Dict]:
        """Score all pre-deal SPACs"""

        spacs = self.get_scorable_spacs()

        print(f"Scoring {len(spacs)} pre-deal SPACs with sufficient data...")
        print("=" * 80)

        results = []
        for spac in spacs:
            result = self.calculate_composite_score(spac)
            results.append(result)

        # Sort by total score descending
        results.sort(key=lambda x: x['total_score'], reverse=True)

        return results

    def print_results(self, results: List[Dict], top_n: int = 20):
        """Print top scoring SPACs with detailed breakdown"""

        print(f"\n🎯 TOP {top_n} PRE-DEAL SPACS - PHASE 1 'LOADED GUN' SCORE")
        print("=" * 80)

        for i, result in enumerate(results[:top_n], 1):
            print(f"\n#{i}. {result['ticker']} - {result['company']}")
            print(f"   📊 TOTAL SCORE: {result['total_score']:.1f}/100")
            print(f"   💰 Market Cap: ${result['market_cap']:.1f}M")
            print(f"   📈 Premium: {result['premium']:.1f}%")
            print(f"   ⏰ Days to Deadline: {result['days_to_deadline']}")
            print(f"   🏢 Sponsor: {result['sponsor_normalized']}")
            print(f"   💵 Trust/Share: ${result['trust_value']:.2f}")
            print(f"   💲 Current Price: ${result['price']:.2f}")

            print(f"\n   Score Breakdown:")
            for factor, score_data in result['scores'].items():
                weight = result['weights'][factor]
                weighted = score_data['score'] * weight
                print(f"      {factor:20s}: {score_data['score']:3.0f} × {weight:.0%} = {weighted:5.1f} | {score_data['reasoning']}")

        print("\n" + "=" * 80)
        print(f"Scored {len(results)} total SPACs")

        # Summary statistics
        avg_score = sum(r['total_score'] for r in results) / len(results)
        print(f"\n📊 Summary Statistics:")
        print(f"   Average Score: {avg_score:.1f}")
        print(f"   Highest Score: {results[0]['total_score']:.1f} ({results[0]['ticker']})")
        print(f"   Lowest Score: {results[-1]['total_score']:.1f} ({results[-1]['ticker']})")


def main():
    scorer = Phase1Scorer()

    try:
        results = scorer.score_all()
        scorer.print_results(results, top_n=20)

        # Save to CSV for analysis
        df = pd.DataFrame(results)
        df.to_csv('phase1_scores.csv', index=False)
        print(f"\n💾 Saved detailed scores to phase1_scores.csv")

    finally:
        scorer.close()


if __name__ == '__main__':
    main()
