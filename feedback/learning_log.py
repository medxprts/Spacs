#!/usr/bin/env python3
"""
Learning Log - Track Feedback System Learnings
Version: 2.0.0

Simplified version of data_quality_logger.py focused on learning outcomes.
"""

import sys
import os
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import SessionLocal


class LearningLog:
    """
    Track learnings from data quality feedback process

    Features:
    - Log user feedback
    - Track fix effectiveness
    - Identify improvement opportunities
    - Support self-improvement system
    """

    def __init__(self, db_session=None):
        """Initialize learning log"""
        self.db = db_session or SessionLocal()
        self.owns_session = db_session is None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.owns_session:
            self.db.close()

    def log_fix_applied(
        self,
        ticker: str,
        field: str,
        old_value: any,
        new_value: any,
        fix_template_id: str,
        confidence: float,
        user_approved: bool = True
    ):
        """
        Log a fix that was applied

        Args:
            ticker: SPAC ticker
            field: Field that was fixed
            old_value: Original value
            new_value: New value
            fix_template_id: Template used
            confidence: Confidence level
            user_approved: Whether user approved it
        """
        self.db.execute(
            text("""
                INSERT INTO data_quality_conversations (
                    issue_id, issue_type, ticker, status,
                    original_data, final_fix, learning_notes,
                    started_at, completed_at
                )
                VALUES (
                    :issue_id, :issue_type, :ticker, :status,
                    :original_data::jsonb, :final_fix::jsonb, :learning_notes,
                    NOW(), NOW()
                )
            """),
            {
                'issue_id': f"fix_{ticker}_{field}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                'issue_type': 'fix_applied',
                'ticker': ticker,
                'status': 'approved' if user_approved else 'auto_applied',
                'original_data': {field: str(old_value)},
                'final_fix': {field: str(new_value)},
                'learning_notes': f"Applied {fix_template_id} (confidence: {confidence})"
            }
        )
        self.db.commit()

    def log_user_modification(
        self,
        ticker: str,
        field: str,
        proposed_value: any,
        actual_value: any,
        reason: str
    ):
        """
        Log when user modifies proposed fix

        Args:
            ticker: SPAC ticker
            field: Field modified
            proposed_value: What system proposed
            actual_value: What user changed it to
            reason: Why user changed it
        """
        self.db.execute(
            text("""
                INSERT INTO data_quality_conversations (
                    issue_id, issue_type, ticker, status,
                    proposed_fix, final_fix, learning_notes,
                    started_at, completed_at
                )
                VALUES (
                    :issue_id, 'user_modification', :ticker, 'modified',
                    :proposed::jsonb, :final::jsonb, :notes,
                    NOW(), NOW()
                )
            """),
            {
                'issue_id': f"mod_{ticker}_{field}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                'ticker': ticker,
                'proposed': {field: str(proposed_value)},
                'final': {field: str(actual_value)},
                'notes': f"User modified: {reason}"
            }
        )
        self.db.commit()

    def get_learnings_for_pattern(
        self,
        error_pattern: str,
        limit: int = 10
    ) -> list:
        """
        Get past learnings for similar error pattern

        Args:
            error_pattern: Pattern key
            limit: Max results

        Returns:
            List of past cases
        """
        result = self.db.execute(
            text("""
                SELECT ticker, learning_notes, final_fix, completed_at
                FROM data_quality_conversations
                WHERE error_pattern = :pattern
                  AND status IN ('approved', 'modified')
                  AND completed_at IS NOT NULL
                ORDER BY completed_at DESC
                LIMIT :limit
            """),
            {'pattern': error_pattern, 'limit': limit}
        )

        learnings = []
        for row in result:
            learnings.append({
                'ticker': row[0],
                'learning': row[1],
                'fix': row[2],
                'date': row[3]
            })

        return learnings

    def record_error_pattern(
        self,
        pattern_key: str,
        ticker: str,
        description: str = None
    ):
        """
        Record error occurrence for self-improvement tracking

        Args:
            pattern_key: Error pattern identifier
            ticker: Affected ticker
            description: Optional description
        """
        self.db.execute(
            text("SELECT record_error_occurrence(:pattern, :ticker, :desc)"),
            {
                'pattern': pattern_key,
                'ticker': ticker,
                'desc': description
            }
        )
        self.db.commit()

    def get_patterns_needing_fixes(self) -> list:
        """
        Get error patterns that have crossed threshold

        Returns:
            List of patterns needing code fixes
        """
        result = self.db.execute(
            text("SELECT * FROM patterns_needing_fix")
        )

        patterns = []
        for row in result:
            patterns.append({
                'pattern_key': row[0],
                'description': row[1],
                'occurrence_count': row[2],
                'occurrences_last_30_days': row[3],
                'threshold': row[4],
                'last_seen': row[5],
                'affected_tickers': row[6]
            })

        return patterns


if __name__ == "__main__":
    # Test learning log
    with LearningLog() as log:
        # Test recording error pattern
        log.record_error_pattern(
            'test_pattern',
            'TEST',
            'Test error description'
        )
        print("✓ Recorded error pattern")

        # Test getting patterns needing fixes
        patterns = log.get_patterns_needing_fixes()
        print(f"✓ Found {len(patterns)} patterns needing fixes")
