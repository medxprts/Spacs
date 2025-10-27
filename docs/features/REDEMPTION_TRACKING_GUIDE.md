# Redemption Tracking Guide

**IMPORTANT**: Not every SPAC has redemptions. We must distinguish between:

1. **Not yet checked** → `redemptions_occurred = NULL`
2. **Checked, no redemptions** → `redemptions_occurred = FALSE, shares_redeemed = 0`
3. **Has redemptions** → `redemptions_occurred = TRUE, shares_redeemed > 0`

---

## When to Use Each Function

### Use `add_redemption_event()` - When redemptions ARE found

```python
from utils.redemption_tracker import add_redemption_event

# Found redemptions in filing
if redemption_data and redemption_data.get('shares_redeemed'):
    add_redemption_event(
        db_session=db,
        ticker='CEP',
        shares_redeemed=5000000,
        redemption_amount=50500000.0,
        filing_date=filing_date,
        source='8-K',
        reason='Shareholder redemptions before merger vote'
    )
```

### Use `mark_no_redemptions_found()` - When NO redemptions found

```python
from utils.redemption_tracker import mark_no_redemptions_found

# Checked filing, no redemptions mentioned
if filing_was_checked and not redemption_data:
    mark_no_redemptions_found(
        db_session=db,
        ticker='CEP',
        source='DEFM14A',
        filing_date=filing_date,
        reason='Checked DEFM14A proxy, no redemptions reported'
    )
```

---

## Integration Examples

### Example 1: Extension 8-K Processing

```python
# In sec_data_scraper.py around line 3615

if latest_ext and 'shares_redeemed' in latest_ext:
    # Extension filing found

    if latest_ext['shares_redeemed'] and latest_ext['shares_redeemed'] > 0:
        # Redemptions occurred
        add_redemption_event(
            db_session=self.db,
            ticker=ticker,
            shares_redeemed=latest_ext['shares_redeemed'],
            redemption_amount=0.0,  # Usually not reported in extension filings
            filing_date=latest_ext['date'],
            source='8-K',
            reason='Redemptions related to deadline extension'
        )
    else:
        # Extension filing found but no redemptions
        mark_no_redemptions_found(
            db_session=self.db,
            ticker=ticker,
            source='8-K',
            filing_date=latest_ext['date'],
            reason='Extension 8-K checked, no redemptions mentioned'
        )
```

### Example 2: DEFM14A Processing

```python
# In filing_processor.py when processing DEFM14A

def _process_merger_proxy(self, filing):
    # ... extract deal terms ...

    # Check for redemptions in proxy
    redemption_data = self._extract_redemptions(filing_text)

    if redemption_data and redemption_data.get('shares_redeemed'):
        # Found redemptions
        add_redemption_event(
            db_session=db,
            ticker=ticker,
            shares_redeemed=redemption_data['shares_redeemed'],
            redemption_amount=redemption_data.get('redemption_amount', 0.0),
            filing_date=filing_date,
            source='DEFM14A',
            reason='Shareholder redemptions from merger proxy'
        )
    else:
        # DEFM14A checked but no redemptions mentioned
        # This is common for deals with no/low redemptions
        mark_no_redemptions_found(
            db_session=db,
            ticker=ticker,
            source='DEFM14A',
            filing_date=filing_date,
            reason='DEFM14A checked, no redemptions disclosed'
        )
```

### Example 3: Post-Merger 8-K (Final Redemptions)

```python
# When processing post-merger 8-K

if deal_completed and redemption_data:
    if redemption_data.get('shares_redeemed'):
        add_redemption_event(
            db_session=db,
            ticker=ticker,
            shares_redeemed=redemption_data['shares_redeemed'],
            redemption_amount=redemption_data['redemption_amount'],
            filing_date=filing_date,
            source='8-K',
            reason='Final redemption count from merger completion 8-K'
        )
    else:
        # Merger completed with zero redemptions
        mark_no_redemptions_found(
            db_session=db,
            ticker=ticker,
            source='8-K',
            filing_date=filing_date,
            reason='Merger completed with zero redemptions'
        )
```

---

## Data Quality Checks

### Check Coverage Status

```sql
-- Three states of redemption data:

-- 1. Not yet checked (NULL)
SELECT COUNT(*) as not_checked
FROM spacs
WHERE redemptions_occurred IS NULL;

-- 2. Checked and confirmed zero (FALSE with 0 shares)
SELECT COUNT(*) as confirmed_zero
FROM spacs
WHERE redemptions_occurred = FALSE
AND shares_redeemed = 0;

-- 3. Has redemptions (TRUE with shares > 0)
SELECT COUNT(*) as has_redemptions
FROM spacs
WHERE redemptions_occurred = TRUE
AND shares_redeemed > 0;
```

### Find SPACs That Need Checking

```sql
-- SPACs that should be checked for redemptions
SELECT ticker, deal_status, announced_date
FROM spacs
WHERE deal_status IN ('ANNOUNCED', 'COMPLETED')
AND redemptions_occurred IS NULL
ORDER BY announced_date DESC;
```

---

## Coverage Reporting

**Before distinguishing zero vs unchecked:**
```
Redemption Coverage: 0.5% (1/185)
```
❌ Misleading - implies 184 SPACs are missing data

**After distinguishing zero vs unchecked:**
```
Redemption Data Status:
- Has redemptions: 15 SPACs (8%)
- Confirmed zero: 120 SPACs (65%)
- Not yet checked: 50 SPACs (27%)

Coverage: 135/185 = 73% ✅
```
✅ Accurate - shows 73% have been checked

---

## Common Scenarios

### Scenario 1: Pre-Deal SPAC
**Status**: SEARCHING
**Redemptions**: Should be NULL (not applicable yet)
**Action**: Don't mark anything

### Scenario 2: Deal Announced, No Vote Yet
**Status**: ANNOUNCED
**Redemptions**: Probably NULL (no redemptions until vote)
**Action**: Wait until DEFM14A filed

### Scenario 3: DEFM14A Filed, No Redemptions Mentioned
**Status**: ANNOUNCED
**Redemptions**: Mark as FALSE with zero
**Action**: Call `mark_no_redemptions_found()`

### Scenario 4: Extension 8-K Shows Redemptions
**Status**: SEARCHING (extended)
**Redemptions**: Mark as TRUE with redemption count
**Action**: Call `add_redemption_event()`

### Scenario 5: Merger Completed, Zero Redemptions
**Status**: COMPLETED
**Redemptions**: Mark as FALSE with zero
**Action**: Call `mark_no_redemptions_found()`

### Scenario 6: Merger Completed, High Redemptions
**Status**: COMPLETED
**Redemptions**: Mark as TRUE with redemption count
**Action**: Call `add_redemption_event()`

---

## AI Extraction Updates

### Update AI Prompts to Detect "No Redemptions"

**Before:**
```python
# AI only extracts if redemptions found
redemption_data = extract_redemptions(text)
if redemption_data:
    add_redemption_event(...)
# Problem: Silent failure if zero redemptions
```

**After:**
```python
# AI explicitly returns "checked" flag
redemption_data = extract_redemptions(text)

if redemption_data['checked']:
    if redemption_data['shares_redeemed'] > 0:
        add_redemption_event(
            shares_redeemed=redemption_data['shares_redeemed'],
            ...
        )
    else:
        mark_no_redemptions_found(
            reason='AI confirmed no redemptions in filing'
        )
```

### Enhanced AI Prompt

```python
prompt = f"""
Extract redemption data from this filing:

Return JSON:
{{
  "checked": true/false,  // Was redemption data looked for?
  "redemptions_found": true/false,  // Were redemptions mentioned?
  "shares_redeemed": <number or 0>,
  "redemption_amount": <number or 0>,
  "redemption_percentage": <number or 0>
}}

IMPORTANT:
- Set "checked": true if you looked for redemption data
- Set "redemptions_found": false if filing says "no redemptions" or "zero redemptions"
- Use 0 for all numbers if no redemptions found
"""
```

---

## Testing

### Test Case 1: SPAC with No Redemptions

```python
from utils.redemption_tracker import mark_no_redemptions_found
from database import SessionLocal

db = SessionLocal()

# Mark as checked with zero
mark_no_redemptions_found(
    db_session=db,
    ticker='FGMC',
    source='DEFM14A',
    filing_date=date(2025, 5, 15),
    reason='Test: No redemptions in BOXABL merger'
)

# Verify
spac = db.query(SPAC).filter(SPAC.ticker == 'FGMC').first()
assert spac.redemptions_occurred == False
assert spac.shares_redeemed == 0
assert spac.redemption_percentage == 0.0
```

### Test Case 2: SPAC with Redemptions

```python
from utils.redemption_tracker import add_redemption_event

# Add redemption event
add_redemption_event(
    db_session=db,
    ticker='CEP',
    shares_redeemed=2500000,
    redemption_amount=25000000.0,
    filing_date=date(2025, 6, 1),
    source='DEFM14A',
    reason='Test: Redemptions before merger vote'
)

# Verify
spac = db.query(SPAC).filter(SPAC.ticker == 'CEP').first()
assert spac.redemptions_occurred == True
assert spac.shares_redeemed == 2500000
assert spac.redemption_percentage > 0
```

---

## Summary

**Key Principles:**

1. ✅ **Always mark zero explicitly** - Don't leave as NULL
2. ✅ **Use correct function** - `add_redemption_event()` vs `mark_no_redemptions_found()`
3. ✅ **Log everything** - Both functions log to history table
4. ✅ **AI should confirm** - Prompt should explicitly check for "no redemptions"
5. ✅ **Coverage is clear** - Distinguish checked (0 or >0) from unchecked (NULL)

**Data States:**
- `NULL` = Not yet checked (unknown)
- `FALSE + 0` = Checked and confirmed zero redemptions
- `TRUE + >0` = Has redemptions

**Coverage Calculation:**
```
Coverage = (confirmed_zero + has_redemptions) / total_spacs
NOT just: has_redemptions / total_spacs
```

---

*Always distinguish between "unknown" and "confirmed zero"*
*Updated: October 9, 2025*
