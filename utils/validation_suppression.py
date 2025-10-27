#!/usr/bin/env python3
"""
Validation Suppression Utility

Manages suppressions for validation rules that user has confirmed are correct.
Prevents re-flagging of issues that have been reviewed and approved.

Usage:
    from utils.validation_suppression import suppress_issue, is_suppressed, list_suppressions

    # Suppress an issue
    suppress_issue(
        ticker='ISRL',
        rule_name='Stale Announced Deal (18+ months)',
        reason='Automatic extensions enabled with monthly deposits'
    )

    # Check if suppressed
    if is_suppressed('ISRL', 'Stale Announced Deal (18+ months)'):
        print("Issue is suppressed")

    # List all suppressions
    suppressions = list_suppressions()
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from typing import Optional, Dict, List
from sqlalchemy import text
from database import SessionLocal


def suppress_issue(
    ticker: str,
    rule_name: str,
    reason: str,
    issue_type: Optional[str] = None,
    original_issue: Optional[Dict] = None,
    conversation_id: Optional[str] = None,
    expires_in_days: Optional[int] = None
) -> bool:
    """
    Add a suppression rule for a validation issue

    Args:
        ticker: SPAC ticker symbol
        rule_name: Validation rule name (e.g., 'Stale Announced Deal (18+ months)')
        reason: Why this issue should be suppressed
        issue_type: Type of issue (e.g., 'stale_data', 'anomaly')
        original_issue: Original issue dict for reference
        conversation_id: ID of conversation where this was discussed
        expires_in_days: Days until suppression expires (None = permanent)

    Returns:
        True if suppression added/updated successfully
    """
    db = SessionLocal()
    try:
        expires_at = None
        if expires_in_days:
            expires_at = datetime.now() + timedelta(days=expires_in_days)

        query = text("""
            INSERT INTO validation_suppressions (
                ticker, rule_name, issue_type, reason, original_issue,
                conversation_id, expires_at, suppressed_at
            ) VALUES (
                :ticker, :rule_name, :issue_type, :reason, :original_issue::jsonb,
                :conversation_id, :expires_at, NOW()
            )
            ON CONFLICT (ticker, rule_name) DO UPDATE SET
                reason = EXCLUDED.reason,
                issue_type = EXCLUDED.issue_type,
                original_issue = EXCLUDED.original_issue,
                conversation_id = EXCLUDED.conversation_id,
                expires_at = EXCLUDED.expires_at,
                suppressed_at = NOW()
        """)

        db.execute(query, {
            'ticker': ticker,
            'rule_name': rule_name,
            'issue_type': issue_type,
            'reason': reason,
            'original_issue': str(original_issue) if original_issue else None,
            'conversation_id': conversation_id,
            'expires_at': expires_at
        })
        db.commit()

        print(f"✅ Suppressed: {rule_name} for {ticker}")
        if expires_in_days:
            print(f"   Expires in {expires_in_days} days")

        return True

    except Exception as e:
        print(f"❌ Error suppressing issue: {e}")
        db.rollback()
        return False

    finally:
        db.close()


def is_suppressed(ticker: str, rule_name: str) -> bool:
    """
    Check if a validation rule is suppressed for a ticker

    Args:
        ticker: SPAC ticker symbol
        rule_name: Validation rule name

    Returns:
        True if suppressed and not expired
    """
    db = SessionLocal()
    try:
        result = db.execute(
            text("""
                SELECT COUNT(*) FROM validation_suppressions
                WHERE ticker = :ticker
                  AND rule_name = :rule_name
                  AND (expires_at IS NULL OR expires_at > NOW())
            """),
            {'ticker': ticker, 'rule_name': rule_name}
        )
        count = result.scalar()
        return count > 0

    except Exception as e:
        print(f"⚠️  Error checking suppression: {e}")
        return False

    finally:
        db.close()


def remove_suppression(ticker: str, rule_name: str) -> bool:
    """
    Remove a suppression (re-enable validation for this rule)

    Args:
        ticker: SPAC ticker symbol
        rule_name: Validation rule name

    Returns:
        True if removed successfully
    """
    db = SessionLocal()
    try:
        result = db.execute(
            text("""
                DELETE FROM validation_suppressions
                WHERE ticker = :ticker AND rule_name = :rule_name
            """),
            {'ticker': ticker, 'rule_name': rule_name}
        )
        db.commit()

        if result.rowcount > 0:
            print(f"✅ Removed suppression: {rule_name} for {ticker}")
            return True
        else:
            print(f"⚠️  No suppression found for {ticker} / {rule_name}")
            return False

    except Exception as e:
        print(f"❌ Error removing suppression: {e}")
        db.rollback()
        return False

    finally:
        db.close()


def list_suppressions(ticker: Optional[str] = None, active_only: bool = True) -> List[Dict]:
    """
    List all suppressions

    Args:
        ticker: Filter by ticker (None = all tickers)
        active_only: Only show non-expired suppressions

    Returns:
        List of suppression dicts
    """
    db = SessionLocal()
    try:
        query = """
            SELECT
                ticker, rule_name, issue_type, reason,
                suppressed_at, expires_at, conversation_id
            FROM validation_suppressions
            WHERE 1=1
        """

        params = {}

        if ticker:
            query += " AND ticker = :ticker"
            params['ticker'] = ticker

        if active_only:
            query += " AND (expires_at IS NULL OR expires_at > NOW())"

        query += " ORDER BY suppressed_at DESC"

        result = db.execute(text(query), params)

        suppressions = []
        for row in result:
            suppressions.append({
                'ticker': row[0],
                'rule_name': row[1],
                'issue_type': row[2],
                'reason': row[3],
                'suppressed_at': row[4],
                'expires_at': row[5],
                'conversation_id': row[6]
            })

        return suppressions

    except Exception as e:
        print(f"❌ Error listing suppressions: {e}")
        return []

    finally:
        db.close()


def cleanup_expired_suppressions() -> int:
    """
    Remove expired suppressions from database

    Returns:
        Number of suppressions cleaned up
    """
    db = SessionLocal()
    try:
        result = db.execute(
            text("""
                DELETE FROM validation_suppressions
                WHERE expires_at IS NOT NULL AND expires_at <= NOW()
            """)
        )
        db.commit()

        count = result.rowcount
        if count > 0:
            print(f"✅ Cleaned up {count} expired suppression(s)")

        return count

    except Exception as e:
        print(f"❌ Error cleaning up suppressions: {e}")
        db.rollback()
        return 0

    finally:
        db.close()


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Validation Suppression Utility')
    parser.add_argument('--add', action='store_true', help='Add a suppression')
    parser.add_argument('--remove', action='store_true', help='Remove a suppression')
    parser.add_argument('--list', action='store_true', help='List suppressions')
    parser.add_argument('--cleanup', action='store_true', help='Clean up expired suppressions')

    parser.add_argument('--ticker', type=str, help='SPAC ticker')
    parser.add_argument('--rule', type=str, help='Rule name')
    parser.add_argument('--reason', type=str, help='Reason for suppression')
    parser.add_argument('--expires-days', type=int, help='Days until expiration')

    args = parser.parse_args()

    if args.add:
        if not args.ticker or not args.rule or not args.reason:
            print("❌ --add requires --ticker, --rule, and --reason")
            exit(1)

        suppress_issue(
            ticker=args.ticker,
            rule_name=args.rule,
            reason=args.reason,
            expires_in_days=args.expires_days
        )

    elif args.remove:
        if not args.ticker or not args.rule:
            print("❌ --remove requires --ticker and --rule")
            exit(1)

        remove_suppression(args.ticker, args.rule)

    elif args.list:
        suppressions = list_suppressions(ticker=args.ticker)

        if not suppressions:
            print("No suppressions found")
        else:
            print(f"\n📋 Suppressions: {len(suppressions)}\n")
            for s in suppressions:
                print(f"{'='*80}")
                print(f"Ticker: {s['ticker']}")
                print(f"Rule: {s['rule_name']}")
                print(f"Reason: {s['reason']}")
                print(f"Suppressed: {s['suppressed_at'].strftime('%Y-%m-%d %H:%M')}")
                if s['expires_at']:
                    print(f"Expires: {s['expires_at'].strftime('%Y-%m-%d %H:%M')}")
                else:
                    print("Expires: Never")
                print()

    elif args.cleanup:
        count = cleanup_expired_suppressions()
        print(f"Cleaned up {count} expired suppression(s)")

    else:
        parser.print_help()
        print("\nExamples:")
        print("  # Add suppression")
        print('  python3 utils/validation_suppression.py --add --ticker ISRL --rule "Stale Announced Deal (18+ months)" --reason "Auto-extensions enabled"')
        print("\n  # List all suppressions")
        print("  python3 utils/validation_suppression.py --list")
        print("\n  # List for specific ticker")
        print("  python3 utils/validation_suppression.py --list --ticker ISRL")
        print("\n  # Remove suppression")
        print('  python3 utils/validation_suppression.py --remove --ticker ISRL --rule "Stale Announced Deal (18+ months)"')
        print("\n  # Cleanup expired")
        print("  python3 utils/validation_suppression.py --cleanup")
