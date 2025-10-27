# Premium News RSS Feeds for SPAC Monitoring

**Date:** October 9, 2025

---

## Overview

Premium news sources (WSJ, NYT, Bloomberg, etc.) offer RSS feeds that provide:
- Earlier coverage than free sources
- More detailed deal analysis
- Exclusive scoops and insider information
- Better quality/credibility

**Note:** Subscription may be required to view full articles, but RSS feeds are often accessible even without subscription (headlines + summaries visible).

---

## Wall Street Journal (WSJ)

### SPAC-Relevant RSS Feeds

**Markets & Finance:**
```
https://feeds.a.dj.com/rss/RSSMarketsMain.xml
https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml
```

**Deals & Deal Makers:**
```
https://feeds.a.dj.com/rss/RSSWSJD.xml  # WSJ Deals section
```

**All Business News:**
```
https://feeds.a.dj.com/rss/RSSWorldNews.xml
```

**Search-Based RSS (Custom Queries):**
WSJ provides search-based RSS for specific topics:
```
https://www.wsj.com/search?query=SPAC&min-date=YYYY-MM-DD&max-date=YYYY-MM-DD&sort=date-desc&source=wsjarticle

# Example for SPAC deals:
https://www.wsj.com/search?query=SPAC+merger&sort=date-desc&source=wsjarticle
```

**Pros:**
- High credibility (tier-1 source)
- Often breaks SPAC deals first
- Detailed financial analysis
- RSS feeds update in real-time

**Cons:**
- Full article requires subscription ($40/month)
- RSS shows headlines + first paragraph only

**How to Use:**
1. RSS feed shows headline + summary (FREE)
2. If deal keywords detected → trigger AI verification
3. If AI confirms → send alert + link to article
4. User can read full article with subscription

---

## New York Times (NYT)

### Business RSS Feeds

**All Business News:**
```
https://rss.nytimes.com/services/xml/rss/nyt/Business.xml
https://rss.nytimes.com/services/xml/rss/nyt/DealBook.xml  # M&A focus
```

**Markets:**
```
https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml
```

**Pros:**
- Comprehensive business coverage
- DealBook newsletter covers SPACs occasionally
- RSS feeds are well-maintained

**Cons:**
- Less SPAC-focused than WSJ
- Paywall for full articles

---

## Bloomberg

### RSS Feeds

**Note:** Bloomberg discontinued most RSS feeds in 2019, but some still work:

```
https://www.bloomberg.com/feed/podcast/masters-in-business.xml
```

**Alternative:** Bloomberg Terminal has RSS feeds, but requires expensive subscription ($20,000+/year)

**Better Option:** Use Bloomberg's free web search:
```
https://www.bloomberg.com/search?query=SPAC+merger
```

**Pros:**
- Most authoritative financial news
- Real-time market data
- Often first to report major deals

**Cons:**
- RSS feeds mostly discontinued
- Full access requires expensive subscription
- Better suited for web scraping (if allowed by ToS)

---

## Financial Times (FT)

### RSS Feeds

**Companies & Markets:**
```
https://www.ft.com/companies?format=rss
https://www.ft.com/markets?format=rss
```

**M&A:**
```
https://www.ft.com/mergers-acquisitions?format=rss
```

**Pros:**
- Strong M&A coverage
- International perspective
- Well-maintained RSS feeds

**Cons:**
- Paywall ($75/month)
- Less US SPAC focus than WSJ

---

## Reuters

### RSS Feeds (FREE)

**All Business:**
```
https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best
```

**Deals:**
```
https://www.reuters.com/business/deals/
# Note: Direct RSS discontinued, but can parse from page
```

**Pros:**
- FREE (no subscription required)
- Fast, reliable
- Wire service = often first to report

**Cons:**
- RSS feeds less consistent than before
- May need to scrape website directly

---

## Barron's

### RSS Feeds

**All Articles:**
```
https://www.barrons.com/feed/rss/
```

**Market Data:**
```
https://www.barrons.com/market-data?mod=BOL_TOPNAV
```

**Pros:**
- Strong SPAC coverage
- Investment analysis focus
- Part of WSJ (Dow Jones)

**Cons:**
- Subscription required ($30/month)
- Less frequent updates than WSJ

---

## Seeking Alpha

### RSS Feeds (FREE + Premium)

**SPAC News:**
```
https://seekingalpha.com/market-news/spacs.xml
https://seekingalpha.com/tag/spacs.xml
```

**All Market News:**
```
https://seekingalpha.com/market_currents.xml
```

**Pros:**
- FREE RSS feeds
- Strong SPAC community
- Real-time news + analysis
- User comments provide sentiment

**Cons:**
- Mix of professional + amateur analysis
- Some premium articles require subscription

---

## How to Use Premium RSS Feeds

### 1. RSS Feed Access (No Subscription Needed)

**What you get:**
- Headlines (full text)
- First paragraph / summary
- Publication timestamp
- Article URL

**What you DON'T get:**
- Full article body (requires subscription)

**Strategy:**
```python
# RSS feed provides enough for detection:
article = {
    'title': 'SPAC XYZ Announces $2B Merger with TechCorp',
    'summary': 'Special purpose acquisition company XYZ Corp said Monday it reached a definitive agreement to merge with...',
    'url': 'https://wsj.com/articles/...',
    'published': '2025-10-09T08:30:00Z'
}

# AI can analyze title + summary to detect deal
verification = verify_deal_news_with_ai(ticker, article)

# If confirmed deal:
if verification['is_deal_announcement']:
    send_telegram_alert(f"🚨 WSJ: {article['title']}\n\nRead: {article['url']}")
    # User clicks link, logs in with subscription, reads full article
```

### 2. Subscription Required for Full Text

**If you have subscriptions:**
- WSJ: $40/month
- NYT: $25/month
- FT: $75/month
- Barron's: $30/month

**What changes:**
- You can read full articles after RSS alert
- More credibility when verifying deals
- Better context for investment decisions

**No changes to RSS monitoring:**
- RSS feeds work the same way (headline + summary)
- Subscription only needed for clicking through to full article

---

## Implementation in RSS Monitor

### Adding Premium Feeds

Edit `rss_news_monitor.py`:

```python
self.feeds = {
    # Free feeds (existing)
    'google_spac_deals': 'https://news.google.com/rss/search?q=SPAC+%22definitive+agreement%22',
    'pr_newswire_ma': 'https://www.prnewswire.com/rss/mergers-and-acquisitions.rss',

    # Premium feeds (NEW)
    'wsj_markets': 'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',
    'wsj_deals': 'https://feeds.a.dj.com/rss/RSSWSJD.xml',
    'nyt_business': 'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml',
    'nyt_dealbook': 'https://rss.nytimes.com/services/xml/rss/nyt/DealBook.xml',
    'ft_companies': 'https://www.ft.com/companies?format=rss',
    'barrons': 'https://www.barrons.com/feed/rss/',
    'seeking_alpha_spacs': 'https://seekingalpha.com/market-news/spacs.xml'
}
```

### Feed Priority

When multiple sources report same news:

**Tier 1 (Highest Credibility):**
- WSJ, Bloomberg, Financial Times
- Use for CRITICAL alerts
- AI confidence +20% if from tier 1

**Tier 2 (High Credibility):**
- NYT, Reuters, Barron's
- Use for HIGH alerts
- AI confidence +10% if from tier 2

**Tier 3 (Moderate Credibility):**
- Seeking Alpha, Yahoo Finance
- Use for MEDIUM alerts
- Standard confidence calculation

```python
def adjust_confidence_by_source(self, base_confidence: int, source: str) -> int:
    """Adjust confidence based on source credibility"""
    tier_1_sources = ['wsj', 'bloomberg', 'ft']
    tier_2_sources = ['nyt', 'reuters', 'barrons']

    source_lower = source.lower()

    if any(t1 in source_lower for t1 in tier_1_sources):
        return min(base_confidence + 20, 100)
    elif any(t2 in source_lower for t2 in tier_2_sources):
        return min(base_confidence + 10, 100)
    else:
        return base_confidence
```

---

## RSS Feed Monitoring Strategy

### Optimal Setup

**Every 15 minutes:**
- Poll WSJ, NYT, FT feeds (premium)
- Poll Google News, PR Newswire (free)
- Check for deal keywords

**When deal keywords found:**
1. Filter duplicates (signal_tracker.py)
2. AI verification (verify_deal_news_with_ai)
3. Adjust confidence by source tier
4. If confidence >70% → Telegram alert

**Alert includes:**
- Source (e.g., "WSJ", "NYT")
- Headline
- AI verification summary
- Link to full article (requires subscription)

### Example Alert

```
🚨 TIER 1 SOURCE - CRITICAL

Source: Wall Street Journal
Ticker: $CCCX
Headline: "CCCX Reaches $3B Deal to Merge with AI Startup"

AI Verification:
✅ Deal Stage: Definitive Agreement
✅ Target: TechCorp AI Inc.
✅ Confidence: 95%

Read full article (WSJ subscription):
https://www.wsj.com/articles/...

Actions: Checking SEC 8-K for confirmation
```

---

## Cost-Benefit Analysis

### Free RSS Feeds Only

**Cost:** $0/month

**Coverage:**
- Google News (aggregates 1000s of sources)
- PR Newswire (official press releases)
- Yahoo Finance
- Seeking Alpha (free tier)

**Latency:** ~30 minutes after official announcement

**Sufficient for:** Most SPAC monitoring needs

### Adding WSJ Subscription

**Cost:** $40/month

**Additional Value:**
- 15-30 minutes faster than free sources
- Exclusive scoops (rumors before official announcement)
- Higher credibility (tier 1 source)
- Detailed deal analysis

**ROI:** If you catch ONE deal 30 minutes early with 10% premium, that's worth $1000+ on a $10k position

### Full Premium Suite

**Cost:** ~$170/month (WSJ + NYT + FT + Barron's)

**Additional Value:**
- Maximum coverage (tier 1 sources)
- International deals (FT)
- Multiple perspectives
- Redundancy (if one source down)

**ROI:** For serious SPAC investors managing $100k+ portfolios

---

## Recommended Setup

### Minimum (Free)

```python
feeds = {
    'google_news': 'https://news.google.com/rss/search?q=SPAC+merger',
    'pr_newswire': 'https://www.prnewswire.com/rss/mergers-and-acquisitions.rss',
    'seeking_alpha': 'https://seekingalpha.com/market-news/spacs.xml'
}
```

**Poll every:** 15 minutes

### Standard (WSJ Subscription)

```python
feeds = {
    # Free
    'google_news': '...',
    'pr_newswire': '...',
    'seeking_alpha': '...',

    # Premium
    'wsj_markets': 'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',
    'wsj_deals': 'https://feeds.a.dj.com/rss/RSSWSJD.xml'
}
```

**Poll every:** 15 minutes (more valuable with WSJ)

### Maximum (All Subscriptions)

```python
feeds = {
    # All free + all premium sources
    # Total: 8-10 feeds
}
```

**Poll every:** 10 minutes (high-frequency trading setup)

---

## Testing Premium Feeds

```bash
# Test if WSJ RSS is accessible
python3 -c "
import feedparser
feed = feedparser.parse('https://feeds.a.dj.com/rss/RSSMarketsMain.xml')
print(f'WSJ Feed: {len(feed.entries)} articles')
for entry in feed.entries[:3]:
    print(f'  - {entry.title}')
"

# Test NYT
python3 -c "
import feedparser
feed = feedparser.parse('https://rss.nytimes.com/services/xml/rss/nyt/Business.xml')
print(f'NYT Feed: {len(feed.entries)} articles')
"

# Test Seeking Alpha (free)
python3 -c "
import feedparser
feed = feedparser.parse('https://seekingalpha.com/market-news/spacs.xml')
print(f'Seeking Alpha: {len(feed.entries)} articles')
"
```

---

## Summary

**Question:** Do WSJ, NYT, etc. have RSS feeds we can use?

**Answer:** YES

**What you get without subscription:**
- ✅ RSS feed access (headlines + summaries)
- ✅ Publication timestamps
- ✅ Article URLs
- ✅ Enough information for AI to detect deals

**What you need subscription for:**
- ❌ Full article text
- ❌ Detailed analysis
- ❌ Premium content

**Recommendation:**
1. **Start with free feeds** (Google News, PR Newswire, Seeking Alpha)
2. **Add WSJ ($40/month)** if managing $50k+ portfolio
3. **Add NYT + FT** if managing $200k+ portfolio

**Key insight:** RSS feeds give you the ALERT for free. Subscription gives you the DETAILS after the alert.

---

**Implementation:** Add premium feeds to `rss_news_monitor.py` → Poll every 15 min → AI verifies → Telegram alert with link → User reads full article with subscription
