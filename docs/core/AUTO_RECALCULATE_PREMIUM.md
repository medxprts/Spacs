# Auto-Recalculate Premium When Trust Value Changes

**Date:** October 9, 2025
**Fix:** Ensure premium automatically updates when trust_value changes

---

## The Problem

**Discovered:** AEXA premium was incorrect after trust_value changed

```
AEXA Data:
- Price: $11.59
- Trust Value: $9.80 (recently updated from $11.04)
- Premium (stored): 4.98% ❌ WRONG
- Premium (calculated): 18.27% ✅ CORRECT
```

**Root Cause:**
- `trust_value` was updated by tracker
- `premium` was NOT recalculated
- Premium became stale/incorrect

---

## The Solution

### Added: `recalculate_premium()` Function

**Location:** `/home/ubuntu/spac-research/utils/trust_account_tracker.py`

```python
def recalculate_premium(db_session: Session, ticker: str) -> bool:
    """
    Recalculate premium based on current price and trust_value

    Premium = ((price - trust_value) / trust_value) * 100

    This should be called whenever:
    - trust_value changes
    - price changes
    """

    spac = db_session.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        return False

    # Need both price and trust_value to calculate premium
    if not spac.price or not spac.trust_value:
        return False

    # Convert to float for calculation (handle Decimal types)
    price = float(spac.price)
    trust_value = float(spac.trust_value)

    old_premium = spac.premium
    new_premium = round(((price - trust_value) / trust_value) * 100, 2)

    # Only update if changed
    if old_premium != new_premium:
        spac.premium = new_premium
        db_session.commit()
        print(f"   ✓ Recalculated premium: {old_premium:.2f}% → {new_premium:.2f}%")
        return True

    return False
```

---

## Integration Points

### 1. After `update_trust_value()` Changes

```python
def update_trust_value(...):
    # ... update trust_value ...

    db_session.commit()
    print(f"   ✓ Logged to history")

    # Recalculate premium (trust_value changed)
    recalculate_premium(db_session, ticker)  # ← ADDED

    return True
```

### 2. After `update_shares_outstanding()` Recalculates Trust Value

```python
def update_shares_outstanding(...):
    # ... update shares ...

    # Recalculate trust_value if we have trust_cash
    if spac.trust_cash and spac.trust_cash > 0 and new_value > 0:
        old_nav = spac.trust_value
        new_nav = round(spac.trust_cash / new_value, 2)
        spac.trust_value = new_nav
        print(f"   ✓ Recalculated trust_value: ${old_nav:.2f} → ${new_nav:.2f} per share")
        db_session.commit()

        # Recalculate premium (trust_value changed)
        recalculate_premium(db_session, ticker)  # ← ADDED

    return True
```

### 3. Future: After Price Updates

**TODO:** Add to `price_updater.py` when price changes:

```python
def update_price(ticker, new_price):
    spac.price = new_price
    db.commit()

    # Recalculate premium (price changed)
    from utils.trust_account_tracker import recalculate_premium
    recalculate_premium(db, ticker)
```

---

## Dependent Data Relationships

### Trust Value Changes Affect:

```
trust_value changes
    ↓
premium must recalculate ✅ NOW AUTOMATIC
```

### Shares Outstanding Changes Affect:

```
shares_outstanding changes
    ↓
trust_value recalculates (trust_cash / shares)
    ↓
premium recalculates ✅ NOW AUTOMATIC
```

### Trust Cash Changes Affect:

```
trust_cash changes
    ↓
(no automatic recalc - waits for shares_outstanding update)
    ↓
when shares updates → trust_value recalculates
    ↓
premium recalculates ✅ NOW AUTOMATIC
```

### Price Changes Affect:

```
price changes
    ↓
premium must recalculate ⚠️ TODO: Add to price_updater.py
```

---

## Testing

### Test 1: Fix AEXA (Manual)

**Before:**
```
Price: $11.59
Trust Value: $9.80
Premium: 4.98% ❌ WRONG
```

**After:**
```python
from utils.trust_account_tracker import recalculate_premium
recalculate_premium(db, 'AEXA')
```

**Result:**
```
✓ Recalculated premium: 4.98% → 18.27%

Price: $11.59
Trust Value: $9.80
Premium: 18.27% ✅ CORRECT
```

### Test 2: Automatic Recalculation

**Scenario:** Update trust_value for a SPAC

```python
from utils.trust_account_tracker import update_trust_value

update_trust_value(
    db_session=db,
    ticker='TEST',
    new_value=9.50,
    source='10-Q',
    filing_date=date(2025, 10, 1)
)
```

**Expected Output:**
```
✓ Updating trust_value: $10.00 → $9.50
    Source: S-1 → 10-Q
    Filing date: 2025-09-01 → 2025-10-01
✓ Logged to history
✓ Recalculated premium: 10.00% → 15.79%  ← AUTOMATIC!
```

---

## Query to Find Incorrect Premiums

```sql
-- Find SPACs where stored premium doesn't match calculated premium
SELECT
    ticker,
    price,
    trust_value,
    premium as stored_premium,
    ROUND(((price - trust_value) / trust_value * 100)::numeric, 2) as calculated_premium,
    ABS(premium - ((price - trust_value) / trust_value * 100)) as difference,
    CASE
        WHEN ABS(premium - ((price - trust_value) / trust_value * 100)) < 0.01 THEN '✅ Match'
        WHEN ABS(premium - ((price - trust_value) / trust_value * 100)) < 1.0 THEN '⚠️ Minor'
        ELSE '❌ Major Mismatch'
    END as status
FROM spacs
WHERE price IS NOT NULL
AND trust_value IS NOT NULL
AND ABS(premium - ((price - trust_value) / trust_value * 100)) > 0.01
ORDER BY difference DESC;
```

---

## Fix All Incorrect Premiums

```python
#!/usr/bin/env python3
"""
Recalculate premiums for all SPACs
"""

from database import SessionLocal, SPAC
from utils.trust_account_tracker import recalculate_premium

db = SessionLocal()

try:
    spacs = db.query(SPAC).filter(
        SPAC.price.isnot(None),
        SPAC.trust_value.isnot(None)
    ).all()

    print(f"Checking {len(spacs)} SPACs with price and trust_value...")

    fixed = 0
    for spac in spacs:
        result = recalculate_premium(db, spac.ticker)
        if result:
            fixed += 1

    print(f"\n✅ Recalculated premiums for {fixed} SPACs")

finally:
    db.close()
```

---

## Summary

### What Changed:
1. ✅ Added `recalculate_premium()` function
2. ✅ Integrated into `update_trust_value()`
3. ✅ Integrated into `update_shares_outstanding()` (when trust_value recalculates)
4. ✅ Handles Decimal/float type conversion

### When Premium Recalculates:
- ✅ When trust_value is updated directly
- ✅ When shares_outstanding changes (triggers trust_value recalc)
- ⚠️ TODO: When price is updated

### AEXA Result:
- Premium fixed: 4.98% → 18.27%
- Now correctly reflects $11.59 price vs $9.80 trust value

---

**Key Principle:** Dependent data must update automatically when source data changes.

Formula: `premium = ((price - trust_value) / trust_value) × 100`

Dependencies:
- `premium` depends on `price` and `trust_value`
- `trust_value` depends on `trust_cash` and `shares_outstanding`
- All trackers must trigger downstream recalculations
