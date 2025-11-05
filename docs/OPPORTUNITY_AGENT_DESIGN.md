# Opportunity Identification Agent - Design Document

**Date**: 2025-11-04
**Purpose**: Build a screening model to identify SPACs with highest potential for massive short-term "pop"

---

## Strategy Overview

**Goal**: Not long-term stability - find SPACs with potential for explosive short-term gains driven by:
- Market hype
- "Story" narrative
- Technical factors (low float squeeze)

**Two-Phase Approach**:
1. **Phase 1**: Find "Loaded Guns" (pre-announcement filters)
2. **Phase 2**: Detect "Lit Fuse" (post-announcement catalysts)

---

## Phase 1: Pre-Announcement Filters (Finding "Loaded Guns")

**Goal**: Build initial portfolio of 5-10 "blank" SPACs to hold before deals announced

### Filter Criteria

#### 1. Market Cap: $100M - $500M
- **Why**: Sweet spot for retail/speculative interest
- **Implementation**: Calculate from `price * shares_outstanding`
- **Data Source**: Database columns `price`, `shares_outstanding`

#### 2. Sponsor Track Record
- **Metric**: Sponsors whose previous deals had >15% price spike after announcement
- **Implementation**:
  - Track all SPACs by sponsor
  - Measure price change in 7/14/30 days post-announcement
  - Calculate average "pop" per sponsor
- **Data Source**: Historical `price_history` table, `sponsor` column
- **Scoring**:
  - 0 points: No history or <5% avg pop
  - 5 points: 5-10% avg pop
  - 10 points: 10-15% avg pop
  - 15 points: >15% avg pop

#### 3. Target Industry (Hot Narrative Sectors)
- **Target Sectors**:
  - AI / Artificial Intelligence
  - Cybersecurity
  - Digital Assets / Crypto / Blockchain
  - Next-gen Energy (EV, batteries, renewable)
  - FinTech
  - Space Tech
  - BioTech (gene therapy, CRISPR)
- **Avoid**: Industrials, Consumer Goods, Traditional Retail
- **Data Source**: `target_sector` or `sector` column
- **Scoring**:
  - 0 points: Boring sectors
  - 10 points: Hot narrative sectors

#### 4. Investor-Friendly Structure

**4a. Low Warrant Dilution**
- **Preferred**: 1/5, 1/3, or 0 warrants per unit
- **Data Source**: `warrant_ratio` column (e.g., "1/3", "1/5", "0")
- **Scoring**:
  - 0 points: 1/1 or 1/2 warrants (high dilution)
  - 5 points: 1/3 warrants
  - 10 points: 1/4 or 1/5 warrants
  - 15 points: 0 warrants (no dilution)

**4b. Performance-Based Promote**
- **Preferred**: Sponsor shares vest at $15, $20, etc. (not just IPO close)
- **Data Source**: Extract from S-1 filing or `sponsor_promote` column
- **Scoring**:
  - 0 points: No vesting or standard vesting
  - 10 points: Performance-based vesting ($15+)

### Phase 1 Scoring Formula

```
LOADED_GUN_SCORE =
  market_cap_fit (0/10) +
  sponsor_track_record (0-15) +
  hot_narrative_sector (0/10) +
  low_warrant_dilution (0-15) +
  performance_promote (0/10)

MAX SCORE: 60 points

THRESHOLDS:
- 45-60: A-Tier "Loaded Gun" (top picks)
- 30-44: B-Tier (watchlist)
- <30: C-Tier (ignore)
```

---

## Phase 2: Post-Announcement Catalysts (The "Lit Fuse")

**Goal**: When a "loaded gun" SPAC announces a deal, scan for catalysts that predict explosive pop

### Catalyst Detection

#### 1. PIPE Analysis (CRITICAL - #1 Signal)

**1a. PIPE Size**
- **Metric**: PIPE as % of trust size
- **Target**: 50-100%+ of trust size
- **Data Source**: Extract from 8-K filing (Item 1.01 or exhibits)
- **Scoring**:
  - 0 points: No PIPE or <25%
  - 5 points: 25-50%
  - 10 points: 50-75%
  - 15 points: 75-100%
  - 20 points: >100% (mega PIPE)

**1b. PIPE Quality (Tier-1 Institutions)**
- **Target**: BlackRock, Fidelity, Vanguard, T. Rowe Price, Wellington, etc.
- **Data Source**: PIPE investor list from 8-K exhibits (EX-10.1, EX-10.2)
- **Scoring**:
  - 0 points: No tier-1 investors
  - 10 points: 1-2 tier-1 investors
  - 20 points: 3+ tier-1 investors

#### 2. "Hockey Stick" Projections

**Metric**: Wildly optimistic revenue/growth projections in investor presentation

**Detection**:
- Extract from 425 filing or investor deck (EX-99.2)
- Look for CAGR >50%, 3-5 year revenue growth >300%
- Charts with exponential curves

**Data Source**: Investor presentation PDF/PPT → AI extraction

**Scoring**:
- 0 points: Conservative or no projections
- 10 points: Moderate growth (20-50% CAGR)
- 20 points: Hockey stick (>50% CAGR, >300% growth)

#### 3. Low Float Squeeze Formula (THE MONEY MAKER)

**Formula**: High Redemptions + Strong PIPE = Tiny Float Squeeze

**3a. High Redemption Rate**
- **Metric**: % of public shares redeemed
- **Target**: 90-98% redemptions
- **Data Source**: 8-K filing post-vote (Item 8.01 or press release)
- **Calculation**: `redemption_percentage = (shares_redeemed / shares_outstanding_pre_vote) * 100`
- **Scoring**:
  - 0 points: <50% redemptions
  - 5 points: 50-70% redemptions
  - 10 points: 70-85% redemptions
  - 15 points: 85-95% redemptions
  - 25 points: >95% redemptions (EXTREME squeeze setup)

**3b. Post-Redemption Float**
- **Metric**: Shares remaining in public float
- **Target**: <5M shares (tiny float)
- **Calculation**: `public_float = shares_outstanding - shares_redeemed - sponsor_shares - PIPE_shares_locked`
- **Scoring**:
  - 0 points: >20M shares
  - 10 points: 10-20M shares
  - 20 points: 5-10M shares
  - 30 points: <5M shares (EXTREME squeeze potential)

**3c. PIPE Lockup Period**
- **Metric**: How long PIPE shares are locked
- **Target**: 6-12 months (keeps supply tight)
- **Data Source**: PIPE subscription agreement
- **Scoring**:
  - 0 points: No lockup or <3 months
  - 5 points: 3-6 months
  - 10 points: 6-12 months
  - 15 points: >12 months

### Phase 2 Scoring Formula

```
LIT_FUSE_SCORE =
  pipe_size (0-20) +
  pipe_quality (0-20) +
  hockey_stick_projections (0-20) +
  high_redemptions (0-25) +
  tiny_float (0-30) +
  pipe_lockup (0-15)

MAX SCORE: 130 points

THRESHOLDS:
- 100-130: EXTREME SQUEEZE SETUP (ALL IN SIGNAL)
- 70-99: Strong Catalyst (Buy signal)
- 40-69: Moderate Interest (Watchlist)
- <40: Weak Catalyst (Pass)
```

---

## Combined Opportunity Score

```
TOTAL_OPPORTUNITY_SCORE = LOADED_GUN_SCORE + LIT_FUSE_SCORE

MAX SCORE: 190 points

ALERT THRESHOLDS:
- 150-190: 🔥 EXTREME OPPORTUNITY (Immediate Telegram alert)
- 100-149: 🎯 STRONG OPPORTUNITY (Daily alert)
- 70-99: ⚠️  MODERATE OPPORTUNITY (Weekly watchlist)
- <70: ❌ PASS
```

---

## Database Schema

### New Tables

#### 1. `opportunity_scores` (Phase 1 scores)
```sql
CREATE TABLE opportunity_scores (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker),

    -- Phase 1 Scores
    market_cap_score INT,
    sponsor_score INT,
    sector_score INT,
    warrant_dilution_score INT,
    promote_score INT,
    loaded_gun_score INT,  -- Sum of Phase 1

    -- Metadata
    market_cap NUMERIC,
    sponsor_avg_pop NUMERIC,  -- Average % pop from sponsor's previous deals
    warrant_ratio VARCHAR(10),
    has_performance_promote BOOLEAN,

    last_updated TIMESTAMP DEFAULT NOW(),

    UNIQUE(ticker)
);
```

#### 2. `deal_catalysts` (Phase 2 catalysts)
```sql
CREATE TABLE deal_catalysts (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker),

    -- PIPE Data
    pipe_size_millions NUMERIC,
    pipe_percentage NUMERIC,  -- % of trust
    pipe_investors TEXT[],  -- Array of investor names
    tier1_investor_count INT,

    -- Projections
    has_hockey_stick BOOLEAN,
    revenue_cagr NUMERIC,
    revenue_growth_3yr NUMERIC,

    -- Redemptions
    redemption_percentage NUMERIC,
    shares_redeemed BIGINT,
    post_redemption_float BIGINT,
    pipe_lockup_months INT,

    -- Phase 2 Scores
    pipe_size_score INT,
    pipe_quality_score INT,
    projection_score INT,
    redemption_score INT,
    float_score INT,
    lockup_score INT,
    lit_fuse_score INT,  -- Sum of Phase 2

    -- Metadata
    detected_date DATE,
    catalyst_filing_url VARCHAR(500),

    UNIQUE(ticker)
);
```

#### 3. `sponsor_performance` (Historical track record)
```sql
CREATE TABLE sponsor_performance (
    id SERIAL PRIMARY KEY,
    sponsor_name VARCHAR(255) UNIQUE,

    -- Performance Metrics
    total_deals INT,
    completed_deals INT,
    avg_announcement_pop NUMERIC,  -- Avg % pop in 30 days post-announcement
    max_announcement_pop NUMERIC,  -- Best performing deal

    -- Deal History
    deal_tickers TEXT[],  -- List of SPAC tickers

    last_updated TIMESTAMP DEFAULT NOW()
);
```

#### 4. `opportunity_alerts` (Alert history)
```sql
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
```

---

## Agent Implementation

### File Structure
```
agents/
  opportunity_agent.py           # Main agent (orchestrator-compatible)
  opportunity_filters.py         # Phase 1 filter logic
  opportunity_catalysts.py       # Phase 2 catalyst detection
  opportunity_scorer.py          # Scoring algorithms

utils/
  sponsor_tracker.py             # Track sponsor performance history
  pipe_extractor.py              # Extract PIPE data from 8-K
  projection_analyzer.py         # Analyze revenue projections
  float_calculator.py            # Calculate post-redemption float
```

### Agent Workflow

#### Daily Task (Phase 1 Screening)
1. Query all SPACs with `deal_status='SEARCHING'`
2. Calculate market cap
3. Score each SPAC using Phase 1 filters
4. Update `opportunity_scores` table
5. Send Telegram alerts for new A-Tier "loaded guns"

#### Event-Driven Task (Phase 2 Detection)
Triggered when:
- Deal announcement detected (8-K Item 1.01)
- PIPE filing detected
- Shareholder vote results published

Workflow:
1. Extract PIPE data from 8-K exhibits
2. Extract projections from investor deck
3. Wait for redemption data (post-vote 8-K)
4. Calculate Phase 2 scores
5. Update `deal_catalysts` table
6. Calculate combined score
7. Send EXTREME/STRONG opportunity alerts

---

## Alert Templates

### Phase 1: New "Loaded Gun" Alert
```
🔫 NEW LOADED GUN DETECTED

Ticker: $BLUW
Score: 48/60 (A-Tier)

✅ Market Cap: $275M
✅ Sponsor: Acme Partners (avg 18% pop)
✅ Sector: AI / Machine Learning
✅ Warrants: 1/5 (low dilution)
✅ Promote: Performance-based ($15 vesting)

Strategy: BUY PRE-ANNOUNCEMENT
Hold until deal announced, watch for "lit fuse"
```

### Phase 2: "Lit Fuse" Alert
```
🔥🔥🔥 EXTREME SQUEEZE SETUP 🔥🔥🔥

Ticker: $BLUW → $NEWCO
Combined Score: 165/190

LOADED GUN (Pre-Deal):
✅ Score: 48/60
✅ Hot narrative (AI sector)
✅ Strong sponsor track record

LIT FUSE (Post-Deal):
🚀 PIPE: $200M (87% of trust) - Tier 1
   Investors: BlackRock, Fidelity, T. Rowe
🚀 Redemptions: 94% (EXTREME)
🚀 Float: 3.2M shares (TINY)
🚀 PIPE Lockup: 12 months
🚀 Projections: 65% CAGR (hockey stick)

TRADE SETUP:
- Tiny float (3.2M shares)
- High speculative demand (AI hype)
- Smart money validation (Tier 1 PIPE)
- Perfect squeeze conditions

RISK: High volatility, momentum-driven
```

---

## Next Steps

1. ✅ Create database tables
2. Build Phase 1 filters (opportunity_filters.py)
3. Build Phase 2 catalyst detection (opportunity_catalysts.py)
4. Build scoring algorithm (opportunity_scorer.py)
5. Create main agent (opportunity_agent.py)
6. Integrate with orchestrator
7. Test on historical data (backtest)
8. Deploy and monitor

---

**Status**: Design Complete
**Ready for**: Implementation
