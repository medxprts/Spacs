#!/usr/bin/env python3
"""
Telegram Conversational Approval Listener

Monitors Telegram for data quality fix approvals with conversational interface.
Enables interactive chat with Claude to review, modify, and approve fixes.

Features:
- Show before/after diffs
- Modify proposed fixes via conversation
- Ask questions about changes
- Log conversations for learning
- Auto-apply approved fixes

Run as background service:
    python3 telegram_approval_listener.py --daemon

Integration:
    Orchestrator sends alert → User chats with Claude → User approves → Listener applies fix

Refactored to use TelegramAgent (centralized communication)
"""

import os
import sys
import time
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from openai import OpenAI

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC, engine
from sqlalchemy import text
from telegram_agent import TelegramAgent


class ConversationState:
    """Tracks conversation state for a data quality issue"""

    def __init__(self, db_session, issue_id: str, issue_data: Dict):
        self.db = db_session
        self.issue_id = issue_id
        self.issue_type = issue_data.get('type')
        self.ticker = issue_data.get('ticker')
        self.proposed_fix = issue_data.get('proposed_fix', {})
        self.original_data = issue_data.get('original_data', {})
        self.final_fix = self.proposed_fix.copy()  # Start with proposed, user can modify
        self.messages = []

        # Load from database if exists
        self._load_from_db()

    def _load_from_db(self):
        """Load existing conversation from database"""
        result = self.db.execute(
            text("SELECT messages, proposed_fix, final_fix, original_data FROM data_quality_conversations WHERE issue_id = :issue_id"),
            {"issue_id": self.issue_id}
        ).fetchone()

        if result:
            self.messages = result[0] if result[0] else []
            self.proposed_fix = result[1] if result[1] else {}
            self.final_fix = result[2] if result[2] else self.proposed_fix.copy()
            if result[3]:
                self.original_data = result[3]

    def save(self):
        """Save conversation state to database"""
        self.db.execute(
            text("""
                INSERT INTO data_quality_conversations
                (issue_id, issue_type, ticker, messages, proposed_fix, final_fix, status)
                VALUES (:issue_id, :issue_type, :ticker, :messages, :proposed_fix, :final_fix, 'active')
                ON CONFLICT (issue_id) DO UPDATE SET
                    messages = EXCLUDED.messages,
                    final_fix = EXCLUDED.final_fix
            """),
            {
                "issue_id": self.issue_id,
                "issue_type": self.issue_type,
                "ticker": self.ticker,
                "messages": json.dumps(self.messages),
                "proposed_fix": json.dumps(self.proposed_fix),
                "final_fix": json.dumps(self.final_fix)
            }
        )
        self.db.commit()

    def add_message(self, role: str, content: str):
        """Add message to conversation history"""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        self.save()

    def update_final_fix(self, field: str, value: any):
        """Update the final fix with user's modification"""
        self.final_fix[field] = value
        self.save()

    def mark_completed(self, status: str, learning_notes: str = None):
        """Mark conversation as completed"""
        self.db.execute(
            text("""
                UPDATE data_quality_conversations
                SET status = :status,
                    completed_at = NOW(),
                    learning_notes = :learning_notes
                WHERE issue_id = :issue_id
            """),
            {
                "issue_id": self.issue_id,
                "status": status,
                "learning_notes": learning_notes
            }
        )
        self.db.commit()


class TelegramApprovalListener:
    """Listens for Telegram approvals and triggers fixes with conversational interface

    REFACTORED: Now uses TelegramAgent for all communication
    """

    def __init__(self):
        # Use centralized TelegramAgent for all communication
        self.telegram = TelegramAgent()

        # Expose attributes for backward compatibility
        self.chat_id = self.telegram.chat_id
        self.bot_token = self.telegram.bot_token
        self.ai_client = self.telegram.ai_client
        self.state_file = self.telegram.state_file

        # Legacy compatibility - map to telegram agent state
        self.pending_approvals = {}  # Track pending fix requests
        self.active_conversations = {}  # issue_id -> ConversationState

        # Load state from file if exists
        self.load_state()

    def load_state(self):
        """Load last update ID from state file (delegates to TelegramAgent)"""
        try:
            # TelegramAgent already loaded state in __init__
            # Just sync our pending_approvals from it
            self.pending_approvals = self.telegram.state.get('pending_approvals', {})
            print(f"📂 Loaded state: last_update_id={self.telegram.state.get('last_update_id')}")
        except Exception as e:
            print(f"⚠️  Could not load state: {e}")

    def save_state(self):
        """Save last update ID to state file (delegates to TelegramAgent)"""
        try:
            # Update pending_approvals in telegram agent's state
            self.telegram.state['pending_approvals'] = self.pending_approvals
            self.telegram.save_state()
        except Exception as e:
            print(f"⚠️  Could not save state: {e}")

    def get_updates(self) -> List[Dict]:
        """Get new messages from Telegram (delegates to TelegramAgent)"""
        return self.telegram.get_updates(timeout=2)  # 2 second timeout for listener loop

    def format_before_after(self, original_data: Dict, final_fix: Dict, ticker: str) -> str:
        """Format before/after diff for display"""
        diff_lines = [f"📊 <b>Proposed Changes for {ticker}:</b>\n"]

        for field, new_value in final_fix.items():
            old_value = original_data.get(field)

            if old_value != new_value:
                diff_lines.append(f"• <b>{field}</b>:")
                diff_lines.append(f"  Before: {old_value}")
                diff_lines.append(f"  After:  {new_value}\n")

        return "\n".join(diff_lines)

    def chat_with_claude(self, user_message: str, conversation: ConversationState) -> str:
        """Chat with Claude about the data quality issue"""
        if not self.ai_client:
            return "❌ Conversational features disabled - DEEPSEEK_API_KEY not set"

        # Build context for Claude
        system_prompt = f"""You are a data quality assistant helping review and approve fixes for a SPAC research database.

Current Issue:
- Type: {conversation.issue_type}
- Ticker: {conversation.ticker}
- Original Data: {json.dumps(conversation.original_data, indent=2)}
- Proposed Fix: {json.dumps(conversation.proposed_fix, indent=2)}
- Current Final Fix: {json.dumps(conversation.final_fix, indent=2)}

Help the user understand the proposed changes, answer questions, and modify the fix as needed.
Be concise and factual. When showing changes, use before/after format."""

        # Build message history (last 10 messages for context)
        messages = [{"role": "system", "content": system_prompt}]
        recent_messages = conversation.messages[-10:] if len(conversation.messages) > 10 else conversation.messages
        messages.extend([{"role": msg["role"], "content": msg["content"]} for msg in recent_messages])
        messages.append({"role": "user", "content": user_message})

        try:
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.3,
                max_tokens=1000
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ Error chatting with Claude: {str(e)}"

    def process_conversation_command(self, message_text: str, username: str, db) -> Tuple[Optional[str], Optional[str]]:
        """
        Process conversational commands

        Returns: (action, response_text)
        - action: 'approve', 'skip', 'chat', or None
        - response_text: Text to send back to user
        """
        text = message_text.strip()
        text_upper = text.upper()
        words = text_upper.split()

        # Check for BATCH APPROVE commands first (before single approve)
        if any(word in ['APPROVE', 'APPROVED'] for word in words):
            # Check for "APPROVE ALL [PATTERN]" or "APPROVE [PATTERN]"

            # APPROVE ALL (everything)
            if 'ALL' in text_upper:
                # Check if there's a pattern after ALL
                remaining = text_upper.replace('APPROVE', '').replace('APPROVED', '').replace('ALL', '').strip()

                if not remaining:
                    # Just "APPROVE ALL" - approve everything
                    return ('batch_approve_all', None)
                else:
                    # "APPROVE ALL [PATTERN]" - approve by pattern
                    return ('batch_approve_pattern', remaining)

            # APPROVE [PATTERN] (without ALL keyword)
            elif len(words) > 1:
                # Extract pattern (everything after APPROVE/APPROVED)
                pattern = text_upper
                for keyword in ['APPROVE', 'APPROVED', 'YES', 'APPLY']:
                    pattern = pattern.replace(keyword, '', 1).strip()

                # Check if it looks like a pattern (multi-word or specific keywords)
                pattern_keywords = ['TRUST', 'CASH', 'VALUE', 'DEAL', 'STATUS', 'DATE', 'RANGE']
                if any(kw in pattern for kw in pattern_keywords):
                    return ('batch_approve_pattern', pattern)

            # Single word APPROVE - approve current issue only
            if len(words) == 1 or (len(words) == 2 and words[1] in ['IT', 'THIS']):
                return ('approve', None)

        # Check for NEXT command (process next item in queue)
        if any(keyword in text_upper for keyword in ['NEXT', 'SKIP', 'IGNORE']):
            return ('next', "⏭️  Moving to next issue...")

        # Check for STOP command (stop processing queue)
        if any(keyword in text_upper for keyword in ['STOP', 'CANCEL', 'QUIT']):
            return ('stop', "🛑 Stopped processing queue")

        # Check for "show changes" or "what will change"
        if any(phrase in text.lower() for phrase in ['show changes', 'what will change', 'show me', 'what changes']):
            # Find active conversation
            active_conv = self._get_active_conversation(db)
            if active_conv:
                diff = self.format_before_after(
                    active_conv.original_data,
                    active_conv.final_fix,
                    active_conv.ticker
                )
                return ('chat', diff)
            else:
                return ('chat', "No active data quality issue to review")

        # Check for "change [field] to [value]" pattern
        change_patterns = [
            r'change (\w+) to (.+)',
            r'set (\w+) to (.+)',
            r'update (\w+) to (.+)'
        ]

        for pattern in change_patterns:
            import re
            match = re.search(pattern, text.lower())
            if match:
                field = match.group(1)
                value = match.group(2).strip()

                # Find active conversation and update
                active_conv = self._get_active_conversation(db)
                if active_conv:
                    # Parse value (remove quotes if present)
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]

                    # Handle NULL
                    if value.upper() == 'NULL':
                        value = None

                    active_conv.update_final_fix(field, value)
                    active_conv.add_message("user", f"Changed {field} to {value}")

                    # Show updated diff
                    diff = self.format_before_after(
                        active_conv.original_data,
                        active_conv.final_fix,
                        active_conv.ticker
                    )
                    return ('chat', f"✅ Updated proposal:\n\n{diff}")
                else:
                    return ('chat', "No active data quality issue to modify")

        # Check for control commands (work even without active conversation)
        text_lower = text.lower()

        # Command: Queue ALL data quality issues
        if ('queue' in text_lower and ('trust' in text_lower or 'data' in text_lower or 'issues' in text_lower)) or \
           text_lower.strip() in ['queue', 'queue issues', 'queue all']:
            return ('queue_all_issues', None)

        # Command: Auto-fix trust issues
        if ('auto' in text_lower or 'fix' in text_lower) and 'trust' in text_lower:
            return ('auto_fix_trust', None)

        # Command: Skip for now
        if 'skip for now' in text_lower or text_lower.strip() in ['skip', 'skip it', 'skip all']:
            return ('skip_all', "✅ Skipping remaining issues")

        # Command: Run validation
        if 'run validation' in text_lower or 'check data' in text_lower:
            return ('run_validation', None)

        # Otherwise, treat as conversational query
        active_conv = self._get_active_conversation(db)
        if active_conv:
            claude_response = self.chat_with_claude(text, active_conv)
            active_conv.add_message("user", text)
            active_conv.add_message("assistant", claude_response)
            return ('chat', claude_response)
        else:
            # No active conversation - check for old-style approval
            return (self.process_approval_response(text, username), None)

    def _get_active_conversation(self, db) -> Optional[ConversationState]:
        """Get the most recent active conversation"""
        result = db.execute(
            text("""
                SELECT issue_id, issue_type, ticker, proposed_fix, messages, original_data
                FROM data_quality_conversations
                WHERE status = 'active'
                ORDER BY started_at DESC
                LIMIT 1
            """)
        ).fetchone()

        if result:
            issue_data = {
                'type': result[1],
                'ticker': result[2],
                'proposed_fix': result[3] if result[3] else {},
                'original_data': result[5] if result[5] else {}
            }

            # Create conversation state
            conv = ConversationState(db, result[0], issue_data)
            return conv

        return None

    def process_approval_response(self, message_text: str, username: str) -> Optional[str]:
        """
        Process user's approval/rejection response (legacy method)

        Returns: action to take ('approve', 'skip', 'manual', or None)
        """
        text = message_text.strip().upper()

        # Check for approval keywords (standalone or at start)
        # Must be whole word to avoid matching "fix" in "The fix should be..."
        words = text.split()
        approval_keywords = ['APPROVE', 'YES', 'APPROVED']
        if any(word in approval_keywords for word in words):
            return 'approve'

        # Check for skip keywords
        if any(keyword in text for keyword in ['SKIP', 'IGNORE']):
            return 'skip'

        # Check for manual keywords
        if 'MANUAL' in text:
            return 'manual'

        return None

    def _parse_value_for_field(self, field: str, value, spac_obj) -> any:
        """
        Parse value to correct type based on field type

        Handles:
        - Strings like "<= $345.3M" -> 345300000.0
        - Strings like "NULL" -> None
        - Already correct types -> pass through
        """
        import re
        from datetime import datetime

        # Handle NULL
        if value is None or (isinstance(value, str) and value.upper() == 'NULL'):
            return None

        # Get the column type from the SPAC model
        column_type = type(getattr(spac_obj, field)).__name__ if hasattr(spac_obj, field) else None

        # If value is already correct type, return as-is
        if column_type and type(value).__name__ == column_type:
            return value

        # Parse float/numeric fields
        if column_type in ['float', 'Decimal', 'int'] or field in ['trust_cash', 'trust_value', 'price', 'premium']:
            if isinstance(value, str):
                # Extract numeric value from strings like "<= $345.3M" or "$345.3M"
                # Remove currency symbols and operators
                clean_value = re.sub(r'[<>=\$,]', '', value.split('(')[0].strip())

                # Handle M (millions) suffix
                if 'M' in clean_value.upper():
                    clean_value = clean_value.upper().replace('M', '')
                    try:
                        return float(clean_value) * 1_000_000
                    except:
                        return None

                # Handle B (billions) suffix
                if 'B' in clean_value.upper():
                    clean_value = clean_value.upper().replace('B', '')
                    try:
                        return float(clean_value) * 1_000_000_000
                    except:
                        return None

                # Plain numeric string
                try:
                    return float(clean_value) if clean_value else None
                except:
                    return None
            else:
                return float(value)

        # Parse datetime fields
        if column_type in ['datetime', 'date'] or field in ['ipo_date', 'announced_date', 'deadline_date']:
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value)
                except:
                    return None
            return value

        # Default: return as string
        return str(value) if value is not None else None

    def apply_fix(self, anomaly_type: str = None, conversation: ConversationState = None) -> Dict:
        """
        Apply the approved fix based on anomaly type

        Supports multiple fix types:
        - invalid_targets: Clear invalid targets
        - type_errors: Fix Decimal/Float mismatches
        - date_errors: Fix date format issues
        - trust_errors: Trigger 424B4 re-scraping
        - status_inconsistency: Research and fix deal status
        """
        print(f"\n🔧 Applying approved fix for: {anomaly_type or 'default'}...")

        # Import at top of method to avoid scoping issues
        from database import SessionLocal as DB, SPAC

        # If conversation provided, use final_fix from conversation
        if conversation:
            final_fix = conversation.final_fix
            ticker = conversation.ticker

            # Apply the fix based on conversation data
            db = DB()
            try:
                spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
                if spac:
                    fixed_fields = []
                    for field, value in final_fix.items():
                        if hasattr(spac, field):
                            # Parse value to correct type based on column type
                            parsed_value = self._parse_value_for_field(field, value, spac)
                            setattr(spac, field, parsed_value)
                            fixed_fields.append(field)

                    db.commit()

                    # Mark conversation as completed with learning notes
                    learning_notes = f"User approved fix for {ticker}. Modified fields: {', '.join(fixed_fields)}"
                    conversation.mark_completed('approved', learning_notes)

                    return {
                        'status': 'auto_fixed',
                        'fix_type': conversation.issue_type,
                        'fixed': 1,
                        'failed': 0,
                        'fields_modified': fixed_fields
                    }
            finally:
                db.close()

        # Load pending approval state (legacy path)
        approval_state_file = '/home/ubuntu/spac-research/.data_quality_approvals.json'
        approval_state = {}

        if os.path.exists(approval_state_file):
            with open(approval_state_file, 'r') as f:
                approval_state = json.load(f)

        # Find matching approval
        matching_approval = None
        approval_id = None

        if anomaly_type:
            # Find most recent approval for this anomaly type
            for aid, approval in approval_state.items():
                if approval['anomaly_type'] == anomaly_type and approval['status'] == 'pending':
                    matching_approval = approval
                    approval_id = aid
                    break

        if not matching_approval:
            # No pending approval found for this anomaly type
            print(f"⚠️  No pending approval found for anomaly_type: {anomaly_type}")
            return {"status": "error", "message": f"No pending approval found for {anomaly_type}"}

        # Extract fix parameters
        fix_params = matching_approval.get('fix_parameters', {})
        fix_type = fix_params.get('fix_type')
        affected_spacs = matching_approval.get('affected_spacs', [])

        result = {}

        # Route to appropriate fixer based on fix type
        if fix_type == 'invalid_targets':
            # Clear invalid targets
            db = DB()
            try:
                fixed = 0
                for ticker in affected_spacs:
                    spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
                    if spac and spac.target:
                        spac.target = None
                        spac.deal_status = 'SEARCHING'
                        fixed += 1
                db.commit()
                result = {'status': 'auto_fixed', 'fix_type': 'invalid_targets', 'fixed': fixed, 'failed': 0}
            finally:
                db.close()

        elif fix_type in ['type_errors', 'date_errors', 'trust_errors']:
            # Use DataQualityFixerAgent
            from agents.data_quality_fixer_agent import DataQualityFixerAgent

            fixer = DataQualityFixerAgent(auto_commit=fix_params.get('auto_commit', True))

            if fix_type == 'type_errors':
                fixed_count = fixer.fix_decimal_float_mismatch()
                result = {'status': 'auto_fixed', 'fix_type': 'type_errors', 'fixed': fixed_count, 'failed': 0}

            elif fix_type == 'date_errors':
                fixed_count = fixer.fix_expected_close_dates()
                result = {'status': 'auto_fixed', 'fix_type': 'date_errors', 'fixed': fixed_count, 'failed': 0}

            elif fix_type == 'trust_errors':
                trust_result = fixer.fix_trust_cash_batch(max_spacs=10, auto_approve=True)
                result = {'status': 'auto_fixed', 'fix_type': 'trust_errors', **trust_result}

            fixer.close()

        else:
            result = {'status': 'unknown_fix_type', 'fix_type': fix_type}

        # Mark approval as completed
        if approval_id and approval_state:
            approval_state[approval_id]['status'] = 'completed'
            approval_state[approval_id]['completed_at'] = datetime.now().isoformat()
            approval_state[approval_id]['result'] = result

            with open(approval_state_file, 'w') as f:
                json.dump(approval_state, f, indent=2)

        return result

    def send_message(self, text: str):
        """Send message to Telegram (delegates to TelegramAgent)"""
        return self.telegram.send_message(text)

    def process_updates(self, updates: List[Dict]):
        """Process incoming Telegram messages"""
        db = SessionLocal()

        try:
            for update in updates:
                # Update last_update_id
                self.last_update_id = update['update_id']

                # Check if it's a message
                if 'message' not in update:
                    continue

                message = update['message']

                # Only process messages from our chat
                if str(message['chat']['id']) != str(self.chat_id):
                    continue

                # Get message details
                message_text = message.get('text', '')
                username = message.get('from', {}).get('username', 'Unknown')
                message_date = datetime.fromtimestamp(message['date'])

                # Ignore messages older than 5 minutes
                if datetime.now() - message_date > timedelta(minutes=5):
                    continue

                # Process conversational command
                action, response = self.process_conversation_command(message_text, username, db)

                # Handle BATCH APPROVE ALL
                if action == 'batch_approve_all':
                    print(f"\n✅ BATCH APPROVE ALL RECEIVED from @{username}")
                    queue = ValidationIssueQueue()
                    count = queue.batch_approve_all()

                    response = f"""✅ <b>BATCH APPROVED ALL ISSUES</b>

Approved <b>{count}</b> pending issue(s)

The orchestrator will process these on next run.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All issues have been approved!"""

                    send_telegram_alert(response)
                    self.last_processed_update_id = update_id
                    continue

                # Handle BATCH APPROVE BY PATTERN
                elif action == 'batch_approve_pattern':
                    pattern = response if response else ""
                    print(f"\n✅ BATCH APPROVE PATTERN RECEIVED from @{username}")
                    print(f"   Pattern: '{pattern}'")

                    queue = ValidationIssueQueue()
                    count = queue.batch_approve_by_pattern(pattern)

                    if count > 0:
                        response_msg = f"""✅ <b>BATCH APPROVED BY PATTERN</b>

Pattern: <code>{pattern}</code>
Approved: <b>{count}</b> issue(s)

The orchestrator will process these on next run.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Continue with remaining issues? Reply APPROVE for next pattern."""
                    else:
                        response_msg = f"""⚠️ <b>NO MATCHES FOUND</b>

Pattern: <code>{pattern}</code>

No pending issues match this pattern.

Available patterns:
• Trust Cash
• Trust Value
• Deal Status"""

                    send_telegram_alert(response_msg)
                    self.last_processed_update_id = update_id

                    # If more issues remain, send next one
                    queue.send_current_issue()
                    continue

                elif action == 'approve':
                    print(f"\n✅ APPROVAL RECEIVED from @{username}")
                    print(f"   Message: '{message_text}'")
                    print(f"   Time: {message_date.strftime('%Y-%m-%d %H:%M:%S')}")

                    # Check if there's an active conversation
                    active_conv = self._get_active_conversation(db)

                    if active_conv:
                        # Apply fix from conversation
                        result = self.apply_fix(conversation=active_conv)

                        # Build response
                        if result.get('status') == 'auto_fixed':
                            fields_modified = result.get('fields_modified', [])
                            response = f"""✅ <b>FIX APPLIED</b>

Ticker: {active_conv.ticker}
Modified Fields: {', '.join(fields_modified)}

Conversation logged for learning."""
                        else:
                            response = f"⚠️  Fix failed: {result.get('status', 'unknown error')}"

                    else:
                        # Legacy path - extract anomaly type from message
                        anomaly_type = None
                        message_upper = message_text.upper()

                        # Check for specific anomaly type in message
                        if 'INVALID_TARGET' in message_upper or 'INVALID TARGET' in message_upper:
                            anomaly_type = 'invalid_target'
                        elif 'TYPE_ERROR' in message_upper or 'TYPE ERROR' in message_upper:
                            anomaly_type = 'type_error'
                        elif 'DATE' in message_upper:
                            anomaly_type = 'date_format_error'
                        elif 'TRUST' in message_upper:
                            anomaly_type = 'trust_cash_error'
                        elif 'STATUS' in message_upper:
                            anomaly_type = 'deal_status_inconsistency'

                        # Apply fix
                        result = self.apply_fix(anomaly_type)

                        # Build response based on fix type
                        if result.get('status') == 'auto_fixed':
                            fix_type = result.get('fix_type', 'unknown')
                            fixed_count = result.get('fixed', 0)
                            failed_count = result.get('failed', 0)

                            if fix_type == 'invalid_targets':
                                response = f"""✅ <b>FIX APPLIED</b>

Fixed: {fixed_count} SPACs
Failed: {failed_count} SPACs

The invalid targets have been cleared and reset to SEARCHING status.
Re-run deal_announcement_scraper.py to extract correct targets."""

                            elif fix_type == 'type_errors':
                                response = f"""✅ <b>TYPE ERRORS FIXED</b>

Fixed: {fixed_count} Decimal/Float mismatches
Failed: {failed_count}"""

                            elif fix_type == 'date_errors':
                                response = f"""✅ <b>DATE ERRORS FIXED</b>

Fixed: {fixed_count} date format issues
Failed: {failed_count}"""

                            elif fix_type == 'trust_errors':
                                response = f"""✅ <b>TRUST CASH ERRORS FIXED</b>

Errors found: {result.get('errors_found', 0)}
Rescraped: {result.get('rescraped', 0)}"""

                            else:
                                response = f"""✅ <b>FIX APPLIED</b>

Type: {fix_type}
Fixed: {fixed_count}
Failed: {failed_count}"""

                        elif result.get('status') == 'clean':
                            response = "✅ No issues found (already fixed or resolved)"

                        else:
                            response = f"⚠️  Fix failed: {result.get('status', 'unknown error')}"

                    self.send_message(response)

                    # After approval, check if there are more issues in queue
                    try:
                        from validation_issue_queue import ValidationIssueQueue
                        queue = ValidationIssueQueue()
                        if queue.is_awaiting_response():
                            queue.mark_current_resolved('approved')

                            if queue.has_more_issues():
                                queue.send_current_issue()
                                stats = queue.get_stats()
                                print(f"   Auto-sending next issue {stats['current']}/{stats['total']}")
                    except Exception as e:
                        print(f"   Warning: Could not auto-advance queue: {e}")

                elif action == 'next':
                    print(f"\n⏭️  NEXT requested by @{username}")
                    # Load queue and send next issue
                    try:
                        from validation_issue_queue import ValidationIssueQueue
                        queue = ValidationIssueQueue()
                        queue.mark_current_resolved('skipped')

                        if queue.has_more_issues():
                            queue.send_current_issue()
                            stats = queue.get_stats()
                            print(f"   Sent issue {stats['current']}/{stats['total']}")
                        else:
                            self.send_message("✅ Queue completed! No more issues.")
                    except Exception as e:
                        self.send_message(f"⚠️ Error processing next issue: {e}")

                elif action == 'stop':
                    print(f"\n🛑 STOP requested by @{username}")
                    try:
                        from validation_issue_queue import ValidationIssueQueue
                        queue = ValidationIssueQueue()
                        stats = queue.get_stats()
                        remaining = stats['remaining']

                        # Clear queue
                        queue.data['issues'] = []
                        queue.save_queue()

                        self.send_message(f"🛑 Stopped processing. {remaining} issues skipped.")
                    except Exception as e:
                        self.send_message(f"⚠️ Error stopping queue: {e}")

                elif action == 'chat':
                    print(f"\n💬 CHAT from @{username}: {message_text[:50]}...")
                    if response:
                        self.send_message(response)

                elif action == 'manual':
                    print(f"\n👤 MANUAL REVIEW requested by @{username}")
                    response = """👤 <b>Manual Review Mode</b>

No automatic fix will be applied.
Use the following commands:

<b>Check issues:</b>
python3 data_quality_orchestrator.py --dry-run

<b>Apply fix manually:</b>
python3 data_quality_orchestrator.py --auto-fix

<b>View affected SPACs:</b>
python3 fix_invalid_targets.py
"""
                    self.send_message(response)

                elif action == 'queue_all_issues':
                    print(f"\n📋 QUEUE ALL ISSUES requested by @{username}")

                    try:
                        from validation_issue_queue import ValidationIssueQueue
                        from data_validator_core import DataValidatorAgent

                        # Check if there's already a queue in progress
                        queue = ValidationIssueQueue()

                        if queue.has_more_issues():
                            # Queue already exists - show current status instead of recreating
                            stats = queue.get_stats()
                            current_issue = queue.get_current_issue()

                            if current_issue:
                                ticker = current_issue.get('ticker', 'Unknown')
                                rule = current_issue.get('rule', 'Unknown')

                                self.send_message(f"""📋 <b>Queue Status</b>

Current: Issue {stats['current']}/{stats['total']}
Remaining: {stats['remaining']} issues

<b>Current Issue:</b>
{ticker}: {rule}

💡 Type 'next' to skip, 'approve' to fix, or 'stop' to clear queue.""")
                            else:
                                self.send_message(f"""📋 <b>Queue Status</b>

{stats['total']} issues in queue
Type 'next' to process next issue.""")
                        else:
                            # No queue in progress - create new one
                            self.send_message("🔄 Running validation and queueing ALL data quality issues...")

                            # Run validation to get all issues
                            validator = DataValidatorAgent()
                            all_issues = validator.validate_all_spacs()

                            # Filter to only CRITICAL and HIGH severity issues
                            important_issues = [
                                issue for issue in all_issues
                                if issue.get('severity') in ['CRITICAL', 'HIGH']
                            ]

                            if important_issues:
                                queue.add_issues(important_issues)
                                queue.send_current_issue()

                                stats = queue.get_stats()

                                # Count issues by type
                                issue_types = {}
                                for issue in important_issues:
                                    issue_type = issue.get('type', 'unknown')
                                    issue_types[issue_type] = issue_types.get(issue_type, 0) + 1

                                types_summary = ', '.join([f"{count} {itype}" for itype, count in issue_types.items()])

                                self.send_message(f"""✅ <b>Queued {stats['total']} data quality issues</b>

Issue breakdown: {types_summary}

Sent issue 1/{stats['total']} for review.""")
                            else:
                                self.send_message("✅ No critical data quality issues found!")

                    except Exception as e:
                        self.send_message(f"⚠️ Error queueing issues: {str(e)}")
                        print(f"Error: {e}")

                elif action == 'auto_fix_trust':
                    print(f"\n🔧 AUTO-FIX TRUST requested by @{username}")
                    self.send_message("🔄 Calling orchestrator to investigate and fix trust_cash issues...")

                    try:
                        # Import orchestrator and create task
                        import sys
                        from datetime import datetime as dt_datetime
                        sys.path.append('/home/ubuntu/spac-research')
                        from agent_orchestrator import Orchestrator, AgentTask, TaskPriority, TaskStatus

                        # Initialize orchestrator
                        orchestrator = Orchestrator()

                        self.send_message("🔍 Orchestrator initialized. Running data validator with auto-fix enabled...")

                        # Create data_validator task with auto_fix enabled
                        task = AgentTask(
                            task_id=f"trust_fix_{dt_datetime.now().strftime('%Y%m%d_%H%M%S')}",
                            agent_name="data_validator",
                            task_type="data_validation_with_autofix",
                            priority=TaskPriority.HIGH,
                            status=TaskStatus.PENDING,
                            created_at=dt_datetime.now(),
                            parameters={'auto_fix': True, 'focus': 'trust_cash'}
                        )

                        # Get the data_validator agent and execute task directly
                        data_validator_agent = orchestrator.agents['data_validator']
                        result_task = data_validator_agent.execute(task)

                        # Check result
                        if result_task.status == TaskStatus.COMPLETED:
                            result = result_task.result or {}
                            critical = result.get('critical', 0)
                            high = result.get('high', 0)
                            fixed = len(result.get('fixes_applied', []))

                            self.send_message(f"""✅ <b>ORCHESTRATOR FIX COMPLETE</b>

The orchestrator's data validator ran with auto-fix enabled.

Issues detected:
• CRITICAL: {critical}
• HIGH: {high}

✅ Auto-fixed {fixed} issues

The orchestrator investigated each trust_cash issue with AI analysis and applied appropriate fixes.""")
                        elif result_task.status == TaskStatus.FAILED:
                            self.send_message(f"⚠️ Orchestrator task failed: {result_task.error}")
                        else:
                            self.send_message(f"ℹ️ Orchestrator task status: {result_task.status.value}")

                    except Exception as e:
                        import traceback
                        error_details = traceback.format_exc()
                        self.send_message(f"⚠️ Error calling orchestrator: {str(e)}")
                        print(f"Error: {e}")
                        print(f"Traceback: {error_details}")

                elif action == 'skip_all':
                    print(f"\n⏭️  SKIP ALL requested by @{username}")
                    if response:
                        self.send_message(response)

                elif action == 'run_validation':
                    print(f"\n✅ RUN VALIDATION requested by @{username}")
                    self.send_message("🔄 Running validation and queueing issues...")

                    try:
                        from validation_issue_queue import ValidationIssueQueue
                        from data_validator_core import DataValidatorAgent

                        # Run validation to get all issues
                        validator = DataValidatorAgent()
                        all_issues = validator.validate_all_spacs()

                        # Filter to only CRITICAL and HIGH severity issues
                        important_issues = [
                            issue for issue in all_issues
                            if issue.get('severity') in ['CRITICAL', 'HIGH']
                        ]

                        if important_issues:
                            queue = ValidationIssueQueue()
                            queue.add_issues(important_issues)
                            queue.send_current_issue()

                            stats = queue.get_stats()

                            # Count issues by type
                            issue_types = {}
                            for issue in important_issues:
                                issue_type = issue.get('type', 'unknown')
                                issue_types[issue_type] = issue_types.get(issue_type, 0) + 1

                            types_summary = ', '.join([f"{count} {itype}" for itype, count in issue_types.items()])

                            self.send_message(f"""✅ <b>Validation Complete - Issues Queued</b>

Queued {stats['total']} issues for review

Issue breakdown: {types_summary}

Sent issue 1/{stats['total']} for review.""")
                        else:
                            self.send_message("✅ No critical data quality issues found!")

                    except Exception as e:
                        import traceback
                        error_details = traceback.format_exc()
                        self.send_message(f"⚠️ Error running validation: {str(e)}")
                        print(f"Error: {e}")
                        print(f"Traceback: {error_details}")

        finally:
            db.close()
            # Save state after processing
            self.save_state()

    def run(self, daemon=False):
        """Run the listener"""
        print("\n" + "="*80)
        print("TELEGRAM CONVERSATIONAL APPROVAL LISTENER")
        print("="*80)
        print(f"\n📱 Monitoring Telegram chat: {self.chat_id}")
        print(f"🤖 Bot: {self.bot_token[:10]}...")
        print(f"💾 State file: {self.state_file}")
        print(f"\n💬 Conversational Features:")
        print(f"   • 'show changes' - See before/after diff")
        print(f"   • 'change [field] to [value]' - Modify fix")
        print(f"   • Ask questions - Chat with Claude")
        print(f"   • 'APPROVE' - Apply final fix")
        print(f"   • 'SKIP' - Ignore issue")
        print("\nPress Ctrl+C to stop\n")

        if daemon:
            print("🔄 Running in daemon mode (background service)\n")

        try:
            while True:
                # Get new updates
                updates = self.get_updates()

                if updates:
                    print(f"\n📨 Received {len(updates)} update(s)")
                    self.process_updates(updates)

                # Sleep before next poll
                time.sleep(2)

        except KeyboardInterrupt:
            print("\n\n🛑 Listener stopped by user")
            self.save_state()
            print("💾 State saved\n")

        except Exception as e:
            print(f"\n❌ Listener error: {e}")
            self.save_state()
            raise


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Telegram Conversational Approval Listener')
    parser.add_argument('--daemon', action='store_true', help='Run as background daemon')
    parser.add_argument('--test', action='store_true', help='Test connection and exit')

    args = parser.parse_args()

    listener = TelegramApprovalListener()

    if args.test:
        # Test Telegram connection
        print("\n🧪 Testing Telegram connection...")

        try:
            response = requests.get(f"{listener.api_url}/getMe", timeout=10)
            if response.status_code == 200:
                bot_info = response.json()['result']
                print(f"✅ Connected to bot: @{bot_info['username']}")
                print(f"   Bot ID: {bot_info['id']}")
                print(f"   Bot name: {bot_info['first_name']}")
            else:
                print(f"❌ Connection failed: {response.status_code}")
        except Exception as e:
            print(f"❌ Connection error: {e}")

        return

    # Run listener
    listener.run(daemon=args.daemon)


if __name__ == "__main__":
    main()
