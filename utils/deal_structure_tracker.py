#!/usr/bin/env python3
"""
Deal Structure Fields Tracker

Extends deal_value_tracker logic to handle all deal structure fields:
- min_cash: Minimum cash condition
- min_cash_percentage: Minimum cash as % of trust
- pipe_size: PIPE investment amount
- pipe_price: PIPE price per share
- earnout_shares: Earnout/contingent shares
- forward_purchase: Forward purchase agreement amount

All fields use same precedence as deal_value:
- Latest filing date wins
- Source priority: S-4 (1) > DEFM14A (2) > 8-K (3)
"""

from datetime import date, datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text


# Source priority (lower = higher priority)
SOURCE_PRIORITY = {
    'S-4': 1,
    'DEFM14A': 2,
    'PREM14A': 2,
    '8-K': 3,
    'Form 425': 3,
    'Schedule TO': 4,
    'DEFA14A': 4,
}

# Tracked deal structure fields
DEAL_STRUCTURE_FIELDS = [
    'min_cash',
    'min_cash_percentage',
    'pipe_size',
    'pipe_price',
    'earnout_shares',
    'forward_purchase',
    'has_pipe',
    'has_earnout',
]


def update_deal_structure_field(
    db_session: Session,
    ticker: str,
    field_name: str,
    new_value: Any,
    source: str,
    filing_date: Optional[date] = None,
    reason: str = None
) -> bool:
    """
    Update a single deal structure field with date-based precedence

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        field_name: Name of field to update (min_cash, pipe_size, etc.)
        new_value: New value to set
        source: Filing type (S-4, DEFM14A, 8-K, etc.)
        filing_date: Date of filing (REQUIRED for precedence)
        reason: Human-readable reason for update

    Returns:
        True if field was updated, False if skipped

    Precedence Rules:
        1. Latest filing date wins
        2. For same date: S-4 > DEFM14A > 8-K
        3. Never overwrite with null/empty
    """
    from database import SPAC

    if field_name not in DEAL_STRUCTURE_FIELDS:
        print(f"⚠️  Unknown deal structure field: {field_name}")
        return False

    # Null/empty check
    if new_value is None or (isinstance(new_value, str) and not new_value.strip()):
        print(f"⊘ Skipping {field_name}: null/empty value")
        return False

    if not filing_date:
        print(f"⚠️  Warning: No filing_date for {field_name}. Using today.")
        filing_date = date.today()

    # Get current SPAC record
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"❌ SPAC {ticker} not found")
        return False

    # Get current value and tracking metadata
    current_value = getattr(spac, field_name, None)

    # Get tracking metadata
    source_field = f"{field_name}_source"
    date_field = f"{field_name}_filing_date"

    # Try to get current source and date
    try:
        result = db_session.execute(text(f"""
            SELECT {source_field}, {date_field}
            FROM spacs
            WHERE ticker = :ticker
        """), {'ticker': ticker})
        row = result.fetchone()
        current_source = row[0] if row else None
        current_filing_date = row[1] if row else None
    except:
        # Columns don't exist yet
        current_source = None
        current_filing_date = None

    # Check if value is effectively unchanged
    if current_value == new_value:
        print(f"ℹ️  {ticker}: {field_name} unchanged ({new_value})")
        return False

    # Determine if we should update based on precedence
    should_update = False

    if current_value is None:
        # No existing value - always update
        should_update = True
        print(f"✓ Setting {field_name}: {new_value}")

    elif not current_filing_date:
        # Existing value has no date - update if new one has better source
        source_priority = SOURCE_PRIORITY.get(source, 99)
        current_priority = SOURCE_PRIORITY.get(current_source, 99) if current_source else 99

        if source_priority <= current_priority:
            should_update = True
            print(f"✓ Updating {field_name} (better source): {current_value} → {new_value}")
        else:
            print(f"⊘ Skipping {field_name}: {source} (priority {source_priority}) < {current_source} (priority {current_priority})")
            return False

    else:
        # Both have filing dates - use date-based precedence
        if filing_date > current_filing_date:
            # Newer filing - always wins
            should_update = True
            print(f"✓ Updating {field_name} (newer filing): {current_value} → {new_value}")

        elif filing_date == current_filing_date:
            # Same date - use source priority
            source_priority = SOURCE_PRIORITY.get(source, 99)
            current_priority = SOURCE_PRIORITY.get(current_source, 99) if current_source else 99

            if source_priority < current_priority:
                should_update = True
                print(f"✓ Updating {field_name} (higher priority): {current_value} → {new_value}")
            else:
                print(f"⊘ Skipping {field_name}: {source} not better than {current_source} on same date")
                return False

        else:
            # Older filing - skip
            print(f"⊘ Skipping {field_name}: Filing date {filing_date} < current {current_filing_date}")
            return False

    if not should_update:
        return False

    # Log changes
    print(f"  Source: {current_source or 'None'} → {source}")
    print(f"  Filing date: {current_filing_date or 'None'} → {filing_date}")
    if reason:
        print(f"  Reason: {reason}")

    # Ensure history table exists BEFORE attempting insert
    try:
        # Check if table exists (lightweight query)
        db_session.execute(text("SELECT 1 FROM deal_structure_history LIMIT 1"))
    except:
        # Table doesn't exist - create it in a separate transaction
        print(f"  ℹ️  Creating deal_structure_history table...")
        try:
            db_session.rollback()  # Clear any failed transaction
            db_session.execute(text("""
                CREATE TABLE IF NOT EXISTS deal_structure_history (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    field_name VARCHAR(50) NOT NULL,
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
        except Exception as create_err:
            print(f"  ⚠️  Could not create table: {create_err}")
            db_session.rollback()

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO deal_structure_history
            (ticker, field_name, old_value, new_value, source, filing_date, reason, changed_at)
            VALUES
            (:ticker, :field_name, :old_value, :new_value, :source, :filing_date, :reason, NOW())
        """), {
            'ticker': ticker,
            'field_name': field_name,
            'old_value': str(current_value) if current_value is not None else None,
            'new_value': str(new_value),
            'source': source,
            'filing_date': filing_date,
            'reason': reason or f'{field_name} from {source}'
        })
        print("  ✓ Logged to history")
    except Exception as e:
        print(f"  ⚠️  Could not log to history: {e}")
        # Don't fail the whole update if history logging fails
        db_session.rollback()

    # Add tracking columns if they don't exist
    try:
        db_session.execute(text(f"""
            ALTER TABLE spacs ADD COLUMN IF NOT EXISTS {source_field} VARCHAR(50)
        """))
        db_session.execute(text(f"""
            ALTER TABLE spacs ADD COLUMN IF NOT EXISTS {date_field} DATE
        """))
        db_session.commit()
    except:
        pass

    # Update SPAC record
    setattr(spac, field_name, new_value)

    # Update tracking metadata
    try:
        db_session.execute(text(f"""
            UPDATE spacs
            SET {source_field} = :source,
                {date_field} = :filing_date
            WHERE ticker = :ticker
        """), {
            'ticker': ticker,
            'source': source,
            'filing_date': filing_date
        })
    except:
        # Columns might not exist - that's okay
        pass

    # Commit with error monitoring
    try:
        db_session.commit()
        return True
    except Exception as e:
        # Log failure and alert
        from utils.database_monitor import log_write_failure
        log_write_failure(
            operation='deal_structure_update',
            ticker=ticker,
            error=e,
            context={
                'field_name': field_name,
                'new_value': new_value,
                'source': source,
                'filing_date': filing_date
            }
        )
        print(f"      ❌ Database commit failed: {e}")
        db_session.rollback()
        return False


def update_deal_structure(
    db_session: Session,
    ticker: str,
    structure_data: Dict[str, Any],
    source: str,
    filing_date: Optional[date] = None,
    reason: str = None
) -> Dict[str, bool]:
    """
    Update multiple deal structure fields at once

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        structure_data: Dictionary of field_name: value pairs
        source: Filing type
        filing_date: Date of filing
        reason: Human-readable reason

    Returns:
        Dictionary of field_name: updated (bool) showing what changed

    Example:
        update_deal_structure(
            db, 'CEP',
            {
                'min_cash': 250000000.0,
                'pipe_size': 100000000.0,
                'pipe_price': 10.0,
                'has_pipe': True
            },
            source='8-K',
            filing_date=date(2025, 3, 15),
            reason='Deal announcement'
        )
    """
    results = {}

    for field_name, value in structure_data.items():
        if field_name in DEAL_STRUCTURE_FIELDS:
            updated = update_deal_structure_field(
                db_session=db_session,
                ticker=ticker,
                field_name=field_name,
                new_value=value,
                source=source,
                filing_date=filing_date,
                reason=reason
            )
            results[field_name] = updated
        else:
            print(f"⚠️  Unknown field: {field_name}")
            results[field_name] = False

    return results


# Unit tests
if __name__ == "__main__":
    print("Testing deal structure tracker...\n")

    print("="*50)
    print("Tracked Fields:")
    for field in DEAL_STRUCTURE_FIELDS:
        print(f"  - {field}")

    print("\n" + "="*50)
    print("Source Priority:")
    for source, priority in sorted(SOURCE_PRIORITY.items(), key=lambda x: x[1]):
        print(f"  {priority}. {source}")

    print("\n" + "="*50)
    print("Example Usage:")
    print("""
    update_deal_structure(
        db, 'CEP',
        {
            'min_cash': 250_000_000.0,
            'pipe_size': 100_000_000.0,
            'pipe_price': 10.0,
            'earnout_shares': 15_000_000.0,
            'has_pipe': True,
            'has_earnout': True
        },
        source='DEFM14A',
        filing_date=date(2025, 5, 15),
        reason='Final deal terms from proxy'
    )
    """)
