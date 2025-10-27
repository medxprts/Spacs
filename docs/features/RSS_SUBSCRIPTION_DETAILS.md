# RSS Feeds - What's Included in Subscriptions

**TL;DR:** RSS feeds are **FREE to access** (even without subscription), but **full article content** requires subscription.

---

## What You Get Without Subscription

### RSS Feed Access (100% FREE)

**All these work WITHOUT paying:**
- ✅ RSS feed URLs (can be polled anytime)
- ✅ Article headlines (full text)
- ✅ First 1-2 paragraphs (summary)
- ✅ Publication timestamp
- ✅ Article URL/link
- ✅ Author (sometimes)

**Example RSS entry (NO subscription needed):**
```xml
<item>
  <title>SPAC XYZ Announces $3B Merger with TechCorp</title>
  <description>
    Special purpose acquisition company XYZ Corp said Monday it reached
    a definitive agreement to merge with TechCorp in a deal valued at
    $3 billion. The transaction is expected to close in Q2 2026...
  </description>
  <link>https://www.wsj.com/articles/spac-xyz-merger-techcorp-12345</link>
  <pubDate>Mon, 09 Oct 2025 08:32:00 EST</pubDate>
</item>
```

**What you can do with this (no subscription):**
1. ✅ Detect deal announcement (headline says "merger")
2. ✅ Extract ticker ($XYZ)
3. ✅ Extract target (TechCorp)
4. ✅ Extract deal value ($3B)
5. ✅ Extract expected close (Q2 2026)
6. ✅ Run AI verification on summary
7. ✅ Send Telegram alert
8. ✅ Timestamp the alert

**What you CAN'T do:**
- ❌ Read the full article (need subscription)
- ❌ Get detailed analysis from the article
- ❌ See charts/graphs in article

---

## What You Get With Subscription

### WSJ Digital Subscription ($40/month)

**RSS feed access:** Same as free (no change)

**NEW with subscription:**
- ✅ Click article link → full article text
- ✅ Detailed deal analysis
- ✅ Management quotes
- ✅ Banker commentary
- ✅ Financial projections
- ✅ Historical context

**Example full article content (requires subscription):**
```
[Full WSJ Article - requires login]

SPAC XYZ Announces $3B Merger with TechCorp
By Jane Reporter

Special purpose acquisition company XYZ Corp said Monday it reached
a definitive agreement to merge with TechCorp in a deal valued at
$3 billion, marking one of the largest SPAC deals of 2025.

[... 15 more paragraphs of detailed analysis ...]

The deal values TechCorp at 12x forward revenue, a premium to...
[... financial details ...]

Goldman Sachs and Morgan Stanley are acting as advisors...
[... more details ...]

[Charts, tables, analyst commentary, etc.]
```

### NYT Digital Subscription ($25/month)

**RSS feed access:** Same as free

**NEW with subscription:**
- ✅ Full article access
- ✅ DealBook analysis
- ✅ Opinion pieces
- ✅ Longer investigative pieces

### Financial Times ($75/month)

**RSS feed access:** Same as free

**NEW with subscription:**
- ✅ Full article access
- ✅ Lex column analysis
- ✅ International coverage
- ✅ FT Alphaville blog

---

## For SPAC Monitoring: Do You Need Subscriptions?

### RSS Summaries Are Usually Enough

**For deal detection, RSS summaries (FREE) provide:**

✅ **Headline:** "SPAC XYZ Announces Merger with TechCorp"
- Tells you: deal announced
- Ticker: XYZ
- Target: TechCorp

✅ **First 1-2 paragraphs:**
- Deal value: $3 billion
- Deal type: "definitive agreement" (binding)
- Expected close: Q2 2026
- Key terms: "$10/share redemption"

✅ **Enough for AI verification:**
```python
# AI can verify from summary alone:
verification = verify_deal_news_with_ai(ticker, {
    'title': 'SPAC XYZ Announces Merger with TechCorp',
    'description': 'XYZ reached definitive agreement to merge...'
})

# Result:
{
  'is_deal_announcement': True,
  'deal_stage': 'definitive_agreement',
  'target_name': 'TechCorp',
  'confidence': 95
}

# No subscription needed!
```

✅ **Enough for Telegram alert:**
```
🚨 DEAL DETECTED

Ticker: $XYZ
Source: WSJ (Tier 1)
Target: TechCorp
Deal Value: $3B
Status: Definitive Agreement

Link: https://wsj.com/... (subscription required for full article)

Action: Monitoring SEC for 8-K confirmation
```

### When You MIGHT Want Subscription

**Scenario 1: Deep Due Diligence**
- Reading full article for investment decision
- Understanding management's rationale
- Analyzing financial projections
- Comparing to similar deals

**Scenario 2: Complex Deals**
- PIPE details (Private Investment in Public Equity)
- Earnout structures
- Sponsor economics
- Valuation methodology

**Scenario 3: Professional Research**
- Writing investment memos
- Client reporting
- Competitive analysis

---

## Recommendation by Portfolio Size

### Managing <$50k: Free RSS Only

**Use:**
- Google News RSS (free)
- PR Newswire RSS (free)
- Seeking Alpha RSS (free)

**Why:**
- Headlines + summaries are enough for deal detection
- Can verify via SEC 8-K (free) for full details
- $40/month subscription not worth it for small portfolio

**Setup:**
```python
feeds = {
    'google_news': 'https://news.google.com/rss/search?q=SPAC+merger',
    'pr_newswire': 'https://www.prnewswire.com/rss/mergers-and-acquisitions.rss',
    'seeking_alpha': 'https://seekingalpha.com/market-news/spacs.xml'
}
```

### Managing $50k-$200k: Add WSJ ($40/month)

**Use:**
- All free feeds (above)
- + WSJ RSS feeds

**Why:**
- WSJ breaks deals 15-30 min faster than free sources
- Tier 1 credibility (AI confidence bonus)
- Full articles useful for bigger positions
- ROI: Catching ONE deal 30 min early = easily worth $40

**Setup:**
```python
feeds = {
    # Free
    'google_news': '...',
    'pr_newswire': '...',
    'seeking_alpha': '...',

    # WSJ (Tier 1)
    'wsj_markets': 'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',
    'wsj_deals': 'https://feeds.a.dj.com/rss/RSSWSJD.xml'
}
```

### Managing $200k+: Full Suite ($170/month)

**Use:**
- All free feeds
- + WSJ ($40/month)
- + NYT ($25/month)
- + FT ($75/month)
- + Barron's ($30/month)

**Why:**
- Maximum coverage (multiple tier 1 sources)
- Redundancy (if one source down)
- International deals (FT)
- Different perspectives
- Professional research capability

**Setup:**
```python
feeds = {
    # Free
    'google_news': '...',
    'pr_newswire': '...',
    'seeking_alpha': '...',

    # Tier 1
    'wsj_markets': '...',
    'wsj_deals': '...',
    'ft_companies': 'https://www.ft.com/companies?format=rss',

    # Tier 2
    'nyt_business': 'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml',
    'nyt_dealbook': 'https://rss.nytimes.com/services/xml/rss/nyt/DealBook.xml',
    'barrons': 'https://www.barrons.com/feed/rss/'
}
```

---

## What About Paywalled Content?

### Some RSS Feeds Show Full Text (Rare)

**Sources that sometimes include full text in RSS:**
- Seeking Alpha (free tier articles)
- Some business wire releases
- Company press releases (always free)

**Sources that only show summaries in RSS:**
- WSJ (1-2 paragraphs max)
- NYT (1-2 paragraphs max)
- FT (1 paragraph max)
- Barron's (summary only)

### How to Tell if RSS Has Full Text

Check the RSS entry:
```xml
<!-- Summary only (subscription needed for full) -->
<description>
  First paragraph here... [Read more at WSJ.com - subscription required]
</description>

<!-- Full text included (rare) -->
<content:encoded>
  <![CDATA[
    Full article text here... [entire article]
  ]]>
</content:encoded>
```

Most premium sources (WSJ, NYT, FT) only include summaries in RSS.

---

## Testing RSS Feeds (No Subscription)

### Test WSJ RSS (Free Access)

```bash
python3 << 'EOF'
import feedparser

feed = feedparser.parse('https://feeds.a.dj.com/rss/RSSMarketsMain.xml')

print(f"WSJ RSS Feed: {len(feed.entries)} articles\n")

for entry in feed.entries[:3]:
    print(f"Title: {entry.title}")
    print(f"Summary: {entry.summary[:200]}...")
    print(f"Link: {entry.link}")
    print(f"Published: {entry.published}\n")
EOF
```

**Output (NO subscription needed):**
```
WSJ RSS Feed: 20 articles

Title: SPAC XYZ Announces Merger with TechCorp
Summary: Special purpose acquisition company XYZ Corp said Monday it reached a definitive agreement to merge with TechCorp in a deal valued at $3 billion. The transaction is expected to close in Q2...
Link: https://www.wsj.com/articles/spac-xyz-merger-techcorp-12345
Published: Mon, 09 Oct 2025 08:32:00 EST
```

**Note:** You can see the summary! No subscription needed for RSS.

**If you click the link:**
```
[WSJ.com - Login Required]

Subscribe to read this article and unlock unlimited access.

[Subscribe Now - $40/month]
```

### Test NYT RSS (Free Access)

```bash
python3 << 'EOF'
import feedparser

feed = feedparser.parse('https://rss.nytimes.com/services/xml/rss/nyt/Business.xml')

print(f"NYT RSS Feed: {len(feed.entries)} articles\n")

for entry in feed.entries[:2]:
    print(f"Title: {entry.title}")
    print(f"Summary: {entry.summary[:200]}...")
    print()
EOF
```

**Works without subscription!**

---

## Summary

### Question: "Are these RSS services included in subscriptions?"

**Answer:**

**RSS feeds themselves = FREE (no subscription needed)**
- ✅ Can poll RSS feeds anytime
- ✅ Get headlines + summaries
- ✅ Enough for deal detection

**Full article content = Requires subscription**
- ❌ Need WSJ subscription to read full WSJ articles
- ❌ Need NYT subscription to read full NYT articles
- But you already got the alert from RSS summary!

**For SPAC monitoring:**
- RSS summaries (FREE) → Detect deal → Send alert → Monitor SEC
- Subscription (paid) → Read full analysis → Investment decision

**Workflow:**
1. RSS catches headline (FREE)
2. AI verifies from summary (FREE)
3. Send Telegram alert (FREE)
4. **Optional:** Click link, read full article (needs subscription)
5. SEC 8-K confirms details (FREE)

**Bottom line:** You can run the entire monitoring system with FREE RSS access. Subscriptions just let you read the full articles after you get the alert.

---

**Recommendation:** Start with free RSS feeds. Add WSJ subscription later if you find you want to read full articles frequently.
