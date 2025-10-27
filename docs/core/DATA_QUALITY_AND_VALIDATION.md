# Data Quality Issues & Lessons Learned

**Date:** October 9, 2025

---

## Issue #1: AEXA Trust Value Calculation Error

**Date Discovered:** October 9, 2025

### The Problem

AEXA showing **$11.04 trust value per share** when it should be ~$7-10 based on $300M IPO.

```
Current Data:
- trust_cash: $456,730,000
- shares_outstanding: 41,371,478
- trust_value: $11.04
- ipo_proceeds: $300,000,000

Problem: Trust cash ($456.7M) is $156M HIGHER than IPO proceeds ($300M)!
```

### Root Cause

**Circular calculation error** from using incorrect initial data:

1. **Initial bad data** (unknown source):
   - `trust_value` = $11.04 ← WRONG (should be ~$10.00 for new IPO)
   - `shares_outstanding` = 41,371,478

2. **Calculation script amplified error**:
   ```python
   # calculate_missing_trust_cash.py ran:
   trust_cash = shares_outstanding × trust_value
   trust_cash = 41.37M × $11.04 = $456.73M ← INCORRECT!
   ```

3. **Result**: Trust cash now shows $456.7M instead of expected ~$294M

### Why This Happened

**Violated cardinal rule: "Always default to filings data"**

- Calculation scripts should ONLY run when filing data is unavailable
- Initial data may have been from unreliable source (manual entry, API, etc.)
- Never trust calculated values over SEC filing data

### The Correct Process

```
Priority Hierarchy (ALWAYS follow this order):

1. SEC Filings (424B4, S-1, 10-Q) ← HIGHEST PRIORITY
   ↓ (only if unavailable)
2. Calculated from filing-sourced components
   ↓ (only if unavailable)
3. Third-party APIs (if verified)
   ↓ (last resort)
4. Manual estimates (mark clearly as "estimated")
```

### What Should Have Happened

**Step 1: Check SEC filings FIRST**
```bash
# Fetch AEXA 424B4 filing
curl "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0002079173&type=424B4" \
  -H "User-Agent: LEVP SPAC Platform fenil@legacyevp.com"
```

**Step 2: Extract trust account data from prospectus**
```
Look for:
- "gross proceeds of $XXX million"
- "deposited into trust account"
- "shares of Class A common stock"
- "$X.XX per share in trust"
```

**Step 3: Validate against IPO proceeds**
```python
# Sanity check
if trust_cash > ipo_proceeds:
    raise ValueError(f"Trust cash ({trust_cash}) cannot exceed IPO proceeds ({ipo_proceeds})")

# Typical ranges
expected_trust_cash = ipo_proceeds * 0.95  # After ~5% fees
if abs(trust_cash - expected_trust_cash) / expected_trust_cash > 0.10:
    print(f"⚠️ Warning: Trust cash differs by >10% from expected")
```

**Step 4: Mark data source**
```python
spac.trust_cash = 294000000
spac.trust_cash_source = "424B4"  # ← CRITICAL: Track source
spac.trust_cash_filing_date = filing_date
```

### Expected Values for AEXA

Based on $300M IPO (September 2025):

```
IPO proceeds:        $300,000,000
Underwriting fees:    ~$6,000,000 (2%)
Trust account:       ~$294,000,000 (98%)
Shares outstanding:   41,371,478
Trust value/share:    $7.11 ($294M ÷ 41.37M)

OR (if $10/share target):
Trust account:       $413,710,000
Expected shares:      41,371,000
Trust value/share:    $10.00
```

**Conclusion**: Need to check AEXA's 424B4 to determine actual trust structure.

---

## Lesson Learned: The Golden Rule

### ⚠️ ALWAYS DEFAULT TO FILINGS DATA ⚠️

**Never run calculation scripts that overwrite filing-sourced data.**

### Implementation Changes Required

#### 1. Add Data Source Validation

**Before any calculation:**
```python
def should_calculate_trust_cash(spac):
    """Only calculate if we don't have filing data"""

    # NEVER overwrite filing-sourced data
    if spac.trust_cash_source in ['424B4', 'S-1', '10-Q', 'S-4', 'DEFM14A']:
        print(f"⚠️ {spac.ticker}: Has filing data ({spac.trust_cash_source}), skipping calculation")
        return False

    # Only calculate if truly missing
    if not spac.trust_cash:
        return True

    # If source is 'calculated' or 'estimated', filing data can override
    if spac.trust_cash_source in ['calculated', 'estimated', None]:
        return True

    return False
```

#### 2. Update All Calculation Scripts

**Pattern to follow:**
```python
# ❌ WRONG - Old approach
for spac in spacs_missing_trust_cash:
    spac.trust_cash = spac.shares_outstanding * spac.trust_value
    spac.data_source = 'calculated'

# ✅ CORRECT - New approach
for spac in spacs_missing_trust_cash:
    if should_calculate_trust_cash(spac):
        spac.trust_cash = spac.shares_outstanding * spac.trust_value
        spac.trust_cash_source = 'calculated'
        print(f"✓ {spac.ticker}: Calculated trust_cash (no filing data available)")
    else:
        print(f"⏭️ {spac.ticker}: Skipping (has {spac.trust_cash_source} data)")
```

#### 3. Add Sanity Checks to Scrapers

**In sec_data_scraper.py:**
```python
def validate_trust_account_data(spac, trust_cash, source):
    """Validate trust account data before saving"""

    # Check 1: Trust cash shouldn't exceed IPO proceeds
    if spac.ipo_proceeds:
        ipo_proceeds_value = parse_money(spac.ipo_proceeds)
        if trust_cash > ipo_proceeds_value:
            print(f"⚠️ WARNING: {spac.ticker} trust_cash (${trust_cash/1e6:.1f}M) > IPO proceeds (${ipo_proceeds_value/1e6:.1f}M)")
            print(f"   Source: {source}")
            print(f"   This may indicate data error - review manually")
            return False

    # Check 2: Trust value per share should be $7-12 for most SPACs
    if spac.shares_outstanding and spac.shares_outstanding > 0:
        trust_per_share = trust_cash / spac.shares_outstanding
        if trust_per_share < 7 or trust_per_share > 12:
            print(f"⚠️ WARNING: {spac.ticker} trust value per share (${trust_per_share:.2f}) outside normal range ($7-$12)")
            print(f"   Trust: ${trust_cash/1e6:.1f}M, Shares: {spac.shares_outstanding/1e6:.1f}M")
            return False

    return True
```

#### 4. Prioritize Filing Sources in Trackers

**Already implemented in trust_account_tracker.py:**
```python
SOURCE_PRIORITY = {
    '10-Q': 1,      # Quarterly report (most recent)
    'S-4': 2,       # Merger filing
    'DEFM14A': 3,   # Proxy statement
    '424B4': 4,     # Final prospectus
    'S-1': 5,       # Registration
    '8-K': 6,       # Current report
    'calculated': 99,  # ← Lowest priority
    'estimated': 100   # ← Never overwrite
}
```

**This ensures filing data always wins over calculations.**

---

## Files to Update

### 1. **calculate_missing_trust_cash.py**
- ✅ Add source checking before calculation
- ✅ Only calculate if `trust_cash_source` is NULL or 'calculated'

### 2. **smart_trust_cash_sourcing.py**
- ✅ Add validation checks before storing data
- ✅ Compare against IPO proceeds

### 3. **sec_data_scraper.py**
- ✅ Add sanity checks when extracting trust data
- ✅ Flag values that seem incorrect
- ✅ Always set `trust_cash_source` field

### 4. **fix_new_ipo_trust_data.py**
- ✅ Check data source before "fixing"
- ✅ Only fix calculated values, not filing-sourced

---

## Immediate Action Items

### For AEXA:
1. ✅ Scrape 424B4 filing to get actual trust account value
2. ✅ Verify shares outstanding (41.37M seems high)
3. ✅ Update database with correct filing-sourced data
4. ✅ Mark source as "424B4" with filing date

### For All SPACs:
1. ✅ Audit trust_cash values where `trust_cash > ipo_proceeds`
2. ✅ Check if any have `trust_cash_source = 'calculated'` but shouldn't
3. ✅ Re-scrape filings for SPACs with suspicious values
4. ✅ Update calculation scripts to check source before overwriting

---

## Prevention Checklist

Before running ANY data update script:

- [ ] Check if existing data is from SEC filings
- [ ] Validate new data against known constraints
- [ ] Compare to IPO proceeds / other reliable benchmarks
- [ ] Mark data source clearly
- [ ] Test on 1-2 SPACs before bulk update
- [ ] Create backup before making changes

**Remember: Filing data is ALWAYS more reliable than calculated data.**

---

## Query to Find Similar Issues

```sql
-- Find SPACs where trust_cash exceeds IPO proceeds
SELECT
    ticker,
    ipo_proceeds,
    trust_cash,
    (trust_cash - CAST(REPLACE(REPLACE(ipo_proceeds, '$', ''), ',', '') AS FLOAT)) AS excess,
    trust_cash_source,
    ipo_date
FROM spacs
WHERE ipo_proceeds IS NOT NULL
AND trust_cash IS NOT NULL
AND trust_cash > CAST(REPLACE(REPLACE(ipo_proceeds, '$', ''), ',', '') AS FLOAT)
ORDER BY excess DESC;
```

```sql
-- Find SPACs with unusual trust values per share
SELECT
    ticker,
    trust_cash,
    shares_outstanding,
    trust_value,
    (trust_cash / shares_outstanding) AS calculated_nav,
    trust_cash_source,
    CASE
        WHEN (trust_cash / shares_outstanding) < 7 THEN 'Too Low'
        WHEN (trust_cash / shares_outstanding) > 12 THEN 'Too High'
        ELSE 'Normal'
    END AS flag
FROM spacs
WHERE trust_cash IS NOT NULL
AND shares_outstanding IS NOT NULL
AND shares_outstanding > 0
AND ((trust_cash / shares_outstanding) < 7 OR (trust_cash / shares_outstanding) > 12)
ORDER BY (trust_cash / shares_outstanding) DESC;
```

---

**The Golden Rule: When in doubt, go back to the SEC filing. Always.**
