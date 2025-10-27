# SPAC Data Sources and Priority Logic

**Date:** October 10, 2025
**Purpose:** Complete mapping of data field → potential sources → priority logic

---

## Overview

This document maps every SPAC database field to its potential data sources and defines the priority/precedence rules when multiple sources exist for the same field.

---

## Data Source Priority Framework

### General Principles

1. **Most Recent > Older**: Later filings override earlier filings (except for immutable fields like IPO data)
2. **Primary SEC Filings > Secondary Sources**: Official SEC documents > market data APIs > manual entry
3. **Specific > General**: Detailed filings (S-4, DEFM14A) > summary filings (8-K press releases)
4. **Event-Driven > Batch**: Real-time filing monitor updates > daily batch scraping
5. **Calculated Fields**: Always recalculate from source data, never store stale calculations

---

## Field-by-Field Data Source Mapping

### Core Identification Fields

#### `ticker` (String)
**Sources:**
1. **Manual entry** (initial SPAC creation)
2. **424B4 prospectus** - AI extraction from IPO filing (IPODetector agent)
3. **8-K press release** (Exhibit 99.1) - AI extraction

**Priority Logic:**
- Use **424B4** as authoritative source (official ticker assignment)
- Fall back to **8-K** if 424B4 not yet filed
- Manual entry only for initial tracking

**Update Trigger:** Never changes after IPO (immutable)

---

#### `company` (String)
**Sources:**
1. **424B4 prospectus** - Cover page
2. **SEC Company Search API** - CIK lookup
3. **8-K press release** - Company name mentioned

**Priority Logic:**
- Use **424B4 cover page** (official legal name)
- If not available, use **SEC API** lookup by CIK
- Validate: Company name should match CIK entity (Investigation Agent checks this)

**Update Trigger:** Only update if Investigation Agent discovers wrong CIK

---

#### `cik` (String)
**Sources:**
1. **SEC Company Search API** - Search by company name
2. **Manual entry** - Initial tracking
3. **Investigation Agent** - Auto-correction when wrong CIK detected

**Priority Logic:**
- **Investigation Agent correction** > **SEC API** > **Manual entry**
- Validation: CIK must have SIC code 6770 (SPAC designation)
- Validation: Filing dates must align with IPO date (no filings >2 years before IPO)

**Update Trigger:**
- Only update if Investigation Agent detects ticker was recycled
- Run weekly CIK validator (`validate_cik_mappings.py`)

---

### IPO Data Fields (Immutable After IPO)

#### `ipo_date` (Date)
**Sources:**
1. **424B4 filing date** (authoritative - IPO closed)
2. **8-K press release** (Exhibit 99.1) - AI extraction from IPO closing announcement
3. **SEC Company Search** - First 424B4 filing date

**Priority Logic:**
- Use **424B4 filing date** (this is the official IPO close date)
- If AI extracts different date from press release, investigate discrepancy
- Never update after initial set (immutable)

**Extracted By:** IPODetector agent (AI + regex), `sec_data_scraper.py` (legacy batch)

---

#### `ipo_proceeds` (String, e.g., "$200M")
**Sources:**
1. **424B4 prospectus** - Cover page or "The Offering" section (AI extraction)
2. **8-K press release** - IPO closing announcement (AI extraction)
3. **S-1 registration** - Expected proceeds (preliminary)

**Priority Logic:**
- **424B4** (authoritative - actual proceeds)
- **8-K** if 424B4 extraction fails
- Never use S-1 (those are projected, not actual)

**Extracted By:** IPODetector agent (DeepSeek AI), `extract_424b4_enhanced()` (AI Agent #3)

---

#### `unit_structure` (String, e.g., "1 share + 1/3 warrant")
**Sources:**
1. **424B4 prospectus** - "Description of Securities" section
2. **8-K press release** - IPO announcement
3. **S-1 registration** - Preliminary structure

**Priority Logic:**
- **424B4** (final structure)
- **8-K** (usually matches 424B4)
- **S-1** only if neither 424B4 nor 8-K available

**Extracted By:** IPODetector agent (AI + regex), `sec_data_scraper.py` (AI Agent #1)

**Used For:** Validation before warrant extraction (prevents hallucination for rights-only SPACs)

---

#### `shares_outstanding` / `shares_outstanding_base` (Float, millions)
**Sources:**
1. **10-Q/10-K financial statements** - Balance sheet or equity notes (most current)
2. **8-K redemption results** - Post-redemption share count
3. **424B4 prospectus** - Initial IPO share count (AI extraction)
4. **Calculated**: `shares_outstanding_base + overallotment_units` (if overallotment exercised)

**Priority Logic:**
1. **10-Q/10-K** (most recent quarterly/annual) via TrustAccountProcessor
2. **8-K redemption results** via RedemptionProcessor
3. **424B4** for initial IPO baseline
4. **Never use Yahoo Finance** - often stale or includes post-merger dilution

**Auto-Recalculation Triggers:**
- **Redemption detected** (8-K Item 9.01) → `shares_outstanding -= shares_redeemed`
- **10-Q/10-K parsed** → Update to latest reported shares
- **Updates** `trust_value` and `premium` automatically via tracker

**Extracted By:** TrustAccountProcessor, RedemptionProcessor, IPODetector

---

#### `deadline_months` (Integer, typically 18-24)
**Sources:**
1. **424B4 prospectus** - "Business Combination" section (AI extraction)
2. **S-1 registration** - Charter description
3. **Default**: 18 months if extraction fails

**Priority Logic:**
- **424B4 AI extraction** (DeepSeek analyzes offering section)
- Fall back to **18 months** (most common)

**Extracted By:** IPODetector agent (AI Agent #4), `_extract_deadline_with_ai()`

---

#### `deadline_date` (Date)
**Sources:**
1. **Calculated**: `ipo_date + relativedelta(months=deadline_months)`
2. **8-K extension filing** - Updates deadline (ExtensionMonitor agent)
3. **DEF 14A** - Extension approval

**Priority Logic:**
1. **Latest extension from 8-K/DEF 14A** (overrides original)
2. **Calculated from IPO** for initial value
3. Track extensions: `extension_count`, `original_deadline_date`

**Auto-Recalculation Triggers:**
- **Extension detected** → Update `deadline_date`, set `is_extended=True`

**Extracted By:** Calculated initially, ExtensionMonitor for updates

---

### Trust Account & Valuation Fields

#### `trust_cash` (Float, dollars)
**Sources:**
1. **10-Q/10-K financial statements** - Balance sheet "Cash and investments held in Trust Account"
2. **Calculated from trust_value**: `trust_cash = trust_value × shares_outstanding`
3. **424B4** - Initial trust amount (IPO proceeds)

**Priority Logic:**
1. **10-Q/10-K** (most recent filing) via TrustAccountProcessor (AI Agent #8)
2. **Calculated** from `trust_value` if financials fail to extract
3. **Never exceed IPO proceeds** - Validation prevents AEXA-type errors

**Auto-Recalculation Triggers:**
- **10-Q/10-K parsed** → Update trust_cash → Recalculate trust_value and premium
- **Shares redeemed** → Reduce trust_cash by redemption amount

**Validation:** `trust_cash <= (IPO proceeds + interest accrued)`

**Extracted By:** TrustAccountProcessor (AI + regex hybrid)

**Source Tracking Fields:**
- `trust_cash_source` (e.g., "10-Q")
- `trust_cash_filing_date` (date of source filing)

---

#### `trust_value` (Numeric, per-share NAV, typically $10.00-$10.20)
**Sources:**
1. **Calculated**: `trust_cash / shares_outstanding`
2. **10-Q/10-K** - Directly stated NAV per share
3. **Default**: $10.00 at IPO

**Priority Logic:**
- **Always calculate** from `trust_cash / shares_outstanding` (most accurate)
- If calculation not possible, use **10-Q/10-K stated NAV**
- Never use stale value - **recalculate** on every trust_cash or shares update

**Auto-Recalculation Triggers (via tracker):**
- `trust_cash` updated → Recalculate `trust_value`
- `shares_outstanding` updated → Recalculate `trust_value`
- `trust_value` updated → Recalculate `premium`

**Extracted By:** Tracker auto-calculation, TrustAccountProcessor

**Source Tracking Fields:**
- `trust_value_source` (e.g., "calculated")
- `trust_value_filing_date`

---

#### `premium` (Float, percentage)
**Sources:**
1. **Calculated**: `((price - trust_value) / trust_value) × 100`

**Priority Logic:**
- **Always calculate** - never store stale value
- Depends on: `price` (current market price) and `trust_value` (NAV)

**Auto-Recalculation Triggers (via tracker):**
- `price` updated → Recalculate `premium`
- `trust_value` updated → Recalculate `premium`
- `trust_cash` updated → Recalculate trust_value → Recalculate `premium`
- `shares_outstanding` updated → Recalculate trust_value → Recalculate `premium`

**Formula:**
```python
premium = ((price - trust_value) / trust_value) * 100 if trust_value else None
```

**Extracted By:** Tracker auto-calculation

---

### Pricing Fields

#### `price` / `common_price` (Float, dollars)
**Sources:**
1. **Yahoo Finance** (yfinance) - Real-time market data (primary)
2. **Alpha Vantage API** - Fallback
3. **Polygon.io API** - Secondary fallback

**Priority Logic:**
1. **Yahoo Finance** (free, reliable, 99% coverage)
2. **Alpha Vantage** if Yahoo fails
3. **Polygon.io** as last resort

**Update Frequency:**
- **Market hours** (9:30 AM - 4:00 PM ET): Every 15-60 minutes via PriceMonitorAgent
- **After hours**: Use last close price

**Extracted By:** `price_updater.py` (PriceMonitorAgent)

**Source Tracking:** `last_price_update` (timestamp of last price fetch)

---

#### `unit_price` (Float)
**Sources:**
1. **Yahoo Finance** - Try multiple ticker formats (Learning #21)
   - `{TICKER}.U`, `{TICKER}-U`, `{TICKER}U`, `{TICKER} U`, `{TICKER}/U`
2. **Alpha Vantage** - Fallback
3. **Calculated**: `price + (warrant_ratio × warrant_price)` (if unit ticker doesn't trade)

**Priority Logic:**
1. **Market data** (Yahoo/Alpha Vantage) if unit ticker trades
2. **Calculated** if unit doesn't trade separately (rare after unit split)
3. Store discovered ticker format in `unit_ticker` field

**Multi-Format Discovery:** Try all ticker suffixes, save working format

**Extracted By:** `price_updater.py` (multi-format discovery)

---

#### `warrant_price` (Float)
**Sources:**
1. **Yahoo Finance** - Multi-format ticker discovery
   - `{TICKER}W`, `{TICKER}.W`, `{TICKER}.WS`, `{TICKER}-WT`, `{TICKER}+`
2. **Alpha Vantage** - Fallback
3. **Null** if SPAC has rights instead of warrants

**Priority Logic:**
1. **Market data** if warrant trades
2. **Null** if SPAC uses rights (Learning #22: component price validation)
3. Never estimate - either found or null

**Validation (Learning #22):**
- If `unit_structure` contains "right" → warrant_price should be NULL
- If `price` and `warrant_price` exist → `unit_price` MUST exist
- If `unit_price` and `price` exist → `warrant_price` OR `rights_price` MUST exist

**Extracted By:** `price_updater.py`, `fix_component_prices.py`

---

#### `rights_price` (Float)
**Sources:**
1. **Yahoo Finance** - Multi-format ticker discovery
   - `{TICKER}R`, `{TICKER}.R`, `{TICKER} R`, `{TICKER}-R`
2. **Alpha Vantage** - Fallback

**Priority Logic:**
- Same as `warrant_price`
- Mutually exclusive with warrants (SPACs have either warrants OR rights, not both)

**Extracted By:** `price_updater.py` (added Oct 10, 2025)

---

### Deal Status & Lifecycle Fields

#### `deal_status` (Enum: SEARCHING, ANNOUNCED, COMPLETED, LIQUIDATED, DELISTED, MERGER_TERMINATED)
**Sources:**
1. **8-K filings** - Multiple item numbers determine status
   - Item 1.01 → 'ANNOUNCED' (DealDetector)
   - Item 2.01 → 'COMPLETED' (CompletionMonitor)
   - Item 1.02 → 'MERGER_TERMINATED'
2. **Form 25** - Delisting notice → 'DELISTED' or 'COMPLETED' (DelistingDetector)
3. **Form 15** - Reporting termination → 'LIQUIDATED'
4. **Lifecycle Agent** - Precedence resolution when multiple events detected

**Priority Logic:**
1. **COMPLETED** (highest precedence - deal actually closed)
2. **MERGER_TERMINATED** (deal fell through)
3. **LIQUIDATED** (winding down)
4. **DELISTED** (exchange removal)
5. **ANNOUNCED** (active deal)
6. **SEARCHING** (no deal yet)

**Precedence Example:**
- If both MERGER_TERMINATED and DELISTED events found, status = MERGER_TERMINATED (explains why delisted)

**Extracted By:** DealDetector, CompletionMonitor, DelistingDetector, SPACLifecycleDetector

---

#### `target` (String, company name)
**Sources:**
1. **8-K (Item 1.01)** - Exhibit 10.1 or 99.1 (DealDetector - AI extraction)
2. **DEFM14A** - Merger proxy (FilingProcessor)
3. **S-4** - Merger registration (S4Processor)
4. **Form 425** - Merger communications

**Priority Logic:**
1. **DEFM14A** (final target name before vote)
2. **S-4** (detailed merger registration)
3. **8-K** (initial announcement - may be incomplete name)
4. **Form 425** (supplemental)

**Update Trigger:**
- Initial value from 8-K
- Refine with S-4/DEFM14A if name changes (e.g., "TechCorp" → "TechCorp, Inc.")

**Extracted By:** DealDetector (AI Agent #9), S4Processor, FilingProcessor

---

#### `announced_date` (Date)
**Sources:**
1. **8-K filing date** (Item 1.01)
2. **8-K press release text** - "entered into definitive agreement on [date]"
3. **Form 425** filing date

**Priority Logic:**
- Use **8-K filing date** (official announcement to market)
- AI may extract different signature date from agreement text - use filing date for consistency

**Validation:** Must be >= IPO date (Investigation Agent checks this)

**Extracted By:** DealDetector

---

#### `deal_value` (String, e.g., "$500M enterprise value")
**Sources:**
1. **DEFM14A** - Most detailed valuation (FilingProcessor)
2. **S-4** - Pro forma merger details (S4Processor)
3. **8-K press release** - Initial announcement (DealDetector - AI extraction)
4. **Investor presentation** (8-K Exhibit 99.2)

**Priority Logic:**
1. **DEFM14A** (final deal terms before vote)
2. **S-4** (registration statement)
3. **Investor presentation** (may have more detail than 8-K)
4. **8-K** (initial - may be enterprise OR equity value, often unclear)

**Disambiguation:**
- AI attempts to extract whether "enterprise value" or "equity value"
- Store in notes if ambiguous

**Extracted By:** S4Processor (most comprehensive), FilingProcessor, DealDetector

**Source Tracking Fields:**
- `deal_value_source` (e.g., "DEFM14A")
- `deal_value_filing_date`
- `deal_value_updated_at`

---

#### `expected_close` / `expected_close_date` (String/Date)
**Sources:**
1. **8-K press release** - "expected to close in Q2 2026"
2. **DEFM14A** - Estimated closing timeline
3. **S-4** - Merger closing conditions

**Priority Logic:**
- Use **DEFM14A** (closest to actual closing)
- Update if extensions announced

**Extracted By:** DealDetector, FilingProcessor

---

### Shareholder Vote & Redemption Fields

#### `shareholder_vote_date` (Date)
**Sources:**
1. **DEF 14A / DEFM14A** - Proxy statement (FilingProcessor - AI extraction)
2. **8-K** - Vote results announcement
3. **DEFA14A** - Supplemental proxy materials (ProxyProcessor)

**Priority Logic:**
- **DEF 14A / DEFM14A** (official vote notice)
- **DEFA14A** if vote date changed

**Extracted By:** FilingProcessor (AI agent), ProxyProcessor

---

#### `shares_redeemed` (Integer)
**Sources:**
1. **8-K (Item 9.01)** - Exhibit with redemption results (RedemptionProcessor - AI extraction)
2. **10-Q/10-K** - "Shares subject to redemption" note changes
3. **8-K press release** - Vote results announcement

**Priority Logic:**
- **8-K redemption filing** (most accurate)
- Cross-validate with **10-Q/10-K** equity notes

**Auto-Recalculation Triggers:**
- `shares_outstanding -= shares_redeemed`
- Recalculate `trust_cash`, `trust_value`, `premium`

**Extracted By:** RedemptionProcessor (`redemption_scraper.py`)

---

#### `redemption_percentage` (Float)
**Sources:**
1. **Calculated**: `(shares_redeemed / shares_outstanding_pre_redemption) × 100`
2. **8-K press release** - May state percentage directly

**Priority Logic:**
- **Calculate** from `shares_redeemed` and `shares_outstanding`
- Validate against stated percentage in press release (if available)

**Extracted By:** RedemptionProcessor (calculated)

---

### Advanced IPO Terms (AI-Enhanced Extraction from 424B4)

#### `warrant_exercise_price` (Float, typically $11.50)
**Sources:**
1. **424B4 "Description of Securities"** - AI extraction (AI Agent #5)
2. **S-1 registration** - Preliminary terms
3. **Default**: $11.50 (most common)

**Priority Logic:**
- **424B4 AI extraction** (final terms)
- **S-1** if 424B4 fails
- Default only if all extraction fails

**Pre-Validation:** Check `unit_structure` for "warrant" vs "right" before extraction (Learning #22)

**Extracted By:** `extract_424b4_enhanced()` (AI Agent #5 - Warrant Terms)

---

#### `warrant_redemption_price` (Float, typically $18.00)
**Sources:**
1. **424B4** - AI extraction from warrant description
2. **S-1** - Preliminary

**Priority Logic:** Same as `warrant_exercise_price`

**Extracted By:** AI Agent #5

---

#### `warrant_redemption_days` (Text, e.g., "20 trading days within 30-day period")
**Sources:**
1. **424B4** - AI extraction

**Priority Logic:** 424B4 only (too complex for defaults)

**Data Type:** TEXT (not INTEGER) - contains complex redemption windows

**Extracted By:** AI Agent #5

**Schema Fix:** Changed from INTEGER to TEXT (Oct 8, 2025) to handle complex redemption terms

---

#### `warrant_expiration_years` (Integer, typically 5)
**Sources:**
1. **424B4** - AI extraction
2. **Default**: 5 years

**Priority Logic:**
- **424B4 AI**
- Default to 5

**Extracted By:** AI Agent #5

---

#### `overallotment_units` / `overallotment_percentage` / `overallotment_days` (Float/Integer)
**Sources:**
1. **424B4 cover page + "The Offering" section** - AI extraction (AI Agent #3)
2. **8-K** - Overallotment exercise announcement

**Priority Logic:**
- **424B4** for initial terms (15% / 45 days typical)
- **8-K** to update `overallotment_exercised=True`

**Calculated:** `shares_outstanding_with_overallotment = shares_outstanding_base + overallotment_units` (if exercised)

**Extracted By:** `extract_424b4_enhanced()` (AI Agent #3 - Overallotment)

---

#### `extension_available` / `extension_months_available` / `extension_requires_loi` (Boolean/Integer)
**Sources:**
1. **424B4 "The Offering" section** - AI extraction (AI Agent #4)

**Priority Logic:** 424B4 only (charter-defined terms)

**Example:**
```json
{
  "extension_available": true,
  "extension_months_available": 6,
  "extension_requires_loi": true,
  "extension_requires_vote": false,
  "extension_automatic": false,
  "max_deadline_with_extensions": "2027-12-26"
}
```

**Extracted By:** `extract_424b4_enhanced()` (AI Agent #4 - Extension Terms)

---

#### `management_team` / `key_executives` / `management_summary` (Text)
**Sources:**
1. **424B4 "Management" section** - AI extraction (AI Agent #6)
2. **DEF 14A** - May have updated management

**Priority Logic:**
- **424B4** for initial team
- **DEF 14A** if management changes

**Format:**
- `key_executives`: "John Smith, Jane Doe, Bob Johnson" (comma-separated)
- `management_summary`: "2-3 sentence team overview"
- `management_team`: "John Smith - Former CEO of...|Jane Doe - 20 years investment banking..." (pipe-separated bios)

**Extracted By:** AI Agent #6 (Management Team)

---

#### `founder_shares_cost` / `private_placement_cost` / `sponsor_total_at_risk` (Float)
**Sources:**
1. **424B4 "The Offering" section** - AI extraction (AI Agent #7)
2. **S-1** - Preliminary

**Priority Logic:** 424B4 > S-1

**Calculated:**
- `sponsor_total_at_risk = founder_shares_cost + private_placement_cost`
- `sponsor_at_risk_percentage = (sponsor_total_at_risk / ipo_proceeds) × 100`

**Extracted By:** AI Agent #7 (Sponsor Economics)

---

### Deal Structure Fields (S-4 / DEFM14A Extraction)

#### `pipe_size` / `pipe_price` (Float)
**Sources:**
1. **S-4** - Most detailed PIPE terms (S4Processor - AI extraction)
2. **DEFM14A** - May summarize PIPE
3. **8-K** - Initial PIPE announcement

**Priority Logic:**
1. **S-4** (registration statement)
2. **DEFM14A** if S-4 fails
3. **8-K** as last resort

**Extracted By:** S4Processor (`s4_scraper.py`)

---

#### `min_cash` / `min_cash_percentage` (Float)
**Sources:**
1. **S-4** - Merger conditions (AI extraction)
2. **DEFM14A** - Vote requirements
3. **8-K** - May state minimum cash condition

**Priority Logic:** S-4 > DEFM14A > 8-K

**Calculated:** `min_cash_percentage = (min_cash / deal_value) × 100`

**Extracted By:** S4Processor

---

#### `earnout_shares` / `has_earnout` (Float/Boolean)
**Sources:**
1. **S-4** - Earnout structure (AI extraction)
2. **DEFM14A** - May summarize earnout

**Priority Logic:** S-4 > DEFM14A

**Extracted By:** S4Processor

---

### Financial Projections (Investor Presentation)

#### `projected_revenue_y1/y2/y3` / `projected_ebitda_y1/y2/y3` (Float)
**Sources:**
1. **Investor presentation** (8-K Exhibit 99.2) - AI extraction
2. **DEFM14A** - May include projections
3. **S-4** - Pro forma financials

**Priority Logic:**
1. **Investor presentation** (most detailed projections)
2. **DEFM14A**
3. **S-4**

**Extracted By:** Investor presentation scraper (future implementation)

**Source Tracking:**
- `projections_source` (e.g., "8-K Exhibit 99.2")
- `projections_filing_date`

---

#### `ev_revenue_multiple` / `ev_ebitda_multiple` (Float)
**Sources:**
1. **Calculated**:
   - `ev_revenue_multiple = deal_value / projected_revenue_y1`
   - `ev_ebitda_multiple = deal_value / projected_ebitda_y1`
2. **Investor presentation** - May state multiples directly

**Priority Logic:**
- **Calculate** from projections
- Validate against stated multiples

**Extracted By:** Calculated post-extraction

---

### Lifecycle Event Dates (SPACLifecycleDetector)

#### `completion_date` / `new_ticker` (Date/String)
**Sources:**
1. **8-K (Item 2.01)** - Deal closure announcement
2. **Form 25** - Delisting notice (may indicate completion or liquidation)

**Priority Logic:**
- **8-K Item 2.01** filing date = completion date
- Extract new ticker from 8-K text: "formerly known as [OLD], now [NEW]"

**Extracted By:** CompletionMonitor (`deal_closing_detector.py`), SPACLifecycleDetector

---

#### `merger_termination_date` (Date)
**Sources:**
1. **8-K (Item 1.02)** - Termination of material agreement
2. **Press release** - Mutual termination announcement

**Priority Logic:** 8-K filing date

**Extracted By:** SPACLifecycleDetector

---

#### `liquidation_date` / `delisting_date` (Date)
**Sources:**
1. **Form 15** - Reporting termination
2. **Form 25** - Delisting notice
3. **8-K (Item 1.01)** - Liquidation announcement

**Priority Logic:**
- **Form 15** filing date = liquidation date
- **Form 25** filing date = delisting date

**Extracted By:** SPACLifecycleDetector, DelistingDetector

---

## Multi-Source Reconciliation Strategy

### When Sources Disagree

**Example:** 8-K says "$500M enterprise value", S-4 says "$480M equity value"

**Resolution:**
1. **Identify which metric** (enterprise vs equity value)
2. **Prefer S-4** (more detailed, later filing)
3. **Store both** in notes if material difference
4. **AI validates** plausibility (enterprise should be > equity)

---

### Validation Rules

#### Trust Account Validation (AEXA Lesson)
```python
if trust_cash > (ipo_proceeds * 1.1):  # Allow 10% interest accrual
    flag_error("Trust cash exceeds IPO proceeds - likely extraction error")
    research_issue("check_latest_10q_for_trust_cash")
```

#### Temporal Validation (OBA Lesson)
```python
if announced_date < (ipo_date - timedelta(days=730)):  # 2 years
    flag_anomaly("Deal announced >2 years before IPO")
    trigger_investigation_agent()
```

#### Component Price Validation (Learning #22)
```python
if price and warrant_price and not unit_price:
    flag_error("Missing unit price (have common + warrant)")
    run_multi_format_ticker_discovery()
```

---

## Source Tracking Best Practices

### Why Track Sources?

1. **Debugging**: When data looks wrong, know where it came from
2. **Precedence**: If multiple sources exist, know which was used
3. **Staleness**: Know if data needs refreshing (e.g., 10-Q > 3 months old)
4. **Investigation**: Help Investigation Agent diagnose data quality issues

### Tracked Source Fields

For critical data points, track:
- `{field}_source` (e.g., "10-Q", "8-K", "calculated")
- `{field}_filing_date` (date of source document)
- `{field}_updated_at` (timestamp of extraction)

**Examples:**
- `trust_cash_source = "10-Q"`
- `trust_cash_filing_date = "2025-08-10"`
- `deal_value_source = "DEFM14A"`
- `shares_source = "8-K redemption"`
- `shares_filing_date = "2025-09-15"`

---

## Auto-Recalculation Dependencies

### Tracker System (`update_spac_trackers.py`)

When certain fields update, dependent fields auto-recalculate:

```
trust_cash updated
    ↓
  Recalculate trust_value = trust_cash / shares_outstanding
    ↓
  Recalculate premium = ((price - trust_value) / trust_value) × 100
```

```
shares_outstanding updated
    ↓
  Recalculate trust_value
    ↓
  Recalculate premium
```

```
price updated
    ↓
  Recalculate premium
```

**Benefit:** No stale calculated values, always mathematically consistent

**Documentation:** See `AUTO_RECALCULATE_PREMIUM.md`

---

## Data Quality Checks

### Weekly Validation Jobs

1. **CIK Validator** (`validate_cik_mappings.py`)
   - Verify CIK SIC code = 6770
   - Verify filing dates align with IPO
   - Auto-correct if wrong CIK detected

2. **Component Price Validator** (`validate_component_prices.py`)
   - Check Learning #22 rules
   - Flag missing component prices
   - Run multi-format ticker discovery

3. **Trust Account Validator** (`verify_trust_data.py`)
   - Check trust_cash <= IPO proceeds × 1.1
   - Verify trust_value calculations
   - Flag anomalies for research

---

## Filing Type → Data Point Mapping Summary

| Filing Type | Primary Data Points Extracted |
|-------------|-------------------------------|
| **424B4** | ipo_date, ipo_proceeds, unit_structure, deadline_months, shares_outstanding, warrant terms, overallotment, extension terms, management, sponsor economics |
| **8-K (Item 1.01)** | target, announced_date, deal_value (preliminary) |
| **8-K (Item 2.01)** | completion_date, new_ticker |
| **8-K (Item 5.03)** | deadline_date (extension), extension_count |
| **8-K (Item 9.01)** | shares_redeemed, redemption_percentage |
| **S-4** | deal_value (detailed), pipe_size, min_cash, earnout_shares, pro forma financials |
| **DEFM14A** | shareholder_vote_date, deal terms (final), management recommendations |
| **10-Q/10-K** | trust_cash, shares_outstanding (current), redemptions |
| **Form 25** | delisting_date, deal_status (DELISTED or COMPLETED) |
| **Form 15** | liquidation_date, deal_status (LIQUIDATED) |

---

## Agent → Data Point Responsibility

| Agent | Fields Updated |
|-------|----------------|
| **IPODetector** | ipo_date, ipo_proceeds, unit_structure, deadline_months, shares_outstanding, trust_value, warrant_exercise_price, warrant_expiration_years |
| **DealDetector** | deal_status='ANNOUNCED', target, announced_date, deal_value (initial) |
| **TrustAccountProcessor** | trust_cash, shares_outstanding, trust_value (triggers premium recalc) |
| **ExtensionMonitor** | deadline_date, extension_count, is_extended=True |
| **RedemptionProcessor** | shares_redeemed, redemption_percentage, shares_outstanding (triggers trust_value/premium recalc) |
| **S4Processor** | deal_value (final), pipe_size, min_cash, earnout_shares, has_earnout, has_pipe |
| **FilingProcessor** | shareholder_vote_date, vote_purpose |
| **CompletionMonitor** | deal_status='COMPLETED', completion_date, new_ticker |
| **DelistingDetector** | deal_status='DELISTED', delisting_date |
| **SPACLifecycleDetector** | deal_status (precedence resolution), completion_date, merger_termination_date, liquidation_date |
| **PriceMonitorAgent** | price, unit_price, warrant_price, rights_price (triggers premium recalc) |

---

## Key Learnings Applied

### Learning #21: Multi-Format Ticker Discovery
When fetching component prices, try multiple ticker formats:
- **Units:** `TICKER.U`, `TICKER-U`, `TICKER U`, `TICKERU`
- **Warrants:** `TICKERW`, `TICKER.W`, `TICKER.WS`, `TICKER-WT`, `TICKER+`
- **Rights:** `TICKERR`, `TICKER.R`, `TICKER R`

**Result:** 50% increase in successful component price discovery

---

### Learning #22: Component Price Validation
**Rules:**
- If common + warrant prices exist → unit price MUST exist
- If unit + common prices exist → warrant OR rights MUST exist
- Pre-validate unit_structure before warrant extraction (prevents hallucination)

**Implementation:** `validate_component_prices.py`, `fix_component_prices.py`

---

### Learning #23: IPO Detection (Dual Modes)
**Event-Driven:** SEC monitor polls every 15 min for 424B4
**Batch Backup:** Daily cron at 9 AM checks for missed IPO closings

**Result:** Pre-IPO SPACs automatically graduate to main pipeline when IPO closes

---

## Future Enhancements

1. **Confidence Scoring**: Track extraction confidence for each field
2. **Multi-Source Validation**: Cross-validate same field from different sources
3. **Automated Discrepancy Resolution**: AI decides which source to trust when they conflict
4. **Data Freshness Tracking**: Flag stale data (e.g., trust_cash > 90 days old)
5. **Historical Versioning**: Track all updates to critical fields (audit trail)

---

**Last Updated:** October 10, 2025

