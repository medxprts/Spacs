#!/usr/bin/env python3
"""
Telegram Interface - Conversational Approval Workflow
Version: 2.0.0

Simplified Telegram interface for validation issue review.
Replaces telegram_approval_listener.py (1,130 lines → ~300 lines)
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, Optional
from openai import OpenAI
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from telegram_agent import TelegramAgent
from feedback.validation_queue import ValidationQueue
from feedback.investigation_engine import InvestigationEngine
from feedback.fix_applier import FixApplier

load_dotenv()


class TelegramInterface:
    """
    Conversational Telegram interface for data quality review

    Features:
    - Sequential issue presentation
    - Interactive conversation (ask questions, modify fixes)
    - Batch approval support
    - Learning from user feedback
    """

    def __init__(self):
        """Initialize Telegram interface"""
        self.telegram = TelegramAgent()
        self.queue = ValidationQueue()
        self.investigator = InvestigationEngine()
        self.fixer = FixApplier()

        # AI for conversational responses
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            self.ai_client = OpenAI(
                api_key=deepseek_key,
                base_url="https://api.deepseek.com"
            )
        else:
            self.ai_client = None

    def send_current_issue(self) -> bool:
        """
        Send current issue to Telegram for user review

        Returns:
            True if sent, False if no issues
        """
        issue = self.queue.get_current_issue()
        if not issue:
            print("No current issue to send")
            return False

        queue_info = self.queue.get_active_queue()
        position = queue_info['current_index'] + 1
        total = queue_info['total_issues']

        # Format message
        message = self._format_issue_message(issue, position, total)

        # Send via Telegram
        success = self.telegram.send_message(message, parse_mode='HTML')

        if success:
            print(f"✓ Sent issue {position}/{total} to Telegram")

        return success

    def _format_issue_message(self, issue: Dict, position: int, total: int) -> str:
        """
        Format issue as Telegram message with HTML

        Args:
            issue: Issue dictionary
            position: Current position in queue
            total: Total issues in queue

        Returns:
            Formatted HTML message
        """
        import html as html_lib

        # Extract issue data
        issue_data = issue['issue_data']
        ticker = html_lib.escape(str(issue.get('ticker', 'N/A')))
        field = html_lib.escape(str(issue.get('field', 'N/A')))
        rule_name = html_lib.escape(str(issue.get('rule_name', 'N/A')))
        severity = html_lib.escape(str(issue.get('severity', 'MEDIUM')))

        message = html_lib.escape(str(issue_data.get('message', 'No description')))
        actual = html_lib.escape(str(issue_data.get('actual', 'N/A')))
        expected = html_lib.escape(str(issue_data.get('expected', 'N/A')))

        # Build message
        msg = f"""🔍 <b>Data Quality Issue {position}/{total}</b>

<b>Ticker:</b> {ticker}
<b>Field:</b> {field}
<b>Rule:</b> {rule_name}
<b>Severity:</b> {severity}

<b>Issue:</b> {message}

<b>Current Value:</b> {actual}
<b>Expected:</b> {expected}
"""

        # Add research findings if available
        if issue_data.get('research_findings'):
            findings = html_lib.escape(str(issue_data['research_findings']))
            confidence = issue_data.get('research_confidence', 0)

            msg += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 <b>WEB RESEARCH FINDINGS:</b>

{findings}

<b>Confidence:</b> {confidence}%
"""

            if issue_data.get('suggested_fix'):
                suggested = html_lib.escape(str(issue_data['suggested_fix']))
                msg += f"""
<b>💡 SUGGESTED FIX:</b>
<code>{suggested}</code>
"""

        # Add action menu
        msg += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>📋 WHAT WOULD YOU LIKE TO DO?</b>

<b>1️⃣ APPROVE THIS ISSUE</b>
   Reply: <code>APPROVE</code>
   → Apply fix for this issue only

<b>2️⃣ BATCH APPROVE</b>
   Reply: <code>APPROVE ALL</code> → Approve all remaining issues
   Reply: <code>APPROVE {field.upper()}</code> → Approve all {field} issues

<b>3️⃣ SKIP / DO NOTHING</b>
   Reply: <code>skip</code> or <code>next</code>
   → Move to next issue without fixing

<b>4️⃣ REVIEW CHANGES</b>
   Reply: <code>show changes</code>
   → See before/after comparison

<b>5️⃣ CHAT WITH CLAUDE</b>
   Reply: Ask questions or request modifications
   Examples:
     • "Why is this wrong?"
     • "Change {field} to [value]"
     • "What's the risk if I skip this?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>Progress:</b> {position}/{total} issues
"""

        return msg

    def process_user_response(self, user_message: str) -> str:
        """
        Process user response to current issue

        Args:
            user_message: Message from user

        Returns:
            Response message to send back
        """
        msg = user_message.strip().upper()

        # Handle batch approvals
        if msg == "APPROVE ALL":
            count = self.queue.batch_approve_all()
            return f"✅ Batch approved ALL {count} remaining issues"

        if msg.startswith("APPROVE ") and len(msg.split()) == 2:
            pattern = msg.split()[1]
            count = self.queue.batch_approve_by_pattern(pattern)
            return f"✅ Batch approved {count} issues matching '{pattern}'"

        # Handle single approval
        if msg == "APPROVE":
            self.queue.mark_current_approved()
            if self.queue.has_more_issues():
                self.send_current_issue()
                return "✅ Approved. Moving to next issue..."
            else:
                return "✅ Approved. All issues processed!"

        # Handle skip
        if msg in ["SKIP", "NEXT"]:
            self.queue.mark_current_skipped()
            if self.queue.has_more_issues():
                self.send_current_issue()
                return "⏭️ Skipped. Moving to next issue..."
            else:
                return "⏭️ Skipped. All issues processed!"

        # Handle show changes
        if "SHOW" in msg and "CHANGE" in msg:
            return self._show_proposed_changes()

        # Handle conversational AI
        return self._handle_conversation(user_message)

    def _show_proposed_changes(self) -> str:
        """Show before/after comparison for current issue"""
        issue = self.queue.get_current_issue()
        if not issue:
            return "No current issue"

        issue_data = issue['issue_data']
        ticker = issue['ticker']
        field = issue['field']
        actual = issue_data.get('actual')
        expected = issue_data.get('expected')

        msg = f"""📋 <b>PROPOSED CHANGES FOR {ticker}</b>

<b>Field:</b> {field}

<b>BEFORE:</b>
<code>{actual}</code>

<b>AFTER:</b>
<code>{expected}</code>

Reply <code>APPROVE</code> to apply this change.
Reply <code>skip</code> to skip this issue.
"""
        return msg

    def _handle_conversation(self, user_message: str) -> str:
        """
        Handle conversational questions using AI

        Args:
            user_message: User's question or comment

        Returns:
            AI-generated response
        """
        if not self.ai_client:
            return "💬 Conversational AI not available (missing DEEPSEEK_API_KEY)"

        issue = self.queue.get_current_issue()
        if not issue:
            return "No current issue to discuss"

        # Build context
        context = f"""Current Issue:
Ticker: {issue['ticker']}
Field: {issue['field']}
Rule: {issue['rule_name']}
Severity: {issue['severity']}
Issue Data: {json.dumps(issue['issue_data'], indent=2)}

User Question: {user_message}

You are a helpful assistant reviewing data quality issues. Answer the user's question
about this issue clearly and concisely. If they request changes, acknowledge and
explain what will be modified.
"""

        try:
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a data quality assistant."},
                    {"role": "user", "content": context}
                ],
                max_tokens=500
            )

            return response.choices[0].message.content

        except Exception as e:
            return f"❌ Error generating response: {str(e)}"

    def listen(self, timeout_minutes: int = 60) -> Optional[str]:
        """
        Listen for user response via Telegram

        Args:
            timeout_minutes: How long to wait

        Returns:
            User message or None if timeout
        """
        return self.telegram.wait_for_response(timeout_minutes=timeout_minutes)

    def send_code_fix_proposal(self, fix_proposal: Dict) -> bool:
        """
        Send code fix proposal for user review

        Args:
            fix_proposal: Fix details from self-improvement agent

        Returns:
            True if sent successfully
        """
        import html as html_lib

        error_pattern = html_lib.escape(fix_proposal.get('error_pattern', 'Unknown'))
        count = fix_proposal.get('occurrence_count', 0)
        root_cause = html_lib.escape(fix_proposal.get('root_cause', 'Unknown'))
        fix_description = html_lib.escape(fix_proposal.get('fix_description', 'No description'))
        files = ', '.join(fix_proposal.get('files_to_modify', []))
        confidence = fix_proposal.get('confidence', 0)

        message = f"""🔧 <b>CODE IMPROVEMENT PROPOSAL</b>

<b>Error Pattern:</b> {error_pattern}
<b>Occurrences:</b> {count} times (last 30 days)

<b>Root Cause:</b>
{root_cause}

<b>Proposed Fix:</b>
{fix_description}

<b>Files to Modify:</b>
<code>{files}</code>

<b>Confidence:</b> {confidence}%

⚠️ <b>THIS IS A PROPOSAL ONLY</b> ⚠️
No code will be changed without your explicit approval.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>ACTIONS:</b>

<code>REVIEW</code> - Show me the exact code changes (git diff format)
<code>APPROVE CODE FIX {fix_proposal.get('fix_id', 'XXX')}</code> - Apply this fix
<code>REJECT</code> - Do not apply this fix
<code>DELAY</code> - Remind me in 24 hours
<code>DISCUSS</code> - Ask questions about this fix
"""

        return self.telegram.send_message(message, parse_mode='HTML')


if __name__ == "__main__":
    # Test interface
    interface = TelegramInterface()
    interface.send_current_issue()
