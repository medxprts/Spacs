#!/usr/bin/env python3
"""
phase2_pattern_detector.py - Pattern Detection Engine

Purpose: Analyze validation failures to detect recurring patterns indicating
         systemic issues that require new validators.

Key Capabilities:
    1. Temporal Analysis: Detect patterns over time
    2. Field Correlation: Identify related field issues
    3. Banker/Sector Clustering: Entity-specific patterns
    4. Rule Gap Detection: Identify missing validators

Architecture:
    validation_failures table
        ↓
    PatternDetector (this file)
        ↓
    detected_patterns table → Validator Synthesis (Phase 3)

Usage:
    # Analyze last 30 days for patterns
    python3 phase2_pattern_detector.py --analyze --lookback 30

    # Show detected patterns
    python3 phase2_pattern_detector.py --list-patterns

    # Test pattern detection on specific issue type
    python3 phase2_pattern_detector.py --test temporal_impossibility
"""

import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import json
from collections import Counter, defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from sqlalchemy import text


class Pattern:
    """Represents a detected validation failure pattern"""

    def __init__(self, pattern_data: Dict):
        self.pattern_name = pattern_data['pattern_name']
        self.pattern_type = pattern_data['pattern_type']
        self.description = pattern_data['description']
        self.issue_count = pattern_data['issue_count']
        self.affected_tickers = pattern_data['affected_tickers']
        self.common_characteristics = pattern_data['common_characteristics']
        self.impact_score = pattern_data['impact_score']
        self.recommended_validator = pattern_data.get('recommended_validator', {})

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'pattern_name': self.pattern_name,
            'pattern_type': self.pattern_type,
            'description': self.description,
            'issue_count': self.issue_count,
            'affected_tickers': self.affected_tickers,
            'common_characteristics': self.common_characteristics,
            'impact_score': self.impact_score,
            'recommended_validator': self.recommended_validator
        }


class PatternDetector:
    """
    Detects recurring validation failure patterns for validator synthesis

    Pattern Detection Algorithm:
        1. Query validation_failures for recent issues
        2. Group by issue_type and look for clusters
        3. Analyze common characteristics within clusters
        4. Calculate impact score (severity + frequency + spread)
        5. Determine if pattern warrants new validator
        6. Generate validator recommendation
    """

    def __init__(self, min_issue_count: int = 3, min_confidence: float = 0.70,
                 min_impact_score: float = 60.0):
        """
        Initialize pattern detector

        Args:
            min_issue_count: Minimum issues to constitute a pattern (default: 3)
            min_confidence: Minimum similarity confidence (0-1) (default: 0.70)
            min_impact_score: Minimum impact score (0-100) (default: 60.0)
        """
        self.min_issue_count = min_issue_count
        self.min_confidence = min_confidence
        self.min_impact_score = min_impact_score
        self.db = SessionLocal()

    def detect_patterns(self, lookback_days: int = 30) -> List[Pattern]:
        """
        Main pattern detection method

        Args:
            lookback_days: Analyze issues from last N days

        Returns: List of detected patterns meeting thresholds
        """
        print(f"\n{'='*70}")
        print(f"Pattern Detection Analysis (Last {lookback_days} Days)")
        print(f"{'='*70}\n")

        # Load recent validation failures
        failures = self._load_validation_failures(lookback_days)

        if not failures:
            print("No validation failures found in timeframe")
            return []

        print(f"Analyzing {len(failures)} validation failures...")
        print(f"Thresholds: min_issues={self.min_issue_count}, "
              f"min_confidence={self.min_confidence}, min_impact={self.min_impact_score}\n")

        patterns = []

        # Pattern Detection Strategy 1: Issue Type Clustering
        patterns.extend(self._detect_issue_type_patterns(failures))

        # Pattern Detection Strategy 2: Field Correlation
        patterns.extend(self._detect_field_correlation_patterns(failures))

        # Pattern Detection Strategy 3: Entity-Specific (Banker/Sector)
        patterns.extend(self._detect_entity_specific_patterns(failures))

        # Pattern Detection Strategy 4: Temporal Patterns
        patterns.extend(self._detect_temporal_patterns(failures))

        # Deduplicate patterns
        patterns = self._deduplicate_patterns(patterns)

        # Filter by thresholds
        patterns = [p for p in patterns if p.impact_score >= self.min_impact_score]

        print(f"\n{'='*70}")
        print(f"Pattern Detection Complete: {len(patterns)} pattern(s) detected")
        print(f"{'='*70}\n")

        if patterns:
            for i, pattern in enumerate(patterns, 1):
                print(f"Pattern {i}: {pattern.pattern_name}")
                print(f"  Type: {pattern.pattern_type}")
                print(f"  Issues: {pattern.issue_count}")
                print(f"  Impact Score: {pattern.impact_score:.1f}/100")
                print(f"  Affected Tickers: {', '.join(pattern.affected_tickers[:5])}" +
                      (f" (+{len(pattern.affected_tickers)-5} more)" if len(pattern.affected_tickers) > 5 else ""))
                print()

        return patterns

    def _load_validation_failures(self, lookback_days: int) -> List[Dict]:
        """Load recent validation failures from database"""
        query = text("""
            SELECT
                id,
                ticker,
                validation_method,
                issue_type,
                severity,
                field,
                expected_value,
                actual_value,
                error_message,
                metadata,
                related_fields,
                detected_at
            FROM validation_failures
            WHERE detected_at >= NOW() - INTERVAL ':days days'
              AND fix_applied = false  -- Only unresolved issues
            ORDER BY detected_at DESC
        """)

        result = self.db.execute(query, {'days': lookback_days})

        failures = []
        for row in result:
            failures.append({
                'id': row[0],
                'ticker': row[1],
                'validation_method': row[2],
                'issue_type': row[3],
                'severity': row[4],
                'field': row[5],
                'expected_value': row[6],
                'actual_value': row[7],
                'error_message': row[8],
                'metadata': json.loads(row[9]) if row[9] else {},
                'related_fields': json.loads(row[10]) if row[10] else {},
                'detected_at': row[11]
            })

        return failures

    def _detect_issue_type_patterns(self, failures: List[Dict]) -> List[Pattern]:
        """
        Strategy 1: Detect patterns by issue_type clustering

        Example: 3+ SPACs with temporal_impossibility → new validator needed
        """
        patterns = []

        # Group by issue_type
        issue_groups = defaultdict(list)
        for failure in failures:
            issue_groups[failure['issue_type']].append(failure)

        # Analyze each group
        for issue_type, issues in issue_groups.items():
            if len(issues) < self.min_issue_count:
                continue

            # Extract common characteristics
            tickers = list(set([i['ticker'] for i in issues]))
            severities = [i['severity'] for i in issues]
            fields = [i['field'] for i in issues if i['field']]

            # Calculate similarity confidence
            field_counter = Counter(fields)
            most_common_field = field_counter.most_common(1)[0] if field_counter else (None, 0)
            field_similarity = most_common_field[1] / len(issues) if most_common_field else 0

            severity_counter = Counter(severities)
            most_common_severity = severity_counter.most_common(1)[0][0]

            # Check if confidence meets threshold
            confidence = field_similarity  # Can be more sophisticated
            if confidence < self.min_confidence:
                continue

            # Calculate impact score
            impact_score = self._calculate_impact_score(
                issue_count=len(issues),
                severity=most_common_severity,
                ticker_count=len(tickers)
            )

            # Build pattern
            common_chars = {
                'issue_type': issue_type,
                'common_field': most_common_field[0] if most_common_field else None,
                'common_severity': most_common_severity,
                'field_occurrence_rate': f"{field_similarity*100:.0f}%",
                'validation_gap': self._identify_validation_gap(issue_type, issues),
                'example_error': issues[0]['error_message']
            }

            # Generate validator recommendation
            validator_rec = self._recommend_validator_for_issue_type(
                issue_type, issues, common_chars
            )

            pattern = Pattern({
                'pattern_name': f"{issue_type}_pattern",
                'pattern_type': self._classify_pattern_type(issue_type, issues),
                'description': self._generate_pattern_description(issue_type, issues),
                'issue_count': len(issues),
                'affected_tickers': tickers,
                'common_characteristics': common_chars,
                'impact_score': impact_score,
                'recommended_validator': validator_rec
            })

            patterns.append(pattern)

        return patterns

    def _detect_field_correlation_patterns(self, failures: List[Dict]) -> List[Pattern]:
        """
        Strategy 2: Detect patterns where multiple fields fail together

        Example: trust_cash error always occurs with ipo_proceeds error
                → Extraction bug in IPO scraping
        """
        patterns = []

        # Build field co-occurrence matrix
        ticker_fields = defaultdict(set)
        for failure in failures:
            if failure['field']:
                ticker_fields[failure['ticker']].add(failure['field'])

        # Find field pairs that co-occur frequently
        field_pairs = Counter()
        for fields in ticker_fields.values():
            if len(fields) >= 2:
                for f1 in fields:
                    for f2 in fields:
                        if f1 < f2:  # Avoid duplicates
                            field_pairs[(f1, f2)] += 1

        # Identify significant correlations
        for (field1, field2), count in field_pairs.items():
            if count < self.min_issue_count:
                continue

            # Get issues for these fields
            related_issues = [
                f for f in failures
                if f['field'] in [field1, field2]
            ]

            tickers_affected = list(set([i['ticker'] for i in related_issues]))

            # Calculate impact
            avg_severity = self._get_average_severity(related_issues)
            impact_score = self._calculate_impact_score(
                issue_count=count,
                severity=avg_severity,
                ticker_count=len(tickers_affected)
            )

            if impact_score < self.min_impact_score:
                continue

            # Build correlation pattern
            pattern = Pattern({
                'pattern_name': f"{field1}_{field2}_correlation_pattern",
                'pattern_type': 'extraction_bug',
                'description': f"Fields {field1} and {field2} frequently fail together, "
                              f"indicating a common extraction issue in the data scraper.",
                'issue_count': count,
                'affected_tickers': tickers_affected,
                'common_characteristics': {
                    'correlated_fields': [field1, field2],
                    'co_occurrence_count': count,
                    'likely_cause': 'Related fields extracted from same data source',
                    'suggested_fix': f'Review extraction logic for {field1} and {field2}'
                },
                'impact_score': impact_score,
                'recommended_validator': {
                    'name': f'validate_{field1}_{field2}_consistency',
                    'description': f'Cross-validate {field1} and {field2} for consistency',
                    'rules': [
                        f'If {field1} is missing, {field2} should also be checked',
                        f'If {field1} is unusual, verify {field2} matches'
                    ]
                }
            })

            patterns.append(pattern)

        return patterns

    def _detect_entity_specific_patterns(self, failures: List[Dict]) -> List[Pattern]:
        """
        Strategy 3: Detect patterns specific to bankers, sectors, or sponsors

        Example: All Goldman Sachs SPACs missing warrant_ratio
                → Banker-specific scraping issue
        """
        patterns = []

        # Group failures by ticker, then look up entity info
        ticker_failures = defaultdict(list)
        for failure in failures:
            ticker_failures[failure['ticker']].append(failure)

        # Load SPAC entity data (banker, sector, sponsor)
        from database import SPAC
        spacs = {s.ticker: s for s in self.db.query(SPAC).all()}

        # Group by banker
        banker_issues = defaultdict(list)
        for ticker, issues in ticker_failures.items():
            if ticker in spacs and spacs[ticker].banker:
                banker = spacs[ticker].banker
                banker_issues[banker].extend(issues)

        # Detect banker-specific patterns
        for banker, issues in banker_issues.items():
            if len(issues) < self.min_issue_count:
                continue

            # Check if specific issue types recur for this banker
            issue_type_counts = Counter([i['issue_type'] for i in issues])
            for issue_type, count in issue_type_counts.items():
                if count < self.min_issue_count:
                    continue

                specific_issues = [i for i in issues if i['issue_type'] == issue_type]
                tickers_affected = list(set([i['ticker'] for i in specific_issues]))

                avg_severity = self._get_average_severity(specific_issues)
                impact_score = self._calculate_impact_score(
                    issue_count=count,
                    severity=avg_severity,
                    ticker_count=len(tickers_affected)
                )

                if impact_score < self.min_impact_score:
                    continue

                pattern = Pattern({
                    'pattern_name': f"{banker.lower().replace(' ', '_')}_{issue_type}_pattern",
                    'pattern_type': 'entity_specific',
                    'description': f"SPACs with banker {banker} consistently have "
                                  f"{issue_type} issues, indicating banker-specific data problem.",
                    'issue_count': count,
                    'affected_tickers': tickers_affected,
                    'common_characteristics': {
                        'entity_type': 'banker',
                        'entity_name': banker,
                        'issue_type': issue_type,
                        'likely_cause': f'Banker-specific filing format or data availability issue'
                    },
                    'impact_score': impact_score,
                    'recommended_validator': {
                        'name': f'validate_{banker.lower().replace(" ", "_")}_specific_fields',
                        'description': f'Special validation for {banker} SPACs',
                        'rules': [
                            f'For {banker} SPACs, extra validation on prone fields',
                            'Consider banker-specific scraping logic'
                        ]
                    }
                })

                patterns.append(pattern)

        return patterns

    def _detect_temporal_patterns(self, failures: List[Dict]) -> List[Pattern]:
        """
        Strategy 4: Detect patterns in time (sudden spike, recurring daily, etc.)

        Example: Spike of trust_cash errors in last 3 days
                → Recent scraper change broke something
        """
        patterns = []

        # Group by day
        daily_failures = defaultdict(list)
        for failure in failures:
            day = failure['detected_at'].date()
            daily_failures[day].append(failure)

        # Detect spikes (day with 3x average)
        daily_counts = {day: len(issues) for day, issues in daily_failures.items()}
        if daily_counts:
            avg_daily = sum(daily_counts.values()) / len(daily_counts)

            for day, count in daily_counts.items():
                if count >= avg_daily * 3 and count >= self.min_issue_count:
                    # Spike detected
                    spike_issues = daily_failures[day]
                    issue_types = Counter([i['issue_type'] for i in spike_issues])
                    top_issue_type = issue_types.most_common(1)[0][0]

                    tickers_affected = list(set([i['ticker'] for i in spike_issues]))

                    impact_score = self._calculate_impact_score(
                        issue_count=count,
                        severity=self._get_average_severity(spike_issues),
                        ticker_count=len(tickers_affected)
                    )

                    pattern = Pattern({
                        'pattern_name': f"spike_{day.strftime('%Y%m%d')}_{top_issue_type}_pattern",
                        'pattern_type': 'temporal_spike',
                        'description': f"Sudden spike of {top_issue_type} issues on {day} "
                                      f"({count} issues, {int(count/avg_daily)}x daily average). "
                                      f"Likely caused by recent code change or data source issue.",
                        'issue_count': count,
                        'affected_tickers': tickers_affected,
                        'common_characteristics': {
                            'spike_date': str(day),
                            'daily_average': round(avg_daily, 1),
                            'spike_multiplier': round(count / avg_daily, 1),
                            'predominant_issue_type': top_issue_type,
                            'likely_cause': 'Recent code change or data source disruption'
                        },
                        'impact_score': impact_score,
                        'recommended_validator': {
                            'name': 'investigate_recent_changes',
                            'description': 'Investigate what changed recently',
                            'rules': [
                                'Review recent commits to scraper',
                                'Check if external data source changed',
                                'Verify no deployment issues'
                            ]
                        }
                    })

                    patterns.append(pattern)

        return patterns

    def _calculate_impact_score(self, issue_count: int, severity: str,
                                ticker_count: int) -> float:
        """
        Calculate impact score (0-100) for a pattern

        Formula:
            base_score = log scale from issue count (0-50 points)
            severity_weight = multiplier (CRITICAL=1.0, HIGH=0.75, MEDIUM=0.5, LOW=0.25)
            ticker_spread = more tickers = higher impact (1 + ticker_count * 0.1)

        Returns: Score 0-100
        """
        import math

        # Base score from issue count (logarithmic)
        base_score = min(50, 10 * math.log(issue_count + 1))

        # Severity weighting
        severity_weights = {
            'CRITICAL': 1.0,
            'HIGH': 0.75,
            'MEDIUM': 0.5,
            'LOW': 0.25
        }
        severity_weight = severity_weights.get(severity, 0.5)

        # Ticker spread multiplier
        ticker_multiplier = 1 + (ticker_count * 0.1)

        # Final score (capped at 100)
        score = min(100, base_score * severity_weight * ticker_multiplier)

        return round(score, 1)

    def _get_average_severity(self, issues: List[Dict]) -> str:
        """Get predominant severity from issue list"""
        severities = [i['severity'] for i in issues]
        severity_counts = Counter(severities)
        return severity_counts.most_common(1)[0][0] if severity_counts else 'MEDIUM'

    def _classify_pattern_type(self, issue_type: str, issues: List[Dict]) -> str:
        """
        Classify pattern type based on issue characteristics

        Types:
            - data_corruption: Bad data (ticker reuse, etc.)
            - extraction_bug: Scraping logic error
            - logic_error: Validation logic wrong
            - data_unavailable: Data missing from source
        """
        # Heuristics based on issue type and characteristics
        if 'temporal' in issue_type or 'cik_mismatch' in issue_type:
            return 'data_corruption'
        elif 'missing' in issue_type:
            return 'data_unavailable'
        elif any('trust' in str(i.get('field', '')) for i in issues):
            return 'extraction_bug'
        else:
            return 'logic_error'

    def _identify_validation_gap(self, issue_type: str, issues: List[Dict]) -> str:
        """Identify what validator is missing"""
        validation_methods = set([i['validation_method'] for i in issues])

        if len(validation_methods) == 1 and 'unknown' in list(validation_methods)[0]:
            return f"No validator exists to check for {issue_type}"
        else:
            return f"Existing validators insufficient for {issue_type}"

    def _generate_pattern_description(self, issue_type: str, issues: List[Dict]) -> str:
        """Generate human-readable pattern description"""
        ticker_count = len(set([i['ticker'] for i in issues]))
        severity = self._get_average_severity(issues)

        return (f"{len(issues)} {severity} issue(s) of type '{issue_type}' detected "
                f"across {ticker_count} SPAC(s). Pattern indicates systemic issue "
                f"requiring new validation logic.")

    def _recommend_validator_for_issue_type(self, issue_type: str,
                                            issues: List[Dict],
                                            common_chars: Dict) -> Dict:
        """
        Generate validator recommendation for issue type pattern

        This is a rule-based recommendation. Phase 3 will use AI to generate actual code.
        """
        field = common_chars.get('common_field')

        # Map issue types to validator recommendations
        recommendations = {
            'temporal_impossibility': {
                'name': 'validate_temporal_consistency',
                'description': 'Check all dates respect causality (IPO → announcement → completion)',
                'rules': [
                    'announced_date >= ipo_date',
                    'completion_date >= announced_date',
                    'merger_termination_date >= announced_date',
                    'deadline_date >= ipo_date + 18 months'
                ],
                'priority': 'CRITICAL'
            },
            'cik_mismatch': {
                'name': 'validate_cik_consistency',
                'description': 'Verify CIK matches ticker ownership in SEC database',
                'rules': [
                    'Query SEC API for ticker → CIK mapping',
                    'Compare with database CIK',
                    'Flag mismatches as data corruption'
                ],
                'priority': 'CRITICAL'
            },
            'trust_cash_unusual': {
                'name': 'validate_trust_cash_reasonableness',
                'description': 'Verify trust cash is reasonable vs IPO proceeds',
                'rules': [
                    'trust_cash should be ~90-105% of IPO proceeds',
                    'Flag if > 120% (likely error)',
                    'Flag if < 80% (significant redemptions or error)'
                ],
                'priority': 'HIGH'
            }
        }

        if issue_type in recommendations:
            return recommendations[issue_type]
        else:
            # Generic recommendation
            return {
                'name': f'validate_{issue_type}',
                'description': f'Validate {field or "data"} for {issue_type} issues',
                'rules': ['Add specific validation logic based on issue characteristics'],
                'priority': 'MEDIUM'
            }

    def _deduplicate_patterns(self, patterns: List[Pattern]) -> List[Pattern]:
        """Remove duplicate patterns detected by multiple strategies"""
        seen = {}
        unique = []

        for pattern in patterns:
            # Use pattern_name as key
            if pattern.pattern_name not in seen:
                seen[pattern.pattern_name] = pattern
                unique.append(pattern)
            else:
                # Keep pattern with higher impact score
                existing = seen[pattern.pattern_name]
                if pattern.impact_score > existing.impact_score:
                    unique.remove(existing)
                    unique.append(pattern)
                    seen[pattern.pattern_name] = pattern

        return unique

    def save_patterns_to_db(self, patterns: List[Pattern]) -> int:
        """
        Save detected patterns to detected_patterns table

        Returns: Number of patterns saved
        """
        saved_count = 0

        for pattern in patterns:
            try:
                # Check if pattern already exists
                check_query = text("""
                    SELECT id FROM detected_patterns
                    WHERE pattern_name = :pattern_name
                      AND status IN ('detected', 'validator_generated')
                """)

                existing = self.db.execute(check_query, {
                    'pattern_name': pattern.pattern_name
                }).fetchone()

                if existing:
                    # Update existing pattern
                    update_query = text("""
                        UPDATE detected_patterns
                        SET
                            issue_count = :issue_count,
                            affected_tickers = :affected_tickers,
                            impact_score = :impact_score,
                            last_occurrence = NOW(),
                            common_characteristics = :common_characteristics,
                            recommended_validator_name = :recommended_validator_name,
                            recommended_validator_rules = :recommended_validator_rules
                        WHERE id = :id
                    """)

                    self.db.execute(update_query, {
                        'id': existing[0],
                        'issue_count': pattern.issue_count,
                        'affected_tickers': pattern.affected_tickers,
                        'impact_score': pattern.impact_score,
                        'common_characteristics': json.dumps(pattern.common_characteristics),
                        'recommended_validator_name': pattern.recommended_validator.get('name'),
                        'recommended_validator_rules': json.dumps(pattern.recommended_validator)
                    })

                    print(f"  Updated existing pattern: {pattern.pattern_name}")
                else:
                    # Insert new pattern
                    insert_query = text("""
                        INSERT INTO detected_patterns (
                            pattern_name,
                            pattern_type,
                            description,
                            issue_count,
                            affected_tickers,
                            common_characteristics,
                            impact_score,
                            recurrence_frequency,
                            recommended_validator_name,
                            recommended_validator_rules,
                            validator_recommended,
                            status
                        ) VALUES (
                            :pattern_name,
                            :pattern_type,
                            :description,
                            :issue_count,
                            :affected_tickers,
                            :common_characteristics,
                            :impact_score,
                            :recurrence_frequency,
                            :recommended_validator_name,
                            :recommended_validator_rules,
                            true,
                            'detected'
                        )
                    """)

                    self.db.execute(insert_query, {
                        'pattern_name': pattern.pattern_name,
                        'pattern_type': pattern.pattern_type,
                        'description': pattern.description,
                        'issue_count': pattern.issue_count,
                        'affected_tickers': pattern.affected_tickers,
                        'common_characteristics': json.dumps(pattern.common_characteristics),
                        'impact_score': pattern.impact_score,
                        'recurrence_frequency': 'weekly',  # Default
                        'recommended_validator_name': pattern.recommended_validator.get('name'),
                        'recommended_validator_rules': json.dumps(pattern.recommended_validator)
                    })

                    print(f"  Saved new pattern: {pattern.pattern_name}")

                saved_count += 1

            except Exception as e:
                print(f"  ⚠️  Failed to save pattern {pattern.pattern_name}: {e}")
                continue

        self.db.commit()
        return saved_count

    def __del__(self):
        """Cleanup"""
        if hasattr(self, 'db'):
            self.db.close()


# ============================================================================
# CLI Interface
# ============================================================================

def list_patterns():
    """Show all detected patterns"""
    db = SessionLocal()
    try:
        query = text("""
            SELECT
                pattern_name,
                pattern_type,
                issue_count,
                impact_score,
                validator_recommended,
                validator_deployed,
                status,
                first_detected,
                last_occurrence
            FROM detected_patterns
            ORDER BY impact_score DESC, issue_count DESC
        """)

        result = db.execute(query)

        print("\n" + "="*80)
        print("Detected Patterns")
        print("="*80 + "\n")

        for row in result:
            status_icon = "✓" if row[5] else ("🔨" if row[4] else "❌")
            print(f"{status_icon} {row[0]}")
            print(f"   Type: {row[1]:20s} | Issues: {row[2]:3d} | Impact: {row[3]:5.1f}/100")
            print(f"   Status: {row[6]:15s} | First: {row[7].strftime('%Y-%m-%d')} | "
                  f"Last: {row[8].strftime('%Y-%m-%d')}")
            print()

    finally:
        db.close()


def test_pattern_on_issue_type(issue_type: str):
    """Test pattern detection on specific issue type"""
    print(f"\nTesting pattern detection for issue_type = '{issue_type}'...\n")

    detector = PatternDetector(min_issue_count=2, min_impact_score=50)
    patterns = detector.detect_patterns(lookback_days=365)  # Look back 1 year for test

    relevant = [p for p in patterns if issue_type in p.pattern_name]

    if relevant:
        print(f"✓ Found {len(relevant)} pattern(s) matching '{issue_type}':\n")
        for p in relevant:
            print(json.dumps(p.to_dict(), indent=2))
    else:
        print(f"✗ No patterns found for '{issue_type}'")
        print(f"\nAll detected patterns:")
        for p in patterns:
            print(f"  - {p.pattern_name}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Phase 2: Pattern Detection Engine')
    parser.add_argument('--analyze', action='store_true',
                       help='Run pattern detection analysis')
    parser.add_argument('--lookback', type=int, default=30,
                       help='Days to look back (default: 30)')
    parser.add_argument('--list-patterns', action='store_true',
                       help='List all detected patterns')
    parser.add_argument('--test', type=str, metavar='ISSUE_TYPE',
                       help='Test detection on specific issue type')
    parser.add_argument('--save', action='store_true',
                       help='Save detected patterns to database')

    args = parser.parse_args()

    if args.analyze:
        detector = PatternDetector()
        patterns = detector.detect_patterns(lookback_days=args.lookback)

        if patterns and args.save:
            print(f"\nSaving {len(patterns)} pattern(s) to database...")
            saved = detector.save_patterns_to_db(patterns)
            print(f"✓ Saved {saved} pattern(s)")

    elif args.list_patterns:
        list_patterns()

    elif args.test:
        test_pattern_on_issue_type(args.test)

    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python3 phase2_pattern_detector.py --analyze --lookback 30 --save")
        print("  python3 phase2_pattern_detector.py --list-patterns")
        print("  python3 phase2_pattern_detector.py --test temporal_impossibility")
