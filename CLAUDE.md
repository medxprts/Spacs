# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

SPAC Research Platform - A comprehensive system for tracking Special Purpose Acquisition Companies (SPACs), including automated SEC filing monitoring, price tracking, deal detection, and AI-powered analysis.

**Tech Stack**: Python, PostgreSQL, FastAPI, Streamlit, SQLAlchemy, DeepSeek AI

## Database Architecture

### Core Model (database.py)
The `SPAC` table contains **102 columns** tracking all aspects of a SPAC lifecycle. Critical fields:

**Trust Account Mechanics**:
- `trust_value` (Numeric): Per-share NAV, typically $10.00 at IPO
- `trust_cash` (Float): Total dollars in trust account
- `premium` (Float): Percentage above/below NAV - **primary metric** for valuation
- Formula: `premium = ((price - trust_value) / trust_value) * 100`

**Deal Status Workflow**:
- `SEARCHING`: Pre-deal SPAC looking for target
- `ANNOUNCED`: Deal announced, pending shareholder vote
- Status transitions tracked via `announced_date`, `expected_close`, `shareholder_vote_date`
- **NEW**: `deal_status_detail` provides granular tracking:
  - `RUMORED_DEAL`: Unconfirmed deal detected from news/Reddit (confidence 70-84%)
  - `CONFIRMED_DEAL`: Deal validated by SEC filing or high-confidence news (confidence 85%+)
- **NEW**: `accelerated_polling_until` enables temporary fast SEC polling (5 min intervals) for rumored deals and price spikes

**Risk Classification**:
- `deal`: Has announced target
- `safe`: >6 months to deadline
- `urgent`: <90 days to deadline
- `expired`: Past deadline date

**Key Columns to Update**:
When scraping SEC filings, prioritize: `ipo_date`, `ipo_proceeds`, `deadline_date`, `trust_cash`, `unit_ticker`, `warrant_ticker`, `unit_structure`, `announced_date`, `target`, `deal_value`

**Orchestrator Integration Columns** (added 2025-10-10):
- `deal_status_detail`: Granular status ('RUMORED_DEAL', 'CONFIRMED_DEAL')
- `rumored_target`: Target company before confirmation
- `rumor_confidence`: AI confidence score 0-100
- `rumor_detected_date`: When rumor first detected
- `accelerated_polling_until`: Timestamp for fast SEC polling (48h for rumors, 24h for price spikes)

### Database Connection
Uses PostgreSQL via `DATABASE_URL` from .env. Connection pooling via SQLAlchemy SessionLocal. Always use context managers or explicit session cleanup.

## Core Components

### 1. SEC Data Scraper (sec_data_scraper.py)
**Purpose**: Scrapes SEC EDGAR for IPO details, deal announcements, and trust account data.

**AI-Enhanced Filing Analysis**:
- Uses DeepSeek API to extract structured data from 8-K, S-1, and 424B press releases
- AI validates IPO "closing" vs "pricing" announcements (avoids premature data)
- Extracts: IPO date, proceeds, unit structure, warrant terms, deadline dates

**Key Methods**:
- `get_cik()`: Looks up CIK number from company name
- `_validate_ipo_press_release()`: Filters for closing (not pricing) announcements
- `extract_with_ai()`: Uses DeepSeek to parse unstructured filing text
- `enrich_spac_from_sec()`: Main orchestrator - fetches and parses all filings

**Deadline Calculation Logic**:
IPO date + 18-24 months (varies by SPAC charter). Uses `relativedelta` for precise date math.

**Usage**:
```bash
python3 sec_data_scraper.py  # Enriches all SPACs in database
```

### 2. Price Updater (price_updater.py)
**Multi-Source Architecture**:
- Primary: Yahoo Finance (yfinance) - free, reliable
- Fallback: Alpha Vantage, Polygon.io (requires API keys)
- Fetches common, unit, and warrant tickers

**Premium Calculation**:
Always recalculate `premium` after price updates: `(price - trust_value) / trust_value * 100`

**Warrant Ticker Detection**:
Tries multiple suffixes: `W`, `WS`, `.W`, `.WS`, `-WT`, `.WT`, `+`, `/WS`

**NEW - Automatic Price Spike Detection** (added 2025-10-10):
- After updating all prices, automatically runs `PriceSpikeMonitor`
- Detects price changes ≥±5% (configurable threshold)
- Triggers orchestrator investigation via `trigger_price_spike()`
- Sends Telegram alerts for significant movements
- Enables 24-hour accelerated SEC polling for spikes ≥10%

**Usage**:
```bash
python3 price_updater.py        # Update all SPAC prices + auto spike detection
python3 warrant_price_fetcher.py  # Update warrant/unit prices
python3 price_spike_monitor.py --threshold 5  # Manual spike check
```

### 3. Deal Monitor (deal_monitor_enhanced.py)
**Purpose**: Scans recent 8-K filings for new deal announcements.

**Process**:
1. Query database for SPACs with `deal_status='SEARCHING'`
2. Fetch last 180 days of 8-K filings via SEC API
3. Parse for keywords: "definitive agreement", "business combination", "merger"
4. Extract target company name, deal value, expected close date
5. Update SPAC record: `deal_status='ANNOUNCED'`, set target/dates
6. Send Telegram notification if configured

**Usage**:
```bash
python3 deal_monitor_enhanced.py
```

### 4. Streamlit Dashboard (streamlit_app.py)
**Features**:
- **AI Chat**: DeepSeek-powered natural language queries (e.g., "Show Goldman SPACs >15% premium")
- **Live Deals**: Filter/sort announced deals by premium, banker, sector
- **Pre-Deal SPACs**: Track SPACs still searching, sorted by urgency
- **Analytics**: Market-wide stats, banker distribution, premium histograms

**Data Loading**:
Uses `@st.cache_data(ttl=300)` for 5-minute cache. Queries database on each refresh.

**AI Agent Integration** (spac_agent.py):
- Function calling interface to database
- Available functions: `search_spacs()`, `get_market_stats()`, `get_top_spacs()`, `compare_bankers()`
- Model: DeepSeek Chat (OpenAI-compatible API)

**Deployment**:
```bash
streamlit run streamlit_app.py --server.port 8501
# Or use systemd service (deploy_streamlit.sh)
```

### 5. FastAPI Backend (main.py)
REST API with endpoints:
- `GET /spacs` - List/filter SPACs (supports premium range, banker, deal status, search)
- `GET /spacs/{ticker}` - Single SPAC details
- `GET /analytics/summary` - Market-wide statistics
- `POST /alerts` - Create price/deal alerts

**CORS**: Configured for open access (`allow_origins=["*"]`)

### 6. Autonomous Data Quality System
**AI-powered data quality monitoring with conversational approval workflow via Telegram.**

**Full Documentation**: See [AUTONOMOUS_DATA_QUALITY_SYSTEM.md](AUTONOMOUS_DATA_QUALITY_SYSTEM.md)

**Architecture**:
1. **Agent Orchestrator** (`agent_orchestrator.py`)
   - Detects ALL data quality issues via `DataValidatorAgent`
   - Routes critical issues to Investigation Agent for AI analysis
   - Sends Telegram alerts with proposed fixes
   - Conversational approval workflow (chat with Claude via Telegram)
   - Auto-applies approved fixes

2. **Target Validator** (`utils/target_validator.py`)
   - Validates target company names using keyword filtering
   - Prevents sponsor/trustee entities from being identified as targets
   - Example: Rejects "Voyager Acquisition Sponsor Holdco LLC" (contains 'sponsor')
   - Integrated into deal_detector_agent.py and target_tracker.py

3. **Investigation Agent** (`investigation_agent.py`)
   - Generates AI-powered hypotheses for anomalies
   - Suggests fixes with confidence scores
   - Documents root causes and prevention strategies
   - Uses DeepSeek AI for analysis

4. **Telegram Conversational Interface** (`telegram_approval_listener.py`)
   - Monitors Telegram for data quality issue responses
   - **Interactive chat**: Ask questions, request changes, review proposed fixes
   - **Preview changes**: See exactly what will be modified before approval
   - **Learning log**: Captures conversation for future improvements
   - Applies fixes after conversational approval

**Two Types of Data Quality Issues**:
1. **Missing Data**: Fields not populated (e.g., missing IPO date, trust value)
   - Investigation Agent searches SEC filings to find missing data
   - Proposes extraction from specific filing sections

2. **Incorrect Data**: Fields populated with wrong values (e.g., invalid target names, wrong dates)
   - Investigation Agent identifies root cause (extraction bug, parsing error)
   - Proposes correction and prevention strategy

**Conversational Workflow**:
```
Data Issue Detected → AI Investigation → Telegram Alert
                                              ↓
                              "Show me the proposed changes"
                                              ↓
                              Claude shows before/after diff
                                              ↓
                         "Change the target to XYZ instead"
                                              ↓
                              Claude updates proposal
                                              ↓
                                     "APPROVE"
                                              ↓
                              Fix applied, logged for learning
```

**Integration Points**:
- **agent_orchestrator.py**: Main orchestration with DataValidatorAgent
- **deal_detector_agent.py**: Validates targets before saving (lines 216-241)
- **target_tracker.py**: Validates all target updates (lines 92-116)
- **deal_data_validator.py**: Flags invalid targets in daily validation

**Example Conversation**:
```
Bot: 🔍 Data Quality Issue: Invalid target for VACH
     AI suggests: Clear target (sponsor entity detected)
     Affected: target="Voyager Acquisition Sponsor Holdco LLC"

You: Show me what will change

Bot: Changes:
     target: "Voyager Acquisition Sponsor..." → NULL
     deal_status: "ANNOUNCED" → "SEARCHING"

You: Actually, set target to "Voyager Space"

Bot: Updated proposal:
     target: "Voyager Acquisition Sponsor..." → "Voyager Space"
     deal_status: "ANNOUNCED" (no change)

You: APPROVE

Bot: ✅ Fix applied successfully
     Logged conversation for learning
```

**Modular Agent Architecture** (Refactored October 2025):

The orchestrator uses a **modular agent architecture** where agents are separate, independently testable modules:

**File Structure**:
```
/agents/
├── orchestrator_agent_base.py    # Base class for task agents (58 lines)
├── price_monitor_agent.py         # Price updates & spike detection
├── risk_analysis_agent.py         # Risk assessment & deadline alerts
├── deal_hunter_agent.py            # SEC filing deal detection
├── vote_tracker_agent.py           # Shareholder vote tracking
├── deadline_extension_agent.py    # Extension detection
├── data_validator_agent.py        # Data quality validation (1,047 lines)
├── data_quality_fixer_agent.py    # Auto-fixes type/date errors
├── pre_ipo_duplicate_checker_agent.py  # Pre-IPO vs main table check
└── premium_alert_agent.py         # Premium threshold monitoring
```

**orchestrator_agent_base.py** (base class):
```python
from agents.orchestrator_agent_base import OrchestratorAgentBase

class MyAgent(OrchestratorAgentBase):
    """Custom agent description"""

    def execute(self, task):
        self._start_task(task)

        try:
            # Agent logic here
            result = {'success': True}
            self._complete_task(task, result)
        except Exception as e:
            self._fail_task(task, str(e))

        return task
```

**Benefits of Modular Architecture**:
- ✅ **Independently testable**: Each agent can be tested in isolation
- ✅ **Smaller files**: Orchestrator reduced from 4,093 → 2,458 lines (40% reduction)
- ✅ **Clear separation**: Agent logic separated from orchestration logic
- ✅ **Easy to extend**: Add new agents by creating a new file in `/agents/`
- ✅ **Maintainability**: Each agent is self-contained with clear responsibilities

**How Orchestrator Imports Agents**:
```python
# In agent_orchestrator.py __init__
from agents.price_monitor_agent import PriceMonitorAgent
from agents.risk_analysis_agent import RiskAnalysisAgent
from agents.deal_hunter_agent import DealHunterAgent
# ... etc

self.agents = {
    'price_monitor': PriceMonitorAgent('price_monitor', self.state_manager),
    'risk_analysis': RiskAnalysisAgent('risk_analysis', self.state_manager),
    # ... etc
}
```

**Core Metrics** (as of October 2025):
- **Orchestrator**: 2,458 lines (down from 4,093)
- **Modular agents**: 9 agents extracted to `/agents/` folder
- **Total agent code**: ~3,400 lines in modular files
- **Coverage**: 75% of agents are modular (9/12)

**Remaining embedded agents** (to be extracted):
- WebResearchAgent, SignalMonitorAgent, TelegramAgent (wrapper agents)

### 7. Orchestrator Trigger System
**Integrated event-driven system that connects external monitors (news, Reddit, price) with the agent orchestrator for automated investigation and accelerated SEC polling.**

**Architecture Overview**:
External signals → `orchestrator_trigger.py` → Database updates → SEC filing monitor → Agent orchestrator

**Core Module**: `orchestrator_trigger.py`

**Three Trigger Types**:

1. **Deal Rumor Trigger** (`trigger_deal_rumor()`)
   - **When**: Reddit leak, news article, or Twitter mentions potential deal
   - **Actions**:
     - Updates database: `deal_status_detail='RUMORED_DEAL'`, sets `rumored_target`, `rumor_confidence`
     - Enables **48-hour accelerated SEC polling** (polls every 5 min instead of 15 min)
     - Sends Telegram alert marked as "⚠️ DEAL RUMOR DETECTED"
   - **Confidence Thresholds**: 70-84% = rumor, 85%+ = confirmed deal

2. **Confirmed Deal Trigger** (`trigger_confirmed_deal()`)
   - **When**: High-confidence news article or SEC filing validates deal
   - **Actions**:
     - Updates database: `deal_status='ANNOUNCED'`, clears rumor fields
     - Disables accelerated polling (no longer needed)
     - Sends Telegram alert marked as "🎯 DEAL CONFIRMED"
     - Routes to agent orchestrator for full processing (S-4 analysis, etc.)
   - **Rumor Confirmation**: If rumor existed, alert includes "✅ Rumor Confirmed!"

3. **Price Spike Trigger** (`trigger_price_spike()`)
   - **When**: Price change ≥5% detected during price update
   - **Actions**:
     - For spikes ≥10%: Enables **24-hour accelerated SEC polling**
     - Sends Telegram alert with price details and investigation status
     - TODO: Triggers orchestrator to check recent filings, news, Reddit
   - **Investigation Plan**: Auto-scan news, Reddit, filings to identify cause

**Integrated Monitors**:

1. **Reddit Sentiment Tracker** (`reddit_sentiment_tracker.py`)
   - Scans r/SPACs daily discussion for deal leaks
   - Confidence scoring based on mention count, bullish ratio, speculation keywords
   - **Integration** (lines 531-538): Calls `trigger_deal_rumor()` for confidence ≥70%

2. **News API Monitor** (via `deal_signal_aggregator.py`)
   - AI validates news articles for deal announcements
   - **Integration** (lines 226-245):
     - Confidence 85%+ → `trigger_confirmed_deal()`
     - Confidence 70-84% → `trigger_deal_rumor()`

3. **Price Spike Monitor** (`price_spike_monitor.py`)
   - Runs after `price_updater.py` completes
   - Detects price changes ≥±5%
   - **Integration**: Calls `trigger_price_spike()` for each spike

**SEC Filing Monitor Integration** (`sec_filing_monitor.py`):
- Calls `get_accelerated_polling_tickers()` each iteration
- Adaptive sleep intervals:
  - **Normal mode**: 15 minutes (900s)
  - **Accelerated mode**: 5 minutes (300s) when rumors/spikes detected
- Displays: "🚀 Accelerated polling enabled for 2 ticker(s): BLUW, CCCX"

**Database Schema** (New Columns):
```sql
deal_status_detail VARCHAR(50)           -- 'RUMORED_DEAL', 'CONFIRMED_DEAL'
rumored_target VARCHAR(255)              -- Target before confirmation
rumor_confidence INTEGER                 -- 0-100 confidence score
rumor_detected_date DATE                 -- When rumor first detected
accelerated_polling_until TIMESTAMP      -- Enable fast polling until this time
```

**Usage Examples**:
```bash
# Test rumor trigger
python3 orchestrator_trigger.py --test-rumor --ticker BLUW

# Test confirmed deal trigger
python3 orchestrator_trigger.py --test-confirmed --ticker CEP

# Check which tickers have accelerated polling
python3 orchestrator_trigger.py
# Output: Tickers with accelerated polling: ['BLUW', 'CCCX']

# Run price spike monitor
python3 price_spike_monitor.py --threshold 5  # Alert for ±5% moves
```

**Workflow Example**:
1. Reddit user posts: "BLUW rumored to merge with TechCorp"
2. Reddit monitor detects leak, confidence 85%
3. `trigger_deal_rumor()` called → Database updated, accelerated polling enabled
4. Telegram alert: "⚠️ DEAL RUMOR DETECTED - BLUW → TechCorp (85%)"
5. SEC monitor wakes up every 5 minutes instead of 15 minutes
6. 8-K filed 6 hours later → SEC monitor detects it immediately
7. `trigger_confirmed_deal()` called → "🎯 DEAL CONFIRMED - Rumor was accurate!"
8. Accelerated polling disabled, routed to agent orchestrator for full S-4 analysis

**Key Files**:
- `orchestrator_trigger.py` - Core trigger functions (261 lines)
- `price_spike_monitor.py` - Price movement detection (120 lines)
- `reddit_sentiment_tracker.py` - Reddit leak detection (integrated at line 531)
- `deal_signal_aggregator.py` - News/signal validation (integrated at line 226)
- `sec_filing_monitor.py` - Adaptive polling (accelerated check at line 432)
- `price_updater.py` - Auto-runs spike monitor after updates (line 472)

### 8. Telegram Agent (telegram_agent.py)
**Centralized Telegram communication system integrated with the orchestrator for all platform notifications and interactive workflows.**

**Architecture**: All agents communicate via Telegram through the orchestrator's `TelegramAgent`, eliminating code duplication and providing unified messaging.

```
┌─────────────────────────────────────────┐
│          ORCHESTRATOR                    │
│  ┌──────────┐  ┌──────────┐  ┌────────┐│
│  │Data      │  │Deal      │  │Price   ││
│  │Validator │  │Hunter    │  │Monitor ││
│  └────┬─────┘  └────┬─────┘  └───┬────┘│
│       └─────────────┴────────────┘      │
│                     │                    │
│            ┌────────▼──────────┐        │
│            │ TelegramAgent     │        │
│            │    Wrapper        │        │
│            └────────┬──────────┘        │
└─────────────────────┼───────────────────┘
                      │
              ┌───────▼───────────┐
              │  TelegramAgent    │
              │  (Core Library)   │
              └───────┬───────────┘
                      │
              ┌───────▼───────────┐
              │ Telegram Bot API  │
              └───────────────────┘
```

**Core Features**:
- **Unified Messaging**: Single source of truth for all Telegram communications
- **Task-Based Architecture**: All Telegram operations tracked by orchestrator (retryable, logged)
- **Conversational Workflows**: Interactive issue review with AI-powered responses
- **HTML Formatting**: Safe message formatting with automatic HTML escaping
- **Queue Management**: Sequential processing of validation issues with user approval

**TelegramAgent Core Library** (`telegram_agent.py`, 260 lines):

**Key Methods**:
- `send_message(text, parse_mode='HTML')` - Send formatted messages
- `get_updates(timeout=30)` - Poll for new messages via long polling
- `wait_for_response(timeout_minutes=60)` - Block until user responds
- `queue_validation_issues(issues)` - Queue data quality issues for review
- `process_user_command(text, db_session)` - Parse user commands (approve/skip/chat)
- `generate_ai_response(user_message, context)` - DeepSeek-powered conversational responses

**State Management**:
- Tracks `last_update_id` to avoid duplicate message processing
- Persists state to `.telegram_listener_state.json`
- Conversation history stored in `data_quality_conversations` table

**TelegramAgentWrapper** (in `agent_orchestrator.py`):

Orchestrator-compatible wrapper supporting these task types:

| Task Type | Purpose | Parameters |
|-----------|---------|------------|
| `send_message` | Send simple message | `{'text': 'Message'}` |
| `send_alert` | Send formatted alert | `{'alert_text': '⚠️ Alert!'}` |
| `queue_validation_issues` | Queue issues for review | `{'issues': [issue1, ...]}` |
| `wait_for_response` | Wait for user input | `{'timeout_minutes': 60}` |

**Usage Example - Any Agent Sending Messages**:
```python
from agent_orchestrator import Orchestrator, AgentTask, TaskPriority, TaskStatus
from datetime import datetime

def send_deal_alert(ticker, target, deal_value):
    """Send deal alert via orchestrator's Telegram agent"""
    orchestrator = Orchestrator()

    task = AgentTask(
        task_id=f"telegram_alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        agent_name="telegram",
        task_type="send_alert",
        priority=TaskPriority.CRITICAL,
        status=TaskStatus.PENDING,
        created_at=datetime.now(),
        parameters={
            'alert_text': f"""🚨 <b>NEW DEAL DETECTED</b>

<b>Ticker:</b> {ticker}
<b>Target:</b> {target}
<b>Deal Value:</b> ${deal_value}M"""
        }
    )

    result = orchestrator.agents['telegram'].execute(task)
    return result.status == TaskStatus.COMPLETED
```

**Interactive Validation Workflow**:

When data quality issues are detected, users receive formatted messages with 4 options:

```
🔍 Data Quality Issue 1/10

Ticker: BLUW
Field: trust_cash
Severity: CRITICAL

Issue: Trust cash $454.5M is 354.5% above IPO $100.0M
Current Value: $454,500,000
Expected: $100,000,000

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 WHAT WOULD YOU LIKE TO DO?

1️⃣ MANUAL REVIEW
   Reply: show changes or show fix
   → See before/after comparison

2️⃣ AUTO-FIX
   Reply: auto-fix or APPROVE
   → Apply suggested fix automatically

3️⃣ SKIP / DO NOTHING
   Reply: skip or next
   → Move to next issue

4️⃣ CHAT WITH CLAUDE
   Reply: Ask questions, request modifications
   → Examples:
     • "Why is this wrong?"
     • "Change trust_cash to 100000000"
     • "What's the best fix for this?"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Progress: 1/10 issues
```

**Backwards Compatibility**: `telegram_approval_listener.py` (1083 lines) still exists but should be refactored to use `TelegramAgent` for communication while keeping conversation logic.

**Integration Points**:
- **Data Validator**: Sends validation issues via `queue_validation_issues` task
- **Deal Monitor**: Sends deal alerts via `send_alert` task
- **Price Monitor**: Sends price spike alerts via `send_alert` task
- **Orchestrator Triggers**: All trigger functions send Telegram notifications via orchestrator

**Testing**:
```bash
# Test message send via orchestrator
python3 test_telegram_orchestrator.py --test message

# Test issue queueing
python3 test_telegram_orchestrator.py --test queue

# Test alert send
python3 test_telegram_orchestrator.py --test alert

# Run all tests
python3 test_telegram_orchestrator.py --test all
```

**Benefits of Centralized Architecture**:
- ✅ **No Code Duplication**: Single Telegram implementation used by all agents
- ✅ **Orchestrator Tracking**: All Telegram operations logged and trackable
- ✅ **Consistent Error Handling**: Centralized exception handling and retries
- ✅ **Easy Testing**: Mock TelegramAgent for all integration tests
- ✅ **Extensible**: Add new task types without modifying existing code

**Key Files**:
- `telegram_agent.py` - Core Telegram library (260 lines)
- `agent_orchestrator.py` - TelegramAgentWrapper (lines 792-842)
- `validation_issue_queue.py` - Issue queue manager (203 lines)
- `test_telegram_orchestrator.py` - Integration test suite
- `TELEGRAM_AGENT_ARCHITECTURE.md` - Detailed architecture documentation

**Environment Variables** (required in `.env`):
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
DEEPSEEK_API_KEY=sk-...  # For AI-powered conversational responses
```

## Development Commands

### Initial Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Setup PostgreSQL database
createdb spac_db
psql spac_db -c "CREATE USER spac_user WITH PASSWORD 'spacpass123';"
psql spac_db -c "GRANT ALL PRIVILEGES ON DATABASE spac_db TO spac_user;"

# Initialize schema
python3 -c "from database import init_db; init_db()"

# Load initial SPAC data (155 SPACs)
python3 load_all_155_spacs.py
```

### Environment Variables (.env)
Required keys:
```
DATABASE_URL=postgresql://spac_user:spacpass123@localhost:5432/spac_db
DEEPSEEK_API_KEY=sk-...           # For AI agent and filing analysis
ALPHA_VANTAGE_KEY=...             # Optional: price data fallback
TELEGRAM_BOT_TOKEN=...            # Optional: deal notifications
TELEGRAM_CHAT_ID=...              # Optional: deal notifications
```

### Database Migrations
```bash
# Add new column
python3 add_new_columns.py

# Check current schema
python3 check_database_columns.py

# Fix duplicate columns
python3 drop_duplicate_columns.py

# Recalculate derived fields
python3 recalculate_premiums.py
```

### Running Services
```bash
# Streamlit dashboard (interactive)
streamlit run streamlit_app.py

# FastAPI server (REST API)
uvicorn main:app --reload --port 8000

# Streamlit as systemd service
sudo systemctl start streamlit
sudo systemctl status streamlit
```

### Data Updates
```bash
# Full pipeline: scrape SEC + update prices
python3 sec_data_scraper.py && python3 price_updater.py

# Deal monitoring (checks for new announcements)
python3 deal_monitor_enhanced.py

# Verify data quality
python3 verify_trust_data.py
python3 check_duplicates.py
```

### Scheduled Monitoring
```bash
# Setup daily cron job
crontab -e
# Add: 0 9 * * * /home/ubuntu/spac-research/daily_deal_monitor.sh >> ~/spac-research/logs/daily_deals.log 2>&1
```

## Architecture Notes

### AI Integration Strategy
**DeepSeek API** is used in two contexts:
1. **Filing Analysis** (sec_data_scraper.py): Extracts structured data from messy SEC HTML/text
2. **Chat Interface** (spac_agent.py): Natural language queries with function calling

**Why DeepSeek**: Cost-effective, OpenAI-compatible API, good at structured extraction.

### SEC EDGAR Scraping Best Practices
- **Rate Limiting**: 10 requests/second max (SEC enforces this)
- **User-Agent**: Must include contact email (`SPAC Research Platform admin@spacresearch.com`)
- **Filing Types**:
  - `S-1`: IPO registration (for proceeds, structure)
  - `424B4`: IPO prospectus (for unit details)
  - `8-K`: Current events (deals, extensions, liquidations)
  - `DEF 14A`: Proxy statements (shareholder vote details)

### Trust Value Calculations
**Critical**: Most SPACs have $10.00 NAV, but some have $10.10 or $9.95 due to interest accrual or fees.

When scraping S-1 filings, look for "trust account per share" language to get precise NAV.

**Premium Thresholds**:
- `< 2%`: Near NAV (minimal downside risk)
- `2-10%`: Moderate premium
- `10-30%`: High premium (market optimism on deal)
- `> 30%`: Very high premium (significant deal excitement)

### Deal Detection Keywords
When parsing 8-Ks for deals, search for:
- "entered into a definitive agreement"
- "business combination agreement"
- "merger agreement"
- "announce the proposed business combination"

Exclude false positives: "exploring strategic alternatives", "in discussions with"

### Warrant Mechanics
Unit structure example: "1 common + 1/3 warrant" means:
- 1 unit contains 1 share + 0.33 warrants
- At separation: unit splits into common (trades as `TICKER`) and warrants (`TICKER.WS`)
- Warrant exercise: typically $11.50 strike, 5-year term

Track via `unit_structure` and `warrant_ratio` columns.

## Common Workflows

### Adding a New SPAC
1. Insert record with basic info (ticker, company, banker, sector)
2. Run `sec_data_scraper.py` to enrich from SEC filings
3. Run `price_updater.py` to get current prices
4. Manually verify `trust_value` and `premium` calculations

### Detecting a New Deal
1. `deal_monitor_enhanced.py` runs daily, finds 8-K with deal keywords
2. AI extracts target, deal value, expected close
3. Updates SPAC: `deal_status='ANNOUNCED'`, sets `target`, `announced_date`
4. Optional: sends Telegram alert
5. Dashboard shows in "Live Deals" tab

### Handling Deadline Extensions
1. Find 8-K with extension announcement
2. Update `deadline_date` (usually +3 or +6 months)
3. Set `is_extended=True`, increment `extension_count`
4. Recalculate `days_to_deadline` and `risk_level`

### Data Quality Checks
```bash
# Find SPACs missing key fields
python3 -c "from database import SessionLocal, SPAC; db=SessionLocal(); print([s.ticker for s in db.query(SPAC).filter(SPAC.ipo_date==None).all()])"

# Verify premium calculations
python3 verify_trust_data.py

# Check for duplicate tickers
python3 check_duplicates.py
```

## Testing Individual Components

### Test SEC Scraper on One SPAC
```python
from sec_data_scraper import SPACDataEnricher
enricher = SPACDataEnricher()
enricher.enrich_spac_from_sec("CEP")  # Replace with any ticker
```

### Test AI Chat Agent
```python
from spac_agent import SPACAIAgent
agent = SPACAIAgent()
result = agent.chat("Show me Goldman Sachs SPACs with premium over 15%", [])
print(result)
```

### Test Price Fetcher
```python
from price_updater import PriceUpdater
updater = PriceUpdater(source='yfinance')
price_data = updater.get_price_yfinance("CEP")
print(price_data)
```

### Manual Database Queries
```python
from database import SessionLocal, SPAC

db = SessionLocal()
try:
    # High premium deals
    deals = db.query(SPAC).filter(
        SPAC.deal_status == 'ANNOUNCED',
        SPAC.premium > 20
    ).all()

    for d in deals:
        print(f"{d.ticker}: {d.target} - {d.premium}%")
finally:
    db.close()
```

### 9. Agent Data Source Reference System
**Centralized documentation of data sources and precedence rules integrated into agent orchestration.**

**Architecture**: All agents inherit from `BaseAgent` with built-in data source validation.

**Core Module**: `agents/data_source_reference.py`

**Key Features**:
- **Data Source Definitions**: 110+ fields mapped to primary/secondary sources
- **Precedence Rules**: Embedded logic for timeliness (8-K for events, 10-Q for periodic data)
- **Exhibit Priority**: Standardized exhibit fetching order (EX-2.1, EX-99.1, EX-10.1)
- **Agent Guidance**: Pre-written instructions for each extraction agent type

**Data Source Categories**:

| Category | Primary Source | Update Frequency | Fields |
|----------|---------------|------------------|--------|
| **Deal Data** | 8-K, 425 | Event-based (0-4 days) | target, deal_value, announced_date, sector |
| **Trust Data** | 10-Q, 10-K | Quarterly (45 days) | trust_cash, trust_value, shares_outstanding |
| **PIPE Data** | 8-K exhibits | Event-based (0-4 days) | pipe_size, pipe_price, has_pipe |
| **Earnout Data** | 8-K exhibits (EX-2.1) | Event-based | earnout_shares, earnout_triggers |
| **Vote Data** | DEFM14A | Scheduled (20+ days before) | shareholder_vote_date, record_date |
| **Redemption Data** | 8-K (post-vote) | Event-based (0-4 days) | redemption_percentage, shares_redeemed |
| **Extension Data** | 8-K (Item 5.03) | Event-based (0-4 days) | deadline_date, is_extended |
| **IPO Data** | S-1, 424B4 | One-time | ipo_date, ipo_price, unit_structure |
| **Warrant Terms** | S-1, 424B4 | One-time (IPO) | strike_price, warrant_ratio, expiration_years |
| **Sponsor Economics** | S-1, 424B4 | One-time (IPO) | sponsor_promote, founder_shares |
| **Projections** | Investor Presentation | Event-based (deal time) | projected_revenue, projected_ebitda |

**Critical Precedence Rule** (from user guidance Oct 20, 2025):
> "The 10-Q or 10-K will likely have information around announced deals, pipes etc. as well in the body, but the 8-K will likely be more timely from the date of the announcement"

**Implementation:**
- Deal data: 8-K PRIMARY (Day 0-4) > 10-Q SECONDARY (Day 30-45)
- Trust data: 10-Q/10-K PRIMARY (quarterly authoritative) > 8-K SECONDARY (occasional mentions)

**Agent Integration**:

```python
from agents.base_agent import BaseAgent
from agents.data_source_reference import (
    should_process_filing_for_field,
    is_primary_source,
    get_exhibit_location,
)

class DealDetectorAgent(BaseAgent):
    async def can_process(self, filing: Dict) -> bool:
        # Use centralized source reference
        return should_process_filing_for_field('target', filing['type'])

    async def process(self, filing: Dict) -> Optional[Dict]:
        # Validate source
        source_check = self.check_data_source('target', filing['type'])
        
        if not source_check['is_primary_source']:
            print(f"⚠️  {filing['type']} is secondary source")
            print(f"ℹ️  Precedence: {source_check['precedence_rule']}")
        
        # Get exhibit location
        location = get_exhibit_location('target')
        print(f"📎 Data location: {location}")
        
        # Extract and update
        deal_data = self._extract_deal(filing)
        self._update_database(deal_data, filing)
```

**Helper Functions**:
- `get_data_source(field)` - Get complete source info (primary, secondary, timeliness)
- `should_process_filing_for_field(field, filing_type)` - Check if filing can provide field
- `is_primary_source(field, filing_type)` - Check if filing is primary source
- `get_exhibit_location(field)` - Get exhibit hint (e.g., "EX-10.1", "EX-99.1")
- `get_exhibit_priority_for_data_type(data_type)` - Get priority-ordered exhibit list

**Exhibit Priority Guide**:
- **Deal Announcement**: EX-99.1 (press release) > EX-2.1 (BCA) > EX-99.2 (presentation)
- **PIPE Data**: EX-10.1 (subscription agreement) > EX-99.1 (press release)
- **Earnout Terms**: EX-2.1 (BCA) > EX-99.1 (summary)
- **Projections**: EX-99.2 (investor deck) > EX-99.3 (pro formas)

**Usage Examples**:

```python
# Check if 8-K is valid source for 'target'
can_process = should_process_filing_for_field('target', '8-K')
# Returns: True

# Check if 8-K is primary source for 'target'
is_primary = is_primary_source('target', '8-K')
# Returns: True (8-K most timely for deal data)

# Check if 10-Q is primary source for 'target'
is_primary = is_primary_source('target', '10-Q')
# Returns: False (10-Q is secondary, 8-K is primary)

# Check if 10-Q is primary source for 'trust_cash'
is_primary = is_primary_source('trust_cash', '10-Q')
# Returns: True (10-Q is authoritative for trust balances)
```

**Pre-Written Agent Guidance**:
- `DEAL_DETECTOR_GUIDANCE` - Deal extraction instructions
- `TRUST_ACCOUNT_GUIDANCE` - Trust balance extraction instructions
- `PIPE_EXTRACTOR_GUIDANCE` - PIPE financing extraction instructions
- `EARNOUT_EXTRACTOR_GUIDANCE` - Earnout terms extraction instructions

**Documentation**:
1. **`agents/data_source_reference.py`** - Python module (650 lines)
2. **`DATA_SOURCE_MATRIX.md`** - Comprehensive documentation (700+ lines, 110+ fields)
3. **`DATA_SOURCE_QUICK_REFERENCE.md`** - Quick lookup guide (320 lines)
4. **`FILING_DATA_PRECEDENCE.md`** - Detailed precedence rules (280 lines)
5. **`AGENT_DATA_SOURCE_INTEGRATION.md`** - Agent integration guide (500 lines)

**Key Files**:
- `agents/base_agent.py` - Base class with data source helpers (lines 17-23, 100-132)
- `agents/data_source_reference.py` - Centralized source definitions
- `agents/deal_detector_agent.py` - Example: Only processes 8-K/425 for deals
- `agents/quarterly_report_extractor.py` - Example: Processes 10-Q/10-K for trust data
- `utils/trust_account_tracker.py` - Date-based precedence implementation

**Benefits**:
- ✅ Consistent precedence rules across all agents
- ✅ Self-documenting code (agents know which filings to process)
- ✅ Prevents data overwrites (8-K deal data won't be overwritten by 10-Q)
- ✅ Built-in validation (agents check source validity before extracting)
- ✅ Centralized updates (change precedence rules in one place)
- ✅ Testable (easy to validate source logic)


### 10. CompletionMonitor Agent (Added 2025-11-04)
**Detects when SPAC deals close and updates status to COMPLETED.**

**File**: `agents/completion_monitor_agent.py` (320 lines)

**Triggered by**: 8-K Item 2.01 (Completion of Acquisition)

**What it does**:
1. Detects completion filings with keywords like "completion of business combination", "consummation of merger"
2. Uses DeepSeek AI to extract:
   - `closing_date`: When the merger closed
   - `new_ticker`: Post-merger ticker symbol
   - `shares_redeemed`: Final redemption count
   - `redemption_amount`: Total cash paid for redemptions
   - `shares_outstanding`: Final share count
3. Includes number parsing (learned from CHAC) to avoid format errors
4. Updates database: `deal_status='COMPLETED'` with all completion data

**Integration**: Called by orchestrator's `_dispatch_completion_monitor()` method

**Pattern**: Follows modular agent architecture (inherits from `BaseAgent`)

**Critical Lesson (HOND Case Study)**:
- ❌ **What Failed**: Archived implementation (`archive/detectors/deal_closing_detector.py`) had import/method mismatch
- ❌ **Silent Failure**: ImportError caught, returned error dict, task marked COMPLETED (misleading!)
- ✅ **Fix**: New modular agent with proper error handling
- ✅ **Prevention**: Monitor agents completing in <1 second, send Telegram alerts on import errors

**Documentation**: See `docs/HOND_COMPLETION_DETECTION_FAILURE.md` for complete root cause analysis

**Usage**:
```python
# Orchestrator automatically routes 8-K Item 2.01 filings
from agents.completion_monitor_agent import CompletionMonitorAgent

agent = CompletionMonitorAgent()
result = await agent.process(filing)
# Returns: {'closing_date': '2025-10-20', 'new_ticker': 'IMSR', ...}
```

## Recent Fixes & Lessons Learned (November 2025)

### Fix 1: AI Number Format Parsing (Nov 4, 2025)
**Issue**: CHAC deal detected but database write failed with `invalid input syntax for type double precision: "1.1M"`

**Root Cause**: AI returned formatted string `"1.1M"` despite prompt instructions to return numeric values

**Solution**: Created `utils/number_parser.py` with three-layer defense:
1. Clear AI prompts with examples
2. Number parsing utility (`parse_numeric_value()`, `sanitize_ai_response()`)
3. Integration into all AI extraction agents

**Files Modified**:
- ✅ `utils/number_parser.py` - NEW (200 lines)
- ✅ `agents/deal_detector_agent.py` - Added `sanitize_ai_response()` at line 207
- ✅ `agents/redemption_extractor.py` - Added number parsing at line 195
- ✅ `streamlit_app.py` - Added `format_number_display()` for consistent UI formatting

**Learning System**: Use Few-Shot SQL (NOT ChromaDB)
- ChromaDB/RAG: 0% improvement in tests
- Few-Shot SQL: +30% accuracy, 100% format correctness
- Log errors to `data_quality_conversations` table for AI learning

**Documentation**: `docs/AI_NUMBER_FORMAT_FIX.md`

**Pattern to Apply**:
```python
# After AI extraction in ANY agent
data = json.loads(response.choices[0].message.content)

# Add number parsing
from utils.number_parser import sanitize_ai_response, MONEY_FIELDS, SHARE_FIELDS
numeric_fields = ['deal_value', 'pipe_size', 'earnout_shares', ...]
data = sanitize_ai_response(data, numeric_fields)

# Now safe to write to database
```

### Fix 2: CompletionMonitor Agent Broken Import (Nov 4, 2025)
**Issue**: HOND completion filing detected but status not updated to COMPLETED (agent completed in 0.0s)

**Root Cause**:
- Orchestrator tried to import `deal_closing_detector.py` from root
- Actual file was archived: `archive/detectors/deal_closing_detector.py`
- ImportError caught silently, returned error dict, task marked COMPLETED

**Solution**: Created new modular `CompletionMonitor` agent
- File: `agents/completion_monitor_agent.py` (320 lines)
- Uses provided filing data (no refetching)
- AI extraction with number parsing
- Proper error handling

**Files Modified**:
- ✅ `agents/completion_monitor_agent.py` - NEW
- ✅ `agent_orchestrator.py` - Updated `_dispatch_completion_monitor()` method

**Documentation**: `docs/HOND_COMPLETION_DETECTION_FAILURE.md`

**Key Learnings**:
1. Silent failures are dangerous - should send Telegram alerts
2. Execution time <1s is a red flag for filing agents
3. Archived code creates hidden dependencies
4. Need integration tests for all filing agents

### Fix 3: Streamlit Number Display Consistency (Nov 4, 2025)
**Issue**: Different number formats across pages ($275M vs $275.0M vs 275000000)

**Solution**:
- Updated `format_number_display()` to always use 1 decimal place
- Applied consistently to all money fields and volume
- Volume shows commas for readability (1,234,567 or 1.2M)

**Files Modified**:
- ✅ `streamlit_app.py` - Multiple formatting fixes (lines 611-629, 1045-1047)

## Error Logging & AI Learning System

**IMPORTANT**: When fixing errors, ALWAYS log to `data_quality_conversations` table for Few-Shot learning.

### How to Log Errors for AI Learning

**Table**: `data_quality_conversations`

**Pattern**:
```sql
INSERT INTO data_quality_conversations (
    issue_id, issue_type, issue_source, ticker, field,
    original_data, proposed_fix, final_fix, learning_notes, created_at
)
VALUES (
    'format_error_chac_20251104',
    'data_corruption',
    'ai_detected',
    'CHAC',
    'earnout_shares',
    '{"ai_returned": "1.1M", "database_expected": 1100000}',
    '{"earnout_shares": {"value": 1100000, "metadata": {"note": "Parsed from formatted string", "fix_type": "number_parser"}}}',
    '{"earnout_shares": {"value": 1100000, "metadata": {"note": "Parsed from formatted string", "fix_type": "number_parser"}}}',
    'AI returned "1.1M" despite prompt instructions. Added parse_numeric_value() to sanitize all numeric fields before database write.',
    NOW()
);
```

### Future: Automated Error Logging

**TODO**: Create error logging utility that automatically logs all code fixes:

```python
# utils/error_logger.py (TO BE CREATED)
def log_code_fix(
    issue_id: str,
    issue_type: str,  # 'import_error', 'format_error', 'validation_error'
    ticker: Optional[str],
    field: Optional[str],
    original_error: str,
    fix_description: str,
    code_changes: Dict,  # {'file': 'path', 'before': 'code', 'after': 'code'}
    learning_notes: str
):
    """
    Log code fixes to data_quality_conversations for AI learning.

    Future agents can query this table and learn from past fixes:
    - Update prompts automatically
    - Suggest fixes for similar errors
    - Prevent recurring issues
    """
    pass
```

**Use Cases for Automated Learning**:
1. **Prompt Auto-Update**: If same error occurs 3+ times, update AI prompt automatically
2. **Pattern Recognition**: Detect similar errors and suggest fixes proactively
3. **Code Generation**: Generate number parsing code for new agents automatically
4. **Prevention**: Add validation checks based on past errors

**Integration Points**:
- `agent_orchestrator.py` - Log agent execution failures
- All AI extraction agents - Log parsing errors
- `validation_issue_queue.py` - Log data quality issues
- `investigation_agent.py` - Log investigation findings

### Error Logging Best Practices

**When to Log**:
1. ✅ AI extraction returns wrong format (e.g., "1.1M" instead of 1100000)
2. ✅ Database write failures due to type mismatches
3. ✅ Agent import errors or execution failures
4. ✅ Data validation failures requiring manual fixes
5. ✅ Investigation findings with root cause analysis

**What to Include**:
- `issue_id`: Unique identifier (e.g., `format_error_chac_20251104`)
- `issue_type`: Category (`data_corruption`, `import_error`, `validation_error`)
- `original_data`: What the system produced/detected (JSON)
- `final_fix`: What was applied to fix it (JSON)
- `learning_notes`: Human-readable explanation with prevention strategy

**Example Workflow**:
```python
# In any agent that encounters an error
try:
    data = sanitize_ai_response(ai_response, numeric_fields)
except Exception as e:
    # Log the error for learning
    log_code_fix(
        issue_id=f"ai_format_error_{ticker}_{datetime.now().strftime('%Y%m%d')}",
        issue_type='format_error',
        ticker=ticker,
        field='pipe_size',
        original_error=str(e),
        fix_description='Applied number parser to convert "275M" to 275000000',
        code_changes={'file': __file__, 'fix': 'Added sanitize_ai_response()'},
        learning_notes='AI returned formatted string despite numeric prompt. Number parser catches this.'
    )
```

**Benefits**:
- 🎯 AI learns from past mistakes
- 🎯 Prompts improve automatically over time
- 🎯 Similar errors prevented in future
- 🎯 Knowledge base for new developers
- 🎯 Reduces manual intervention
