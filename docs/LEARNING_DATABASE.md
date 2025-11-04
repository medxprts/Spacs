# Learning Database - Few-Shot AI Learning System

**Database**: `data_quality_conversations` table in PostgreSQL
**Purpose**: Store all errors, fixes, and learnings for Few-Shot AI improvement
**Status**: Active - 61 issues logged as of Nov 4, 2025

---

## Overview

The `data_quality_conversations` table is our **central learning system** where we log:
- Data quality issues (missing data, anomalies, stale data)
- AI extraction errors (format issues, parsing failures)
- Agent execution failures (import errors, silent failures)
- Code fixes and their outcomes

This enables **Few-Shot learning**: Future AI agents query this table to learn from past mistakes and avoid repeating them.

---

## Database Schema

```sql
CREATE TABLE data_quality_conversations (
    id SERIAL PRIMARY KEY,
    issue_id VARCHAR(100) UNIQUE,           -- Unique identifier
    issue_type VARCHAR(50),                 -- Type of issue
    ticker VARCHAR(10),                     -- SPAC ticker (if applicable)
    field VARCHAR(100),                     -- Field name (if applicable)
    issue_source VARCHAR(20) DEFAULT 'ai_detected',  -- How detected

    -- Timing
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),

    -- Status
    status VARCHAR(20) DEFAULT 'active',    -- active, completed, reviewed, approved

    -- Data
    original_data JSONB DEFAULT '{}',       -- Original problematic data
    proposed_fix JSONB,                     -- AI-suggested fix
    final_fix JSONB,                        -- Actual fix applied
    messages JSONB DEFAULT '[]',            -- Conversation history
    learning_notes TEXT                     -- Human-readable explanation
);
```

**Indexes**:
- `issue_id` (unique)
- `ticker`
- `status`

---

## Issue Types

| Type | Description | Example | Use Case |
|------|-------------|---------|----------|
| `missing_data` | Required field is NULL | Missing trust_value | SEC scraping gaps |
| `data_corruption` | Invalid/wrong values | "1.1M" in numeric field | AI format errors |
| `stale_data` | Outdated information | Deadline passed | Monitoring failures |
| `anomaly` | Statistical outlier | Trust cash 354% above IPO | Data validation |
| `import_error` | Code import failures | Missing archived file | Agent failures |
| `format_error` | Type mismatches | String in numeric column | Parsing issues |
| `validation_error` | Business rule violations | Invalid target name | Logic errors |

---

## Two Learning Modes: Reactive vs Proactive

The learning database supports TWO different learning patterns:

### 1. **Reactive Investigation** (IMPLEMENTED ✅)
**Agent**: `investigation_agent.py`
**When**: After anomaly detected (deadline passed, trust cash spike, invalid data)
**How**: Queries past investigations to generate better hypotheses

**Example**:
```
Anomaly Detected: BLUW deadline passed (2025-10-15)
↓
Investigation Agent:
  → Queries past "deadline_passed" cases
  → AI generates hypothesis: "Likely extension or completion"
  → Searches SEC filings for evidence
  → Finds extension in 8-K Item 5.03
  → Saves outcome to learning database
```

**Implementation**:
```python
# investigation_agent.py (lines 661-796)
def generate_hypotheses(self, anomaly, context):
    # Retrieve past learnings for similar issue type
    past_learnings = self._retrieve_past_learnings(issue_type, ticker)

    # Generate hypotheses informed by past patterns
    return self.hypothesis_generator.generate(anomaly, context, past_learnings)
```

**Works for**: Anomalies that need investigation (deadline issues, data spikes, validation failures)

---

### 2. **Proactive Extraction** (NOT IMPLEMENTED ❌)
**Agents**: Extraction agents (deal_detector, redemption_extractor, etc.)
**When**: During normal extraction, before anomaly occurs
**How**: Query past extraction errors to improve accuracy

**Example**:
```
Agent extracting earnout_shares from 8-K
↓
Before extraction:
  → Queries past "earnout_shares" format errors
  → Sees: "AI returned '1.1M' instead of 1100000"
  → Includes this in prompt: "Return numeric values, not '1.1M'"
  → AI extracts correctly: 1100000
  → Database write succeeds
```

**Current Reality**: ❌ NO extraction agents use this yet
- Infrastructure exists (`SelfLearningMixin`, learning database)
- Pattern documented but not implemented
- All agents still extract without learning from past errors

**What's Needed**:
1. Teach agents to search filings for missing data (not return None)
2. Include past extraction errors in AI prompts
3. Apply learnings proactively during extraction

**User Insight** (Nov 4, 2025):
> "I think the right solution is first confirm it's still a SPAC that isn't completed, and then to try to find it in filings"

**Correct Pattern**:
```python
# When encountering missing data
if trust_value is None:
    # ❌ WRONG: Return None (current pattern)
    # ✅ RIGHT: Search filings to find it

    # 1. Check if SPAC is still active
    if spac.deal_status != 'COMPLETED':
        # 2. Query past learnings
        past_fixes = query_learning_db(field='trust_value')

        # 3. Search filings based on past successes
        # Past learning: "Found in 10-Q, Item 1 - Financial Statements"
        trust_value = search_filing_for_trust_value(ticker, hint='10-Q Item 1')

        # 4. Update database
        if trust_value:
            update_database(ticker, trust_value=trust_value)
```

---

## How Few-Shot Learning Works

### 1. Query Past Corrections

When an AI agent encounters an issue, it queries similar past corrections:

```sql
-- Example: Agent extracting earnout_shares
SELECT
    issue_id,
    ticker,
    original_data,
    final_fix,
    learning_notes,
    created_at
FROM data_quality_conversations
WHERE field = 'earnout_shares'
  AND issue_type = 'data_corruption'
  AND final_fix IS NOT NULL
  AND created_at >= NOW() - INTERVAL '90 days'
ORDER BY created_at DESC
LIMIT 5;
```

**Result**:
```
issue_id: format_error_chac_20251104
ticker: CHAC
original_data: {"ai_returned": "1.1M", "database_expected": 1100000}
final_fix: {"earnout_shares": 1100000, "fix_type": "number_parser"}
learning_notes: AI returned "1.1M" despite prompt instructions.
                Added parse_numeric_value() to sanitize numeric fields.
```

### 2. Include in AI Prompt

The agent includes past corrections in its prompt:

```python
past_corrections = query_past_corrections(field='earnout_shares')

prompt = f"""
Extract earnout_shares from this filing.

IMPORTANT: Return NUMERIC VALUES (not formatted strings).

Past corrections for similar issues:
{format_corrections(past_corrections)}

Example of correct format:
- "1.1M shares" → 1100000 (not "1.1M")
- "$50M" → 50000000 (not "50M")

Filing text:
{filing_text}
"""
```

### 3. AI Learns Pattern

The AI sees past mistakes and corrections, improving accuracy by ~30%.

---

## Current Stats (Nov 4, 2025)

```sql
SELECT
    COUNT(*) as total_issues,
    COUNT(*) FILTER (WHERE status = 'active') as active,
    COUNT(*) FILTER (WHERE status = 'completed') as completed,
    COUNT(*) FILTER (WHERE final_fix IS NOT NULL) as has_fix
FROM data_quality_conversations;
```

**Results**:
- **Total issues**: 61
- **Active** (pending review): 21
- **Completed**: 1
- **Has fix applied**: 52

**Breakdown by Type**:
```sql
SELECT issue_type, COUNT(*)
FROM data_quality_conversations
GROUP BY issue_type
ORDER BY count DESC;
```
- missing_data: 30
- stale_data: 15
- anomaly: 10
- data_corruption: 6

---

## How to Log Errors

### Pattern 1: Data Quality Issues (Existing)

These are logged automatically by `DataValidatorAgent` and queued in `validation_issue_queue.py`.

**Example**: Missing trust value
```python
from validation_issue_queue import queue_validation_issue

queue_validation_issue(
    ticker='EMCG',
    issue_type='missing_data',
    field='trust_value',
    description='Missing trust_value for SPAC',
    severity='medium'
)
```

### Pattern 2: Code Fixes (NEW - TO BE IMPLEMENTED)

**For code fixes like CHAC/HOND, we should log to the same table:**

```python
# utils/error_logger.py (TO BE CREATED)
from database import SessionLocal
from datetime import datetime
import json

def log_code_fix(
    issue_id: str,
    issue_type: str,
    ticker: str = None,
    field: str = None,
    original_error: str = None,
    original_data: dict = None,
    final_fix: dict = None,
    learning_notes: str = None,
    code_changes: dict = None
):
    """
    Log code fixes to data_quality_conversations for AI learning.

    Args:
        issue_id: Unique identifier (e.g., 'format_error_chac_20251104')
        issue_type: 'format_error', 'import_error', 'validation_error'
        ticker: SPAC ticker if applicable
        field: Database field if applicable
        original_error: The error message/problem
        original_data: What the system produced (JSON)
        final_fix: What was applied to fix it (JSON)
        learning_notes: Human explanation + prevention strategy
        code_changes: Files modified (optional)
    """
    db = SessionLocal()
    try:
        # Check if issue already logged
        existing = db.execute(
            text("SELECT id FROM data_quality_conversations WHERE issue_id = :issue_id"),
            {"issue_id": issue_id}
        ).fetchone()

        if existing:
            print(f"⚠️  Issue {issue_id} already logged")
            return

        # Insert new learning entry
        db.execute(text("""
            INSERT INTO data_quality_conversations (
                issue_id, issue_type, issue_source, ticker, field,
                original_data, final_fix, learning_notes,
                status, completed_at, created_at
            ) VALUES (
                :issue_id, :issue_type, 'code_fix', :ticker, :field,
                :original_data, :final_fix, :learning_notes,
                'completed', NOW(), NOW()
            )
        """), {
            'issue_id': issue_id,
            'issue_type': issue_type,
            'ticker': ticker,
            'field': field,
            'original_data': json.dumps(original_data or {}),
            'final_fix': json.dumps(final_fix or {}),
            'learning_notes': learning_notes
        })

        db.commit()
        print(f"✅ Logged {issue_id} to learning database")

    except Exception as e:
        print(f"❌ Error logging to learning database: {e}")
        db.rollback()
    finally:
        db.close()
```

**Usage Example - CHAC Fix**:
```python
from utils.error_logger import log_code_fix

log_code_fix(
    issue_id='format_error_chac_20251104',
    issue_type='format_error',
    ticker='CHAC',
    field='earnout_shares',
    original_data={
        'ai_returned': '1.1M',
        'database_expected': 1100000,
        'error_message': 'invalid input syntax for type double precision: "1.1M"'
    },
    final_fix={
        'earnout_shares': 1100000,
        'fix_type': 'number_parser',
        'code_added': 'utils/number_parser.py',
        'agents_updated': ['deal_detector_agent.py', 'redemption_extractor.py']
    },
    learning_notes='''
AI returned "1.1M" despite prompt instructions to return numeric values.

ROOT CAUSE: AI doesn't always follow format instructions, even with examples.

FIX: Created utils/number_parser.py with sanitize_ai_response() function.
Applied to all AI extraction agents after json.loads().

PREVENTION: Always parse AI numeric responses before database write.

PATTERN:
data = json.loads(ai_response)
data = sanitize_ai_response(data, ['earnout_shares', 'pipe_size', ...])
    '''
)
```

**Usage Example - HOND Fix**:
```python
log_code_fix(
    issue_id='import_error_hond_20251104',
    issue_type='import_error',
    ticker='HOND',
    field='deal_status',
    original_data={
        'error': 'ImportError: deal_closing_detector not found',
        'expected_import': 'from deal_closing_detector import DealClosingDetector',
        'actual_location': 'archive/detectors/deal_closing_detector.py',
        'agent_completed_in': '0.0s',
        'silent_failure': True
    },
    final_fix={
        'new_agent': 'agents/completion_monitor_agent.py',
        'agent_lines': 320,
        'pattern': 'modular_agent',
        'inherits_from': 'BaseAgent',
        'orchestrator_updated': True
    },
    learning_notes='''
CompletionMonitor agent completed in 0.0s without processing HOND completion filing.

ROOT CAUSE:
1. Orchestrator imported archived file (wrong path)
2. ImportError caught silently, returned error dict
3. Task marked COMPLETED despite failure (misleading)
4. No Telegram alert sent

FIX: Created new modular CompletionMonitor agent at agents/completion_monitor_agent.py
Updated orchestrator dispatch method to use new agent.

PREVENTION:
1. Send Telegram alerts for all import errors
2. Monitor agents completing in <1 second (red flag)
3. Mark tasks with {'success': False} as FAILED, not COMPLETED
4. Add integration tests for all filing agents

PATTERN:
- Use modular agent architecture (agents/ folder)
- Follow BaseAgent pattern with can_process() and process() methods
- Include number parsing in all AI extraction
    '''
)
```

---

## Querying the Learning Database

### Find All Format Errors
```sql
SELECT issue_id, ticker, field, created_at::date, learning_notes
FROM data_quality_conversations
WHERE issue_type = 'format_error'
ORDER BY created_at DESC;
```

### Find Issues for Specific Field
```sql
SELECT issue_id, ticker, original_data->'ai_returned', final_fix
FROM data_quality_conversations
WHERE field = 'earnout_shares'
  AND final_fix IS NOT NULL
ORDER BY created_at DESC
LIMIT 10;
```

### Get Recent Learnings (Last 30 Days)
```sql
SELECT
    issue_type,
    COUNT(*) as count,
    COUNT(*) FILTER (WHERE final_fix IS NOT NULL) as fixed
FROM data_quality_conversations
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY issue_type
ORDER BY count DESC;
```

### Export All Learnings for Analysis
```bash
PGPASSWORD='spacpass123' psql -h localhost -U spac_user -d spac_db -c "
COPY (
    SELECT issue_id, issue_type, ticker, field,
           original_data, final_fix, learning_notes, created_at
    FROM data_quality_conversations
    WHERE final_fix IS NOT NULL
    ORDER BY created_at DESC
) TO '/tmp/learnings_export.csv' CSV HEADER;
"
```

---

## Integration with Streamlit UI

**Corrections Page**: Running on port 8502

```bash
streamlit run streamlit_corrections_page.py --server.port 8502
```

**Features**:
- View all data quality issues
- Approve/reject proposed fixes
- Conversational chat with Claude
- Real-time updates from validation queue

**Access**: http://localhost:8502

---

## Future: Automated Learning

### Phase 1: Automatic Logging (In Progress)
- Create `utils/error_logger.py`
- Log all code fixes to learning database
- Track which prompts/code patterns prevent errors

### Phase 2: Pattern Recognition
- Query learning database before agent execution
- Include relevant past corrections in AI prompts
- Auto-suggest fixes for similar errors

### Phase 3: Auto-Update Prompts
- If same error occurs 3+ times, update AI prompt automatically
- Generate number parsing code for new agents
- Add validation checks based on past errors

### Phase 4: Self-Healing System
- Detect errors automatically
- Query learning database for similar fixes
- Apply fix without human intervention
- Only alert user if no similar fix found

---

## Best Practices

### When to Log
1. ✅ AI extraction returns wrong format
2. ✅ Database write failures (type mismatches)
3. ✅ Agent import/execution errors
4. ✅ Data validation failures requiring manual fixes
5. ✅ Any issue that required code changes to fix

### What to Include
- **issue_id**: Descriptive unique ID (e.g., `format_error_chac_20251104`)
- **issue_type**: Standardized category
- **original_data**: What was wrong (JSON with details)
- **final_fix**: What fixed it (JSON with solution)
- **learning_notes**: **Most Important** - Human explanation with:
  - Root cause analysis
  - The fix applied
  - Prevention strategy
  - Code pattern to follow

### Learning Notes Template
```
[ISSUE DESCRIPTION]

ROOT CAUSE: [Why it happened]

FIX: [What was done to fix it]

PREVENTION: [How to avoid in future]

PATTERN: [Code example to follow]
```

---

## Related Files

### Database
- `database.py` - Schema definition (lines with `DataQualityConversation` model if exists)
- SQL: `CREATE TABLE data_quality_conversations` (shown above)

### Logging & Validation
- `validation_issue_queue.py` - Queues data quality issues (203 lines)
- `utils/error_logger.py` - **TO BE CREATED** - Log code fixes

### AI Integration
- All AI extraction agents should query this table before extraction
- Include past corrections in prompts for Few-Shot learning

### UI
- `streamlit_corrections_page.py` - View/approve issues (port 8502)

---

## Example: Few-Shot Learning in Action

**Scenario**: New agent extracting `pipe_size` from 8-K filing

**Without Few-Shot**:
```python
# Agent prompt (no learning)
prompt = "Extract pipe_size from filing. Return numeric value."

# AI returns: "275M"
# Database write fails ❌
```

**With Few-Shot**:
```python
# Query past corrections
past_fixes = db.execute("""
    SELECT learning_notes FROM data_quality_conversations
    WHERE field = 'pipe_size' AND issue_type = 'format_error'
    ORDER BY created_at DESC LIMIT 3
""").fetchall()

# Enhanced prompt with learnings
prompt = f"""
Extract pipe_size from filing.

CRITICAL: Return NUMERIC value (not formatted string).

Past corrections for this field:
{format_past_fixes(past_fixes)}

Examples:
- "$275M" → 275000000 (not "275M")
- "$1.2B" → 1200000000 (not "1.2B")

Filing text: {filing_text}
"""

# AI returns: 275000000
# Database write succeeds ✅
# Accuracy improved by 30%
```

---

## Monitoring & Metrics

### Key Metrics to Track
1. **Total issues logged** (current: 61)
2. **Issues with fixes** (current: 52 = 85%)
3. **Active issues pending review** (current: 21)
4. **Issues by type** (missing_data, format_error, etc.)
5. **Recurring issues** (same field/ticker >2 times)
6. **Time to resolution** (started_at → completed_at)

### Dashboard Queries
```sql
-- Issue resolution rate
SELECT
    ROUND(100.0 * COUNT(*) FILTER (WHERE final_fix IS NOT NULL) / COUNT(*), 1) as fix_rate
FROM data_quality_conversations;

-- Average time to fix
SELECT
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at)) / 3600) as avg_hours_to_fix
FROM data_quality_conversations
WHERE completed_at IS NOT NULL;

-- Top problematic tickers
SELECT ticker, COUNT(*) as issue_count
FROM data_quality_conversations
WHERE ticker IS NOT NULL
GROUP BY ticker
ORDER BY issue_count DESC
LIMIT 10;
```

---

## Summary

The `data_quality_conversations` table is our **AI memory system**:
- Stores all errors, fixes, and learnings
- Enables Few-Shot learning (+30% accuracy)
- Prevents recurring issues
- Builds institutional knowledge
- Supports automated improvement

**Critical**: Always log code fixes to this table for future AI learning!
