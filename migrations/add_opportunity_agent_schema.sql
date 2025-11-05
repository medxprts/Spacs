-- ============================================================================
-- Opportunity Agent Database Schema Migration
-- Date: 2025-11-05
-- Purpose: Add tables and columns for opportunity identification agent
-- ============================================================================

-- ============================================================================
-- PART 1: NEW COLUMNS FOR spacs TABLE
-- ============================================================================

-- Phase 1: Pre-Announcement Data
-- ----------------------------------------------------------------------------

-- Normalized sponsor name (strip Roman numerals for grouping)
-- Example: "Klein Sponsor II LLC" → "Klein Sponsor"
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS sponsor_normalized VARCHAR(255);

-- Promote vesting structure
-- 'standard' = vests on closing, 'performance' = vests at price milestones
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS promote_vesting_type VARCHAR(50);

-- Price milestones for performance-based vesting
-- Example: [12.00, 15.00, 18.00] means vesting at $12, $15, $18
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS promote_vesting_prices NUMERIC[];

-- Phase 2: Post-Announcement Data
-- ----------------------------------------------------------------------------

-- PIPE share lockup period in months
-- Example: 12 = shares locked for 12 months from closing
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS pipe_lockup_months INT;

-- Public float calculation (shares available for trading)
-- Formula: shares_outstanding - founder_shares - private_placement_units
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS public_float BIGINT;

-- Volume on announcement day (from Yahoo Finance)
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS volume_on_announcement_day BIGINT;

-- Volume as percentage of float
-- High % = strong participation/demand
ALTER TABLE spacs ADD COLUMN IF NOT EXISTS volume_pct_of_float NUMERIC;

-- Create index on sponsor_normalized for performance
CREATE INDEX IF NOT EXISTS idx_spacs_sponsor_normalized ON spacs(sponsor_normalized);

-- ============================================================================
-- PART 2: NEW TABLES
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. sponsor_performance
-- Purpose: Track historical performance of SPAC sponsors
-- Usage: Calculate avg price "pop" after deal announcements
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sponsor_performance (
    id SERIAL PRIMARY KEY,
    sponsor_name VARCHAR(255) UNIQUE NOT NULL,

    -- Deal statistics
    total_deals INT DEFAULT 0,
    completed_deals INT DEFAULT 0,
    announced_deals INT DEFAULT 0,

    -- Performance metrics (% price increase from announcement)
    avg_7day_pop NUMERIC,   -- Average 7-day pop
    avg_14day_pop NUMERIC,  -- Average 14-day pop
    avg_30day_pop NUMERIC,  -- Average 30-day pop
    max_pop NUMERIC,        -- Best performing deal
    min_pop NUMERIC,        -- Worst performing deal

    -- Deal history (array of tickers)
    deal_tickers TEXT[],

    -- Metadata
    last_updated TIMESTAMP DEFAULT NOW(),
    data_quality VARCHAR(50) DEFAULT 'complete'  -- 'complete', 'partial', 'estimated'
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sponsor_performance_name ON sponsor_performance(sponsor_name);
CREATE INDEX IF NOT EXISTS idx_sponsor_performance_avg_pop ON sponsor_performance(avg_30day_pop DESC);

-- Comments
COMMENT ON TABLE sponsor_performance IS 'Historical track record of SPAC sponsors';
COMMENT ON COLUMN sponsor_performance.avg_30day_pop IS 'Average % price increase 30 days post-announcement';

-- ----------------------------------------------------------------------------
-- 2. pipe_investors
-- Purpose: Track PIPE investor participants and tier classification
-- Usage: Identify Tier-1 institutional validation
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipe_investors (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker) ON DELETE CASCADE,

    -- Investor details
    investor_name VARCHAR(255) NOT NULL,
    investment_amount NUMERIC,  -- Investment in dollars

    -- Tier classification
    is_tier1 BOOLEAN DEFAULT FALSE,  -- BlackRock, Fidelity, Vanguard, etc.
    tier_category VARCHAR(50),       -- 'institutional', 'strategic', 'insider', 'other'

    -- Metadata
    source_filing VARCHAR(50),  -- 'EX-10.1', 'EX-10.2', 'EX-99.1'
    detected_date DATE DEFAULT CURRENT_DATE,

    UNIQUE(ticker, investor_name)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_pipe_investors_ticker ON pipe_investors(ticker);
CREATE INDEX IF NOT EXISTS idx_pipe_investors_tier1 ON pipe_investors(is_tier1) WHERE is_tier1 = TRUE;
CREATE INDEX IF NOT EXISTS idx_pipe_investors_name ON pipe_investors(investor_name);

-- Comments
COMMENT ON TABLE pipe_investors IS 'PIPE financing participants with tier classification';
COMMENT ON COLUMN pipe_investors.is_tier1 IS 'Tier-1 institutional investors (BlackRock, Fidelity, etc.)';

-- ----------------------------------------------------------------------------
-- 3. opportunity_scores
-- Purpose: Store calculated opportunity scores for each SPAC
-- Usage: Track Phase 1 (Loaded Gun) and Phase 2 (Lit Fuse) scores
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS opportunity_scores (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker) ON DELETE CASCADE,

    -- Phase 1: Pre-Announcement Scores (Loaded Gun)
    market_cap_score INT DEFAULT 0,        -- 0 or 10 points
    sponsor_score INT DEFAULT 0,           -- 0-15 points
    sector_score INT DEFAULT 0,            -- 0 or 10 points
    dilution_score INT DEFAULT 0,          -- 0-15 points (warrants + rights)
    promote_score INT DEFAULT 0,           -- 0 or 10 points
    loaded_gun_score INT DEFAULT 0,        -- Sum of Phase 1 (max 60)

    -- Phase 2: Post-Announcement Scores (Lit Fuse)
    pipe_size_score INT DEFAULT 0,         -- 0-20 points
    pipe_quality_score INT DEFAULT 0,      -- 0-20 points (tier-1 investors)
    projection_score INT DEFAULT 0,        -- 0-20 points (hockey stick)
    lockup_score INT DEFAULT 0,            -- 0-15 points
    volume_score INT DEFAULT 0,            -- 0-15 points (% of float)
    lit_fuse_score INT DEFAULT 0,          -- Sum of Phase 2 (max 90)

    -- Combined Score
    total_score INT DEFAULT 0,             -- loaded_gun + lit_fuse (max 150)

    -- Tier classification
    tier VARCHAR(10),  -- 'A-Tier', 'B-Tier', 'C-Tier'
    alert_threshold VARCHAR(20),  -- 'EXTREME', 'STRONG', 'MODERATE', 'PASS'

    -- Metadata
    last_calculated TIMESTAMP DEFAULT NOW(),
    calculation_version VARCHAR(10) DEFAULT '1.0',

    UNIQUE(ticker)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_ticker ON opportunity_scores(ticker);
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_total ON opportunity_scores(total_score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_loaded_gun ON opportunity_scores(loaded_gun_score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_lit_fuse ON opportunity_scores(lit_fuse_score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_tier ON opportunity_scores(tier);

-- Comments
COMMENT ON TABLE opportunity_scores IS 'Opportunity identification scores for each SPAC';
COMMENT ON COLUMN opportunity_scores.loaded_gun_score IS 'Phase 1 pre-announcement score (max 60)';
COMMENT ON COLUMN opportunity_scores.lit_fuse_score IS 'Phase 2 post-announcement score (max 90)';

-- ----------------------------------------------------------------------------
-- 4. opportunity_alerts
-- Purpose: Log all opportunity alerts sent to Telegram
-- Usage: Track alert history, prevent duplicate alerts
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS opportunity_alerts (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker) ON DELETE CASCADE,

    -- Alert classification
    alert_type VARCHAR(50) NOT NULL,  -- 'EXTREME', 'STRONG', 'MODERATE', 'NEW_LOADED_GUN'
    phase VARCHAR(10),                -- 'PHASE_1', 'PHASE_2', 'COMBINED'

    -- Scores at time of alert
    total_score INT,
    loaded_gun_score INT,
    lit_fuse_score INT,

    -- Alert content
    alert_message TEXT,
    alert_summary VARCHAR(500),

    -- Delivery status
    sent_via_telegram BOOLEAN DEFAULT FALSE,
    telegram_message_id VARCHAR(50),
    delivery_error TEXT,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),

    -- Prevent duplicate alerts (same ticker, same day, same type)
    UNIQUE(ticker, alert_type, created_at::date)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_opportunity_alerts_ticker ON opportunity_alerts(ticker);
CREATE INDEX IF NOT EXISTS idx_opportunity_alerts_type ON opportunity_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_opportunity_alerts_created ON opportunity_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_alerts_sent ON opportunity_alerts(sent_via_telegram);

-- Comments
COMMENT ON TABLE opportunity_alerts IS 'History of opportunity alerts sent via Telegram';
COMMENT ON COLUMN opportunity_alerts.alert_type IS 'EXTREME (120+), STRONG (90-119), MODERATE (70-89)';

-- ----------------------------------------------------------------------------
-- 5. price_history_extended
-- Purpose: Store historical price data for sponsor performance calculation
-- Usage: Track prices 30 days post-announcement for each deal
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_history_extended (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,

    -- Price data
    date DATE NOT NULL,
    price NUMERIC,
    volume BIGINT,

    -- Context
    days_since_announcement INT,  -- 0 = announcement day, 1 = day after, etc.
    days_since_ipo INT,

    -- Calculated metrics
    price_change_pct NUMERIC,  -- % change from announcement day price
    volume_vs_avg NUMERIC,     -- Multiple of 30-day average volume

    -- Metadata
    data_source VARCHAR(50) DEFAULT 'yahoo_finance',
    fetched_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(ticker, date)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_price_history_ext_ticker ON price_history_extended(ticker);
CREATE INDEX IF NOT EXISTS idx_price_history_ext_date ON price_history_extended(date DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_ext_days_announcement ON price_history_extended(ticker, days_since_announcement);

-- Partition by date for performance (optional - uncomment if needed)
-- CREATE INDEX IF NOT EXISTS idx_price_history_ext_date_range ON price_history_extended(date) WHERE date >= CURRENT_DATE - INTERVAL '1 year';

-- Comments
COMMENT ON TABLE price_history_extended IS 'Historical price data for sponsor performance tracking';
COMMENT ON COLUMN price_history_extended.days_since_announcement IS 'Days elapsed since deal announcement (0 = announcement day)';

-- ============================================================================
-- PART 3: HELPER VIEWS
-- ============================================================================

-- ----------------------------------------------------------------------------
-- View: top_opportunity_spacs
-- Purpose: Quick view of highest scoring opportunities
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW top_opportunity_spacs AS
SELECT
    s.ticker,
    s.company,
    s.sponsor,
    s.deal_status,
    s.sector_classified,
    s.is_hot_sector,
    o.loaded_gun_score,
    o.lit_fuse_score,
    o.total_score,
    o.tier,
    o.alert_threshold,
    s.price,
    s.premium,
    s.market_cap,
    s.announced_date,
    o.last_calculated
FROM spacs s
LEFT JOIN opportunity_scores o ON s.ticker = o.ticker
WHERE o.total_score >= 70  -- Only MODERATE+ opportunities
ORDER BY o.total_score DESC;

COMMENT ON VIEW top_opportunity_spacs IS 'Top scoring opportunity SPACs (score >= 70)';

-- ----------------------------------------------------------------------------
-- View: loaded_guns
-- Purpose: Pre-deal SPACs with high Phase 1 scores
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW loaded_guns AS
SELECT
    s.ticker,
    s.company,
    s.sponsor_normalized,
    s.sector_classified,
    s.is_hot_sector,
    o.loaded_gun_score,
    o.market_cap_score,
    o.sponsor_score,
    o.sector_score,
    o.dilution_score,
    o.promote_score,
    o.tier,
    s.price,
    s.premium,
    s.market_cap,
    s.deadline_date
FROM spacs s
LEFT JOIN opportunity_scores o ON s.ticker = o.ticker
WHERE s.deal_status = 'SEARCHING'
  AND o.loaded_gun_score >= 30  -- B-Tier or better
ORDER BY o.loaded_gun_score DESC;

COMMENT ON VIEW loaded_guns IS 'Pre-deal SPACs with high Phase 1 scores (Loaded Guns)';

-- ----------------------------------------------------------------------------
-- View: lit_fuses
-- Purpose: Announced deals with high Phase 2 scores
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW lit_fuses AS
SELECT
    s.ticker,
    s.company,
    s.target,
    s.announced_date,
    o.lit_fuse_score,
    o.pipe_size_score,
    o.pipe_quality_score,
    o.projection_score,
    o.volume_score,
    s.pipe_size,
    s.pipe_percentage,
    s.volume_pct_of_float,
    s.price,
    s.premium,
    (SELECT COUNT(*) FROM pipe_investors pi WHERE pi.ticker = s.ticker AND pi.is_tier1 = TRUE) as tier1_investor_count
FROM spacs s
LEFT JOIN opportunity_scores o ON s.ticker = o.ticker
WHERE s.deal_status = 'ANNOUNCED'
  AND o.lit_fuse_score >= 50  -- Strong catalyst or better
ORDER BY o.lit_fuse_score DESC;

COMMENT ON VIEW lit_fuses IS 'Announced deals with high Phase 2 scores (Lit Fuses)';

-- ============================================================================
-- PART 4: DATA QUALITY CONSTRAINTS
-- ============================================================================

-- Add check constraints for score ranges
ALTER TABLE opportunity_scores
    ADD CONSTRAINT chk_market_cap_score CHECK (market_cap_score BETWEEN 0 AND 10),
    ADD CONSTRAINT chk_sponsor_score CHECK (sponsor_score BETWEEN 0 AND 15),
    ADD CONSTRAINT chk_sector_score CHECK (sector_score BETWEEN 0 AND 10),
    ADD CONSTRAINT chk_dilution_score CHECK (dilution_score BETWEEN 0 AND 15),
    ADD CONSTRAINT chk_promote_score CHECK (promote_score BETWEEN 0 AND 10),
    ADD CONSTRAINT chk_loaded_gun_score CHECK (loaded_gun_score BETWEEN 0 AND 60),
    ADD CONSTRAINT chk_pipe_size_score CHECK (pipe_size_score BETWEEN 0 AND 20),
    ADD CONSTRAINT chk_pipe_quality_score CHECK (pipe_quality_score BETWEEN 0 AND 20),
    ADD CONSTRAINT chk_projection_score CHECK (projection_score BETWEEN 0 AND 20),
    ADD CONSTRAINT chk_lockup_score CHECK (lockup_score BETWEEN 0 AND 15),
    ADD CONSTRAINT chk_volume_score CHECK (volume_score BETWEEN 0 AND 15),
    ADD CONSTRAINT chk_lit_fuse_score CHECK (lit_fuse_score BETWEEN 0 AND 90),
    ADD CONSTRAINT chk_total_score CHECK (total_score BETWEEN 0 AND 150);

-- ============================================================================
-- PART 5: INITIAL DATA POPULATION
-- ============================================================================

-- Create index for performance on commonly queried columns
CREATE INDEX IF NOT EXISTS idx_spacs_deal_status_sector ON spacs(deal_status, is_hot_sector);
CREATE INDEX IF NOT EXISTS idx_spacs_announced_date ON spacs(announced_date) WHERE announced_date IS NOT NULL;

-- ============================================================================
-- PART 6: GRANTS (if using specific database users)
-- ============================================================================

-- Grant permissions to application user (adjust username as needed)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO spac_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO spac_user;

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================

-- Display summary
DO $$
DECLARE
    table_count INT;
    column_count INT;
BEGIN
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_name IN ('sponsor_performance', 'pipe_investors', 'opportunity_scores',
                         'opportunity_alerts', 'price_history_extended');

    SELECT COUNT(*) INTO column_count
    FROM information_schema.columns
    WHERE table_name = 'spacs'
      AND column_name IN ('sponsor_normalized', 'promote_vesting_type', 'promote_vesting_prices',
                          'pipe_lockup_months', 'public_float', 'volume_on_announcement_day',
                          'volume_pct_of_float');

    RAISE NOTICE '════════════════════════════════════════════════════════════════';
    RAISE NOTICE 'Opportunity Agent Schema Migration Complete';
    RAISE NOTICE '════════════════════════════════════════════════════════════════';
    RAISE NOTICE 'New tables created: %', table_count;
    RAISE NOTICE 'New columns added to spacs table: %', column_count;
    RAISE NOTICE 'Views created: 3 (top_opportunity_spacs, loaded_guns, lit_fuses)';
    RAISE NOTICE '════════════════════════════════════════════════════════════════';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '1. Run sponsor normalization script';
    RAISE NOTICE '2. Backfill historical price data';
    RAISE NOTICE '3. Run sector classifier on all SPACs';
    RAISE NOTICE '4. Build extraction agents';
    RAISE NOTICE '════════════════════════════════════════════════════════════════';
END $$;
