#!/usr/bin/env python3
"""
Deal Value Tracker - Centralized deal_value updates with precedence and history

All agents should use update_deal_value() to ensure:
1. Latest filing always wins (date-based precedence)
2. History is tracked for audit trail
3. Null values don't overwrite real values
4. Source is tracked for debugging

Usage:
    from utils.deal_value_tracker import update_deal_value

    update_deal_value(
        db_session=db,
        ticker='CEP',
        new_value='$500M',
        source='DEFM14A',
        filing_date=datetime(2025, 10, 1).date()
    )
"""

import os
import sys
from datetime import datetime, date
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SPAC


def update_deal_value(
    db_session: Session,
    ticker: str,
    new_value: Optional[str],
    source: str,
    filing_date: date,
    reason: Optional[str] = None
) -> bool:
    """
    Update deal_value with date-based precedence and history tracking

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        new_value: New deal value (e.g., "$500M", "$1.5B")
        source: Filing type (e.g., "8-K", "DEFM14A", "S-4")
        filing_date: Date of the filing
        reason: Optional reason for update

    Returns:
        True if updated, False if skipped (precedence rules)

    Precedence Rules:
    1. Latest filing date wins
    2. If same date, higher priority source wins:
       S-4 (1) > DEFM14A (2) > 8-K (3) > Schedule TO (4)
    3. Null values never overwrite existing values
    4. Empty strings never overwrite existing values
    """

    # Source priority (lower number = higher priority)
    SOURCE_PRIORITY = {
        'S-4': 1,
        'DEFM14A': 2,
        'PREM14A': 2,
        '8-K': 3,
        'SC TO': 4,
        'SC 13E3': 4,
        'UNKNOWN': 99
    }

    # Normalize source
    source = source.upper()

    # Get SPAC
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"   ⚠️  SPAC {ticker} not found")
        return False

    # Normalize new value
    if new_value:
        new_value = new_value.strip()
        if not new_value:  # Empty string
            new_value = None

    # Rule 1: Don't overwrite real values with null
    if not new_value and spac.deal_value:
        print(f"   ⏭️  Skipping null value (existing: {spac.deal_value})")
        return False

    # Get current state
    old_value = spac.deal_value
    old_source = spac.deal_value_source
    old_filing_date = spac.deal_value_filing_date

    # Rule 2: If we have existing data, check precedence
    if old_value and old_filing_date:
        # Compare filing dates
        if filing_date < old_filing_date:
            print(f"   ⏭️  Skipping older filing ({filing_date} < {old_filing_date})")
            return False

        elif filing_date == old_filing_date:
            # Same date - check source priority
            old_priority = SOURCE_PRIORITY.get(old_source, 99)
            new_priority = SOURCE_PRIORITY.get(source, 99)

            if new_priority >= old_priority:
                print(f"   ⏭️  Skipping lower priority source ({source} vs {old_source})")
                return False

    # If we get here, update is allowed
    print(f"   ✓ Updating deal_value: {old_value} → {new_value}")
    print(f"     Source: {old_source or 'None'} → {source}")
    print(f"     Filing date: {old_filing_date or 'None'} → {filing_date}")

    # Update SPAC record
    spac.deal_value = new_value
    spac.deal_value_source = source
    spac.deal_value_filing_date = filing_date
    spac.deal_value_updated_at = datetime.now()

    db_session.commit()

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO deal_value_history
            (ticker, old_value, new_value, source, filing_date, changed_at, reason)
            VALUES (:ticker, :old_value, :new_value, :source, :filing_date, :changed_at, :reason)
        """), {
            'ticker': ticker,
            'old_value': old_value,
            'new_value': new_value,
            'source': source,
            'filing_date': filing_date,
            'changed_at': datetime.now(),
            'reason': reason or f"Updated from {source} filing"
        })
        db_session.commit()
        print(f"   ✓ Logged to history")
    except Exception as e:
        print(f"   ⚠️  History logging failed: {e}")
        # Don't fail the whole update if history logging fails
        db_session.rollback()
        db_session.commit()  # Re-commit the SPAC update

    return True


def get_deal_value_history(db_session: Session, ticker: str) -> list:
    """
    Get deal value change history for a SPAC

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker

    Returns:
        List of history entries (newest first)
    """

    result = db_session.execute(text("""
        SELECT old_value, new_value, source, filing_date, changed_at, reason
        FROM deal_value_history
        WHERE ticker = :ticker
        ORDER BY changed_at DESC
    """), {'ticker': ticker})

    history = []
    for row in result:
        history.append({
            'old_value': row[0],
            'new_value': row[1],
            'source': row[2],
            'filing_date': row[3],
            'changed_at': row[4],
            'reason': row[5]
        })

    return history


def get_spacs_with_multiple_valuations(db_session: Session, min_changes: int = 2) -> list:
    """
    Find SPACs where deal value changed multiple times

    Args:
        db_session: SQLAlchemy session
        min_changes: Minimum number of changes to include

    Returns:
        List of tickers with change counts
    """

    result = db_session.execute(text("""
        SELECT ticker, COUNT(*) as change_count
        FROM deal_value_history
        GROUP BY ticker
        HAVING COUNT(*) >= :min_changes
        ORDER BY change_count DESC
    """), {'min_changes': min_changes})

    spacs = []
    for row in result:
        spacs.append({
            'ticker': row[0],
            'change_count': row[1]
        })

    return spacs


if __name__ == "__main__":
    """Test the deal value tracker"""

    from database import SessionLocal
    from datetime import datetime, date

    db = SessionLocal()

    print("="*70)
    print("TESTING DEAL VALUE TRACKER")
    print("="*70)

    # Test 1: Update from 8-K
    print("\nTest 1: Initial value from 8-K")
    update_deal_value(
        db_session=db,
        ticker='CEP',
        new_value='$500M',
        source='8-K',
        filing_date=date(2025, 9, 1),
        reason='Initial deal announcement'
    )

    # Test 2: Try older filing (should be skipped)
    print("\nTest 2: Try older filing (should skip)")
    update_deal_value(
        db_session=db,
        ticker='CEP',
        new_value='$450M',
        source='8-K',
        filing_date=date(2025, 8, 1),  # Older date
        reason='Older filing - should be skipped'
    )

    # Test 3: Update from DEFM14A (newer date + higher priority)
    print("\nTest 3: Update from DEFM14A (should update)")
    update_deal_value(
        db_session=db,
        ticker='CEP',
        new_value='$525M',
        source='DEFM14A',
        filing_date=date(2025, 10, 1),
        reason='Refined valuation in merger proxy'
    )

    # Test 4: Try 8-K from same date (should skip - lower priority)
    print("\nTest 4: Try 8-K from same date (should skip - lower priority)")
    update_deal_value(
        db_session=db,
        ticker='CEP',
        new_value='$480M',
        source='8-K',
        filing_date=date(2025, 10, 1),  # Same date
        reason='Should be skipped - lower priority than DEFM14A'
    )

    # Test 5: Update from S-4 (highest priority)
    print("\nTest 5: Update from S-4 (highest priority - should update)")
    update_deal_value(
        db_session=db,
        ticker='CEP',
        new_value='$520M',
        source='S-4',
        filing_date=date(2025, 10, 15),
        reason='Final valuation in merger registration'
    )

    # Show history
    print("\n" + "="*70)
    print("DEAL VALUE HISTORY FOR CEP")
    print("="*70)

    history = get_deal_value_history(db, 'CEP')
    for entry in history:
        print(f"\n{entry['changed_at']}")
        print(f"  {entry['old_value']} → {entry['new_value']}")
        print(f"  Source: {entry['source']} (filed: {entry['filing_date']})")
        print(f"  Reason: {entry['reason']}")

    db.close()

    print("\n✅ Tests complete!")
