-- Prompt Management Tables
-- Track AI prompt usage, performance, and improvements

-- ============================================================================
-- Prompt Usage Log
-- ============================================================================
CREATE TABLE IF NOT EXISTS prompt_usage_log (
    id SERIAL PRIMARY KEY,

    -- Prompt identification
    prompt_id VARCHAR(100) NOT NULL,   -- e.g., 'deal_target_extraction'
    prompt_version VARCHAR(20),         -- e.g., 'v2'

    -- Usage context
    spac_ticker VARCHAR(10),
    filing_type VARCHAR(20),            -- '8-K', 'S-1', etc.
    filing_url TEXT,

    -- Result
    success BOOLEAN NOT NULL,
    extracted_data TEXT,                -- JSON string of extracted data
    error_message TEXT,

    -- Timing
    used_at TIMESTAMP DEFAULT NOW(),
    response_time_ms INTEGER,

    -- Indexes
    CONSTRAINT prompt_usage_log_unique UNIQUE (prompt_id, spac_ticker, used_at)
);

CREATE INDEX idx_prompt_usage_prompt_id ON prompt_usage_log(prompt_id);
CREATE INDEX idx_prompt_usage_success ON prompt_usage_log(success);
CREATE INDEX idx_prompt_usage_used_at ON prompt_usage_log(used_at);
CREATE INDEX idx_prompt_usage_ticker ON prompt_usage_log(spac_ticker);

-- ============================================================================
-- Prompt Improvements
-- ============================================================================
CREATE TABLE IF NOT EXISTS prompt_improvements (
    id SERIAL PRIMARY KEY,

    -- Prompt identification
    prompt_id VARCHAR(100) NOT NULL,
    old_version VARCHAR(20),
    new_version VARCHAR(20),

    -- What triggered the improvement
    trigger_reason TEXT,                -- 'low_success_rate', 'recurring_extraction_error', etc.
    error_pattern VARCHAR(100),         -- Link to data_quality_conversations.issue_type
    occurrences_before_fix INTEGER,

    -- Improvement details
    old_prompt_text TEXT,
    new_prompt_text TEXT,
    changes_explanation TEXT,           -- What changed and why
    improvement_type VARCHAR(50),       -- 'validation_rules', 'clearer_instructions', etc.

    -- Effectiveness tracking
    success_rate_before FLOAT,          -- e.g., 65.5
    success_rate_after FLOAT,           -- e.g., 92.3
    improvement_effective BOOLEAN,      -- NULL = unknown, TRUE = worked, FALSE = didn't work

    -- Application info
    applied_at TIMESTAMP DEFAULT NOW(),
    applied_by VARCHAR(50) DEFAULT 'code_fix_agent',
    backup_file_path VARCHAR(255),

    -- Meta
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_prompt_improvements_prompt_id ON prompt_improvements(prompt_id);
CREATE INDEX idx_prompt_improvements_error_pattern ON prompt_improvements(error_pattern);
CREATE INDEX idx_prompt_improvements_applied_at ON prompt_improvements(applied_at);

COMMENT ON TABLE prompt_usage_log IS 'Logs every AI prompt usage for performance tracking';
COMMENT ON TABLE prompt_improvements IS 'Tracks improvements made to AI prompts over time';

COMMENT ON COLUMN prompt_improvements.improvement_effective IS 'Did this improvement actually fix the issue?';
COMMENT ON COLUMN prompt_improvements.success_rate_before IS 'Prompt success rate before improvement (%)';
COMMENT ON COLUMN prompt_improvements.success_rate_after IS 'Prompt success rate after improvement (%)';
