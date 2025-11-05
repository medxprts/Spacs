# Opportunity Agent - Data Audit & Sourcing Plan

**Date**: 2025-11-04
**Purpose**: Map required datapoints to existing/new data sources

---

## Phase 1: Pre-Announcement Filters - Data Mapping

### 1. Market Cap: $100M - $500M

**What we need**: Current market capitalization

**Current Database**:
- ✅ `market_cap` (double precision) - EXISTS
- ✅ `price` (double precision) - EXISTS
- ✅ `shares_outstanding` (double precision) - EXISTS

**Data Quality Check**:
```sql
SELECT COUNT(*) as total,
       COUNT(market_cap) as has_market_cap,
       COUNT(price) as has_price,
       COUNT(shares_outstanding) as has_shares
FROM spacs WHERE deal_status = 'SEARCHING';
```

**Sourcing**:
- ✅ Already calculated and stored
- ✅ Updated by price_updater.py
- **Action**: None needed (data exists)

---

### 2. Sponsor Track Record (>15% avg pop after announcement)

**What we need**:
- Historical sponsor performance
- % price change in 7/14/30 days post-announcement for each sponsor's previous deals

**Current Database**:
- ✅ `sponsor` (varchar) - EXISTS
- ✅ `price_at_announcement` (double precision) - EXISTS
- ✅ `announced_date` (timestamp) - EXISTS
- ❌ **MISSING**: Historical price data after announcement
- ❌ **MISSING**: Aggregated sponsor performance metrics

**Data Gaps**:
1. No historical price tracking (only current price)
2. No sponsor performance aggregation

**NEW TABLE NEEDED**: `sponsor_performance`
```sql
CREATE TABLE sponsor_performance (
    id SERIAL PRIMARY KEY,
    sponsor_name VARCHAR(255) UNIQUE,

    -- Performance Metrics
    total_deals INT DEFAULT 0,
    completed_deals INT DEFAULT 0,
    avg_7day_pop NUMERIC,      -- Avg % change 7 days post-announcement
    avg_14day_pop NUMERIC,     -- Avg % change 14 days post-announcement
    avg_30day_pop NUMERIC,     -- Avg % change 30 days post-announcement
    max_pop NUMERIC,           -- Best performing deal

    -- Deal History
    deal_tickers TEXT[],       -- List of SPAC tickers

    last_updated TIMESTAMP DEFAULT NOW()
);
```

**NEW TABLE NEEDED**: `price_history`
```sql
CREATE TABLE price_history (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker),
    date DATE,
    price NUMERIC,
    volume BIGINT,

    -- Key Events
    days_since_announcement INT,
    days_since_vote INT,

    UNIQUE(ticker, date)
);
```

**Data Sourcing**:
1. **Backfill historical prices**:
   - Source: Yahoo Finance API (yfinance)
   - For each SPAC with announced_date, fetch daily prices from announcement date + 30 days
   - Command: `python3 backfill_price_history.py`

2. **Calculate sponsor metrics**:
   - Query: All SPACs by sponsor
   - Calculate: (price_7d_later - price_at_announcement) / price_at_announcement * 100
   - Aggregate by sponsor
   - Command: `python3 calculate_sponsor_performance.py`

3. **Ongoing tracking**:
   - price_updater.py should INSERT into price_history daily
   - sponsor_performance recalculated weekly

**Action Required**:
- [ ] Create `sponsor_performance` table
- [ ] Create `price_history` table
- [ ] Build `backfill_price_history.py` script
- [ ] Build `calculate_sponsor_performance.py` script
- [ ] Update `price_updater.py` to log to price_history

---

### 3. Target Industry (Hot Narrative Sectors)

**What we need**: Classify SPACs by target industry

**Current Database**:
- ✅ `sector` (varchar) - EXISTS

**Sample Data Check**:
```sql
SELECT sector, COUNT(*)
FROM spacs
WHERE deal_status = 'SEARCHING'
GROUP BY sector
ORDER BY COUNT(*) DESC;
```

**Hot Sectors Map**:
```python
HOT_SECTORS = {
    'AI': ['Artificial Intelligence', 'AI', 'Machine Learning', 'Data Analytics'],
    'Cybersecurity': ['Cybersecurity', 'Cyber', 'Security', 'InfoSec'],
    'Digital Assets': ['Crypto', 'Blockchain', 'Digital Assets', 'Web3', 'NFT'],
    'Next-Gen Energy': ['Electric Vehicle', 'EV', 'Battery', 'Clean Energy', 'Renewable'],
    'FinTech': ['FinTech', 'Financial Technology', 'Payments', 'Digital Banking'],
    'Space': ['Space', 'Aerospace', 'Satellite'],
    'BioTech': ['BioTech', 'Gene Therapy', 'CRISPR', 'Genomics']
}

BORING_SECTORS = [
    'Industrials', 'Consumer Goods', 'Traditional Retail',
    'Manufacturing', 'Real Estate', 'Hospitality'
]
```

**Data Quality**:
- Sector data comes from S-1 filing
- May need AI cleanup/standardization

**Action Required**:
- [ ] Create sector classification helper function
- [ ] Review current sector values for inconsistencies
- [ ] Map to hot/boring categories

**Sourcing**: ✅ Already in database (from S-1 extraction)

---

### 4a. Low Warrant Dilution (1/5, 1/3, 0 warrants)

**What we need**: Warrant ratio (warrants per share)

**Current Database**:
- ✅ `warrant_ratio` (double precision) - EXISTS
- ✅ `unit_structure` (varchar) - EXISTS

**Sample Data Check**:
```sql
SELECT warrant_ratio, unit_structure, COUNT(*)
FROM spacs
WHERE deal_status = 'SEARCHING'
GROUP BY warrant_ratio, unit_structure
ORDER BY warrant_ratio;
```

**Data Format**:
- Current: `warrant_ratio = 0.33` (stored as decimal)
- Need: Parse "1/3", "1/5", "0" from unit_structure

**Conversion Logic**:
```python
def parse_warrant_ratio(unit_structure):
    """
    Examples:
    "1 share + 1/3 warrant" → 0.33
    "1 share + 1/5 warrant" → 0.20
    "1 share only" → 0.00
    "1 share + 1 warrant" → 1.00
    """
    if not unit_structure:
        return None

    # Parse fraction
    if '1/3' in unit_structure:
        return 0.33
    elif '1/5' in unit_structure:
        return 0.20
    elif '1/4' in unit_structure:
        return 0.25
    elif '1/2' in unit_structure:
        return 0.50
    elif '+ 1 warrant' in unit_structure:
        return 1.00
    elif 'only' in unit_structure or 'no warrant' in unit_structure:
        return 0.00

    return None
```

**Action Required**:
- [ ] Review warrant_ratio data quality
- [ ] Build warrant_ratio parser if needed

**Sourcing**: ✅ Already in database (from S-1/424B4 extraction)

---

### 4b. Performance-Based Promote

**What we need**: Whether sponsor shares vest at performance thresholds ($15, $20)

**Current Database**:
- ✅ `sponsor_promote` (double precision) - EXISTS (% of shares)
- ❌ **MISSING**: Vesting structure (time-based vs performance-based)

**NEW COLUMN NEEDED**: `promote_vesting_type`
```sql
ALTER TABLE spacs ADD COLUMN promote_vesting_type VARCHAR(50);
-- Values: 'standard', 'performance_based', 'time_based'

ALTER TABLE spacs ADD COLUMN promote_vesting_prices NUMERIC[];
-- Array: [15.00, 20.00] for "$15, $20" vesting
```

**Data Sourcing**:
- Source: S-1 filing (usually in "Founder Shares" or "Promote Structure" section)
- Extraction: AI-powered extraction from S-1
- Keywords: "vest", "performance", "$15", "$20", "price targets"

**Sample S-1 Language**:
> "Founder shares will vest in tranches as follows: 50% at $15.00 per share,
> remaining 50% at $20.00 per share, measured over 20 trading days"

**Action Required**:
- [ ] Add `promote_vesting_type` column
- [ ] Add `promote_vesting_prices` column
- [ ] Build AI extraction for vesting terms from S-1
- [ ] Backfill for existing SPACs

**Script**: `extract_promote_vesting.py`

---

## Phase 2: Post-Announcement Catalysts - Data Mapping

### 1. PIPE Analysis

#### 1a. PIPE Size (% of trust)

**What we need**:
- PIPE investment amount
- Trust size for comparison

**Current Database**:
- ✅ `pipe_size` (double precision) - EXISTS
- ✅ `has_pipe` (boolean) - EXISTS
- ✅ `trust_cash` (double precision) - EXISTS

**Data Quality Check**:
```sql
SELECT COUNT(*) as total,
       COUNT(pipe_size) as has_pipe_size,
       COUNT(trust_cash) as has_trust_cash
FROM spacs
WHERE deal_status = 'ANNOUNCED' AND has_pipe = TRUE;
```

**Calculation**:
```python
pipe_percentage = (pipe_size / trust_cash) * 100
```

**Action Required**:
- [ ] Add calculated column `pipe_percentage`
- [ ] Review data quality for pipe_size

**Sourcing**: ✅ Already in database (from 8-K extraction)

---

#### 1b. PIPE Investors (Tier-1 institutions)

**What we need**: List of PIPE investors

**Current Database**:
- ❌ **MISSING**: PIPE investor names

**NEW TABLE NEEDED**: `pipe_investors`
```sql
CREATE TABLE pipe_investors (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker),
    investor_name VARCHAR(255),
    investment_amount NUMERIC,

    -- Classification
    is_tier1 BOOLEAN DEFAULT FALSE,
    investor_type VARCHAR(50),  -- 'institutional', 'hedge_fund', 'family_office'

    -- Source
    filing_url VARCHAR(500),
    filing_date DATE,

    UNIQUE(ticker, investor_name)
);
```

**Tier-1 Institutions List**:
```python
TIER1_INVESTORS = [
    'BlackRock', 'Vanguard', 'Fidelity', 'State Street',
    'T. Rowe Price', 'Capital Group', 'Wellington Management',
    'Invesco', 'Franklin Templeton', 'PIMCO',
    'Neuberger Berman', 'Janus Henderson', 'Morgan Stanley',
    'Goldman Sachs Asset Management', 'JPMorgan Asset Management'
]
```

**Data Sourcing**:
- Source: 8-K filing exhibits (EX-10.1, EX-10.2 - PIPE subscription agreements)
- Extraction: AI-powered extraction
- Location: "SCHEDULE OF INVESTORS" or "PURCHASERS" section

**Sample 8-K Language**:
```
PIPE Investors:
BlackRock Capital Allocation Trust: $50,000,000
Fidelity Contrafund: $30,000,000
T. Rowe Price Growth Fund: $20,000,000
```

**Action Required**:
- [ ] Create `pipe_investors` table
- [ ] Build AI extraction for PIPE investors from 8-K exhibits
- [ ] Create tier-1 classification function
- [ ] Backfill for existing announced deals

**Script**: `extract_pipe_investors.py`

---

### 2. "Hockey Stick" Projections

**What we need**:
- Revenue projections (3-5 year)
- CAGR (Compound Annual Growth Rate)
- Presence of exponential growth charts

**Current Database**:
- ❌ **MISSING**: Revenue projections
- ❌ **MISSING**: Growth metrics

**NEW TABLE NEEDED**: `deal_projections`
```sql
CREATE TABLE deal_projections (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker),

    -- Revenue Projections (in millions)
    revenue_year1 NUMERIC,
    revenue_year2 NUMERIC,
    revenue_year3 NUMERIC,
    revenue_year4 NUMERIC,
    revenue_year5 NUMERIC,

    -- Calculated Metrics
    revenue_cagr NUMERIC,           -- Compound annual growth rate
    revenue_growth_3yr NUMERIC,     -- (Year3 - Year1) / Year1 * 100
    revenue_growth_5yr NUMERIC,

    -- EBITDA Projections (if available)
    ebitda_year1 NUMERIC,
    ebitda_year3 NUMERIC,
    ebitda_year5 NUMERIC,

    -- Classification
    is_hockey_stick BOOLEAN,        -- CAGR > 50% or 3yr growth > 300%

    -- Source
    filing_url VARCHAR(500),
    filing_date DATE,
    extracted_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(ticker)
);
```

**Data Sourcing**:
- Source: Investor presentation (425 filing or EX-99.2 in 8-K)
- File Format: PDF or PowerPoint
- Extraction: AI-powered extraction from charts/tables
- Location: "Financial Projections" or "Revenue Forecast" section

**Detection Logic**:
```python
def is_hockey_stick(cagr, growth_3yr):
    """
    Hockey stick criteria:
    - CAGR > 50%, OR
    - 3-year growth > 300%
    """
    if cagr and cagr > 50:
        return True
    if growth_3yr and growth_3yr > 300:
        return True
    return False
```

**Action Required**:
- [ ] Create `deal_projections` table
- [ ] Build AI extraction for projections from investor deck
- [ ] Handle PDF/PPT parsing
- [ ] Calculate CAGR and growth metrics

**Script**: `extract_deal_projections.py`

**Challenges**:
- Projections may be in images/charts (requires OCR or chart extraction)
- Post-July 2024 SEC rules may affect disclosure format
- Need to handle disclaimers and adjusted projections

---

### 3. Redemption Data

#### 3a. Redemption Percentage

**What we need**: % of public shares redeemed at vote

**Current Database**:
- ✅ `shares_redeemed` (bigint) - EXISTS
- ✅ `redemption_percentage` (double precision) - EXISTS
- ✅ `redemption_amount` (double precision) - EXISTS
- ✅ `last_redemption_date` (date) - EXISTS

**Data Quality Check**:
```sql
SELECT COUNT(*) as total,
       COUNT(redemption_percentage) as has_redemption_pct,
       COUNT(shares_redeemed) as has_shares_redeemed
FROM spacs
WHERE deal_status IN ('ANNOUNCED', 'COMPLETED');
```

**Action Required**:
- [ ] Review data quality
- [ ] Ensure redemption_percentage is calculated correctly

**Sourcing**: ✅ Already in database (from post-vote 8-K extraction)

---

#### 3b. Post-Redemption Float

**What we need**: Calculate public float after redemptions

**Current Database**:
- ✅ `shares_outstanding` (double precision) - EXISTS
- ✅ `shares_redeemed` (bigint) - EXISTS
- ✅ `founder_shares` (double precision) - EXISTS
- ❌ **MISSING**: PIPE shares count

**Calculation**:
```python
def calculate_post_redemption_float(
    shares_outstanding,
    shares_redeemed,
    founder_shares,
    pipe_shares_issued
):
    """
    Public float = Total shares - Redeemed - Founder - PIPE (if locked)
    """
    public_float = (
        shares_outstanding
        - shares_redeemed
        - founder_shares
        - pipe_shares_issued  # Only if locked
    )
    return public_float
```

**NEW COLUMN NEEDED**:
```sql
ALTER TABLE spacs ADD COLUMN pipe_shares BIGINT;
ALTER TABLE spacs ADD COLUMN pipe_lockup_months INT;
ALTER TABLE spacs ADD COLUMN post_redemption_float BIGINT;
```

**Data Sourcing**:
- PIPE shares: Calculate from `pipe_size / pipe_price`
- PIPE lockup: Extract from PIPE subscription agreement
- Calculate automatically after redemption data available

**Action Required**:
- [ ] Add columns for PIPE shares and lockup
- [ ] Build calculation function
- [ ] Extract PIPE lockup terms from 8-K

---

#### 3c. PIPE Lockup Period

**What we need**: How long PIPE shares are locked (6-12 months ideal)

**Current Database**:
- ❌ **MISSING**: PIPE lockup period

**NEW COLUMN**: (see above - `pipe_lockup_months`)

**Data Sourcing**:
- Source: PIPE subscription agreement (8-K exhibit)
- Keywords: "lock-up", "lockup", "transfer restrictions"
- Typical language: "180 days from closing" or "6 months"

**Sample Language**:
> "Purchaser agrees not to transfer any Shares for a period of twelve (12) months
> following the Closing Date, except as permitted under Rule 144."

**Action Required**:
- [ ] Add `pipe_lockup_months` column
- [ ] Build extraction logic from PIPE agreements
- [ ] Backfill for existing deals

---

## Summary: Data Gaps and Action Plan

### ✅ HAVE (Already in Database)

**Phase 1**:
- Market cap (calculated)
- Sponsor name
- Sector
- Warrant ratio
- Sponsor promote (%)
- Price data

**Phase 2**:
- PIPE size
- Trust cash
- Redemption data (shares, percentage)
- Shares outstanding

### ❌ NEED (Missing from Database)

**Phase 1**:
1. Historical price data (for calculating sponsor "pop" performance)
2. Aggregated sponsor performance metrics
3. Promote vesting structure (performance-based vs time-based)

**Phase 2**:
1. PIPE investor names and tier classification
2. Revenue projections and hockey stick analysis
3. PIPE shares count
4. PIPE lockup period
5. Post-redemption float calculation

---

## New Database Objects Required

### Tables to Create:
1. `sponsor_performance` - Aggregated sponsor track record
2. `price_history` - Daily price tracking for pop calculations
3. `pipe_investors` - PIPE investor details
4. `deal_projections` - Revenue forecasts and hockey stick metrics
5. `opportunity_scores` - Phase 1 scores
6. `deal_catalysts` - Phase 2 scores
7. `opportunity_alerts` - Alert history

### Columns to Add to `spacs` table:
1. `promote_vesting_type` VARCHAR(50)
2. `promote_vesting_prices` NUMERIC[]
3. `pipe_percentage` NUMERIC
4. `pipe_shares` BIGINT
5. `pipe_lockup_months` INT
6. `post_redemption_float` BIGINT

---

## Data Extraction Scripts to Build

### Phase 1:
1. `backfill_price_history.py` - Fetch historical prices from Yahoo Finance
2. `calculate_sponsor_performance.py` - Aggregate sponsor metrics
3. `extract_promote_vesting.py` - Extract vesting terms from S-1

### Phase 2:
1. `extract_pipe_investors.py` - Parse PIPE investor lists from 8-K
2. `extract_deal_projections.py` - Extract projections from investor deck
3. `extract_pipe_lockup.py` - Parse lockup terms from PIPE agreements
4. `calculate_float.py` - Calculate post-redemption float

### Ongoing:
1. Update `price_updater.py` to log to `price_history`
2. Update SEC filing monitor to trigger new extraction agents

---

## Next Steps (Priority Order)

1. **Create database schema** (tables + columns)
2. **Build Phase 1 extraction scripts** (price history, sponsor performance)
3. **Test Phase 1 scoring** with current data
4. **Build Phase 2 extraction scripts** (PIPE investors, projections)
5. **Implement full scoring algorithm**
6. **Deploy and integrate with orchestrator**

---

**Status**: Data audit complete
**Estimated Work**: 4-6 hours for full implementation
**Priority**: High (foundational for opportunity agent)
