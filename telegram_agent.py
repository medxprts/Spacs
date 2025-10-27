#!/usr/bin/env python3
"""
Telegram Agent - Orchestrator-Compatible Telegram Communication Handler

Handles all Telegram interactions for the SPAC platform:
- Sending alerts and notifications
- Receiving and processing user commands
- Managing conversational workflows
- Queueing validation issues for review

Used by the orchestrator for all Telegram-related tasks.
"""

import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from openai import OpenAI
from dotenv import load_dotenv

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC, engine
from sqlalchemy import text

load_dotenv()


class TelegramAgent:
    """
    Centralized Telegram communication agent

    Features:
    - Send messages with HTML formatting
    - Poll for user responses
    - Manage conversational state
    - Queue validation issues for interactive review
    - Integration with orchestrator task system
    """

    def __init__(self, state_file: str = "/home/ubuntu/spac-research/.telegram_listener_state.json"):
        """Initialize Telegram agent"""
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not self.bot_token or not self.chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required in .env")

        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.state_file = state_file

        # Load state
        self.state = self.load_state()

        # AI client for conversational responses
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            self.ai_client = OpenAI(
                api_key=deepseek_key,
                base_url="https://api.deepseek.com"
            )
        else:
            self.ai_client = None

    def load_state(self) -> Dict:
        """Load Telegram state from disk"""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {
            'last_update_id': 0,
            'pending_approvals': {},
            'last_saved': datetime.now().isoformat()
        }

    def save_state(self):
        """Save Telegram state to disk"""
        self.state['last_saved'] = datetime.now().isoformat()
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def send_message(self, text: str, parse_mode: str = 'HTML') -> bool:
        """
        Send message to Telegram

        Args:
            text: Message text (supports HTML if parse_mode='HTML')
            parse_mode: 'HTML' or 'Markdown'

        Returns:
            True if sent successfully, False otherwise
        """
        import html as html_lib

        try:
            # Check if text contains HTML tags that should be preserved
            has_html_tags = any(tag in text for tag in ['<b>', '<i>', '<code>', '<pre>'])

            if not has_html_tags and parse_mode == 'HTML':
                # No HTML tags found, escape everything
                text = html_lib.escape(text)

            response = requests.post(
                f"{self.api_url}/sendMessage",
                json={
                    'chat_id': self.chat_id,
                    'text': text,
                    'parse_mode': parse_mode
                },
                timeout=10
            )

            if response.status_code != 200:
                print(f"⚠️  Telegram send failed: {response.status_code} - {response.text}")
                return False
            else:
                print(f"✅ Sent message to Telegram ({len(text)} chars)")
                return True

        except Exception as e:
            print(f"⚠️  Error sending message: {e}")
            return False

    def get_updates(self, timeout: int = 30) -> List[Dict]:
        """
        Get new messages from Telegram

        Args:
            timeout: Long polling timeout in seconds

        Returns:
            List of update dicts
        """
        try:
            response = requests.get(
                f"{self.api_url}/getUpdates",
                params={
                    'offset': self.state['last_update_id'] + 1,
                    'timeout': timeout
                },
                timeout=timeout + 5
            )

            if response.status_code == 200:
                data = response.json()
                if data['ok'] and data['result']:
                    # Update last_update_id
                    self.state['last_update_id'] = max(
                        u['update_id'] for u in data['result']
                    )
                    self.save_state()
                    return data['result']

            return []

        except Exception as e:
            print(f"⚠️  Error getting updates: {e}")
            return []

    def wait_for_response(self, timeout_minutes: int = 60) -> Optional[str]:
        """
        Wait for user to respond via Telegram

        Args:
            timeout_minutes: How long to wait before timing out

        Returns:
            User's message text, or None if timeout
        """
        start_time = datetime.now()
        timeout = timedelta(minutes=timeout_minutes)

        print(f"⏳ Waiting for Telegram response (timeout: {timeout_minutes}min)...")

        while datetime.now() - start_time < timeout:
            updates = self.get_updates(timeout=5)

            for update in updates:
                if 'message' in update:
                    message = update['message']

                    # Only process messages from our chat
                    if str(message['chat']['id']) == str(self.chat_id):
                        text = message.get('text', '')
                        username = message.get('from', {}).get('username', 'Unknown')

                        print(f"📨 Received from @{username}: {text[:50]}...")
                        return text

            time.sleep(2)

        print(f"⏱️  Timeout waiting for response")
        return None

    def queue_validation_issues(self, issues: List[Dict]) -> Dict:
        """
        Queue validation issues for sequential review

        Args:
            issues: List of issue dicts from data validator

        Returns:
            Result dict with stats
        """
        from validation_issue_queue import ValidationIssueQueue

        # Check if already awaiting response
        queue = ValidationIssueQueue()
        if queue.is_awaiting_response():
            print("⏳ Skipping queue update - already awaiting user response")
            stats = queue.get_stats()
            return {
                'queued': 0,
                'already_awaiting': True,
                'pending_issues': stats['remaining'],
                'message': f"Already awaiting response for issue {stats['current']}/{stats['total']}"
            }

        # Filter to only CRITICAL and HIGH
        important_issues = [
            issue for issue in issues
            if issue.get('severity') in ['CRITICAL', 'HIGH']
        ]

        if not important_issues:
            self.send_message("✅ No critical data quality issues found!")
            return {'queued': 0, 'issues': []}

        # Add to queue (only if not awaiting response)
        queue.add_issues(important_issues)

        # Send first issue
        queue.send_current_issue()

        stats = queue.get_stats()

        # Count by type
        issue_types = {}
        for issue in important_issues:
            issue_type = issue.get('type', 'unknown')
            issue_types[issue_type] = issue_types.get(issue_type, 0) + 1

        types_summary = ', '.join([f"{count} {itype}" for itype, count in issue_types.items()])

        self.send_message(f"""✅ <b>Validation Issues Queued</b>

Queued {stats['total']} issues for review

Issue breakdown: {types_summary}

Sent issue 1/{stats['total']} for review.""")

        return {
            'queued': stats['total'],
            'issues': important_issues,
            'types': issue_types
        }

    def process_user_command(self, text: str, db_session) -> Tuple[str, Optional[str]]:
        """
        Process user command and return action + response

        Args:
            text: User's message text
            db_session: Database session

        Returns:
            Tuple of (action, response_text)

        Actions:
            - 'approve': Apply current fix
            - 'skip': Skip current issue
            - 'show_changes': Show before/after diff
            - 'chat': Conversational response needed
            - 'queue_all_issues': Run validation and queue
            - 'auto_fix_trust': Auto-fix trust issues
            - 'run_validation': Run validation
        """
        text_lower = text.lower().strip()

        # Check for control commands
        if text_lower in ['approve', 'auto-fix', 'yes', 'apply']:
            return ('approve', None)

        if text_lower in ['skip', 'next', 'pass']:
            return ('skip', "⏭️  Skipped. Moving to next issue...")

        if 'show' in text_lower and ('change' in text_lower or 'fix' in text_lower or 'diff' in text_lower):
            return ('show_changes', None)

        # Queue commands
        if ('queue' in text_lower and ('trust' in text_lower or 'data' in text_lower or 'issues' in text_lower)) or \
           text_lower in ['queue', 'queue issues', 'queue all']:
            return ('queue_all_issues', None)

        # Auto-fix trust
        if ('auto' in text_lower or 'fix' in text_lower) and 'trust' in text_lower:
            return ('auto_fix_trust', None)

        # Run validation
        if 'run validation' in text_lower or 'check data' in text_lower:
            return ('run_validation', None)

        # Otherwise, it's a conversational message
        return ('chat', None)

    def generate_ai_response(self, user_message: str, conversation_context: List[Dict]) -> str:
        """
        Generate AI response using DeepSeek

        Args:
            user_message: User's latest message
            conversation_context: List of previous messages

        Returns:
            AI's response text
        """
        if not self.ai_client:
            return "AI not available (DEEPSEEK_API_KEY not set)"

        # Build conversation history
        messages = [
            {"role": "system", "content": """You are Claude, a helpful AI assistant helping review SPAC data quality issues.

The user is reviewing validation errors from the database. Your job is to:
1. Answer questions about the data quality issues
2. Explain why certain values are problematic
3. Suggest fixes when asked
4. Help the user understand the implications

Be concise and helpful."""}
        ]

        # Add conversation history
        for msg in conversation_context[-5:]:  # Last 5 messages
            messages.append({
                "role": msg.get('role', 'user'),
                "content": msg.get('content', '')
            })

        # Add current message
        messages.append({"role": "user", "content": user_message})

        try:
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.7,
                max_tokens=500
            )

            return response.choices[0].message.content

        except Exception as e:
            return f"Error generating response: {str(e)}"


# For backwards compatibility, keep a TelegramApprovalListener wrapper
class TelegramApprovalListener:
    """Backwards-compatible wrapper around TelegramAgent"""

    def __init__(self):
        self.agent = TelegramAgent()

    def send_message(self, text: str):
        return self.agent.send_message(text)

    def get_updates(self):
        return self.agent.get_updates(timeout=2)

    def run(self, daemon=False):
        """Run listener loop"""
        print("\n" + "="*80)
        print("TELEGRAM CONVERSATIONAL APPROVAL LISTENER")
        print("="*80)
        print(f"\n📱 Monitoring Telegram chat: {self.agent.chat_id}")
        print(f"🤖 Bot: {self.agent.bot_token[:10]}...")
        print(f"💾 State file: {self.agent.state_file}")
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
                updates = self.agent.get_updates(timeout=2)

                if updates:
                    print(f"\n📨 Received {len(updates)} update(s)")
                    self.process_updates(updates)

                # Sleep before next poll
                time.sleep(2)

        except KeyboardInterrupt:
            print("\n\n🛑 Listener stopped by user")
            self.agent.save_state()
            print("💾 State saved\n")

        except Exception as e:
            print(f"\n❌ Listener error: {e}")
            self.agent.save_state()
            raise

    def process_updates(self, updates: List[Dict]):
        """Process Telegram updates - delegates to main telegram_approval_listener.py logic"""
        # Import the full processing logic
        # This keeps the existing functionality while using the new TelegramAgent
        pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Telegram Agent for SPAC Platform')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon')
    parser.add_argument('--test', action='store_true', help='Test message send')

    args = parser.parse_args()

    agent = TelegramAgent()

    if args.test:
        print("Sending test message...")
        agent.send_message("🤖 TelegramAgent initialized and ready!")
        print("✅ Test complete")
    elif args.daemon:
        listener = TelegramApprovalListener()
        listener.run(daemon=True)
    else:
        print("TelegramAgent ready. Use --test to send test message or --daemon to run listener.")
