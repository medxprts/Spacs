# SEC Filing → Agent Routing Map

**Date:** October 10, 2025
**Purpose:** Complete mapping of SEC filing types to orchestration agent routing

---

## Architecture Overview

```
SEC Filing Monitor (polls every 15 min)
    ↓
Filing Classifier (AI + rule-based)
    ↓
Agent Orchestrator (multi-agent dispatch)
    ↓
Specialized Agents (async processing)
    ↓
Database Updates + Notifications
```

---

## Filing Classification System

The **SEC Filing Monitor** (`sec_filing_monitor.py`) continuously polls SEC EDGAR for new filings from tracked SPACs. When a new filing is detected, it's classified by:

1. **Rule-based pre-filtering** (Lines 164-279)
2. **AI classification** for 8-Ks (DeepSeek analyzes Item numbers)
3. **Agent routing** via orchestrator

---

## Complete Filing Type → Agent Mapping

### 🔴 **CRITICAL PRIORITY**

#### Form 25 - Delisting/Liquidation Notice
- **Priority:** CRITICAL
- **Agent:** `DelistingDetector`
- **Reason:** Indicates SPAC is delisting (liquidation or deal closure)
- **Dispatcher:** `_dispatch_delisting_detector()` (Line 1097)
- **What it does:**
  - Detects if SPAC is liquidating (failed to close deal)
  - Updates `deal_status` to 'LIQUIDATED'
  - Sends critical alert (investors lose opportunity)

---

### 🟠 **HIGH PRIORITY**

#### 8-K - Current Report
- **Priority:** HIGH (if Item 1.01, 2.01, 5.03) / MEDIUM (other items)
- **Agents:** `DealDetector`, `ExtensionMonitor`, `CompletionMonitor`, `RedemptionProcessor`
- **Reason:** Contains material events (deals, extensions, redemptions, closings)
- **AI Classification:** DeepSeek analyzes filing to determine Item number
- **Dispatcher:** Multiple depending on Item:
  - `_dispatch_deal_detector()` (Line 978) - Item 1.01 (material agreement)
  - `_dispatch_extension_monitor()` (Line 1029) - Item 5.03 (charter amendment)
  - `_dispatch_completion_monitor()` (Line 1144) - Item 2.01 (acquisition completed)
  - `_dispatch_redemption_processor()` (Line 1052) - Redemption results (often Item 8.01)

**Critical 8-K Item Numbers:**
- **Item 1.01:** Material agreement → `DealDetector`
- **Item 2.01:** Completion of acquisition → `CompletionMonitor`
- **Item 5.03:** Charter amendments (deadline extensions) → `ExtensionMonitor`
- **Item 7.01/8.01:** Regulation FD (press releases) → May route to multiple agents
- **Item 4.02:** Non-reliance on prior financials → `ComplianceMonitor`

**What DealDetector does:**
- AI extracts target company, deal value, expected close date
- Updates `deal_status` from 'SEARCHING' → 'ANNOUNCED'
- Populates `target`, `announced_date`, `deal_value`, `expected_close`
- Sends Telegram notification

**What ExtensionMonitor does:**
- Detects deadline extensions (typically +3 or +6 months)
- Updates `deadline_date`, sets `is_extended=True`
- Increments `extension_count`
- Recalculates `risk_level` and `days_to_deadline`

**What CompletionMonitor does:**
- Detects when deal closes (post-merger)
- Updates `deal_status` to 'CLOSED'
- Records final redemption numbers, deal completion date
- Captures post-merger ticker

**What RedemptionProcessor does:**
- Extracts redemption data (shares redeemed, price, remaining trust)
- Updates `redemption_shares`, `redemption_percentage`, `trust_cash`
- Recalculates `premium` based on reduced trust value

---

#### Form 425 - Merger Communication
- **Priority:** HIGH
- **Agent:** `DealDetector`
- **Reason:** Ongoing deal communications (updated terms, investor presentations)
- **Dispatcher:** `_dispatch_deal_detector()` (Line 978)
- **What it does:**
  - Parses investor presentations for deal updates
  - May find revised deal value or terms
  - Typically filed after initial 8-K announcement

---

#### S-4 - Merger Registration Statement
- **Priority:** HIGH
- **Agent:** `S4Processor`
- **Reason:** Comprehensive merger terms and pro forma financials
- **Dispatcher:** `_dispatch_s4_processor()` (Line 1067)
- **What it does:**
  - AI extracts detailed deal structure
  - Gets pro forma revenue, EBITDA, valuation multiples
  - Captures `pipe_investment`, `sponsor_commitment`
  - Updates `deal_valuation`, `target_revenue`, `target_ebitda`
  - Parses founder share dilution and warrant terms

**Key S-4 Data Extracted:**
- Pro forma financials (revenue, EBITDA, cash flow)
- PIPE investment amount and investors
- Sponsor economics and lock-ups
- Valuation multiples (EV/Revenue, EV/EBITDA)
- Share dilution from founder shares
- Earnout structures

---

#### S-4/A - S-4 Amendment
- **Priority:** HIGH
- **Agent:** `S4Processor`
- **Reason:** Updated merger terms (often critical changes)
- **Dispatcher:** `_dispatch_s4_processor()` (Line 1067)
- **What it does:**
  - Same as S-4, but may have revised deal terms
  - Common amendments: updated financials, changed vote dates

---

#### DEF 14A - Definitive Proxy Statement
- **Priority:** HIGH
- **Agent:** `FilingProcessor`
- **Reason:** Shareholder vote details and final deal terms
- **Dispatcher:** `_dispatch_filing_processor()` (Line 1001)
- **What it does:**
  - Extracts `shareholder_vote_date`
  - Gets vote recommendation (FOR/AGAINST)
  - Updates vote threshold requirements
  - Confirms final deal terms before vote

---

#### DEFM14A / PREM14A - Merger Proxy Statements
- **Priority:** HIGH
- **Agents:** `FilingProcessor`
- **Reason:** Comprehensive merger proxy (detailed deal terms + vote info)
- **Dispatcher:** `_dispatch_filing_processor()` (Line 1001)
- **What it does:**
  - Similar to DEF 14A but merger-specific
  - DEFM14A = definitive merger proxy (final)
  - PREM14A = preliminary merger proxy (draft)
  - Extracts vote date, deal terms, fairness opinions

---

#### DEFA14A - Additional Proxy Materials
- **Priority:** HIGH
- **Agent:** `ProxyProcessor`
- **Reason:** Supplemental proxy materials (vote updates, deal changes)
- **Dispatcher:** `_dispatch_proxy_processor()` (Line 1082)
- **What it does:**
  - Processes proxy supplements
  - May contain updated redemption estimates
  - Common right before shareholder vote

---

#### SC TO / SC TO-T - Tender Offer Schedules
- **Priority:** HIGH
- **Agent:** `FilingProcessor`
- **Reason:** No-vote deal path (tender offer instead of shareholder vote)
- **Dispatcher:** `_dispatch_filing_processor()` (Line 1001)
- **What it does:**
  - Detects tender offers (alternative to proxy vote)
  - Updates vote mechanism to "TENDER OFFER"
  - Extracts offer terms and deadline

---

### 🟡 **MEDIUM PRIORITY**

#### 424B4 - Final Prospectus (IPO Closing)
- **Priority:** MEDIUM
- **Agent:** `IPODetector`
- **Reason:** IPO has closed - graduate pre-IPO SPAC to main pipeline
- **Dispatcher:** `_dispatch_ipo_detector()` (Line 1159)
- **What it does:**
  - **Checks if 424B4 is for a tracked pre-IPO SPAC** (via CIK match)
  - If yes: **AI extracts IPO data** from prospectus
    - IPO proceeds (e.g., "$200M")
    - Unit structure (e.g., "1 share + 1/3 warrant")
    - Deadline months (typically 18-24)
    - Shares issued, trust per unit, warrant exercise price
  - **Graduates SPAC** from `pre_ipo` database → `main` database
    - Sets `deal_status='SEARCHING'` (newly public!)
    - Calculates `deadline_date` = IPO date + deadline months
    - Updates pre-IPO record: `filing_status='Closed'`

**AI Extraction Pattern:**
```python
prompt = """Extract SPAC IPO data from this 424B4 prospectus. Return ONLY valid JSON.

Required fields:
- ipo_proceeds: Gross proceeds as string (e.g., "$200M")
- unit_structure: Unit composition (e.g., "1 share + 1/3 warrant")
- deadline_months: Months until business combination deadline (integer, typically 18-24)
- shares_issued: Number of units sold in millions (float)
- trust_per_unit: Cash per unit in trust (typically 10.00)
- warrant_exercise_price: Warrant exercise price (typically 11.50)

Text excerpt:
{text}

Return JSON only (use null for missing fields):"""
```

**Example IPO Graduation Flow:**
1. Pre-IPO SPAC "NEWT" has `filing_status='EFFECTIVE'` (S-1 effective)
2. SEC monitor detects 424B4 filing for CIK matching "NEWT"
3. IPODetector agent extracts IPO data via AI
4. Creates new SPAC in main database:
   - `ticker='NEWT'`
   - `deal_status='SEARCHING'`
   - `ipo_date='2025-10-10'`
   - `deadline_date='2027-04-10'` (IPO date + 18 months)
   - `ipo_proceeds='$200M'`
   - `unit_structure='1 share + 1/3 warrant'`
5. Updates pre-IPO record: `filing_status='Closed'`, `moved_to_main_pipeline=True`

**Important:** This is **event-driven** (15-min polling) with **daily batch backup** via `pre_ipo_ipo_close_monitor_ai.py` at 9 AM.

---

#### S-1 - IPO Registration Statement
- **Priority:** MEDIUM
- **Agent:** `IPODetector`
- **Reason:** Pre-IPO registration (may not be closed yet)
- **Dispatcher:** `_dispatch_ipo_detector()` (Line 1159)
- **What it does:**
  - Checks if S-1 is from tracked pre-IPO SPAC
  - Usually doesn't graduate yet (waiting for 424B4)
  - May extract preliminary IPO terms

---

#### 8-K/A - 8-K Amendment
- **Priority:** MEDIUM
- **Agents:** `DealDetector`, `RedemptionProcessor`
- **Reason:** Corrected 8-K (may fix deal terms or redemption numbers)
- **Dispatcher:** `_dispatch_deal_detector()` or `_dispatch_redemption_processor()`
- **What it does:**
  - Re-processes original 8-K with corrections
  - Often used to correct redemption numbers or deal values

---

#### 10-Q - Quarterly Report
- **Priority:** MEDIUM
- **Agent:** `TrustAccountProcessor`
- **Reason:** Trust account balance update (quarterly NAV)
- **Dispatcher:** `_dispatch_trust_processor()` (Line 1015)
- **What it does:**
  - Extracts trust account balance from balance sheet
  - Updates `trust_cash` and recalculates `trust_value` per share
  - AI parses financial statements for precise NAV

---

#### 10-K - Annual Report
- **Priority:** MEDIUM
- **Agent:** `TrustAccountProcessor`
- **Reason:** Annual trust account data (comprehensive financials)
- **Dispatcher:** `_dispatch_trust_processor()` (Line 1015)
- **What it does:**
  - Same as 10-Q but annual (more detailed)
  - May include sponsor economics disclosure
  - Validates trust account reconciliation

---

#### 10-Q/A / 10-K/A - Financial Report Amendments
- **Priority:** MEDIUM
- **Agent:** `TrustAccountProcessor`
- **Reason:** Corrected financial data
- **Dispatcher:** `_dispatch_trust_processor()` (Line 1015)
- **What it does:**
  - Updates trust account data with corrected figures
  - May indicate accounting errors

---

#### EFFECT - Effectiveness Notice
- **Priority:** MEDIUM
- **Agent:** `EffectivenessMonitor`
- **Reason:** S-4 registration effective (merger can proceed)
- **Dispatcher:** `_dispatch_effectiveness_monitor()` (Line 1189)
- **What it does:**
  - Marks S-4 as effective
  - Updates `s4_effective_date`
  - Indicates deal is getting closer to closing

---

### 🟢 **LOW PRIORITY**

#### NT 10-Q / NT 10-K - Notice of Late Filing
- **Priority:** LOW
- **Agent:** `ComplianceMonitor`
- **Reason:** Compliance issue (late filing)
- **Dispatcher:** `_dispatch_compliance_monitor()` (Line 1193)
- **What it does:**
  - Flags SPAC as non-compliant
  - May indicate financial distress or operational issues
  - Updates `compliance_issues` field

---

#### Other Filing Types
- **Priority:** LOW
- **Agents:** None (skipped)
- **Reason:** Standard filing with no actionable SPAC data
- **Examples:** 3, 4, 5 (insider transactions), SC 13D/G (beneficial ownership)

---

## Agent Dispatcher Methods

All agent dispatchers are in `agent_orchestrator.py` (Lines 978-1193):

| Agent Name | Dispatcher Method | Line | Primary Filing Types |
|-----------|------------------|------|---------------------|
| `DealDetector` | `_dispatch_deal_detector()` | 978 | 8-K (Item 1.01), 425 |
| `FilingProcessor` | `_dispatch_filing_processor()` | 1001 | DEF 14A, DEFM14A, PREM14A, SC TO |
| `TrustAccountProcessor` | `_dispatch_trust_processor()` | 1015 | 10-Q, 10-K |
| `ExtensionMonitor` | `_dispatch_extension_monitor()` | 1029 | 8-K (Item 5.03) |
| `RedemptionProcessor` | `_dispatch_redemption_processor()` | 1052 | 8-K (redemption results) |
| `S4Processor` | `_dispatch_s4_processor()` | 1067 | S-4, S-4/A |
| `ProxyProcessor` | `_dispatch_proxy_processor()` | 1082 | DEFA14A |
| `DelistingDetector` | `_dispatch_delisting_detector()` | 1097 | Form 25 |
| `CompletionMonitor` | `_dispatch_completion_monitor()` | 1144 | 8-K (Item 2.01) |
| `IPODetector` | `_dispatch_ipo_detector()` | 1159 | 424B4, S-1 |
| `EffectivenessMonitor` | `_dispatch_effectiveness_monitor()` | 1189 | EFFECT |
| `ComplianceMonitor` | `_dispatch_compliance_monitor()` | 1193 | NT 10-Q, NT 10-K |

---

## AI-Enhanced Filing Classification

### 8-K Item Number Detection

For **8-K filings**, the system uses **AI classification** to determine Item numbers:

```python
def _classify_8k_with_ai(self, filing: Dict) -> Dict:
    """Use AI to classify 8-K filing by determining Item number"""

    prompt = f"""
Classify this SEC 8-K filing to determine priority and routing:

Filing Type: {filing['type']}
Date: {filing['date']}
Title: {filing['title']}
Summary: {filing['summary']}

Determine:
1. Most likely Item number (1.01, 5.03, 2.01, etc.)
2. Priority (HIGH/MEDIUM/LOW)
3. Which agents should process it

Agents available:
- DealDetector: Detects business combination announcements
- ExtensionMonitor: Detects deadline extensions and redemptions
- CompletionMonitor: Detects deal closures

Return JSON:
{
    "item_number": "1.01",
    "priority": "HIGH",
    "agents_needed": ["DealDetector"],
    "reason": "Likely business combination announcement"
}
"""
```

**AI Model:** DeepSeek Chat (cost-effective, OpenAI-compatible)

**Why AI for 8-Ks:** Item numbers aren't in filing title/summary, need to analyze content

---

## Multi-Agent Routing Example

**Scenario:** SPAC files 8-K announcing deal + redemption results

1. **SEC Monitor** detects new 8-K filing
2. **AI Classifier** analyzes content:
   - Item 1.01: Business combination agreement
   - Item 8.01: Exhibit 99.1 with redemption results
3. **Orchestrator** routes to **multiple agents**:
   - `DealDetector` → Extracts target, deal value
   - `RedemptionProcessor` → Extracts shares redeemed
4. **Both agents** process filing in parallel
5. **Database** updated with both deal data + redemption data

---

## Monitoring Modes

### Real-Time Event-Driven (15-minute polling)
```bash
# Run SEC filing monitor continuously
python3 sec_filing_monitor.py
```

### Daily Batch Backup (9 AM cron)
```bash
# Daily SPAC update script (includes IPO close monitoring)
/home/ubuntu/spac-research/daily_spac_update.sh
```

**Key Scripts:**
- `sec_filing_monitor.py` - Real-time RSS polling (every 15 min)
- `agent_orchestrator.py` - Routes filings to agents
- `daily_spac_update.sh` - Daily batch job (backup + data quality checks)

---

## Agent Implementation Pattern

All agents follow the **BaseAgent** pattern from `agents/base_agent.py`:

```python
class ExampleAgent(BaseAgent):
    async def can_process(self, filing: Dict) -> bool:
        """Check if this agent should process this filing"""
        # Return True if filing is relevant
        pass

    async def process(self, filing: Dict) -> Optional[Dict]:
        """Process the filing and return results"""
        # Extract data using AI + regex
        # Update database
        # Return results dict
        pass
```

**AI Extraction Pattern** (hybrid regex + AI):
1. Try **regex first** (fast, common patterns)
2. Use **AI for missing fields** (DeepSeek extraction)
3. **Merge results** (regex + AI)

**Example from IPODetector:**
```python
# Try regex first (fast)
data = self._extract_with_regex(text)

# Use AI for missing fields
if AI_AVAILABLE:
    if not data.get('ipo_proceeds') or not data.get('unit_structure'):
        ai_data = self._extract_with_ai(text)
        # Merge AI results
        for key, value in ai_data.items():
            if value and not data.get(key):
                data[key] = value
```

---

## Key Learnings

### Learning #21: Multi-Format Ticker Discovery
When fetching prices for units/warrants/rights, try **multiple ticker formats**:
- Units: `TICKER.U`, `TICKER-U`, `TICKER U`, `TICKER/U`
- Warrants: `TICKERW`, `TICKER.W`, `TICKER.WS`, `TICKER-WT`
- Rights: `TICKERR`, `TICKER.R`, `TICKER R`

### Learning #22: Component Price Validation
**Rule:** If common + warrant prices exist → unit price MUST exist
**Rule:** If unit + common prices exist → warrant OR rights MUST exist

### Learning #23: IPO Detection (NEW)
**Real-time + Batch:** 424B4 detection now works in **two modes**:
1. **Event-driven** (SEC monitor → orchestrator → IPODetector) - 15 min
2. **Batch backup** (daily cron job) - 9 AM

**Graduation:** Pre-IPO SPACs automatically move to main pipeline when 424B4 filed

---

*Last updated: October 10, 2025*
