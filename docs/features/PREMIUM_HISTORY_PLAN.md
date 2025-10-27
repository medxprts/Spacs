# Historical Average Premium Chart - Implementation Plan

## Goal
Add a chart to the Streamlit dashboard showing the historical average premium for pre-deal SPACs, starting from the beginning of the year (2025).

## Problem
We currently only store the current price/premium for each SPAC, not historical snapshots.

## Solution: Two-Phase Approach

### Phase 1: Start Collecting Historical Data (Going Forward)
Create a new table to track daily snapshots of market averages.

**New Table: `market_snapshots`**
```sql
CREATE TABLE market_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL UNIQUE,
    avg_premium_predeal FLOAT,           -- Average premium for pre-deal SPACs
    median_premium_predeal FLOAT,        -- Median premium for pre-deal SPACs
    count_predeal INTEGER,               -- Number of pre-deal SPACs
    avg_premium_announced FLOAT,         -- Average premium for announced deals
    median_premium_announced FLOAT,      -- Median premium for announced deals
    count_announced INTEGER,             -- Number of announced deals
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_snapshot_date ON market_snapshots(snapshot_date);
```

**Daily Snapshot Script: `take_market_snapshot.py`**
- Run daily (via cron)
- Calculate average/median premium for pre-deal SPACs
- Calculate average/median premium for announced deals
- Store in `market_snapshots` table

### Phase 2: Display Historical Chart in Dashboard

**Streamlit Component:**
- Query `market_snapshots` table for date range (e.g., YTD 2025)
- Use Plotly or Altair to create line chart
- Show:
  - Average premium (primary line)
  - Median premium (secondary line)
  - Count of SPACs (on secondary y-axis)
- Add filters: date range, pre-deal vs announced

## Alternative: Backfill Historical Data

If we want historical data immediately, we could:
1. Use Yahoo Finance historical data for each SPAC ticker
2. Backfill daily prices from Jan 1, 2025
3. Calculate premium for each date
4. Aggregate into daily market averages

**Pros**: Immediate historical chart
**Cons**:
- Requires fetching 280+ days × 155+ SPACs = ~43,000+ API calls
- Yahoo Finance rate limits could be an issue
- More complex implementation

## Recommended Approach

**Start with Phase 1 only:**
1. Create `market_snapshots` table today
2. Add daily snapshot script to cron
3. Show chart with available data (will grow over time)
4. Add note: "Historical data collection started [date]"

**Benefits:**
- Simple implementation
- Reliable data going forward
- No rate limiting issues
- Can backfill later if needed

## Files to Create/Modify

### New Files:
1. `market_snapshot.py` - Daily snapshot collection script
2. `migrations/add_market_snapshots_table.py` - Database migration

### Modified Files:
1. `database.py` - Add MarketSnapshot model
2. `streamlit_app.py` - Add premium history chart section
3. `daily_spac_update.sh` - Add snapshot script to daily cron

## Implementation Steps

1. ✅ Create plan document (this file)
2. [ ] Add MarketSnapshot model to database.py
3. [ ] Create migration script to add table
4. [ ] Build market_snapshot.py script
5. [ ] Test snapshot collection
6. [ ] Add chart to Streamlit dashboard
7. [ ] Update daily_spac_update.sh to include snapshot
8. [ ] Deploy and monitor

## Chart Specifications

**Location in Dashboard:**
- New section at top of "Pre-Deal SPACs" tab
- Above the sortable table

**Chart Features:**
- **X-axis**: Date
- **Y-axis (left)**: Average Premium %
- **Y-axis (right)**: Number of SPACs
- **Lines**:
  - Primary: Average premium (bold blue line)
  - Secondary: Median premium (dashed gray line)
  - Tertiary: Count of SPACs (thin orange line, right axis)
- **Interactivity**: Hover to see exact values
- **Date Range Filter**: YTD, Last 30 days, Last 90 days, All time

**Example Visual:**
```
Average Premium % (Pre-Deal SPACs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  5% ┤     ╭─────╮
  4% ┤   ╭─╯     ╰╮         ╭─
  3% ┤ ╭─╯        ╰─╮     ╭─╯
  2% ┤─╯            ╰─────╯
  1% ┤
     └─────────────────────────
     Jan  Feb  Mar  Apr  May
```

## Success Metrics

- Chart displays correctly in dashboard
- Daily snapshots run automatically
- Data accuracy: spot-check against manual calculations
- Chart loads in < 2 seconds

## Future Enhancements

- Backfill historical data from Yahoo Finance
- Add confidence intervals / error bars
- Compare pre-deal vs announced premiums on same chart
- Add annotations for major market events
- Export chart data to CSV
