# SPAC Orchestrator Architecture - Final Design
## October 2025

---

## Executive Summary

The SPAC Monitoring System uses an orchestrator-based architecture where specialized AI agents autonomously monitor, validate, research, investigate, and fix data issues. The system runs 24/7 via systemd and includes self-healing capabilities through the Investigation Agent.

**Key Innovation:** Autonomous investigation and root cause analysis - the system can detect anomalies, diagnose problems, and apply fixes without human intervention.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│         AUTONOMOUS MONITOR (systemd service)                 │
│              autonomous_monitor.py (24/7)                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Every 15 min:  SEC Filing Monitor                          │
│                 ├─ sec_filing_monitor.py                    │
│                 └─ Classify → Route to Filing Processors    │
│                                                              │
│  Every 1 hour:  Agent Orchestrator                          │
│                 └─ agent_orchestrator.py                    │
│                    └─ AI decides which agents to run        │
│                       └─ Investigation Agent (if anomalies) │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│         ORCHESTRATOR AGENTS (AI-scheduled)                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. DealHunterAgent        → Find new deal announcements    │
│  2. VoteTrackerAgent       → Track shareholder votes        │
│  3. PriceMonitorAgent      → Update prices (market hours)   │
│  4. RiskAnalysisAgent      → Analyze redemption risk        │
│  5. DeadlineExtensionAgent → Detect deadline extensions     │
│  6. DataValidatorAgent     → Validate data quality          │
│  7. SignalMonitorAgent     → Monitor Reddit/News signals    │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│      FILING PROCESSOR AGENTS (event-driven)                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Triggered by SEC filings:                                  │
│                                                              │
│  1. VoteExtractor         → DEF 14A (proxy statements)      │
│  2. MergerProxyExtractor  → DEFM14A (merger proxies)        │
│  3. TenderOfferProcessor  → Schedule TO (tender offers)     │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│      INVESTIGATION AGENT (autonomous problem-solving)        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Triggered when: Anomalies detected during research         │
│                                                              │
│  Workflow:                                                  │
│  1. AnomalyDetector     → Detect suspicious patterns        │
│  2. HypothesisGenerator → AI generates root cause theories  │
│  3. EvidenceCollector   → Query SEC to test hypotheses      │
│  4. RootCauseDiagnoser  → Confirm actual root cause         │
│  5. FixApplier          → Apply database fixes              │
│  6. PreventionCreator   → Create validation rules           │
│  7. DocumentWriter      → Log investigation report          │
│                                                              │
│  Example: OBA ticker reuse case (see below)                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Orchestrator (agent_orchestrator.py)

**Purpose:** Central coordination hub for all agents

**Key Classes:**
- `Orchestrator` - Main orchestration logic
- `StateManager` - Tracks agent state/last runs
- `BaseAgent` - Base class for all agents
- `AgentTask` - Task definition and scheduling

**Key Methods:**
- `decide_next_agents()` - AI determines which agents to run
- `research_issue()` - Dispatches research requests from validators
- `_detect_anomalies()` - Checks research results for suspicious patterns
- `_build_investigation_context()` - Prepares context for investigation

**Agent Scheduling:**
```python
# AI analyzes market conditions and decides which agents to run
prompt = f"""Based on market conditions, decide which agents should run.
Market is {'OPEN' if market_open else 'CLOSED'}
Time: {current_time}

Available agents:
- DealHunterAgent: Find new deal announcements
- PriceMonitorAgent: Update prices (only if market open)
- DataValidatorAgent: Validate data quality
...

Return JSON list of agents to run with priority."""

agents_to_run = ai_decides_based_on_conditions()
```

---

### 2. Investigation Agent (investigation_agent.py)

**Purpose:** Autonomous root cause analysis and fixing

**Trigger Conditions:**
1. Temporal inconsistency (e.g., deal announced 10 years before IPO)
2. Company name mismatch between database and SEC
3. Extraction failures combined with other suspicious patterns

**7-Step Workflow:**

#### Step 1: AnomalyDetector
Scans research results for suspicious patterns:
```python
if years_gap > 2:  # Deal announced >2 years before IPO
    anomalies.append({
        'type': 'temporal_inconsistency',
        'severity': 'CRITICAL',
        'primary_hypothesis': 'Wrong CIK - ticker may have been recycled'
    })
```

#### Step 2: HypothesisGenerator (AI-Powered)
Uses DeepSeek AI to generate 3-5 root cause hypotheses:
```python
hypotheses = [
    {
        'root_cause': 'Wrong CIK - ticker was recycled from old company',
        'likelihood': 90,
        'verification_steps': [
            'Query SEC for CIK company info',
            'Check SIC code (should be 6770 for SPACs)',
            'Search SEC for correct CIK using company name'
        ],
        'fix_if_true': 'Update CIK to correct company, reset deal_status'
    },
    ...
]
```

#### Step 3: EvidenceCollector
Executes verification steps to test hypotheses:
```python
evidence = {
    'sec_company_name': 'OBA Financial Services, Inc.',
    'sec_sic_code': '6035',  # NOT 6770 (SPAC code)
    'is_spac': False,
    'earliest_filing_date': '2010-05-24',
    'years_before_ipo': 15.1  # Way before IPO!
}
```

#### Step 4: RootCauseDiagnoser
Analyzes evidence to confirm root cause:
```python
if ('wrong cik' in hypothesis and
    not evidence['is_spac'] and  # Current CIK is NOT a SPAC
    evidence['years_before_ipo'] > 2):  # Filings way before IPO

    return {
        'confirmed': True,
        'root_cause': 'Wrong CIK - ticker was recycled',
        'confidence': 95
    }
```

#### Step 5: FixApplier
Applies database fixes based on diagnosis:
```python
# Search SEC for correct CIK
correct_cik = search_sec_for_company(company_name)

# Update database
spac.cik = correct_cik
spac.deal_status = 'SEARCHING'
spac.target = None
spac.announced_date = None
db.commit()
```

#### Step 6: PreventionCreator
Creates validation rules to prevent recurrence:
```python
prevention = {
    'type': 'cik_validator',
    'check': 'Verify CIK SIC code = 6770 and filing dates align with IPO',
    'schedule': 'Run weekly via cron'
}
```

#### Step 7: DocumentWriter
Logs full investigation report:
```python
investigation_report = {
    'timestamp': datetime.now(),
    'ticker': 'OBA',
    'anomalies': [...],
    'hypotheses': [...],
    'evidence': {...},
    'root_cause': 'Wrong CIK - ticker was recycled',
    'fix_applied': True,
    'prevention_created': True
}
save_to_logs(investigation_report)
send_telegram_alert(investigation_report)
```

---

## Real-World Example: OBA Investigation

### The Problem
User reported duplicate alerts: "OBA status is ANNOUNCED but no target company listed"

### Investigation Workflow

**1. Anomaly Detection**
```
Validator: OBA has ANNOUNCED status but no target
Orchestrator: Research recent 8-Ks for deal announcement
Research Result: Found deal announced 2014-09-19
Database: OBA IPO date is 2025-06-26

⚠️ ANOMALY: Deal announced 10.8 years BEFORE IPO!
```

**2. Hypothesis Generation (AI)**
```
AI generates 5 hypotheses:
1. Wrong CIK - ticker recycled (90% likelihood) ← PRIMARY
2. Data entry error (60%)
3. IPO date incorrect (40%)
4. Database merge error (25%)
5. Date parsing error (15%)
```

**3. Evidence Collection**
```
Query SEC for CIK 0001471088:
• Company: OBA Financial Services, Inc.
• SIC Code: 6035 (NOT 6770 - not a SPAC!)
• Earliest filing: 2010-05-24 (15 years before IPO)

✅ Strong evidence: Current CIK is NOT a SPAC
```

**4. Root Cause Diagnosis**
```
Hypothesis #1 confirmed with 95% confidence:
Wrong CIK - ticker "OBA" was recycled
Old company: OBA Financial Services, Inc. (defunct bank)
Correct company: Oxley Bridge Acquisition Ltd (current SPAC)
```

**5. Fix Applied**
```
Search SEC for correct CIK: Found 0002034313
Update database:
• CIK: 0001471088 → 0002034313
• Status: ANNOUNCED → SEARCHING
• Target: Cleared
• Announced date: Cleared
```

**6. Prevention Created**
```
Created CIK validator (validate_cik_mappings.py):
• Check SIC code = 6770 for all SPACs
• Verify filing dates align with IPO
• Schedule: Weekly cron job
```

**7. Documented**
```
Investigation report saved to /logs/investigation_xxxxx.json
Telegram alert sent to monitoring channel
Learnings added to self-learning database
```

### Result
✅ Problem detected, diagnosed, fixed, and prevented - **fully autonomous**

---

## Orchestrator Agents (Detailed)

### 1. DealHunterAgent
**Purpose:** Scan 8-Ks for new deal announcements

**Trigger:** Runs when market conditions suggest deals may have been announced

**Process:**
1. Query SPACs with `deal_status='SEARCHING'`
2. Fetch last 180 days of 8-K filings
3. Parse for deal keywords: "definitive agreement", "business combination"
4. Extract target, deal value, expected close
5. Update database + send Telegram alert

**Integration with Investigation Agent:**
If deal date seems suspicious (e.g., years before IPO), anomaly detector triggers investigation

---

### 2. VoteTrackerAgent
**Purpose:** Track shareholder votes from DEF 14A filings

**Trigger:** Runs for SPACs with `deal_status='ANNOUNCED'` approaching vote dates

**Process:**
1. Fetch DEF 14A filings
2. Extract vote date, record date, meeting details
3. Track voting progress (if reported in 8-Ks)
4. Update `shareholder_vote_date` in database

---

### 3. PriceMonitorAgent
**Purpose:** Update stock prices during market hours

**Trigger:** Only runs when market is OPEN (9:30 AM - 4:00 PM ET)

**Process:**
1. Fetch prices for common, unit, warrant tickers
2. Recalculate premium: `(price - trust_value) / trust_value * 100`
3. Update database
4. Alert if premium exceeds thresholds

**Multi-Source:**
- Primary: Yahoo Finance (yfinance)
- Fallback: Alpha Vantage, Polygon.io

---

### 4. RiskAnalysisAgent
**Purpose:** Analyze redemption risk and deadline urgency

**Trigger:** Runs daily for all active SPACs

**Process:**
1. Calculate `days_to_deadline`
2. Classify risk: `safe` (>180 days), `urgent` (<90 days), `expired`
3. Calculate redemption risk based on:
   - Premium (high premium = low redemption risk)
   - Days to deadline
   - Shareholder approval likelihood
4. Send alerts for high-risk SPACs

---

### 5. DeadlineExtensionAgent
**Purpose:** Detect deadline extensions from 8-Ks

**Trigger:** Runs for SPACs near deadline

**Process:**
1. Scan recent 8-Ks for extension keywords
2. Extract new deadline date
3. Update `deadline_date`, increment `extension_count`
4. Recalculate risk levels

---

### 6. DataValidatorAgent
**Purpose:** Validate data quality and trigger research when needed

**Trigger:** Runs periodically (every 6-24 hours)

**Process:**
1. Run 50+ validation rules across all SPACs
2. Classify issues by severity: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`
3. Classify confidence: `HIGH`, `MEDIUM`, `LOW`
4. **If LOW confidence:** Request orchestrator to research issue
5. If HIGH confidence: Apply auto-fix directly
6. Send Telegram alerts for unresolved issues

**Example Validations:**
```python
# Rule: ANNOUNCED but no target
if spac.deal_status == 'ANNOUNCED' and not spac.target:
    issues.append({
        'severity': 'HIGH',
        'confidence': 'LOW',  # Unclear why
        'needs_research': True,
        'fix_type': 'check_recent_8k_for_deal'
    })
```

**Research Integration:**
When validator encounters LOW confidence issues, it requests orchestrator to research:
```python
orchestrator.research_issue({
    'ticker': 'OBA',
    'field': 'target',
    'fix_type': 'check_recent_8k_for_deal',
    'cik': '0001471088'
})
```

Orchestrator dispatches DealHunterAgent → Returns research results → Anomaly detector checks results → If anomalies found, Investigation Agent triggers

---

### 7. SignalMonitorAgent
**Purpose:** Monitor Reddit/News for deal signals

**Trigger:** Runs periodically (every 4-8 hours)

**Process:**
1. Scrape r/SPACs daily discussion
2. Count mentions of each SPAC ticker
3. Analyze sentiment (bullish/bearish)
4. Extract deal speculation keywords
5. AI verifies if speculation is credible
6. Alert if high confidence deal rumors detected

**AI Verification:**
```python
article = {
    'title': 'SPAC XYZ rumored to merge with TechCorp',
    'content': '...'
}

verification = ai_verify_deal_news(ticker, article)
if verification['confidence'] > 0.75:
    send_alert(f"Credible deal rumor: {ticker} → {verification['target']}")
```

---

## Filing Processor Agents

### 1. VoteExtractor
**Purpose:** Extract vote details from DEF 14A

**Trigger:** SEC filing monitor detects DEF 14A filing

**Process:**
1. Download filing HTML
2. Extract: vote date, record date, proposal details
3. Update database
4. Alert investors of upcoming vote

---

### 2. MergerProxyExtractor
**Purpose:** Extract deal details from DEFM14A

**Trigger:** SEC filing monitor detects DEFM14A (merger proxy)

**Process:**
1. Download filing
2. Extract: deal value, target financials, vote date, sponsor economics
3. Update database with comprehensive deal details
4. Send detailed Telegram alert

---

### 3. TenderOfferProcessor
**Purpose:** Process Schedule TO filings

**Trigger:** SEC filing monitor detects Schedule TO

**Process:**
1. Parse tender offer details
2. Extract: offer price, expiration date, conditions
3. Alert if offer is at significant premium/discount

---

## Data Flow Example

### Scenario: New Deal Announcement Detected

```
1. SEC RSS Monitor (every 15 min)
   └─ Detects 8-K filing for ticker CEP
      └─ Classifies as "potential deal announcement"

2. SEC Filing Monitor
   └─ Routes to MergerProxyExtractor (if DEFM14A)
   └─ Or queues for DealHunterAgent (if 8-K)

3. DealHunterAgent (next hourly run)
   └─ Orchestrator decides to run DealHunterAgent
   └─ Agent fetches 8-K, parses for deal keywords
   └─ Extracts: target="TechCorp", deal_value="$300M"
   └─ Research result: {deal_found: true, announced_date: "2025-10-09"}

4. Anomaly Detector
   └─ Checks: Is announced_date reasonable relative to IPO?
   └─ No anomalies detected ✓

5. Orchestrator
   └─ Returns research result to DataValidator
   └─ Validator applies fix:
      - Updates deal_status = 'ANNOUNCED'
      - Sets target = 'TechCorp'
      - Sets announced_date = '2025-10-09'

6. Telegram Alert
   └─ Sends notification:
      "🎯 NEW DEAL: CEP announced merger with TechCorp
       Deal Value: $300M
       Premium: 8.5%"

7. Future Monitoring
   └─ VoteTrackerAgent monitors for vote date
   └─ PriceMonitorAgent tracks premium changes
   └─ RiskAnalysisAgent assesses deal completion probability
```

---

## Investigation Agent Integration

### When Does Investigation Trigger?

**From Orchestrator.research_issue():**
```python
if deal_found:
    anomalies = self._detect_anomalies(research_result, research_request)

    if anomalies:
        # Trigger Investigation Agent
        investigator = InvestigationAgent()
        investigation_report = investigator.investigate(
            issue=research_request,
            research_result=research_result,
            context=context
        )

        return investigation_report  # Contains fix that was applied
```

**Anomaly Detection Rules:**
1. **Temporal Inconsistency:** Deal date >2 years before/after IPO
2. **Company Name Mismatch:** Database name != SEC name
3. **Extraction Failure + Suspicious Data:** Deal found but can't extract target + other red flags

---

## Error Handling & Resilience

### 1. Graceful Degradation
If AI service fails, agents fall back to rule-based logic:
```python
try:
    ai_response = deepseek.chat(prompt)
except Exception:
    # Fallback to rules
    return rule_based_extraction(filing)
```

### 2. Rate Limiting
SEC requests limited to 10/second:
```python
time.sleep(0.15)  # 150ms between requests
```

### 3. State Persistence
`StateManager` tracks last run times to prevent duplicate work:
```json
{
  "DealHunterAgent": {"last_run": "2025-10-09 14:30:00"},
  "PriceMonitorAgent": {"last_run": "2025-10-09 15:00:00"}
}
```

### 4. Investigation Failure Handling
If investigation fails to find correct CIK:
```python
# Partial fix: At least clear bad data
spac.deal_status = 'SEARCHING'
spac.target = None
spac.announced_date = None

return {
    'fix_applied': True,
    'partial': True,
    'warning': 'Could not find correct CIK - manual verification needed'
}
```

---

## Monitoring & Alerts

### Telegram Alerts

**Critical Alerts:**
- New deal announcements
- Investigation results (wrong CIK detected and fixed)
- Validation failures that couldn't be auto-fixed
- Deadline approaching (<30 days)

**Info Alerts:**
- Price changes >5%
- Deal rumors with high confidence
- Vote dates announced

**Alert Format:**
```
🔍 INVESTIGATION COMPLETE - OBA

Root Cause: Wrong CIK - ticker was recycled
Confidence: 95%

Fix Applied:
• CIK: 0001471088 → 0002034313
• Status: ANNOUNCED → SEARCHING
• Cleared stale data

Report: /logs/investigation_e1db693342cc.json
```

---

## Performance & Scalability

### Current Performance
- **155 SPACs** monitored continuously
- **Orchestrator:** Runs every 1 hour
- **SEC Monitor:** Runs every 15 minutes
- **Average Investigation:** 10-15 seconds end-to-end

### Resource Usage
- **Database:** PostgreSQL (100-200 MB)
- **Memory:** ~500 MB (all agents loaded)
- **API Costs:** ~$2-5/month (DeepSeek API)
- **Server:** AWS EC2 t2.small sufficient

### Scalability
Can scale to 1000+ SPACs with:
- Parallel agent execution
- Cached SEC data
- Database indexing

---

## Deployment

### Systemd Service
```bash
# Install service
sudo cp autonomous_monitor.service /etc/systemd/system/
sudo systemctl enable autonomous_monitor
sudo systemctl start autonomous_monitor

# Check status
sudo systemctl status autonomous_monitor

# View logs
journalctl -u autonomous_monitor -f
```

### Configuration
```bash
# Environment variables (.env)
DATABASE_URL=postgresql://spac_user:spacpass123@localhost:5432/spac_db
DEEPSEEK_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

---

## Testing

### Investigation Agent Test
```bash
python3 test_investigation_agent_auto.py
```

**Test Scenario:**
1. Sets up OBA with wrong CIK (simulates ticker reuse)
2. Triggers investigation
3. Verifies:
   - Anomaly detection works
   - Hypotheses generated correctly
   - Evidence collected from SEC
   - Root cause diagnosed
   - Fix applied (CIK updated)
   - Prevention measures created

**Expected Result:** ✅ TEST PASSED - All checks complete

---

## Future Enhancements

### 1. Multi-SPAC Investigations
Detect patterns across multiple SPACs (e.g., same data quality issue affecting 10+ SPACs)

### 2. Predictive Deal Detection
ML model to predict which SPACs are likely to announce deals soon based on:
- Filing patterns
- Reddit sentiment
- Banker history
- Time since IPO

### 3. Automated Compliance Monitoring
Track S-1 amendments, DEF 14A revisions, etc. to detect material changes

### 4. Portfolio Optimization
Suggest optimal SPAC portfolio based on:
- Risk tolerance
- Deal probability
- Premium levels
- Deadline urgency

---

## Conclusion

The SPAC Orchestrator Architecture represents a fully autonomous monitoring and self-healing system. The Investigation Agent closes the loop by enabling the system to detect, diagnose, and fix data anomalies without human intervention - replicating the problem-solving process a human would use.

**Key Achievements:**
- ✅ 7 specialized orchestrator agents
- ✅ 3 filing processor agents
- ✅ 1 autonomous investigation agent
- ✅ Research-based auto-fix architecture
- ✅ Anomaly detection and root cause analysis
- ✅ Self-healing through Investigation Agent
- ✅ 24/7 monitoring via systemd
- ✅ Comprehensive Telegram alerting
- ✅ Clean codebase (25 agents archived)

**Verified in Production:**
The Investigation Agent successfully solved the OBA ticker reuse case autonomously, demonstrating end-to-end autonomous problem-solving capability.
