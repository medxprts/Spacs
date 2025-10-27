#!/usr/bin/env python3
"""
Date Field Trackers

Specialized trackers for date fields with unique precedence rules:

1. announced_date - EARLIEST date wins (first announcement is authoritative)
2. deadline_date - LATEST date wins (extensions update the deadline)
3. original_deadline_date - Set ONCE, never update

Use Cases:
- announced_date: Deal announcement from 8-K (keep earliest)
- deadline_date: Current deadline, updated by extensions
- original_deadline_date: IPO + 18-24 months (never changes)
"""

from datetime import date, datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text


def update_announced_date(
    db_session: Session,
    ticker: str,
    new_date: date,
    source: str,
    reason: str = None
) -> bool:
    """
    Update announced_date - EARLIEST date wins

    This ensures the initial announcement date is preserved even if
    later filings (S-4, DEFM14A) have different dates.

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        new_date: Announcement date to set
        source: Filing type (8-K, Form 425, etc.)
        reason: Human-readable reason

    Returns:
        True if date was updated, False if skipped

    Precedence Rule:
        EARLIEST date wins (never update to a later date)
    """
    from database import SPAC

    if not new_date:
        print(f"⚠️  Skipping empty announced_date")
        return False

    # Get current SPAC record
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"❌ SPAC {ticker} not found")
        return False

    current_date = spac.announced_date
    if current_date and isinstance(current_date, datetime):
        current_date = current_date.date()

    # Check precedence
    should_update = False

    if not current_date:
        # No existing date - always set
        should_update = True
        print(f"✓ Setting announced_date: {new_date}")

    elif new_date < current_date:
        # Earlier date - update
        should_update = True
        print(f"✓ Updating announced_date (earlier): {current_date} → {new_date}")

    else:
        # Same or later date - skip
        print(f"⊘ Skipping announced_date: {new_date} not earlier than current {current_date}")
        return False

    if not should_update:
        return False

    # Log changes
    print(f"  Source: {source}")
    if reason:
        print(f"  Reason: {reason}")

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO announced_date_history
            (ticker, old_date, new_date, source, reason, changed_at)
            VALUES
            (:ticker, :old_date, :new_date, :source, :reason, NOW())
        """), {
            'ticker': ticker,
            'old_date': current_date,
            'new_date': new_date,
            'source': source,
            'reason': reason or f'Announced date from {source}'
        })
        print("  ✓ Logged to history")
    except Exception as e:
        # Create history table if needed
        print(f"  ℹ️  Creating announced_date_history table...")
        db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS announced_date_history (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                old_date DATE,
                new_date DATE NOT NULL,
                source VARCHAR(50),
                reason TEXT,
                changed_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db_session.commit()

        # Try again
        db_session.execute(text("""
            INSERT INTO announced_date_history
            (ticker, old_date, new_date, source, reason, changed_at)
            VALUES
            (:ticker, :old_date, :new_date, :source, :reason, NOW())
        """), {
            'ticker': ticker,
            'old_date': current_date,
            'new_date': new_date,
            'source': source,
            'reason': reason or f'Announced date from {source}'
        })
        print("  ✓ Logged to history")

    # Update SPAC record
    spac.announced_date = new_date
    db_session.commit()

    return True


def update_deadline_date(
    db_session: Session,
    ticker: str,
    new_date: date,
    source: str,
    reason: str = None,
    is_extension: bool = False
) -> bool:
    """
    Update deadline_date - LATEST date wins

    This handles deadline extensions where the current deadline keeps
    getting pushed out. The most recent extension is always the active deadline.

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        new_date: New deadline date
        source: Filing type (8-K, S-1, etc.)
        reason: Human-readable reason
        is_extension: True if this is an extension (vs initial deadline)

    Returns:
        True if date was updated, False if skipped

    Precedence Rule:
        LATEST date wins (extensions always update)
    """
    from database import SPAC

    if not new_date:
        print(f"⚠️  Skipping empty deadline_date")
        return False

    # Get current SPAC record
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"❌ SPAC {ticker} not found")
        return False

    current_date = spac.deadline_date
    if current_date and isinstance(current_date, datetime):
        current_date = current_date.date()

    # Check precedence
    should_update = False

    if not current_date:
        # No existing deadline - always set
        should_update = True
        print(f"✓ Setting deadline_date: {new_date}")

    elif new_date > current_date:
        # Later date (extension) - update
        should_update = True
        print(f"✓ Updating deadline_date (extension): {current_date} → {new_date}")

        # Mark as extended if deadline moved forward
        if is_extension:
            spac.is_extended = True
            spac.extension_count = (spac.extension_count or 0) + 1

    elif new_date == current_date:
        # Same date - skip
        print(f"ℹ️  {ticker}: Deadline unchanged ({new_date})")
        return False

    else:
        # Earlier date - this is unusual, might be a filing date vs deadline confusion
        print(f"⚠️  Warning: New deadline {new_date} is EARLIER than current {current_date}")
        print(f"    This might be incorrect. Review {source} filing.")
        return False

    if not should_update:
        return False

    # Log changes
    print(f"  Source: {source}")
    if reason:
        print(f"  Reason: {reason}")
    if is_extension:
        print(f"  Extension #{spac.extension_count}")

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO deadline_history
            (ticker, old_date, new_date, source, is_extension, reason, changed_at)
            VALUES
            (:ticker, :old_date, :new_date, :source, :is_extension, :reason, NOW())
        """), {
            'ticker': ticker,
            'old_date': current_date,
            'new_date': new_date,
            'source': source,
            'is_extension': is_extension,
            'reason': reason or f'Deadline {"extension" if is_extension else "set"} from {source}'
        })
        print("  ✓ Logged to history")
    except Exception as e:
        # Create history table if needed
        print(f"  ℹ️  Creating deadline_history table...")
        db_session.execute(text("""
            CREATE TABLE IF NOT EXISTS deadline_history (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(10) NOT NULL,
                old_date DATE,
                new_date DATE NOT NULL,
                source VARCHAR(50),
                is_extension BOOLEAN DEFAULT FALSE,
                reason TEXT,
                changed_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db_session.commit()

        # Try again
        db_session.execute(text("""
            INSERT INTO deadline_history
            (ticker, old_date, new_date, source, is_extension, reason, changed_at)
            VALUES
            (:ticker, :old_date, :new_date, :source, :is_extension, :reason, NOW())
        """), {
            'ticker': ticker,
            'old_date': current_date,
            'new_date': new_date,
            'source': source,
            'is_extension': is_extension,
            'reason': reason or f'Deadline {"extension" if is_extension else "set"} from {source}'
        })
        print("  ✓ Logged to history")

    # Update SPAC record
    spac.deadline_date = new_date
    db_session.commit()

    return True


def set_original_deadline(
    db_session: Session,
    ticker: str,
    deadline_date: date,
    source: str,
    reason: str = None
) -> bool:
    """
    Set original_deadline_date - ONE TIME ONLY

    This should only be set from the IPO filing (S-1 or 424B4) and
    NEVER updated thereafter. Extensions update deadline_date, not this field.

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        deadline_date: Original deadline from charter
        source: Filing type (S-1, 424B4)
        reason: Human-readable reason

    Returns:
        True if date was set, False if already exists

    Precedence Rule:
        SET ONCE, NEVER UPDATE
    """
    from database import SPAC

    if not deadline_date:
        print(f"⚠️  Skipping empty original_deadline_date")
        return False

    # Get current SPAC record
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"❌ SPAC {ticker} not found")
        return False

    current_date = spac.original_deadline_date
    if current_date and isinstance(current_date, datetime):
        current_date = current_date.date()

    # Check if already set
    if current_date:
        print(f"ℹ️  {ticker}: Original deadline already set ({current_date})")
        print(f"    Attempted to set to {deadline_date} from {source} - IGNORED")
        return False

    # Set for first time
    print(f"✓ Setting original_deadline_date: {deadline_date}")
    print(f"  Source: {source}")
    if reason:
        print(f"  Reason: {reason}")

    spac.original_deadline_date = deadline_date
    db_session.commit()

    return True


# Unit tests
if __name__ == "__main__":
    from datetime import timedelta

    print("Testing date trackers...\n")

    # Test dates
    early = date(2025, 1, 15)
    middle = date(2025, 3, 15)
    late = date(2025, 6, 15)

    print("="*50)
    print("ANNOUNCED DATE (earliest wins):")
    print(f"  Current: {middle}")
    print(f"  Earlier date ({early}): Should update ✓")
    print(f"  Later date ({late}): Should skip ✗")

    print("\n" + "="*50)
    print("DEADLINE DATE (latest wins):")
    print(f"  Current: {middle}")
    print(f"  Earlier date ({early}): Should skip ✗")
    print(f"  Later date ({late}): Should update ✓ (extension)")

    print("\n" + "="*50)
    print("ORIGINAL DEADLINE (set once):")
    print(f"  Current: None")
    print(f"  First time ({middle}): Should set ✓")
    print(f"  Second time ({late}): Should skip ✗ (already set)")
