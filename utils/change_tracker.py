"""
Change Tracker Utility
Logs all automated database changes made by orchestrator agents
"""

from database import SessionLocal
from sqlalchemy import text
from datetime import datetime, date
from typing import Any, Optional


class ChangeTracker:
    """Track database changes made by orchestrator agents"""

    @staticmethod
    def log_change(
        ticker: str,
        field_name: str,
        old_value: Any,
        new_value: Any,
        change_source: str,
        filing_type: Optional[str] = None,
        filing_date: Optional[date] = None,
        change_type: str = 'update'
    ):
        """
        Log a database field change

        Args:
            ticker: SPAC ticker symbol
            field_name: Name of field that changed (e.g., 'trust_cash', 'target')
            old_value: Previous value (None if new field)
            new_value: New value
            change_source: Agent that made the change (e.g., 'TrustAccountProcessor')
            filing_type: Type of filing that triggered change (e.g., '10-Q', '8-K')
            filing_date: Date of the filing
            change_type: Type of change ('update', 'new_field', 'correction')
        """
        # Skip if values are the same
        if str(old_value) == str(new_value):
            return

        db = SessionLocal()
        try:
            db.execute(text("""
                INSERT INTO orchestrator_changes (
                    ticker, field_name, old_value, new_value,
                    change_source, filing_type, filing_date, change_type
                ) VALUES (
                    :ticker, :field_name, :old_value, :new_value,
                    :change_source, :filing_type, :filing_date, :change_type
                )
            """), {
                'ticker': ticker,
                'field_name': field_name,
                'old_value': str(old_value) if old_value is not None else None,
                'new_value': str(new_value) if new_value is not None else None,
                'change_source': change_source,
                'filing_type': filing_type,
                'filing_date': filing_date,
                'change_type': change_type
            })
            db.commit()
        except Exception as e:
            print(f"⚠️  Failed to log change: {e}")
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def log_multiple_changes(
        ticker: str,
        changes: dict,
        change_source: str,
        filing_type: Optional[str] = None,
        filing_date: Optional[date] = None
    ):
        """
        Log multiple field changes at once

        Args:
            ticker: SPAC ticker symbol
            changes: Dict of {field_name: (old_value, new_value)}
            change_source: Agent that made the changes
            filing_type: Type of filing that triggered changes
            filing_date: Date of the filing
        """
        for field_name, (old_value, new_value) in changes.items():
            ChangeTracker.log_change(
                ticker=ticker,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                change_source=change_source,
                filing_type=filing_type,
                filing_date=filing_date,
                change_type='new_field' if old_value is None else 'update'
            )

    @staticmethod
    def get_daily_summary(target_date: Optional[date] = None) -> dict:
        """
        Get summary of changes for a specific date

        Args:
            target_date: Date to summarize (defaults to today)

        Returns:
            Dict with change statistics
        """
        if target_date is None:
            target_date = datetime.now().date()

        db = SessionLocal()
        try:
            # Total changes
            total_result = db.execute(text("""
                SELECT COUNT(*) as count
                FROM orchestrator_changes
                WHERE DATE(timestamp) = :target_date
            """), {'target_date': target_date}).fetchone()

            # Changes by source
            by_source = db.execute(text("""
                SELECT change_source, COUNT(*) as count
                FROM orchestrator_changes
                WHERE DATE(timestamp) = :target_date
                GROUP BY change_source
                ORDER BY count DESC
            """), {'target_date': target_date}).fetchall()

            # Changes by field
            by_field = db.execute(text("""
                SELECT field_name, COUNT(*) as count
                FROM orchestrator_changes
                WHERE DATE(timestamp) = :target_date
                GROUP BY field_name
                ORDER BY count DESC
                LIMIT 10
            """), {'target_date': target_date}).fetchall()

            # Changes by ticker (top 10)
            by_ticker = db.execute(text("""
                SELECT ticker, COUNT(*) as count
                FROM orchestrator_changes
                WHERE DATE(timestamp) = :target_date
                GROUP BY ticker
                ORDER BY count DESC
                LIMIT 10
            """), {'target_date': target_date}).fetchall()

            # Recent significant changes
            significant_changes = db.execute(text("""
                SELECT ticker, field_name, old_value, new_value, change_source, filing_type
                FROM orchestrator_changes
                WHERE DATE(timestamp) = :target_date
                  AND field_name IN ('target', 'deal_status', 'deal_value', 'trust_cash',
                                     'shares_outstanding', 'announced_date', 'expected_close')
                ORDER BY timestamp DESC
                LIMIT 20
            """), {'target_date': target_date}).fetchall()

            return {
                'date': target_date,
                'total_changes': total_result.count if total_result else 0,
                'by_source': [{'source': row.change_source, 'count': row.count} for row in by_source],
                'by_field': [{'field': row.field_name, 'count': row.count} for row in by_field],
                'by_ticker': [{'ticker': row.ticker, 'count': row.count} for row in by_ticker],
                'significant_changes': [
                    {
                        'ticker': row.ticker,
                        'field': row.field_name,
                        'old_value': row.old_value,
                        'new_value': row.new_value,
                        'source': row.change_source,
                        'filing_type': row.filing_type
                    }
                    for row in significant_changes
                ]
            }
        finally:
            db.close()

    @staticmethod
    def format_daily_summary(summary: dict) -> str:
        """
        Format daily summary for Telegram report

        Args:
            summary: Dict from get_daily_summary()

        Returns:
            Formatted string for Telegram
        """
        if summary['total_changes'] == 0:
            return "📊 **Database Changes**: No automated changes recorded"

        lines = [
            f"📊 **Database Changes**: {summary['total_changes']} total updates",
            ""
        ]

        # Changes by source
        if summary['by_source']:
            lines.append("**By Agent:**")
            for item in summary['by_source'][:5]:
                lines.append(f"  • {item['source']}: {item['count']} changes")
            lines.append("")

        # Top updated fields
        if summary['by_field']:
            lines.append("**Top Updated Fields:**")
            for item in summary['by_field'][:5]:
                lines.append(f"  • {item['field']}: {item['count']} updates")
            lines.append("")

        # SPACs with most changes
        if summary['by_ticker']:
            lines.append("**Most Updated SPACs:**")
            for item in summary['by_ticker'][:5]:
                lines.append(f"  • {item['ticker']}: {item['count']} changes")
            lines.append("")

        # Significant changes
        if summary['significant_changes']:
            lines.append("**Key Changes:**")
            for change in summary['significant_changes'][:10]:
                old_val = change['old_value'] or 'None'
                new_val = change['new_value'] or 'None'

                # Truncate long values
                if len(old_val) > 30:
                    old_val = old_val[:27] + '...'
                if len(new_val) > 30:
                    new_val = new_val[:27] + '...'

                lines.append(
                    f"  • {change['ticker']}.{change['field']}: "
                    f"{old_val} → {new_val} "
                    f"({change['filing_type'] or 'API'})"
                )

        return "\n".join(lines)
