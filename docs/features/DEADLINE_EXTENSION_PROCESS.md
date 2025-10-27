# Deadline & Extension Process - Correct Handling

**Date:** October 9, 2025
**Example:** QETA (Quetta Acquisition Corporation)

---

## The Problem: Capacity vs Events

We're mixing two different concepts:

### 1. Extension CAPACITY (from Charter/S-1)
What the SPAC **CAN** do per their charter

### 2. Extension EVENTS (from 8-K filings)
What the SPAC **HAS ACTUALLY** done

---

## QETA Example

### Current Database State ❌ (WRONG)
```
ipo_date:                    2023-10-06
original_deadline_date:      2025-10-06
deadline_date:               2025-10-06
is_extended:                 TRUE ❌ (wrong - they haven't extended)
extension_count:             21 ❌ (corrupted data)
extension_available:         TRUE ✓
extension_months_available:  12 ✓
max_deadline_with_extensions: 21 ❌ (should be 36)
```

### What It SHOULD Be ✅ (CORRECT)
```
# IPO & Original Deadline
ipo_date:                    2023-10-06
original_deadline_date:      2025-10-06 (24 months from IPO)

# Current Status
deadline_date:               2025-10-06 (still on original deadline)
is_extended:                 FALSE (have NOT extended yet)
extension_count:             0 (zero extension events)

# Extension Capacity (from charter)
extension_available:         TRUE (charter allows extensions)
extension_months_available:  12 (can add 12 months)
max_deadline_with_extensions: 36 (could go to Oct 2026 if needed)

# Extension Events (none yet)
extension_date:              NULL (no extensions filed)
```

---

## Correct Process for Deadlines

### Step 1: Set Original Deadline (from S-1/424B4)

**Source:** IPO prospectus
**When:** Once, at IPO
**Fields:**
```python
original_deadline_date = ipo_date + 24 months  # Never changes
deadline_date = original_deadline_date  # Initial current deadline
```

**Example:**
```
IPO: 2023-10-06
Original deadline: 2025-10-06 (24 months)
Current deadline: 2025-10-06 (starts same as original)
```

---

### Step 2: Extract Extension Capacity (from S-1/424B4)

**Source:** IPO prospectus "Extension" section
**When:** Once, at IPO
**Fields:**
```python
extension_available: TRUE/FALSE  # Does charter allow?
extension_months_available: 12   # How many months can add?
extension_requires_vote: TRUE/FALSE
extension_deposit_per_share: 0.03  # Cost per extension month
max_deadline_with_extensions: 36  # Total possible months from IPO
```

**Example (QETA):**
```
extension_available: TRUE
extension_months_available: 12
max_deadline_with_extensions: 36 months
Calculation: 24 months (original) + 12 months (extension) = 36 months total
Max deadline: 2023-10-06 + 36 months = 2026-10-06
```

**IMPORTANT:** These are CAPABILITIES, not actual extensions!

---

### Step 3: Monitor for Actual Extensions (from 8-K)

**Source:** 8-K filings (Item 8.01 typically)
**When:** Only when extension actually happens
**Trigger:** 8-K with "extension" keywords

**Fields to Update:**
```python
deadline_date = new_deadline  # Move deadline forward
is_extended = TRUE  # Mark that extension occurred
extension_count += 1  # Increment counter
extension_date = filing_date  # Date of this extension
```

**Example Extension Event:**
```
# Before extension
deadline_date: 2025-10-06
is_extended: FALSE
extension_count: 0

# After 8-K filed for extension
deadline_date: 2026-10-06  # Extended by 12 months
is_extended: TRUE
extension_count: 1
extension_date: 2025-09-15  # When extension 8-K filed
```

---

## The Three Key Fields

### 1. original_deadline_date
- **Set once:** From S-1/424B4
- **Never changes:** Even if extended
- **Purpose:** Track original charter deadline
- **Example:** 2025-10-06

### 2. deadline_date
- **Set initially:** Same as original_deadline_date
- **Updates:** Each time extension filed
- **Purpose:** Current active deadline
- **Example:** 2025-10-06 (or 2026-10-06 if extended)

### 3. max_deadline_with_extensions
- **Set once:** From S-1/424B4
- **Calculation:** original deadline + all possible extensions
- **Purpose:** Latest possible deadline
- **Example:** 2026-10-06 (24 + 12 = 36 months)

---

## Data States

### State 1: Pre-Extension (QETA Current State)
```
original_deadline_date: 2025-10-06
deadline_date:          2025-10-06  ← Current deadline
max_deadline:           2026-10-06  ← Could extend to here
is_extended:            FALSE
extension_count:        0
Status: Can extend but hasn't yet
```

### State 2: After One Extension
```
original_deadline_date: 2025-10-06  ← Never changes
deadline_date:          2026-10-06  ← Extended
max_deadline:           2026-10-06
is_extended:            TRUE
extension_count:        1
extension_date:         2025-09-15
Status: Extended once, at max deadline
```

### State 3: Multiple Extensions Possible
```
original_deadline_date: 2025-04-01
deadline_date:          2025-10-01  ← Extended 6 months
max_deadline:           2026-10-01  ← Could extend 12 more months
is_extended:            TRUE
extension_count:        1
Status: Extended once, can extend 1 more time
```

---

## Common Scraper Mistakes ❌

### Mistake 1: Setting is_extended from Capacity
```python
# WRONG:
if s1_data.get('extension_available'):
    spac.is_extended = TRUE  # ❌ Just because they CAN doesn't mean they DID
```

**Correct:**
```python
# ONLY set is_extended when finding actual extension 8-K
if extension_8k_found:
    spac.is_extended = TRUE  # ✅
```

### Mistake 2: Overwriting deadline_date
```python
# WRONG:
spac.deadline_date = original_deadline  # ❌ Overwrites extensions!
```

**Correct:**
```python
# Only set if not already set, or use tracker
if not spac.deadline_date:
    update_deadline_date(...)  # ✅
```

### Mistake 3: Confusing max_deadline with deadline
```python
# WRONG:
spac.deadline_date = max_deadline  # ❌ They haven't extended yet!
```

**Correct:**
```python
spac.max_deadline_with_extensions = ipo_date + 36 months  # Capacity
spac.deadline_date = ipo_date + 24 months  # Current deadline
```

---

## Validation Queries

### Check for Incorrect Extensions
```sql
-- SPACs marked as extended but deadline = original
SELECT ticker, original_deadline_date, deadline_date, is_extended, extension_count
FROM spacs
WHERE is_extended = TRUE
AND deadline_date = original_deadline_date;
-- Should return 0 rows (if extended, deadline should be different)
```

### Check Extension Count Sanity
```sql
-- Extension count should be small (0-3 typically)
SELECT ticker, extension_count
FROM spacs
WHERE extension_count > 3;
-- Large numbers like 21 indicate data corruption
```

### Check Max Deadline Calculation
```sql
-- Max deadline should be reasonable (18-48 months from IPO)
SELECT ticker,
       ROUND((max_deadline_with_extensions::date - ipo_date::date) / 30.0) as max_months
FROM spacs
WHERE max_deadline_with_extensions IS NOT NULL
AND (max_deadline_with_extensions::date - ipo_date::date) / 30.0 NOT BETWEEN 18 AND 48;
-- Should be 24, 30, 36, or 42 typically
```

---

## Fix QETA Data

```sql
-- Reset QETA to correct state
UPDATE spacs
SET
    is_extended = FALSE,  -- Have NOT extended yet
    extension_count = 0,  -- Zero extension events
    extension_date = NULL,  -- No extensions filed
    deadline_date = original_deadline_date,  -- Current = original
    max_deadline_with_extensions = 36,  -- 24 + 12 possible months
    extension_available = TRUE,  -- Charter allows
    extension_months_available = 12  -- Can add 12 months
WHERE ticker = 'QETA';
```

---

## Scraper Implementation

### When Processing S-1/424B4
```python
# Set extension CAPACITY
if prosp_data.get('extension_available'):
    spac.extension_available = TRUE
    spac.extension_months_available = prosp_data['extension_months']

    # Calculate max possible deadline
    max_deadline = ipo_date + original_months + extension_months
    spac.max_deadline_with_extensions = max_deadline

    # But DON'T set is_extended or extension_count
    # Those only get set when actual extension 8-K is filed
```

### When Processing Extension 8-K
```python
# Found actual extension event
if extension_8k_found:
    # Use deadline tracker
    update_deadline_date(
        ticker=ticker,
        new_date=new_deadline,
        source='8-K',
        is_extension=TRUE
    )

    # This automatically sets:
    # - is_extended = TRUE
    # - extension_count += 1
    # - extension_date = filing_date
```

---

## Summary

**Key Principle:** CAPACITY ≠ EVENTS

| Field | Type | Source | When Set |
|-------|------|--------|----------|
| `original_deadline_date` | Date | S-1 | Once at IPO |
| `deadline_date` | Date | S-1, then 8-K | Initially, then each extension |
| `max_deadline_with_extensions` | Date | S-1 | Once at IPO (capacity) |
| `extension_available` | Boolean | S-1 | Once at IPO (capacity) |
| `extension_months_available` | Integer | S-1 | Once at IPO (capacity) |
| `is_extended` | Boolean | 8-K | Only when actual extension filed |
| `extension_count` | Integer | 8-K | Incremented each extension event |
| `extension_date` | Date | 8-K | Date of last extension event |

**QETA Correct State:**
- Original deadline: Oct 2025 (24 months)
- Current deadline: Oct 2025 (not extended yet - has deal)
- CAN extend to: Oct 2026 (12 month capacity)
- HAS extended: NO (extension_count = 0)

---

*Correct handling prevents confusion between what SPACs CAN do vs what they HAVE done*
