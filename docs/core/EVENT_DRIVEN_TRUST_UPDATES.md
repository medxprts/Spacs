# Event-Driven Trust Account Updates

## Overview

Trust account data (`trust_cash`, `trust_value`, `premium`) is **automatically updated** when SEC filings are detected, ensuring data stays current without manual intervention.

**Last Updated:** October 9, 2025
**Status:** ✅ Fully Integrated

---

## Architecture: Event-Driven Pipeline

```
SEC EDGAR → Filing Monitor → Classification → Agent → Tracker → Database
                                                               ↓
                                                        Auto-recalculate:
                                                        - trust_value
                                                        - premium
```

---

## 1. SEC Filing Detection

**Tool:** `sec_filing_monitor.py`
**Mode:** Continuous polling (every 15 minutes)
**Coverage:** All 155 tracked SPACs

### Filing Types Monitored for Trust Data:
- ✅ **10-Q** (Quarterly Report) - Contains quarterly trust balance
- ✅ **10-K** (Annual Report) - Contains annual trust balance
- ✅ **424B4** (IPO Prospectus) - Fallback for new SPACs without quarterly reports
- ✅ **8-K** (Current Report) - Redemptions, extensions, liquidations

### How It Works:
```python
# sec_filing_monitor.py polls SEC RSS feeds
monitor = SECFilingMonitor(poll_interval_seconds=900)  # 15 min
monitor.monitor_continuous()

# For each new filing detected:
classification = monitor.classify_filing(filing)

# 10-Q/10-K filings route to TrustAccountProcessor
if filing_type in ['10-Q', '10-K']:
    return {
        'priority': 'MEDIUM',
        'agents_needed': ['TrustAccountProcessor'],
        'reason': 'Trust account data update'
    }
```

---

## 2. Trust Data Extraction

**Agent:** `quarterly_report_extractor.py` (alias: TrustAccountProcessor)
**Extracts:**
- Trust cash balance (from financial statements)
- Shares redeemed (from stockholders' equity notes)
- Extensions (from subsequent events notes)
- Deal status changes (liquidation/completion indicators)

### Extraction Strategy:
1. **Get Filing URL** from SEC RSS feed
2. **Fetch Document** (HTML version of 10-Q/10-K)
3. **Parse Trust Section** using regex + AI fallback
4. **Extract Dollar Amount** from trust account disclosure
5. **Extract Share Count** from equity disclosures
6. **Route to Tracker** for database update

---

## 3. Trust Account Tracker (Auto-Recalculation)

**Tool:** `utils/trust_account_tracker.py`
**Purpose:** Ensures dependent fields update automatically

### Automatic Recalculations:

#### When Trust Cash Updates:
```python
update_trust_cash(
    db_session=db,
    ticker='AEXA',
    new_value=338_100_000,  # $338.1M from 10-Q
    source='10-Q',
    filing_date='2025-09-30',
    quarter='Q3 2025'
)

# Automatically recalculates:
# 1. trust_value = trust_cash / shares_outstanding
# 2. premium = ((price - trust_value) / trust_value) * 100
```

#### When Shares Outstanding Updates (Redemptions):
```python
update_shares_outstanding(
    db_session=db,
    ticker='AEXA',
    new_value=34_500_000,  # 34.5M shares (after redemptions)
    source='10-Q',
    filing_date='2025-09-30',
    reason='Redemptions: 5M shares redeemed'
)

# Automatically recalculates:
# 1. trust_value = trust_cash / shares_outstanding (↑ if redemptions)
# 2. premium = ((price - trust_value) / trust_value) * 100
```

### Date Precedence Logic:
- **Newer filings override older filings**
- Example: If 10-Q (Sep 30) is newer than last update (Jun 30), use 10-Q data
- Prevents data regression (old filings don't overwrite new data)

---

## 4. Fallback Strategy: 424B4 for New SPACs

**Problem:** New SPACs (<180 days old) may not have filed their first 10-Q yet
**Solution:** Use IPO prospectus (424B4) as fallback

### When Fallback Triggers:
1. No 10-Q or 10-K found
2. SPAC < 180 days since IPO
3. Trust data extraction from 10-Q failed

### Calculation:
```python
# From 424B4 IPO prospectus:
ipo_proceeds = $345,000,000  # Gross proceeds (including overallotment)
trust_cash = ipo_proceeds * 0.98  # Deduct 2% upfront underwriting fee
trust_cash = $338,100,000

shares_outstanding = 34,500,000  # Base + overallotment

trust_value = $338.1M / 34.5M = $9.80/share
```

### Automatic Upgrade:
When the first 10-Q is filed, the fallback data is automatically replaced by actual filing data (date precedence ensures this).

---

## 5. Data Quality Validation

**Agent:** `data_validator_agent.py`
**Runs:** After each trust update + scheduled validation

### New Validation Rule (AEXA Lesson):
```python
def validate_trust_cash_vs_ipo(spac):
    """
    Ensure trust_cash does not exceed IPO proceeds

    AEXA Example:
    - BEFORE: trust_cash=$456.7M, ipo_proceeds=$345M ❌
    - AFTER:  trust_cash=$338.1M, ipo_proceeds=$345M ✅
    """
    if spac.trust_cash > ipo_proceeds * 1.02:  # Allow 2% tolerance
        return {
            'severity': 'CRITICAL',
            'message': 'Trust cash exceeds IPO - circular calculation error',
            'auto_fix': 'recalculate_from_424b4'
        }
```

### Auto-Fix Flow:
1. **Validator detects** trust_cash > ipo_proceeds
2. **Flags as LOW confidence** (needs SEC filing verification)
3. **Orchestrator dispatches** research agent
4. **Investigation Agent** re-scrapes 424B4 filing
5. **Applies fix** using correct filing data
6. **Documents lesson** in validation log

---

## 6. Complete Event Flow Example

### Scenario: AEXA files Q3 2025 10-Q on November 14, 2025

```
15:30 - SEC publishes 10-Q to EDGAR
15:35 - sec_filing_monitor.py detects new filing (next 15-min poll)
15:35 - Classifies as "10-Q" → routes to TrustAccountProcessor
15:36 - quarterly_report_extractor.py downloads 10-Q
15:36 - Extracts: trust_cash=$340M, shares=34.5M (no redemptions)
15:36 - Calls update_trust_cash(db, 'AEXA', 340_000_000, '10-Q', '2025-09-30', 'Q3 2025')
15:36 - Tracker updates database:
        - trust_cash: $338.1M → $340M
        - trust_value: $9.80 → $9.86 (auto-calculated)
        - premium: 18.27% → 17.61% (auto-recalculated)
15:36 - Validation runs (trust_cash=$340M < ipo_proceeds=$345M ✅)
15:37 - Telegram alert sent: "AEXA trust updated from 10-Q"
```

**Total time:** ~7 minutes from SEC publication to database update

---

## 7. Cron Schedule Summary

### Continuous Monitoring (Always Running):
- `sec_filing_monitor.py` - Polls every 15 minutes

### Daily Scheduled Tasks (9 AM):
- `deal_monitor_enhanced.py` - Scans 8-Ks for new deals
- `redemption_scraper.py` - Scrapes redemption results from 8-Ks
- `deadline_extension_monitor.py` - Checks for deadline extensions

### Weekly Scheduled Tasks (Sunday 9 AM):
- `deal_monitor_complete.py --mode verify` - Re-verifies all deals

---

## 8. Key Files Reference

| File | Purpose | Triggers |
|------|---------|----------|
| `sec_filing_monitor.py` | Detects new SEC filings via RSS | Every 15 min |
| `agents/quarterly_report_extractor.py` | Extracts trust data from 10-Q/10-K | On 10-Q/10-K detection |
| `utils/trust_account_tracker.py` | Updates DB with auto-recalculation | On trust data change |
| `data_validator_agent.py` | Validates trust data quality | After updates + scheduled |
| `investigation_agent.py` | Investigates anomalies | On validation failure |
| `sec_data_scraper.py` | Manual scraper (424B4 fallback) | Manual/scheduled |

---

## 9. Monitoring & Alerts

### Telegram Notifications Sent For:
- ✅ New 10-Q/10-K detected
- ✅ Trust data updated successfully
- ✅ Data quality issues detected (trust_cash > IPO)
- ✅ Investigation completed (auto-fix applied)

### Logs:
- `/home/ubuntu/spac-research/logs/filing_monitor.log` - Filing detection
- `/home/ubuntu/spac-research/logs/trust_updates.log` - Trust updates
- `/home/ubuntu/spac-research/logs/validation.log` - Data quality checks
- `/home/ubuntu/spac-research/logs/investigation_*.json` - Investigation reports

---

## 10. Testing the Flow

### Manual Test:
```bash
# 1. Trigger single poll
cd /home/ubuntu/spac-research
python3 sec_filing_monitor.py  # Runs one poll cycle

# 2. Check for AEXA's latest 10-Q
python3 agents/quarterly_report_extractor.py --ticker AEXA

# 3. Verify trust data was updated
psql -U spac_user -d spac_db -c "
    SELECT ticker, trust_cash, trust_value, premium, last_updated
    FROM spacs
    WHERE ticker='AEXA';
"

# 4. Run validation to ensure quality
python3 data_validator_agent.py --ticker AEXA
```

### Start Continuous Monitoring:
```bash
# Option 1: Run in screen session
screen -S filing-monitor
python3 sec_filing_monitor.py
# Ctrl+A, D to detach

# Option 2: Run as systemd service (recommended)
sudo systemctl start sec-filing-monitor
sudo systemctl status sec-filing-monitor
```

---

## 11. Data Quality Safeguards

### From AEXA Lesson (Oct 9, 2025):

**Problem:** AEXA had trust_cash=$456.7M exceeding IPO proceeds=$345M
**Cause:** Circular calculation using bad trust_value
**Fix:** Re-scraped 424B4 for actual IPO structure

**Prevention Measures Implemented:**

1. ✅ **Validation Rule:** Trust cash cannot exceed 102% of IPO proceeds
2. ✅ **424B4 Fallback:** New SPACs use IPO prospectus data
3. ✅ **Auto-Recalculation:** Premium updates when trust_value changes
4. ✅ **Date Precedence:** Newer filings always override older data
5. ✅ **Source Tracking:** All updates log source filing and date
6. ✅ **Investigation Agent:** Automatically investigates anomalies
7. ✅ **Self-Learning:** Validation log teaches agents to prevent recurrence

---

## Summary

**Your trust account data is now:**
- ✅ **Event-driven** - Updates automatically when 10-Q/10-K filed
- ✅ **Self-healing** - Validates and auto-fixes data quality issues
- ✅ **Real-time** - Detects filings within 15 minutes of SEC publication
- ✅ **Accurate** - Uses SEC filings as source of truth (not calculations)
- ✅ **Resilient** - Falls back to 424B4 for new SPACs without quarterly reports
- ✅ **Smart** - Prevents circular calculation errors (AEXA lesson)

**No manual intervention required!** 🚀
