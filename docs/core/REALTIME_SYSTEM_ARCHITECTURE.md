# Real-Time System Architecture - Complete Overview

## Philosophy: Everything Real-Time

**Goal:** Database should reflect reality **within minutes**, not hours or days.

**Three Real-Time Monitors Running 24/7:**

1. **SEC Filing Monitor** (every 15 min) - Filing-based data
2. **Price Monitor** (every 5 min) - Market data
3. **Reddit Monitor** (every 15 min) - Social sentiment data

**Orchestrator:** Safety net only (once daily)

---

## Real-Time Monitor #1: SEC Filing Monitor

**File:** `sec_filing_monitor.py`

**Updates:** ~80% of database fields

**Frequency:** Every 15 minutes (SEC RSS polling)

**Latency:** 15-20 minutes from SEC publication to database

**What it monitors:**
- Deal announcements (8-K Item 1.01)
- Extensions (8-K Item 5.03)
- Redemptions (8-K Item 9.01)
- Trust account updates (10-Q, 10-K)
- Vote dates (DEFM14A, PREM14A)
- Deal closings (8-K Item 2.01, Form 25)
- S-4 merger registrations
- Proxy materials (DEFA14A)

**How to start:**
```bash
# Option 1: Screen session (always running)
screen -S filing-monitor
cd /home/ubuntu/spac-research
python3 sec_filing_monitor.py
# Ctrl+A, D to detach

# Option 2: Systemd service (production)
sudo systemctl start sec-filing-monitor
sudo systemctl enable sec-filing-monitor
```

**Database fields updated:**
- `deal_status`, `target`, `announced_date`, `deal_value`
- `trust_cash`, `shares_outstanding`, `trust_value`, `premium`
- `deadline_date`, `extension_count`, `is_extended`
- `shareholder_vote_date`, `record_date`
- `completion_date`, `delisting_date`, `new_ticker`

**Telegram alerts:**
- 🚨 New deal announcements
- 📅 Deadline extensions
- ✅ Deal completions
- ⚠️ Delisting notifications

---

## Real-Time Monitor #2: Price Monitor

**File:** `realtime_price_monitor.py`

**Updates:** Price data (non-filing)

**Frequency:**
- **Market hours (9:30 AM - 4:00 PM ET):** Every 30 seconds
- **Off-hours:** Every 30 minutes

**Latency:** 30 seconds from price change to database

**Why 30 seconds?**
- Premiums change throughout the day
- Users expect live data
- Arbitrage opportunities are time-sensitive
- Yahoo Finance has no strict rate limits
- Near-real-time pricing for active trading

**What it monitors:**
- Common stock prices (`price`)
- Warrant prices (`warrant_price`)
- Unit prices (`unit_price`)
- Auto-recalculates `premium`

**How to start:**
```bash
# Screen session (always running)
screen -S price-monitor
cd /home/ubuntu/spac-research
python3 realtime_price_monitor.py
# Ctrl+A, D to detach
```

**Database fields updated:**
- `price`
- `warrant_price`
- `unit_price`
- `premium` (auto-calculated)

**Console output:**
```
🔴 MARKET OPEN - Active updating
[09:35:00] Updating prices for all SPACs...
   ✓ Updated 155/155 SPACs
   💤 Next update: 09:35:30 (30 sec)

🔴 MARKET OPEN - Active updating
[09:35:30] Updating prices for all SPACs...
   ✓ Updated 155/155 SPACs
   💤 Next update: 09:36:00 (30 sec)
```

---

## Real-Time Monitor #3: Reddit Monitor

**File:** `realtime_reddit_monitor.py`

**Updates:** Social sentiment data

**Frequency:** Every 15 minutes

**Latency:** 15 minutes from Reddit post to database

**Why continuous monitoring?**
- Detect "leak" speculation before announcements
- Track sentiment shifts in real-time
- Catch early deal rumors
- Alert on unusual mention spikes

**What it monitors:**
- r/SPACs posts and comments
- Mentions of each SPAC ticker
- Sentiment (bullish vs bearish)
- Speculation keywords ("leak", "rumor", "sources say")

**How to start:**
```bash
# Screen session (always running)
screen -S reddit-monitor
cd /home/ubuntu/spac-research
python3 realtime_reddit_monitor.py
# Ctrl+A, D to detach
```

**Database fields updated:**
- `reddit_mentions_7d`
- `reddit_bullish_ratio`
- `reddit_speculation_score`
- `reddit_last_updated`

**Unusual activity detection:**
```
📊 AEXA: 25 mentions, 80% bullish
   🚨 HIGH SPECULATION SCORE: 85%
   → Potential leak or early deal rumor
```

**Telegram alerts (TODO):**
- Unusual mention spikes (>20 mentions in 7 days)
- High speculation score (>70%)
- Sentiment shift (bullish ratio change >30%)

---

## Orchestrator (Safety Net)

**File:** `agent_orchestrator.py`

**Purpose:** Backup check + data validation

**Frequency:** Once daily (9 AM)

**What it does:**
- Validates data quality
- Checks for any missed filings (rare)
- Runs Investigation Agent for anomalies
- Lightweight - most updates already handled by real-time monitors

**AI knows:** "Filing monitor + price monitor + Reddit monitor handle 95% of updates. Be selective."

**Typical daily run:**
```
[ORCHESTRATOR] Decision: Run DataValidator only (all other data is real-time)
[ORCHESTRATOR] Scheduled 1 task

[DataValidator] Validating 155 SPACs...
[DataValidator] ✓ No anomalies detected
```

**How to schedule:**
```bash
crontab -e
# Add: 0 9 * * * /path/to/agent_orchestrator.py
```

---

## Complete System Setup

### 1. Start All Real-Time Monitors

```bash
# SEC Filing Monitor
screen -S filing-monitor
python3 sec_filing_monitor.py
# Ctrl+A, D

# Price Monitor
screen -S price-monitor
python3 realtime_price_monitor.py
# Ctrl+A, D

# Reddit Monitor
screen -S reddit-monitor
python3 realtime_reddit_monitor.py
# Ctrl+A, D

# View running screens
screen -ls
```

**Expected output:**
```
There are screens on:
    12345.filing-monitor    (Detached)
    12346.price-monitor     (Detached)
    12347.reddit-monitor    (Detached)
3 Sockets in /var/run/screen/S-ubuntu.
```

---

### 2. Schedule Orchestrator (Safety Net)

```bash
crontab -e

# Add:
# Orchestrator - Daily at 9 AM (validation only)
0 9 * * * /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/agent_orchestrator.py >> ~/spac-research/logs/orchestrator.log 2>&1

# Issue Resolution Agent - Every hour
0 * * * * /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/agents/issue_resolution_agent.py >> ~/spac-research/logs/issue_agent.log 2>&1
```

---

### 3. Monitor System Health

```bash
# Check if all monitors are running
ps aux | grep -E "(sec_filing|realtime_price|realtime_reddit)"

# View filing monitor activity
tail -f ~/spac-research/logs/filing_monitor.log

# View price updates (real-time)
screen -r price-monitor

# View Reddit activity
screen -r reddit-monitor

# Check database freshness
psql -U spac_user -d spac_db -c "
SELECT
    ticker,
    price,
    premium,
    reddit_mentions_7d,
    reddit_last_updated,
    updated_at
FROM spacs
ORDER BY updated_at DESC
LIMIT 10;
"
```

---

## Data Freshness Guarantee

### Filing Data (from SEC)
- **Latency:** 15-20 minutes from SEC publication
- **Example:** Deal announced at 10:30 AM → Database updated by 10:50 AM

### Price Data (from Yahoo Finance)
- **Latency:** 30 seconds during market hours
- **Example:** Price changes at 2:35:00 PM → Database updated by 2:35:30 PM

### Reddit Data (from r/SPACs)
- **Latency:** 15 minutes from post
- **Example:** Speculation post at 11:00 AM → Database updated by 11:15 AM

### Validation (from Orchestrator)
- **Frequency:** Once daily
- **Purpose:** Catch any edge cases or anomalies

---

## System Resource Usage

### CPU
- Filing Monitor: ~2% (polls every 15 min, mostly idle)
- Price Monitor: ~8% during market hours (30-sec updates), ~1% off-hours
- Reddit Monitor: ~3% (API calls every 15 min)
- **Total:** ~13% CPU during market hours

### Memory
- Filing Monitor: ~100 MB
- Price Monitor: ~80 MB
- Reddit Monitor: ~90 MB
- **Total:** ~270 MB RAM

### Network
- SEC API: ~10 requests/min during filing detection
- Yahoo Finance: ~155 requests every 30 sec (during market hours)
- Reddit API: ~50 requests every 15 min
- **Total:** Moderate bandwidth (~5 MB/hour during market hours)

### Disk
- Log files: **~2 MB/day** (end-of-day summaries only)
  - Filing monitor: ~1 MB/day (filing events only)
  - Price monitor: ~500 KB/day (end-of-day summary only, not every update)
  - Reddit monitor: ~500 KB/day (activity summaries)
- Database updates: Negligible (just field updates)
- **Total:** ~60 MB/month for logs

**Log Strategy:**
- Price monitor: Only logs end-of-day summary (4:00 PM ET)
- Filing monitor: Only logs filing detection events
- Reddit monitor: Only logs unusual activity
- **Database is updated in real-time** (every 30 seconds for prices)
- **Console shows live updates** for monitoring

**Recommendation:** Rotate logs every 6 months
```bash
# Add to cron
0 0 1 */6 * find ~/spac-research/logs -name "*.log" -mtime +180 -delete
```

---

## Failover & Resilience

### If Filing Monitor Crashes
- **Detection:** Orchestrator checks last filing detection timestamp
- **Backup:** Orchestrator runs DealMonitor to catch missed filings
- **Alert:** Telegram notification if monitor down >1 hour

### If Price Monitor Crashes
- **Detection:** Orchestrator checks last price update timestamp
- **Backup:** Orchestrator runs PriceUpdater
- **Impact:** Stale prices for up to 9 hours (until next orchestrator run)

### If Reddit Monitor Crashes
- **Detection:** Check `reddit_last_updated` field
- **Backup:** Orchestrator runs RedditMonitor
- **Impact:** Missing Reddit sentiment for up to 24 hours

### Auto-Restart on Crash

```bash
# Create monitor script
cat > /home/ubuntu/spac-research/monitor_health.sh << 'EOF'
#!/bin/bash

# Check if filing monitor is running
if ! pgrep -f "sec_filing_monitor.py" > /dev/null; then
    echo "[$(date)] Filing monitor down, restarting..."
    screen -dmS filing-monitor bash -c "cd /home/ubuntu/spac-research && python3 sec_filing_monitor.py"
fi

# Check if price monitor is running
if ! pgrep -f "realtime_price_monitor.py" > /dev/null; then
    echo "[$(date)] Price monitor down, restarting..."
    screen -dmS price-monitor bash -c "cd /home/ubuntu/spac-research && python3 realtime_price_monitor.py"
fi

# Check if reddit monitor is running
if ! pgrep -f "realtime_reddit_monitor.py" > /dev/null; then
    echo "[$(date)] Reddit monitor down, restarting..."
    screen -dmS reddit-monitor bash -c "cd /home/ubuntu/spac-research && python3 realtime_reddit_monitor.py"
fi
EOF

chmod +x /home/ubuntu/spac-research/monitor_health.sh

# Schedule health check every 5 minutes
crontab -e
# Add: */5 * * * * /home/ubuntu/spac-research/monitor_health.sh >> ~/spac-research/logs/health.log 2>&1
```

---

## Systemd Services (Production Setup)

For production, use systemd instead of screen:

```bash
# Create systemd services
sudo tee /etc/systemd/system/spac-filing-monitor.service << EOF
[Unit]
Description=SPAC Filing Monitor (Real-Time)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/spac-research
ExecStart=/home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/sec_filing_monitor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/spac-price-monitor.service << EOF
[Unit]
Description=SPAC Price Monitor (Real-Time)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/spac-research
ExecStart=/home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/realtime_price_monitor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/spac-reddit-monitor.service << EOF
[Unit]
Description=SPAC Reddit Monitor (Real-Time)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/spac-research
ExecStart=/home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/realtime_reddit_monitor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start all services
sudo systemctl daemon-reload
sudo systemctl enable spac-filing-monitor spac-price-monitor spac-reddit-monitor
sudo systemctl start spac-filing-monitor spac-price-monitor spac-reddit-monitor

# Check status
sudo systemctl status spac-filing-monitor
sudo systemctl status spac-price-monitor
sudo systemctl status spac-reddit-monitor
```

---

## Summary

**Real-Time Monitors (24/7):**
| Monitor | Frequency | Updates | Latency |
|---------|-----------|---------|---------|
| SEC Filing | 15 min | Deals, extensions, trust data, votes | 15-20 min |
| Price | 30 sec (market hours) | Prices, premiums | 30 sec |
| Reddit | 15 min | Mentions, sentiment, speculation | 15 min |

**Coverage:** ~95% of database updates handled in real-time

**Orchestrator (Daily):**
- Purpose: Safety net + validation
- Frequency: Once daily (9 AM)
- Coverage: ~5% (backup checks)

**Result:** Database reflects reality within **30 seconds - 20 minutes** across all data sources! 🚀

**This is a truly real-time system.** ⚡
- **Price data:** 30-second latency (near-real-time)
- **Filing data:** 15-20 minute latency (event-driven)
- **Reddit data:** 15-minute latency (continuous monitoring)
