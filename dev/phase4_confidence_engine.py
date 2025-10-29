#!/usr/bin/env python3
"""
phase4_confidence_engine.py - Confidence Scoring & Auto-Deploy Decision System

Purpose: Decide which validators to auto-deploy vs queue for human review.

Key Capabilities:
    1. Multi-factor confidence scoring (pattern + code + history + blast radius)
    2. Threshold-based deployment decisions
    3. Post-deployment monitoring
    4. Automatic rollback on high false positive rate

Architecture:
    Generated Validator (Phase 3)
        ↓
    ConfidenceEngine (this file)
        ↓
    Decision: Auto-Deploy (≥95%) | Deploy with Monitoring (80-94%) |
              Human Review (70-79%) | Reject (<70%)
        ↓
    ValidatorMonitor (continuous tracking)

Usage:
    # Score a generated validator
    python3 phase4_confidence_engine.py --score-pattern 1

    # Check if validator should auto-deploy
    python3 phase4_confidence_engine.py --check-deploy 1

    # Monitor deployed validators
    python3 phase4_confidence_engine.py --monitor

    # Rollback validator
    python3 phase4_confidence_engine.py --rollback validate_temporal_consistency
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
import json
import ast

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from sqlalchemy import text


class ConfidenceEngine:
    """
    Sophisticated confidence scoring for validator deployment decisions

    Confidence Factors:
        1. Pattern Strength (40%): Issue count, recurrence, impact
        2. Code Quality (30%): Syntax, completeness, follows patterns
        3. Historical Accuracy (20%): Similar patterns, validator track record
        4. Blast Radius (10%): Affected SPACs, reversibility
    """

    def __init__(self):
        """Initialize confidence engine"""
        self.db = SessionLocal()

        # Deployment thresholds
        self.auto_deploy_threshold = float(os.getenv('AUTO_DEPLOY_THRESHOLD', 95))
        self.monitored_deploy_threshold = 80.0
        self.human_review_threshold = 70.0

        print(f"✓ ConfidenceEngine initialized")
        print(f"  Auto-deploy threshold: {self.auto_deploy_threshold}%")

    def score_pattern_validator(self, pattern_id: int) -> Dict:
        """
        Calculate comprehensive confidence score for pattern's validator

        Args:
            pattern_id: ID from detected_patterns table

        Returns: Dict with scores breakdown and deployment recommendation
        """
        print(f"\n{'='*70}")
        print(f"Confidence Scoring for Pattern ID {pattern_id}")
        print(f"{'='*70}\n")

        # Load pattern and validator
        pattern = self._load_pattern_with_validator(pattern_id)
        if not pattern:
            raise ValueError(f"Pattern {pattern_id} not found or no validator generated")

        # Calculate each factor
        pattern_strength_score = self._score_pattern_strength(pattern)
        code_quality_score = self._score_code_quality(pattern)
        historical_accuracy_score = self._score_historical_accuracy(pattern)
        blast_radius_score = self._score_blast_radius(pattern)

        # Weighted total
        total_confidence = (
            pattern_strength_score * 0.40 +
            code_quality_score * 0.30 +
            historical_accuracy_score * 0.20 +
            blast_radius_score * 0.10
        )

        # Determine deployment recommendation
        recommendation = self._get_deployment_recommendation(total_confidence)

        result = {
            'pattern_id': pattern_id,
            'pattern_name': pattern['pattern_name'],
            'validator_name': pattern['recommended_validator_name'],
            'scores': {
                'pattern_strength': round(pattern_strength_score, 1),
                'code_quality': round(code_quality_score, 1),
                'historical_accuracy': round(historical_accuracy_score, 1),
                'blast_radius': round(blast_radius_score, 1)
            },
            'total_confidence': round(total_confidence, 1),
            'recommendation': recommendation,
            'reasoning': self._generate_reasoning(pattern, total_confidence, recommendation)
        }

        # Print summary
        print(f"Pattern: {pattern['pattern_name']}")
        print(f"Validator: {pattern['recommended_validator_name']}\n")
        print(f"Confidence Breakdown:")
        print(f"  Pattern Strength:     {result['scores']['pattern_strength']:5.1f}/100 (40% weight)")
        print(f"  Code Quality:         {result['scores']['code_quality']:5.1f}/100 (30% weight)")
        print(f"  Historical Accuracy:  {result['scores']['historical_accuracy']:5.1f}/100 (20% weight)")
        print(f"  Blast Radius:         {result['scores']['blast_radius']:5.1f}/100 (10% weight)")
        print(f"\n{'─'*70}")
        print(f"  TOTAL CONFIDENCE:     {result['total_confidence']:5.1f}/100")
        print(f"{'─'*70}\n")
        print(f"Recommendation: {recommendation['action'].upper()}")
        print(f"Reasoning: {result['reasoning']}\n")

        return result

    def _load_pattern_with_validator(self, pattern_id: int) -> Optional[Dict]:
        """Load pattern with generated validator code"""
        query = text("""
            SELECT
                id,
                pattern_name,
                pattern_type,
                description,
                issue_count,
                affected_tickers,
                common_characteristics,
                impact_score,
                recurrence_frequency,
                recommended_validator_name,
                validator_code,
                validator_confidence_score,
                first_detected,
                last_occurrence
            FROM detected_patterns
            WHERE id = :pattern_id
        """)

        result = self.db.execute(query, {'pattern_id': pattern_id}).fetchone()

        if not result or not result[10]:  # No validator_code
            return None

        return {
            'id': result[0],
            'pattern_name': result[1],
            'pattern_type': result[2],
            'description': result[3],
            'issue_count': result[4],
            'affected_tickers': result[5],
            'common_characteristics': json.loads(result[6]) if result[6] else {},
            'impact_score': result[7],
            'recurrence_frequency': result[8],
            'recommended_validator_name': result[9],
            'validator_code': result[10],
            'validator_confidence_score': result[11],
            'first_detected': result[12],
            'last_occurrence': result[13]
        }

    def _score_pattern_strength(self, pattern: Dict) -> float:
        """
        Score pattern strength (0-100)

        Factors:
        - Issue count (more issues = stronger pattern)
        - Impact score (from pattern detection)
        - Recurrence frequency (daily/weekly = stronger)
        - Time span (longer = more established)
        """
        # Base: Impact score from pattern detection (0-100)
        base_score = pattern['impact_score']

        # Boost for high issue count
        issue_boost = min(10, pattern['issue_count'] - 3)  # 0-10 points

        # Boost for frequent recurrence
        frequency_map = {'daily': 10, 'weekly': 7, 'monthly': 4, 'rare': 0}
        frequency_boost = frequency_map.get(pattern['recurrence_frequency'], 5)

        # Boost for established pattern (time span)
        days_active = (pattern['last_occurrence'] - pattern['first_detected']).days
        time_boost = min(10, days_active / 7)  # 0-10 points (max at 10 weeks)

        total = base_score + issue_boost + frequency_boost + time_boost

        return min(100, total)

    def _score_code_quality(self, pattern: Dict) -> float:
        """
        Score generated code quality (0-100)

        Factors:
        - Syntax validity (50 points)
        - Completeness checks (30 points)
        - Docstring quality (10 points)
        - Error handling (10 points)
        """
        code = pattern['validator_code']
        score = 0

        # 1. Syntax validity (50 points)
        try:
            ast.parse(code)
            score += 50
        except:
            return 0  # Syntax error = auto-fail

        # 2. Completeness (30 points) - check for required components
        completeness_checks = [
            'def ' + pattern['recommended_validator_name'] in code,
            'spac: SPAC' in code,
            'List[Dict]' in code or 'list[dict]' in code.lower(),
            'issues = []' in code or 'issues = list()' in code,
            'return issues' in code,
            "'severity'" in code or '"severity"' in code,
            "'type'" in code or '"type"' in code,
            "'ticker'" in code or '"ticker"' in code,
            "'message'" in code or '"message"' in code,
            'if ' in code  # Has conditional logic
        ]
        completeness_score = (sum(completeness_checks) / len(completeness_checks)) * 30
        score += completeness_score

        # 3. Docstring quality (10 points)
        has_docstring = '"""' in code or "'''" in code
        docstring_keywords = ['Purpose', 'Auto-generated', 'Pattern', 'Lesson']
        docstring_quality = sum(1 for kw in docstring_keywords if kw in code)
        docstring_score = (5 if has_docstring else 0) + docstring_quality
        score += min(10, docstring_score)

        # 4. Error handling (10 points)
        error_handling_checks = [
            'if not ' in code or 'if spac.' in code,  # Checks for None
            'try:' in code or 'except' in code,  # Exception handling
            '.date()' in code or 'isinstance' in code  # Type handling
        ]
        error_handling_score = (sum(error_handling_checks) / len(error_handling_checks)) * 10
        score += error_handling_score

        return min(100, score)

    def _score_historical_accuracy(self, pattern: Dict) -> float:
        """
        Score based on historical validator performance (0-100)

        Factors:
        - Similar pattern validators' accuracy
        - Overall false positive rate of auto-generated validators
        - User feedback on previous generated validators
        """
        # Query validator_deployments for similar validators
        query = text("""
            SELECT
                AVG(
                    CASE
                        WHEN total_runs > 0
                        THEN (1.0 - (false_positives::FLOAT / total_runs)) * 100
                        ELSE 50
                    END
                ) as avg_accuracy,
                COUNT(*) as similar_count
            FROM validator_deployments vd
            JOIN detected_patterns dp ON vd.pattern_id = dp.id
            WHERE dp.pattern_type = :pattern_type
              AND vd.status IN ('active', 'monitoring')
              AND vd.total_runs >= 10
        """)

        result = self.db.execute(query, {
            'pattern_type': pattern['pattern_type']
        }).fetchone()

        if result and result[1] > 0:  # Have historical data
            avg_accuracy = result[0]
            similar_count = result[1]

            # Base score from average accuracy
            base_score = avg_accuracy

            # Boost for more similar validators (higher confidence)
            confidence_boost = min(10, similar_count * 2)

            total = base_score + confidence_boost
            return min(100, total)

        else:
            # No historical data - neutral score with penalty
            # First validator of this pattern type = more risk
            return 50.0  # Neutral with slight pessimism

    def _score_blast_radius(self, pattern: Dict) -> float:
        """
        Score blast radius / risk assessment (0-100)

        Lower risk = higher score
        Higher risk = lower score

        Factors:
        - Number of SPACs affected (more = higher risk)
        - Severity of issues (CRITICAL = higher risk if wrong)
        - Reversibility (can we easily rollback?)
        """
        # Base score (start pessimistic)
        score = 100

        # Penalty for large blast radius
        affected_count = len(pattern['affected_tickers'])
        if affected_count > 50:
            score -= 30
        elif affected_count > 20:
            score -= 20
        elif affected_count > 10:
            score -= 10

        # Penalty for CRITICAL severity (higher stakes if false positive)
        common_severity = pattern['common_characteristics'].get('common_severity', 'MEDIUM')
        if common_severity == 'CRITICAL':
            score -= 15
        elif common_severity == 'HIGH':
            score -= 10

        # Boost for data_corruption patterns (usually safe - they catch impossible data)
        if pattern['pattern_type'] == 'data_corruption':
            score += 10

        # Boost for small, focused validators (easier to rollback)
        code_lines = len(pattern['validator_code'].split('\n'))
        if code_lines < 50:
            score += 5

        return max(0, min(100, score))

    def _get_deployment_recommendation(self, confidence: float) -> Dict:
        """
        Generate deployment recommendation based on confidence score

        Thresholds:
        - ≥95%: Auto-deploy
        - 80-94%: Deploy with monitoring
        - 70-79%: Human review required
        - <70%: Reject
        """
        if confidence >= self.auto_deploy_threshold:
            return {
                'action': 'auto_deploy',
                'monitoring_period_days': 7,
                'requires_approval': False
            }
        elif confidence >= self.monitored_deploy_threshold:
            return {
                'action': 'deploy_with_monitoring',
                'monitoring_period_days': 14,
                'requires_approval': False
            }
        elif confidence >= self.human_review_threshold:
            return {
                'action': 'human_review',
                'monitoring_period_days': 7,
                'requires_approval': True
            }
        else:
            return {
                'action': 'reject',
                'monitoring_period_days': 0,
                'requires_approval': False
            }

    def _generate_reasoning(self, pattern: Dict, confidence: float,
                           recommendation: Dict) -> str:
        """Generate human-readable reasoning for decision"""
        action = recommendation['action']

        if action == 'auto_deploy':
            return (f"High confidence ({confidence:.1f}%) based on strong pattern "
                   f"({pattern['issue_count']} issues), good code quality, and low risk. "
                   f"Safe for automatic deployment with 7-day monitoring.")

        elif action == 'deploy_with_monitoring':
            return (f"Medium-high confidence ({confidence:.1f}%). Pattern is solid but "
                   f"requires extended 14-day monitoring to ensure no false positives.")

        elif action == 'human_review':
            return (f"Medium confidence ({confidence:.1f}%). Pattern detected but "
                   f"validator needs human review before deployment. Recommend reviewing "
                   f"generated code for accuracy.")

        else:  # reject
            return (f"Low confidence ({confidence:.1f}%). Pattern may not be strong enough "
                   f"or generated code has issues. Not recommended for deployment.")

    def save_confidence_score(self, pattern_id: int, scoring_result: Dict) -> bool:
        """Save confidence score to database"""
        try:
            update_query = text("""
                UPDATE detected_patterns
                SET validator_confidence_score = :confidence
                WHERE id = :pattern_id
            """)

            self.db.execute(update_query, {
                'pattern_id': pattern_id,
                'confidence': scoring_result['total_confidence']
            })

            self.db.commit()
            return True

        except Exception as e:
            print(f"⚠️  Could not save score: {e}")
            self.db.rollback()
            return False

    def __del__(self):
        """Cleanup"""
        if hasattr(self, 'db'):
            self.db.close()


class ValidatorMonitor:
    """
    Monitor deployed validators for performance and false positives

    Tracks:
    - Issues detected count
    - False positive rate
    - User feedback (approved/rejected fixes)
    - Execution time
    """

    def __init__(self):
        """Initialize monitor"""
        self.db = SessionLocal()

    def monitor_deployed_validators(self, days: int = 7) -> Dict:
        """
        Check performance of all deployed validators

        Args:
            days: Look at last N days of activity

        Returns: Dict with performance metrics and alerts
        """
        print(f"\n{'='*70}")
        print(f"Validator Performance Monitor (Last {days} Days)")
        print(f"{'='*70}\n")

        query = text("""
            SELECT
                vd.validator_name,
                vd.status,
                vd.confidence_score,
                vd.total_runs,
                vd.issues_detected,
                vd.false_positives,
                vd.user_approvals,
                vd.user_rejections,
                vd.deployed_at,
                EXTRACT(EPOCH FROM (NOW() - vd.deployed_at))/86400 as days_deployed
            FROM validator_deployments vd
            WHERE vd.status IN ('active', 'monitoring')
              AND vd.deployed_at >= NOW() - INTERVAL ':days days'
            ORDER BY vd.deployed_at DESC
        """)

        result = self.db.execute(query, {'days': days})

        validators = []
        alerts = []

        for row in result:
            validator = {
                'name': row[0],
                'status': row[1],
                'confidence': row[2],
                'total_runs': row[3],
                'issues_detected': row[4],
                'false_positives': row[5],
                'user_approvals': row[6],
                'user_rejections': row[7],
                'deployed_at': row[8],
                'days_deployed': round(row[9], 1)
            }

            # Calculate rates
            if validator['total_runs'] > 0:
                validator['false_positive_rate'] = round(
                    (validator['false_positives'] / validator['total_runs']) * 100, 1
                )
            else:
                validator['false_positive_rate'] = 0.0

            if (validator['user_approvals'] + validator['user_rejections']) > 0:
                validator['user_approval_rate'] = round(
                    (validator['user_approvals'] /
                     (validator['user_approvals'] + validator['user_rejections'])) * 100, 1
                )
            else:
                validator['user_approval_rate'] = None

            validators.append(validator)

            # Generate alerts
            # Alert 1: High false positive rate (>10%)
            if validator['false_positive_rate'] > 10 and validator['total_runs'] >= 10:
                alerts.append({
                    'type': 'high_false_positive_rate',
                    'validator': validator['name'],
                    'rate': validator['false_positive_rate'],
                    'recommendation': 'Consider disabling or refining validator'
                })

            # Alert 2: Low user approval rate (<60%)
            if validator['user_approval_rate'] and validator['user_approval_rate'] < 60:
                alerts.append({
                    'type': 'low_user_approval',
                    'validator': validator['name'],
                    'rate': validator['user_approval_rate'],
                    'recommendation': 'Users frequently reject fixes - review validator logic'
                })

            # Alert 3: No issues detected (possible dead validator)
            if validator['days_deployed'] >= 7 and validator['issues_detected'] == 0:
                alerts.append({
                    'type': 'no_issues_detected',
                    'validator': validator['name'],
                    'days': validator['days_deployed'],
                    'recommendation': 'Validator not detecting issues - may be unnecessary or pattern resolved'
                })

        # Print results
        print(f"Monitored Validators: {len(validators)}\n")

        for v in validators:
            status_icon = "✓" if v['status'] == 'active' else "⏱"
            print(f"{status_icon} {v['name']}")
            print(f"   Deployed: {v['deployed_at'].strftime('%Y-%m-%d')} ({v['days_deployed']} days ago)")
            print(f"   Runs: {v['total_runs']} | Issues: {v['issues_detected']} | "
                  f"False Pos: {v['false_positives']} ({v['false_positive_rate']}%)")

            if v['user_approval_rate'] is not None:
                print(f"   User Approval Rate: {v['user_approval_rate']}%")

            print()

        # Print alerts
        if alerts:
            print(f"\n{'='*70}")
            print(f"⚠️  ALERTS ({len(alerts)})")
            print(f"{'='*70}\n")

            for alert in alerts:
                print(f"⚠️  {alert['type'].replace('_', ' ').upper()}")
                print(f"   Validator: {alert['validator']}")
                if 'rate' in alert:
                    print(f"   Rate: {alert['rate']}%")
                if 'days' in alert:
                    print(f"   Days Deployed: {alert['days']}")
                print(f"   → {alert['recommendation']}")
                print()

        return {
            'validators': validators,
            'alerts': alerts
        }

    def rollback_validator(self, validator_name: str, reason: str) -> bool:
        """
        Disable a deployed validator

        Args:
            validator_name: Validator to disable
            reason: Reason for rollback

        Returns: Success boolean
        """
        try:
            update_query = text("""
                UPDATE validator_deployments
                SET
                    status = 'rolled_back',
                    disabled_at = NOW(),
                    disabled_reason = :reason
                WHERE validator_name = :validator_name
                  AND status IN ('active', 'monitoring')
            """)

            self.db.execute(update_query, {
                'validator_name': validator_name,
                'reason': reason
            })

            self.db.commit()
            print(f"✓ Rolled back validator: {validator_name}")
            return True

        except Exception as e:
            print(f"✗ Rollback failed: {e}")
            self.db.rollback()
            return False

    def __del__(self):
        """Cleanup"""
        if hasattr(self, 'db'):
            self.db.close()


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Phase 4: Confidence Engine & Monitoring')
    parser.add_argument('--score-pattern', type=int, metavar='ID',
                       help='Calculate confidence score for pattern')
    parser.add_argument('--check-deploy', type=int, metavar='ID',
                       help='Check if validator should be deployed')
    parser.add_argument('--monitor', action='store_true',
                       help='Monitor deployed validators')
    parser.add_argument('--rollback', type=str, metavar='VALIDATOR',
                       help='Rollback (disable) a validator')
    parser.add_argument('--reason', type=str, default='Manual rollback',
                       help='Reason for rollback')

    args = parser.parse_args()

    if args.score_pattern:
        engine = ConfidenceEngine()
        result = engine.score_pattern_validator(args.score_pattern)
        engine.save_confidence_score(args.score_pattern, result)

    elif args.check_deploy:
        engine = ConfidenceEngine()
        result = engine.score_pattern_validator(args.check_deploy)

        print("\n" + "="*70)
        print("DEPLOYMENT DECISION")
        print("="*70)

        if result['recommendation']['requires_approval']:
            print("\n❌ HUMAN REVIEW REQUIRED")
            print(f"   Confidence: {result['total_confidence']:.1f}%")
            print(f"   Reason: {result['reasoning']}")
        else:
            print(f"\n✓ {result['recommendation']['action'].upper()}")
            print(f"   Confidence: {result['total_confidence']:.1f}%")
            print(f"   Monitoring: {result['recommendation']['monitoring_period_days']} days")
            print(f"   Reason: {result['reasoning']}")

    elif args.monitor:
        monitor = ValidatorMonitor()
        monitor.monitor_deployed_validators(days=7)

    elif args.rollback:
        monitor = ValidatorMonitor()
        monitor.rollback_validator(args.rollback, args.reason)

    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python3 phase4_confidence_engine.py --score-pattern 1")
        print("  python3 phase4_confidence_engine.py --check-deploy 1")
        print("  python3 phase4_confidence_engine.py --monitor")
        print("  python3 phase4_confidence_engine.py --rollback validate_temporal_consistency --reason 'High false positives'")
