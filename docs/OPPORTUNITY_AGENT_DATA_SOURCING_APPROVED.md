# Opportunity Agent - Approved Data Sourcing Plan

**Date**: 2025-11-05
**Status**: All sourcing methods approved by user

---

## Phase 1: Pre-Announcement Filters ("Loaded Gun")

### 1. Market Cap ($100M - $500M)
**Status**: ✅ Already Have
- **Source**: Database columns `price` × `shares_outstanding`
- **Calculation**: `market_cap = price * shares_outstanding`
- **No extraction needed**

### 2. Sponsor Track Record (>15% avg pop)
**Status**: ❌ Missing - Need to Build
- **Approved Method**: Option B - Systematic extraction from SEC EDGAR + our database
- **Execution Plan**:
  1. Query our database for all SPACs by sponsor (we have 185 SPACs, 66 announced deals)
  2. Normalize sponsor names (strip Roman numerals: "Klein II" → "Klein")
  3. For each announced deal, fetch historical prices from Yahoo Finance (30 days post-announcement)
  4. Calculate sponsor performance: `avg_pop = mean((price_day_X - price_announcement) / price_announcement * 100)`
  5. Store in new `sponsor_performance` table

- **Database Changes**:
  ```sql
  -- Add normalized sponsor column
  ALTER TABLE spacs ADD COLUMN sponsor_normalized VARCHAR(255);

  -- New table for sponsor performance
  CREATE TABLE sponsor_performance (
      sponsor_name VARCHAR(255) UNIQUE,
      total_deals INT,
      avg_7day_pop NUMERIC,
      avg_14day_pop NUMERIC,
      avg_30day_pop NUMERIC,
      max_pop NUMERIC,
      last_updated TIMESTAMP DEFAULT NOW()
  );

  -- New table for historical price tracking
  CREATE TABLE price_history_extended (
      ticker VARCHAR(10),
      date DATE,
      price NUMERIC,
      volume BIGINT,
      days_since_announcement INT,
      UNIQUE(ticker, date)
  );
  ```

- **Storage**: 66 deals × 30 days = 1,980 rows (~60KB)
- **Time to backfill**: ~33 seconds (Yahoo Finance API)

### 3. Target Sector (Hot vs Boring)
**Status**: ✅ Built - sector_classifier.py
- **Primary Source**: 424B4 (final prospectus at IPO)
- **Fallback**: S-1 (registration statement)
- **Validation Source** (post-deal only): 8-K Item 1.01 actual target sector
  - Used for learning/improvement, NOT for filtering

- **Multi-Source Priority**:
  1. **424B4** (IPO closing - most detailed) ← Ground truth for filtering
  2. **S-1** (IPO registration) ← Fallback
  3. **8-K Item 1.01** (deal announcement) ← Validation only (too late for filtering)

- **Hot Sectors** (10 points each):
  - AI / Machine Learning
  - Cybersecurity
  - Digital Assets / Crypto / Blockchain
  - Next-Gen Energy (EV, Battery, Renewable)
  - FinTech
  - Space / Aerospace
  - BioTech / Gene Therapy

- **Boring Sectors** (0 points):
  - Industrials / Manufacturing
  - Consumer Goods / Retail
  - Real Estate
  - Traditional Finance

- **Database Columns** (already added):
  ```sql
  ALTER TABLE spacs ADD COLUMN sector_classified VARCHAR(50);
  ALTER TABLE spacs ADD COLUMN sector_confidence INT;
  ALTER TABLE spacs ADD COLUMN is_hot_sector BOOLEAN DEFAULT FALSE;
  ```

### 4. Warrant Dilution + Rights (Low dilution preferred)
**Status**: ✅ Already Have Data
- **Source**: Database columns `warrant_ratio`, `right_ticker`, `unit_structure`
- **Calculation**:
  ```python
  total_dilution = warrant_ratio + parse_rights_from_unit_structure(unit_structure)

  # Scoring (lower dilution = higher score)
  if total_dilution == 0:
      score = 15  # NO dilution
  elif total_dilution <= 0.2:
      score = 10  # e.g., 1/5 warrant only
  elif total_dilution <= 0.33:
      score = 5   # e.g., 1/3 warrant only
  else:
      score = 0   # High dilution
  ```

- **No extraction needed** - data exists

### 5. Performance-Based Promote
**Status**: ❌ Missing - Need to Extract
- **Approved Source**: 424B4 (ground truth)
- **Fallback**: S-1
- **Section to Extract**: "Founder Shares" or "Sponsor Promote" or "Earnout Provisions"
- **Keywords**: "vest", "vesting", "performance-based", "price thresholds"

- **Examples**:
  - ❌ Standard: "Founder shares vest upon closing" → 0 points
  - ✅ Performance: "25% vest at $12.00, 25% at $15.00" → 10 points

- **Database Changes**:
  ```sql
  ALTER TABLE spacs ADD COLUMN promote_vesting_type VARCHAR(50);  -- 'standard' | 'performance'
  ALTER TABLE spacs ADD COLUMN promote_vesting_prices NUMERIC[];  -- [12.00, 15.00, 18.00]
  ```

---

## Phase 2: Post-Announcement Catalysts ("Lit Fuse")

**IMPORTANT**: All Phase 2 data must be available AT ANNOUNCEMENT (not post-vote)
- We're trading the announcement pop, not post-vote squeeze
- Redemption data removed from Phase 2 (happens 2-3 months after announcement)

### 6. PIPE Size (50-100%+ of trust)
**Status**: ⚠️ 24% Populated - Need Better Extraction
- **Primary Source**: 8-K EX-99.1 (press release)
- **Fallback 1**: 8-K EX-10.1/EX-10.2 (PIPE subscription agreements) ← Sum individual investors
- **Fallback 2**: 8-K EX-2.1 (business combination agreement)
- **Fallback 3**: DEFM14A (proxy statement) - too late but good for validation

- **Extraction**: AI-powered from exhibits
- **Test Results**: ✅ Fallback structure works (tested on DYNX)

- **Calculation**:
  ```python
  pipe_percentage = (pipe_size / trust_cash) * 100

  # Scoring
  if pipe_pct > 100:
      score = 20  # MEGA PIPE
  elif pipe_pct >= 75:
      score = 15  # Large PIPE
  elif pipe_pct >= 50:
      score = 10  # Solid PIPE
  elif pipe_pct >= 25:
      score = 5   # Small PIPE
  else:
      score = 0
  ```

### 7. PIPE Investors (Tier-1 Institutions)
**Status**: ❌ Missing - Need to Build
- **Source**: 8-K EX-10.1/EX-10.2 (PIPE subscription agreements)
- **Secondary**: 8-K EX-99.1 (press release) - may mention "led by BlackRock"

- **Tier-1 Institutions**:
  - BlackRock, Vanguard, Fidelity, State Street
  - T. Rowe Price, Capital Group, Wellington
  - Morgan Stanley, Goldman Sachs, JPMorgan

- **Database Changes**:
  ```sql
  CREATE TABLE pipe_investors (
      ticker VARCHAR(10) REFERENCES spacs(ticker),
      investor_name VARCHAR(255),
      investment_amount NUMERIC,
      is_tier1 BOOLEAN DEFAULT FALSE,
      UNIQUE(ticker, investor_name)
  );
  ```

- **Scoring**:
  ```python
  tier1_count = count(investors where is_tier1 = True)

  if tier1_count >= 3:
      score = 20  # Multiple Tier-1 investors
  elif tier1_count >= 1:
      score = 10  # 1-2 Tier-1 investors
  else:
      score = 0   # No Tier-1 validation
  ```

### 8. Revenue Projections ("Hockey Stick")
**Status**: ❌ 0% Populated - Need to Extract
- **Source**: Investor Presentation (DEFA14A or 425 filing, EX-99.2)
- **Format**: Usually PDF/PPT investor deck
- **Extraction**: AI-powered (DeepSeek can read PDF text)

- **What to Extract**:
  - Revenue Year 1, Year 2, Year 3
  - EBITDA Year 1, Year 2, Year 3
  - Calculate CAGR: `((Y3_revenue / Y1_revenue) ^ (1/3) - 1) * 100`

- **Scoring**:
  ```python
  if cagr > 50:
      score = 20  # Hockey stick (hype factor)
  elif cagr >= 20:
      score = 10  # Moderate growth
  else:
      score = 0   # Conservative
  ```

- **Database Columns** (already exist, need to populate):
  - `projected_revenue_y1`, `projected_revenue_y2`, `projected_revenue_y3`
  - `projected_ebitda_y1`, `projected_ebitda_y2`, `projected_ebitda_y3`
  - `revenue_growth_rate` (CAGR)

### 9. PIPE Lockup Period
**Status**: ❌ Missing - Need to Extract
- **Source**: 8-K EX-10.1/EX-10.2 (PIPE subscription agreements)
- **Section**: "Lock-Up Agreement" or "Transfer Restrictions"
- **Keywords**: "6-month lock-up", "locked for 12 months"

- **Database Changes**:
  ```sql
  ALTER TABLE spacs ADD COLUMN pipe_lockup_months INT;
  ```

- **Scoring**:
  ```python
  if lockup_months >= 12:
      score = 15  # Long lockup (tight supply)
  elif lockup_months >= 6:
      score = 10  # Medium lockup
  elif lockup_months >= 3:
      score = 5   # Short lockup
  else:
      score = 0   # No lockup
  ```

### 10. Volume as % of Float (Announcement Day)
**Status**: ✅ Have Data - Need to Capture at Announcement
- **Measurement Window**: **Announcement day only** (Option C)
  - Future enhancement: 3-day rolling sum

- **Source**: Yahoo Finance API (yfinance)
- **Timing**: Fetch volume for announcement date when deal detected

- **Float Calculation**:
  ```python
  founder_shares = founder_shares or (shares_outstanding * 0.20)  # Fallback
  public_float = shares_outstanding - founder_shares - private_placement_units

  volume_pct_of_float = (volume_on_announcement_day / public_float) * 100
  ```

- **Scoring**:
  ```python
  if volume_pct_of_float >= 20:
      score = 15  # EXTREME turnover
  elif volume_pct_of_float >= 10:
      score = 12  # Very high turnover
  elif volume_pct_of_float >= 5:
      score = 8   # High turnover
  elif volume_pct_of_float >= 2:
      score = 4   # Moderate turnover
  else:
      score = 0   # Low turnover
  ```

- **Database Changes**:
  ```sql
  ALTER TABLE spacs ADD COLUMN public_float BIGINT;
  ALTER TABLE spacs ADD COLUMN volume_on_announcement_day BIGINT;
  ALTER TABLE spacs ADD COLUMN volume_pct_of_float NUMERIC;
  ```

- **Why this matters**:
  - Normal SPAC: 1-3% float turnover
  - Hot deal: 5-10% (strong demand)
  - Extreme: 10-20%+ (massive participation = potential for acceleration)

---

## Revised Scoring System

### Phase 1: "Loaded Gun" (Pre-Announcement)
```
LOADED_GUN_SCORE =
  market_cap_fit (0/10) +
  sponsor_track_record (0-15) +
  hot_narrative_sector (0/10) +
  low_dilution (warrants+rights) (0-15) +
  performance_promote (0/10)

MAX SCORE: 60 points

THRESHOLDS:
- 45-60: A-Tier "Loaded Gun" (top picks)
- 30-44: B-Tier (watchlist)
- <30: C-Tier (ignore)
```

### Phase 2: "Lit Fuse" (Post-Announcement)
```
LIT_FUSE_SCORE =
  pipe_size (0-20) +
  pipe_quality (tier-1 investors) (0-20) +
  hockey_stick_projections (0-20) +
  pipe_lockup (0-15) +
  volume_pct_of_float (0-15)

MAX SCORE: 90 points

THRESHOLDS:
- 70-90: EXTREME catalyst (immediate alert)
- 50-69: Strong catalyst (daily alert)
- 30-49: Moderate catalyst (watchlist)
```

### Combined Opportunity Score
```
TOTAL_OPPORTUNITY_SCORE = LOADED_GUN_SCORE + LIT_FUSE_SCORE

MAX SCORE: 150 points

ALERT THRESHOLDS:
- 120-150: 🔥 EXTREME OPPORTUNITY (Immediate Telegram alert)
- 90-119: 🎯 STRONG OPPORTUNITY (Daily alert)
- 70-89: ⚠️ MODERATE OPPORTUNITY (Weekly watchlist)
- <70: ❌ PASS
```

---

## Integration with Existing Agent Architecture

### Existing Agents (Already Built)
1. **deal_detector_agent.py**
   - Detects 8-K Item 1.01 filings
   - Updates: `deal_status='ANNOUNCED'`, `target`, `announced_date`

### New Agents to Build

2. **pipe_extractor_agent.py** (Phase 2)
   - **Trigger**: When `deal_status` changes to 'ANNOUNCED'
   - **Process**:
     - Fetch 8-K exhibits (EX-99.1, EX-10.1, EX-10.2)
     - Extract PIPE size (with fallback hierarchy)
     - Extract PIPE investor names
     - Extract PIPE lockup period
   - **Updates**: `pipe_size`, `pipe_percentage`, `pipe_investors` table, `pipe_lockup_months`

3. **projection_extractor_agent.py** (Phase 2)
   - **Trigger**: When DEFA14A/425 filed (investor deck)
   - **Process**:
     - Fetch EX-99.2 (investor presentation PDF)
     - AI extraction of revenue/EBITDA projections
     - Calculate CAGR (hockey stick detection)
   - **Updates**: `projected_revenue_y1/y2/y3`, `revenue_growth_rate`

4. **volume_tracker_agent.py** (Phase 2)
   - **Trigger**: When `deal_status` changes to 'ANNOUNCED'
   - **Process**:
     - Fetch volume for announcement date from Yahoo Finance
     - Calculate public float
     - Calculate volume as % of float
   - **Updates**: `volume_on_announcement_day`, `public_float`, `volume_pct_of_float`

5. **sponsor_performance_builder.py** (Phase 1 - One-time backfill)
   - **Run**: One-time script + monthly updates
   - **Process**:
     - Normalize all sponsor names
     - Fetch historical prices for announced deals
     - Calculate avg pop at 7, 14, 30 days
   - **Updates**: `sponsor_normalized`, `sponsor_performance` table

6. **opportunity_scorer_agent.py** (Scoring Engine)
   - **Trigger**: After Phase 1 or Phase 2 data updates
   - **Process**:
     - Calculate Phase 1 score (for SEARCHING SPACs)
     - Calculate Phase 2 score (for ANNOUNCED SPACs)
     - Calculate combined score
     - Send Telegram alerts for high scores
   - **Updates**: `opportunity_scores` table, `opportunity_alerts` table

### Agent Orchestrator Flow
```
Pre-Deal (SEARCHING SPACs):
  Daily: opportunity_scorer_agent (Phase 1 only)
      → Calculate loaded_gun_score
      → Alert on new A-Tier SPACs

Deal Announced:
  8-K Item 1.01 detected → deal_detector_agent
                        ↓
        deal_status='ANNOUNCED' → pipe_extractor_agent (Phase 2)
                                → volume_tracker_agent (Phase 2)
                        ↓
     DEFA14A/425 detected → projection_extractor_agent (Phase 2)
                        ↓
         Phase 2 data complete → opportunity_scorer_agent
                              → Calculate lit_fuse_score
                              → Calculate total_score
                              → Send EXTREME/STRONG alerts
```

---

## Database Schema Summary

### New Tables
```sql
-- Sponsor historical performance
CREATE TABLE sponsor_performance (
    id SERIAL PRIMARY KEY,
    sponsor_name VARCHAR(255) UNIQUE,
    total_deals INT,
    avg_7day_pop NUMERIC,
    avg_14day_pop NUMERIC,
    avg_30day_pop NUMERIC,
    max_pop NUMERIC,
    last_updated TIMESTAMP DEFAULT NOW()
);

-- PIPE investor details
CREATE TABLE pipe_investors (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker),
    investor_name VARCHAR(255),
    investment_amount NUMERIC,
    is_tier1 BOOLEAN DEFAULT FALSE,
    UNIQUE(ticker, investor_name)
);

-- Opportunity scores
CREATE TABLE opportunity_scores (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker),

    -- Phase 1 Scores
    market_cap_score INT,
    sponsor_score INT,
    sector_score INT,
    dilution_score INT,
    promote_score INT,
    loaded_gun_score INT,

    -- Phase 2 Scores
    pipe_size_score INT,
    pipe_quality_score INT,
    projection_score INT,
    lockup_score INT,
    volume_score INT,
    lit_fuse_score INT,

    -- Combined
    total_score INT,

    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(ticker)
);

-- Alert history
CREATE TABLE opportunity_alerts (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker),
    alert_type VARCHAR(50),  -- 'EXTREME', 'STRONG', 'MODERATE'
    total_score INT,
    loaded_gun_score INT,
    lit_fuse_score INT,
    alert_message TEXT,
    sent_via_telegram BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Extended price history (for sponsor performance)
CREATE TABLE price_history_extended (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10),
    date DATE,
    price NUMERIC,
    volume BIGINT,
    days_since_announcement INT,
    UNIQUE(ticker, date)
);
```

### New Columns for spacs Table
```sql
-- Phase 1
ALTER TABLE spacs ADD COLUMN sponsor_normalized VARCHAR(255);
ALTER TABLE spacs ADD COLUMN promote_vesting_type VARCHAR(50);
ALTER TABLE spacs ADD COLUMN promote_vesting_prices NUMERIC[];

-- Phase 2
ALTER TABLE spacs ADD COLUMN pipe_lockup_months INT;
ALTER TABLE spacs ADD COLUMN public_float BIGINT;
ALTER TABLE spacs ADD COLUMN volume_on_announcement_day BIGINT;
ALTER TABLE spacs ADD COLUMN volume_pct_of_float NUMERIC;
```

---

## Next Steps (In Order)

1. ✅ **Data Audit Complete**
2. ✅ **Data Sourcing Approved**
3. ⏳ **Create Database Schema** (5 new tables, 6 new columns)
4. ⏳ **Build Extraction Scripts**:
   - sponsor_performance_builder.py
   - pipe_extractor_agent.py
   - projection_extractor_agent.py
   - volume_tracker_agent.py
5. ⏳ **Build Scoring Engine**:
   - opportunity_scorer_agent.py
6. ⏳ **Integrate with Orchestrator**
7. ⏳ **Test on Historical Data** (backtest)
8. ⏳ **Deploy and Monitor**

---

**Status**: All data sourcing methods approved. Ready to proceed with database schema design.
