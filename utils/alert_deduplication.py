#!/usr/bin/env python3
"""
alert_deduplication.py - Prevent Duplicate Telegram Alerts

Purpose: Track sent Telegram notifications and prevent sending duplicates
         within a specified time window (default: 24 hours)

Problem: Users receiving multiple alerts for the same event (e.g., Reddit mentions)
Solution: Track what's been sent and only send once per day per ticker/alert_type

Usage:
    from utils.alert_deduplication import should_send_alert, mark_alert_sent

    if should_send_alert(ticker='BLUW', alert_type='reddit_leak'):
        send_telegram_alert(message)
        mark_alert_sent(ticker='BLUW', alert_type='reddit_leak')
"""

from datetime import datetime, timedelta
from sqlalchemy import text
from database import SessionLocal


class AlertDeduplicator:
    """
    Manage Telegram alert deduplication

    Alert Types:
    - reddit_leak: Reddit deal leak detected
    - reddit_summary: Daily Reddit scan summary
    - price_spike: Price movement alert
    - deal_detected: New deal announcement
    - validation_issue: Data quality issue
    """

    def __init__(self, dedup_hours: int = 24):
        """
        Initialize deduplicator

        Args:
            dedup_hours: Hours to wait before resending same alert (default: 24)
        """
        self.dedup_hours = dedup_hours
        self.db = SessionLocal()
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Create telegram_notifications table if it doesn't exist"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS telegram_notifications (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(10),
            alert_type VARCHAR(50) NOT NULL,
            alert_key VARCHAR(255),  -- For additional uniqueness (e.g., target name)
            message_preview TEXT,
            sent_at TIMESTAMP DEFAULT NOW(),

            -- Index for fast lookups
            CONSTRAINT unique_alert UNIQUE (ticker, alert_type, alert_key, sent_at)
        );

        CREATE INDEX IF NOT EXISTS idx_telegram_notifications_ticker
        ON telegram_notifications(ticker);

        CREATE INDEX IF NOT EXISTS idx_telegram_notifications_alert_type
        ON telegram_notifications(alert_type);

        CREATE INDEX IF NOT EXISTS idx_telegram_notifications_sent_at
        ON telegram_notifications(sent_at);
        """

        try:
            self.db.execute(text(create_table_sql))
            self.db.commit()
        except Exception as e:
            print(f"⚠️  Could not create telegram_notifications table: {e}")
            self.db.rollback()

    def should_send_alert(self, alert_type: str, ticker: str = None,
                         alert_key: str = None) -> bool:
        """
        Check if alert should be sent (not sent recently)

        Args:
            alert_type: Type of alert (e.g., 'reddit_leak', 'price_spike')
            ticker: SPAC ticker (optional)
            alert_key: Additional uniqueness key (optional, e.g., target name)

        Returns: True if should send, False if duplicate
        """
        cutoff_time = datetime.now() - timedelta(hours=self.dedup_hours)

        query = """
            SELECT COUNT(*) FROM telegram_notifications
            WHERE alert_type = :alert_type
              AND sent_at >= :cutoff_time
        """
        params = {'alert_type': alert_type, 'cutoff_time': cutoff_time}

        # Add ticker filter if provided
        if ticker:
            query += " AND ticker = :ticker"
            params['ticker'] = ticker

        # Add alert_key filter if provided
        if alert_key:
            query += " AND alert_key = :alert_key"
            params['alert_key'] = alert_key

        try:
            result = self.db.execute(text(query), params)
            count = result.scalar()

            if count > 0:
                print(f"  ⏭️  Skipping duplicate alert: {alert_type} for {ticker or 'all'} "
                      f"(last sent within {self.dedup_hours}h)")
                return False

            return True

        except Exception as e:
            print(f"  ⚠️  Error checking alert deduplication: {e}")
            # If check fails, allow send (fail open)
            return True

    def mark_alert_sent(self, alert_type: str, ticker: str = None,
                       alert_key: str = None, message_preview: str = None):
        """
        Mark alert as sent

        Args:
            alert_type: Type of alert
            ticker: SPAC ticker (optional)
            alert_key: Additional uniqueness key (optional)
            message_preview: First 100 chars of message (for debugging)
        """
        insert_query = """
            INSERT INTO telegram_notifications (
                ticker, alert_type, alert_key, message_preview, sent_at
            ) VALUES (
                :ticker, :alert_type, :alert_key, :message_preview, NOW()
            )
            ON CONFLICT (ticker, alert_type, alert_key, sent_at)
            DO NOTHING
        """

        try:
            self.db.execute(text(insert_query), {
                'ticker': ticker,
                'alert_type': alert_type,
                'alert_key': alert_key,
                'message_preview': message_preview[:100] if message_preview else None
            })
            self.db.commit()
            print(f"  ✓ Marked alert sent: {alert_type} for {ticker or 'all'}")

        except Exception as e:
            print(f"  ⚠️  Error marking alert as sent: {e}")
            self.db.rollback()

    def get_recent_alerts(self, hours: int = 24, alert_type: str = None) -> list:
        """
        Get recently sent alerts

        Args:
            hours: Look back this many hours
            alert_type: Filter by alert type (optional)

        Returns: List of alert dicts
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)

        query = """
            SELECT
                ticker, alert_type, alert_key, message_preview, sent_at
            FROM telegram_notifications
            WHERE sent_at >= :cutoff_time
        """
        params = {'cutoff_time': cutoff_time}

        if alert_type:
            query += " AND alert_type = :alert_type"
            params['alert_type'] = alert_type

        query += " ORDER BY sent_at DESC"

        try:
            result = self.db.execute(text(query), params)
            alerts = []
            for row in result:
                alerts.append({
                    'ticker': row[0],
                    'alert_type': row[1],
                    'alert_key': row[2],
                    'message_preview': row[3],
                    'sent_at': row[4]
                })
            return alerts

        except Exception as e:
            print(f"⚠️  Error fetching recent alerts: {e}")
            return []

    def cleanup_old_alerts(self, days: int = 30):
        """
        Clean up old alert records

        Args:
            days: Delete alerts older than this many days
        """
        cutoff_time = datetime.now() - timedelta(days=days)

        delete_query = """
            DELETE FROM telegram_notifications
            WHERE sent_at < :cutoff_time
        """

        try:
            result = self.db.execute(text(delete_query), {'cutoff_time': cutoff_time})
            self.db.commit()
            print(f"✓ Cleaned up {result.rowcount} old alert records (older than {days} days)")

        except Exception as e:
            print(f"⚠️  Error cleaning up old alerts: {e}")
            self.db.rollback()

    def __del__(self):
        """Cleanup database connection"""
        if hasattr(self, 'db'):
            self.db.close()


# ============================================================================
# Convenience Functions (backward compatible)
# ============================================================================

_deduplicator = None

def get_deduplicator(dedup_hours: int = 24) -> AlertDeduplicator:
    """Get or create global deduplicator instance"""
    global _deduplicator
    if _deduplicator is None:
        _deduplicator = AlertDeduplicator(dedup_hours=dedup_hours)
    return _deduplicator


def should_send_alert(alert_type: str, ticker: str = None,
                     alert_key: str = None, dedup_hours: int = 24) -> bool:
    """
    Quick check: should this alert be sent?

    Usage:
        if should_send_alert('reddit_leak', ticker='BLUW'):
            send_telegram_alert(message)
            mark_alert_sent('reddit_leak', ticker='BLUW')
    """
    dedup = get_deduplicator(dedup_hours)
    return dedup.should_send_alert(alert_type, ticker, alert_key)


def mark_alert_sent(alert_type: str, ticker: str = None,
                   alert_key: str = None, message_preview: str = None):
    """
    Mark alert as sent

    Always call this AFTER successfully sending alert
    """
    dedup = get_deduplicator()
    dedup.mark_alert_sent(alert_type, ticker, alert_key, message_preview)


def get_recent_alerts(hours: int = 24, alert_type: str = None) -> list:
    """Get recently sent alerts"""
    dedup = get_deduplicator()
    return dedup.get_recent_alerts(hours, alert_type)


def cleanup_old_alerts(days: int = 30):
    """Clean up old alert records"""
    dedup = get_deduplicator()
    dedup.cleanup_old_alerts(days)


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Alert Deduplication Utility')
    parser.add_argument('--list', action='store_true', help='List recent alerts')
    parser.add_argument('--cleanup', action='store_true', help='Clean up old alerts')
    parser.add_argument('--test', action='store_true', help='Test deduplication')
    parser.add_argument('--hours', type=int, default=24, help='Hours for recent alerts')

    args = parser.parse_args()

    if args.list:
        alerts = get_recent_alerts(hours=args.hours)
        print(f"\n📊 Recent Alerts (Last {args.hours} hours): {len(alerts)}\n")
        for alert in alerts:
            print(f"{alert['sent_at'].strftime('%Y-%m-%d %H:%M')} | "
                  f"{alert['alert_type']:20s} | {alert['ticker'] or 'N/A':6s} | "
                  f"{alert['message_preview'][:50] if alert['message_preview'] else 'No preview'}")

    elif args.cleanup:
        cleanup_old_alerts(days=30)

    elif args.test:
        print("\n🧪 Testing Alert Deduplication\n")

        # Test 1: Should send first time
        print("Test 1: First alert for BLUW reddit_leak")
        if should_send_alert('reddit_leak', ticker='BLUW'):
            print("  ✓ Should send (first time)")
            mark_alert_sent('reddit_leak', ticker='BLUW', message_preview="BLUW leak detected")

        # Test 2: Should NOT send duplicate
        print("\nTest 2: Duplicate alert for BLUW reddit_leak")
        if should_send_alert('reddit_leak', ticker='BLUW'):
            print("  ✗ ERROR: Should NOT send (duplicate)")
        else:
            print("  ✓ Correctly blocked duplicate")

        # Test 3: Different ticker should send
        print("\nTest 3: Different ticker (CCCX) reddit_leak")
        if should_send_alert('reddit_leak', ticker='CCCX'):
            print("  ✓ Should send (different ticker)")
            mark_alert_sent('reddit_leak', ticker='CCCX', message_preview="CCCX leak detected")

        # Test 4: Different alert type should send
        print("\nTest 4: Different alert type (price_spike) for BLUW")
        if should_send_alert('price_spike', ticker='BLUW'):
            print("  ✓ Should send (different alert type)")
            mark_alert_sent('price_spike', ticker='BLUW', message_preview="BLUW price spike")

        print("\n✓ Tests complete")

    else:
        parser.print_help()
        print("\nExamples:")
        print("  python3 utils/alert_deduplication.py --list")
        print("  python3 utils/alert_deduplication.py --list --hours 48")
        print("  python3 utils/alert_deduplication.py --cleanup")
        print("  python3 utils/alert_deduplication.py --test")
