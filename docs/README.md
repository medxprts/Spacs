# SPAC Research Platform Documentation

## 🎯 Quick Start

**New to the system?** Start here:
1. [CLAUDE.md](../CLAUDE.md) - Project overview & development commands
2. [Agentic AI Orchestration](core/AGENTIC_AI_ORCHESTRATION.md) - Complete system overview ⭐
3. [SEC Filing Routing Map](core/SEC_FILING_ROUTING_MAP.md) - How filings route to agents
4. [Data Sources & Priority](core/DATA_SOURCES_AND_PRIORITY.md) - Where data comes from

---

## 📂 Documentation Structure

### Core System (`core/`)
**Essential reading for understanding the system**

- **AGENTIC_AI_ORCHESTRATION.md** - Master orchestration guide ⭐
- **ORCHESTRATOR_ARCHITECTURE_FINAL.md** - Orchestrator design patterns
- **SEC_FILING_ROUTING_MAP.md** - Complete filing → agent routing ⭐
- **DATA_SOURCES_AND_PRIORITY.md** - Field → source mapping ⭐
- **IPO_DETECTOR_IMPLEMENTATION.md** - IPO graduation system
- **REALTIME_SYSTEM_ARCHITECTURE.md** - Real-time monitoring (15-min polling)
- **EVENT_DRIVEN_TRUST_UPDATES.md** - Trust account update flow
- **AUTO_RECALCULATE_PREMIUM.md** - Dependent data relationships
- **DATA_QUALITY_AND_VALIDATION.md** - Data quality lessons & validation
- **ALL_LEARNINGS_SUMMARY.md** - System learnings (23+ learnings)
- **DOCUMENTATION_INDEX.md** - Complete documentation index

---

### Features (`features/`)
**Feature-specific implementation guides**

#### Deal & Lifecycle Monitoring
- Deal monitoring guides
- Deadline extension detection
- Redemption tracking (Learning #19)
- Lifecycle detection

#### Pricing & Market Data
- Pricing system
- Market cap tracking
- Component price discovery (Learning #21, #22)
- Premium calculation

#### News & Sentiment
- News monitoring
- Reddit sentiment tracking
- RSS feeds
- Signal triggers

#### Alerts
- Telegram alerts
- Telegram bot setup

#### SEC Filing Extraction
- 424B4 extraction
- Warrant extraction
- Founder shares tracking
- Overallotment detection

---

### Operations (`operations/`)
**Deployment & daily operations**

- **PRODUCTION_SYSTEM_SUMMARY.md** - Production deployment
- **RECOMMENDED_CRON_SCHEDULE.md** - Cron job schedule
- **MORNING_CHECKLIST.md** - Daily checklist
- **OVERNIGHT_DATA_COVERAGE_PLAN.md** - Overnight improvement strategy
- **PENDING_TASKS.md** - Current tasks
- **TODO.md** - TODO list

---

### Agents (`agents/`)
**Agent-specific documentation** (to be created)

Planned agent-specific docs for:
- DealDetector
- TrustAccountProcessor
- ExtensionMonitor
- RedemptionProcessor
- S4Processor
- FilingProcessor
- ProxyProcessor
- DelistingDetector
- CompletionMonitor
- IPODetector ✅
- EffectivenessMonitor
- ComplianceMonitor

---

## 📚 Archive (`../archive/`)

Historical documentation moved to archive:
- `session_summaries/` - 96 session summary files
- `deprecated_architecture/` - Old architecture docs
- `old_agents/` - Archived agent documentation
- `investigations/` - Specific issue investigations (OBA, QETA, etc.)

---

## 🔑 Key Concepts

### Agentic AI Orchestration
- **SEC Filing Monitor** polls every 15 minutes
- **Filing Classifier** routes filings to appropriate agents (AI-enhanced for 8-Ks)
- **12 Specialized Agents** process filings and update database
- **Tracker System** auto-recalculates dependent fields
- **Investigation Agent** diagnoses and fixes data anomalies

### Data Priority Rules
1. **Most Recent > Older** - Later filings override earlier
2. **Primary SEC > Secondary** - Official docs > APIs
3. **Specific > General** - Detailed filings (S-4) > summaries (8-K)
4. **Event-Driven > Batch** - Real-time updates > daily jobs
5. **Calculated > Stored** - Always recalculate from source

### Filing → Agent Routing
- **8-K** → AI determines Item number → Routes to DealDetector, ExtensionMonitor, etc.
- **424B4** → IPODetector (graduates pre-IPO SPACs)
- **S-4** → S4Processor (deal structure)
- **10-Q/10-K** → TrustAccountProcessor (trust cash)
- **DEF 14A** → FilingProcessor (vote dates)
- **Form 25** → DelistingDetector (delisting/completion)

---

## 🚀 Common Tasks

### "I want to understand the system"
1. Read [AGENTIC_AI_ORCHESTRATION.md](core/AGENTIC_AI_ORCHESTRATION.md)
2. Review [SEC_FILING_ROUTING_MAP.md](core/SEC_FILING_ROUTING_MAP.md)
3. Check [ALL_LEARNINGS_SUMMARY.md](core/ALL_LEARNINGS_SUMMARY.md)

### "I want to add a new data field"
1. Understand sourcing: [DATA_SOURCES_AND_PRIORITY.md](core/DATA_SOURCES_AND_PRIORITY.md)
2. Find which agent extracts it: [SEC_FILING_ROUTING_MAP.md](core/SEC_FILING_ROUTING_MAP.md)
3. Check dependent fields: [AUTO_RECALCULATE_PREMIUM.md](core/AUTO_RECALCULATE_PREMIUM.md)

### "I want to deploy the system"
1. [PRODUCTION_SYSTEM_SUMMARY.md](operations/PRODUCTION_SYSTEM_SUMMARY.md)
2. [RECOMMENDED_CRON_SCHEDULE.md](operations/RECOMMENDED_CRON_SCHEDULE.md)
3. [MORNING_CHECKLIST.md](operations/MORNING_CHECKLIST.md)

### "I want to improve data coverage"
1. [OVERNIGHT_DATA_COVERAGE_PLAN.md](operations/OVERNIGHT_DATA_COVERAGE_PLAN.md)

---

## 📊 Documentation Statistics

- **Active Core Docs:** 11 files
- **Feature Docs:** ~20 files
- **Operations Docs:** 7 files
- **Archived Docs:** 120+ files
- **Total:** 158 files (40 active, 118 archived)

---

**Last Updated:** October 10, 2025
**Maintainer:** Claude Code AI System
