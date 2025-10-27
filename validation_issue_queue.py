#!/usr/bin/env python3
"""
Validation Issue Queue Manager
Manages sequential processing of validation issues via Telegram
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from utils.telegram_notifier import send_telegram_alert

QUEUE_FILE = "/home/ubuntu/spac-research/.validation_issue_queue.json"


class ValidationIssueQueue:
    """Manage sequential processing of validation issues"""
    
    def __init__(self):
        self.queue_file = QUEUE_FILE
        self.load_queue()
    
    def load_queue(self):
        """Load queue from file"""
        if os.path.exists(self.queue_file):
            with open(self.queue_file, 'r') as f:
                self.data = json.load(f)
        else:
            self.data = {
                'issues': [],
                'current_index': 0,
                'awaiting_response': False,
                'last_updated': None
            }
    
    def save_queue(self):
        """Save queue to file"""
        self.data['last_updated'] = datetime.now().isoformat()
        with open(self.queue_file, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def add_issues(self, issues: List[Dict]):
        """Add new issues to queue (clears existing queue)"""
        self.data['issues'] = issues
        self.data['current_index'] = 0
        self.data['awaiting_response'] = False
        self.save_queue()
    
    def get_current_issue(self) -> Optional[Dict]:
        """Get current issue waiting for response"""
        if not self.data['issues']:
            return None
        
        if self.data['current_index'] >= len(self.data['issues']):
            return None
        
        return self.data['issues'][self.data['current_index']]
    
    def mark_current_resolved(self, resolution: str = 'approved'):
        """Mark current issue as resolved and move to next"""
        if self.data['issues'] and self.data['current_index'] < len(self.data['issues']):
            current_issue = self.data['issues'][self.data['current_index']]
            current_issue['resolution'] = resolution
            current_issue['resolved_at'] = datetime.now().isoformat()

            # Also mark the corresponding database conversation as completed
            ticker = current_issue.get('ticker')
            if ticker:
                self._mark_conversation_completed(ticker, resolution)

        self.data['current_index'] += 1
        self.data['awaiting_response'] = False
        self.save_queue()

    def _mark_conversation_completed(self, ticker: str, resolution: str):
        """Mark the active conversation for this ticker as completed in database"""
        from database import SessionLocal
        from sqlalchemy import text

        db = SessionLocal()
        try:
            # Find most recent active conversation for this ticker
            db.execute(
                text("""
                    UPDATE data_quality_conversations
                    SET status = :status,
                        completed_at = NOW(),
                        learning_notes = :learning_notes
                    WHERE ticker = :ticker
                      AND status = 'active'
                      AND issue_id LIKE 'queue_issue_%'
                      AND completed_at IS NULL
                """),
                {
                    'ticker': ticker,
                    'status': resolution,  # 'approved' or 'skipped'
                    'learning_notes': f"User {resolution} issue via queue"
                }
            )
            db.commit()
            print(f"   ✓ Marked {ticker} conversation as {resolution}")
        except Exception as e:
            print(f"   ⚠️  Could not mark conversation as completed: {e}")
            db.rollback()
        finally:
            db.close()

    def batch_approve_by_pattern(self, pattern: str) -> int:
        """
        Batch approve all pending issues matching a pattern

        Args:
            pattern: Rule pattern to match (e.g., "Trust Cash", "Trust Value", "Deal Status")

        Returns:
            Number of issues approved
        """
        pattern_lower = pattern.lower()
        approved_count = 0

        for issue in self.data['issues']:
            # Only approve pending issues
            if issue.get('resolution') not in [None, 'pending']:
                continue

            # Check if rule matches pattern
            rule = issue.get('rule', '').lower()
            if pattern_lower in rule:
                issue['resolution'] = 'approved'
                issue['resolved_at'] = datetime.now().isoformat()
                approved_count += 1

        # Reset awaiting_response since we batch processed
        self.data['awaiting_response'] = False
        self.save_queue()

        return approved_count

    def batch_approve_all(self) -> int:
        """
        Batch approve ALL pending issues

        Returns:
            Number of issues approved
        """
        approved_count = 0

        for issue in self.data['issues']:
            if issue.get('resolution') in [None, 'pending']:
                issue['resolution'] = 'approved'
                issue['resolved_at'] = datetime.now().isoformat()
                approved_count += 1

        self.data['awaiting_response'] = False
        self.save_queue()

        return approved_count

    def _get_spac_age_info(self, ticker: str) -> str:
        """
        Get SPAC age information for context in validation messages

        Args:
            ticker: SPAC ticker symbol

        Returns:
            Formatted HTML string with age info, or empty string if not available
        """
        try:
            from database import SessionLocal, SPAC
            from datetime import datetime

            db = SessionLocal()
            try:
                spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
                if not spac or not spac.ipo_date:
                    return ""

                # Calculate age
                ipo_date = spac.ipo_date.date() if hasattr(spac.ipo_date, 'date') else spac.ipo_date
                age_days = (datetime.now().date() - ipo_date).days
                age_years = age_days / 365.25

                # Format age nicely
                if age_years >= 1.0:
                    age_str = f"{age_years:.1f} years"
                elif age_days >= 30:
                    age_str = f"{age_days // 30} months"
                else:
                    age_str = f"{age_days} days"

                # Calculate expected trust value with interest (assuming ~4% APY)
                expected_trust = 10.00 * (1.04 ** age_years)

                # Add context for trust value issues
                context = ""
                if age_years >= 1.5:
                    context = f" (⚠️ Interest accumulated)\n<b>Expected Trust Value:</b> ~${expected_trust:.2f} with interest"
                elif age_years >= 0.5:
                    context = f" (ℹ️ Some interest expected)\n<b>Expected Trust Value:</b> ~${expected_trust:.2f} with interest"
                else:
                    context = " (✓ Minimal interest expected)"

                return f"\n<b>SPAC Age:</b> {age_str}{context}"

            finally:
                db.close()

        except Exception as e:
            print(f"Warning: Could not get SPAC age for {ticker}: {e}")
            return ""

    def send_current_issue(self) -> bool:
        """Send current issue to Telegram and create conversation state"""
        issue = self.get_current_issue()
        if not issue:
            return False

        total = len(self.data['issues'])
        current = self.data['current_index'] + 1

        # Create conversation state for this issue
        self._create_conversation_state(issue, current)

        # Get SPAC age for context
        spac_age_str = self._get_spac_age_info(issue.get('ticker'))

        # Escape HTML entities in issue data
        import html
        ticker = html.escape(str(issue.get('ticker', 'N/A')))
        field = html.escape(str(issue.get('field', 'N/A')))
        rule = html.escape(str(issue.get('rule', 'N/A')))
        severity = html.escape(str(issue.get('severity', 'N/A')))
        msg = html.escape(str(issue.get('message', 'N/A')))
        actual = html.escape(str(issue.get('actual', 'N/A')))
        expected = html.escape(str(issue.get('expected', 'N/A')))

        # Format issue message
        message = f"""🔍 <b>Data Quality Issue {current}/{total}</b>

<b>Ticker:</b> {ticker}
<b>Field:</b> {field}
<b>Rule:</b> {rule}
<b>Severity:</b> {severity}

<b>Issue:</b> {msg}

<b>Current Value:</b> {actual}
<b>Expected:</b> {expected}
{spac_age_str}
"""

        # NEW: Add web research findings if available
        if issue.get('research_findings'):
            findings = html.escape(str(issue['research_findings']))
            confidence = issue.get('research_confidence', 0)
            sec_verified = issue.get('sec_verified', False)

            message += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 <b>WEB RESEARCH FINDINGS:</b>

{findings}
"""

            if sec_verified:
                sec_url = issue.get('sec_filing_url', '')
                if sec_url:
                    message += f"\n✅ <b>SEC VERIFIED</b> (8-K filing confirms)\n"
                else:
                    message += f"\n✅ <b>SEC VERIFIED</b>\n"

            if issue.get('suggested_fix'):
                suggested = html.escape(str(issue['suggested_fix']))
                confidence_icon = "🎯" if confidence >= 90 else "⚠️" if confidence >= 70 else "❓"
                message += f"""
{confidence_icon} <b>SUGGESTED FIX (Confidence: {confidence}%):</b>
<code>{suggested}</code>
"""
        elif issue.get('auto_fix'):
            auto_fix = html.escape(str(issue['auto_fix']))
            message += f"\n<b>Suggested Fix:</b> {auto_fix}\n"

        message += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>📋 WHAT WOULD YOU LIKE TO DO?</b>

<b>1️⃣ APPROVE THIS ISSUE</b>
   Reply: <code>APPROVE</code>
   → Apply fix for this issue only

<b>2️⃣ BATCH APPROVE</b>
   Reply: <code>APPROVE ALL</code> → Approve all remaining issues
   Reply: <code>APPROVE TRUST CASH</code> → Approve all trust cash issues
   Reply: <code>APPROVE TRUST VALUE</code> → Approve all trust value issues
   Reply: <code>APPROVE DEAL STATUS</code> → Approve all deal status issues

<b>3️⃣ SKIP / DO NOTHING</b>
   Reply: <code>skip</code> or <code>next</code>
   → Move to next issue

<b>4️⃣ MANUAL REVIEW</b>
   Reply: <code>show changes</code> or <code>show fix</code>
   → See before/after comparison

<b>5️⃣ CHAT WITH CLAUDE</b>
   Reply: Ask questions, request modifications
   → Examples:
     • "Why is this wrong?"
     • "Change {field} to [new value]"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Progress: {current}/{total} issues"""

        send_telegram_alert(message)
        self.data['awaiting_response'] = True
        self.save_queue()
        return True

    def _create_conversation_state(self, issue: Dict, issue_number: int):
        """Create conversation state in database for this issue"""
        from database import SessionLocal, engine, SPAC
        from sqlalchemy import text
        import json

        db = SessionLocal()
        try:
            issue_id = f"queue_issue_{issue_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            ticker = issue.get('ticker')

            # Fetch current SPAC data for original_data
            original_data = {}
            if ticker:
                spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
                if spac:
                    field = issue.get('field')
                    if field:
                        original_data[field] = str(getattr(spac, field, None))

            # Create conversation entry
            db.execute(
                text("""
                    INSERT INTO data_quality_conversations
                    (issue_id, issue_type, ticker, messages, proposed_fix, final_fix, original_data, status, started_at)
                    VALUES (:issue_id, :issue_type, :ticker, :messages, :proposed_fix, :final_fix, :original_data, 'active', NOW())
                    ON CONFLICT (issue_id) DO UPDATE SET
                        status = 'active',
                        started_at = NOW()
                """),
                {
                    "issue_id": issue_id,
                    "issue_type": issue.get('type', 'validation_error'),
                    "ticker": ticker,
                    "messages": json.dumps([]),
                    "proposed_fix": json.dumps({
                        issue.get('field'): issue.get('expected') if issue.get('auto_fix') else None
                    }),
                    "final_fix": json.dumps({
                        issue.get('field'): issue.get('expected') if issue.get('auto_fix') else None
                    }),
                    "original_data": json.dumps(original_data)
                }
            )
            db.commit()
        except Exception as e:
            print(f"Warning: Could not create conversation state: {e}")
            db.rollback()
        finally:
            db.close()
    
    def is_awaiting_response(self) -> bool:
        """Check if currently waiting for user response"""
        return self.data.get('awaiting_response', False)
    
    def has_more_issues(self) -> bool:
        """Check if there are more issues in queue"""
        return self.data['current_index'] < len(self.data['issues'])
    
    def get_stats(self) -> Dict:
        """Get queue statistics"""
        return {
            'total': len(self.data['issues']),
            'current': self.data['current_index'] + 1 if self.has_more_issues() else len(self.data['issues']),
            'remaining': len(self.data['issues']) - self.data['current_index'],
            'awaiting_response': self.data.get('awaiting_response', False)
        }


if __name__ == "__main__":
    # Test queue
    queue = ValidationIssueQueue()
    print(f"Queue stats: {queue.get_stats()}")
    
    if queue.has_more_issues():
        print(f"Current issue: {queue.get_current_issue()}")
