# Multi-Source Deal Monitor Setup Guide

## Overview

Your new deal detection system combines **4 free sources** for comprehensive SPAC deal monitoring:

1. **SEC RSS Feed** - Real-time 8-K monitoring (100% free, no API key)
2. **News API** - Financial news aggregation (500 requests/day free)
3. **Twitter API** - Social signals from key accounts (500k tweets/month free)
4. **AI Validation** - DeepSeek API for signal validation (already configured)

**Total Cost: $0/month** (all free tiers)

---

## Quick Start

### 1. Install Dependencies

```bash
cd /home/ubuntu/spac-research
pip install feedparser tweepy  # Add missing packages
```

### 2. Get Free API Keys

#### News API (5 minutes)
1. Visit: https://newsapi.org/register
2. Sign up for free tier (500 requests/day)
3. Copy your API key
4. Add to `.env`:
   ```bash
   NEWS_API_KEY=your_key_here
   ```

#### Twitter API (10 minutes)
1. Visit: https://developer.twitter.com/en/portal/dashboard
2. Sign up for free tier (500k tweets/month)
3. Create an app
4. Copy your Bearer Token
5. Add to `.env`:
   ```bash
   TWITTER_BEARER_TOKEN=your_token_here
   ```

### 3. Test Individual Monitors

```bash
# Test SEC RSS (no API key needed)
python3 sec_rss_monitor.py --once

# Test News API
python3 news_api_monitor.py --ticker CEP

# Test Twitter
python3 twitter_monitor.py --ticker CEP

# Test unified system (dry run)
python3 deal_monitor_unified.py
```

### 4. Run Full Scan

```bash
# Dry run (don't commit to database)
python3 deal_monitor_unified.py

# Live run (commit confirmed deals)
python3 deal_monitor_unified.py --commit
```

---

## Usage Examples

### Daily Monitoring (Recommended)

```bash
# Conservative: preserve API quota
python3 deal_monitor_unified.py \
  --commit \
  --news-max-spacs 50 \
  --twitter-max-spacs 30
```

**API Usage:**
- News API: ~50 requests (10% of daily quota)
- Twitter: ~30 requests (unlimited on free tier)
- Runs in ~5-10 minutes

### Aggressive Monitoring

```bash
# Scan all SPACs (uses more API quota)
python3 deal_monitor_unified.py \
  --commit \
  --news-days 14 \
  --twitter-hours 48
```

**API Usage:**
- News API: ~155 requests (31% of daily quota)
- Twitter: ~155 requests
- Runs in ~15-20 minutes

### Real-time SEC Monitoring

```bash
# Run continuously, check SEC RSS every 10 minutes
python3 sec_rss_monitor.py --continuous --interval 10

# Or use screen/tmux for background:
screen -S sec_monitor
python3 sec_rss_monitor.py --continuous
# Detach with Ctrl+A, D
```

---

## Automation Setup

### Option 1: Cron Job (Recommended)

Run unified monitor twice daily:

```bash
crontab -e
```

Add:
```bash
# 9 AM daily scan
0 9 * * * cd /home/ubuntu/spac-research && /home/ubuntu/spac-research/venv/bin/python3 deal_monitor_unified.py --commit --news-max-spacs 50 --twitter-max-spacs 30 >> logs/deal_monitor_daily.log 2>&1

# 3 PM daily scan
0 15 * * * cd /home/ubuntu/spac-research && /home/ubuntu/spac-research/venv/bin/python3 deal_monitor_unified.py --commit --news-max-spacs 50 --twitter-max-spacs 30 >> logs/deal_monitor_daily.log 2>&1
```

### Option 2: Systemd Service (Real-time)

Create `/etc/systemd/system/sec-rss-monitor.service`:

```ini
[Unit]
Description=SEC RSS Monitor for SPAC Deals
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/spac-research
ExecStart=/home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/sec_rss_monitor.py --continuous --interval 10
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable sec-rss-monitor
sudo systemctl start sec-rss-monitor
sudo systemctl status sec-rss-monitor
```

---

## API Quota Management

### News API Free Tier
- **Limit:** 500 requests/day
- **Resets:** Daily at midnight UTC
- **Strategy:** Scan 50 SPACs 2x/day = 100 requests/day (20% usage)
- **Buffer:** 400 requests for ad-hoc queries

### Twitter API Free Tier
- **Limit:** 500k tweets/month, 50 requests/15min
- **Strategy:** Scan 30 SPACs/run, 2x/day = 60/day = 1,800/month
- **Usage:** <1% of quota

### SEC RSS
- **Limit:** None (public RSS feed)
- **Best Practice:** Poll every 10-15 minutes
- **Usage:** Unlimited

### DeepSeek AI
- **Cost:** ~$0.14 per 1M input tokens, $0.28 per 1M output
- **Usage:** ~100 validations/month = <$0.05/month
- **Essentially free**

---

## Architecture Diagram

```
┌─────────────────────────────────────────┐
│         Data Sources (All Free)         │
├─────────────────────────────────────────┤
│ 1. SEC RSS Feed (every 10 mins)        │
│ 2. News API (2x daily, 50 SPACs)       │
│ 3. Twitter (2x daily, 30 SPACs)        │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│      Deal Signal Aggregator             │
│   - Deduplicates signals                │
│   - Combines from multiple sources      │
│   - Tracks confidence scores            │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│       AI Validator (DeepSeek)           │
│   - Validates real vs. false deals      │
│   - Extracts target company name        │
│   - Scores confidence (0-100%)          │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│         Database Update                 │
│   - Updates deal_status=ANNOUNCED       │
│   - Sets target, announced_date         │
│   - Logs to data_validation.jsonl       │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│         Notifications (Optional)        │
│   - Telegram alerts                     │
│   - Email notifications                 │
│   - Streamlit dashboard update          │
└─────────────────────────────────────────┘
```

---

## Monitoring & Logs

### View Logs
```bash
# Latest unified scan
tail -f logs/deal_monitor_daily.log

# View recent scans
ls -lth logs/deal_scan_*.json | head -5

# View specific scan results
cat logs/deal_scan_20251007_143020.json | jq
```

### Check API Usage
```bash
# News API usage in script output
grep "API requests used" logs/deal_monitor_daily.log

# Twitter API usage
grep "API requests used" logs/deal_monitor_daily.log
```

### Data Quality Logs
```bash
# View recent deal detections
python3 data_validation_log.py --recent 20 | grep deal_signal_aggregator
```

---

## Troubleshooting

### "NEWS_API_KEY not found"
- Check `.env` file exists in `/home/ubuntu/spac-research/`
- Verify key format: `NEWS_API_KEY=abc123...`
- No quotes needed around key

### "Twitter API rate limit reached"
- Free tier: 50 requests per 15 minutes
- Solution: Reduce `--twitter-max-spacs` or increase scan interval

### "AI validation not available"
- Check `DEEPSEEK_API_KEY` in `.env`
- Test: `python3 -c "from deal_signal_aggregator import AI_AVAILABLE; print(AI_AVAILABLE)"`

### "No deals found" (but you know there was one)
- Check if SPAC has `cik` field populated
- Verify SPAC `deal_status='SEARCHING'` (monitors skip announced deals)
- Check logs for parsing errors

---

## Optimization Tips

### 1. Prioritize High-Value SPACs
Create `priority_spacs.txt`:
```
CEP
APAD
GSRT
```

Modify script to scan these first.

### 2. Adjust Scan Frequency
- **Urgent:** Real-time SEC RSS (continuous)
- **Standard:** 2x daily unified scan
- **Conservative:** 1x daily scan

### 3. Preserve API Quota
```bash
# Only scan SPACs near deadline (high urgency)
# Add filter in deal_monitor_unified.py:
spacs = db.query(SPAC).filter(
    SPAC.deal_status == 'SEARCHING',
    SPAC.days_to_deadline < 180  # <6 months to deadline
).all()
```

---

## Feature Roadmap

### Phase 1: Complete ✅
- SEC RSS monitor
- News API integration
- Twitter monitoring
- Unified aggregator
- AI validation

### Phase 2: Coming Soon
- Reddit r/SPACs monitoring (free)
- Company IR page scraper (free)
- Press release wire RSS feeds (free)
- Deal progression tracker (LOI → definitive → proxy → close)

### Phase 3: Advanced
- Sentiment analysis on social signals
- Deal probability scoring
- Automated deal term extraction (PIPE, min cash, etc.)
- Competitive intelligence (banker presentations)

---

## Support

### Get Help
```bash
# Test all monitors
python3 deal_monitor_unified.py --help

# Individual monitor help
python3 sec_rss_monitor.py --help
python3 news_api_monitor.py --help
python3 twitter_monitor.py --help
```

### Report Issues
Create an issue with:
1. Command you ran
2. Error message
3. Relevant logs from `logs/` directory

---

## Cost Analysis

| Service | Free Tier | Your Usage | % Used | Cost |
|---------|-----------|------------|--------|------|
| SEC RSS | Unlimited | Continuous | 0% | $0 |
| News API | 500 req/day | 100 req/day | 20% | $0 |
| Twitter | 500k tweets/month | 1,800/month | <1% | $0 |
| DeepSeek | $0.14/1M tokens | <10k tokens/month | <1% | <$0.05 |
| **TOTAL** | | | | **~$0/month** |

**Upgrading to paid tiers:**
- News API: $449/month (unlimited)
- Twitter API: $100/month (higher rate limits)
- **Not necessary for your use case!**

---

## Next Steps

1. ✅ Test individual monitors
2. ✅ Run unified dry run
3. ✅ Set up cron job for automation
4. ✅ Monitor logs for first week
5. ✅ Adjust scan frequency based on results

Happy deal hunting! 🎯
