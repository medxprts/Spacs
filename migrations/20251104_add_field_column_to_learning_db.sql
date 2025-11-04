-- Migration: Add 'field' column to data_quality_conversations for field-based learning
-- Date: 2025-11-04
-- Purpose: Enable field-based querying for proactive extraction learning
--
-- Context:
-- The extraction learning system needs to query past errors/successes by field name
-- (e.g., "Show me past format errors for 'earnout_shares'"). This requires a
-- dedicated 'field' column for efficient querying.
--
-- Before: Learning entries had no field association
-- After: Each learning can be queried by field name (e.g., 'earnout_shares', 'trust_value')

-- Add field column
ALTER TABLE data_quality_conversations
ADD COLUMN IF NOT EXISTS field VARCHAR(100);

-- Create index for efficient field-based queries
CREATE INDEX IF NOT EXISTS idx_conversations_field
ON data_quality_conversations(field);

-- Backfill existing CHAC/HOND errors (from Nov 4, 2025 fixes)
UPDATE data_quality_conversations
SET field = 'earnout_shares',
    original_data = '{
      "agent_name": "deal_detector",
      "ai_returned": "1.1M",
      "database_expected": 1100000,
      "error_message": "invalid input syntax for type double precision: \"1.1M\""
    }'::jsonb
WHERE issue_id = 'format_error_chac_20251104';

UPDATE data_quality_conversations
SET field = 'deal_status'
WHERE issue_id = 'import_error_hond_20251104';

-- Verify migration
SELECT
    COUNT(*) as total_entries,
    COUNT(*) FILTER (WHERE field IS NOT NULL) as entries_with_field,
    COUNT(DISTINCT field) as unique_fields
FROM data_quality_conversations;

-- Show sample field-based query (what the learning system will use)
SELECT
    field,
    issue_type,
    ticker,
    LEFT(learning_notes, 60) as learning_preview,
    created_at::date
FROM data_quality_conversations
WHERE field IS NOT NULL
ORDER BY created_at DESC
LIMIT 5;
