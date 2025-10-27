# Interactive Telegram Bot Guide

The bot is now **running in the background** and listening for your commands!

## Quick Start

1. **Open Telegram** on your phone or desktop
2. **Find your bot** (search for the bot name or check your recent chats)
3. **Send a command** - just type it like a normal message

## Available Commands

### 🔧 Fix Issues

```
/fix TICKER
```
**Example:** `/fix TBMC`

Auto-fixes all issues for a ticker:
- Re-scrapes SEC filings
- Updates prices
- Recalculates premiums
- Shows what was fixed and what needs manual review

---

### 🔍 Investigate Issues

```
/investigate TICKER
```
**Example:** `/investigate DMYY`

Uses AI to diagnose why issues exist:
- Shows root cause with confidence %
- Explains what went wrong
- Recommends specific actions

---

### 📄 Re-scrape SEC Filings

```
/scrape TICKER
```
**Example:** `/scrape ATMC`

Forces fresh scrape from SEC EDGAR:
- Fetches 8-K, S-1, 10-Q filings
- Extracts IPO date, banker, trust value
- Shows what data was found

---

### 💰 Update Price

```
/price TICKER
```
**Example:** `/price CEP`

Updates price from Yahoo Finance:
- Current price
- Premium vs NAV
- 24h price change

---

### 📊 Run Audits

```
/audit
```
Quick audit on 3 sample SPACs (fast)

```
/fullaudit
```
Full audit on all 155 SPACs (1-2 minutes)

Shows:
- Total issues by severity
- Top issue types
- Health score

---

### 📈 Database Status

```
/status
```

Shows database health:
- Total SPACs
- Deal status breakdown
- Missing data counts
- Overall health score

---

### ❓ Help

```
/help
```
Shows available commands

```
/start
```
Welcome message

---

## Usage Examples

### Scenario 1: Fix an issue from notification

When you get a notification like:
```
🔍 Data Quality Alert - Manual Review Needed

Ticker: TBMC
Issue: missing_ipo_date
...
```

**Just reply:**
```
/fix TBMC
```

The bot will:
1. Re-scrape SEC filings
2. Extract IPO date and other data
3. Report back what was fixed

---

### Scenario 2: Check what's wrong with a SPAC

```
/investigate TBMC
```

**Bot responds:**
```
🔍 Investigation Report: TBMC

Company: Trailblazer Merger Corporation I
Issues Found: 3

1. Missing IPO Date
   Severity: CRITICAL
   Root Cause: CIK lookup failed - company name may be incorrect
   Confidence: 90%
   Recommended: Verify company name in SEC database

2. Never Scraped
   Severity: MEDIUM
   Root Cause: SEC scraper never successfully ran for this ticker
   Confidence: 85%
   Recommended: Re-run scraper after fixing CIK

Fix with: /fix TBMC
```

---

### Scenario 3: Quick health check

```
/status
```

**Bot responds:**
```
📊 Database Status
2025-10-06 15:45

Total SPACs: 155

Deal Status:
  • Announced: 57
  • Searching: 98

Data Quality:
  • Missing IPO date: 68
  • Missing price: 3
  • Never scraped: 56

Health Score: ✅ 75.4%

Run /audit for detailed report
```

---

### Scenario 4: Update prices for trading

```
/price CEP
```

**Bot responds:**
```
✅ Price updated for CEP

  • Price: $10.25
  • Trust Value: $10.00
  • Premium: +2.50%
  • 24h Change: +0.15%
```

---

## Bot Status

**Current Status:** Running in background

**Check if running:**
```bash
ps aux | grep telegram_bot.py
```

**View logs:**
```bash
tail -f telegram_bot_output.log
```

**Stop bot:**
```bash
pkill -f telegram_bot.py
```

**Start bot:**
```bash
python3 telegram_bot.py > telegram_bot_output.log 2>&1 &
```

**View bot activity:**
```bash
tail -20 telegram_bot.log
```

---

## Running as System Service

To keep the bot running 24/7 (survives reboots):

1. Create systemd service:

```bash
sudo nano /etc/systemd/system/spac-telegram-bot.service
```

2. Add this content:

```ini
[Unit]
Description=SPAC Data Quality Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/spac-research
Environment="PATH=/usr/bin:/usr/local/bin"
ExecStart=/usr/bin/python3 /home/ubuntu/spac-research/telegram_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable spac-telegram-bot
sudo systemctl start spac-telegram-bot
sudo systemctl status spac-telegram-bot
```

4. Control service:

```bash
# Stop
sudo systemctl stop spac-telegram-bot

# Restart
sudo systemctl restart spac-telegram-bot

# View logs
sudo journalctl -u spac-telegram-bot -f
```

---

## Tips

1. **Quick fixes:** When you get alerts, just reply with `/fix [TICKER]`

2. **Morning routine:** Send `/status` to see overnight issues

3. **Before market open:** Send `/audit` to check data freshness

4. **After deal announcements:** Use `/scrape [TICKER]` to get latest 8-K

5. **Batch commands:** Send multiple commands in sequence:
   ```
   /fix TBMC
   /fix DMYY
   /status
   ```

6. **Case insensitive:** `/fix tbmc` works same as `/fix TBMC`

7. **Investigate first:** Use `/investigate` before `/fix` for complex issues

---

## Troubleshooting

**Bot not responding?**
```bash
# Check if running
ps aux | grep telegram_bot.py

# Check logs
tail -20 telegram_bot_output.log

# Restart
pkill -f telegram_bot.py
python3 telegram_bot.py > telegram_bot_output.log 2>&1 &
```

**Commands timing out?**
- SEC scraping can take 30-60 seconds
- Full audit takes 1-2 minutes
- Bot will respond when complete

**"Error" message?**
- Check logs: `tail telegram_bot.log`
- Verify ticker exists: `/status`
- Try `/investigate` instead of `/fix`

---

## Integration with Data Quality Agent

The bot uses the same backend as `data_quality_agent.py`:

- **Bot commands** = Interactive, on-demand fixes
- **data_quality_agent.py** = Scheduled batch processing
- **Both share** same database, scraper, price updater

Run daily via cron for automated fixes, use bot for manual intervention.

---

## Security Note

The bot only responds to your Telegram chat ID (configured in `.env`).

To change allowed user:
1. Edit `.env`
2. Update `TELEGRAM_CHAT_ID`
3. Restart bot

---

## Next Steps

1. ✅ Bot is running - try sending `/help` in Telegram
2. Test with `/status` to see current database state
3. Try `/fix` on one of the problem tickers from earlier
4. Set up systemd service for 24/7 operation
5. Add daily cron job for automated maintenance

The bot will keep running in the background until you stop it or reboot.
