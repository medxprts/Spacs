-- Add social_sentiment table for tracking Reddit/social media buzz
-- Used by Phase 1 scoring system (0-5 points for "Social Buzz")

CREATE TABLE IF NOT EXISTS social_sentiment (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) REFERENCES spacs(ticker) ON DELETE CASCADE,

    -- Mention metrics (7-day rolling window)
    mention_count_7d INTEGER DEFAULT 0,
    mention_count_24h INTEGER DEFAULT 0,
    mention_count_1h INTEGER DEFAULT 0,

    -- Target speculation
    rumored_targets TEXT[],  -- List of potential targets mentioned
    target_confidence FLOAT,  -- 0.0-1.0, highest confidence target
    top_rumored_target VARCHAR(255),  -- Most mentioned potential target

    -- Sentiment analysis
    sentiment_score FLOAT,  -- -1.0 (negative) to +1.0 (positive)
    sentiment_category VARCHAR(20),  -- 'bullish', 'neutral', 'bearish'

    -- Buzz scoring (for Phase 1 scorer)
    buzz_score INTEGER DEFAULT 0,  -- 0-5 points
    buzz_level VARCHAR(20),  -- 'none', 'low', 'medium', 'high', 'extreme'

    -- Top content samples
    top_posts JSONB,  -- Array of {title, url, upvotes, created_at, excerpt}

    -- Metadata
    last_updated TIMESTAMP DEFAULT NOW(),
    data_source VARCHAR(50) DEFAULT 'reddit',  -- 'reddit', 'twitter', 'stocktwits'
    update_count INTEGER DEFAULT 0,

    -- Unique constraint
    UNIQUE(ticker)
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_social_sentiment_ticker ON social_sentiment(ticker);
CREATE INDEX IF NOT EXISTS idx_social_sentiment_buzz_score ON social_sentiment(buzz_score);
CREATE INDEX IF NOT EXISTS idx_social_sentiment_last_updated ON social_sentiment(last_updated);

-- View for high buzz SPACs
CREATE OR REPLACE VIEW high_buzz_spacs AS
SELECT
    s.ticker,
    s.spac_name,
    s.deal_status,
    s.premium,
    ss.buzz_score,
    ss.buzz_level,
    ss.mention_count_7d,
    ss.mention_count_24h,
    ss.top_rumored_target,
    ss.sentiment_category,
    ss.last_updated
FROM spacs s
JOIN social_sentiment ss ON s.ticker = ss.ticker
WHERE ss.buzz_score >= 2  -- At least "medium" buzz
ORDER BY ss.buzz_score DESC, ss.mention_count_24h DESC;

COMMENT ON TABLE social_sentiment IS 'Tracks social media buzz and sentiment for SPACs, used in Phase 1 scoring (0-5 points)';
COMMENT ON COLUMN social_sentiment.buzz_score IS 'Phase 1 scoring points: 0=no buzz, 1-2=low, 3=medium, 4=high, 5=extreme viral';
COMMENT ON COLUMN social_sentiment.top_posts IS 'JSON array of top Reddit posts: [{title, url, upvotes, created_at, excerpt}]';
