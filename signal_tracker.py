#!/usr/bin/env python3
"""
Signal Tracker - Ensures we only alert on NEW information

Tracks:
1. News articles seen (by URL hash)
2. Reddit posts processed (by post ID)
3. Last alert sent for each ticker
4. Prevents duplicate alerts within cooldown period
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from pathlib import Path


class SignalTracker:
    """
    Tracks processed signals to ensure we only alert on NEW information

    Storage format:
    {
      "news_seen": {
        "url_hash_1": {"timestamp": "2025-10-09T12:00:00", "ticker": "CCCX", "title": "..."},
        "url_hash_2": {...}
      },
      "reddit_seen": {
        "post_id_1": {"timestamp": "2025-10-09T12:00:00", "ticker": "CCCX"},
        "post_id_2": {...}
      },
      "last_alerts": {
        "CCCX": {"timestamp": "2025-10-09T12:00:00", "reason": "News article"},
        "MLAC": {...}
      }
    }
    """

    def __init__(self, tracker_file: str = "/home/ubuntu/spac-research/logs/signal_tracker.json"):
        self.tracker_file = tracker_file
        self.data = self._load_tracker()

        # Configurable retention periods
        self.news_retention_days = 30  # Keep news history for 30 days
        self.reddit_retention_days = 14  # Keep Reddit history for 14 days
        self.alert_cooldown_hours = 6  # Don't re-alert same ticker within 6 hours

    def _load_tracker(self) -> Dict:
        """Load tracker data from disk"""
        if os.path.exists(self.tracker_file):
            try:
                with open(self.tracker_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load tracker file: {e}")

        # Initialize empty tracker
        return {
            'news_seen': {},
            'reddit_seen': {},
            'last_alerts': {}
        }

    def _save_tracker(self):
        """Save tracker data to disk"""
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.tracker_file), exist_ok=True)

        with open(self.tracker_file, 'w') as f:
            json.dump(self.data, f, indent=2, default=str)

    def _cleanup_old_entries(self):
        """Remove old entries to prevent unbounded growth"""
        now = datetime.now()

        # Cleanup old news entries
        news_cutoff = now - timedelta(days=self.news_retention_days)
        self.data['news_seen'] = {
            url_hash: data
            for url_hash, data in self.data['news_seen'].items()
            if datetime.fromisoformat(data['timestamp']) > news_cutoff
        }

        # Cleanup old Reddit entries
        reddit_cutoff = now - timedelta(days=self.reddit_retention_days)
        self.data['reddit_seen'] = {
            post_id: data
            for post_id, data in self.data['reddit_seen'].items()
            if datetime.fromisoformat(data['timestamp']) > reddit_cutoff
        }

        # Cleanup old alert timestamps (keep last 7 days)
        alert_cutoff = now - timedelta(days=7)
        self.data['last_alerts'] = {
            ticker: data
            for ticker, data in self.data['last_alerts'].items()
            if datetime.fromisoformat(data['timestamp']) > alert_cutoff
        }

    def _hash_url(self, url: str) -> str:
        """Generate hash for URL"""
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def is_news_new(self, url: str, title: str = None) -> bool:
        """
        Check if news article is new (not seen before)

        Args:
            url: Article URL
            title: Article title (for logging)

        Returns:
            True if NEW article, False if already seen
        """
        url_hash = self._hash_url(url)

        if url_hash in self.data['news_seen']:
            # Already seen this article
            seen_data = self.data['news_seen'][url_hash]
            print(f"  📰 News DUPLICATE: {title or url} (seen {seen_data['timestamp']})")
            return False

        # New article!
        return True

    def mark_news_seen(self, url: str, ticker: str, title: str = None):
        """Mark news article as seen"""
        url_hash = self._hash_url(url)

        self.data['news_seen'][url_hash] = {
            'timestamp': datetime.now().isoformat(),
            'ticker': ticker,
            'title': title or url,
            'url': url
        }

        self._save_tracker()

    def is_reddit_post_new(self, post_id: str) -> bool:
        """
        Check if Reddit post is new (not seen before)

        Args:
            post_id: Reddit post/comment ID

        Returns:
            True if NEW post, False if already seen
        """
        if post_id in self.data['reddit_seen']:
            # Already processed this post
            return False

        # New post!
        return True

    def mark_reddit_seen(self, post_id: str, ticker: str):
        """Mark Reddit post as seen"""
        self.data['reddit_seen'][post_id] = {
            'timestamp': datetime.now().isoformat(),
            'ticker': ticker
        }

        self._save_tracker()

    def should_alert(self, ticker: str, reason: str, min_hours_between: Optional[int] = None) -> bool:
        """
        Check if we should send alert for this ticker

        Prevents alert fatigue by enforcing cooldown period.

        Args:
            ticker: SPAC ticker
            reason: Reason for alert
            min_hours_between: Override default cooldown (default: 6 hours)

        Returns:
            True if should alert, False if in cooldown period
        """
        cooldown_hours = min_hours_between if min_hours_between is not None else self.alert_cooldown_hours

        if ticker in self.data['last_alerts']:
            last_alert = self.data['last_alerts'][ticker]
            last_time = datetime.fromisoformat(last_alert['timestamp'])
            hours_since = (datetime.now() - last_time).total_seconds() / 3600

            if hours_since < cooldown_hours:
                print(f"  ⏸️  Alert COOLDOWN: {ticker} (last alert {hours_since:.1f}h ago, cooldown {cooldown_hours}h)")
                return False

        # OK to alert
        return True

    def mark_alert_sent(self, ticker: str, reason: str, confidence: float = None):
        """Mark that alert was sent for this ticker"""
        self.data['last_alerts'][ticker] = {
            'timestamp': datetime.now().isoformat(),
            'reason': reason,
            'confidence': confidence
        }

        self._save_tracker()

    def filter_new_news(self, articles: List[Dict], ticker: str) -> List[Dict]:
        """
        Filter list of articles to only NEW ones

        Args:
            articles: List of article dicts with 'url' key
            ticker: Ticker these articles are about

        Returns:
            List of only NEW articles
        """
        new_articles = []

        for article in articles:
            url = article.get('url') or article.get('link')
            title = article.get('title', '')

            if not url:
                continue

            if self.is_news_new(url, title):
                new_articles.append(article)
                # Mark as seen
                self.mark_news_seen(url, ticker, title)

        if new_articles:
            print(f"  ✅ {len(new_articles)} NEW article(s) (filtered out {len(articles) - len(new_articles)} duplicates)")
        else:
            print(f"  ⏭️  0 new articles (all {len(articles)} already seen)")

        return new_articles

    def filter_new_reddit_mentions(self, mentions: List[Dict], ticker: str) -> List[Dict]:
        """
        Filter list of Reddit mentions to only NEW ones

        Args:
            mentions: List of mention dicts with 'id' key
            ticker: Ticker these mentions are about

        Returns:
            List of only NEW mentions
        """
        new_mentions = []

        for mention in mentions:
            post_id = mention.get('id')

            if not post_id:
                continue

            if self.is_reddit_post_new(post_id):
                new_mentions.append(mention)
                # Mark as seen
                self.mark_reddit_seen(post_id, ticker)

        if new_mentions:
            print(f"  ✅ {len(new_mentions)} NEW mention(s) (filtered out {len(mentions) - len(new_mentions)} duplicates)")
        else:
            print(f"  ⏭️  0 new mentions (all {len(mentions)} already seen)")

        return new_mentions

    def get_stats(self) -> Dict:
        """Get tracker statistics"""
        return {
            'news_articles_tracked': len(self.data['news_seen']),
            'reddit_posts_tracked': len(self.data['reddit_seen']),
            'tickers_with_recent_alerts': len(self.data['last_alerts']),
            'oldest_news': min(
                (datetime.fromisoformat(d['timestamp']) for d in self.data['news_seen'].values()),
                default=None
            ),
            'oldest_reddit': min(
                (datetime.fromisoformat(d['timestamp']) for d in self.data['reddit_seen'].values()),
                default=None
            )
        }

    def cleanup(self):
        """Run cleanup and save"""
        self._cleanup_old_entries()
        self._save_tracker()


if __name__ == "__main__":
    # Test tracker
    tracker = SignalTracker()

    print("Signal Tracker Test")
    print("="*80)

    # Test news tracking
    print("\n1. Testing news tracking:")
    url1 = "https://example.com/article1"
    print(f"   Is {url1} new? {tracker.is_news_new(url1)}")  # True
    tracker.mark_news_seen(url1, "CCCX", "Test Article 1")
    print(f"   Is {url1} new? {tracker.is_news_new(url1)}")  # False (duplicate)

    # Test Reddit tracking
    print("\n2. Testing Reddit tracking:")
    post_id1 = "abc123"
    print(f"   Is post {post_id1} new? {tracker.is_reddit_post_new(post_id1)}")  # True
    tracker.mark_reddit_seen(post_id1, "CCCX")
    print(f"   Is post {post_id1} new? {tracker.is_reddit_post_new(post_id1)}")  # False

    # Test alert cooldown
    print("\n3. Testing alert cooldown:")
    print(f"   Should alert CCCX? {tracker.should_alert('CCCX', 'Test')}")  # True
    tracker.mark_alert_sent('CCCX', 'Test', confidence=85)
    print(f"   Should alert CCCX again? {tracker.should_alert('CCCX', 'Test')}")  # False (cooldown)
    print(f"   Should alert MLAC? {tracker.should_alert('MLAC', 'Test')}")  # True (different ticker)

    # Test filtering
    print("\n4. Testing filtering:")
    articles = [
        {'url': 'https://example.com/new1', 'title': 'New Article 1'},
        {'url': url1, 'title': 'Old Article'},  # Already seen
        {'url': 'https://example.com/new2', 'title': 'New Article 2'},
    ]
    new_articles = tracker.filter_new_news(articles, 'CCCX')
    print(f"   Filtered: {len(new_articles)} new out of {len(articles)} total")

    # Stats
    print("\n5. Tracker stats:")
    stats = tracker.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    print("\n✅ Test complete")
