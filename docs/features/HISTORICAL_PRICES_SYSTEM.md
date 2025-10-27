# Historical Prices System - Complete Documentation

**End-of-day historical pricing for all SPAC securities since January 1, 2025**

---

## Overview

The historical prices system tracks daily end-of-day prices for all SPAC securities:
- **Common stock** (main ticker, e.g., RTAC)
- **Warrants** (e.g., RTACW)
- **Units** (e.g., RTACU) - Trade from IPO before separation
- **Rights** (e.g., RTAC.R) - Some SPACs issue rights

**Database:** `historical_prices` table
**Start Date:** January 1, 2025
**Update Frequency:** Daily at market close (4:00 PM ET)

---

## Database Schema

### Table: `historical_prices`

```sql
CREATE TABLE historical_prices (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,           -- Main SPAC ticker
    date DATE NOT NULL,                     -- Trading date
    price FLOAT,                            -- Common stock price
    warrant_price FLOAT,                    -- Warrant price (if separated)
    unit_price FLOAT,                       -- Unit price (trades before separation)
    rights_price FLOAT,                     -- Rights price (if issued)
    trust_value FLOAT,                      -- Trust value at this date
    premium FLOAT,                          -- Premium % = (price - trust) / trust * 100
    volume BIGINT,                          -- Trading volume
    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(ticker, date)                    -- One record per ticker per day
);

-- Indexes for fast lookups
CREATE INDEX idx_historical_prices_ticker ON historical_prices(ticker);
CREATE INDEX idx_historical_prices_date ON historical_prices(date);
CREATE INDEX idx_historical_prices_ticker_date ON historical_prices(ticker, date);
```

---

## Key Concepts

### Unit vs. Common/Warrant Trading

**IPO Structure:**
1. **Units trade first** after IPO (e.g., RTACU)
   - Contain: 1 common share + fraction of warrant (e.g., 1/3 warrant)
   - Trades as a bundle

2. **Separation** happens 52 days after IPO
   - Units split into common and warrants
   - Common trades separately (RTAC)
   - Warrants trade separately (RTACW)
   - Units may continue trading

**Example Timeline:**
- Day 1 (IPO): Only units trade (RTACU)
- Day 52: Separation - common (RTAC) and warrants (RTACW) start trading
- Day 53+: All three may trade (RTACU, RTAC, RTACW)

### Rights

- Some SPACs issue **rights** (e.g., RTAC.R)
- Allow holders to purchase additional shares at specific price
- Trade separately like warrants
- Not all SPACs have rights

---

## Backfill Process

### Initial Backfill (Jan 1, 2025 → Present)

**Script:** `backfill_historical_prices.py`

**What it does:**
1. Fetches historical prices from Yahoo Finance for all SPACs
2. Fetches common, warrant, unit, and rights prices (if they exist)
3. Stores in `historical_prices` table
4. Calculates premium for each day

**Usage:**
```bash
# Backfill all SPACs from Jan 1, 2025 to present
python3 backfill_historical_prices.py --start-date 2025-01-01

# Backfill single SPAC
python3 backfill_historical_prices.py --ticker RTAC --start-date 2025-01-01

# Custom date range
python3 backfill_historical_prices.py --start-date 2025-01-01 --end-date 2025-06-30
```

**Performance:**
- Rate limiting: 0.5 sec per SPAC (Yahoo Finance safe limit)
- Time estimate: ~2-3 minutes for all 185 SPACs
- Records created: ~21,000+ (163 SPACs × ~130 days average)

**Output Example:**
```
[1/185]
📊 RTAC: Fetching historical prices...
   ✅ Common: 85 days
   📊 Fetching warrant prices (RTACW)...
   ✅ Warrants: 85 days
   📊 Fetching unit prices (RTACU)...
   ✅ Units: 100 days
   📊 Fetching rights prices (RTAC.R)...
   ⚠️  Rights: No data (may not trade separately)
   📊 Total: 270 price records

================================================================================
BACKFILL COMPLETE
================================================================================
✅ Success: 163 SPACs
❌ Errors: 22 SPACs (delisted or IPO'd after Jan 1)
📊 Total prices inserted: 21,020
```

---

## Daily Updates

### Real-Time Price Monitor Integration

The `realtime_price_monitor.py` now logs end-of-day prices automatically:

**Process:**
1. Monitor runs every 30 seconds during market hours
2. Database updated in real-time
3. At **4:00 PM ET (market close):**
   - Captures final prices for the day
   - Writes summary to `logs/eod_prices.log`
   - **TODO:** Also insert into `historical_prices` table

### Future Enhancement: Auto-Insert

**Planned Feature:**
```python
def insert_todays_prices():
    """Insert today's EOD prices into historical_prices table"""
    db = SessionLocal()

    spacs = db.query(SPAC).all()

    for spac in spacs:
        insert_historical_price(
            db,
            spac.ticker,
            date.today(),
            spac.price,
            spac.volume,
            spac.trust_value
        )

        # Also insert warrant/unit/rights prices
        # ...

    db.commit()
```

**Add to `realtime_price_monitor.py` at market close**

---

## Querying Historical Data

### Example Queries

**1. Get price history for one SPAC:**
```sql
SELECT date, price, warrant_price, unit_price, premium
FROM historical_prices
WHERE ticker = 'RTAC'
ORDER BY date DESC
LIMIT 30;
```

**2. Get all SPACs on a specific date:**
```sql
SELECT ticker, price, premium
FROM historical_prices
WHERE date = '2025-09-30'
ORDER BY premium DESC;
```

**3. Calculate price change over time:**
```sql
SELECT
    ticker,
    MIN(price) as min_price,
    MAX(price) as max_price,
    AVG(price) as avg_price,
    (MAX(price) - MIN(price)) / MIN(price) * 100 as price_change_pct
FROM historical_prices
WHERE date >= '2025-01-01'
GROUP BY ticker
ORDER BY price_change_pct DESC
LIMIT 20;
```

**4. Find SPACs trading above $11 for 30+ days:**
```sql
SELECT ticker, COUNT(*) as days_above_11
FROM historical_prices
WHERE price > 11
GROUP BY ticker
HAVING COUNT(*) >= 30
ORDER BY days_above_11 DESC;
```

**5. Premium trend analysis:**
```sql
SELECT
    ticker,
    date,
    premium,
    AVG(premium) OVER (
        PARTITION BY ticker
        ORDER BY date
        ROWS BETWEEN 7 PRECEDING AND CURRENT ROW
    ) as premium_7d_avg
FROM historical_prices
WHERE ticker = 'RTAC'
ORDER BY date DESC;
```

---

## Python Usage

### Fetching Historical Data

```python
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# Get price history for RTAC
query = text("""
    SELECT date, price, warrant_price, unit_price, premium
    FROM historical_prices
    WHERE ticker = :ticker
    ORDER BY date DESC
    LIMIT 90
""")

result = db.execute(query, {'ticker': 'RTAC'})
history = result.fetchall()

for row in history:
    print(f"{row.date}: ${row.price:.2f} (Premium: {row.premium:.2f}%)")
```

### Generating Charts

```python
import pandas as pd
import matplotlib.pyplot as plt

# Fetch data
query = """
    SELECT date, price, premium
    FROM historical_prices
    WHERE ticker = 'RTAC'
    ORDER BY date
"""

df = pd.read_sql(query, db.connection())

# Plot price and premium
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

ax1.plot(df['date'], df['price'])
ax1.set_title('RTAC Price History')
ax1.set_ylabel('Price ($)')

ax2.plot(df['date'], df['premium'])
ax2.set_title('RTAC Premium History')
ax2.set_ylabel('Premium (%)')
ax2.axhline(y=0, color='r', linestyle='--')

plt.tight_layout()
plt.savefig('rtac_history.png')
```

---

## Storage Impact

### Current Size (After Backfill)

**Records:** ~21,020 historical prices (as of Oct 9, 2025)

**Database size:**
```sql
SELECT pg_size_pretty(pg_total_relation_size('historical_prices'));
-- Result: ~3 MB
```

### Annual Growth Projection

**Assumptions:**
- 163 active SPACs (some delist, new ones IPO)
- 252 trading days per year
- 4 price types per SPAC (common, warrant, unit, rights)

**Total records per year:**
- 163 SPACs × 252 days = 41,076 records/year
- With warrant/unit/rights: ~41,076 (stored in same row)

**Storage:**
- Current: ~3 MB (for 283 days)
- Full year: ~4-5 MB/year
- 5 years: ~20-25 MB (minimal!)

---

## Maintenance

### Log Rotation

Historical price logs are minimal:
- `logs/eod_prices.log` - Daily summaries only
- Size: ~20 KB/day = ~7 MB/year
- Rotation: Every 6 months

```bash
# Add to cron
0 0 1 */6 * find ~/spac-research/logs -name "eod_prices.log" -mtime +180 -delete
```

### Database Vacuum

PostgreSQL automatically manages space:
```sql
-- Check table bloat
SELECT pg_size_pretty(pg_total_relation_size('historical_prices'));

-- Manual vacuum (if needed)
VACUUM ANALYZE historical_prices;
```

---

## Future Enhancements

### 1. Intraday Price Tracking

**Current:** End-of-day only
**Future:** Track high/low/open/close

```sql
ALTER TABLE historical_prices
ADD COLUMN open_price FLOAT,
ADD COLUMN high_price FLOAT,
ADD COLUMN low_price FLOAT;
```

### 2. Dividend/Distribution Tracking

Track special dividends or distributions:
```sql
ALTER TABLE historical_prices
ADD COLUMN dividend FLOAT,
ADD COLUMN distribution_type VARCHAR(50);
```

### 3. Historical Trust Value Tracking

**Current:** Uses current trust_value for all dates
**Future:** Track trust_value changes over time

```sql
CREATE TABLE trust_value_history (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10),
    date DATE,
    trust_value FLOAT,
    source VARCHAR(50),  -- '10-Q', '10-K', 'press release'
    UNIQUE(ticker, date)
);
```

### 4. Automated Data Quality Checks

Run daily validation:
- Check for gaps in date ranges
- Verify price sanity (no negative prices, no huge jumps)
- Alert on missing data

### 5. API Endpoint for Charts

**FastAPI endpoint:**
```python
@app.get("/api/history/{ticker}")
def get_price_history(ticker: str, days: int = 90):
    """Return price history for charting"""
    query = text("""
        SELECT date, price, premium
        FROM historical_prices
        WHERE ticker = :ticker
        AND date >= CURRENT_DATE - INTERVAL ':days days'
        ORDER BY date
    """)

    result = db.execute(query, {'ticker': ticker, 'days': days})
    return [{'date': r.date, 'price': r.price, 'premium': r.premium} for r in result]
```

---

## Summary

✅ **Historical prices system is complete:**
- Database table created with proper indexes
- Backfill script fetches common, warrant, unit, and rights prices
- ~21,000 historical records loaded (Jan 1, 2025 → Oct 9, 2025)
- Minimal storage impact (~3 MB currently, ~5 MB/year growth)
- Ready for charting, analysis, and backtesting

🚀 **Next Steps:**
1. Integrate EOD logging into real-time price monitor
2. Build charting UI in Streamlit
3. Add premium trend analysis
4. Create price alerts based on historical patterns

---

*Last updated: October 9, 2025*
