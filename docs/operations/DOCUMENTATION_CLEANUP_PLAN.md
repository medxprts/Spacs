# Documentation Cleanup & Archive Plan

**Date:** October 10, 2025
**Purpose:** Archive obsolete documentation, consolidate relevant docs into agentic AI orchestration structure

---

## Current Situation

- **Total docs**: 156 markdown files
- **Active agents**: 12 (DealDetector, TrustAccountProcessor, ExtensionMonitor, RedemptionProcessor, S4Processor, FilingProcessor, ProxyProcessor, DelistingDetector, CompletionMonitor, IPODetector, EffectivenessMonitor, ComplianceMonitor)
- **Archived agents**: 25+ agents removed during cleanup
- **Problem**: Many docs reference obsolete agents/architecture

---

## Documentation Categories

### ✅ Keep (Current Agentic System)
Documents actively describing current system:

1. **AGENTIC_AI_ORCHESTRATION.md** - Master orchestration guide
2. **ORCHESTRATOR_ARCHITECTURE_FINAL.md** - Orchestrator design
3. **SEC_FILING_ROUTING_MAP.md** - Filing → agent routing
4. **DATA_SOURCES_AND_PRIORITY.md** - Field → source mapping
5. **IPO_DETECTOR_IMPLEMENTATION.md** - IPO graduation system
6. **REALTIME_SYSTEM_ARCHITECTURE.md** - Real-time monitoring
7. **EVENT_DRIVEN_TRUST_UPDATES.md** - Trust account flow
8. **AUTO_RECALCULATE_PREMIUM.md** - Dependent data
9. **DATA_QUALITY_ISSUES.md** - AEXA lessons
10. **ALL_LEARNINGS_SUMMARY.md** - System learnings
11. **CLAUDE.md** - Project overview
12. **DOCUMENTATION_INDEX.md** - This index

**Total: 12 core docs**

---

### 🗂️ Archive (Session Summaries)
Historical context, not current reference:

All `SESSION_SUMMARY_*.md` files (96 files):
- SESSION_SUMMARY_OCT_2025.md
- SESSION_SUMMARY_OCT9.md
- SESSION_SUMMARY_OCT9_PART2.md
- SESSION_SUMMARY_OCT9_PART3.md
- SESSION_SUMMARY_OCT9_AI_PRESCREENING.md
- SESSION_SUMMARY_OCT9_INTELLIGENT_ROUTING.md
- SESSION_SUMMARY_OCT8.md
- SESSION_SUMMARY_LIFECYCLE_DETECTOR.md
- SESSION_SUMMARY_424B4_IMPLEMENTATION.md
- SESSION_SUMMARY_424B4_INTEGRATION.md
- SESSION_SUMMARY_PHASE2_COMPLETE.md
- SESSION_COMPLETE_SUMMARY.md
- SUMMARY_COMPLETED_WORK.md
- FIXES_SUMMARY_OCT9.md
- OVERNIGHT_UPDATE_SUMMARY.md
- TODAYS_ACCOMPLISHMENTS.md
- TONIGHT_SUMMARY.md
- TOMORROW_AGENDA.md
- IMPLEMENTATION_SUMMARY.md
- (and 77 more session summaries...)

**Move to:** `/archive/session_summaries/`

---

### 🗂️ Archive (Deprecated Architecture)
Old architectural designs superseded by current system:

1. **AGENTIC_SYSTEM.md** - Superseded by AGENTIC_AI_ORCHESTRATION.md
2. **ARCHITECTURE.md** - Superseded by ORCHESTRATOR_ARCHITECTURE_FINAL.md
3. **SIMPLIFIED_AGENT_ARCHITECTURE.md** - Old design
4. **YAML_CONFIG_ARCHITECTURE.md** - YAML config deprecated
5. **YAML_MIGRATION_PROGRESS.md** - YAML migration abandoned
6. **AGENT_INTEGRATION_PLAN.md** - Completed, now in INTEGRATION_GUIDE
7. **AGENT_INTEGRATION_COMPLETE.md** - Historical
8. **FINAL_4_AGENT_SYSTEM.md** - Old consolidation plan (now have 12 agents)
9. **FINAL_AGENT_RECOMMENDATION.md** - Completed
10. **AGENT_AUDIT_2025.md** - Historical audit

**Move to:** `/archive/deprecated_architecture/`

---

### 🗂️ Archive (Obsolete Agent Docs)
Docs for agents that were archived:

1. **AGENT_TRACKING_UPDATES.md** - Old agent tracking (now in orchestrator)
2. **RESEARCH_BASED_AUTO_FIX_ARCHITECTURE.md** - Old auto-fix design
3. **INVESTIGATION_AGENT_DESIGN.md** - Old investigation design (now integrated)
4. **INVESTIGATION_SUMMARY.md** - Superseded by current investigation flow

**Move to:** `/archive/old_agents/`

---

### 🗂️ Archive (Specific Issue Investigations)
One-off investigations, keep for reference but not active:

1. **OBA_FIX_SUMMARY.md** - OBA ticker reuse (solved)
2. **QETA_INVESTIGATION.md** - QETA issue (solved)
3. **QETA_FIX_SUMMARY.md** - Solved
4. **QETA_COMPLETE_FIX_SUMMARY.md** - Solved
5. **QETA_IPO_DATE_ISSUE.md** - Solved
6. **TICKER_ANALYSIS_SUMMARY.md** - Completed analysis
7. **CIK_RESOLUTION_WORKFLOW.md** - Now automated
8. **EXPIRED_SPACS_FIX.md** - Fixed
9. **FINAL_SUMMARY_EXPIRED_SPACS.md** - Solved

**Move to:** `/archive/investigations/`

---

### 🔄 Consolidate (Redundant Guides)
Multiple docs covering same topic - consolidate into one:

#### Topic: Data Quality & Validation
**Keep:** DATA_QUALITY_ISSUES.md (most comprehensive)
**Archive:**
- DATA_QUALITY_SUMMARY.md (redundant)
- DATA_QUALITY_AGENT_README.md (merge into main)
- DATA_VALIDATOR_FLOW.md (merge into main)
- VALIDATION_RULES_SUMMARY.md (consolidate)
- VALIDATION_RULES_SEVERITY.md (consolidate)
- PREVENT_DATA_CORRUPTION.md (merge)

**Action:** Consolidate into **DATA_QUALITY_AND_VALIDATION.md**

---

#### Topic: Filing Processing
**Keep:** SEC_FILING_ROUTING_MAP.md (comprehensive)
**Archive:**
- FILING_ROUTING_MAP.md (duplicate)
- FILING_TYPES_AUDIT.md (historical)
- NEW_FILING_TYPES_IMPLEMENTATION.md (completed)
- FILING_PROCESSOR_CONSOLIDATION.md (done)
- SEC_CONSOLIDATION_STRATEGY.md (done)

---

#### Topic: 424B4 Extraction
**Keep:** 424B4_EXTRACTION_GUIDE.md
**Archive:**
- 424B3_SUPPORT_NOTE.md (edge case)
- 424B3_FALLBACK_SUCCESS.md (implementation detail)
- ADDITIONAL_424B4_DATAPOINTS.md (merge into main guide)
- 424B4_vs_OVERALLOTMENT_ANALYSIS.md (analysis complete)

---

#### Topic: Deployment & Operations
**Keep:** PRODUCTION_SYSTEM_SUMMARY.md
**Archive:**
- DEPLOYMENT_SUMMARY.md (merge)
- FULL_SYSTEM_INTEGRATION.md (merge)

---

### 📝 Keep (Active Reference Docs)
Documents actively used for specific features:

#### Deal & Extension Monitoring
- DEAL_MONITOR_SETUP.md
- DEADLINE_EXTENSION_PROCESS.md
- LEARNING_19_REDEMPTION_TRACKING.md
- REDEMPTION_TRACKING_GUIDE.md

#### Pricing & Market Data
- PRICING_FIX_SUMMARY.md
- MARKET_CAP_EXPLANATION.md
- MARKET_CAP_LEARNINGS.md

#### Alerts & Notifications
- TELEGRAM_ALERTS_GUIDE.md
- TELEGRAM_BOT_GUIDE.md

#### Logging & Monitoring
- DATA_LOGGING_GUIDE.md
- LOGGING_STATUS.md

#### News & Sentiment
- CONTINUOUS_NEWS_MONITORING_COMPLETE.md
- REDDIT_SENTIMENT_SUMMARY.md

---

## Reorganized Documentation Structure

```
/home/ubuntu/spac-research/
├── docs/
│   ├── core/                          # Core system docs (12 files)
│   │   ├── AGENTIC_AI_ORCHESTRATION.md
│   │   ├── ORCHESTRATOR_ARCHITECTURE_FINAL.md
│   │   ├── SEC_FILING_ROUTING_MAP.md
│   │   ├── DATA_SOURCES_AND_PRIORITY.md
│   │   ├── IPO_DETECTOR_IMPLEMENTATION.md
│   │   ├── REALTIME_SYSTEM_ARCHITECTURE.md
│   │   ├── EVENT_DRIVEN_TRUST_UPDATES.md
│   │   ├── AUTO_RECALCULATE_PREMIUM.md
│   │   ├── DATA_QUALITY_AND_VALIDATION.md (consolidated)
│   │   ├── ALL_LEARNINGS_SUMMARY.md
│   │   ├── CLAUDE.md
│   │   └── DOCUMENTATION_INDEX.md
│   │
│   ├── agents/                        # Agent-specific guides (12 files)
│   │   ├── DealDetector.md
│   │   ├── TrustAccountProcessor.md
│   │   ├── ExtensionMonitor.md
│   │   ├── RedemptionProcessor.md
│   │   ├── S4Processor.md
│   │   ├── FilingProcessor.md
│   │   ├── ProxyProcessor.md
│   │   ├── DelistingDetector.md
│   │   ├── CompletionMonitor.md
│   │   ├── IPODetector.md
│   │   ├── EffectivenessMonitor.md
│   │   └── ComplianceMonitor.md
│   │
│   ├── features/                      # Feature-specific docs (15 files)
│   │   ├── deal_monitoring.md
│   │   ├── redemption_tracking.md
│   │   ├── pricing_system.md
│   │   ├── news_monitoring.md
│   │   ├── reddit_sentiment.md
│   │   ├── telegram_alerts.md
│   │   ├── data_logging.md
│   │   ├── market_cap_tracking.md
│   │   ├── premium_calculation.md
│   │   ├── trust_account_updates.md
│   │   ├── deadline_extensions.md
│   │   ├── 424b4_extraction.md
│   │   ├── warrant_extraction.md
│   │   ├── founder_shares.md
│   │   └── overallotment.md
│   │
│   ├── operations/                    # Operations & deployment (5 files)
│   │   ├── PRODUCTION_SYSTEM.md (consolidated)
│   │   ├── RECOMMENDED_CRON_SCHEDULE.md
│   │   ├── MORNING_CHECKLIST.md
│   │   ├── PENDING_TASKS.md
│   │   └── TODO.md
│   │
│   └── README.md                      # Quick navigation guide
│
├── archive/
│   ├── session_summaries/             # 96 session summary files
│   ├── deprecated_architecture/       # 10 old architecture docs
│   ├── old_agents/                    # 4 obsolete agent docs
│   └── investigations/                # 9 specific issue investigations
│
└── (root - keep only essential files like CLAUDE.md, README.md)
```

---

## Cleanup Commands

```bash
cd /home/ubuntu/spac-research

# Create new structure
mkdir -p docs/{core,agents,features,operations}
mkdir -p archive/{session_summaries,deprecated_architecture,old_agents,investigations}

# Move core docs
mv AGENTIC_AI_ORCHESTRATION.md docs/core/
mv ORCHESTRATOR_ARCHITECTURE_FINAL.md docs/core/
mv SEC_FILING_ROUTING_MAP.md docs/core/
mv DATA_SOURCES_AND_PRIORITY.md docs/core/
mv IPO_DETECTOR_IMPLEMENTATION.md docs/core/
mv REALTIME_SYSTEM_ARCHITECTURE.md docs/core/
mv EVENT_DRIVEN_TRUST_UPDATES.md docs/core/
mv AUTO_RECALCULATE_PREMIUM.md docs/core/
mv DATA_QUALITY_ISSUES.md docs/core/DATA_QUALITY_AND_VALIDATION.md
mv ALL_LEARNINGS_SUMMARY.md docs/core/
mv CLAUDE.md docs/core/
mv DOCUMENTATION_INDEX.md docs/core/

# Move session summaries
mv SESSION_*.md archive/session_summaries/
mv *_SUMMARY*.md archive/session_summaries/
mv TODAYS_*.md archive/session_summaries/
mv TONIGHT_*.md archive/session_summaries/
mv TOMORROW_*.md archive/session_summaries/

# Move deprecated architecture
mv AGENTIC_SYSTEM.md archive/deprecated_architecture/
mv ARCHITECTURE.md archive/deprecated_architecture/
mv SIMPLIFIED_AGENT_ARCHITECTURE.md archive/deprecated_architecture/
mv YAML_*.md archive/deprecated_architecture/
mv AGENT_INTEGRATION_PLAN.md archive/deprecated_architecture/
mv AGENT_INTEGRATION_COMPLETE.md archive/deprecated_architecture/
mv FINAL_4_AGENT_SYSTEM.md archive/deprecated_architecture/
mv FINAL_AGENT_RECOMMENDATION.md archive/deprecated_architecture/
mv AGENT_AUDIT_2025.md archive/deprecated_architecture/

# Move old agents
mv AGENT_TRACKING_UPDATES.md archive/old_agents/
mv RESEARCH_BASED_AUTO_FIX_ARCHITECTURE.md archive/old_agents/
mv INVESTIGATION_AGENT_DESIGN.md archive/old_agents/
mv INVESTIGATION_SUMMARY.md archive/old_agents/

# Move investigations
mv OBA_*.md archive/investigations/
mv QETA_*.md archive/investigations/
mv TICKER_ANALYSIS_SUMMARY.md archive/investigations/
mv CIK_RESOLUTION_WORKFLOW.md archive/investigations/
mv EXPIRED_SPACS_*.md archive/investigations/
mv FINAL_SUMMARY_EXPIRED_SPACS.md archive/investigations/

# Move operations docs
mv PRODUCTION_SYSTEM_SUMMARY.md docs/operations/
mv DEPLOYMENT_SUMMARY.md docs/operations/
mv RECOMMENDED_CRON_SCHEDULE.md docs/operations/
mv MORNING_CHECKLIST.md docs/operations/
mv PENDING_TASKS.md docs/operations/
mv TODO.md docs/operations/

# Move feature docs
mv DEAL_MONITOR_*.md docs/features/deal_monitoring.md
mv DEADLINE_*.md docs/features/
mv LEARNING_19_REDEMPTION_TRACKING.md docs/features/redemption_tracking.md
mv REDEMPTION_TRACKING_GUIDE.md docs/features/
mv PRICING_*.md docs/features/
mv MARKET_CAP_*.md docs/features/
mv CONTINUOUS_NEWS_MONITORING_COMPLETE.md docs/features/news_monitoring.md
mv REDDIT_SENTIMENT_*.md docs/features/
mv TELEGRAM_*.md docs/features/
mv DATA_LOGGING_GUIDE.md docs/features/
mv 424B4_EXTRACTION_GUIDE.md docs/features/424b4_extraction.md
mv WARRANT_*.md docs/features/
mv FOUNDER_SHARES_*.md docs/features/
mv OVERALLOTMENT_*.md docs/features/

# Create docs README
cat > docs/README.md << 'EOF'
# SPAC Research Platform Documentation

## Quick Navigation

### Core System
- [Agentic AI Orchestration](core/AGENTIC_AI_ORCHESTRATION.md) - **Start Here**
- [SEC Filing Routing Map](core/SEC_FILING_ROUTING_MAP.md)
- [Data Sources & Priority](core/DATA_SOURCES_AND_PRIORITY.md)
- [Documentation Index](core/DOCUMENTATION_INDEX.md)

### Agents
See `agents/` directory for agent-specific documentation.

### Features
See `features/` directory for feature-specific guides.

### Operations
See `operations/` directory for deployment and daily operations.

## Archive
Historical documentation moved to `/archive/` directory.
EOF

echo "Documentation cleanup complete!"
echo "- Core docs: docs/core/ (12 files)"
echo "- Agent docs: docs/agents/ (create agent-specific docs)"
echo "- Feature docs: docs/features/ (~15 files)"
echo "- Operations: docs/operations/ (5 files)"
echo "- Archived: archive/ (120+ files)"
```

---

## Benefits of Reorganization

### ✅ Clarity
- New developers see only 12 core docs (not 156!)
- Clear structure: core → agents → features → operations

### ✅ Maintainability
- Active docs in `/docs/`
- Historical docs in `/archive/` (still searchable, not in the way)
- Easy to find relevant documentation

### ✅ Aligned with Current System
- Only documents current agentic AI orchestration
- Obsolete agent docs archived
- Session summaries archived but available for reference

---

## Action Plan

1. **Create backup:**
   ```bash
   cd /home/ubuntu
   tar -czf spac-research-docs-backup-$(date +%Y%m%d).tar.gz spac-research/*.md
   ```

2. **Run cleanup script** (above commands)

3. **Update CLAUDE.md** to reference new structure

4. **Create agent-specific docs** (12 files in `/docs/agents/`)

5. **Update root README.md** to point to `/docs/README.md`

---

**Ready to clean up?** This will make the documentation much more manageable! 📚✨

