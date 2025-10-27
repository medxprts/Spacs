# Retail Sentiment Tracking Strategy
## Tracking WSB, Reddit, Twitter for SPAC Retail Interest

---

## Overview
Track retail investor sentiment and mentions across social media to gauge retail interest in pre-deal SPACs. High retail interest often correlates with premium expansion and increased volatility.

---

## Data Sources (in priority order)

### 1. **Reddit API** (Best for SPACs)
**Subreddits to Monitor**:
- r/SPACs (most relevant - SPAC-focused community)
- r/wallstreetbets (high volume, meme potential)
- r/stocks (general retail sentiment)
- r/investing (more conservative crowd)
- r/SecurityAnalysis (institutional-leaning but relevant)

**What to Track**:
- Post mentions of ticker
- Comment mentions
- Upvotes/awards (engagement proxy)
- Post sentiment (bullish/bearish)
- Unique authors (breadth of interest)

**API**: Reddit API (free, 60 requests/min)
**Cost**: Free

---

### 2. **Twitter/X API** (Real-time sentiment)
**What to Track**:
- Tweet volume mentioning ticker
- Influencer mentions (accounts with >10k followers)
- Sentiment (bullish/bearish/neutral)
- Retweets/likes (virality)

**API**: Twitter API v2 (Free tier: 1,500 tweets/month)
**Cost**: Free tier sufficient for daily checks

---

### 3. **StockTwits** (Retail-focused)
**What to Track**:
- Message volume
- Bullish vs Bearish indicator
- Trending status
- Watchlist adds

**API**: StockTwits API (free)
**Cost**: Free

---

### 4. **Google Trends** (Search interest)
**What to Track**:
- Search volume for ticker
- Related queries
- Geographic interest

**API**: Google Trends API (unofficial but works)
**Cost**: Free

---

## Database Schema Enhancement

### New Fields for SPAC Table

```python
# Add to database.py
class SPAC(Base):
    # ... existing fields ...

    # Retail Sentiment
    reddit_mentions_7d = Column(Integer)           # Mentions last 7 days
    reddit_mentions_30d = Column(Integer)          # Mentions last 30 days
    reddit_sentiment_score = Column(Float)         # -1 to +1 (bearish to bullish)
    reddit_engagement_score = Column(Float)        # Upvotes + awards normalized
    twitter_mentions_7d = Column(Integer)
    twitter_sentiment_score = Column(Float)
    stocktwits_messages_7d = Column(Integer)
    stocktwits_bullish_pct = Column(Float)        # % bullish messages
    google_trends_score = Column(Float)            # 0-100 search interest
    retail_interest_rank = Column(Integer)         # Overall rank (1 = most interest)
    retail_last_updated = Column(DateTime)
```

---

## Implementation Architecture

### File Structure
```
retail_sentiment/
├── reddit_scraper.py           # Reddit API integration
├── twitter_scraper.py          # Twitter API integration
├── stocktwits_scraper.py       # StockTwits API
├── google_trends_scraper.py    # Google Trends
├── sentiment_analyzer.py       # AI-powered sentiment analysis
└── retail_sentiment_aggregator.py  # Combines all sources
```

---

## Detailed Implementation

### 1. Reddit Scraper (`reddit_scraper.py`)

```python
import praw  # Python Reddit API Wrapper
from datetime import datetime, timedelta

class RedditScraper:
    def __init__(self):
        # Setup Reddit API client
        self.reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent="SPAC Sentiment Tracker 1.0"
        )

        self.subreddits = ['SPACs', 'wallstreetbets', 'stocks']

    def get_ticker_mentions(self, ticker: str, days_back: int = 7) -> Dict:
        """Get Reddit mentions for a ticker"""
        mentions = []
        cutoff = datetime.now() - timedelta(days=days_back)

        for subreddit_name in self.subreddits:
            subreddit = self.reddit.subreddit(subreddit_name)

            # Search for ticker mentions
            for post in subreddit.search(f"${ticker} OR {ticker}", time_filter='week', limit=100):
                post_time = datetime.fromtimestamp(post.created_utc)
                if post_time >= cutoff:
                    mentions.append({
                        'title': post.title,
                        'text': post.selftext,
                        'score': post.score,
                        'num_comments': post.num_comments,
                        'created': post_time,
                        'subreddit': subreddit_name,
                        'url': f"https://reddit.com{post.permalink}"
                    })

        return {
            'mention_count': len(mentions),
            'total_upvotes': sum(m['score'] for m in mentions),
            'total_comments': sum(m['num_comments'] for m in mentions),
            'mentions': mentions
        }

    def calculate_sentiment(self, mentions: List[Dict]) -> float:
        """Calculate sentiment score using AI"""
        if not mentions or not AI_AVAILABLE:
            return 0.0

        # Combine top 5 most upvoted posts
        top_posts = sorted(mentions, key=lambda x: x['score'], reverse=True)[:5]

        combined_text = "\n\n".join([
            f"{m['title']}\n{m['text'][:500]}"
            for m in top_posts
        ])

        prompt = f"""Analyze sentiment toward stock ticker from these Reddit posts. Return JSON with:
- sentiment: "bullish", "bearish", or "neutral"
- score: -1.0 to +1.0 (bearish to bullish)
- reasoning: Brief explanation

Posts:
{combined_text}

Return JSON only:"""

        response = AI_CLIENT.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=150
        )

        result = json.loads(response.choices[0].message.content)
        return result['score']
```

**Key Metrics**:
- **Mentions**: Raw count of posts/comments mentioning ticker
- **Engagement**: Upvotes + comments (shows real interest vs spam)
- **Sentiment**: AI-analyzed bullish/bearish/neutral
- **Velocity**: Change in mentions week-over-week

---

### 2. Sentiment Aggregator (`retail_sentiment_aggregator.py`)

```python
class RetailSentimentAggregator:
    """Combines all retail sentiment sources into single score"""

    def calculate_retail_interest_score(self, spac: SPAC) -> float:
        """
        Calculate overall retail interest score (0-100)

        Weighted average of:
        - Reddit mentions (40%)
        - Reddit engagement (20%)
        - Twitter mentions (20%)
        - StockTwits volume (10%)
        - Google Trends (10%)
        """

        scores = []

        # Reddit score (40% weight)
        if spac.reddit_mentions_7d:
            # Normalize to 0-100 (assume max 1000 mentions/week is 100)
            reddit_score = min(100, (spac.reddit_mentions_7d / 1000) * 100)
            scores.append(('reddit', reddit_score, 0.4))

        # Reddit engagement (20% weight)
        if spac.reddit_engagement_score:
            scores.append(('engagement', spac.reddit_engagement_score, 0.2))

        # Twitter (20% weight)
        if spac.twitter_mentions_7d:
            twitter_score = min(100, (spac.twitter_mentions_7d / 500) * 100)
            scores.append(('twitter', twitter_score, 0.2))

        # StockTwits (10% weight)
        if spac.stocktwits_messages_7d:
            st_score = min(100, (spac.stocktwits_messages_7d / 200) * 100)
            scores.append(('stocktwits', st_score, 0.1))

        # Google Trends (10% weight)
        if spac.google_trends_score:
            scores.append(('trends', spac.google_trends_score, 0.1))

        if not scores:
            return 0.0

        # Calculate weighted average
        total_weight = sum(weight for _, _, weight in scores)
        weighted_sum = sum(score * weight for _, score, weight in scores)

        return weighted_sum / total_weight

    def rank_spacs_by_retail_interest(self) -> List[Tuple[str, float]]:
        """Rank all pre-deal SPACs by retail interest"""
        db = SessionLocal()

        spacs = db.query(SPAC).filter(
            SPAC.deal_status == 'SEARCHING'
        ).all()

        ranked = []
        for spac in spacs:
            score = self.calculate_retail_interest_score(spac)
            if score > 0:
                ranked.append((spac.ticker, score))

        # Sort by score descending
        ranked.sort(key=lambda x: x[1], reverse=True)

        # Update ranks in database
        for rank, (ticker, score) in enumerate(ranked, 1):
            db.query(SPAC).filter(SPAC.ticker == ticker).update({
                'retail_interest_rank': rank
            })

        db.commit()
        db.close()

        return ranked
```

---

## Display in Streamlit Dashboard

### New Tab: "🔥 Retail Buzz"

```python
elif page == "🔥 Retail Buzz":
    st.title("🔥 Retail Interest Tracker")

    # Top metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        top_spac = df_predeal.sort_values('retail_interest_rank').iloc[0]
        st.metric("🏆 Most Discussed", top_spac['ticker'])
    with col2:
        avg_mentions = df_predeal['reddit_mentions_7d'].mean()
        st.metric("Avg Reddit Mentions", f"{int(avg_mentions)}/week")
    with col3:
        trending = len(df_predeal[df_predeal['reddit_mentions_7d'] > 50])
        st.metric("Trending SPACs (>50 mentions)", trending)
    with col4:
        bullish = len(df_predeal[df_predeal['reddit_sentiment_score'] > 0.3])
        st.metric("Bullish Sentiment", bullish)

    # Retail Interest Leaderboard
    st.markdown("### 📊 Retail Interest Leaderboard")

    retail_df = df_predeal[df_predeal['retail_interest_rank'].notna()].copy()
    retail_df = retail_df.sort_values('retail_interest_rank')

    display_cols = ['ticker', 'company', 'premium', 'reddit_mentions_7d',
                    'reddit_sentiment_score', 'twitter_mentions_7d',
                    'retail_interest_rank', 'notes']

    st.dataframe(
        retail_df[display_cols],
        column_config={
            'ticker': 'Ticker',
            'reddit_mentions_7d': st.column_config.NumberColumn('Reddit (7d)', format="%d"),
            'reddit_sentiment_score': st.column_config.NumberColumn('Sentiment', format="%.2f"),
            'twitter_mentions_7d': st.column_config.NumberColumn('Twitter (7d)', format="%d"),
            'retail_interest_rank': st.column_config.NumberColumn('Rank', format="#%d")
        }
    )

    # Sentiment Distribution
    st.markdown("### 📈 Sentiment Distribution")
    fig = px.scatter(retail_df, x='premium', y='reddit_sentiment_score',
                     size='reddit_mentions_7d', hover_name='ticker',
                     labels={'premium': 'Premium %', 'reddit_sentiment_score': 'Sentiment Score'},
                     title='Premium vs Reddit Sentiment')
    st.plotly_chart(fig)
```

---

## Automation & Scheduling

### Daily Cron Job (3 times/day to catch trends)

```bash
# Morning (before market open)
0 8 * * * python3 retail_sentiment_aggregator.py --commit

# Mid-day check
0 12 * * * python3 retail_sentiment_aggregator.py --commit

# Evening recap
0 18 * * * python3 retail_sentiment_aggregator.py --commit
```

---

## Cost Analysis

### API Costs (Monthly)

| Service | Tier | Cost | Calls/Month |
|---------|------|------|-------------|
| Reddit API | Free | $0 | Unlimited (rate-limited) |
| Twitter API v2 | Free | $0 | 1,500 tweets/month |
| StockTwits | Free | $0 | Unlimited |
| Google Trends | Free | $0 | Unofficial API |
| DeepSeek AI (sentiment) | Paid | **$2-5** | ~500 analyses/month |

**Total Monthly Cost**: **$2-5** (AI sentiment analysis only)

---

## Key Benefits

1. **Early Signal**: Detect retail interest before premium spikes
2. **Risk Warning**: High retail = volatility risk
3. **Opportunity**: Low premium + high retail = potential play
4. **Meme Detection**: Identify WSB-driven pumps early

---

## Example Use Cases

### Use Case 1: Early Retail Interest Detection
```
RTAC shows:
- Reddit mentions: 150/week (up from 20)
- Sentiment: +0.7 (bullish)
- Premium: 9.8%
→ Signal: Retail interest building, watch for premium expansion
```

### Use Case 2: Meme SPAC Warning
```
HOND shows:
- Reddit mentions: 500/week
- WSB mentions: 80% of total
- Sentiment: +0.9 (extreme bullish)
- Premium: 69.5%
→ Signal: Meme stock risk, avoid or take profits
```

### Use Case 3: Undervalued + Retail Buzz
```
GSRT shows:
- Reddit mentions: 100/week
- Sentiment: +0.5 (moderately bullish)
- Premium: 26.2%
- Deal value: $475M (reasonable)
→ Signal: Organic retail interest in quality deal
```

---

## Implementation Priority

### Phase 1 (Week 1): Reddit Integration
1. Setup Reddit API credentials
2. Build `reddit_scraper.py`
3. Add Reddit fields to database
4. Test on 5 SPACs
5. Add "Retail Buzz" tab to Streamlit

### Phase 2 (Week 2): Sentiment Analysis
1. Integrate DeepSeek AI for sentiment
2. Build sentiment aggregator
3. Create retail interest ranking
4. Add charts to dashboard

### Phase 3 (Week 3): Multi-source Integration
1. Add Twitter API
2. Add StockTwits
3. Add Google Trends
4. Combine into weighted score

### Phase 4 (Week 4): Automation
1. Setup 3x daily cron jobs
2. Add historical tracking (trends over time)
3. Create alerts for sudden spikes

---

## Sample Output

```
RETAIL SENTIMENT REPORT - 2025-10-07
====================================

TOP 5 RETAIL BUZZ:
1. RTAC  - Score: 87/100 (Reddit: 150, Twitter: 89, Sentiment: +0.7)
2. HOND  - Score: 82/100 (Reddit: 120, Twitter: 76, Sentiment: +0.9)
3. CEP   - Score: 75/100 (Reddit: 98,  Twitter: 45, Sentiment: +0.6)
4. GSRT  - Score: 68/100 (Reddit: 85,  Twitter: 34, Sentiment: +0.5)
5. WLAC  - Score: 61/100 (Reddit: 72,  Twitter: 28, Sentiment: +0.4)

TREND ALERTS:
⚠️  RTAC mentions up 650% week-over-week (20 → 150)
⚠️  HOND reached r/wallstreetbets front page (8,500 upvotes)
✅  CEP steady growth (Bitcoin/crypto narrative gaining traction)
```

---

Would you like me to start building the Reddit scraper first, or would you prefer to test the current deal data collection system we just built?
