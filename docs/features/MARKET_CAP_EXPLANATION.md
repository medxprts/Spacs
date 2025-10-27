# Market Cap Data Source & Auto-Fix Explanation

## Where Market Cap Comes From

### Two Different Calculations:

**1. price_updater.py (Yahoo Finance source)**
```python
# Line 229 in price_updater.py
if spac.shares_outstanding:
    if spac.founder_shares:
        total_shares = spac.shares_outstanding + spac.founder_shares
    else:
        # Fallback: assume 25% founder shares (typical SPAC structure)
        total_shares = spac.shares_outstanding * 1.25
    market_cap = (price * total_shares) / 1_000_000
```

**Formula**: `market_cap = price × (shares_outstanding + founder_shares) / 1M`

**Includes**: Public shares **+ founder shares** (typically 20-25% more)

---

**2. data_validator.py (Auto-fix calculation)**
```python
# Line 1086 in data_validator.py
spac.market_cap = (float(spac.price) * float(spac.shares_outstanding)) / 1_000_000
```

**Formula**: `market_cap = price × shares_outstanding / 1M`

**Includes**: **Public shares only** (no founder shares)

---

## The Discrepancy

### Example: MLAC

```sql
ticker: MLAC
price: $11.07
shares_outstanding: 23,000,000 (public shares)
founder_shares: NULL (not in database)
```

**price_updater.py calculation** (what was stored):
```
market_cap = $11.07 × 23,000,000 × 1.25 / 1M
           = $11.07 × 28,750,000 / 1M
           = $318.26M
```
(Assumes 25% founder shares: 23M × 1.25 = 28.75M total)

**data_validator.py calculation** (what auto-fix did):
```
market_cap = $11.07 × 23,000,000 / 1M
           = $254.61M
```
(Public shares only)

**Difference**: $318.26M - $254.61M = **$63.65M** (20% difference)

This 20% gap represents the assumed founder shares!

---

## What the Auto-Fix Actually Did

### Before Auto-Fix:
```sql
MLAC: market_cap = 318.26  -- Includes estimated 25% founder shares
HCMA: market_cap = 328.27  -- Includes estimated 25% founder shares
BCAR: market_cap = 314.38  -- Includes estimated 25% founder shares
```

### After Auto-Fix:
```sql
MLAC: market_cap = 254.61  -- Public shares only
HCMA: market_cap = 262.61  -- Public shares only
BCAR: market_cap = 251.50  -- Public shares only
```

### What Changed:
The auto-fix **removed the 25% founder share assumption** and recalculated using public shares only.

---

## Which Calculation is Correct?

### It depends on what you want to measure:

**Public shares only (validator's method)**:
- ✅ More conservative
- ✅ Reflects actual tradable/redeemable shares
- ✅ Used for redemption scenarios
- ❌ Understates total equity value

**Public + Founder shares (price_updater's method)**:
- ✅ Reflects true total market cap
- ✅ Standard financial reporting
- ✅ What investors typically see
- ❌ Requires accurate founder share data (which we often don't have)

### Industry Standard:
**Include founder shares** in market cap calculation. This is what Yahoo Finance, Bloomberg, and other financial sites show.

---

## The Problem

### Missing Founder Share Data:
```sql
SELECT COUNT(*) FROM spacs WHERE founder_shares IS NULL;
-- Result: 180 out of 186 SPACs (97%)
```

We don't have founder share data for most SPACs, so:
- **price_updater.py** assumes 25% (reasonable industry average)
- **data_validator.py** ignores founder shares entirely (uses 0%)

### Result:
The auto-fix **made our market_cap values LESS accurate** by removing the founder share estimate.

---

## What Should We Do?

### Option 1: Revert Auto-Fix for market_cap ✅ RECOMMENDED
```bash
# Rollback to include founder shares
psql spac_db < logs/rollback_20251008_132018.sql
```

**Reasoning**:
- Market cap **should** include founder shares (industry standard)
- 25% assumption is better than 0% assumption
- Our current values (254.61M) understate by ~20%

### Option 2: Fix the Validator Logic
Change line 1086 in data_validator.py:
```python
# OLD (public shares only):
spac.market_cap = (float(spac.price) * float(spac.shares_outstanding)) / 1_000_000

# NEW (include founder shares):
if spac.founder_shares:
    total_shares = float(spac.shares_outstanding) + float(spac.founder_shares)
else:
    total_shares = float(spac.shares_outstanding) * 1.25  # Assume 25%

spac.market_cap = (float(spac.price) * total_shares) / 1_000_000
```

This makes the validator match the price_updater logic.

### Option 3: Get Actual Founder Share Data
Scrape from SEC S-1 filings:
- Section: "Capitalization Table" or "Founder Shares"
- Typical disclosure: "The Sponsor purchased 5,750,000 founder shares..."

Then the calculation will be accurate without assumptions.

---

## Current Data Quality Issue

### After the auto-fix, we have:
- **142 SPACs** with market_cap calculated as: `price × shares_outstanding` (public only)
- **44 SPACs** with market_cap still calculated as: `price × shares_outstanding × 1.25` (public + estimated founder)

### This creates inconsistency:
- Some SPACs: market_cap includes founder shares
- Other SPACs: market_cap excludes founder shares
- **Cannot compare market caps across SPACs** reliably

---

## Examples with Actual Database Values

```sql
SELECT
    ticker,
    price,
    shares_outstanding,
    founder_shares,
    market_cap as current_mcap,
    ROUND(price * shares_outstanding / 1000000.0, 2) as public_only_mcap,
    ROUND(price * shares_outstanding * 1.25 / 1000000.0, 2) as with_founder_estimate
FROM spacs
WHERE ticker IN ('MLAC', 'HCMA', 'BCAR');
```

| ticker | price | shares_out | founder_shares | current_mcap | public_only | with_founder |
|--------|-------|------------|----------------|--------------|-------------|--------------|
| MLAC   | 11.07 | 23,000,000 | NULL           | **254.61**   | 254.61      | 318.26       |
| HCMA   | 10.38 | 25,300,000 | NULL           | **262.61**   | 262.61      | 328.27       |
| BCAR   | 10.06 | 25,000,000 | NULL           | **251.50**   | 251.50      | 314.38       |

**Current (after auto-fix)**: 254.61M (public only)
**Should be**: 318.26M (public + 25% founder estimate)
**Would be ideal**: `price × (23M + actual_founder_shares)` if we had the data

---

## Recommendation

### Immediate Action:
1. **Disable market_cap auto-fix** in data_validator.py
2. **Do NOT run Tier 1 fixes** until this is resolved
3. **Decide**: Should we use public-only or public+founder calculation?

### Long-term Solution:
1. Scrape founder share data from SEC S-1 filings
2. Store in `founder_shares` column
3. Use actual data instead of 25% assumption
4. Update both price_updater.py and data_validator.py to use same logic

### For now:
**Disable the market_cap_calculation rule** from auto-fix tier 1:
```python
# Line 898 in data_validator.py
tier_1_rules = [
    'premium_calculation',
    'days_to_deadline_calculation',
    # 'market_cap_calculation',  # DISABLED - needs founder share data
    'return_since_announcement_calculation'
]
```

---

## Summary

**Where market_cap comes from**:
- Initially populated by `price_updater.py` from Yahoo Finance prices
- Calculated as: `price × shares_outstanding × 1.25` (assumes 25% founder shares)

**What the auto-fix did**:
- Recalculated 142 SPACs using: `price × shares_outstanding` (no founder shares)
- Reduced market_cap values by ~20% on average
- Made data **less accurate** and **inconsistent** across SPACs

**Why this happened**:
- Two different calculation methods in codebase
- Missing founder share data (180/186 SPACs)
- Validator assumed 0% founder shares instead of 25%

**What we should do**:
- **Disable market_cap auto-fix** until we have founder share data
- **Keep existing market_cap values** from price_updater (with 25% assumption)
- OR: Rollback the 142 market_cap fixes from the auto-fix run
