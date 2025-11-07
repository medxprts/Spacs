#!/usr/bin/env python3
"""
Social Sentiment Agent - Reddit Buzz Tracking & Scoring

Monitors Reddit (r/SPACs) for SPAC mentions and integrates buzz into Phase 1 scoring:
- Tracks mention counts (24h, 7d rolling windows)
- Extracts rumored targets using AI
- Analyzes sentiment (bullish/neutral/bearish)
- Calculates buzz score (0-5 points for Phase 1 scorer)
- Updates social_sentiment table

Buzz Score Rubric:
  0 points: No mentions or <3 mentions/week
  1 point:  3-9 mentions/week (low buzz)
  2 points: 10-19 mentions/week (moderate buzz)
  3 points: 20-49 mentions/week (high buzz)
  4 points: 50-99 mentions/week (very high buzz)
  5 points: 100+ mentions/week (viral/extreme buzz)

Integration: Called by orchestrator every 30 minutes, updates social_sentiment table
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
import json
import re
from collections import defaultdict

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from agents.orchestrator_agent_base import OrchestratorAgentBase
from agents.agent_task import AgentTask
from openai import OpenAI

# Reddit scraping (using PRAW)
try:
    import praw
    REDDIT_AVAILABLE = True
except ImportError:
    REDDIT_AVAILABLE = False
    print("⚠️  praw not installed. Install with: pip install praw")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SocialSentimentAgent(OrchestratorAgentBase):
    """
    Monitors Reddit for SPAC buzz and calculates social sentiment scores
    """

    def __init__(self):
        super().__init__()
        self.db = SessionLocal()

        # Initialize AI client for sentiment analysis
        api_key = os.getenv('DEEPSEEK_API_KEY')
        self.ai_client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        ) if api_key else None

        # Initialize Reddit client
        self.reddit = self._init_reddit() if REDDIT_AVAILABLE else None

        # Ticker patterns for mention detection
        self.ticker_pattern = re.compile(r'\$?([A-Z]{3,5})(?:\s|$|[.,!?])')

    def _init_reddit(self) -> Optional[praw.Reddit]:
        """Initialize Reddit API client"""
        try:
            reddit = praw.Reddit(
                client_id=os.getenv('REDDIT_CLIENT_ID'),
                client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
                user_agent='SPAC Research Platform v1.0 (by /u/spacresearch)'
            )
            logger.info("✓ Reddit API initialized")
            return reddit
        except Exception as e:
            logger.warning(f"Reddit API not available: {e}")
            return None

    def execute(self, task: AgentTask) -> AgentTask:
        """Main execution: scan Reddit and update social sentiment"""
        self._start_task(task)

        try:
            if not self.reddit:
                self._fail_task(task, "Reddit API not available")
                return task

            # Get all active SPACs
            spacs = self.db.query(SPAC).filter(
                SPAC.deal_status.in_(['SEARCHING', 'ANNOUNCED'])
            ).all()

            logger.info(f"Scanning Reddit for {len(spacs)} SPACs...")

            # Scan Reddit for mentions
            mentions = self._scan_reddit_mentions(spacs, days=7)

            # Update social_sentiment table
            updated_count = 0
            for spac in spacs:
                ticker = spac.ticker
                if ticker in mentions:
                    self._update_sentiment_record(ticker, mentions[ticker])
                    updated_count += 1
                else:
                    # No mentions - set to zero
                    self._update_sentiment_record(ticker, {
                        'mention_count_7d': 0,
                        'mention_count_24h': 0,
                        'mention_count_1h': 0,
                        'posts': [],
                        'rumored_targets': [],
                        'sentiment': 0.0
                    })

            result = {
                'spacs_scanned': len(spacs),
                'spacs_with_mentions': len(mentions),
                'total_mentions': sum(m['mention_count_7d'] for m in mentions.values()),
                'updated_records': updated_count
            }

            self._complete_task(task, result)

        except Exception as e:
            logger.error(f"Social sentiment scan failed: {e}")
            self._fail_task(task, str(e))
        finally:
            self.db.close()

        return task

    def _scan_reddit_mentions(self, spacs: List[SPAC], days: int = 7) -> Dict[str, Dict]:
        """
        Scan r/SPACs for ticker mentions in last N days

        Returns dict: {ticker: {mention_count_7d, mention_count_24h, posts, sentiment}}
        """
        mentions = defaultdict(lambda: {
            'mention_count_7d': 0,
            'mention_count_24h': 0,
            'mention_count_1h': 0,
            'posts': [],
            'rumored_targets': [],
            'sentiment': 0.0
        })

        ticker_set = {s.ticker.upper() for s in spacs}

        try:
            subreddit = self.reddit.subreddit('SPACs')

            # Scan recent posts
            cutoff_time = datetime.utcnow() - timedelta(days=days)
            cutoff_24h = datetime.utcnow() - timedelta(hours=24)
            cutoff_1h = datetime.utcnow() - timedelta(hours=1)

            # Get recent submissions
            for submission in subreddit.new(limit=500):
                post_time = datetime.utcfromtimestamp(submission.created_utc)

                if post_time < cutoff_time:
                    break  # Too old

                # Extract tickers from title and selftext
                text = f"{submission.title} {submission.selftext}"
                found_tickers = self._extract_tickers(text, ticker_set)

                for ticker in found_tickers:
                    mentions[ticker]['mention_count_7d'] += 1

                    if post_time >= cutoff_24h:
                        mentions[ticker]['mention_count_24h'] += 1

                    if post_time >= cutoff_1h:
                        mentions[ticker]['mention_count_1h'] += 1

                    # Save post details (top 5 only)
                    if len(mentions[ticker]['posts']) < 5:
                        mentions[ticker]['posts'].append({
                            'title': submission.title,
                            'url': f"https://reddit.com{submission.permalink}",
                            'upvotes': submission.score,
                            'created_at': post_time.isoformat(),
                            'excerpt': submission.selftext[:200] if submission.selftext else ''
                        })

            # Also scan top comments for deeper context
            for submission in subreddit.hot(limit=50):
                post_time = datetime.utcfromtimestamp(submission.created_utc)

                if post_time < cutoff_time:
                    continue

                submission.comments.replace_more(limit=0)
                for comment in submission.comments.list()[:100]:  # Top 100 comments
                    comment_time = datetime.utcfromtimestamp(comment.created_utc)

                    if comment_time < cutoff_time:
                        continue

                    found_tickers = self._extract_tickers(comment.body, ticker_set)

                    for ticker in found_tickers:
                        mentions[ticker]['mention_count_7d'] += 1

                        if comment_time >= cutoff_24h:
                            mentions[ticker]['mention_count_24h'] += 1

                        if comment_time >= cutoff_1h:
                            mentions[ticker]['mention_count_1h'] += 1

            logger.info(f"Found mentions for {len(mentions)} tickers")

        except Exception as e:
            logger.error(f"Reddit scan error: {e}")

        return dict(mentions)

    def _extract_tickers(self, text: str, ticker_set: set) -> List[str]:
        """Extract valid SPAC tickers from text"""
        found = []
        matches = self.ticker_pattern.findall(text.upper())

        for match in matches:
            if match in ticker_set:
                found.append(match)

        return list(set(found))  # Deduplicate

    def _update_sentiment_record(self, ticker: str, mention_data: Dict):
        """Update or insert social_sentiment record with buzz scoring"""

        # Calculate buzz score (0-5 points)
        mention_count = mention_data['mention_count_7d']
        buzz_score, buzz_level = self._calculate_buzz_score(mention_count)

        # Analyze sentiment if we have posts
        sentiment_score = 0.0
        sentiment_category = 'neutral'
        rumored_targets = []
        top_rumored = None

        if mention_data['posts'] and self.ai_client:
            sentiment_analysis = self._analyze_sentiment_ai(ticker, mention_data['posts'])
            sentiment_score = sentiment_analysis['sentiment_score']
            sentiment_category = sentiment_analysis['sentiment_category']
            rumored_targets = sentiment_analysis['rumored_targets']
            top_rumored = rumored_targets[0] if rumored_targets else None

        # Prepare top posts JSON
        top_posts_json = json.dumps(mention_data['posts'][:5])

        # Upsert into social_sentiment table
        try:
            self.db.execute("""
                INSERT INTO social_sentiment (
                    ticker, mention_count_7d, mention_count_24h, mention_count_1h,
                    rumored_targets, top_rumored_target, sentiment_score, sentiment_category,
                    buzz_score, buzz_level, top_posts, last_updated, update_count
                ) VALUES (
                    :ticker, :mention_7d, :mention_24h, :mention_1h,
                    :rumored_targets, :top_rumored, :sentiment_score, :sentiment_category,
                    :buzz_score, :buzz_level, :top_posts::jsonb, NOW(), 1
                )
                ON CONFLICT (ticker) DO UPDATE SET
                    mention_count_7d = EXCLUDED.mention_count_7d,
                    mention_count_24h = EXCLUDED.mention_count_24h,
                    mention_count_1h = EXCLUDED.mention_count_1h,
                    rumored_targets = EXCLUDED.rumored_targets,
                    top_rumored_target = EXCLUDED.top_rumored_target,
                    sentiment_score = EXCLUDED.sentiment_score,
                    sentiment_category = EXCLUDED.sentiment_category,
                    buzz_score = EXCLUDED.buzz_score,
                    buzz_level = EXCLUDED.buzz_level,
                    top_posts = EXCLUDED.top_posts,
                    last_updated = NOW(),
                    update_count = social_sentiment.update_count + 1
            """, {
                'ticker': ticker,
                'mention_7d': mention_data['mention_count_7d'],
                'mention_24h': mention_data['mention_count_24h'],
                'mention_1h': mention_data['mention_count_1h'],
                'rumored_targets': rumored_targets,
                'top_rumored': top_rumored,
                'sentiment_score': sentiment_score,
                'sentiment_category': sentiment_category,
                'buzz_score': buzz_score,
                'buzz_level': buzz_level,
                'top_posts': top_posts_json
            })
            self.db.commit()

        except Exception as e:
            logger.error(f"Error updating sentiment for {ticker}: {e}")
            self.db.rollback()

    def _calculate_buzz_score(self, mention_count: int) -> Tuple[int, str]:
        """
        Calculate buzz score (0-5) and level based on 7-day mention count

        Rubric:
          0: <3 mentions/week (none)
          1: 3-9 mentions (low)
          2: 10-19 mentions (medium)
          3: 20-49 mentions (high)
          4: 50-99 mentions (very high)
          5: 100+ mentions (extreme/viral)
        """
        if mention_count < 3:
            return 0, 'none'
        elif mention_count < 10:
            return 1, 'low'
        elif mention_count < 20:
            return 2, 'medium'
        elif mention_count < 50:
            return 3, 'high'
        elif mention_count < 100:
            return 4, 'very_high'
        else:
            return 5, 'extreme'

    def _analyze_sentiment_ai(self, ticker: str, posts: List[Dict]) -> Dict:
        """
        Use AI to analyze sentiment and extract rumored targets

        Returns:
            {
                'sentiment_score': -1.0 to +1.0,
                'sentiment_category': 'bullish' / 'neutral' / 'bearish',
                'rumored_targets': ['Company A', 'Company B'],
                'target_confidence': 0.0-1.0
            }
        """
        if not self.ai_client:
            return {
                'sentiment_score': 0.0,
                'sentiment_category': 'neutral',
                'rumored_targets': [],
                'target_confidence': 0.0
            }

        # Combine post titles and excerpts
        text_sample = "\n\n".join([
            f"Title: {p['title']}\nExcerpt: {p.get('excerpt', '')}"
            for p in posts[:5]
        ])

        prompt = f"""Analyze Reddit sentiment for SPAC ${ticker}.

Recent posts:
{text_sample}

Return JSON with:
{{
  "sentiment_score": <-1.0 to +1.0, where -1=very bearish, 0=neutral, +1=very bullish>,
  "sentiment_category": "<bullish|neutral|bearish>",
  "rumored_targets": ["<company names if mentioned, otherwise empty>"],
  "target_confidence": <0.0-1.0, confidence that a target is being discussed>
}}

Only return valid JSON, no other text."""

        try:
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )

            result_text = response.choices[0].message.content.strip()

            # Extract JSON from response
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0].strip()
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0].strip()

            result = json.loads(result_text)

            return {
                'sentiment_score': float(result.get('sentiment_score', 0.0)),
                'sentiment_category': result.get('sentiment_category', 'neutral'),
                'rumored_targets': result.get('rumored_targets', []),
                'target_confidence': float(result.get('target_confidence', 0.0))
            }

        except Exception as e:
            logger.error(f"AI sentiment analysis failed for {ticker}: {e}")
            return {
                'sentiment_score': 0.0,
                'sentiment_category': 'neutral',
                'rumored_targets': [],
                'target_confidence': 0.0
            }

    def close(self):
        """Clean up resources"""
        if self.db:
            self.db.close()


def main():
    """CLI interface for testing"""
    import argparse

    parser = argparse.ArgumentParser(description='Social Sentiment Agent')
    parser.add_argument('--scan', action='store_true', help='Scan Reddit and update sentiment')
    parser.add_argument('--ticker', type=str, help='Analyze specific ticker')

    args = parser.parse_args()

    agent = SocialSentimentAgent()

    if args.scan:
        task = AgentTask(
            agent_name='social_sentiment',
            task_type='reddit_scan',
            priority=5
        )
        result = agent.execute(task)
        print(f"\n{result}")

    elif args.ticker:
        # Quick check for specific ticker
        db = SessionLocal()
        try:
            result = db.execute("""
                SELECT * FROM social_sentiment WHERE ticker = :ticker
            """, {'ticker': args.ticker.upper()}).fetchone()

            if result:
                print(f"\n{args.ticker.upper()} Social Sentiment:")
                print(f"  Buzz Score: {result.buzz_score}/5 ({result.buzz_level})")
                print(f"  Mentions (7d): {result.mention_count_7d}")
                print(f"  Mentions (24h): {result.mention_count_24h}")
                print(f"  Sentiment: {result.sentiment_category} ({result.sentiment_score:.2f})")
                print(f"  Rumored Target: {result.top_rumored_target or 'None'}")
                print(f"  Last Updated: {result.last_updated}")
            else:
                print(f"No sentiment data found for {args.ticker.upper()}")
        finally:
            db.close()

    else:
        parser.print_help()

    agent.close()


if __name__ == '__main__':
    main()
