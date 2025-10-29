-- Code Improvements Tracking Table
-- Logs all code fixes applied by the Code Fix Agent

CREATE TABLE IF NOT EXISTS code_improvements (
    id SERIAL PRIMARY KEY,

    -- Code location
    file_path VARCHAR(255) NOT NULL,
    function_name VARCHAR(100),
    line_range_start INTEGER,
    line_range_end INTEGER,

    -- Error pattern this fix addresses
    error_pattern VARCHAR(100) NOT NULL,
    occurrences_before_fix INTEGER,

    -- Fix details
    fix_explanation TEXT NOT NULL,
    prevention_type VARCHAR(50),  -- 'validation', 'extraction_improvement', etc.
    confidence_score INTEGER,     -- AI confidence (0-100)

    -- Application info
    applied_at TIMESTAMP DEFAULT NOW(),
    applied_by VARCHAR(50) DEFAULT 'code_fix_agent',
    lines_changed INTEGER,
    backup_path VARCHAR(255),

    -- Effectiveness tracking
    occurrences_after_fix INTEGER DEFAULT 0,
    fix_effective BOOLEAN,
    effectiveness_notes TEXT,

    -- Meta
    created_at TIMESTAMP DEFAULT NOW(),

    -- Indexes
    CONSTRAINT code_improvements_unique UNIQUE (file_path, error_pattern, applied_at)
);

CREATE INDEX idx_code_improvements_error_pattern ON code_improvements(error_pattern);
CREATE INDEX idx_code_improvements_file ON code_improvements(file_path);
CREATE INDEX idx_code_improvements_applied_at ON code_improvements(applied_at);

COMMENT ON TABLE code_improvements IS 'Tracks code fixes applied by the self-healing system';
COMMENT ON COLUMN code_improvements.error_pattern IS 'Issue type from data_quality_conversations';
COMMENT ON COLUMN code_improvements.occurrences_before_fix IS 'How many times this error occurred before the fix';
COMMENT ON COLUMN code_improvements.fix_effective IS 'NULL = unknown, TRUE = error stopped, FALSE = error persists';
