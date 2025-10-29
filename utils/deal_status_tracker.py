#!/usr/bin/env python3
"""
Deal Status State Machine

Ensures valid transitions for deal_status field:
- SEARCHING → ANNOUNCED → COMPLETED / TERMINATED / LIQUIDATED
- No backwards transitions allowed
- Validates state changes before updating database

Valid States:
- SEARCHING: Pre-deal SPAC looking for target
- ANNOUNCED: Deal announced, pending vote
- COMPLETED: Merger completed successfully
- TERMINATED: Deal terminated, back to searching
- LIQUIDATED: SPAC liquidated, returned cash to shareholders
- EXTENDED: Deadline extended (searching status)
"""

from datetime import date, datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

# Valid state transitions
VALID_TRANSITIONS = {
    'SEARCHING': ['ANNOUNCED', 'EXTENDED', 'LIQUIDATED'],
    'ANNOUNCED': ['COMPLETED', 'TERMINATED', 'LIQUIDATED'],
    'EXTENDED': ['ANNOUNCED', 'LIQUIDATED'],
    'TERMINATED': ['ANNOUNCED', 'LIQUIDATED'],  # Can announce new deal after termination
    'COMPLETED': [],  # Terminal state
    'LIQUIDATED': [],  # Terminal state
}


class InvalidStateTransition(Exception):
    """Raised when attempting an invalid deal status transition"""
    pass


def update_deal_status(
    db_session: Session,
    ticker: str,
    new_status: str,
    source: str,
    filing_date: Optional[date] = None,
    reason: str = None
) -> bool:
    """
    Update deal_status with state machine validation

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        new_status: New status to set
        source: Filing type that triggered update (8-K, DEFM14A, etc.)
        filing_date: Date of filing
        reason: Human-readable reason for status change

    Returns:
        True if status was updated, False if skipped

    Raises:
        InvalidStateTransition: If transition is not allowed
    """
    from database import SPAC

    # Get current SPAC record
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"❌ SPAC {ticker} not found")
        return False

    current_status = spac.deal_status or 'SEARCHING'
    new_status = new_status.upper()

    # Normalize statuses
    if current_status not in VALID_TRANSITIONS:
        current_status = 'SEARCHING'

    if new_status not in VALID_TRANSITIONS:
        print(f"⚠️  Invalid status: {new_status}")
        return False

    # Check if transition is valid
    if current_status == new_status:
        print(f"ℹ️  {ticker}: Status already {current_status}")
        return False

    if new_status not in VALID_TRANSITIONS[current_status]:
        error_msg = (
            f"Invalid transition: {current_status} → {new_status}\n"
            f"Valid transitions from {current_status}: {VALID_TRANSITIONS[current_status]}"
        )
        raise InvalidStateTransition(error_msg)

    # Valid transition - update status
    print(f"✓ Updating deal_status: {current_status} → {new_status}")
    print(f"  Source: {source}")
    if filing_date:
        print(f"  Filing date: {filing_date}")
    if reason:
        print(f"  Reason: {reason}")

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO deal_status_history
            (ticker, old_status, new_status, source, filing_date, reason, changed_at)
            VALUES
            (:ticker, :old_status, :new_status, :source, :filing_date, :reason, NOW())
        """), {
            'ticker': ticker,
            'old_status': current_status,
            'new_status': new_status,
            'source': source,
            'filing_date': filing_date,
            'reason': reason or f'Status transition from {source}'
        })
        print("  ✓ Logged to history")
    except Exception as e:
        # Table doesn't exist - create it in a separate transaction
        print(f"  ℹ️  Creating deal_status_history table...")
        try:
            db_session.rollback()  # Clear any failed transaction
            db_session.execute(text("""
                CREATE TABLE IF NOT EXISTS deal_status_history (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    old_status VARCHAR(20),
                    new_status VARCHAR(20) NOT NULL,
                    source VARCHAR(50),
                    filing_date DATE,
                    reason TEXT,
                    changed_at TIMESTAMP DEFAULT NOW()
                )
            """))
            db_session.commit()
            print("  ✓ Table created")

            # Try INSERT again
            db_session.execute(text("""
                INSERT INTO deal_status_history
                (ticker, old_status, new_status, source, filing_date, reason, changed_at)
                VALUES
                (:ticker, :old_status, :new_status, :source, :filing_date, :reason, NOW())
            """), {
                'ticker': ticker,
                'old_status': current_status,
                'new_status': new_status,
                'source': source,
                'filing_date': filing_date,
                'reason': reason or f'Status transition from {source}'
            })
            print("  ✓ Logged to history")
        except Exception as create_err:
            print(f"  ⚠️  Could not create table or log history: {create_err}")
            db_session.rollback()

    # Update SPAC record
    spac.deal_status = new_status
    db_session.commit()

    return True


def get_status_history(db_session: Session, ticker: str) -> list:
    """
    Get status transition history for a SPAC

    Returns list of status changes in chronological order
    """
    result = db_session.execute(text("""
        SELECT old_status, new_status, source, filing_date, reason, changed_at
        FROM deal_status_history
        WHERE ticker = :ticker
        ORDER BY changed_at ASC
    """), {'ticker': ticker})

    return [dict(row) for row in result]


def validate_transition(current_status: str, new_status: str) -> bool:
    """
    Check if a status transition is valid without updating database

    Args:
        current_status: Current deal status
        new_status: Proposed new status

    Returns:
        True if transition is valid, False otherwise
    """
    current_status = (current_status or 'SEARCHING').upper()
    new_status = new_status.upper()

    if current_status not in VALID_TRANSITIONS:
        current_status = 'SEARCHING'

    if new_status not in VALID_TRANSITIONS:
        return False

    return new_status in VALID_TRANSITIONS[current_status]


# Unit tests
if __name__ == "__main__":
    print("Testing deal_status state machine...\n")

    # Test valid transitions
    print("✅ Valid Transitions:")
    print(f"  SEARCHING → ANNOUNCED: {validate_transition('SEARCHING', 'ANNOUNCED')}")
    print(f"  ANNOUNCED → COMPLETED: {validate_transition('ANNOUNCED', 'COMPLETED')}")
    print(f"  ANNOUNCED → TERMINATED: {validate_transition('ANNOUNCED', 'TERMINATED')}")
    print(f"  TERMINATED → ANNOUNCED: {validate_transition('TERMINATED', 'ANNOUNCED')}")

    print("\n❌ Invalid Transitions:")
    print(f"  ANNOUNCED → SEARCHING: {validate_transition('ANNOUNCED', 'SEARCHING')}")
    print(f"  COMPLETED → ANNOUNCED: {validate_transition('COMPLETED', 'ANNOUNCED')}")
    print(f"  LIQUIDATED → SEARCHING: {validate_transition('LIQUIDATED', 'SEARCHING')}")

    print("\n" + "="*50)
    print("State Machine Rules:")
    for state, transitions in VALID_TRANSITIONS.items():
        print(f"  {state:15} → {', '.join(transitions) if transitions else 'TERMINAL STATE'}")
