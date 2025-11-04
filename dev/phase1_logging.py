#!/usr/bin/env python3
"""
phase1_logging.py - Enhanced Validation Failure Logging

Purpose: Wrap production DataValidatorAgent to log all validation failures
         to validation_failures table for pattern detection analysis.

Architecture:
    Production DataValidatorAgent (unchanged)
        ↓
    ValidationLoggingWrapper (this file)
        ↓
    validation_failures table → Pattern Detection (Phase 2)

Usage:
    # Setup database tables
    python3 phase1_logging.py --setup

    # Test logging
    python3 phase1_logging.py --test

    # Run validation with logging on all SPACs
    python3 phase1_logging.py --validate-all

Integration with production:
    from dev.phase1_logging import ValidationLoggingWrapper
    validator = ValidationLoggingWrapper()
    issues = validator.validate_spac(spac)  # Auto-logs to DB
"""

import sys
import os
from datetime import datetime
from typing import List, Dict, Optional
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, SPAC
from sqlalchemy import text


class ValidationLoggingWrapper:
    """
    Wraps production DataValidatorAgent to add logging capability

    Non-invasive: Does not modify production validator, only adds logging layer
    """

    def __init__(self, enable_logging: bool = True):
        """
        Initialize wrapper

        Args:
            enable_logging: If False, acts as pure pass-through (no logging)
        """
        # Import production validator
        from data_validator_core import DataValidatorAgent

        self.production_validator = DataValidatorAgent()
        self.enable_logging = enable_logging
        self.db = SessionLocal()

        print(f"✓ ValidationLoggingWrapper initialized")
        print(f"  Logging: {'ENABLED' if enable_logging else 'DISABLED'}")


    def validate_spac(self, spac: SPAC) -> List[Dict]:
        """
        Validate SPAC and log failures

        This is a drop-in replacement for DataValidatorAgent.validate_all()

        Returns: Same format as production validator
        """
        # Call production validator (unchanged)
        issues = self.production_validator.validate_all(spac)

        # Log failures if enabled
        if self.enable_logging and issues:
            self._log_validation_failures(spac, issues)

        return issues


    def _log_validation_failures(self, spac: SPAC, issues: List[Dict]):
        """
        Log validation failures to database for pattern analysis

        Args:
            spac: SPAC that was validated
            issues: List of validation issues from production validator
        """
        try:
            for issue in issues:
                # Extract core fields
                ticker = spac.ticker
                validation_method = self._extract_validation_method(issue)
                issue_type = issue.get('type', 'unknown')
                severity = issue.get('severity', 'MEDIUM')
                field = issue.get('field')
                error_message = issue.get('message', '')

                # Extract expected/actual values
                expected_value = str(issue.get('expected', ''))
                actual_value = str(issue.get('actual', ''))

                # Build metadata JSON
                metadata = {
                    'rule': issue.get('rule'),
                    'auto_fix': issue.get('auto_fix'),
                    'issue_metadata': issue.get('metadata', {}),
                    'spac_cik': spac.cik,
                    'spac_company': spac.company,
                    'deal_status': spac.deal_status
                }

                # Extract related fields from issue metadata
                related_fields = {}
                if 'metadata' in issue and isinstance(issue['metadata'], dict):
                    # Example: ATMV temporal issue includes ipo_date, announced_date
                    for key, value in issue['metadata'].items():
                        if key in ['ipo_date', 'announced_date', 'completion_date',
                                   'trust_cash', 'trust_value', 'shares_outstanding']:
                            related_fields[key] = str(value)

                # Insert into validation_failures table
                insert_query = text("""
                    INSERT INTO validation_failures (
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
                    ) VALUES (
                        :ticker,
                        :validation_method,
                        :issue_type,
                        :severity,
                        :field,
                        :expected_value,
                        :actual_value,
                        :error_message,
                        :metadata,
                        :related_fields,
                        :detected_at
                    )
                """)

                self.db.execute(insert_query, {
                    'ticker': ticker,
                    'validation_method': validation_method,
                    'issue_type': issue_type,
                    'severity': severity,
                    'field': field,
                    'expected_value': expected_value,
                    'actual_value': actual_value,
                    'error_message': error_message,
                    'metadata': json.dumps(metadata),
                    'related_fields': json.dumps(related_fields),
                    'detected_at': datetime.now()
                })

            self.db.commit()
            print(f"  ✓ Logged {len(issues)} validation failure(s) for {spac.ticker}")

        except Exception as e:
            print(f"  ⚠️  Logging failed (non-critical): {e}")
            self.db.rollback()
            # Don't raise - logging failure shouldn't break validation


    def _extract_validation_method(self, issue: Dict) -> str:
        """
        Extract validation method name from issue

        Production validator doesn't always include this, so we infer it
        """
        # Some issues include 'rule' field that hints at validator
        rule = issue.get('rule', '')
        issue_type = issue.get('type', '')

        # Map issue types to validator methods (best effort)
        method_mapping = {
            'temporal_impossibility': 'validate_temporal_consistency',
            'cik_mismatch': 'validate_cik_consistency',
            'missing_critical': 'validate_ipo_basics',
            'trust_value_unusual': 'validate_trust_value_reasonableness',
            'market_cap_mismatch': 'validate_market_cap_consistency',
            'premium_outlier': 'validate_premium_reasonableness',
            'trust_cash_unusual': 'validate_trust_cash_matches_ipo',
            'invalid_target': 'validate_deal_data'
        }

        if issue_type in method_mapping:
            return method_mapping[issue_type]

        # Fallback: use issue type as method name
        return f"validate_{issue_type}"


    def log_fix_result(self, ticker: str, issue: Dict, fix_applied: bool,
                      fix_method: str, fix_success: bool, fix_details: Optional[Dict] = None):
        """
        Log the result of applying a fix

        Call this from orchestrator after fix is applied

        Args:
            ticker: SPAC ticker
            issue: Original issue dict
            fix_applied: Whether fix was applied
            fix_method: "auto_applied", "user_approved", "skipped"
            fix_success: Whether fix succeeded
            fix_details: Details of what was changed
        """
        try:
            # Find the most recent validation failure for this issue
            query = text("""
                UPDATE validation_failures
                SET
                    fix_applied = :fix_applied,
                    fix_method = :fix_method,
                    fix_success = :fix_success,
                    fix_applied_at = :fix_applied_at,
                    fix_details = :fix_details,
                    resolved_at = :resolved_at
                WHERE id = (
                    SELECT id FROM validation_failures
                    WHERE ticker = :ticker
                      AND issue_type = :issue_type
                      AND field = :field
                      AND fix_applied = false
                    ORDER BY detected_at DESC
                    LIMIT 1
                )
            """)

            self.db.execute(query, {
                'fix_applied': fix_applied,
                'fix_method': fix_method,
                'fix_success': fix_success,
                'fix_applied_at': datetime.now() if fix_applied else None,
                'fix_details': json.dumps(fix_details) if fix_details else None,
                'resolved_at': datetime.now() if fix_success else None,
                'ticker': ticker,
                'issue_type': issue.get('type'),
                'field': issue.get('field')
            })

            self.db.commit()
            print(f"  ✓ Logged fix result for {ticker} ({fix_method})")

        except Exception as e:
            print(f"  ⚠️  Fix logging failed: {e}")
            self.db.rollback()


    def get_unresolved_issues(self, days: int = 30) -> List[Dict]:
        """
        Get unresolved validation failures for pattern analysis

        Args:
            days: Look back this many days

        Returns: List of unresolved issues
        """
        query = text("""
            SELECT
                id,
                ticker,
                validation_method,
                issue_type,
                severity,
                field,
                error_message,
                metadata,
                detected_at
            FROM validation_failures
            WHERE fix_applied = false
              AND detected_at >= NOW() - INTERVAL ':days days'
            ORDER BY detected_at DESC
        """)

        result = self.db.execute(query, {'days': days})
        return [dict(row) for row in result.fetchall()]


    def __del__(self):
        """Cleanup database connection"""
        if hasattr(self, 'db'):
            self.db.close()


# ============================================================================
# Setup and Testing Functions
# ============================================================================

def setup_database():
    """
    Create validation_failures tables in database

    Runs the SQL schema file
    """
    print("Setting up validation_failures tables...")

    db = SessionLocal()
    try:
        # Read SQL file
        sql_file = os.path.join(os.path.dirname(__file__), 'validation_failures.sql')
        with open(sql_file, 'r') as f:
            sql = f.read()

        # Execute SQL (split by semicolon for multiple statements)
        statements = sql.split(';')
        for statement in statements:
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                try:
                    db.execute(text(statement))
                except Exception as e:
                    # Some statements may fail if already exist (OK)
                    if 'already exists' not in str(e).lower():
                        print(f"  ⚠️  Statement warning: {e}")

        db.commit()
        print("✓ Database setup complete")
        print("\nTables created:")
        print("  - validation_failures")
        print("  - detected_patterns")
        print("  - validator_deployments")
        print("  - learning_feedback")
        print("\nViews created:")
        print("  - active_patterns_summary")
        print("  - validator_performance")
        print("  - recent_validation_failures")

    except Exception as e:
        print(f"✗ Setup failed: {e}")
        db.rollback()
        return False
    finally:
        db.close()

    return True


def test_logging():
    """
    Test validation logging on a few SPACs

    This validates the logging mechanism works without breaking production validator
    """
    print("\n" + "="*60)
    print("Testing Validation Logging Wrapper")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        # Get 5 SPACs to test
        spacs = db.query(SPAC).limit(5).all()

        print(f"Testing on {len(spacs)} SPACs...\n")

        # Create wrapper with logging enabled
        wrapper = ValidationLoggingWrapper(enable_logging=True)

        total_issues = 0
        for spac in spacs:
            print(f"Validating {spac.ticker} ({spac.company})...")
            issues = wrapper.validate_spac(spac)

            if issues:
                print(f"  Found {len(issues)} issue(s)")
                total_issues += len(issues)
            else:
                print(f"  ✓ No issues found")

        print(f"\n✓ Test complete")
        print(f"  Total issues logged: {total_issues}")

        # Verify logging worked
        query = text("SELECT COUNT(*) as count FROM validation_failures WHERE detected_at >= NOW() - INTERVAL '1 minute'")
        result = db.execute(query).fetchone()
        logged_count = result[0]

        print(f"  Database records created: {logged_count}")

        if logged_count == total_issues:
            print("\n✓ All issues successfully logged!")
            return True
        else:
            print(f"\n⚠️  Mismatch: Expected {total_issues}, logged {logged_count}")
            return False

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def validate_all_spacs():
    """
    Run validation with logging on ALL SPACs

    Use this for initial data collection
    """
    print("\n" + "="*60)
    print("Running Validation with Logging on ALL SPACs")
    print("="*60 + "\n")

    db = SessionLocal()
    try:
        # Get all SPACs
        spacs = db.query(SPAC).all()
        total = len(spacs)

        print(f"Validating {total} SPACs...\n")

        # Create wrapper
        wrapper = ValidationLoggingWrapper(enable_logging=True)

        total_issues = 0
        spacs_with_issues = 0

        for i, spac in enumerate(spacs, 1):
            print(f"[{i}/{total}] {spac.ticker}...", end=' ')

            issues = wrapper.validate_spac(spac)

            if issues:
                print(f"{len(issues)} issue(s)")
                total_issues += len(issues)
                spacs_with_issues += 1
            else:
                print("OK")

        print(f"\n" + "="*60)
        print("Validation Complete")
        print("="*60)
        print(f"Total SPACs: {total}")
        print(f"SPACs with issues: {spacs_with_issues}")
        print(f"Total issues found: {total_issues}")
        print(f"Average issues per SPAC: {total_issues/total:.1f}")

        # Show breakdown by severity
        query = text("""
            SELECT severity, COUNT(*) as count
            FROM validation_failures
            WHERE detected_at >= NOW() - INTERVAL '5 minutes'
            GROUP BY severity
            ORDER BY
                CASE severity
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'HIGH' THEN 2
                    WHEN 'MEDIUM' THEN 3
                    ELSE 4
                END
        """)
        result = db.execute(query)

        print("\nBreakdown by severity:")
        for row in result:
            print(f"  {row[0]}: {row[1]}")

        return True

    except Exception as e:
        print(f"\n✗ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def show_recent_failures(limit: int = 20):
    """Show recent validation failures"""
    db = SessionLocal()
    try:
        query = text("""
            SELECT
                ticker,
                issue_type,
                severity,
                field,
                error_message,
                detected_at
            FROM validation_failures
            ORDER BY detected_at DESC
            LIMIT :limit
        """)

        result = db.execute(query, {'limit': limit})

        print(f"\nRecent Validation Failures (last {limit}):")
        print("-" * 80)

        for row in result:
            print(f"{row[5].strftime('%Y-%m-%d %H:%M')} | {row[0]:6s} | {row[2]:8s} | {row[1]:20s} | {row[3] or 'N/A':15s}")
            if row[4]:
                print(f"  └─ {row[4][:100]}")

    finally:
        db.close()


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Phase 1: Validation Failure Logging')
    parser.add_argument('--setup', action='store_true', help='Setup database tables')
    parser.add_argument('--test', action='store_true', help='Test logging on 5 SPACs')
    parser.add_argument('--validate-all', action='store_true', help='Validate all SPACs with logging')
    parser.add_argument('--show-recent', type=int, metavar='N', help='Show N recent failures')

    args = parser.parse_args()

    if args.setup:
        success = setup_database()
        sys.exit(0 if success else 1)

    elif args.test:
        success = test_logging()
        sys.exit(0 if success else 1)

    elif args.validate_all:
        success = validate_all_spacs()
        sys.exit(0 if success else 1)

    elif args.show_recent:
        show_recent_failures(args.show_recent)

    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python3 phase1_logging.py --setup          # Create tables")
        print("  python3 phase1_logging.py --test           # Test on 5 SPACs")
        print("  python3 phase1_logging.py --validate-all   # Full validation run")
        print("  python3 phase1_logging.py --show-recent 20 # Show last 20 failures")
