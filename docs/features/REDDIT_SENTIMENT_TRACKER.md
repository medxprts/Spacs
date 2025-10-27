# Reddit Sentiment Tracker

## Overview

Monitors r/SPACs, r/wallstreetbets, and r/stocks to detect:
1. **Deal Leaks** - Speculation about targets before official announcements
2. **Sentiment Spikes** - 3x+ activity increases that often precede premium spikes

## Use Cases

### 1. Leak Detection
**Problem**: Sometimes deal discussions start on Reddit days/weeks before official announcement.

**Solution**: Track pre-deal SPACs with elevated premiums and scan for:
- Multiple posts speculating about specific targets
- Deal-related keywords appearing before 8-K filing
- Insider information patterns

**Example Alert**:
```
🚨 POTENTIAL LEAK DETECTED! (confidence: 85%)
   SPAC: ABC - Premium: 18%
   Deal speculation mentions: 5
   Rumored target: SpaceX (mentioned 3 times)
```

### 2. Premium Spike Prediction
**Problem**: By the time premium spikes 20-30%, the move is over.

**Solution**: Detect sentiment spikes that historically precede price action:
- 3x+ increase in mentions over 24h vs 7-day average
- 3x+ increase in engagement (upvotes + comments)
- Early warning before institutions pile in

**Example Alert**:
```
🚨 SENTIMENT SPIKE DETECTED! (3.2x normal activity)
   SPAC: XYZ - Premium: 8% (still cheap!)
   Recent mentions (24h): 12 vs avg 3.7/day
   Recent engagement (24h): 450 vs avg 120/day
```

## Setup

### 1. Get Reddit API Credentials

1. Go to https://www.reddit.com/prefs/apps
2. Click "create app" or "create another app"
3. Fill out form:
   - **Name**: SPAC Research Platform
   - **App type**: Script
   - **Redirect URI**: http://localhost:8080
4. Copy your credentials

### 2. Add to .env

```bash
REDDIT_CLIENT_ID=your-client-id-here
REDDIT_CLIENT_SECRET=your-client-secret-here
REDDIT_USER_AGENT=SPAC Research Platform by /u/YourRedditUsername
```

### 3. Install Dependencies

```bash
pip install praw
```

## Usage

### Single Ticker Analysis

```bash
python3 reddit_sentiment_tracker.py --ticker SPAC
```

**Output**:
- Search results across 3 subreddits
- Leak detection analysis
- Sentiment spike detection
- Top 5 posts with sentiment classification
- Deal speculation indicators

### Full Market Scan

```bash
python3 reddit_sentiment_tracker.py --scan-all
```

Scans ALL pre-deal SPACs with premium >5% and generates leak alert summary.

**Best use**: Run daily to catch early signals before market moves.

### Automated Daily Scan

```bash
# Add to crontab for daily 8am scan
crontab -e

# Add this line:
0 8 * * * /home/ubuntu/spac-research/daily_sentiment_scan.sh
```

Check results:
```bash
tail -100 /home/ubuntu/spac-research/logs/sentiment_scan.log
```

## How It Works

### Leak Detection Algorithm

```python
def check_for_leaks(ticker, spac, mentions):
    # 1. Count deal speculation mentions
    deal_speculation_count = sum(1 for m in mentions
                                  if m['sentiment']['is_deal_speculation'])

    # 2. Extract mentioned targets
    targets = [m['sentiment']['mentioned_target']
               for m in mentions if m['sentiment']['mentioned_target']]

    # 3. Flag as leak if:
    #    - SPAC status = SEARCHING (no official deal)
    #    - AND 3+ deal speculation mentions
    #    - OR same target mentioned 2+ times

    if spac.deal_status == 'SEARCHING':
        if deal_speculation_count >= 3:
            return {'leak_detected': True, 'confidence': 80}

        if most_common_target_count >= 2:
            return {'leak_detected': True, 'confidence': 90}

    return {'leak_detected': False}
```

### Sentiment Spike Detection

```python
def track_sentiment_spike(ticker, mentions):
    # Compare last 24h to 7-day average
    recent_24h = [m for m in mentions if created < 24h_ago]
    older = [m for m in mentions if created > 24h_ago]

    daily_avg_mentions = len(older) / days
    daily_avg_engagement = sum(older.engagement) / days

    # Flag as spike if 3x+ increase
    if len(recent_24h) > daily_avg_mentions * 3:
        return {'spike_detected': True, 'multiplier': 3.5}

    return {'spike_detected': False}
```

### AI Sentiment Analysis

Each post/comment is analyzed with DeepSeek AI:

**Input**: Reddit post text
**Output**:
```json
{
  "sentiment": "bullish",
  "is_deal_speculation": true,
  "mentioned_target": "SpaceX",
  "confidence": 85,
  "themes": ["target rumor", "valuation", "management team"]
}
```

## Trading Strategy Example

### Pre-Deal SPAC Leak Strategy

1. **Filter**: SPACs with premium 5-15% (not too low, not too expensive)
2. **Scan Daily**: Run `--scan-all` every morning
3. **Watch for**:
   - 3+ deal speculation posts mentioning same target
   - Sentiment spike (3x+ activity increase)
4. **Action**: Buy small position if leak confidence >80%
5. **Exit**: Sell on official announcement (premium spike)

### Expected Returns
- **Base case**: 5-10% gain if leak confirmed
- **Best case**: 20-30% if deal has good market reception
- **Worst case**: -2% if leak was false (redeem near NAV)

**Risk**: Low - near-NAV entry protects downside

## Cost

- Reddit API: **FREE** (10,000 requests/hour)
- DeepSeek AI: **~$0.001 per analysis** (~$2-5/month for daily scans)

## Example Output

```
================================================================================
Reddit Sentiment Analysis: ATII - Archimedes Tech SPAC Partners II Co.
Status: SEARCHING
Premium: 23.11%
================================================================================

  Searching Reddit for $ATII (last 7 days)...
  ✓ Found 8 mentions across r/SPACs, r/wallstreetbets, r/stocks

🔍 Analyzing for deal leaks...
  🚨 POTENTIAL LEAK DETECTED! (confidence: 85%)
     Deal speculation mentions: 5
     Rumored target: Starship Technologies (mentioned 3 times)

📈 Analyzing sentiment spike (premium predictor)...
  🚨 SENTIMENT SPIKE DETECTED! (4.2x normal activity)
     Recent mentions (24h): 15 vs avg 3.6/day
     Recent engagement (24h): 580 vs avg 120/day

📋 Top mentions:

  [1] r/SPACs - ATII rumored to be merging with Starship Tech
      Score: 45, Comments: 23
      Sentiment: bullish (confidence: 90%)
      ⚠️  Contains deal speculation
      URL: https://reddit.com/r/SPACs/comments/xyz123

  [2] r/wallstreetbets - $ATII DD - autonomous delivery play
      Score: 120, Comments: 67
      Sentiment: bullish (confidence: 85%)
      ⚠️  Contains deal speculation
      URL: https://reddit.com/r/wallstreetbets/comments/abc456
```

## Limitations

- Reddit activity for SPACs has declined since 2021-2022 peak
- Most retail traders moved to crypto/options
- Leak detection works best when there IS Reddit chatter
- False positives possible (speculation without actual leak)

## Future Enhancements

1. **Twitter/X Integration** - Track FinTwit SPAC influencers
2. **StockTwits API** - More SPAC-focused community
3. **Discord Monitoring** - Private SPAC Discord servers
4. **Historical Backtesting** - Measure leak detection accuracy
5. **Telegram Alerts** - Real-time notifications when leak detected

## Support

Issues? Check:
1. Reddit API credentials in `.env`
2. DeepSeek API key configured
3. `praw` library installed
4. Internet connection (Reddit API rate limits)

For help: https://github.com/reddit-archive/reddit/wiki/API
