#!/usr/bin/env python3
"""
Validation Queue - Database-Backed Sequential Issue Processing
Version: 2.0.0

Replaces validation_issue_queue.py (395 lines) with database storage.
No more JSON file sync issues!
"""

import sys
import os
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import SessionLocal, SPAC


class ValidationQueue:
    """Database-backed validation queue for sequential issue review"""

    def __init__(self, db_session=None):
        """
        Initialize validation queue

        Args:
            db_session: Optional database session (creates new if not provided)
        """
        self.db = db_session or SessionLocal()
        self.owns_session = db_session is None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.owns_session:
            self.db.close()

    def create_queue(
        self,
        issues: List[Dict],
        triggered_by: str = 'manual',
        priority: str = 'normal'
    ) -> int:
        """
        Create new validation queue

        Args:
            issues: List of issue dictionaries
            triggered_by: Who/what triggered this queue
            priority: Queue priority level

        Returns:
            queue_id: ID of created queue
        """
        # Create queue
        result = self.db.execute(
            text("""
                INSERT INTO validation_queue (total_issues, triggered_by, priority)
                VALUES (:total, :triggered, :priority)
                RETURNING id
            """),
            {
                'total': len(issues),
                'triggered': triggered_by,
                'priority': priority
            }
        )
        queue_id = result.fetchone()[0]

        # Add items
        for position, issue in enumerate(issues, start=1):
            self.db.execute(
                text("""
                    INSERT INTO validation_queue_items (
                        queue_id, position, ticker, field, rule_id, rule_name,
                        severity, category, issue_data, proposed_fix
                    )
                    VALUES (
                        :queue_id, :position, :ticker, :field, :rule_id, :rule_name,
                        :severity, :category, :issue_data::jsonb, :proposed_fix::jsonb
                    )
                """),
                {
                    'queue_id': queue_id,
                    'position': position,
                    'ticker': issue.get('ticker'),
                    'field': issue.get('field'),
                    'rule_id': issue.get('rule_id', issue.get('rule')),
                    'rule_name': issue.get('rule_name', issue.get('rule')),
                    'severity': issue.get('severity', 'MEDIUM'),
                    'category': issue.get('category', 'unknown'),
                    'issue_data': issue,
                    'proposed_fix': issue.get('proposed_fix', issue.get('auto_fix'))
                }
            )

        self.db.commit()
        print(f"✓ Created queue {queue_id} with {len(issues)} issues")
        return queue_id

    def get_active_queue(self) -> Optional[Dict]:
        """
        Get currently active queue

        Returns:
            Queue info dict or None
        """
        result = self.db.execute(
            text("""
                SELECT id, current_index, total_issues, awaiting_response, created_at
                FROM validation_queue
                WHERE status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
            """)
        ).fetchone()

        if not result:
            return None

        return {
            'queue_id': result[0],
            'current_index': result[1],
            'total_issues': result[2],
            'awaiting_response': result[3],
            'created_at': result[4]
        }

    def get_current_issue(self) -> Optional[Dict]:
        """
        Get current issue from active queue

        Returns:
            Issue dict or None
        """
        result = self.db.execute(
            text("""
                SELECT * FROM get_next_queue_item()
            """)
        ).fetchone()

        if not result:
            return None

        return {
            'queue_id': result[0],
            'item_id': result[1],
            'position': result[2],
            'ticker': result[3],
            'field': result[4],
            'rule_name': result[5],
            'severity': result[6],
            'issue_data': result[7]
        }

    def mark_current_approved(self, resolution_notes: str = None):
        """Mark current issue as approved and move to next"""
        queue = self.get_active_queue()
        if not queue:
            return

        # Mark current item as approved
        self.db.execute(
            text("""
                UPDATE validation_queue_items
                SET status = 'approved',
                    resolved_at = NOW(),
                    resolution_notes = :notes
                WHERE queue_id = :queue_id
                  AND position = :position + 1
                  AND status = 'pending'
            """),
            {
                'queue_id': queue['queue_id'],
                'position': queue['current_index'],
                'notes': resolution_notes
            }
        )

        # Move to next
        self.db.execute(
            text("""
                UPDATE validation_queue
                SET current_index = current_index + 1,
                    awaiting_response = FALSE
                WHERE id = :queue_id
            """),
            {'queue_id': queue['queue_id']}
        )

        self.db.commit()

    def mark_current_skipped(self, reason: str = None):
        """Mark current issue as skipped and move to next"""
        queue = self.get_active_queue()
        if not queue:
            return

        self.db.execute(
            text("""
                UPDATE validation_queue_items
                SET status = 'skipped',
                    resolved_at = NOW(),
                    resolution_notes = :reason
                WHERE queue_id = :queue_id
                  AND position = :position + 1
                  AND status = 'pending'
            """),
            {
                'queue_id': queue['queue_id'],
                'position': queue['current_index'],
                'reason': reason
            }
        )

        self.db.execute(
            text("""
                UPDATE validation_queue
                SET current_index = current_index + 1,
                    awaiting_response = FALSE
                WHERE id = :queue_id
            """),
            {'queue_id': queue['queue_id']}
        )

        self.db.commit()

    def batch_approve_by_pattern(self, pattern: str) -> int:
        """
        Batch approve all pending issues matching pattern

        Args:
            pattern: Rule pattern (e.g., "Trust Cash", "Premium")

        Returns:
            Number of issues approved
        """
        queue = self.get_active_queue()
        if not queue:
            return 0

        result = self.db.execute(
            text("""
                UPDATE validation_queue_items
                SET status = 'approved',
                    resolved_at = NOW(),
                    resolution_notes = 'Batch approved'
                WHERE queue_id = :queue_id
                  AND status = 'pending'
                  AND (rule_name ILIKE :pattern OR category ILIKE :pattern)
                RETURNING id
            """),
            {
                'queue_id': queue['queue_id'],
                'pattern': f'%{pattern}%'
            }
        )

        approved_count = len(result.fetchall())

        # Log batch approval
        if approved_count > 0:
            item_ids = [row[0] for row in result]
            self.db.execute(
                text("""
                    INSERT INTO batch_approvals (queue_id, pattern, items_approved, item_ids)
                    VALUES (:queue_id, :pattern, :count, :ids)
                """),
                {
                    'queue_id': queue['queue_id'],
                    'pattern': pattern,
                    'count': approved_count,
                    'ids': item_ids
                }
            )

        self.db.commit()
        return approved_count

    def batch_approve_all(self) -> int:
        """
        Batch approve ALL pending issues in current queue

        Returns:
            Number of issues approved
        """
        queue = self.get_active_queue()
        if not queue:
            return 0

        result = self.db.execute(
            text("""
                UPDATE validation_queue_items
                SET status = 'approved',
                    resolved_at = NOW(),
                    resolution_notes = 'Batch approved (all)'
                WHERE queue_id = :queue_id
                  AND status = 'pending'
                RETURNING id
            """),
            {'queue_id': queue['queue_id']}
        )

        approved_count = len(result.fetchall())

        if approved_count > 0:
            item_ids = [row[0] for row in result]
            self.db.execute(
                text("""
                    INSERT INTO batch_approvals (queue_id, pattern, items_approved, item_ids)
                    VALUES (:queue_id, 'ALL', :count, :ids)
                """),
                {
                    'queue_id': queue['queue_id'],
                    'count': approved_count,
                    'ids': item_ids
                }
            )

        # Complete queue since all approved
        self.db.execute(
            text("""
                UPDATE validation_queue
                SET status = 'completed',
                    completed_at = NOW()
                WHERE id = :queue_id
            """),
            {'queue_id': queue['queue_id']}
        )

        self.db.commit()
        return approved_count

    def get_queue_stats(self) -> Dict:
        """
        Get statistics for active queue

        Returns:
            Stats dictionary
        """
        queue = self.get_active_queue()
        if not queue:
            return {'error': 'No active queue'}

        result = self.db.execute(
            text("""
                SELECT * FROM queue_statistics WHERE queue_id = :queue_id
            """),
            {'queue_id': queue['queue_id']}
        ).fetchone()

        if not result:
            return {}

        return {
            'queue_id': result[0],
            'created_at': result[1],
            'total_issues': result[2],
            'approved_count': result[3],
            'skipped_count': result[4],
            'pending_count': result[5],
            'modified_count': result[6],
            'avg_conversation_turns': result[7]
        }

    def has_more_issues(self) -> bool:
        """Check if active queue has more pending issues"""
        queue = self.get_active_queue()
        if not queue:
            return False

        return queue['current_index'] < queue['total_issues']


if __name__ == "__main__":
    # Test queue
    with ValidationQueue() as queue:
        print(f"Active queue: {queue.get_active_queue()}")
        print(f"Current issue: {queue.get_current_issue()}")
        print(f"Stats: {queue.get_queue_stats()}")
