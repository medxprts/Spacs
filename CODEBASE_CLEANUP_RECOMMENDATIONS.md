# Codebase Cleanup Recommendations

**Generated**: 2025-11-04
**Active Files**: 122 Python files (63,176 lines)
**Excluded**: 226 deprecated files, archive directory

---

## Summary

The codebase audit identified:
- ✅ **94 unused files** (never imported, not entry points)
- ⚠️ **1 duplicate file** (`data_validator_agent.py` exists in root and agents/)
- ⚠️ **30 large files** (>500 lines) - some are backups
- ⚠️ **26 unreachable files** from entry points

---

## Priority 1: Remove Backup Files (SAFE TO DELETE)

These are backup copies that should be moved to `archive/`:

```bash
# Backup orchestrator files
agent_orchestrator.backup.py           # 4,093 lines - backup
agent_orchestrator_manual_clean.py     # 3,348 lines - backup
agent_orchestrator_cleaned.py          # 3,347 lines - backup
```

**Action**: Move to `archive/backups_nov2025/`

---

## Priority 2: Resolve Duplicate Files

### data_validator_agent.py (DUPLICATE)

Two versions exist:
- `data_validator_agent.py` (root, 2,468 lines)
- `agents/data_validator_agent.py` (agents/, 1,046 lines)

**Question**: Which is the canonical version?
- Root version (2,468 lines) appears older/larger
- Agents version (1,046 lines) follows modular pattern

**Recommendation**:
1. Verify which version `agent_orchestrator.py` imports
2. Keep the imported version
3. Archive the other

---

## Priority 3: Move Utility Scripts to `scripts/` Directory

These are one-off scripts, not core system code:

**Backfill Scripts** (move to `scripts/backfills/`):
- `backfill_vote_dates.py` (270 lines)
- `backfill_expected_close_dates.py` (95 lines)
- `backfill_expected_close_from_8k.py` (207 lines)
- `backfill_expected_close_from_s4_def14a.py` (386 lines)
- `backfill_proxy_filings.py` (217 lines)

**Fix Scripts** (move to `scripts/fixes/`):
- `fix_dtsq_trust_cash_redemption.py` (125 lines)
- `fix_number_parsing_all_agents.py` (92 lines)

**Trace/Debug Scripts** (move to `scripts/debug/`):
- `trace_dmyy_extensions.py` (270 lines)
- `trace_spac_extensions.py` (319 lines)
- `reprocess_aaci_deal.py` (212 lines)

**Setup Scripts** (move to `scripts/setup/`):
- `setup_s3_backups.py` (304 lines)
- `backup_to_s3_python.py` (120 lines)
- `open_port_8502.py` (76 lines)

**Migration Scripts** (move to `scripts/migrations/`):
- `migrate_correction_format.py` (403 lines)
- `consolidate_error_tables.py` (297 lines)
- `cleanup_duplicate_corrections.py` (207 lines)
- `index_corrections_to_vectordb.py` (278 lines)

**Reporting Scripts** (move to `scripts/reports/`):
- `show_learning_stats.py` (51 lines)
- `regenerate_generic_summaries.py` (117 lines)
- `daily_quality_report.py` (152 lines)

**Total**: 22 files (4,500 lines) → organize into `scripts/` directory

---

## Priority 4: Archive Unused Dev/Experimental Code

**Dev Experimental Files** (move to `archive/dev_experiments/`):
- `dev/phase1_logging.py` (554 lines)
- `dev/phase2_pattern_detector.py` (858 lines)
- `dev/phase3_validator_synthesis_agent.py` (573 lines)
- `dev/phase4_confidence_engine.py` (689 lines)
- `dev/orchestrator_integration.py` (552 lines)
- `dev/dash_app.py` (648 lines)

**Question**: Are these still being developed or abandoned?

**Experimental Agents** (verify usage):
- `agents/crewai_agent_base.py` (108 lines) - CrewAI integration
- `agents/filing_analysis_crew_agent.py` (209 lines)
- `agents/langgraph_agent_base.py` (155 lines) - LangGraph integration
- `agents/filing_analysis_langgraph_agent.py` (311 lines)
- `agents/deal_investigation_langgraph_agent.py` (417 lines)
- `agents/rag_learning_mixin.py` (278 lines) - RAG integration
- `agents/self_learning_mixin.py` (332 lines)

**Question**: Are CrewAI/LangGraph/RAG integrations still planned? If not, archive.

---

## Priority 5: Review Unreachable Code

Files not reachable from any entry point (but might be standalone scripts):

**Possibly Still Useful**:
- `audit_codebase.py` - This audit tool (just created)
- `monitor_service_health.py` (148 lines) - Health monitoring
- `data_quality_logger.py` - Logging utility
- `filing_orchestrator.py` (446 lines) - Alternative orchestrator?
- `signal_tracker.py` (334 lines) - Signal tracking
- `run_enrichment.py` (11 lines) - Enrichment runner

**Question**: Should these be added to entry points or archived?

---

## Priority 6: Consolidate Unused Agents

These agents are defined but never imported:

**Possibly Unused**:
- `agents/orchestrator_agent_base.py` (58 lines) - Base class, but is it used?
- `agents/deal_hunter_agent.py` (53 lines)
- `agents/ipo_detector_agent.py` (365 lines)
- `agents/issue_resolution_agent.py` (330 lines)
- `agents/risk_analysis_agent.py` (55 lines)
- `agents/sector_extraction_agent.py` (349 lines)
- `agents/vote_tracker_agent.py` (59 lines)
- `agents/deadline_extension_agent.py` (128 lines)
- `agents/pre_ipo_duplicate_checker_agent.py` (102 lines)
- `agents/data_quality_fixer_agent.py` (65 lines)
- `agents/presentation_extractor.py` (352 lines)
- `agents/universal_filing_analyzer.py` (651 lines)
- `agents/extension_monitor_agent.py` (294 lines)
- `agents/premium_alert_agent.py` (239 lines)

**Action Required**:
1. Check if `agent_orchestrator.py` imports these dynamically
2. If truly unused, move to `archive/unused_agents/`
3. If used, add explicit imports for clarity

---

## Priority 7: Consolidate Utils

**Tracker Utils** (many similar trackers):
- `utils/deal_value_tracker.py` (301 lines)
- `utils/redemption_tracker.py` (493 lines)
- `utils/trust_account_tracker.py` (613 lines)
- `utils/deal_structure_tracker.py` (370 lines)
- `utils/date_trackers.py` (382 lines)
- `utils/deal_status_tracker.py` (224 lines)
- `utils/target_tracker.py` (299 lines)

**Question**: Can these be consolidated into a unified tracker module?

**Specialized Utils** (verify usage):
- `utils/alert_deduplication.py` (346 lines)
- `utils/validation_suppression.py` (342 lines)
- `utils/error_detector.py` (119 lines)
- `utils/expected_close_normalizer.py` (165 lines)
- `utils/timezone_helper.py` (195 lines)
- `utils/correction_display_helpers.py` (251 lines)

---

## Priority 8: Review Large Files for Refactoring

Files >2000 lines (might benefit from modularization):

```
sec_data_scraper.py          4,427 lines - Could extract filing-specific parsers
agent_orchestrator.py        2,608 lines - Already improved from 4,093!
data_validator_agent.py      2,468 lines - Could extract validation rules
streamlit_app.py             2,137 lines - Could split into pages/components
```

**Note**: These are working files, refactor only if needed for maintainability.

---

## Priority 9: Document Entry Points

Current entry points (scripts run directly):
1. `agent_orchestrator.py` - Main orchestration loop
2. `price_updater.py` - Price updates
3. `streamlit_app.py` - Dashboard
4. `main.py` - FastAPI server
5. `sec_data_scraper.py` - SEC scraper
6. `deal_monitor_enhanced.py` - Deal monitoring
7. `price_spike_monitor.py` - Spike detection
8. `reddit_sentiment_tracker.py` - Reddit monitoring
9. `telegram_approval_listener.py` - Telegram listener
10. `warrant_price_fetcher.py` - Warrant prices

**Missing from entry points** (but might be used):
- `pre_ipo_graduation.py` (149 lines) - IPO graduation
- `pre_ipo_spac_finder.py` (591 lines) - Pre-IPO finder
- `volume_tracker.py` (206 lines) - Volume tracking
- `spac_news_feed.py` (230 lines) - News feed
- `deal_signal_aggregator.py` (425 lines) - Signal aggregation
- `vote_date_alerts.py` (177 lines) - Vote alerts

**Action**: Add to entry points or document as utilities

---

## Recommended Cleanup Steps

### Step 1: Safe Deletions (move to archive)
```bash
mkdir -p archive/backups_nov2025
mv agent_orchestrator.backup.py archive/backups_nov2025/
mv agent_orchestrator_manual_clean.py archive/backups_nov2025/
mv agent_orchestrator_cleaned.py archive/backups_nov2025/
```

### Step 2: Resolve Duplicate
```bash
# Check which is imported
grep -r "from data_validator_agent" . --exclude-dir=archive --exclude-dir=deprecated

# Move unused one to archive
```

### Step 3: Organize Scripts
```bash
mkdir -p scripts/{backfills,fixes,debug,setup,migrations,reports}

# Move backfill scripts
mv backfill_*.py scripts/backfills/

# Move fix scripts
mv fix_*.py scripts/fixes/

# Move trace/debug scripts
mv trace_*.py scripts/debug/
mv reprocess_*.py scripts/debug/

# Move setup scripts
mv setup_*.py scripts/setup/
mv backup_to_s3_python.py scripts/setup/
mv open_port_8502.py scripts/setup/

# Move migration scripts
mv migrate_*.py scripts/migrations/
mv consolidate_*.py scripts/migrations/
mv cleanup_duplicate_*.py scripts/migrations/
mv index_corrections_*.py scripts/migrations/

# Move report scripts
mv show_learning_stats.py scripts/reports/
mv regenerate_generic_summaries.py scripts/reports/
mv daily_quality_report.py scripts/reports/
```

### Step 4: Archive Experimental Code
```bash
mkdir -p archive/dev_experiments_nov2025

# Move dev experimental files (verify first!)
# mv dev/phase*.py archive/dev_experiments_nov2025/
```

### Step 5: Create Scripts README
```bash
echo "# Scripts Directory

## Backfills
- One-off scripts to populate historical data

## Fixes
- One-off scripts to fix data issues

## Debug
- Debug/trace scripts for investigation

## Setup
- Setup and deployment scripts

## Migrations
- Database and data migration scripts

## Reports
- Reporting and statistics scripts
" > scripts/README.md
```

---

## After Cleanup

**Expected Result**:
- Root directory: ~40 core files (orchestrator, main services)
- `agents/`: ~15-20 active agents
- `utils/`: ~15 active utilities
- `scripts/`: ~22 utility scripts (organized)
- `archive/`: Historical/backup code

**Benefits**:
- ✅ Clearer codebase structure
- ✅ Easier onboarding for new developers
- ✅ Faster navigation
- ✅ Reduced confusion about what's active vs experimental

---

## Questions to Answer

Before cleanup, answer these questions:

1. **data_validator_agent.py**: Which version is canonical (root vs agents/)?
2. **Dev experiments**: Are CrewAI/LangGraph/RAG still planned?
3. **Unused agents**: Should they be archived or added to orchestrator?
4. **Tracker utils**: Should these be consolidated?
5. **Entry points**: Should missing scripts be added to cron/systemd?

---

**Next Step**: Review these recommendations and confirm which cleanup actions to take.
