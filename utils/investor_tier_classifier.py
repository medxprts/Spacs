#!/usr/bin/env python3
"""
Investor Tier Classifier
Classifies PIPE investors into tiers based on institutional quality and reputation

Tier-1: Elite institutions (BlackRock, Fidelity, etc.) - Strongest validation signal
Tier-2: Notable institutions (smaller asset managers, hedge funds)
Tier-3: Strategic investors, corporate investors
Tier-4: Family offices, smaller funds, unknown

Why this matters:
- Tier-1 PIPE = 20 points (smart money validation)
- Tier-2 PIPE = 10 points (decent validation)
- Tier-3+ = 0 points (no institutional signal)
"""

from typing import Dict, List, Optional
import re


# ============================================================================
# TIER-1: Elite Institutional Investors
# These are the "smart money" signals we want
# ============================================================================

TIER1_INVESTORS = {
    # Major Asset Managers (>$1T AUM)
    'blackrock': {
        'variations': ['blackrock', 'black rock', 'blk'],
        'aum_billions': 9000,
        'description': 'Largest global asset manager'
    },
    'vanguard': {
        'variations': ['vanguard', 'vanguard group'],
        'aum_billions': 7000,
        'description': 'Second largest asset manager'
    },
    'fidelity': {
        'variations': ['fidelity', 'fidelity investments', 'fidelity management'],
        'aum_billions': 4500,
        'description': 'Major mutual fund manager'
    },
    'state street': {
        'variations': ['state street', 'ssga', 'state street global'],
        'aum_billions': 4000,
        'description': 'Major institutional investor'
    },

    # Major Mutual Fund Complexes
    't. rowe price': {
        'variations': ['t. rowe price', 't rowe price', 'trowe', 't.rowe'],
        'aum_billions': 1400,
        'description': 'Active equity manager'
    },
    'capital group': {
        'variations': ['capital group', 'capital research', 'american funds'],
        'aum_billions': 2500,
        'description': 'American Funds manager'
    },
    'wellington': {
        'variations': ['wellington management', 'wellington'],
        'aum_billions': 1300,
        'description': 'Large institutional manager'
    },

    # Elite Investment Banks (Asset Management Arms)
    'goldman sachs': {
        'variations': ['goldman sachs', 'goldman', 'gs asset management', 'gsam'],
        'aum_billions': 2500,
        'description': 'Elite investment bank'
    },
    'morgan stanley': {
        'variations': ['morgan stanley', 'ms investment management', 'msim'],
        'aum_billions': 1500,
        'description': 'Elite investment bank'
    },
    'jpmorgan': {
        'variations': ['jpmorgan', 'jp morgan', 'j.p. morgan', 'jpm', 'jpmorgan chase'],
        'aum_billions': 3000,
        'description': 'Largest US bank'
    },

    # Sovereign Wealth Funds
    'gic': {
        'variations': ['gic', 'government of singapore investment'],
        'aum_billions': 690,
        'description': 'Singapore sovereign wealth fund'
    },
    'temasek': {
        'variations': ['temasek', 'temasek holdings'],
        'aum_billions': 300,
        'description': 'Singapore state-owned investment'
    },
    'adia': {
        'variations': ['adia', 'abu dhabi investment authority'],
        'aum_billions': 850,
        'description': 'Abu Dhabi sovereign fund'
    },

    # Prominent Hedge Funds
    'millennium': {
        'variations': ['millennium', 'millennium management'],
        'aum_billions': 60,
        'description': 'Large multi-strategy hedge fund'
    },
    'citadel': {
        'variations': ['citadel', 'citadel advisors'],
        'aum_billions': 60,
        'description': 'Major hedge fund'
    },
}


# ============================================================================
# TIER-2: Notable Institutional Investors
# Good validation but not elite
# ============================================================================

TIER2_INVESTORS = {
    # Large Hedge Funds / Asset Managers ($10B-$100B AUM)
    'viking': {'variations': ['viking', 'viking global']},
    'tiger global': {'variations': ['tiger global', 'tiger management']},
    'd1 capital': {'variations': ['d1 capital', 'd1 partners']},
    'coatue': {'variations': ['coatue', 'coatue management']},
    'glenview': {'variations': ['glenview capital']},
    'third point': {'variations': ['third point', 'third point llc']},

    # Notable SPAC-Focused Investors
    'magnetar': {'variations': ['magnetar', 'magnetar capital']},
    'aristeia': {'variations': ['aristeia', 'aristeia capital']},
    'glazer capital': {'variations': ['glazer', 'glazer capital']},

    # Mid-Tier Asset Managers
    'fidelity national': {'variations': ['fidelity national', 'fnf']},
    'neuberger berman': {'variations': ['neuberger berman', 'neuberger']},
    'frank russell': {'variations': ['frank russell', 'russell investments']},
    'pimco': {'variations': ['pimco', 'pacific investment']},

    # Corporate Venture Arms (if investing significantly)
    'intel capital': {'variations': ['intel capital']},
    'salesforce ventures': {'variations': ['salesforce ventures']},
    'google ventures': {'variations': ['google ventures', 'gv']},
}


# ============================================================================
# TIER-3: Strategic/Corporate Investors
# Industry players, not financial validation
# ============================================================================

TIER3_CATEGORIES = {
    'keywords': [
        'corporation', 'corp.', 'inc.', 'limited', 'ltd.',
        'holdings', 'ventures', 'investments',
        'partners', 'capital', 'fund'
    ]
}


class InvestorTierClassifier:
    """Classify PIPE investors into tiers"""

    def __init__(self):
        pass

    def classify_investor(self, investor_name: str) -> Dict:
        """
        Classify an investor into a tier

        Returns:
            {
                'tier': 1-4,
                'tier_name': 'Tier-1 Elite' | 'Tier-2 Notable' | 'Tier-3 Strategic' | 'Tier-4 Unknown',
                'matched_entity': 'BlackRock' (if matched),
                'confidence': 0-100,
                'description': 'Largest global asset manager'
            }
        """
        investor_lower = investor_name.lower().strip()

        # Check Tier-1 (exact or fuzzy match)
        tier1_match = self._check_tier1(investor_lower)
        if tier1_match:
            return {
                'tier': 1,
                'tier_name': 'Tier-1 Elite',
                'is_tier1': True,
                'matched_entity': tier1_match['name'],
                'confidence': tier1_match['confidence'],
                'description': tier1_match.get('description', ''),
                'aum_billions': tier1_match.get('aum_billions', 0)
            }

        # Check Tier-2
        tier2_match = self._check_tier2(investor_lower)
        if tier2_match:
            return {
                'tier': 2,
                'tier_name': 'Tier-2 Notable',
                'is_tier1': False,
                'matched_entity': tier2_match['name'],
                'confidence': tier2_match['confidence'],
                'description': 'Notable institutional investor'
            }

        # Check Tier-3 (strategic/corporate)
        if self._is_corporate_investor(investor_lower):
            return {
                'tier': 3,
                'tier_name': 'Tier-3 Strategic',
                'is_tier1': False,
                'confidence': 50,
                'description': 'Strategic or corporate investor'
            }

        # Tier-4 (unknown)
        return {
            'tier': 4,
            'tier_name': 'Tier-4 Unknown',
            'is_tier1': False,
            'confidence': 0,
            'description': 'Unknown or unclassified investor'
        }

    def _check_tier1(self, investor_lower: str) -> Optional[Dict]:
        """Check if investor matches Tier-1 list"""
        for entity_name, entity_data in TIER1_INVESTORS.items():
            variations = entity_data['variations']

            # Exact match
            if investor_lower == entity_name:
                return {
                    'name': entity_name.title(),
                    'confidence': 100,
                    **entity_data
                }

            # Check variations
            for variation in variations:
                if variation in investor_lower:
                    # Fuzzy match confidence based on length
                    confidence = 90 if len(variation) > 5 else 80
                    return {
                        'name': entity_name.title(),
                        'confidence': confidence,
                        **entity_data
                    }

        return None

    def _check_tier2(self, investor_lower: str) -> Optional[Dict]:
        """Check if investor matches Tier-2 list"""
        for entity_name, entity_data in TIER2_INVESTORS.items():
            variations = entity_data['variations']

            for variation in variations:
                if variation in investor_lower:
                    return {
                        'name': entity_name.title(),
                        'confidence': 85
                    }

        return None

    def _is_corporate_investor(self, investor_lower: str) -> bool:
        """Check if investor looks like a corporate/strategic investor"""
        # Corporate indicators
        corporate_keywords = ['corporation', 'corp.', 'inc.', 'holdings', 'ventures']
        return any(keyword in investor_lower for keyword in corporate_keywords)

    def classify_pipe_investors(self, investor_list: List[str]) -> Dict:
        """
        Classify a list of PIPE investors

        Returns:
            {
                'tier1_count': 3,
                'tier2_count': 1,
                'tier1_investors': ['BlackRock', 'Fidelity', 'T. Rowe Price'],
                'tier2_investors': ['Tiger Global'],
                'total_investors': 5,
                'tier1_percentage': 60.0,
                'validation_strength': 'STRONG'  # EXTREME, STRONG, MODERATE, WEAK
            }
        """
        results = {
            'tier1_investors': [],
            'tier2_investors': [],
            'tier3_investors': [],
            'tier4_investors': [],
            'tier1_count': 0,
            'tier2_count': 0,
            'classifications': []
        }

        for investor_name in investor_list:
            classification = self.classify_investor(investor_name)
            results['classifications'].append({
                'name': investor_name,
                **classification
            })

            if classification['tier'] == 1:
                results['tier1_count'] += 1
                results['tier1_investors'].append(classification['matched_entity'])
            elif classification['tier'] == 2:
                results['tier2_count'] += 1
                results['tier2_investors'].append(classification.get('matched_entity', investor_name))
            elif classification['tier'] == 3:
                results['tier3_investors'].append(investor_name)
            else:
                results['tier4_investors'].append(investor_name)

        results['total_investors'] = len(investor_list)
        results['tier1_percentage'] = (results['tier1_count'] / len(investor_list) * 100) if investor_list else 0

        # Determine validation strength
        if results['tier1_count'] >= 3:
            results['validation_strength'] = 'EXTREME'
        elif results['tier1_count'] >= 1:
            results['validation_strength'] = 'STRONG'
        elif results['tier2_count'] >= 2:
            results['validation_strength'] = 'MODERATE'
        else:
            results['validation_strength'] = 'WEAK'

        return results


# ============================================================================
# SCORING FUNCTION (for opportunity agent)
# ============================================================================

def calculate_pipe_quality_score(tier1_count: int, tier2_count: int) -> int:
    """
    Calculate PIPE quality score based on investor tiers

    Scoring:
    - 20 points: 3+ Tier-1 investors
    - 15 points: 2 Tier-1 investors
    - 10 points: 1 Tier-1 investor
    - 5 points: 2+ Tier-2 investors (no Tier-1)
    - 0 points: No Tier-1 or Tier-2
    """
    if tier1_count >= 3:
        return 20
    elif tier1_count == 2:
        return 15
    elif tier1_count == 1:
        return 10
    elif tier2_count >= 2:
        return 5
    else:
        return 0


# ============================================================================
# CLI TESTING
# ============================================================================

if __name__ == '__main__':
    classifier = InvestorTierClassifier()

    # Test cases
    test_investors = [
        "BlackRock Funds",
        "Fidelity Management & Research",
        "T. Rowe Price Associates",
        "Tiger Global Management",
        "ETH Partners LLC",
        "JBerns inv EM1, LLC",
        "XYZ Capital Partners"
    ]

    print("=" * 80)
    print("INVESTOR TIER CLASSIFICATION TEST")
    print("=" * 80)

    print("\nIndividual Classifications:")
    print("-" * 80)

    for investor in test_investors:
        result = classifier.classify_investor(investor)
        print(f"\n{investor}")
        print(f"  Tier: {result['tier_name']}")
        if result.get('matched_entity'):
            print(f"  Matched: {result['matched_entity']}")
        print(f"  Confidence: {result['confidence']}%")
        if result.get('description'):
            print(f"  Description: {result['description']}")

    print("\n" + "=" * 80)
    print("PIPE GROUP ANALYSIS")
    print("=" * 80)

    group_result = classifier.classify_pipe_investors(test_investors)

    print(f"\nTotal Investors: {group_result['total_investors']}")
    print(f"Tier-1 Count: {group_result['tier1_count']}")
    print(f"Tier-2 Count: {group_result['tier2_count']}")
    print(f"Validation Strength: {group_result['validation_strength']}")

    if group_result['tier1_investors']:
        print(f"\nTier-1 Investors:")
        for inv in group_result['tier1_investors']:
            print(f"  ✅ {inv}")

    if group_result['tier2_investors']:
        print(f"\nTier-2 Investors:")
        for inv in group_result['tier2_investors']:
            print(f"  ⭐ {inv}")

    # Calculate score
    score = calculate_pipe_quality_score(
        group_result['tier1_count'],
        group_result['tier2_count']
    )

    print(f"\n{'=' * 80}")
    print(f"PIPE QUALITY SCORE: {score}/20")
    print(f"{'=' * 80}")

    if score >= 15:
        print("🔥 EXTREME: Multiple elite institutions")
    elif score >= 10:
        print("✅ STRONG: At least one elite institution")
    elif score >= 5:
        print("⭐ MODERATE: Notable investors")
    else:
        print("⚠️  WEAK: No institutional validation")
