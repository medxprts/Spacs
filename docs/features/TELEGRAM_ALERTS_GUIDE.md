# Telegram Alerts - Quick Reference

## What You'll Receive

### 🚨 Instant Leak Alerts (Confidence ≥ 70%)
Sent immediately when leak detected during daily 10 AM scan

**Contains:**
- Ticker + Company name
- Leak confidence percentage
- Current premium
- Reddit mention count (last 7 days)
- Bullish sentiment ratio
- Number of deal speculation comments
- Rumored target company (if mentioned)
- Total engagement score

**Example:**
```
🚨 SPAC LEAK DETECTED 🚨

RTAC - Renatus Tactical Acquisition Corp I
Confidence: 80%
Premium: 9.23%

Reddit Mentions: 6 (last 7 days)
Bullish Ratio: 67%
Deal Speculation: 4 comments

🎯 Rumored Target: Rubidex

📊 Total Engagement: 89
```

### 📊 Daily Summary Alert
Sent after full scan completes (only if high-confidence leaks found)

**Contains:**
- Total count of leaks detected
- List of all tickers with ≥70% confidence
- Key metrics for each

**Example:**
```
📊 Daily Reddit Scan Complete

Found 2 high-confidence leak(s):

• RTAC (80% confidence)
  Premium: 9.23%, Mentions: 6
  Target: Rubidex

• ABCD (75% confidence)
  Premium: 12.5%, Mentions: 8
  Target: TechCo
```

## Alert Timing

**Automated Scan**: Every day at 10:00 AM
- Scans all pre-deal SPACs with premium > 5%
- Analyzes r/SPACs Daily Discussion threads
- Sends alerts for confidence ≥ 70%

**Manual Scan**: Run anytime
```bash
python3 reddit_sentiment_tracker.py --scan-all
```

## What Triggers an Alert?

**Leak Detection Criteria:**
1. SPAC status = SEARCHING (no deal announced)
2. AND one of:
   - 3+ Reddit comments mention deal speculation
   - Same target company mentioned 2+ times

**Confidence Calculation:**
- Each speculation comment: +20% confidence
- Each target mention: +30% confidence
- Max confidence: 95%

**Alert Threshold:**
- Telegram alerts sent only for confidence ≥ 70%
- Lower confidence leaks logged but not alerted

## What To Do When You Get an Alert

1. **Review Premium**: High premium + leak = market may already know
2. **Check Reddit**: Click through to r/SPACs Daily Discussion
3. **Read Comments**: Review the actual speculation (URLs in log files)
4. **Verify Target**: Search for the rumored target company
5. **Monitor Price Action**: Watch for volume/price spikes
6. **Set Price Alerts**: Consider entry point if conviction high

## Manual Commands

### Check Single SPAC
```bash
python3 reddit_sentiment_tracker.py --ticker RTAC
```

### Full Leak Scan
```bash
python3 reddit_sentiment_tracker.py --scan-all
```

### View Today's Log
```bash
cat logs/reddit_sentiment_$(date +%Y%m%d).log
```

### View Latest Scan Results
```bash
ls -lt logs/reddit_sentiment_*.log | head -1 | awk '{print $9}' | xargs cat
```

## Adjusting Alert Sensitivity

To change the confidence threshold for alerts, edit:
`/home/ubuntu/spac-research/reddit_sentiment_tracker.py`

Find line ~533:
```python
if leak_report['confidence'] >= 70:  # Change this number
```

- **Lower (e.g., 50)**: More alerts, more false positives
- **Higher (e.g., 80)**: Fewer alerts, higher quality signals
- **Default: 70%** - Good balance

## Disable Telegram Alerts

Remove from `.env`:
```bash
# Comment out or remove these lines:
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
```

Alerts will stop, but log files continue.

## Historical Accuracy Tracking

Coming soon: Track which leaks predicted actual deals

**Planned Features:**
- Leak → Deal confirmation tracking
- False positive rate analysis
- Time-to-announcement metrics
- Premium change correlation
