#!/usr/bin/env python3
"""
Redemption Tracker - Incremental redemption tracking with deduplication

CRITICAL: Redemptions must be INCREMENTAL (add to total), not REPLACEMENT.

Each 8-K or DEFM14A reports a redemption event:
- Event 1: 5M shares redeemed
- Event 2: 3M shares redeemed
- Total: 8M shares redeemed (NOT 3M!)

This tracker ensures:
1. Redemptions are cumulative (increment, not overwrite)
2. Same filing not processed twice (deduplication)
3. shares_outstanding is updated correctly
4. Full audit trail
5. Distinction between "not checked" vs "checked and zero"

Usage - When redemptions are found:
    from utils.redemption_tracker import add_redemption_event

    add_redemption_event(
        db_session=db,
        ticker='CEP',
        shares_redeemed=5000000,  # 5M shares
        redemption_amount=50500000.0,  # $50.5M
        filing_date=datetime(2025, 11, 1).date(),
        source='8-K',
        reason='Shareholder redemptions before merger vote'
    )

Usage - When NO redemptions are found:
    from utils.redemption_tracker import mark_no_redemptions_found

    mark_no_redemptions_found(
        db_session=db,
        ticker='CEP',
        source='DEFM14A',
        filing_date=datetime(2025, 11, 1).date(),
        reason='Checked DEFM14A, no redemptions reported'
    )

This marks redemptions_occurred = FALSE (vs NULL for unchecked)
"""

import os
import sys
import json
from datetime import datetime, date
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SPAC
from utils.trust_account_tracker import update_shares_outstanding, update_trust_cash


def add_redemption_event(
    db_session: Session,
    ticker: str,
    shares_redeemed: int,
    redemption_amount: float,
    filing_date: date,
    source: str,
    reason: Optional[str] = None
) -> bool:
    """
    Add a redemption event (INCREMENTAL - adds to cumulative total)

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        shares_redeemed: Shares redeemed in THIS event (e.g., 5000000 for 5M)
        redemption_amount: Dollar amount redeemed in THIS event
        filing_date: Date of the filing
        source: Filing type (e.g., "8-K", "DEFM14A")
        reason: Optional reason

    Returns:
        True if added, False if already processed (duplicate)

    CRITICAL: This function INCREMENTS totals, does NOT overwrite!

    Example:
        - Initial: 50M shares, $500M trust cash
        - Event 1: 5M shares redeemed @ $10.10 = $50.5M
          → shares: 45M, trust: $449.5M, total redeemed: 5M/$50.5M
        - Event 2: 3M shares redeemed @ $10.10 = $30.3M
          → shares: 42M, trust: $419.2M, total redeemed: 8M/$80.8M
    """

    # Normalize source
    source = source.upper()

    # Get SPAC
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"   ⚠️  SPAC {ticker} not found")
        return False

    # Check if we've already processed this filing date
    filing_date_str = filing_date.strftime('%Y-%m-%d')

    processed_dates = []
    if spac.processed_redemption_dates:
        try:
            processed_dates = json.loads(spac.processed_redemption_dates)
        except:
            processed_dates = []

    if filing_date_str in processed_dates:
        print(f"   ⏭️  Skipping duplicate - already processed redemption from {filing_date}")
        return False

    # Get current values
    old_shares_redeemed = spac.shares_redeemed or 0
    old_redemption_amount = spac.redemption_amount or 0.0
    old_shares_outstanding = spac.shares_outstanding or 0.0
    old_trust_cash = spac.trust_cash or 0.0
    old_redemption_events = spac.redemption_events or 0

    # Calculate new values (INCREMENTAL - add to totals)
    new_shares_redeemed = old_shares_redeemed + shares_redeemed
    new_redemption_amount = old_redemption_amount + redemption_amount
    new_shares_outstanding = old_shares_outstanding - shares_redeemed
    new_trust_cash = old_trust_cash - redemption_amount
    new_redemption_events = old_redemption_events + 1

    # Calculate redemption percentage
    if spac.shares_outstanding:
        redemption_percentage = (new_shares_redeemed / (old_shares_outstanding + new_shares_redeemed)) * 100
    else:
        redemption_percentage = 0.0

    print(f"   ✓ Adding redemption event #{new_redemption_events}")
    print(f"     Shares redeemed: {shares_redeemed:,.0f} ({shares_redeemed/1_000_000:.2f}M)")
    print(f"     Amount redeemed: ${redemption_amount:,.0f}")
    print(f"     Filing date: {filing_date}")
    print(f"     Source: {source}")

    print(f"\n   📊 Cumulative Totals:")
    print(f"     Total shares redeemed: {old_shares_redeemed:,.0f} → {new_shares_redeemed:,.0f} ({new_shares_redeemed/1_000_000:.2f}M)")
    print(f"     Total amount redeemed: ${old_redemption_amount:,.0f} → ${new_redemption_amount:,.0f}")
    print(f"     Redemption percentage: {redemption_percentage:.1f}%")
    print(f"     Shares outstanding: {old_shares_outstanding:,.0f} → {new_shares_outstanding:,.0f} ({new_shares_outstanding/1_000_000:.2f}M)")
    print(f"     Trust cash: ${old_trust_cash:,.0f} → ${new_trust_cash:,.0f}")

    # Update SPAC record
    spac.shares_redeemed = new_shares_redeemed
    spac.redemption_amount = new_redemption_amount
    spac.redemption_percentage = redemption_percentage
    spac.last_redemption_date = filing_date
    spac.redemption_events = new_redemption_events
    spac.redemptions_occurred = True

    # Mark this filing date as processed
    processed_dates.append(filing_date_str)
    spac.processed_redemption_dates = json.dumps(processed_dates)

    db_session.commit()

    # Update shares_outstanding using tracker (for proper precedence)
    update_shares_outstanding(
        db_session=db_session,
        ticker=ticker,
        new_value=new_shares_outstanding,
        source=source,
        filing_date=filing_date,
        reason=f"After {shares_redeemed:,.0f} shares redeemed"
    )

    # Update trust_cash using tracker (for proper precedence)
    update_trust_cash(
        db_session=db_session,
        ticker=ticker,
        new_value=new_trust_cash,
        source=source,
        filing_date=filing_date,
        quarter=None
    )

    # Log to history table
    try:
        db_session.execute(text("""
            INSERT INTO redemption_history
            (ticker, shares_redeemed, redemption_amount, cumulative_shares, cumulative_amount,
             source, filing_date, changed_at, reason)
            VALUES (:ticker, :shares_redeemed, :redemption_amount, :cumulative_shares, :cumulative_amount,
                    :source, :filing_date, :changed_at, :reason)
        """), {
            'ticker': ticker,
            'shares_redeemed': shares_redeemed,
            'redemption_amount': redemption_amount,
            'cumulative_shares': new_shares_redeemed,
            'cumulative_amount': new_redemption_amount,
            'source': source,
            'filing_date': filing_date,
            'changed_at': datetime.now(),
            'reason': reason or f"Redemption event from {source} filing"
        })
        db_session.commit()
        print(f"   ✓ Logged to redemption history")
    except Exception as e:
        print(f"   ⚠️  History logging failed: {e}")
        # Don't fail the whole update if history logging fails
        db_session.rollback()
        db_session.commit()

    return True


def mark_no_redemptions_found(
    db_session: Session,
    ticker: str,
    source: str,
    filing_date: Optional[date] = None,
    reason: str = None
) -> bool:
    """
    Mark that a SPAC has been checked for redemptions and NONE were found

    This distinguishes between:
    - Not yet checked (redemptions_occurred = NULL)
    - Checked and confirmed zero (redemptions_occurred = FALSE, shares_redeemed = 0)
    - Has redemptions (redemptions_occurred = TRUE, shares_redeemed > 0)

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker
        source: Filing type checked (8-K, DEFM14A, etc.)
        filing_date: Date of filing checked
        reason: Human-readable reason

    Returns:
        True if marked successfully
    """
    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"❌ SPAC {ticker} not found")
        return False

    # Only mark if not already marked
    if spac.redemptions_occurred is True:
        print(f"ℹ️  {ticker}: Already has redemptions recorded")
        return False

    if spac.redemptions_occurred is False and spac.shares_redeemed == 0:
        print(f"ℹ️  {ticker}: Already marked as no redemptions")
        return False

    print(f"✓ Marking {ticker}: No redemptions found")
    print(f"  Source: {source}")
    if filing_date:
        print(f"  Filing checked: {filing_date}")
    if reason:
        print(f"  Reason: {reason}")

    # Mark as checked with zero redemptions
    spac.redemptions_occurred = False
    spac.shares_redeemed = 0
    spac.redemption_amount = 0.0
    spac.redemption_percentage = 0.0
    spac.redemption_events = 0

    # Log to history for audit trail
    try:
        db_session.execute(text("""
            INSERT INTO redemption_history
            (ticker, shares_redeemed, redemption_amount, cumulative_shares, cumulative_amount,
             source, filing_date, changed_at, reason)
            VALUES (:ticker, 0, 0.0, 0, 0.0, :source, :filing_date, :changed_at, :reason)
        """), {
            'ticker': ticker,
            'source': source,
            'filing_date': filing_date,
            'changed_at': datetime.now(),
            'reason': reason or f'Checked {source}, no redemptions found'
        })
        print(f"   ✓ Logged to history")
    except Exception as e:
        print(f"   ⚠️  History logging failed: {e}")

    db_session.commit()
    return True


def get_redemption_history(db_session: Session, ticker: str) -> list:
    """
    Get redemption event history for a SPAC

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker

    Returns:
        List of redemption events (newest first)
    """

    result = db_session.execute(text("""
        SELECT shares_redeemed, redemption_amount, cumulative_shares, cumulative_amount,
               source, filing_date, changed_at, reason
        FROM redemption_history
        WHERE ticker = :ticker
        ORDER BY changed_at DESC
    """), {'ticker': ticker})

    history = []
    for row in result:
        history.append({
            'shares_redeemed': row[0],
            'redemption_amount': row[1],
            'cumulative_shares': row[2],
            'cumulative_amount': row[3],
            'source': row[4],
            'filing_date': row[5],
            'changed_at': row[6],
            'reason': row[7]
        })

    return history


def get_spacs_with_redemptions(db_session: Session, min_percentage: float = 0.0) -> list:
    """
    Find SPACs with redemptions above a certain percentage

    Args:
        db_session: SQLAlchemy session
        min_percentage: Minimum redemption percentage (0-100)

    Returns:
        List of SPACs with redemption data
    """

    result = db_session.execute(text("""
        SELECT ticker, company, shares_redeemed, redemption_amount, redemption_percentage,
               redemption_events, last_redemption_date
        FROM spacs
        WHERE redemptions_occurred = true
          AND redemption_percentage >= :min_percentage
        ORDER BY redemption_percentage DESC
    """), {'min_percentage': min_percentage})

    spacs = []
    for row in result:
        spacs.append({
            'ticker': row[0],
            'company': row[1],
            'shares_redeemed': row[2],
            'redemption_amount': row[3],
            'redemption_percentage': row[4],
            'redemption_events': row[5],
            'last_redemption_date': row[6]
        })

    return spacs


def reset_redemption_tracking(db_session: Session, ticker: str) -> bool:
    """
    Reset redemption tracking for a SPAC (USE WITH CAUTION!)

    This is only needed if redemptions were counted incorrectly and need to be reprocessed.

    Args:
        db_session: SQLAlchemy session
        ticker: SPAC ticker

    Returns:
        True if reset, False if SPAC not found
    """

    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        print(f"   ⚠️  SPAC {ticker} not found")
        return False

    print(f"   ⚠️  Resetting redemption tracking for {ticker}")
    print(f"     Current: {spac.shares_redeemed or 0:,.0f} shares, ${spac.redemption_amount or 0:,.0f}")

    spac.redemptions_occurred = False
    spac.shares_redeemed = 0
    spac.redemption_amount = 0.0
    spac.redemption_percentage = 0.0
    spac.last_redemption_date = None
    spac.redemption_events = 0
    spac.processed_redemption_dates = None

    db_session.commit()
    print(f"   ✓ Reset complete")

    return True


if __name__ == "__main__":
    """Test the redemption tracker"""

    from database import SessionLocal
    from datetime import datetime, date

    db = SessionLocal()

    print("="*70)
    print("TESTING REDEMPTION TRACKER")
    print("="*70)

    # Reset first (for testing)
    print("\nResetting CEP redemption tracking (for testing)...")
    reset_redemption_tracking(db, 'CEP')

    # Test 1: First redemption event
    print("\nTest 1: First redemption event (Nov 1)")
    add_redemption_event(
        db_session=db,
        ticker='CEP',
        shares_redeemed=5000000,  # 5M shares
        redemption_amount=50500000.0,  # $50.5M ($10.10 per share)
        filing_date=date(2025, 11, 1),
        source='8-K',
        reason='Initial redemptions before merger vote'
    )

    # Test 2: Second redemption event
    print("\nTest 2: Second redemption event (Nov 15)")
    add_redemption_event(
        db_session=db,
        ticker='CEP',
        shares_redeemed=3000000,  # 3M shares
        redemption_amount=30300000.0,  # $30.3M ($10.10 per share)
        filing_date=date(2025, 11, 15),
        source='8-K',
        reason='Additional redemptions'
    )

    # Test 3: Try to process same date again (should skip)
    print("\nTest 3: Try to process Nov 1 again (should skip - duplicate)")
    add_redemption_event(
        db_session=db,
        ticker='CEP',
        shares_redeemed=5000000,
        redemption_amount=50500000.0,
        filing_date=date(2025, 11, 1),  # Same date as Test 1
        source='8-K',
        reason='Duplicate - should be skipped'
    )

    # Test 4: Third redemption event
    print("\nTest 4: Third redemption event (Nov 30)")
    add_redemption_event(
        db_session=db,
        ticker='CEP',
        shares_redeemed=2000000,  # 2M shares
        redemption_amount=20200000.0,  # $20.2M
        filing_date=date(2025, 11, 30),
        source='DEFM14A',
        reason='Final redemptions at merger close'
    )

    # Show history
    print("\n" + "="*70)
    print("REDEMPTION HISTORY FOR CEP")
    print("="*70)

    history = get_redemption_history(db, 'CEP')
    for i, entry in enumerate(history):
        print(f"\nEvent #{len(history) - i} - {entry['changed_at'].date()}")
        print(f"  Shares: {entry['shares_redeemed']:,.0f} ({entry['shares_redeemed']/1_000_000:.2f}M)")
        print(f"  Amount: ${entry['redemption_amount']:,.0f}")
        print(f"  Cumulative: {entry['cumulative_shares']:,.0f} shares / ${entry['cumulative_amount']:,.0f}")
        print(f"  Source: {entry['source']} (filed: {entry['filing_date']})")
        print(f"  Reason: {entry['reason']}")

    # Show final state
    print("\n" + "="*70)
    print("FINAL STATE")
    print("="*70)

    spac = db.query(SPAC).filter(SPAC.ticker == 'CEP').first()
    print(f"\nCEP - {spac.company}")
    print(f"  Total shares redeemed: {spac.shares_redeemed:,.0f} ({spac.shares_redeemed/1_000_000:.2f}M)")
    print(f"  Total amount redeemed: ${spac.redemption_amount:,.0f}")
    print(f"  Redemption percentage: {spac.redemption_percentage:.1f}%")
    print(f"  Redemption events: {spac.redemption_events}")
    print(f"  Shares outstanding: {spac.shares_outstanding:,.0f} ({spac.shares_outstanding/1_000_000:.2f}M)")
    print(f"  Trust cash: ${spac.trust_cash:,.0f}")
    print(f"  Trust value (NAV): ${spac.trust_value:.2f} per share")

    db.close()

    print("\n✅ Tests complete!")
