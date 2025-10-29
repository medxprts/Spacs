-- Migration: Consolidate Feedback State to Database
-- Version: 1.0.0
-- Date: 2025-10-29
-- Purpose: Replace JSON file state with database tables for ACID compliance

-- ============================================================================
-- 1. VALIDATION QUEUE TABLES
-- ============================================================================

-- Main queue table (replaces .validation_issue_queue.json)
CREATE TABLE IF NOT EXISTS validation_queue (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT NOW(),
    current_index INTEGER DEFAULT 0,
    total_issues INTEGER DEFAULT 0,
    awaiting_response BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'active',  -- 'active', 'completed', 'cancelled'

    -- Metadata
    triggered_by VARCHAR(50),  -- 'data_validator', 'manual', 'scheduled'
    priority VARCHAR(20) DEFAULT 'normal',  -- 'low', 'normal', 'high', 'critical'

    CONSTRAINT valid_status CHECK (status IN ('active', 'completed', 'cancelled'))
);

CREATE INDEX idx_validation_queue_status ON validation_queue(status);
CREATE INDEX idx_validation_queue_created_at ON validation_queue(created_at);

COMMENT ON TABLE validation_queue IS 'Sequential queue for validation issue review';
COMMENT ON COLUMN validation_queue.current_index IS 'Current position in queue (0-based)';
COMMENT ON COLUMN validation_queue.awaiting_response IS 'TRUE if waiting for user response';

-- Individual issues in queue
CREATE TABLE IF NOT EXISTS validation_queue_items (
    id SERIAL PRIMARY KEY,
    queue_id INTEGER REFERENCES validation_queue(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,  -- Position in queue (1, 2, 3...)

    -- Issue details
    ticker VARCHAR(10),
    field VARCHAR(50),
    rule_id VARCHAR(50),  -- Links to validation_rules.yaml
    rule_name VARCHAR(100),
    severity VARCHAR(20),  -- 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    category VARCHAR(50),  -- 'trust_account', 'deal_data', etc.

    -- Issue data (flexible JSON storage)
    issue_data JSONB NOT NULL,  -- Full issue details

    -- Status tracking
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'approved', 'skipped', 'modified'
    resolved_at TIMESTAMP,
    resolution_notes TEXT,

    -- Fix tracking
    proposed_fix JSONB,  -- Original AI-proposed fix
    applied_fix JSONB,   -- Actual fix applied (may differ if user modified)
    fix_template_id VARCHAR(50),  -- Links to fix_templates.yaml

    -- User interaction
    user_modified BOOLEAN DEFAULT FALSE,
    modification_count INTEGER DEFAULT 0,
    conversation_turns INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT valid_item_status CHECK (status IN ('pending', 'approved', 'skipped', 'modified')),
    CONSTRAINT valid_severity CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW'))
);

CREATE INDEX idx_queue_items_queue_id ON validation_queue_items(queue_id);
CREATE INDEX idx_queue_items_position ON validation_queue_items(queue_id, position);
CREATE INDEX idx_queue_items_status ON validation_queue_items(status);
CREATE INDEX idx_queue_items_ticker ON validation_queue_items(ticker);
CREATE INDEX idx_queue_items_rule_id ON validation_queue_items(rule_id);

COMMENT ON TABLE validation_queue_items IS 'Individual validation issues in sequential queue';
COMMENT ON COLUMN validation_queue_items.issue_data IS 'Full issue details: actual, expected, message, etc.';
COMMENT ON COLUMN validation_queue_items.user_modified IS 'TRUE if user modified proposed fix via chat';

-- ============================================================================
-- 2. TELEGRAM STATE TABLE
-- ============================================================================

-- Telegram agent state (replaces .telegram_listener_state.json)
CREATE TABLE IF NOT EXISTS telegram_state (
    id SERIAL PRIMARY KEY,
    last_update_id BIGINT DEFAULT 0,  -- Last processed Telegram update ID
    last_message_timestamp TIMESTAMP,

    -- Current context
    active_queue_id INTEGER REFERENCES validation_queue(id),
    active_conversation_id VARCHAR(100),  -- Links to data_quality_conversations

    -- State
    is_listening BOOLEAN DEFAULT TRUE,
    last_heartbeat TIMESTAMP DEFAULT NOW(),

    -- Config
    bot_token_hash VARCHAR(64),  -- Hashed token for verification
    chat_id BIGINT,

    -- Metadata
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT telegram_state_singleton CHECK (id = 1)  -- Only one row allowed
);

CREATE INDEX idx_telegram_state_updated_at ON telegram_state(updated_at);

COMMENT ON TABLE telegram_state IS 'Telegram bot state - replaces JSON file storage';
COMMENT ON COLUMN telegram_state.last_update_id IS 'Last processed update from Telegram getUpdates';
COMMENT ON COLUMN telegram_state.telegram_state_singleton IS 'Ensures only one state record exists';

-- Initialize with default values
INSERT INTO telegram_state (id, last_update_id)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 3. ENHANCED DATA QUALITY CONVERSATIONS TABLE
-- ============================================================================

-- Enhance existing table if needed (may already exist)
DO $$
BEGIN
    -- Add columns if they don't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='data_quality_conversations'
                   AND column_name='queue_item_id') THEN
        ALTER TABLE data_quality_conversations
        ADD COLUMN queue_item_id INTEGER REFERENCES validation_queue_items(id);

        CREATE INDEX idx_dqc_queue_item ON data_quality_conversations(queue_item_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='data_quality_conversations'
                   AND column_name='conversation_turns') THEN
        ALTER TABLE data_quality_conversations
        ADD COLUMN conversation_turns INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='data_quality_conversations'
                   AND column_name='user_satisfaction') THEN
        ALTER TABLE data_quality_conversations
        ADD COLUMN user_satisfaction INTEGER CHECK (user_satisfaction BETWEEN 1 AND 5);

        COMMENT ON COLUMN data_quality_conversations.user_satisfaction IS 'User rating 1-5 after resolution';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='data_quality_conversations'
                   AND column_name='error_pattern') THEN
        ALTER TABLE data_quality_conversations
        ADD COLUMN error_pattern VARCHAR(100);

        CREATE INDEX idx_dqc_error_pattern ON data_quality_conversations(error_pattern);

        COMMENT ON COLUMN data_quality_conversations.error_pattern IS 'Pattern key for self-improvement tracking';
    END IF;
END $$;

-- ============================================================================
-- 4. ERROR PATTERN TRACKING (for self-improvement)
-- ============================================================================

CREATE TABLE IF NOT EXISTS error_patterns (
    id SERIAL PRIMARY KEY,
    pattern_key VARCHAR(100) UNIQUE NOT NULL,  -- e.g., "shares_outstanding_not_found_424B4"
    pattern_description TEXT,

    -- Occurrence tracking
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    occurrence_count INTEGER DEFAULT 0,
    occurrences_last_30_days INTEGER DEFAULT 0,

    -- Self-improvement tracking
    threshold INTEGER DEFAULT 3,  -- Trigger fix after N occurrences
    status VARCHAR(30) DEFAULT 'monitoring',  -- 'monitoring', 'fix_proposed', 'fix_applied', 'resolved'
    fix_proposed_at TIMESTAMP,
    fix_applied_at TIMESTAMP,

    -- Fix details
    proposed_fix_id INTEGER REFERENCES code_improvements(id),
    root_cause TEXT,
    affected_tickers TEXT[],  -- Array of ticker symbols

    -- Effectiveness
    occurrences_after_fix INTEGER DEFAULT 0,
    fix_effective BOOLEAN,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT valid_pattern_status CHECK (status IN ('monitoring', 'fix_proposed', 'fix_applied', 'resolved'))
);

CREATE INDEX idx_error_patterns_key ON error_patterns(pattern_key);
CREATE INDEX idx_error_patterns_status ON error_patterns(status);
CREATE INDEX idx_error_patterns_last_seen ON error_patterns(last_seen);

COMMENT ON TABLE error_patterns IS 'Tracks recurring error patterns for self-improvement system';
COMMENT ON COLUMN error_patterns.threshold IS 'Number of occurrences before triggering code fix proposal';

-- ============================================================================
-- 5. BATCH APPROVAL HISTORY
-- ============================================================================

CREATE TABLE IF NOT EXISTS batch_approvals (
    id SERIAL PRIMARY KEY,
    queue_id INTEGER REFERENCES validation_queue(id),

    -- Batch details
    pattern VARCHAR(100),  -- e.g., "Trust Cash", "Trust Value", "ALL"
    items_approved INTEGER,
    item_ids INTEGER[],  -- Array of validation_queue_items.id

    -- User
    approved_by VARCHAR(50) DEFAULT 'user',
    approved_at TIMESTAMP DEFAULT NOW(),

    -- Context
    approval_reason TEXT,
    confidence_level DECIMAL(3,2)  -- 0.00 to 1.00
);

CREATE INDEX idx_batch_approvals_queue ON batch_approvals(queue_id);
CREATE INDEX idx_batch_approvals_pattern ON batch_approvals(pattern);

COMMENT ON TABLE batch_approvals IS 'Tracks batch approval operations for audit trail';

-- ============================================================================
-- 6. VIEWS FOR CONVENIENCE
-- ============================================================================

-- Active queue with current issue
CREATE OR REPLACE VIEW current_queue_status AS
SELECT
    q.id as queue_id,
    q.current_index,
    q.total_issues,
    q.awaiting_response,
    qi.id as current_item_id,
    qi.ticker,
    qi.field,
    qi.rule_name,
    qi.severity,
    qi.status,
    qi.issue_data
FROM validation_queue q
LEFT JOIN validation_queue_items qi ON qi.queue_id = q.id AND qi.position = q.current_index + 1
WHERE q.status = 'active'
ORDER BY q.created_at DESC
LIMIT 1;

COMMENT ON VIEW current_queue_status IS 'Shows current active queue and item awaiting review';

-- Error patterns needing attention
CREATE OR REPLACE VIEW patterns_needing_fix AS
SELECT
    pattern_key,
    pattern_description,
    occurrence_count,
    occurrences_last_30_days,
    threshold,
    last_seen,
    affected_tickers
FROM error_patterns
WHERE status = 'monitoring'
  AND occurrences_last_30_days >= threshold
ORDER BY occurrences_last_30_days DESC;

COMMENT ON VIEW patterns_needing_fix IS 'Error patterns that have crossed threshold and need code fixes';

-- Queue statistics
CREATE OR REPLACE VIEW queue_statistics AS
SELECT
    q.id as queue_id,
    q.created_at,
    q.total_issues,
    COUNT(CASE WHEN qi.status = 'approved' THEN 1 END) as approved_count,
    COUNT(CASE WHEN qi.status = 'skipped' THEN 1 END) as skipped_count,
    COUNT(CASE WHEN qi.status = 'pending' THEN 1 END) as pending_count,
    COUNT(CASE WHEN qi.user_modified THEN 1 END) as modified_count,
    ROUND(AVG(qi.conversation_turns), 1) as avg_conversation_turns
FROM validation_queue q
LEFT JOIN validation_queue_items qi ON qi.queue_id = q.id
GROUP BY q.id, q.created_at, q.total_issues
ORDER BY q.created_at DESC;

COMMENT ON VIEW queue_statistics IS 'Aggregate statistics for each validation queue';

-- ============================================================================
-- 7. FUNCTIONS
-- ============================================================================

-- Function to get next queue item
CREATE OR REPLACE FUNCTION get_next_queue_item()
RETURNS TABLE (
    queue_id INTEGER,
    item_id INTEGER,
    position INTEGER,
    ticker VARCHAR,
    field VARCHAR,
    rule_name VARCHAR,
    severity VARCHAR,
    issue_data JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        q.id,
        qi.id,
        qi.position,
        qi.ticker,
        qi.field,
        qi.rule_name,
        qi.severity,
        qi.issue_data
    FROM validation_queue q
    JOIN validation_queue_items qi ON qi.queue_id = q.id
    WHERE q.status = 'active'
      AND qi.position = q.current_index + 1
      AND qi.status = 'pending'
    ORDER BY q.created_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_next_queue_item IS 'Retrieves next pending item from active queue';

-- Function to record error occurrence
CREATE OR REPLACE FUNCTION record_error_occurrence(
    p_pattern_key VARCHAR,
    p_ticker VARCHAR,
    p_description TEXT DEFAULT NULL
)
RETURNS void AS $$
BEGIN
    INSERT INTO error_patterns (
        pattern_key,
        pattern_description,
        first_seen,
        last_seen,
        occurrence_count,
        occurrences_last_30_days,
        affected_tickers
    )
    VALUES (
        p_pattern_key,
        p_description,
        NOW(),
        NOW(),
        1,
        1,
        ARRAY[p_ticker]
    )
    ON CONFLICT (pattern_key) DO UPDATE SET
        last_seen = NOW(),
        occurrence_count = error_patterns.occurrence_count + 1,
        occurrences_last_30_days = (
            SELECT COUNT(*)
            FROM data_quality_conversations
            WHERE error_pattern = p_pattern_key
              AND created_at > NOW() - INTERVAL '30 days'
        ),
        affected_tickers = array_append(
            error_patterns.affected_tickers,
            p_ticker
        ),
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION record_error_occurrence IS 'Records error occurrence for self-improvement tracking';

-- ============================================================================
-- 8. DATA MIGRATION (from JSON files if they exist)
-- ============================================================================

-- Note: Run these manually after deploying migration
COMMENT ON SCHEMA public IS 'Manual migration steps:
1. Export .validation_issue_queue.json to validation_queue tables
2. Export .telegram_listener_state.json to telegram_state table
3. Link existing data_quality_conversations to queue_items
4. Verify all state migrated correctly
5. Backup and remove JSON files';

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================

-- Verify tables created
DO $$
DECLARE
    table_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN (
          'validation_queue',
          'validation_queue_items',
          'telegram_state',
          'error_patterns',
          'batch_approvals'
      );

    IF table_count = 5 THEN
        RAISE NOTICE '✅ Migration successful: All 5 tables created';
    ELSE
        RAISE WARNING '⚠️  Only % of 5 tables created', table_count;
    END IF;
END $$;
