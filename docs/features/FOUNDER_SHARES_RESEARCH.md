# Founder Shares & Fully Diluted Market Cap - Research

## The Full Picture: What We Need

### Current Calculation (Incomplete):
```
market_cap = price × shares_outstanding × 1.25  # Rough estimate
```

### Proper Fully Diluted Market Cap:
```
fully_diluted_mcap = (
    common_shares +           # Public redeemable shares
    founder_shares +          # Non-redeemable Class B shares
    warrant_shares +          # If in-the-money, using treasury method
    rights_shares +           # If applicable
    PIPE_shares               # Forward purchase agreements
) × price
```

---

## 1. Founder Shares (Class B)

### Ground Truth Source: **S-1 Registration Statement**

**Where to find it**:
- Section: "Description of Securities" or "Capitalization"
- Typical location: Page 30-50 of S-1
- Alternative: Form 8-K filed at IPO close

**Example language**:
```
"On December 15, 2020, the Sponsor purchased 5,750,000 founder shares
for an aggregate purchase price of $25,000, or approximately $0.004 per share."
```

**Typical structure**:
- 20% of public shares (e.g., 25M public → 5M founder)
- Sometimes 25% (to account for 15% over-allotment)
- Price: $0.003 - $0.005 per share

**Formula from S-1**:
```
founder_shares = initial_shares × (1 + overallotment_coverage)
```

If S-1 says: "7,187,500 founder shares (assuming full exercise of over-allotment)"
- Base founder shares: 6,250,000
- Over-allotment coverage: 937,500
- Total: 7,187,500

---

## 2. Warrants (Treasury Method)

### Ground Truth Source: **S-1 Registration Statement** + **424B4 Prospectus**

**Where to find it**:
- Section: "Description of Warrants"
- Unit structure: "1 share + 1/3 warrant" or "1 share + 1/2 warrant"

**Typical terms**:
- Exercise price: $11.50 per share
- Expiration: 5 years from business combination
- Ratio: 1/3, 1/2, or 1/4 warrant per unit

**Treasury Method Calculation**:
```python
if price > exercise_price:  # In-the-money
    warrant_shares = (warrants_outstanding × (price - exercise_price)) / price
else:
    warrant_shares = 0  # Out-of-the-money warrants don't dilute
```

**Example (MLAC)**:
```
Unit structure: 1 share + 1/3 warrant
Public shares: 23,000,000
Warrants outstanding: 23,000,000 / 3 = 7,666,667
Exercise price: $11.50
Current price: $11.07

Treasury method:
Since $11.07 < $11.50, warrants are OUT of the money
Additional shares from warrants: 0
```

**If price was $15**:
```
warrant_shares = (7,666,667 × ($15 - $11.50)) / $15
               = (7,666,667 × $3.50) / $15
               = 1,788,889 additional shares
```

---

## 3. Rights

### Ground Truth Source: **S-1** (if applicable)

**Where to find it**:
- Section: "Description of Rights"
- Less common than warrants (only ~10% of SPACs)

**Example**:
```
"Each right entitles the holder to receive one-tenth of one share
of Class A common stock upon consummation of our initial business combination."
```

**Typical structure**:
- 1 right = 0.1 shares
- Auto-exercised at business combination
- No exercise price

**Calculation**:
```
rights_shares = (rights_outstanding × conversion_ratio)
```

---

## 4. Forward Purchase Agreements (PIPE)

### Ground Truth Source: **8-K filed at deal announcement**

**Where to find it**:
- Section: "Subscription Agreement" or "PIPE Financing"
- Exhibit 10.1 or similar

**Example**:
```
"The Sponsor has agreed to purchase $50 million of common stock
at $10.00 per share in a private placement concurrent with closing."
```

**Calculation**:
```
pipe_shares = pipe_amount / pipe_price
            = $50,000,000 / $10.00
            = 5,000,000 shares
```

---

## 5. Earnout Shares

### Ground Truth Source: **8-K at deal announcement** or **Merger Agreement (Annex A)**

**Where to find it**:
- Section: "Earnout Provisions" or "Contingent Consideration"

**Example**:
```
"Additional earnout shares of up to 3,000,000 will be issued if the stock
price exceeds $15.00 for 20 trading days within 3 years of closing."
```

**Calculation**:
- If contingent: May or may not include (depends on accounting treatment)
- If vested: Include in fully diluted count

---

## Data Source Priority

### For each SPAC, scrape in this order:

| Data Field | Priority Source | Backup Source | Capture Rate |
|------------|----------------|---------------|--------------|
| **founder_shares** | S-1 (Section: Capitalization) | 8-K at IPO close | 95%+ |
| **warrant_ratio** | S-1 (Section: Description of Securities) | 424B4 Prospectus | 98%+ |
| **warrant_exercise_price** | S-1 (Warrant section) | 424B4 Prospectus | 98%+ |
| **rights_ratio** | S-1 (if applicable) | N/A | 10% (rare) |
| **pipe_size** | 8-K at deal announcement | Merger proxy (DEF 14A) | 60% (only announced deals) |
| **earnout_shares** | Merger Agreement (8-K Exhibit) | DEF 14A | 60% (only announced deals) |

---

## Where to Add This to Our System

### Option 1: Enhance sec_data_scraper.py ✅ RECOMMENDED

**Why**: Already scrapes S-1, 8-K, and other SEC filings

**Add new extraction methods**:

```python
def extract_founder_shares(self, s1_text: str) -> Dict:
    """
    Extract founder share data from S-1

    Looks for:
    - "founder shares" or "Class B shares"
    - Share count (typically 20-25% of public shares)
    - Purchase price (typically $0.003-0.005)
    """
    prompt = """
    From this S-1 registration statement, extract:
    1. Number of founder shares issued
    2. Founder share purchase price
    3. Over-allotment shares (if mentioned)
    4. Total founder ownership percentage

    Return JSON format.
    """

    response = ai_extract(s1_text, prompt)
    return response

def extract_warrant_terms(self, s1_text: str) -> Dict:
    """
    Extract warrant structure from S-1

    Looks for:
    - Unit structure (e.g., "1 share + 1/3 warrant")
    - Warrant exercise price
    - Warrant expiration terms
    """
    prompt = """
    From this S-1, extract the warrant terms:
    1. Unit structure (how many warrants per unit?)
    2. Warrant exercise price (typically $11.50)
    3. Warrant expiration (typically 5 years)
    4. Total warrants outstanding

    Return JSON format.
    """

    response = ai_extract(s1_text, prompt)
    return response

def extract_pipe_details(self, deal_8k_text: str) -> Dict:
    """
    Extract PIPE financing from deal announcement 8-K

    Looks for:
    - PIPE commitment amount
    - PIPE price per share
    - PIPE investors
    """
    prompt = """
    From this 8-K deal announcement, extract PIPE financing details:
    1. Total PIPE commitment ($)
    2. PIPE price per share
    3. Lead PIPE investors
    4. PIPE shares issued

    Return JSON format.
    """

    response = ai_extract(deal_8k_text, prompt)
    return response
```

**Integration point**:
```python
# In sec_data_scraper.py, line ~450
def enrich_spac_from_sec(self, ticker: str):
    ...
    # After getting S-1
    if s1_filing:
        founder_data = self.extract_founder_shares(s1_text)
        warrant_data = self.extract_warrant_terms(s1_text)

        spac.founder_shares = founder_data['founder_shares']
        spac.warrant_ratio = warrant_data['warrant_ratio']
        spac.warrant_exercise_price = warrant_data['exercise_price']

    # After getting deal 8-K
    if deal_8k:
        pipe_data = self.extract_pipe_details(deal_8k_text)
        spac.pipe_size = pipe_data['pipe_size']
        spac.pipe_price = pipe_data['pipe_price']
```

---

### Option 2: Create New CapTableAgent

**Purpose**: Specialized agent for capitalization table reconstruction

**Responsibilities**:
1. Scrape S-1 for founder shares, warrants, rights
2. Scrape deal 8-K for PIPE, earnouts
3. Calculate fully diluted share count
4. Update market cap with treasury method

**When to run**:
- After SEC enrichment (has all filings)
- Before market cap validation
- Triggered by orchestrator when needed

---

## Improving Capture Rate

### Current Challenges:

1. **AI extraction accuracy**: DeepSeek may miss numeric values
2. **Document length**: S-1 filings are 200-300 pages
3. **Varied formatting**: Each SPAC phrases it differently
4. **Cost**: Full S-1 extraction costs ~$0.50-1.00 per SPAC

### Strategies to Improve:

#### Strategy 1: Section-Specific Extraction ✅ BEST
```python
# Instead of sending full 300-page S-1 to LLM:
sections_to_check = [
    "Capitalization",
    "Description of Securities",
    "Principal Stockholders",
    "Management",
]

for section in sections_to_check:
    section_text = extract_section(s1_html, section)  # ~5-10 pages
    if "founder shares" in section_text.lower():
        founder_data = ai_extract(section_text, prompt)
        break
```

**Benefits**:
- Reduces LLM input from 300 pages → 10 pages
- Reduces cost by 95%
- Improves accuracy (less noise)

#### Strategy 2: Regex Patterns First, AI Fallback
```python
# Try regex patterns first
patterns = [
    r"([0-9,]+)\s+founder shares",
    r"([0-9,]+)\s+Class B.*shares",
    r"Sponsor purchased\s+([0-9,]+)\s+shares",
]

founder_shares = None
for pattern in patterns:
    match = re.search(pattern, text)
    if match:
        founder_shares = int(match.group(1).replace(',', ''))
        break

# If regex fails, use AI
if not founder_shares:
    founder_shares = ai_extract(text, prompt)
```

**Benefits**:
- Free for 60-70% of cases (regex works)
- AI only for edge cases
- Faster execution

#### Strategy 3: Use Structured SEC API
```python
# SEC EDGAR has structured data for some fields
url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# This might have:
# - CommonStockSharesOutstanding
# - PreferredStockSharesOutstanding (founder shares)
# - WarrantsAndRightsOutstanding
```

**Benefits**:
- Free, structured data
- No AI needed
- High accuracy

**Limitations**:
- Not all SPACs report in XBRL format
- May be delayed vs HTML filings
- Coverage: ~40-50% of SPACs

---

## Implementation Plan

### Phase 1: S-1 Extraction (Week 1)
1. Add `extract_founder_shares()` to sec_data_scraper.py
2. Add `extract_warrant_terms()` to sec_data_scraper.py
3. Add section-specific extraction helper
4. Run on all 186 SPACs
5. Log extraction success rate to data_quality.jsonl

**Target**: 90%+ capture rate for founder_shares and warrant_ratio

### Phase 2: Deal Filings (Week 2)
1. Add `extract_pipe_details()` for 8-K deal announcements
2. Add `extract_earnout_shares()` from merger agreements
3. Run only on SPACs with deal_status='ANNOUNCED' (66 SPACs)

**Target**: 70%+ capture rate for PIPE data

### Phase 3: Market Cap Recalculation (Week 3)
1. Add new column: `fully_diluted_shares`
2. Implement treasury method for warrants
3. Update price_updater.py to calculate fully diluted market cap
4. Update data_validator.py to validate against fully diluted

**Formula**:
```python
def calculate_fully_diluted_mcap(spac):
    total_shares = (
        spac.shares_outstanding +
        (spac.founder_shares or 0) +
        calculate_warrant_dilution(spac) +
        (spac.pipe_shares or 0)
    )
    return spac.price * total_shares / 1_000_000

def calculate_warrant_dilution(spac):
    """Treasury method for in-the-money warrants"""
    if not spac.warrant_ratio or not spac.warrant_exercise_price:
        return 0

    warrants_out = spac.shares_outstanding * spac.warrant_ratio

    if spac.price > spac.warrant_exercise_price:
        # In-the-money: use treasury method
        dilution = (warrants_out * (spac.price - spac.warrant_exercise_price)) / spac.price
        return dilution
    else:
        # Out-of-the-money: no dilution
        return 0
```

### Phase 4: Validation & Monitoring
1. Add validation rules:
   - `founder_shares` should be 15-30% of `shares_outstanding`
   - `warrant_ratio` should be between 0.2 and 1.0
   - `warrant_exercise_price` should be $11.50 ± $1.50
2. Add to data_quality.jsonl logging
3. Flag outliers for manual review

---

## Expected Results

### Before:
```
MLAC market_cap: $254.61M (public shares only)
  - Shares: 23,000,000
  - Price: $11.07
  - Calculation: 23M × $11.07 / 1M
```

### After (with founder shares):
```
MLAC market_cap: $318.26M (public + founder, no warrant dilution)
  - Public shares: 23,000,000
  - Founder shares: 5,750,000 (25%)
  - Warrants: OUT of money ($11.07 < $11.50 exercise)
  - Total: 28,750,000
  - Calculation: 28.75M × $11.07 / 1M
```

### After (fully diluted, if price was $15):
```
MLAC market_cap: $446.17M (fully diluted)
  - Public shares: 23,000,000
  - Founder shares: 5,750,000
  - Warrant dilution: 1,789,000 (treasury method at $15)
  - Total: 30,539,000
  - Calculation: 30.54M × $15 / 1M
```

---

## Cost Estimation

### LLM Costs (DeepSeek):
- S-1 section extraction: ~5,000 tokens input + 500 tokens output
- Cost: $0.014 per SPAC (with section-specific extraction)
- Total for 186 SPACs: **$2.60**

### Time Estimation:
- Per SPAC: ~10-15 seconds (API calls)
- Total for 186 SPACs: **30-45 minutes**

### Manual Fallback:
- For 10% that fail extraction: **~20 SPACs × 5 min = 100 minutes**

---

## Summary

**To properly calculate market cap, we need**:
1. ✅ Founder shares (from S-1)
2. ✅ Warrant ratio & exercise price (from S-1)
3. ✅ PIPE shares (from deal 8-K)
4. ⚠️ Earnout shares (conditional, from merger agreement)

**Best implementation**:
- Enhance sec_data_scraper.py with section-specific extraction
- Add 3 new methods: `extract_founder_shares()`, `extract_warrant_terms()`, `extract_pipe_details()`
- Use regex patterns first, AI as fallback
- Run on all 186 SPACs, capture rate target: 90%+

**Cost/Time**:
- $2.60 for all 186 SPACs
- 30-45 minutes runtime
- 90%+ capture rate expected

**Ready to implement?**
