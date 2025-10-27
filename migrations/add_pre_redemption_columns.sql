-- Migration: Add pre-redemption trust tracking columns
-- Date: 2025-10-27
-- Purpose: Enable post-redemption trust cash calculation pattern

-- Add columns for tracking trust account state before redemption votes
ALTER TABLE spacs
ADD COLUMN IF NOT EXISTS pre_redemption_trust_cash NUMERIC,
ADD COLUMN IF NOT EXISTS pre_redemption_nav NUMERIC(10, 2),
ADD COLUMN IF NOT EXISTS trust_balance_date DATE,
ADD COLUMN IF NOT EXISTS extension_deposit NUMERIC,
ADD COLUMN IF NOT EXISTS expense_withdrawals NUMERIC,
ADD COLUMN IF NOT EXISTS def14a_filing_date DATE,
ADD COLUMN IF NOT EXISTS def14a_url TEXT;

-- Add comments for documentation
COMMENT ON COLUMN spacs.pre_redemption_trust_cash IS 'Trust cash before redemption vote (from DEF14A/DEFM14A)';
COMMENT ON COLUMN spacs.pre_redemption_nav IS 'NAV per share before redemption (from DEF14A/DEFM14A)';
COMMENT ON COLUMN spacs.trust_balance_date IS 'Date of trust balance disclosure in proxy';
COMMENT ON COLUMN spacs.extension_deposit IS 'Sponsor deposit for deadline extension (from 8-K)';
COMMENT ON COLUMN spacs.expense_withdrawals IS 'Cash withdrawn from trust for expenses';
COMMENT ON COLUMN spacs.def14a_filing_date IS 'Date of most recent DEF14A/DEFM14A filing';
COMMENT ON COLUMN spacs.def14a_url IS 'URL to most recent DEF14A/DEFM14A filing';

-- Create index for efficient queries
CREATE INDEX IF NOT EXISTS idx_spacs_def14a_filing_date ON spacs(def14a_filing_date);
CREATE INDEX IF NOT EXISTS idx_spacs_trust_balance_date ON spacs(trust_balance_date);
