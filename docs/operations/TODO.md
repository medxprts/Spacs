# SPAC Research Platform - TODO List

## 🔴 CRITICAL PRIORITY

### 1. Implement Comprehensive Data Validator (91 Rules)
**Status**: IN PROGRESS (Building framework now)
**Location**: `data_validator.py` (being created)
**Documentation**: `VALIDATION_RULES_SEVERITY.md`

**Phase 1 - Core Validator (Week 1):**
- [ ] Implement 40 rules we can validate with current data (IN PROGRESS)
- [ ] Add CRITICAL rules (15 rules - block bad data)
- [ ] Add ERROR rules (28 rules - flag immediately)
- [ ] Test validator on existing 186 SPACs
- [ ] Integration with orchestrator

**Phase 2 - Quick Win Data Sources (Week 1):**
- [x] Auto-capture `price_at_announcement` from Yahoo Finance historical (DONE - 50 deals backfilled)
- [x] Calculate `volume_avg_30d` from Yahoo historical (DONE)
- [x] Auto-calculate `return_since_announcement` (DONE)
- [x] Enables Rules 19, 43, 49, 50

**Phase 3 - Shares Outstanding Capture:**
- [x] Extract `shares_outstanding` from IPO completion press release (DONE - enhanced sec_data_scraper.py)
- [x] Display format in millions (DONE)
- [x] Fallback to latest 10-Q/10-K (DONE in sec_data_scraper.py)
- [ ] Extract `founder_shares` and calculate `founder_ownership` (needs 10-Q parser)
- [x] Enables Rules 18, 22-29 (partial)

**Phase 4 - Redemption Tracking (Week 3):**
- [x] Created `redemption_tracker.py` with Super 8-K + 10-Q fallback (DONE)
- [ ] Debug iXBRL format and extension vote redemptions (IN PROGRESS - see REDEMPTION_TRACKER_DEBUG_NOTES.md)
- [ ] Track `redemptions_occurred`, `shares_redeemed`, `redemption_amount`
- [ ] Calculate `redemption_percentage`
- [ ] Test on 6 known redemption cases (EURK, SLAM, IRRX, BRZH, GLLI, KYIV)
- [ ] Enables full redemption validation

---

## 🟠 HIGH PRIORITY

### 2. Agent Integration & Orchestration
**Status**: PARTIAL (orchestrator exists, needs new agents)

**Integrate New Agents:**
- [ ] S-4 Parser Agent → orchestrator (Rule-based scheduling)
- [ ] Enhanced Data Validator → orchestrator (Weekly for pre-deal, 3-day for active deals)
- [ ] Pre-IPO Finder → orchestrator (Weekly S-1 scan)
- [ ] 10-Q Parser (when built) → orchestrator

**Orchestrator Enhancements:**
- [ ] Implement smart scraping cadence (Rule 87):
  - Active deals: Every 3 days
  - Pre-deal SPACs: Weekly
  - Closed/liquidating: Never
- [ ] Add lifecycle-based status updates (Rules 51, 90-92):
  - Deal Hunter → ANNOUNCED
  - S-4 Parser → S4_FILED
  - Vote Tracker → PROXY_FILED, VOTE_SCHEDULED
  - Deadline Monitor → LIQUIDATING

**AI Training & Self-Improvement:**
- [x] Enhanced extraction logger (Option A - DONE)
  - Logs full prompts, source text, errors
  - Uses `enhance_extraction_logger.py`
  - Outputs to `logs/extraction_log_enhanced.jsonl`
- [ ] Full ai_training_logger.py migration (Option B - Future)
  - Migrate from `enhance_extraction_logger.py` to `ai_training_logger.py`
  - Create `ai_training_logs/` directory structure
  - Organize logs into 4 categories: successful/failed/validation_errors/edge_cases
  - Integrate into all 11 AI agents in `sec_data_scraper.py`
  - Enable self-improvement agent to analyze patterns
  - **When**: After 4-agent consolidation is complete
- [ ] Build Self-Improvement Agent (Agent #5)
  - Analyzes failed extractions from training logs
  - Uses AI to detect error patterns
  - Generates improved prompts automatically
  - Tests new prompts on failed cases
  - Auto-deploys if >20% improvement
  - **Depends on**: Option B migration complete

### 3. Pre-IPO Pipeline Completion
**Status**: IN PROGRESS (finder works, needs testing)
**Background Task**: Running (30-day S-1 scan)

- [x] Enhanced S-1 parser (now extracts 16 fields)
- [x] Added exhibit parsing for S-1/A amendments
- [x] Efficient section-based extraction (99% reduction)
- [ ] Test with 60 SPACs found
- [ ] Verify database population
- [ ] Add to orchestrator (weekly runs)
- [ ] Monitor `logs/sec_parsing_efficiency.jsonl` for optimization opportunities

### 4. Database Schema Updates
**Status**: PARTIAL (some done, more needed)

**Completed:**
- [x] Added `original_deadline_date` column (for extension tracking)

**Needed:**
- [ ] Add `previous_deal_status` for transition validation
- [ ] Consider field-level data_source tracking
- [ ] Add alert history table (prevent duplicate alerts)

### 5. Telegram Conversational Approval System Debugging
**Status**: IN PROGRESS (system crashing, needs fixes)
**Priority**: HIGH (blocks data quality workflow)

**Issues to Debug:**
- [ ] Investigate 'fix failed: error' response in Telegram
- [ ] Debug why conversation_state table doesn't exist (may need database migration)
- [ ] Test Telegram conversational features with a fresh message after fixes
- [ ] Verify DEEPSEEK_API_KEY is properly loaded in systemd service
- [ ] Ensure DATABASE_URL environment variable is accessible

**AEXA Trust Cash Fix (Related):**
- [ ] Implement trust cash fix - scrape actual overallotment proceeds from 424B4 or IPO closing press release
- [ ] Enhance SEC scraper to only include overallotment if IPO closing press release confirms it was exercised
- [ ] Fix trust_cash calculation mismatch (shares_outstanding includes overallotment, trust_cash does not)

**Context:**
- User identified AEXA has incorrect trust NAV ($8.48 instead of ~$9.80)
- Root cause: shares_outstanding (34.675M) includes overallotment, but trust_cash ($294M) does not
- User's fix: Extract actual proceeds from 424B4 or IPO closing press release
- Only include overallotment proceeds if press release confirms it was exercised

---

## 🟡 MEDIUM PRIORITY

### 5. Missing Data Source Implementations

**Historical Price Data (Easy - Week 1):**
- [ ] Enhance `price_updater.py` to fetch 30-day volume average
- [ ] Add historical price lookup function
- [ ] Auto-populate `price_at_announcement` when deal announced

**Warrant/Unit Structure Parser (Medium - Week 4):**
- [ ] Extract `warrant_strike` from S-1 or unit split 8-K
- [ ] Parse `warrant_ratio` from `unit_structure` string
- [ ] Track `has_rights` vs warrants

**Sponsor/Banking Details (Medium - Covered by Pre-IPO parser):**
- [ ] Extract `sponsor_promote` from S-1
- [ ] Extract `underwriter_discount` from S-1
- [ ] Parse `co_bankers` list

### 6. Alert System Enhancements
**Status**: BASIC ALERTS EXIST (needs expansion)

**Rule 84 Alert Triggers:**
- [ ] Urgent deadline alert (<60 days, no deal)
- [ ] Extreme redemptions (>90%)
- [ ] Deep discount to NAV (<-15%)
- [ ] Dormant SPAC (no 8-K in >90 days)

**Alert Deduplication:**
- [ ] Track alert history (don't spam)
- [ ] Implement 7-day cooldown per alert type
- [ ] Priority-based alert routing (CRITICAL → Telegram, INFO → logs)

### 7. Parsing Efficiency & Logging
**Status**: IMPLEMENTED for S-4, needs expansion

**Already Logging:**
- [x] S-4 parsing efficiency (`logs/sec_parsing_efficiency.jsonl`)
- [x] Section extraction stats
- [x] Document size reduction metrics

**Extend to Other Documents:**
- [ ] Add logging to vote_date_tracker.py (DEF 14A)
- [ ] Add logging to deal_monitor (8-K)
- [ ] After 100 parses, analyze logs for optimization
- [ ] Implement evidence-based section targeting

### 8. Cross-Table Validation
**Status**: RULES DEFINED (not implemented)

- [ ] Implement Rules 72-75 (Pre-IPO ↔ Main table consistency)
- [ ] Validate CIK → company name mapping
- [ ] Detect duplicate tickers
- [ ] Track graduation field mapping

---

## 🟢 LOW PRIORITY / FUTURE ENHANCEMENTS

### 9. YAML Configuration Migration
**Status**: DESIGNED BUT DEFERRED (wait until code is stable)
**Documentation**: `YAML_CONFIG_ARCHITECTURE.md`, `YAML_MIGRATION_PROGRESS.md`

**Why Deferred:**
- ⚠️ Phase 2 (424B4 extraction) still in testing
- ⚠️ Prompts still being refined based on test results
- ⚠️ Would create double work during active development
- ✅ Design complete, ready when code stabilizes

**When to Migrate:**
- ✅ After Phase 2 is 90%+ accurate
- ✅ After 1-2 weeks of stable production use
- ✅ After prompt structures are finalized
- ✅ When ready to consolidate to 4 core agents

**What's Ready:**
- ✅ `base_agent.py` - YAML loading framework
- ✅ 4 core agent configs created
- ✅ Example extraction prompt (ipo_extraction.yaml)
- ✅ Directory structure established

**Migration Path:**
1. Finish & validate current hardcoded system
2. Run in production for 1-2 weeks
3. Identify stable prompt patterns
4. Create remaining 10 extraction prompt YAMLs
5. Refactor 4 core agents to use base_agent.py
6. Test hot reload functionality
7. Run old + new in parallel
8. Switch to YAML once validated

**Benefits (when ready):**
- No code changes for prompt updates
- Hot reload (no restarts)
- Version control for prompts
- Self-improvement agent can update YAML
- 85% agent consolidation (25 → 4)

### 10. Enhanced S-4 Parser Coverage
**Status**: BASIC VERSION WORKING (2/10 SPACs extracted data)

**Improvements:**
- [ ] Fine-tune AI prompts for better extraction
- [ ] Try exhibit-only parsing (Annex A = merger agreement)
- [ ] Parallel processing (5 SPACs at once)
- [ ] Database caching for parsed S-4s

### 10. Retail Sentiment Tracking
**Status**: STRATEGY COMPLETE, NOT STARTED
- Strategy documented in `RETAIL_SENTIMENT_STRATEGY.md`
- Build Reddit API integration (PRAW) - already have `reddit_sentiment_tracker.py`
- Add Twitter, StockTwits, Google Trends
- Database schema already documented
- Estimated cost: $2-5/month

### 11. Historical Premium Data Backfilling
**Status**: NOT STARTED
**Priority**: MEDIUM
**Location**: Analytics dashboard chart update

**Context:**
- Historical average premium chart now split into pre-deal vs announced SPACs
- Current `MarketSnapshot` table has separate columns for both categories
- Need to ensure historical data is properly separated and backfilled

**Tasks:**
- [ ] Verify `MarketSnapshot` table has complete historical data for both:
  - `avg_premium_predeal`, `median_premium_predeal`, `weighted_avg_premium_predeal`, `count_predeal`
  - `avg_premium_announced`, `median_premium_announced`, `weighted_avg_premium_announced`, `count_announced`
- [ ] Backfill any missing historical snapshots (if gaps exist)
- [ ] Add validation that daily snapshot script properly separates SEARCHING vs ANNOUNCED
- [ ] Test chart displays correctly with historical data
- [ ] Document data collection process in operations guide

**Benefits:**
- Investors can track premium trends separately for pre-deal vs announced SPACs
- Different premium behavior patterns (pre-deal SPACs trade closer to NAV, announced deals have higher premiums)
- Better market analysis and investment decisions

### 12. Historical Redemption Tracking
**Status**: NOT STARTED
- Track redemption trends over time
- Build redemption predictor model
- Correlate with premium, PIPE size, sponsor quality

### 12. Deal Closing Detection
**Status**: BASIC VERSION EXISTS (needs testing)
- Verify `deal_closing_detector.py` works
- Test on recently closed deals
- Ensure new ticker and closing date captured
- Auto-update status to CLOSED

---

## ✅ COMPLETED

### Agents & Automation
- ✅ Agentic AI Orchestrator (`agent_orchestrator.py`)
- ✅ S-4 Merger Parser Agent (`s4_merger_parser_agent.py`)
- ✅ Vote Date Tracker (`vote_date_tracker.py`)
- ✅ Deal Hunter (`deal_monitor_enhanced.py`)
- ✅ Price Monitor (`price_updater.py`)
- ✅ Warrant Price Fetcher (`warrant_price_fetcher.py`)
- ✅ Risk Analysis (`risk_analysis_agent.py`)
- ✅ Basic Data Validator (`data_validator_agent.py`)
- ✅ Pre-IPO SPAC Finder (`pre_ipo_spac_finder.py`) - 42 SPACs found
- ✅ Historical Price Agent (`historical_price_agent.py`) - 50 deals backfilled
- ✅ Redemption Tracker (`redemption_tracker.py`) - needs debugging
- ✅ Data Quality Logger (`data_quality_logger.py`)
- ✅ Background Data Collection Script (`run_all_data_collection.sh`)

### Database & Schema
- ✅ Pre-IPO database schema (30+ columns)
- ✅ Main SPAC table (69 columns)
- ✅ Added `original_deadline_date` column
- ✅ Vote tracking columns
- ✅ Historical price columns (`price_at_announcement`, `volume_avg_30d`)

### Documentation
- ✅ 91 validation rules defined (`VALIDATION_RULES_SEVERITY.md`)
- ✅ Data coverage audit (`/tmp/data_coverage_audit.md`)
- ✅ Efficient parsing strategy (`EFFICIENT_DOCUMENT_PARSING.md`)
- ✅ Parsing efficiency notes (`PARSING_EFFICIENCY_NOTES.md`)
- ✅ Pre-IPO pipeline design (`PRE_IPO_PIPELINE_DESIGN.md`)
- ✅ Auto-fix capabilities doc (`AUTO_FIX_CAPABILITIES.md`)
- ✅ Data validator flow (`DATA_VALIDATOR_FLOW.md`)
- ✅ Redemption tracker debug notes (`REDEMPTION_TRACKER_DEBUG_NOTES.md`)

### Dashboard & Interface
- ✅ Streamlit dashboard (`streamlit_app.py`)
- ✅ FastAPI backend (`main.py`)
- ✅ AI chat agent (`spac_agent.py`)

---

## 📊 IMPLEMENTATION ROADMAP

### Week 1: Validation + Quick Wins
- [ ] Implement 40-rule validator
- [ ] Add historical price data (Yahoo Finance)
- [ ] Test validator on 186 SPACs
- [ ] Fix critical data issues found

### Week 2: 10-Q Parser + Trust Data
- [ ] Build 10-Q parser for shares_outstanding
- [ ] Extract founder_shares and redemption data
- [ ] Enable 20+ additional validation rules
- [ ] Integrate with orchestrator

### Week 3: Redemption Tracking
- [ ] Parse 8-K redemption notices
- [ ] Full redemption tracking
- [ ] Alert system for high redemptions
- [ ] Enable all redemption validation rules

### Week 4: Polish & Optimization
- [ ] S-1 warrant/structure parsing
- [ ] Analyze parsing efficiency logs
- [ ] Optimize section extraction
- [ ] Performance tuning

---

## 📈 SUCCESS METRICS

**Data Quality:**
- Current: ~55% validation rule coverage
- Target: >85% coverage (75+ rules active)
- Current issues: TBD (validator not yet run)
- Target: <10 critical issues across 186 SPACs

**Automation:**
- Current: Manual trigger required
- Target: Fully autonomous agentic system
- Alert response time: <4 hours for critical issues

**Cost Efficiency:**
- Current: Unknown
- Target: <$1/month for all AI parsing
- SEC scraping: 81% reduction (3000→560 calls/month)

---

## 🚨 BLOCKING ISSUES

**None currently!** All systems ready for implementation.

**Previous blocker resolved:**
- ✅ AI extraction issues - Fixed in various parsers
- ✅ Validation rules design - Complete (91 rules defined)
- ✅ Pre-IPO pipeline - Enhanced and ready for testing

---

## 💡 NEXT ACTIONS

**Immediate (Now):**
1. ✅ Historical price data added (50 deals backfilled)
2. ✅ Pre-IPO finder complete (42 SPACs found)
3. ⏳ SEC enrichment running (86 SPACs missing shares_outstanding)
4. 🚧 Building comprehensive data validator framework

**Tonight/Background:**
- All data collection agents running via `run_all_data_collection.sh`
- Processes persist even if Claude session closes (nohup)
- Monitor logs in `/home/ubuntu/spac-research/logs/`
- Data quality logging active in `logs/data_quality.jsonl`

**This Week:**
1. Complete comprehensive data validator (40-50 rules)
2. Test validator on updated database
3. Generate data quality summary (`python3 data_quality_logger.py --summary`)
4. Fix critical issues found
5. Debug redemption tracker (iXBRL format, extension votes)

**This Month:**
1. Build 10-Q parser for founder_shares
2. Complete redemption tracking
3. Full validation coverage (75+ rules)
4. Autonomous agentic operation

---

## 🔄 TRUST CASH SOURCING STRATEGY (October 9, 2025)

### Smart Waterfall Approach

**Priority-based sourcing based on SPAC age:**

```
┌─────────────────────────────────────────────────────────────┐
│                 TRUST CASH SOURCING LOGIC                   │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        │                                       │
        ▼                                       ▼
┌──────────────────┐                  ┌──────────────────┐
│ New SPACs        │                  │ Mature SPACs     │
│ (<3 months old)  │                  │ (>3 months old)  │
│                  │                  │                  │
│ Source: 424B4    │                  │ Source: 10-Q/K   │
│ Why: Initial     │                  │ Why: Current bal │
│      trust size  │                  │      after       │
│                  │                  │      redemptions │
└──────────────────┘                  └──────────────────┘
        │                                       │
        │         If extraction fails           │
        └───────────────────┬───────────────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │ FALLBACK         │
                  │ Calculate:       │
                  │ shares * trust   │
                  └──────────────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │ VALIDATION       │
                  │ Compare extracted│
                  │ vs calculated    │
                  │ Flag if >5% diff │
                  └──────────────────┘
```

### Implementation Status

- [x] Smart sourcing script created (`smart_trust_cash_sourcing.py`)
- [x] Tested on 33 new SPACs (1 successful extraction from 424B4)
- [x] Identified 9 mature SPACs needing 10-Q extraction (likely redemptions)
- [ ] Add to business validation rules (Rules 92-94)
- [ ] Integrate into main enrichment pipeline
- [ ] Add data_source tracking (424b4_extracted, 10q_extracted, calculated)

### Validation Rules to Add

**Rule 92**: Trust Cash Source Validation
- **Check**: Verify trust_cash has appropriate data_source flag
- **New SPACs (<90 days)**: Should be '424b4_extracted'
- **Mature SPACs (>90 days)**: Should be '10q_extracted' or '10k_extracted'
- **Severity**: WARNING if using 'calculated' for mature SPACs

**Rule 93**: Trust Cash Variance Check
- **Check**: Compare extracted vs calculated trust cash
- **Threshold**: Flag if difference >5%
- **Action**: Mark for 10-Q re-extraction
- **Severity**: ERROR if variance >10% (likely redemptions missed)

**Rule 94**: Trust Cash Freshness
- **Check**: Ensure trust cash is from recent 10-Q
- **Threshold**: Data should be <90 days old for mature SPACs
- **Action**: Re-extract from latest 10-Q
- **Severity**: WARNING if data >90 days old

### Current Coverage

| Category | Count | Source |
|----------|-------|--------|
| New SPACs (<3mo) | 33 | Should use 424B4 |
| Mature SPACs (>3mo) | 153 | Should use 10-Q |
| With variance >5% | 9 | Need 10-Q extraction |
| Total coverage | 171/186 (92%) | Mixed sources |

### Next Steps

1. **Enhance 424B4 extraction pattern** - Current regex only found 1/10
2. **Integrate 10-Q trust cash extraction** - For mature SPACs
3. **Add to validation rules** - Rules 92-94
4. **Update enrichment pipeline** - Use smart sourcing strategy
5. **Track data source** - Add timestamps and source to data_source field

