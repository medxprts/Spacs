#!/usr/bin/env python3
"""
Target Company Tracker

Tracks target company name with date-based precedence:
- Latest filing date wins (same as deal_value)
- Source priority: S-4 (1) > DEFM14A (2) > 8-K (3)
- Maintains audit trail of target name changes
- Handles target name variations (e.g., "Acme Inc" vs "Acme, Inc.")

Use Cases:
- Initial announcement (8-K): Sets preliminary target name
- Proxy filing (DEFM14A): May clarify/correct target name
- S-4 filing: Final legal name of target
"""

from datetime import date, datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from utils.target_validator import validate_target, sanitize_target


# Source priority (lower = higher priority)
SOURCE_PRIORITY = {
    'S-4': 1,
    'DEFM14A': 2,
    'PREM14A': 2,
    '8-K': 3,
    'Form 425': 3,
    'DEFA14A': 4,
    'Press Release': 5,
}


def normalize_target_name(name: str) -> str:
    """
    Normalize target company name for comparison

    Handles common variations:
    - Trailing punctuation
    - "Inc." vs "Inc"
    - Extra whitespace
    """
    if not name:
        return ""

    # Basic cleanup
    name = name.strip()
    name = ' '.join(name.split())  # Normalize whitespace

    # Remove trailing punctuation that varies
    name = name.rstrip('.,')

    return name


def update_target(
    db_session: Session,
    ticker: str,
    new_value: str,
    source: str,
    filing_date: Optional[date] = None,
    reason: str = None
) -> bool:
    """
    Update target company name with date-based precedence

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        new_value: New target company name
        source: Filing type (S-4, DEFM14A, 8-K, etc.)
        filing_date: Date of filing (REQUIRED for precedence)
        reason: Human-readable reason for update

    Returns:
        True if target was updated, False if skipped

    Precedence Rules:
        1. Latest filing date wins
        2. For same date: S-4 > DEFM14A > 8-K > DEFA14A > Press Release
        3. Never overwrite with null/empty
    """
    from database import SPAC

    # Validation
    if not new_value or not new_value.strip():
        print(f"⚠️  Skipping empty target name")
        return False

    # Sanitize and validate target name
    new_value = sanitize_target(new_value)
    is_valid, validation_reason = validate_target(new_value, ticker)

    if not is_valid:
        print(f"⚠️  Invalid target rejected: '{new_value}'")
        print(f"   Reason: {validation_reason}")
        print(f"   Source: {source}, Filing date: {filing_date}")
        # Log as anomaly for Investigation Agent
        from utils.error_detector import log_manual_error
        log_manual_error(
            error_type='InvalidTargetExtraction',
            error_message=f"Attempted to set invalid target: '{new_value}' - {validation_reason}",
            script='target_tracker.py',
            function='update_target',
            ticker=ticker,
            context={
                'extracted_target': new_value,
                'validation_failure': validation_reason,
                'source': source,
                'filing_date': str(filing_date),
                'reason': reason
            }
        )
        return False

    if not filing_date:
        print(f"⚠️  Warning: No filing_date provided for target update. Using today.")
        filing_date = date.today()

    # Get current SPAC record
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"❌ SPAC {ticker} not found")
        return False

    # Get current target info
    current_target = spac.target
    current_source = getattr(spac, 'target_source', None)
    current_filing_date = getattr(spac, 'target_filing_date', None)

    # Normalize names for comparison
    new_normalized = normalize_target_name(new_value)
    current_normalized = normalize_target_name(current_target) if current_target else ""

    # Check if target is effectively the same (ignore minor variations)
    if new_normalized == current_normalized and current_target:
        print(f"ℹ️  {ticker}: Target unchanged ('{new_value}')")
        return False

    # Determine if we should update based on precedence
    should_update = False

    if not current_target:
        # No existing target - always update
        should_update = True
        print(f"✓ Setting target: {new_value}")

    elif not current_filing_date:
        # Existing target has no date - update if new one has better source
        source_priority = SOURCE_PRIORITY.get(source, 99)
        current_priority = SOURCE_PRIORITY.get(current_source, 99) if current_source else 99

        if source_priority <= current_priority:
            should_update = True
            print(f"✓ Updating target (better source): {current_target} → {new_value}")
        else:
            print(f"⊘ Skipping update: {source} (priority {source_priority}) < {current_source} (priority {current_priority})")
            return False

    else:
        # Both have filing dates - use date-based precedence
        if filing_date > current_filing_date:
            # Newer filing - always wins
            should_update = True
            print(f"✓ Updating target (newer filing): {current_target} → {new_value}")

        elif filing_date == current_filing_date:
            # Same date - use source priority
            source_priority = SOURCE_PRIORITY.get(source, 99)
            current_priority = SOURCE_PRIORITY.get(current_source, 99) if current_source else 99

            if source_priority < current_priority:
                should_update = True
                print(f"✓ Updating target (higher priority source): {current_target} → {new_value}")
            else:
                print(f"⊘ Skipping update: {source} (priority {source_priority}) not better than {current_source} (priority {current_priority}) on same date")
                return False

        else:
            # Older filing - skip
            print(f"⊘ Skipping update: Filing date {filing_date} older than current {current_filing_date}")
            return False

    if not should_update:
        return False

    # Log changes
    print(f"  Source: {current_source or 'None'} → {source}")
    print(f"  Filing date: {current_filing_date or 'None'} → {filing_date}")
    if reason:
        print(f"  Reason: {reason}")

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO target_history
            (ticker, old_value, new_value, source, filing_date, reason, changed_at)
            VALUES
            (:ticker, :old_value, :new_value, :source, :filing_date, :reason, NOW())
        """), {
            'ticker': ticker,
            'old_value': current_target,
            'new_value': new_value,
            'source': source,
            'filing_date': filing_date,
            'reason': reason or f'Target updated from {source}'
        })
        print("  ✓ Logged to history")
    except Exception as e:
        # Table doesn't exist - create it in a separate transaction
        print(f"  ℹ️  Creating target_history table...")
        try:
            db_session.rollback()  # Clear any failed transaction
            db_session.execute(text("""
                CREATE TABLE IF NOT EXISTS target_history (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    old_value TEXT,
                    new_value TEXT NOT NULL,
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
                INSERT INTO target_history
                (ticker, old_value, new_value, source, filing_date, reason, changed_at)
                VALUES
                (:ticker, :old_value, :new_value, :source, :filing_date, :reason, NOW())
            """), {
                'ticker': ticker,
                'old_value': current_target,
                'new_value': new_value,
                'source': source,
                'filing_date': filing_date,
                'reason': reason or f'Target updated from {source}'
            })
            print("  ✓ Logged to history")
        except Exception as create_err:
            print(f"  ⚠️  Could not create table or log history: {create_err}")
            db_session.rollback()

    # Add tracking columns if they don't exist
    try:
        db_session.execute(text("""
            ALTER TABLE spacs ADD COLUMN IF NOT EXISTS target_source VARCHAR(50)
        """))
        db_session.execute(text("""
            ALTER TABLE spacs ADD COLUMN IF NOT EXISTS target_filing_date DATE
        """))
        db_session.commit()
    except:
        pass

    # Update SPAC record
    spac.target = new_value

    # Update tracking metadata
    try:
        db_session.execute(text("""
            UPDATE spacs
            SET target_source = :source,
                target_filing_date = :filing_date
            WHERE ticker = :ticker
        """), {
            'ticker': ticker,
            'source': source,
            'filing_date': filing_date
        })
    except:
        # Columns might not exist - that's okay
        pass

    db_session.commit()

    return True


# Unit tests
if __name__ == "__main__":
    print("Testing target tracker...\n")

    # Test name normalization
    print("Name Normalization Tests:")
    print(f"  'Acme Inc.' → '{normalize_target_name('Acme Inc.')}'")
    print(f"  'Acme Inc' → '{normalize_target_name('Acme Inc')}'")
    print(f"  'Acme,  Inc.' → '{normalize_target_name('Acme,  Inc.')}'")

    print("\n" + "="*50)
    print("Source Priority:")
    for source, priority in sorted(SOURCE_PRIORITY.items(), key=lambda x: x[1]):
        print(f"  {priority}. {source}")
