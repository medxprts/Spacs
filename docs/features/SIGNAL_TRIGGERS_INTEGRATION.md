# Signal Triggers Integration - Reddit & News

**Date:** October 9, 2025
**Status:** ✅ Implemented

---

## Overview

**NEW ORCHESTRATOR TRIGGER:** News releases and Reddit activity now trigger the orchestrator to take immediate action on potential deal leaks and market-moving events.

---

## Why This Matters

### Problem
- News articles often beat SEC filings by hours/days
- Reddit discussions can detect deal "leaks" before official announcements
- Current system only monitors SEC (reactive, not proactive)

### Solution
**Multi-Source Signal Detection →Orchestrator Triggers → Immediate Verification**

---

## Alert Flow

```
┌─────────────────────────────────────────────────────────────┐
│              SIGNAL SOURCES (Monitored)                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  📰 News Feeds                🗣️ Reddit                      │
│  ├─ Google News RSS           ├─ r/SPACs mentions          │
│  ├─ PR Newswire RSS          ├─ Deal speculation           │
│  ├─ Business Wire RSS        ├─ Sentiment spikes           │
│  ├─ Yahoo Finance RSS        └─ Target mentions            │
│  └─ NewsAPI (backup)                                        │
│                                                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓ Signal detected
┌─────────────────────────────────────────────────────────────┐
│           SIGNAL MONITOR AGENT                               │
│           (Runs every 3-6 hours)                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Collect signals from all sources                        │
│  2. Calculate confidence (0-100%)                           │
│  3. Detect patterns (spikes, multiple sources, keywords)    │
│  4. Assess priority (CRITICAL/HIGH/MEDIUM/LOW)              │
│                                                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓ IF: Confidence >70% OR Critical keywords
┌─────────────────────────────────────────────────────────────┐
│                TELEGRAM ALERTS                               │
│               (Immediate notification)                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  🚨 CRITICAL: "Definitive agreement" in news                │
│  ⚠️  HIGH: Reddit spike + deal speculation                  │
│  📊 MEDIUM: Multiple sources same ticker                    │
│                                                              │
│  Alert includes:                                            │
│  • Ticker + confidence %                                    │
│  • Reason for trigger                                       │
│  • Reddit details (mentions, sentiment, spike)              │
│  • News details (articles, keywords, target)                │
│  • Orchestrator actions triggered                           │
│                                                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓ Triggers orchestrator
┌─────────────────────────────────────────────────────────────┐
│           ORCHESTRATOR ACTIONS                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  → Dispatch DealDetector (verify via SEC 8-Ks)             │
│  → Update database (if deal confirmed)                      │
│  → Run DataValidator (ensure consistency)                   │
│  → Send follow-up alert (verification results)              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Trigger Conditions

### CRITICAL Priority (Immediate Alert + Action)

| Condition | Confidence | Orchestrator Action |
|-----------|-----------|-------------------|
| News: "Definitive agreement" keyword | 90%+ | → Verify 8-K immediately + Update status + Alert |
| News: "Merger agreement" + target named | 90%+ | → Extract target + Verify + Update |
| Multiple news articles (3+) same day | 85%+ | → Full SEC verification cycle |

### HIGH Priority (Alert + Action)

| Condition | Confidence | Orchestrator Action |
|-----------|-----------|-------------------|
| Reddit: Mention spike 3x + deal speculation | 75%+ | → Check 8-Ks + Monitor closely |
| Reddit + News: Both sources signal | 80%+ | → Immediate SEC verification |
| News: 2+ articles with deal keywords | 70%+ | → Verify via DealDetector |

### MEDIUM Priority (Action, Alert if Confirmed)

| Condition | Confidence | Orchestrator Action |
|-----------|-----------|-------------------|
| Reddit: High sentiment + deal speculation | 60%+ | → Monitor + Verify next cycle |
| News: 1 article with deal keywords | 50%+ | → Add to verification queue |
| Combined confidence >70% | 70%+ | → Trigger DealDetector |

---

## Free Real-Time News RSS Feeds

### Recommended Sources (All Free)

#### 1. **Google News RSS** (Best for SPAC news)
```
# Company-specific
https://news.google.com/rss/search?q={TICKER}+SPAC+merger

# SPAC deals in general
https://news.google.com/rss/search?q=SPAC+definitive+agreement

# Update frequency: Real-time (< 1 minute)
# Coverage: Aggregates from 1000s of sources
# Cost: FREE
```

**Pros:**
- Real-time updates
- Aggregates ALL news sources
- No API key needed
- No rate limits

**Example for CCCX:**
```
https://news.google.com/rss/search?q=CCCX+SPAC+merger+OR+business+combination
```

#### 2. **Yahoo Finance RSS** (Good for SPAC news)
```
# Company-specific
https://finance.yahoo.com/rss/headline?s={TICKER}

# Update frequency: ~5 minutes
# Coverage: Yahoo Finance + partners
# Cost: FREE
```

#### 3. **PR Newswire RSS** (Official press releases)
```
# SPAC deals
https://www.prnewswire.com/rss/mergers-and-acquisitions.rss

# Update frequency: Real-time
# Coverage: Official company press releases
# Cost: FREE (public releases)
```

**Pros:**
- Official announcements (high confidence)
- Often beats SEC filings by hours
- No rate limits

#### 4. **Business Wire RSS** (Official press releases)
```
# SPAC category
https://www.businesswire.com/portal/site/home/rss/

# Filter by keyword in RSS reader
# Update frequency: Real-time
# Cost: FREE
```

#### 5. **Seeking Alpha RSS** (Analysis + News)
```
# SPAC news
https://seekingalpha.com/market-news/spacs.xml

# Update frequency: ~15 minutes
# Coverage: News + analysis
# Cost: FREE (with registration)
```

---

## Implementation

### File Created: `signal_monitor_agent.py`

**What it does:**
1. Monitors Reddit (r/SPACs) for mentions, sentiment, deal speculation
2. Monitors News feeds for deal keywords
3. Calculates combined confidence
4. Triggers orchestrator when confidence >70%
5. **Sends Telegram alerts for HIGH/CRITICAL priority**

### Integration with Orchestrator

**Added to orchestrator:**
```python
# agent_orchestrator.py

self.agents = {
    # ... existing agents ...
    'signal_monitor': SignalMonitorAgentWrapper('signal_monitor', self.state_manager)
}
```

**AI Decision Making Updated:**
```python
# Orchestrator now considers:
- Signal monitor last run time
- Recent deal signal triggers
- Reddit/News activity levels

# Example decision:
{
  "tasks": [
    {
      "agent": "signal_monitor",
      "priority": "HIGH",
      "reason": "Check for deal leaks (last run 6h ago)"
    },
    {
      "agent": "deal_hunter",
      "priority": "MEDIUM",
      "reason": "Verify signals via SEC 8-Ks"
    }
  ]
}
```

---

## Telegram Alert Examples

### Example 1: CRITICAL - News Article with Definitive Agreement

```
🚨 CRITICAL PRIORITY SIGNAL

Ticker: $CCCX
Reason: News article mentions definitive agreement
Confidence: 95%

News:
  • Articles: 2
  • 🚨 DEFINITIVE AGREEMENT MENTIONED
  • Target: TechCorp Industries

Actions: deal_detector, data_validator
```

### Example 2: HIGH - Reddit Spike + Deal Speculation

```
⚠️ HIGH PRIORITY SIGNAL

Ticker: $MLAC
Reason: Reddit mention spike (18 mentions) with deal speculation
Confidence: 82%

Reddit:
  • Mentions: 18
  • Sentiment: bullish
  • Deal speculation detected
  • ⚠️ MENTION SPIKE DETECTED

Actions: deal_detector
```

### Example 3: MEDIUM - Multiple Sources

```
📊 MEDIUM PRIORITY SIGNAL

Ticker: $CEP
Reason: Signals from both Reddit and News
Confidence: 73%

Reddit:
  • Mentions: 8
  • Sentiment: bullish

News:
  • Articles: 1
  • Keywords: "business combination"

Actions: deal_detector
```

---

## RSS Feed Integration (Recommended Architecture)

### Current: NewsAPI (Limited)
- 500 requests/day limit
- Delayed updates (~1 hour)
- Requires API key
- ✅ Currently works

### Proposed: RSS Feeds (Better)
- Unlimited requests
- Real-time updates (< 1 minute)
- No API key needed
- More comprehensive

### Implementation Plan

**Add RSS Feed Monitor:**
```python
# rss_news_monitor.py

import feedparser
from datetime import datetime

class RSSNewsMonitor:
    def __init__(self):
        self.feeds = {
            'google_news': 'https://news.google.com/rss/search?q=SPAC+definitive+agreement',
            'pr_newswire': 'https://www.prnewswire.com/rss/mergers-and-acquisitions.rss',
            'business_wire': 'https://www.businesswire.com/portal/site/home/rss/',
            'yahoo_finance': 'https://finance.yahoo.com/rss/headline?s={ticker}'
        }

    def poll_feeds(self, ticker: Optional[str] = None) -> List[Dict]:
        """Poll all RSS feeds for new articles"""
        articles = []

        for feed_name, feed_url in self.feeds.items():
            if '{ticker}' in feed_url and ticker:
                feed_url = feed_url.format(ticker=ticker)
            elif '{ticker}' in feed_url:
                continue

            feed = feedparser.parse(feed_url)

            for entry in feed.entries:
                # Check if mentions ticker or SPAC keywords
                if self._is_relevant(entry, ticker):
                    articles.append({
                        'title': entry.title,
                        'url': entry.link,
                        'published': entry.published_parsed,
                        'source': feed_name,
                        'summary': entry.get('summary', '')
                    })

        return articles

    def _is_relevant(self, entry, ticker: Optional[str]) -> bool:
        """Check if article is relevant to SPAC deals"""
        text = f"{entry.title} {entry.get('summary', '')}".lower()

        # Check for deal keywords
        deal_keywords = [
            'definitive agreement',
            'merger agreement',
            'business combination',
            'spac deal'
        ]

        if ticker and ticker.lower() in text:
            return True

        return any(keyword in text for keyword in deal_keywords)
```

**Integrate into SignalMonitorAgent:**
```python
# signal_monitor_agent.py

def check_rss_signals(self, ticker: str, hours_back: int = 24) -> Dict:
    """Check RSS feeds for recent news"""
    rss_monitor = RSSNewsMonitor()

    articles = rss_monitor.poll_feeds(ticker=ticker)

    # Filter for recent articles (last N hours)
    recent_articles = [
        a for a in articles
        if datetime(*a['published'][:6]) > datetime.now() - timedelta(hours=hours_back)
    ]

    # Analyze for deal signals
    has_definitive_agreement = any(
        'definitive agreement' in a['title'].lower() or
        'definitive agreement' in a['summary'].lower()
        for a in recent_articles
    )

    return {
        'articles_count': len(recent_articles),
        'has_definitive_agreement': has_definitive_agreement,
        'sources': list(set(a['source'] for a in recent_articles)),
        'confidence': self._calculate_rss_confidence(recent_articles)
    }
```

---

## Scheduling

### Recommended Schedule

| Agent | Frequency | Trigger |
|-------|-----------|---------|
| **Signal Monitor** | Every **3 hours** | Autonomous monitor |
| **Reddit Check** | Every **6 hours** | (within signal monitor) |
| **RSS/News Check** | Every **30 minutes** | (within signal monitor) |
| **Deal Verification** | On-demand | When signal confidence >70% |

### Add to Autonomous Monitor

```python
# autonomous_monitor.py

def __init__(self):
    # ... existing ...
    self.signal_monitor_interval = 10800  # 3 hours
    self.last_signal_monitor_run = None

def should_run_signal_monitor(self) -> bool:
    if not self.last_signal_monitor_run:
        return True

    elapsed = (datetime.now() - self.last_signal_monitor_run).total_seconds()
    return elapsed >= self.signal_monitor_interval

def run(self):
    while self.running:
        # Run orchestrator every 1 hour
        if self.should_run_orchestrator():
            self.run_orchestrator()

        # Run signal monitor every 3 hours
        if self.should_run_signal_monitor():
            self.run_signal_monitor()

        # Run SEC monitor every 15 min
        self.run_sec_monitor()
```

---

## Testing

### Test Signal Monitor

```bash
# Test on specific ticker
python3 signal_monitor_agent.py --ticker CCCX

# Test on all SPACs
python3 signal_monitor_agent.py --reddit-days 7 --news-days 3
```

### Expected Output

```
================================================================================
SIGNAL MONITOR AGENT
================================================================================

Monitoring 185 searching SPACs
  Reddit lookback: 7 days
  News lookback: 3 days

[CCCX] Checking signals...
  Reddit: 12 mentions, bullish sentiment, confidence=65%
  News: 2 articles, confidence=85%
  ⚠️  TRIGGER: HIGH priority
     Reason: Signals from both Reddit and News
     Actions: deal_detector

================================================================================
SUMMARY: 1 orchestrator trigger(s)
================================================================================
```

---

## Benefits

### 1. Early Detection
- News often beats SEC filings by hours
- Reddit can detect "leaks" before official announcements
- Gain **hours to days** of advance notice

### 2. Market Sentiment
- Track bullish/bearish sentiment shifts
- Detect deal speculation before confirmation
- Monitor community confidence levels

### 3. Multiple Confirmation
- News + Reddit + SEC = high confidence
- Single source = lower confidence, verify
- Cross-validation reduces false positives

### 4. Immediate Alerts
- Telegram notifications for HIGH/CRITICAL signals
- User gets real-time deal leak alerts
- Can act on information immediately

---

## RSS vs NewsAPI Comparison

| Feature | NewsAPI | Google News RSS | PR Newswire RSS |
|---------|---------|----------------|-----------------|
| **Cost** | Free (500/day) | FREE (unlimited) | FREE (unlimited) |
| **Latency** | ~1 hour | < 1 minute | Real-time |
| **Coverage** | Good | Excellent | Official only |
| **Rate Limit** | 500 requests/day | None | None |
| **API Key** | Required | Not needed | Not needed |
| **Best For** | Backup source | Primary monitor | Press releases |

**Recommendation:** Use RSS as primary, NewsAPI as backup

---

## Next Steps

### Phase 1: Current (Done)
- ✅ Created signal_monitor_agent.py
- ✅ Integrated with orchestrator
- ✅ Telegram alerts for HIGH/CRITICAL
- ✅ Confidence-based triggering

### Phase 2: RSS Integration (Recommended)
- [ ] Create rss_news_monitor.py
- [ ] Add Google News RSS feeds
- [ ] Add PR Newswire RSS
- [ ] Add Yahoo Finance RSS
- [ ] Test real-time detection

### Phase 3: Enhanced Monitoring
- [ ] Add Twitter/X monitoring (if API access)
- [ ] Add Bloomberg terminal RSS (if available)
- [ ] Add Seeking Alpha RSS
- [ ] Machine learning for pattern detection

---

## Configuration

### Enable Signal Monitoring

**Add to .env:**
```
# Reddit API (for sentiment tracking)
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_secret
REDDIT_USER_AGENT=LEVP SPAC Platform

# NewsAPI (backup to RSS)
NEWS_API_KEY=your_key  # Optional

# Telegram (for alerts)
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Schedule in Autonomous Monitor

**Current schedule:**
- Orchestrator: Every 1 hour
- SEC monitor: Every 15 minutes

**Add signal monitor:**
- Signal monitor: Every 3 hours
  - Reddit check: Included
  - RSS/News check: Included

---

## Summary

**Problem:** Missing early deal signals from news and social media

**Solution:** Multi-source signal detection with confidence-based triggering

**Result:**
- ✅ Real-time Telegram alerts for potential deals
- ✅ Orchestrator verification via SEC 8-Ks
- ✅ Early detection (hours to days ahead of SEC)
- ✅ Cross-validation (Reddit + News + SEC)

**Status:** Ready to deploy with RSS integration recommended

---

**Run:** `python3 signal_monitor_agent.py`
**Integrate:** Added to orchestrator as new agent
**Schedule:** Every 3 hours via autonomous monitor
