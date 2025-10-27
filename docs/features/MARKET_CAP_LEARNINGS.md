# Market Cap Learnings - Yahoo Finance Methodology

**Date:** October 9, 2025
**Source:** AEXA market cap investigation

---

## Problem

AEXA's market cap seemed wrong:
- Manual calculation: $11.34 × 34,675,000 = $393M
- Yahoo Finance reported: $560.88M
- Difference: $167M (43% higher!)

## Root Cause

**Yahoo Finance calculates market cap differently than expected:**

1. **Yahoo's "Shares Outstanding" field** = Public float only (~34.7M)
2. **Yahoo's "Market Cap" calculation** = Price × Total shares (public + founder) (~49.5M)
3. **This creates apparent inconsistency:** Market Cap / Shares Outstanding ≠ Price

## Investigation Results

### AEXA 424B4 Prospectus (Sept 29, 2025)

**Share Structure:**
- Public shares (Class A): 34,500,000 (with full over-allotment)
- Founder shares (Class B): 14,785,714 (30% of total)
  - Can be reduced to 12,857,143 if over-allotment not exercised
- Private placement: 175,000 shares
- **Total shares outstanding:** ~49,460,713

**Yahoo Finance Data:**
- Reported "Shares Outstanding": 34,675,000
- Reported "Market Cap": $560,884,480
- **Implied total shares:** $560,884,480 / $11.34 = **49,460,713**

**Validation:**
- 34,675,000 (public) + 14,785,714 (founder) ≈ 49,460,713 ✅
- Founder percentage: 14.8M / 49.5M = **29.9%** (typical range: 20-30%) ✅

---

## Key Learnings

### 1. Yahoo Includes Founder Shares in Market Cap

**This is standard practice across all SPACs:**
- Market cap reflects total enterprise value
- Includes ALL shares (public + founder/sponsor + private placement)
- Founder shares have economic value even if not publicly traded

### 2. "Shares Outstanding" vs. "Market Cap Basis"

**Two different concepts:**

| Metric | What It Means | AEXA Example |
|--------|---------------|--------------|
| Shares Outstanding (Yahoo field) | Public float | 34,675,000 |
| Total Shares (for market cap) | Public + Founder + PP | 49,460,713 |
| Founder Shares | Sponsor allocation (typically 20-30%) | 14,785,714 |

### 3. Founder Share Allocation Varies

**Don't assume 20%!**

Common allocations:
- Standard SPAC: 20% (4:1 ratio)
- AEXA: 30% (2.33:1 ratio)
- Range seen: 15-35%

**Always verify from 424B4 prospectus.**

### 4. Market Cap Calculation Approaches

**Wrong approach (what we were doing):**
```python
market_cap = price × shares_outstanding_from_yahoo
# Problem: Only counts public float, misses founder shares
```

**Correct approach:**
```python
# Option 1: Trust Yahoo's market cap directly
market_cap = yahoo_finance.info['marketCap'] / 1_000_000  # Convert to millions

# Option 2: Calculate from 424B4 data
total_shares = public_shares + founder_shares + private_placement
market_cap = (price × total_shares) / 1_000_000
```

---

## System Updates Required

### 1. Update Database Schema

**Add new columns:**
```sql
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS founder_shares BIGINT;
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS total_shares_outstanding BIGINT;
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS private_placement_shares BIGINT;
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS founder_share_percentage FLOAT;
```

**Calculation:**
```python
total_shares_outstanding = shares_outstanding + founder_shares + private_placement_shares
founder_share_percentage = (founder_shares / total_shares_outstanding) * 100
```

### 2. Update price_updater.py

**Current logic (WRONG):**
```python
# Calculates fully diluted market cap (public + warrants)
market_cap = price × (shares_outstanding + warrant_dilution) / 1M
```

**New logic (CORRECT):**
```python
# Use Yahoo's market cap directly (includes founder shares)
yahoo_market_cap = stock.info.get('marketCap', 0) / 1_000_000

# Store both for comparison
update_data['market_cap'] = yahoo_market_cap  # Primary field
update_data['calculated_market_cap'] = (price × shares_outstanding) / 1M  # For debugging

# Calculate implied total shares
if yahoo_market_cap and price:
    implied_total_shares = (yahoo_market_cap * 1_000_000) / price
    update_data['total_shares_outstanding'] = int(implied_total_shares)
```

### 3. Add Validation Rules

**Check if founder share percentage makes sense:**

```python
def validate_market_cap(spac, yahoo_market_cap, price):
    """Validate that market cap makes sense given share structure"""

    if not yahoo_market_cap or not price or not spac.shares_outstanding:
        return None

    # Calculate implied total shares from Yahoo's market cap
    implied_total = (yahoo_market_cap * 1_000_000) / price

    # Calculate implied founder shares
    implied_founder = implied_total - spac.shares_outstanding

    # Calculate founder percentage
    founder_pct = (implied_founder / implied_total) * 100

    # Typical SPAC founder allocation: 20-30%
    if founder_pct < 15 or founder_pct > 35:
        logger.warning(
            f"{spac.ticker}: Unusual founder percentage {founder_pct:.1f}%. "
            f"Implied founder shares: {implied_founder:,.0f}. "
            f"Review 424B4 to verify share structure."
        )

    return {
        'implied_total_shares': int(implied_total),
        'implied_founder_shares': int(implied_founder),
        'founder_percentage': round(founder_pct, 2)
    }
```

### 4. Extract Founder Shares from SEC Filings

**Add to sec_data_scraper.py:**

```python
def extract_founder_shares(self, ticker: str, cik: str) -> Optional[int]:
    """
    Extract founder/sponsor share count from 424B4 prospectus

    Looks for:
    - "founder shares" or "Class B" shares
    - Capitalization table
    - Share structure after offering
    """

    # Search for 424B4 (IPO prospectus)
    filings = self.search_filings(cik, '424B4', count=1)

    if not filings:
        return None

    content = self.fetch_filing_content(filings[0]['url'])

    # Use AI to extract founder shares
    prompt = f"""Extract the founder/sponsor share count from this SPAC prospectus.

{content[:20000]}

Find:
1. Founder shares (Class B common stock)
2. Total shares outstanding after IPO (public + founder)

Report exact numbers only.
"""

    response = self.ai_client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )

    # Parse AI response for founder shares
    # (implementation details...)

    return founder_shares
```

### 5. Update Documentation

**Add to CLAUDE.md:**

```markdown
### Market Cap Calculation

**IMPORTANT:** Always use Yahoo Finance's market cap directly, do NOT recalculate.

**Why?**
- Yahoo includes ALL shares (public + founder/sponsor + private placement)
- Our `shares_outstanding` field only tracks public float
- Founder shares are typically 20-30% of total shares

**Example (AEXA):**
- Public shares: 34.7M
- Founder shares: 14.8M (30%)
- Total: 49.5M
- Market cap: $11.34 × 49.5M = $560.88M ✅

**Validation:**
- Founder shares typically 20-30% of total
- Flag if outside 15-35% range
- Always verify from 424B4 prospectus
```

---

## Action Items

- [ ] Add `founder_shares`, `total_shares_outstanding` columns to database
- [ ] Update `price_updater.py` to use Yahoo market cap directly
- [ ] Add market cap validation function
- [ ] Extract founder shares from 424B4 in `sec_data_scraper.py`
- [ ] Update all 185 SPACs with founder share data
- [ ] Add founder share percentage to Streamlit dashboard
- [ ] Document in CLAUDE.md

---

## References

- AEXA 424B4: https://www.sec.gov/Archives/edgar/data/2079173/000119312525221814/d38750d424b4.htm
- Filed: September 29, 2025
- Public shares: 34,500,000
- Founder shares: 14,785,714 (30% allocation)

---

*Last updated: October 9, 2025*
