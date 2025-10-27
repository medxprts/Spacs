# Recommended Cron Schedule - Optimized for Event-Driven System

## Philosophy

**The real-time filing monitor handles 80% of database updates automatically.** The periodic orchestrator runs are just a **safety net** for:
1. Non-filing data (prices, Reddit mentions)
2. Data quality validation
3. Backup check for any missed filings (rare)

---

## Cron Schedule

```bash
crontab -e

# Add these lines:

# ============================================================================
# PRIMARY SYSTEM: Real-time filing monitor (runs continuously, not via cron)
# Started manually: screen -S filing-monitor && python3 sec_filing_monitor.py
# Or via systemd: sudo systemctl start sec-filing-monitor
# ============================================================================

# ============================================================================
# PERIODIC UPDATES (Safety Net)
# ============================================================================

# Orchestrator - Once daily at 9 AM (light run, mostly price updates + validation)
0 9 * * * /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/agent_orchestrator.py >> ~/spac-research/logs/orchestrator.log 2>&1

# Issue Resolution Agent - Every hour (analyzes user issues, sends Telegram proposals)
0 * * * * /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/agents/issue_resolution_agent.py >> ~/spac-research/logs/issue_agent.log 2>&1

# ============================================================================
# OPTIONAL: Additional safety checks
# ============================================================================

# Price updates - Every 4 hours during market hours (9 AM - 5 PM)
# (Orchestrator AI will decide if needed, but can force it here)
0 9,13,17 * * 1-5 /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/price_updater.py >> ~/spac-research/logs/price.log 2>&1

# Data validator - Daily at 10 PM (after market close, clean data)
0 22 * * * /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/data_validator_agent.py >> ~/spac-research/logs/validator.log 2>&1
```

---

## What Each Job Does

### 1. **Orchestrator (Daily at 9 AM)**

**Purpose:** Safety net + non-filing data

**What AI typically decides to run:**
- **Price Monitor** (if >6 hours since last update) - HIGH priority
- **Data Validator** (daily quality check) - MEDIUM priority
- **Deal Hunter** (ONLY if >48 hours since last run) - BACKUP ONLY
- **Deadline Extension** (ONLY if expired SPACs detected) - BACKUP ONLY

**Expected output:**
```
[ORCHESTRATOR] Decision: Run Price Monitor (last updated 8h ago) and Data Validator (daily check)
[ORCHESTRATOR] Scheduled 2 tasks

[PriceMonitor] Updating prices for 155 SPACs...
[PriceMonitor] ✓ Updated 155 prices

[DataValidator] Validating 155 SPACs...
[DataValidator] ✓ No anomalies detected
```

**Frequency:** Daily (9 AM)

---

### 2. **Issue Resolution Agent (Every Hour)**

**Purpose:** Analyze user-reported issues, suggest fixes via Telegram

**What it does:**
1. Queries `user_issues` table for open issues
2. AI analyzes each issue (diagnoses bugs, suggests fixes)
3. Sends Telegram notification with proposed solution
4. Marks issue as 'in_progress' (awaiting human approval)

**Expected output:**
```
[ISSUE AGENT] Found 2 open issues

🔍 Analyzing Issue #1: Premium calculation negative for AEXA
   ✓ Analysis complete
   Priority: high
   Estimated effort: 15 minutes
   ✅ Telegram notification sent

🔍 Analyzing Issue #2: Price not updating for MLAC
   ✓ Analysis complete
   Priority: medium
   Estimated effort: 30 minutes
   ✅ Telegram notification sent
```

**Frequency:** Every hour

---

### 3. **Price Updater (3x/day - OPTIONAL)**

**Purpose:** Force price updates during market hours

**What it does:**
- Fetches prices from Yahoo Finance for all 155 SPACs
- Updates: `price`, `warrant_price`, `unit_price`
- Auto-recalculates `premium`

**Note:** The orchestrator's Price Monitor should handle this, but this provides guaranteed updates.

**Expected output:**
```
[PRICE] Updating 155 SPAC prices...
[PRICE] Source: Yahoo Finance
[PRICE] ✓ Updated 155/155 SPACs
[PRICE] Avg premium: 5.2%
```

**Frequency:** 9 AM, 1 PM, 5 PM (market hours)

---

### 4. **Data Validator (Daily at 10 PM - OPTIONAL)**

**Purpose:** Daily quality check after market close

**What it does:**
1. Validates all 155 SPACs for data quality issues
2. Checks: premium calculation, trust value logic, deadline consistency
3. Triggers Investigation Agent for anomalies
4. Auto-fixes simple issues

**Expected output:**
```
[VALIDATOR] Validating 155 SPACs...
[VALIDATOR] ✓ 153 SPACs passed all checks
[VALIDATOR] ⚠️  2 anomalies detected

[INVESTIGATOR] Investigating AEXA...
[INVESTIGATOR] ✓ Corrected trust_cash from $350M to $340M (source: 10-Q 2025-09-30)

[VALIDATOR] Summary: 2 issues found, 2 auto-fixed
```

**Frequency:** Daily (10 PM)

---

## What NOT to Schedule

**Don't schedule these via cron - they're handled by the real-time filing monitor:**

- ❌ Deal detection (filing monitor catches 8-Ks in real-time)
- ❌ Extension monitoring (filing monitor catches 8-K Item 5.03)
- ❌ Redemption processing (filing monitor catches 8-K Item 9.01)
- ❌ Trust account updates (filing monitor catches 10-Q/10-K)
- ❌ Vote tracking (filing monitor catches DEFM14A)
- ❌ Deal closings (filing monitor catches Form 25, 8-K Item 2.01)

**The filing monitor handles all of these within 15-20 minutes of SEC publication!**

---

## Monitoring

### Check if Filing Monitor is Running
```bash
# Check process
ps aux | grep sec_filing_monitor.py

# View recent activity
tail -f ~/spac-research/logs/filing_monitor.log

# Restart if needed
screen -r filing-monitor  # Or: sudo systemctl restart sec-filing-monitor
```

### Check Cron Jobs are Running
```bash
# View cron logs
grep CRON /var/log/syslog | tail -20

# View orchestrator output
tail -f ~/spac-research/logs/orchestrator.log

# View issue agent output
tail -f ~/spac-research/logs/issue_agent.log
```

### Verify Database Updates
```bash
# Check recent price updates
psql -U spac_user -d spac_db -c "
SELECT ticker, price, premium, updated_at
FROM spacs
ORDER BY updated_at DESC
LIMIT 10;
"

# Check when last filing was processed
tail -f ~/spac-research/logs/filing_monitor.log | grep "Processing"
```

---

## Expected System Behavior

### Normal Day (No New Filings)

**Filing Monitor (24/7):**
- Polls SEC every 15 minutes
- No new filings detected
- No database updates

**Orchestrator (9 AM):**
- AI decision: "Run Price Monitor (8h since last update) + Data Validator (daily check)"
- Updates 155 prices
- Validates data quality
- **Result:** 155 SPACs have fresh prices, data validated

**Issue Agent (Every Hour):**
- Checks for new user issues
- If none: exits immediately
- If found: analyzes and sends Telegram

---

### Active Day (New Deal Announced)

**10:30 AM - SEC publishes 8-K for AEXA**

**Filing Monitor:**
- 10:45 AM - Detects 8-K (Item 1.01)
- AI classifies as deal announcement
- Routes to DealDetector
- Fetches main filing + Exhibit 99.1
- AI analyzes content for relevance
- DealDetector processes filing
- Database updated:
  - `deal_status = 'ANNOUNCED'`
  - `target = 'Target Technologies Inc'`
  - `deal_value = '$850 million'`
- Telegram alert sent: 🚨 AEXA announced deal!

**Total latency:** 15 minutes from SEC → Database → Alert

**Orchestrator (Next Day 9 AM):**
- AI decision: "Price Monitor only (deal already captured by filing monitor)"
- Updates prices
- **Does NOT re-process deal** (already handled in real-time!)

---

## Minimal Cron Schedule (Recommended)

If you trust the filing monitor (which you should!), you can run an ultra-minimal schedule:

```bash
# Orchestrator - Daily at 9 AM (prices + validation)
0 9 * * * /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/agent_orchestrator.py >> ~/spac-research/logs/orchestrator.log 2>&1

# Issue agent - Every hour
0 * * * * /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/agents/issue_resolution_agent.py >> ~/spac-research/logs/issue_agent.log 2>&1
```

**That's it!** The filing monitor handles everything else in real-time.

---

## Summary

**Event-Driven (Real-Time) - Filing Monitor:**
- Handles: Deals, extensions, redemptions, trust updates, votes, closings
- Frequency: Continuous (15 min polling)
- Latency: 15-20 minutes from SEC publication
- **This is the PRIMARY system** ⭐

**Scheduled (Periodic) - Orchestrator:**
- Handles: Prices, data validation, missed filing backup
- Frequency: Daily at 9 AM
- **This is the SAFETY NET** 🛡️

**Result:** Minimal cron jobs, maximum automation! 🚀
