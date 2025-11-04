# CLAUDE.md

**SPAC Research Platform** - Automated SEC filing monitoring, price tracking, deal detection, and AI-powered analysis.

---

## Tech Stack & Environment

**Stack**: Python, PostgreSQL, FastAPI, Streamlit, SQLAlchemy, DeepSeek AI

**Required Environment Variables** (.env):
```bash
DATABASE_URL=postgresql://spac_user:spacpass123@localhost:5432/spac_db
DEEPSEEK_API_KEY=sk-...           # For AI extraction and chat
TELEGRAM_BOT_TOKEN=...            # For alerts
TELEGRAM_CHAT_ID=...              # For alerts
```

**Database**: PostgreSQL via SQLAlchemy. Always use context managers or explicit session cleanup.

---

## Critical Database Fields

**`SPAC` table**: 102 columns. Key fields:

**Trust & Valuation**:
- `trust_value`: Per-share NAV (typically $10.00)
- `trust_cash`: Total dollars in trust account
- `premium`: **PRIMARY valuation metric** = `((price - trust_value) / trust_value) * 100`
- Always recalculate `premium` after price updates

**Deal Status**:
- `deal_status`: `SEARCHING` → `ANNOUNCED` → `COMPLETED`
- `deal_status_detail`: `RUMORED_DEAL` (70-84% confidence) | `CONFIRMED_DEAL` (85%+)
- `target`, `deal_value`, `announced_date`, `expected_close`

**Risk Levels**:
- `deal`: Has announced target
- `safe`: >6 months to deadline
- `urgent`: <90 days to deadline
- `expired`: Past deadline date

**Orchestrator Integration**:
- `accelerated_polling_until`: Enables fast SEC polling (5 min vs 15 min intervals)
- `rumored_target`, `rumor_confidence`, `rumor_detected_date`

**IPO Data**:
- `ipo_date`, `ipo_proceeds`, `deadline_date`, `unit_structure`, `unit_ticker`, `warrant_ticker`

→ **Full schema**: See `database.py` (102 columns documented)

---

## Key Files Quick Reference

**Core Orchestration**:
- `agent_orchestrator.py` - Main orchestration loop, task dispatching
- `agents/orchestrator_agent_base.py` - Base class for all agents

**Modular Agents** (`/agents/`):
- `deal_detector_agent.py` - 8-K deal detection with AI extraction
- `completion_monitor_agent.py` - Deal closing detection (8-K Item 2.01)
- `price_monitor_agent.py` - Price updates & spike detection
- `risk_analysis_agent.py` - Risk assessment & deadline alerts
- `data_validator_agent.py` - Data quality validation (1,047 lines)
- `redemption_extractor.py` - Shareholder redemption tracking

**Utilities**:
- `utils/number_parser.py` - **CRITICAL**: Sanitize AI numeric responses
- `utils/target_validator.py` - Validate target company names (prevent sponsor/trustee false positives)
- `orchestrator_trigger.py` - Trigger system for rumors, deals, price spikes

**Data Sources**:
- `agents/data_source_reference.py` - Field → source mapping, precedence rules
- `agents/base_agent.py` - Base agent with data source validation helpers

**Database & Models**:
- `database.py` - SPAC model (102 columns), SessionLocal, init_db()

**UI & APIs**:
- `streamlit_app.py` - Dashboard (AI chat, live deals, analytics)
- `main.py` - FastAPI REST API

→ **Full file listing**: See `docs/core/DOCUMENTATION_INDEX.md`

---

## Common Commands

**Initial Setup**:
```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database
python3 -c "from database import init_db; init_db()"

# Load initial SPAC data
python3 load_all_155_spacs.py
```

**Daily Operations**:
```bash
# Update prices (auto-runs spike monitor)
python3 price_updater.py

# Run orchestrator (monitors SEC filings)
python3 agent_orchestrator.py

# Check orchestrator status
python3 agent_orchestrator.py --status

# Manual deal monitoring
python3 deal_monitor_enhanced.py
```

**Data Quality**:
```bash
# Verify trust data
python3 verify_trust_data.py

# Check for duplicates
python3 check_duplicates.py

# Find SPACs missing key fields
python3 -c "from database import SessionLocal, SPAC; db=SessionLocal(); print([s.ticker for s in db.query(SPAC).filter(SPAC.ipo_date==None).all()])"
```

**Services**:
```bash
# Streamlit dashboard
streamlit run streamlit_app.py

# FastAPI server
uvicorn main:app --reload --port 8000

# Streamlit systemd service
sudo systemctl start streamlit
sudo systemctl status streamlit
```

→ **Full operations guide**: See `docs/operations/MORNING_CHECKLIST.md`

---

## Critical Coding Patterns

### 1. Always Use Number Parser (MANDATORY)

**After ANY AI extraction**, sanitize numeric fields to prevent format errors like `"1.1M"` → database crash.

```python
from utils.number_parser import sanitize_ai_response

# After AI extraction
data = json.loads(response.choices[0].message.content)

# ALWAYS sanitize numeric fields before database write
numeric_fields = ['deal_value', 'pipe_size', 'earnout_shares', 'shares_redeemed', 'trust_cash']
data = sanitize_ai_response(data, numeric_fields)

# Now safe to write to database
spac.deal_value = data.get('deal_value')
```

**Why**: AI returns formatted strings (`"275M"`, `"1.1M"`) despite prompts. Three-layer defense:
1. Clear AI prompts with numeric examples
2. `sanitize_ai_response()` parses all numeric fields
3. Database write protected

→ **Details**: See `docs/AI_NUMBER_FORMAT_FIX.md` and `utils/number_parser.py`

### 2. Error Logging for AI Learning

**ALWAYS log errors** to `data_quality_conversations` table for Few-Shot learning:

```python
# When fixing any error
from database import SessionLocal
from datetime import datetime
import json

db = SessionLocal()
try:
    db.execute("""
        INSERT INTO data_quality_conversations (
            issue_id, issue_type, issue_source, ticker, field,
            original_data, proposed_fix, final_fix, learning_notes, created_at
        ) VALUES (
            :issue_id, :issue_type, :issue_source, :ticker, :field,
            :original_data, :proposed_fix, :final_fix, :learning_notes, :created_at
        )
    """, {
        'issue_id': f"format_error_{ticker}_{datetime.now().strftime('%Y%m%d')}",
        'issue_type': 'format_error',  # or 'import_error', 'validation_error'
        'issue_source': 'ai_detected',
        'ticker': ticker,
        'field': 'earnout_shares',
        'original_data': json.dumps({'ai_returned': '1.1M', 'database_expected': 1100000}),
        'proposed_fix': json.dumps({'earnout_shares': 1100000}),
        'final_fix': json.dumps({'earnout_shares': 1100000}),
        'learning_notes': 'AI returned "1.1M" despite prompt instructions. Added number parser.',
        'created_at': datetime.now()
    })
    db.commit()
finally:
    db.close()
```

**Benefits**: AI learns from past mistakes, prompts improve automatically, similar errors prevented.

→ **Query logged fixes**: `SELECT * FROM data_quality_conversations ORDER BY created_at DESC`

### 3. Modular Agent Structure

**All agents inherit from `OrchestratorAgentBase` or `BaseAgent`**:

```python
from agents.orchestrator_agent_base import OrchestratorAgentBase

class MyAgent(OrchestratorAgentBase):
    """Agent description"""

    def execute(self, task):
        self._start_task(task)

        try:
            # Agent logic here
            result = self._do_work(task)
            self._complete_task(task, result)
        except Exception as e:
            self._fail_task(task, str(e))

        return task
```

**Benefits**: Independently testable, clear separation of concerns, easy to extend.

→ **Details**: See `docs/core/AGENTIC_AI_ORCHESTRATION.md`

### 4. Data Source Precedence (CRITICAL)

**8-K is PRIMARY for event-based data (deals, PIPEs, extensions)**
**10-Q/10-K is PRIMARY for periodic data (trust balances, quarterly reports)**

```python
from agents.data_source_reference import is_primary_source, should_process_filing_for_field

# Check if filing is primary source for field
if is_primary_source('target', '8-K'):
    # Extract deal data (8-K is timely)
    pass

if is_primary_source('trust_cash', '10-Q'):
    # Extract trust balance (10-Q is authoritative)
    pass
```

**Key Rule**: 8-K filed within 0-4 days of event → most timely. 10-Q filed 30-45 days after quarter → most accurate for periodic data.

→ **Full precedence rules**: See `agents/data_source_reference.py` and `docs/core/DATA_SOURCES_AND_PRIORITY.md`

### 5. Target Validation

**Always validate target company names** to prevent sponsor/trustee false positives:

```python
from utils.target_validator import is_valid_target_name

target = "Voyager Acquisition Sponsor Holdco LLC"
if not is_valid_target_name(target):
    print(f"❌ Invalid target: {target} (contains 'sponsor')")
    # Don't save, clear field, or investigate further
```

**Rejected keywords**: `sponsor`, `acquisition corp`, `acquisition company`, `trustee`, `representative`

→ **Integration points**: `agents/deal_detector_agent.py` (lines 216-241), `target_tracker.py` (lines 92-116)

### 6. SEC EDGAR Best Practices

**Rate Limiting**: 10 requests/second max (SEC enforced)
**User-Agent**: Must include contact email (`SPAC Research Platform admin@spacresearch.com`)

**Key Filing Types**:
- `8-K`: Current events (deals, extensions, completions) - Event-based (0-4 days)
- `S-1`, `424B4`: IPO registration/prospectus - One-time
- `10-Q`, `10-K`: Quarterly/annual reports - Periodic (30-45 days)
- `DEFM14A`: Proxy statements (shareholder votes) - Scheduled (20+ days before vote)

**Deal Detection Keywords** (8-K):
- ✅ "entered into a definitive agreement", "business combination agreement", "merger agreement"
- ❌ False positives: "exploring strategic alternatives", "in discussions with"

→ **Full routing map**: See `docs/core/SEC_FILING_ROUTING_MAP.md`

### 7. Premium Calculation

**Always recalculate premium after price updates**:

```python
if spac.price and spac.trust_value:
    spac.premium = ((spac.price - spac.trust_value) / spac.trust_value) * 100
```

**Premium Thresholds**:
- `< 2%`: Near NAV (minimal downside risk)
- `2-10%`: Moderate premium
- `10-30%`: High premium (market optimism)
- `> 30%`: Very high premium (strong deal excitement)

### 8. Orchestrator Trigger System

**Three trigger types** for adaptive monitoring:

```python
from orchestrator_trigger import trigger_deal_rumor, trigger_confirmed_deal, trigger_price_spike

# 1. Deal rumor (70-84% confidence) → 48h accelerated polling
trigger_deal_rumor(ticker='BLUW', target='TechCorp', confidence=80, source='reddit')

# 2. Confirmed deal (85%+ confidence) → Route to orchestrator
trigger_confirmed_deal(ticker='CEP', target='Confirmed Inc', deal_value=500)

# 3. Price spike (≥10%) → 24h accelerated polling + investigation
trigger_price_spike(ticker='XPND', old_price=10.05, new_price=11.20, change_pct=11.4)
```

**Accelerated polling**: 5 min intervals instead of 15 min when `accelerated_polling_until` is set.

→ **Details**: See `orchestrator_trigger.py` and `docs/PRICE_SPIKE_INVESTIGATION_FLOW.md`

---

## Workflow Rules

### Git Push Policy

**ASK USER BEFORE PUSHING** for:
- ✅ Major code changes (features, bug fixes, refactors)
- ✅ New agent implementations
- ✅ Database schema changes
- ✅ Breaking changes
- ✅ Major documentation updates
- ✅ Configuration changes

**Can push without asking**:
- Minor typos or formatting fixes
- Small documentation clarifications
- Log file updates

**Pattern**:
1. Make changes
2. Commit locally: `git add -A && git commit -m "..."`
3. **Ask user**: "Should I push these changes to GitHub?"
4. If yes: `git push origin main`
5. Confirm with commit hash

### Testing Patterns

**Test individual components**:
```python
# Test SEC scraper on one SPAC
from sec_data_scraper import SPACDataEnricher
enricher = SPACDataEnricher()
enricher.enrich_spac_from_sec("CEP")

# Test AI chat agent
from spac_agent import SPACAIAgent
agent = SPACAIAgent()
result = agent.chat("Show me Goldman Sachs SPACs with premium over 15%", [])

# Test price fetcher
from price_updater import PriceUpdater
updater = PriceUpdater(source='yfinance')
price_data = updater.get_price_yfinance("CEP")
```

### Database Queries

**Always use context managers**:
```python
from database import SessionLocal, SPAC

db = SessionLocal()
try:
    spacs = db.query(SPAC).filter(SPAC.deal_status == 'ANNOUNCED').all()
    # Process spacs
finally:
    db.close()
```

### Agent Failure Monitoring

**Red flags** to alert on:
1. Agent completes in <1 second (likely import error)
2. Silent failures (exception caught but task marked COMPLETED)
3. Missing critical fields after extraction (NULL when expected value)

→ **Case study**: See `docs/HOND_COMPLETION_DETECTION_FAILURE.md`

---

## Documentation Links

### Core Architecture
- **[DOCUMENTATION_INDEX.md](docs/core/DOCUMENTATION_INDEX.md)** - Master index of all 156+ docs
- **[AGENTIC_AI_ORCHESTRATION.md](docs/core/AGENTIC_AI_ORCHESTRATION.md)** - Complete system overview (11 AI agents)
- **[ORCHESTRATOR_ARCHITECTURE_FINAL.md](docs/core/ORCHESTRATOR_ARCHITECTURE_FINAL.md)** - Orchestrator design patterns
- **[SEC_FILING_ROUTING_MAP.md](docs/core/SEC_FILING_ROUTING_MAP.md)** - Filing type → agent routing map
- **[REALTIME_SYSTEM_ARCHITECTURE.md](docs/core/REALTIME_SYSTEM_ARCHITECTURE.md)** - Real-time monitoring (15-min polling)

### Data Sources & Precedence
- **[DATA_SOURCES_AND_PRIORITY.md](docs/core/DATA_SOURCES_AND_PRIORITY.md)** - Field → source mapping (110+ fields)
- **[agents/data_source_reference.py](agents/data_source_reference.py)** - Precedence rules in code (650 lines)
- **[DATA_SOURCE_MATRIX.md](docs/DATA_SOURCE_MATRIX.md)** - Comprehensive documentation
- **[FILING_DATA_PRECEDENCE.md](docs/FILING_DATA_PRECEDENCE.md)** - Detailed precedence rules

### Data Quality & Validation
- **[DATA_QUALITY_AND_VALIDATION.md](docs/core/DATA_QUALITY_AND_VALIDATION.md)** - Data quality system overview
- **[AUTONOMOUS_DATA_QUALITY_SYSTEM.md](docs/AUTONOMOUS_DATA_QUALITY_SYSTEM.md)** - AI-powered validation workflow
- **[INVESTIGATION_AGENT_DESIGN.md](docs/INVESTIGATION_AGENT_DESIGN.md)** - Auto-fix architecture

### Learning & Fixes
- **Database query**: `SELECT * FROM data_quality_conversations ORDER BY created_at DESC` - All logged fixes
- **[ALL_LEARNINGS_SUMMARY.md](docs/core/ALL_LEARNINGS_SUMMARY.md)** - System learnings (23+ lessons)
- **[AI_NUMBER_FORMAT_FIX.md](docs/AI_NUMBER_FORMAT_FIX.md)** - Number parsing solution (CHAC case study)
- **[HOND_COMPLETION_DETECTION_FAILURE.md](docs/HOND_COMPLETION_DETECTION_FAILURE.md)** - Import error case study
- **[ERROR_REPORTING_GUIDE.md](docs/ERROR_REPORTING_GUIDE.md)** - Error logging best practices

### Agent Development
- **[AGENT_REFACTOR_PROOF_OF_CONCEPT.md](docs/AGENT_REFACTOR_PROOF_OF_CONCEPT.md)** - Modular agent pattern
- **[IPO_DETECTOR_IMPLEMENTATION.md](docs/core/IPO_DETECTOR_IMPLEMENTATION.md)** - IPO graduation system
- **[agents/orchestrator_agent_base.py](agents/orchestrator_agent_base.py)** - Base class (58 lines)

### Operations
- **[MORNING_CHECKLIST.md](docs/operations/MORNING_CHECKLIST.md)** - Daily operations checklist
- **[RECOMMENDED_CRON_SCHEDULE.md](docs/operations/RECOMMENDED_CRON_SCHEDULE.md)** - Cron job schedule
- **[DEPLOYMENT_SUMMARY.md](docs/DEPLOYMENT_SUMMARY.md)** - Deployment guide

### Specific Features
- **[EXTRACTION_AGENT_LEARNING_DESIGN.md](docs/EXTRACTION_AGENT_LEARNING_DESIGN.md)** - Few-Shot learning system
- **[LEARNING_DATABASE.md](docs/LEARNING_DATABASE.md)** - Learning database design
- **[PRICE_SPIKE_INVESTIGATION_FLOW.md](docs/PRICE_SPIKE_INVESTIGATION_FLOW.md)** - Price spike workflow
- **[TELEGRAM_AGENT_ARCHITECTURE.md](docs/TELEGRAM_AGENT_ARCHITECTURE.md)** - Centralized Telegram system

---

## Quick Use Cases

**"I want to understand how the system works"**
→ Start: `AGENTIC_AI_ORCHESTRATION.md` → `ORCHESTRATOR_ARCHITECTURE_FINAL.md` → `SEC_FILING_ROUTING_MAP.md`

**"I want to add a new data field"**
→ Start: `DATA_SOURCES_AND_PRIORITY.md` (find source) → `SEC_FILING_ROUTING_MAP.md` (find agent) → Modify agent

**"I want to understand data quality issues"**
→ Query: `SELECT * FROM data_quality_conversations` → `ALL_LEARNINGS_SUMMARY.md` → `INVESTIGATION_AGENT_DESIGN.md`

**"I want to deploy the system"**
→ Start: `DEPLOYMENT_SUMMARY.md` → `RECOMMENDED_CRON_SCHEDULE.md` → `MORNING_CHECKLIST.md`

**"I encountered an error"**
→ Check: `data_quality_conversations` table → `ERROR_REPORTING_GUIDE.md` → Log the fix

---

**Last Updated**: 2025-11-04
**Maintainer**: Claude Code AI System
