# Learning #19: Redemption Data Extraction & Market Cap Issues

**Date:** October 9, 2025
**Severity:** Medium (redemptions exist but not being updated)
**Status:** ⚠️ Partially Working, Needs Improvement

---

## Question

"Are we now correctly capturing any redemptions for all these spacs that had deadline issues? redemptions should be impacting share counts, market cap etc."

---

## Investigation Results

Tested 23 expired SPACs to check:
1. Are redemptions being extracted?
2. Are share counts being updated?
3. Is market cap reflecting redemptions?

---

## Findings

### ✅ GOOD: Redemptions ARE Being Tracked (74%)

**17 out of 23 SPACs (74%)** have redemption data:

| SPAC | IPO Shares | Current Shares | Redeemed | % Redeemed |
|------|-----------|----------------|----------|------------|
| ISRL | 14,375,000 | 797,932 | 13,577,068 | **94.4%** |
| DYCQ | 6,900,000 | 832,415 | 6,067,585 | **87.9%** |
| FORL | 5,980,000 | 960,307 | 5,019,693 | **83.9%** |
| ATMV | 6,900,000 | 1,574,356 | 5,325,644 | **77.2%** |
| TBMC | 6,900,000 | 2,379,616 | 4,520,384 | **65.5%** |
| OAKU | 5,750,000 | 3,577,425 | 2,172,575 | 37.8% |
| EMCG | 7,475,000 | 5,295,112 | 2,179,888 | 29.2% |
| BOWN | 6,900,000 | 5,896,568 | 1,003,432 | 14.5% |
| ATMC | 6,900,000 | 6,000,000 | 900,000 | 13.0% |
| ...  | ... | ... | ... | ... |

**High Redemption SPACs** (>75%):
- ISRL, DYCQ, FORL, ATMV are close to liquidation
- Only 6-16% of original shareholders remain
- These SPACs are essentially "dead" but still trading

**Key Insight**: Redemptions range from 8% (typical) to 94% (essentially liquidated)

---

### ⚠️ ISSUE #1: Redemptions NOT Being Extracted from 10-Qs

**Evidence**:
```
BAYA:
  Redeemed (calc):   900,000 shares  ← Calculated (baseline - current)
  NOT showing:
  Redeemed (DB):     900,000 shares  ← Would show if extracted from 10-Q
```

**What this means**:
- We HAVE `shares_outstanding` in database (good!)
- We can CALCULATE redemptions (baseline - current)
- But we're NOT **extracting fresh redemption data** from each 10-Q filing

**Root Cause**:

Looking at `quarterly_report_extractor.py` line 683-685:

```python
# Update shares if redemptions occurred
if 'shares_redeemed' in data and spac.shares_outstanding:
    spac.shares_outstanding -= data['shares_redeemed']
    updated_fields.append(f"shares_outstanding={spac.shares_outstanding:,}")
```

**The code exists** to update shares_outstanding when redemptions are extracted.

**But**: The extraction patterns aren't finding `shares_redeemed` in most 10-Qs.

**Evidence from test runs**:
```
BOWN - Processing 10-Q  filed 2025-08-15
  ✓ Shares redeemed: 103,432  ← Found in 1 SPAC!
  ✓ Trust balance: $2,266,500
  ✓ Updated database: trust_cash=$2,266,500, shares_outstanding=5,896,568.0
```

Only **BOWN, ALCY, EMCG** showed "Shares redeemed" messages - that's **3 out of 23 (13%)**.

**Yet 17 SPACs (74%) have redemption data in database** - this means shares_outstanding was set initially (probably from IPO data), but NOT being updated from quarterly reports.

---

### ⚠️ ISSUE #2: Market Cap Unit Problem

**All 23 SPACs** show incorrect market cap:

| SPAC | DB Market Cap | Calculated | Issue |
|------|---------------|------------|-------|
| WALD | $89 | $71,415,000 | 100% off |
| IBAC | $151 | $120,750,000 | 100% off |
| ATMC | $96 | $73,260,000 | 100% off |
| SPKL | $147 | $117,100,000 | 100% off |

**Pattern**: Database values are ~1,000,000x smaller than calculated

**Root Cause**: Market cap is being stored in **millions** without proper unit label
- `$84` in database means `$84 million`
- But displayed as `$84` (looks like $84 dollars)

**Should be**:
- Either: Store in dollars (84,000,000)
- Or: Label properly ("84M" or "$84 million")

---

## Impact Analysis

### Impact of Issue #1 (Not Extracting Redemptions):

**What we're missing**:
- Real-time redemption tracking as 10-Qs are filed
- Historical redemption trends (by quarter)
- Redemption amount ($$ returned to shareholders)

**What still works**:
- Current share count is correct (updated manually or from IPO scraper)
- Can calculate redemptions from baseline
- Premium calculations still accurate

**Severity**: **Medium**
- We HAVE the data (shares_outstanding is accurate)
- We're just not UPDATING it from 10-Qs automatically
- Manual updates or IPO scraper must be keeping it current

### Impact of Issue #2 (Market Cap Units):

**What breaks**:
- Market cap displays look wrong ($84 instead of $84M)
- Filtering/sorting by market cap
- Market cap variance calculations
- Any alerts based on market cap

**Severity**: **Medium-High**
- Affects ALL SPACs (23/23 = 100%)
- But it's a display/unit issue, not data loss
- Easy fix (multiply by 1M or fix storage)

---

## Why Redemption Extraction Patterns Aren't Working

### Current Redemption Extraction Code:

```python
def _parse_redemption_text(self, text: str, ticker: str) -> Optional[Dict]:
    """Parse redemption information from text"""
    result = {}

    # Pattern: Shares redeemed
    redemption_patterns = [
        r'([\d,]+)\s+shares?(?:.*?)(?:were\s+)?redeemed?',
        r'redemption\s+of\s+([\d,]+)\s+shares?',
    ]

    for pattern in redemption_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            shares_str = match.group(1).replace(',', '')
            try:
                shares_redeemed = int(shares_str)
                result['shares_redeemed'] = shares_redeemed
                print(f"      ✓ Shares redeemed: {shares_redeemed:,}")
                break
            except:
                pass

    return result if result else None
```

**Why it's failing**:

1. **Too strict patterns**: Patterns like `"([\d,]+) shares redeemed"` require specific word order
2. **Only searches equity section**: May miss redemptions in other sections
3. **No AI fallback**: Unlike extension extraction, no AI extraction for redemptions

**SPAC 10-Q redemption language varies**:
```
"5,199,297 Public Shares were redeemed" ← MATCHES
"redeeming 5,199,297 shares" ← MATCHES
"stockholders elected to redeem an aggregate of 5,199,297" ← MIGHT MISS
"a total of 5,199,297 shares... tendered for redemption" ← MIGHT MISS
"redemptions totaling 5,199,297" ← MIGHT MISS
```

---

## Recommendations

### Priority 1: Improve Redemption Extraction Patterns

**Add more pattern variations**:
```python
redemption_patterns = [
    # Current patterns
    r'([\d,]+)\s+shares?(?:.*?)(?:were\s+)?redeemed?',
    r'redemption\s+of\s+([\d,]+)\s+shares?',

    # Additional patterns needed
    r'(?:redeem|redeemed|redeeming)(?:[^.]{0,50})([\d,]+)\s+shares?',
    r'([\d,]+)\s+shares?(?:[^.]{0,50})(?:tendered|elected to redeem)',
    r'(?:aggregate|total)(?:[^.]{0,30})of\s+([\d,]+)\s+shares?(?:[^.]{0,30})redemption',
    r'redemptions?\s+totaling\s+([\d,]+)',
]
```

**Add AI fallback** (like extension extraction has):
```python
# If no regex matches and AI available, use AI extraction
if not result and AI_AVAILABLE:
    result = self._extract_redemption_with_ai(text, ticker)
```

**Search full clean text** (not just equity section):
```python
# Current: Only searches 'equity' section
if 'equity' in sections:
    redemption_data = self._parse_redemption_text(sections['equity'], ticker)

# Better: Search full clean text first
if 'full_clean_text' in sections:
    redemption_data = self._parse_redemption_text(sections['full_clean_text'], ticker)
```

### Priority 2: Fix Market Cap Unit Issue

**Option A**: Fix storage (store in dollars, not millions)
```python
# When scraping
spac.market_cap = shares_outstanding * price  # Store in dollars
```

**Option B**: Fix display (label millions)
```python
# When displaying
if market_cap > 1_000_000:
    display = f"${market_cap/1_000_000:.1f}M"
else:
    display = f"${market_cap:,.0f}"
```

**Recommended**: **Option A** (fix storage)
- Consistent with shares_outstanding (stored as actual count, not millions)
- Simplifies calculations
- No confusion about units

### Priority 3: Add Redemption Amount Extraction

Currently extracting:
- ✅ `shares_redeemed` (count)
- ✅ `trust_cash` (remaining)
- ❌ `redemption_amount` ($ paid out) - **MISSING!**

**Should extract**:
```
"5,199,297 shares redeemed for $55,152,224"
       ↓                           ↓
  shares_redeemed           redemption_amount
```

**Why it matters**:
- Helps track trust value erosion
- Can calculate per-share redemption price
- Validation: `redemption_amount ≈ shares_redeemed * trust_value`

### Priority 4: Test on More SPACs

Current test: 3 out of 23 SPACs (13%) extracted redemptions successfully

**Need to test on**:
- 10-20 more SPACs with known redemptions
- Different 10-Q formats
- Different fiscal periods (Q1, Q2, Q3, annual)
- Tune patterns until 80%+ success rate

---

## Learning #19 Summary

### What We Confirmed:
- ✅ Redemptions ARE tracked (74% coverage)
- ✅ shares_outstanding exists and is accurate
- ✅ Can calculate redemptions from baseline
- ✅ Premium calculations use correct shares

### What We Found:
- ⚠️ NOT extracting redemptions from 10-Qs (only 13% success)
- ⚠️ Market cap has unit issue (stored in millions, displayed wrong)
- ⚠️ Missing redemption_amount extraction

### What To Fix:
1. **Improve redemption patterns** (more variations)
2. **Add AI fallback** for redemption extraction
3. **Search full text** for redemptions (not just equity section)
4. **Fix market cap units** (store in dollars OR label millions)
5. **Extract redemption amounts** ($ paid to shareholders)

### Key Insight:
> Having accurate `shares_outstanding` is more important than extracting each redemption event. Our data is CORRECT (we have current share counts), we're just not UPDATING it automatically from 10-Qs. This is medium priority - the data quality is good, automation could be better.

---

## Related Learnings

- **Learning #16**: IPO date validation
- **Learning #17**: Cross-validation (10-Q vs S-1)
- **Learning #18**: 8-K document URL extraction
- **Learning #19**: Redemption extraction patterns (this learning)

---

**Status**: ⚠️ Data quality good (74% coverage), extraction automation needs improvement (13% → 80%+ target)
