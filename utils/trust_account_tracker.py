#!/usr/bin/env python3
"""
Trust Account Tracker - Centralized trust account updates with precedence and history

Critical fields that MUST use date-based precedence:
1. trust_cash - Total $ in trust (from 10-Q, 10-K, 8-K)
2. trust_value - Per-share NAV (from 10-Q, 10-K, calculated)
3. shares_outstanding - Public redeemable shares (from 424B4, 8-K, 10-Q)

All agents should use these functions to ensure:
1. Latest filing always wins (date-based precedence)
2. History is tracked for audit trail
3. Null values don't overwrite real values
4. Source is tracked for debugging

Usage:
    from utils.trust_account_tracker import update_trust_cash, update_shares_outstanding

    update_trust_cash(
        db_session=db,
        ticker='CEP',
        new_value=500000000.0,  # $500M
        source='10-Q',
        filing_date=datetime(2025, 10, 1).date(),
        quarter='Q3 2025'
    )

    update_shares_outstanding(
        db_session=db,
        ticker='CEP',
        new_value=50000000.0,  # 50M shares
        source='8-K',
        filing_date=datetime(2025, 10, 5).date(),
        reason='After redemptions'
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


def update_trust_cash(
    db_session: Session,
    ticker: str,
    new_value: Optional[float],
    source: str,
    filing_date: date,
    quarter: Optional[str] = None
) -> bool:
    """
    Update trust_cash with date-based precedence and history tracking

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        new_value: New trust cash amount (e.g., 500000000.0 for $500M)
        source: Filing type (e.g., "10-Q", "10-K", "8-K")
        filing_date: Date of the filing
        quarter: Optional quarter (e.g., "Q3 2025")

    Returns:
        True if updated, False if skipped (precedence rules)

    Precedence Rules:
    1. Latest filing date wins
    2. Null values never overwrite existing values
    3. All changes logged to history

    CRITICAL: Trust cash changes quarterly. Out-of-order processing
    (Q3 before Q2) would give wrong balance without date precedence!
    """

    # Normalize source
    source = source.upper()

    # Get SPAC
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"   ⚠️  SPAC {ticker} not found")
        return False

    # Rule 1: Don't overwrite real values with null
    if new_value is None and spac.trust_cash:
        print(f"   ⏭️  Skipping null value (existing: ${spac.trust_cash:,.0f})")
        return False

    # Get current state
    old_value = spac.trust_cash
    old_source = spac.trust_cash_source
    old_filing_date = spac.trust_cash_filing_date

    # Rule 2: Latest filing date wins
    if old_value and old_filing_date:
        # Normalize dates for comparison (handle both date and datetime objects)
        filing_date_normalized = filing_date.date() if isinstance(filing_date, datetime) else filing_date
        old_filing_date_normalized = old_filing_date.date() if isinstance(old_filing_date, datetime) else old_filing_date

        if filing_date_normalized < old_filing_date_normalized:
            print(f"   ⏭️  Skipping older filing ({filing_date} < {old_filing_date})")
            return False
        elif filing_date == old_filing_date and old_source == source:
            # Same filing date and source - probably duplicate processing
            print(f"   ⏭️  Skipping duplicate (same date and source)")
            return False

    # If we get here, update is allowed
    old_str = f"${old_value:,.0f}" if old_value else "None"
    new_str = f"${new_value:,.0f}" if new_value else "None"
    print(f"   ✓ Updating trust_cash: {old_str} → {new_str}")
    print(f"     Source: {old_source or 'None'} → {source}")
    print(f"     Filing date: {old_filing_date or 'None'} → {filing_date}")
    if quarter:
        print(f"     Quarter: {quarter}")

    # Update SPAC record
    spac.trust_cash = new_value
    spac.trust_cash_source = source
    spac.trust_cash_filing_date = filing_date

    db_session.commit()

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO trust_account_history
            (ticker, field_name, old_value, new_value, source, filing_date, changed_at, quarter, reason)
            VALUES (:ticker, 'trust_cash', :old_value, :new_value, :source, :filing_date, :changed_at, :quarter, :reason)
        """), {
            'ticker': ticker,
            'old_value': str(old_value) if old_value else None,
            'new_value': str(new_value) if new_value else None,
            'source': source,
            'filing_date': filing_date,
            'changed_at': datetime.now(),
            'quarter': quarter,
            'reason': f"Updated from {source} filing" + (f" ({quarter})" if quarter else "")
        })
        db_session.commit()
        print(f"   ✓ Logged to history")
    except Exception as e:
        print(f"   ⚠️  History logging failed: {e}")
        # Don't fail the whole update if history logging fails
        db_session.rollback()
        db_session.commit()  # Re-commit the SPAC update

    # Recalculate trust_value if we have shares_outstanding
    if spac.shares_outstanding and spac.shares_outstanding > 0:
        spac.trust_value = round(new_value / spac.shares_outstanding, 2)
        print(f"   ✓ Recalculated trust_value: ${spac.trust_value:.2f} per share")
        db_session.commit()

    return True


def update_trust_value(
    db_session: Session,
    ticker: str,
    new_value: Optional[float],
    source: str,
    filing_date: date,
    quarter: Optional[str] = None
) -> bool:
    """
    Update trust_value (NAV per share) with date-based precedence

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        new_value: New trust value per share (e.g., 10.05)
        source: Filing type (e.g., "10-Q", "10-K", "CALCULATED")
        filing_date: Date of the filing (or calculation date)
        quarter: Optional quarter (e.g., "Q3 2025")

    Returns:
        True if updated, False if skipped

    Precedence Rules:
    1. Latest filing date wins
    2. Reported values preferred over calculated (10-Q/10-K > CALCULATED)
    3. Null values never overwrite existing values

    NOTE: If trust_cash or shares_outstanding change, trust_value should
    be recalculated automatically.
    """

    # Normalize source
    source = source.upper()

    # Source priority (lower number = higher priority)
    SOURCE_PRIORITY = {
        '10-Q': 1,      # Reported NAV (highest priority)
        '10-K': 1,      # Reported NAV (highest priority)
        'CALCULATED': 2  # Calculated from trust_cash / shares
    }

    # Get SPAC
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"   ⚠️  SPAC {ticker} not found")
        return False

    # Rule 1: Don't overwrite real values with null
    if new_value is None and spac.trust_value:
        print(f"   ⏭️  Skipping null value (existing: ${spac.trust_value:.2f})")
        return False

    # Get current state
    old_value = spac.trust_value
    old_source = spac.trust_value_source
    old_filing_date = spac.trust_value_filing_date

    # Rule 2: Latest filing date wins
    if old_value and old_filing_date:
        # Normalize dates for comparison (handle both date and datetime objects)
        filing_date_normalized = filing_date.date() if isinstance(filing_date, datetime) else filing_date
        old_filing_date_normalized = old_filing_date.date() if isinstance(old_filing_date, datetime) else old_filing_date

        if filing_date_normalized < old_filing_date_normalized:
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
    old_str = f"${old_value:.2f}" if old_value else "None"
    new_str = f"${new_value:.2f}" if new_value else "None"
    print(f"   ✓ Updating trust_value: {old_str} → {new_str}")
    print(f"     Source: {old_source or 'None'} → {source}")
    print(f"     Filing date: {old_filing_date or 'None'} → {filing_date}")

    # Update SPAC record
    spac.trust_value = new_value
    spac.trust_value_source = source
    spac.trust_value_filing_date = filing_date

    db_session.commit()

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO trust_account_history
            (ticker, field_name, old_value, new_value, source, filing_date, changed_at, quarter, reason)
            VALUES (:ticker, 'trust_value', :old_value, :new_value, :source, :filing_date, :changed_at, :quarter, :reason)
        """), {
            'ticker': ticker,
            'old_value': str(old_value) if old_value else None,
            'new_value': str(new_value) if new_value else None,
            'source': source,
            'filing_date': filing_date,
            'changed_at': datetime.now(),
            'quarter': quarter,
            'reason': f"Updated from {source}" + (f" ({quarter})" if quarter else "")
        })
        db_session.commit()
        print(f"   ✓ Logged to history")
    except Exception as e:
        print(f"   ⚠️  History logging failed: {e}")
        db_session.rollback()
        db_session.commit()

    # Recalculate premium (trust_value changed)
    recalculate_premium(db_session, ticker)

    return True


def update_shares_outstanding(
    db_session: Session,
    ticker: str,
    new_value: Optional[float],
    source: str,
    filing_date: date,
    reason: Optional[str] = None
) -> bool:
    """
    Update shares_outstanding with date-based precedence

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        new_value: New shares outstanding (e.g., 50000000.0 for 50M shares)
        source: Filing type (e.g., "424B4", "8-K", "10-Q")
        filing_date: Date of the filing
        reason: Optional reason (e.g., "After redemptions", "After overallotment")

    Returns:
        True if updated, False if skipped

    Precedence Rules:
    1. Latest filing date wins
    2. All changes logged to history

    CRITICAL: Shares change at IPO, overallotment, and redemptions.
    Out-of-order processing would give wrong share count!
    """

    # Normalize source
    source = source.upper()

    # Get SPAC
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"   ⚠️  SPAC {ticker} not found")
        return False

    # Rule 1: Don't overwrite real values with null
    if new_value is None and spac.shares_outstanding:
        print(f"   ⏭️  Skipping null value (existing: {spac.shares_outstanding:,.0f} shares)")
        return False

    # Get current state
    old_value = spac.shares_outstanding
    old_source = spac.shares_source
    old_filing_date = spac.shares_filing_date

    # Rule 2: Latest filing date wins
    if old_value and old_filing_date:
        # Normalize dates for comparison (handle both date and datetime objects)
        filing_date_normalized = filing_date.date() if isinstance(filing_date, datetime) else filing_date
        old_filing_date_normalized = old_filing_date.date() if isinstance(old_filing_date, datetime) else old_filing_date

        if filing_date_normalized < old_filing_date_normalized:
            print(f"   ⏭️  Skipping older filing ({filing_date} < {old_filing_date})")
            return False
        elif filing_date_normalized == old_filing_date_normalized and old_source == source:
            # Same filing date and source - probably duplicate
            print(f"   ⏭️  Skipping duplicate (same date and source)")
            return False

    # If we get here, update is allowed
    old_str = f"{old_value:,.0f} shares" if old_value else "None"
    new_str = f"{new_value:,.0f} shares" if new_value else "None"
    old_m = f"{old_value/1_000_000:.2f}M" if old_value else "None"
    new_m = f"{new_value/1_000_000:.2f}M" if new_value else "None"

    print(f"   ✓ Updating shares_outstanding: {old_m} → {new_m}")
    print(f"     Source: {old_source or 'None'} → {source}")
    print(f"     Filing date: {old_filing_date or 'None'} → {filing_date}")
    if reason:
        print(f"     Reason: {reason}")

    # Update SPAC record
    spac.shares_outstanding = new_value
    spac.shares_source = source
    spac.shares_filing_date = filing_date

    db_session.commit()

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO trust_account_history
            (ticker, field_name, old_value, new_value, source, filing_date, changed_at, quarter, reason)
            VALUES (:ticker, 'shares_outstanding', :old_value, :new_value, :source, :filing_date, :changed_at, NULL, :reason)
        """), {
            'ticker': ticker,
            'old_value': str(old_value) if old_value else None,
            'new_value': str(new_value) if new_value else None,
            'source': source,
            'filing_date': filing_date,
            'changed_at': datetime.now(),
            'reason': reason or f"Updated from {source} filing"
        })
        db_session.commit()
        print(f"   ✓ Logged to history")
    except Exception as e:
        print(f"   ⚠️  History logging failed: {e}")
        db_session.rollback()
        db_session.commit()

    # Recalculate trust_value if we have trust_cash
    if spac.trust_cash and spac.trust_cash > 0 and new_value > 0:
        old_nav = spac.trust_value
        new_nav = round(spac.trust_cash / new_value, 2)
        spac.trust_value = new_nav
        print(f"   ✓ Recalculated trust_value: ${old_nav:.2f} → ${new_nav:.2f} per share")
        db_session.commit()

        # Recalculate premium (trust_value changed)
        recalculate_premium(db_session, ticker)

    return True


def recalculate_premium(db_session: Session, ticker: str) -> bool:
    """
    Recalculate premium based on current price and trust_value

    Premium = ((price - trust_value) / trust_value) * 100

    This should be called whenever:
    - trust_value changes
    - price changes

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker

    Returns:
        True if recalculated, False if skipped
    """

    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        return False

    # Need both price and trust_value to calculate premium
    if not spac.price or not spac.trust_value:
        return False

    old_premium = spac.premium

    # Convert to float for calculation (handle Decimal types)
    price = float(spac.price)
    trust_value = float(spac.trust_value)

    new_premium = round(((price - trust_value) / trust_value) * 100, 2)

    # Only update if changed
    if old_premium != new_premium:
        spac.premium = new_premium
        db_session.commit()
        print(f"   ✓ Recalculated premium: {old_premium:.2f}% → {new_premium:.2f}%")
        return True

    return False


def get_trust_account_history(db_session: Session, ticker: str, field_name: Optional[str] = None) -> list:
    """
    Get trust account change history for a SPAC

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        field_name: Optional filter by field (trust_cash, trust_value, shares_outstanding)

    Returns:
        List of history entries (newest first)
    """

    if field_name:
        result = db_session.execute(text("""
            SELECT field_name, old_value, new_value, source, filing_date, changed_at, quarter, reason
            FROM trust_account_history
            WHERE ticker = :ticker AND field_name = :field_name
            ORDER BY changed_at DESC
        """), {'ticker': ticker, 'field_name': field_name})
    else:
        result = db_session.execute(text("""
            SELECT field_name, old_value, new_value, source, filing_date, changed_at, quarter, reason
            FROM trust_account_history
            WHERE ticker = :ticker
            ORDER BY changed_at DESC
        """), {'ticker': ticker})

    history = []
    for row in result:
        history.append({
            'field_name': row[0],
            'old_value': row[1],
            'new_value': row[2],
            'source': row[3],
            'filing_date': row[4],
            'changed_at': row[5],
            'quarter': row[6],
            'reason': row[7]
        })

    return history


def get_spacs_with_trust_changes(db_session: Session, min_changes: int = 2, field_name: Optional[str] = None) -> list:
    """
    Find SPACs where trust account data changed multiple times

    Args:
        db_session: SQLAlchemy session
        min_changes: Minimum number of changes to include
        field_name: Optional filter by field

    Returns:
        List of tickers with change counts
    """

    if field_name:
        result = db_session.execute(text("""
            SELECT ticker, COUNT(*) as change_count
            FROM trust_account_history
            WHERE field_name = :field_name
            GROUP BY ticker
            HAVING COUNT(*) >= :min_changes
            ORDER BY change_count DESC
        """), {'min_changes': min_changes, 'field_name': field_name})
    else:
        result = db_session.execute(text("""
            SELECT ticker, COUNT(*) as change_count
            FROM trust_account_history
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
    """Test the trust account tracker"""

    from database import SessionLocal
    from datetime import datetime, date

    db = SessionLocal()

    print("="*70)
    print("TESTING TRUST ACCOUNT TRACKER")
    print("="*70)

    # Test 1: Initial trust_cash from 10-Q
    print("\nTest 1: Initial trust_cash from Q2 2025 10-Q")
    update_trust_cash(
        db_session=db,
        ticker='CEP',
        new_value=500000000.0,  # $500M
        source='10-Q',
        filing_date=date(2025, 8, 15),
        quarter='Q2 2025'
    )

    # Test 2: Try older filing (should be skipped)
    print("\nTest 2: Try older Q1 2025 10-Q (should skip)")
    update_trust_cash(
        db_session=db,
        ticker='CEP',
        new_value=495000000.0,
        source='10-Q',
        filing_date=date(2025, 5, 15),  # Older
        quarter='Q1 2025'
    )

    # Test 3: Update from Q3 10-Q (should update)
    print("\nTest 3: Update from Q3 2025 10-Q (should update)")
    update_trust_cash(
        db_session=db,
        ticker='CEP',
        new_value=505000000.0,  # Increased due to interest
        source='10-Q',
        filing_date=date(2025, 11, 15),
        quarter='Q3 2025'
    )

    # Test 4: Update shares_outstanding from IPO
    print("\nTest 4: Initial shares_outstanding from 424B4")
    update_shares_outstanding(
        db_session=db,
        ticker='CEP',
        new_value=50000000.0,  # 50M shares
        source='424B4',
        filing_date=date(2024, 3, 1),
        reason='IPO closing'
    )

    # Test 5: Update shares after redemptions
    print("\nTest 5: Update shares after redemptions (8-K)")
    update_shares_outstanding(
        db_session=db,
        ticker='CEP',
        new_value=45000000.0,  # 5M redeemed
        source='8-K',
        filing_date=date(2025, 11, 20),
        reason='After redemptions'
    )

    # Show history
    print("\n" + "="*70)
    print("TRUST ACCOUNT HISTORY FOR CEP")
    print("="*70)

    history = get_trust_account_history(db, 'CEP')
    for entry in history:
        print(f"\n{entry['changed_at']}")
        print(f"  Field: {entry['field_name']}")
        print(f"  {entry['old_value']} → {entry['new_value']}")
        print(f"  Source: {entry['source']} (filed: {entry['filing_date']})")
        if entry['quarter']:
            print(f"  Quarter: {entry['quarter']}")
        print(f"  Reason: {entry['reason']}")

    db.close()

    print("\n✅ Tests complete!")
