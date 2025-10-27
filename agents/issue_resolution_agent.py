#!/usr/bin/env python3
"""
Issue Resolution Agent

Monitors user-submitted issues and suggests fixes using AI analysis.
Sends proposed solutions via Telegram for human approval before implementation.

This demonstrates the ultimate agentic AI pattern:
1. User reports issue → 2. AI analyzes → 3. AI suggests fix → 4. Human approves → 5. System implements
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from database import SessionLocal, SPAC, UserIssue
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class IssueResolutionAgent:
    """
    AI Agent that analyzes user-submitted issues and suggests fixes

    Capabilities:
    - Analyzes bug reports and diagnoses root causes
    - Suggests code fixes for bugs
    - Proposes implementation plans for feature requests
    - Investigates data quality issues and recommends corrections
    - Sends Telegram notifications with proposed solutions
    """

    def __init__(self):
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.deepseek_api_key:
            raise Exception("DEEPSEEK_API_KEY required")

        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        self.ai_client = OpenAI(
            api_key=self.deepseek_api_key,
            base_url="https://api.deepseek.com"
        )

    def analyze_issue(self, issue: UserIssue) -> Dict:
        """
        Use AI to analyze the issue and suggest a solution

        Returns:
            Dict with keys:
            - diagnosis: Root cause analysis
            - suggested_fix: Proposed solution
            - implementation_plan: Step-by-step plan
            - priority_recommendation: Suggested priority (low/medium/high/critical)
            - estimated_effort: Time estimate (minutes)
        """
        print(f"\n🔍 Analyzing Issue #{issue.id}: {issue.title}")

        # Build context based on issue type
        context = self._build_issue_context(issue)

        prompt = f"""You are an expert software engineer analyzing a user-reported issue in a SPAC research platform.

Issue Details:
- **ID:** #{issue.id}
- **Type:** {issue.issue_type}
- **Title:** {issue.title}
- **Description:** {issue.description}
- **Related SPAC:** {issue.ticker_related if issue.ticker_related else 'N/A'}
- **Page/Location:** {issue.page_location if issue.page_location else 'N/A'}
- **Submitted:** {issue.submitted_at}

Platform Context:
{context}

Your task:
1. Diagnose the root cause (if bug) or understand the request (if feature)
2. Suggest a specific, actionable fix or implementation plan
3. Provide step-by-step implementation instructions
4. Recommend priority level
5. Estimate effort in minutes

Respond with ONLY valid JSON in this format:
{{
    "diagnosis": "Brief analysis of the issue and root cause",
    "suggested_fix": "Specific solution or feature implementation approach",
    "implementation_plan": [
        "Step 1: ...",
        "Step 2: ...",
        "Step 3: ..."
    ],
    "priority_recommendation": "low|medium|high|critical",
    "estimated_effort_minutes": 30,
    "files_to_modify": [
        "path/to/file1.py",
        "path/to/file2.py"
    ],
    "testing_notes": "How to verify the fix works"
}}

Be specific and actionable. Include actual file paths, function names, and code snippets where applicable."""

        try:
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an expert software engineer analyzing bugs and feature requests. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=2000
            )

            response_text = response.choices[0].message.content.strip()

            # Strip markdown if present
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                if lines[0].startswith('```'):
                    lines = lines[1:]
                if lines and lines[-1].strip() == '```':
                    lines = lines[:-1]
                response_text = '\n'.join(lines).strip()

            import json
            analysis = json.loads(response_text)

            print(f"   ✓ Analysis complete")
            print(f"   Priority: {analysis.get('priority_recommendation', 'medium')}")
            print(f"   Estimated effort: {analysis.get('estimated_effort_minutes', 'N/A')} minutes")

            return analysis

        except Exception as e:
            print(f"   ⚠️  Error analyzing issue: {e}")
            return {
                'diagnosis': 'Error analyzing issue',
                'suggested_fix': 'Manual review required',
                'implementation_plan': ['Review issue manually'],
                'priority_recommendation': 'medium',
                'estimated_effort_minutes': 60,
                'files_to_modify': [],
                'testing_notes': 'N/A'
            }

    def _build_issue_context(self, issue: UserIssue) -> str:
        """Build relevant context for AI based on issue details"""

        context_parts = []

        context_parts.append("**Platform:** SPAC Research Platform (Streamlit + FastAPI + PostgreSQL)")
        context_parts.append("**Tech Stack:** Python, SQLAlchemy, Streamlit, DeepSeek AI, SEC Edgar API")

        # Add SPAC context if ticker mentioned
        if issue.ticker_related:
            db = SessionLocal()
            try:
                spac = db.query(SPAC).filter(SPAC.ticker == issue.ticker_related).first()
                if spac:
                    context_parts.append(f"\n**Related SPAC Data:**")
                    context_parts.append(f"- Ticker: {spac.ticker}")
                    context_parts.append(f"- Company: {spac.company}")
                    context_parts.append(f"- Deal Status: {spac.deal_status}")
                    context_parts.append(f"- Premium: {spac.premium}%")
                    context_parts.append(f"- Trust Value: ${spac.trust_value}")
            finally:
                db.close()

        # Add page-specific context
        if issue.page_location:
            page_contexts = {
                'AI Chat': 'spac_agent.py - DeepSeek-powered natural language query interface',
                'Live Deals': 'streamlit_app.py (📈 Live Deals section) - Shows SPACs with announced deals',
                'Pre-Deal SPACs': 'streamlit_app.py (🔍 Pre-Deal SPACs section) - Shows searching SPACs',
                'Analytics': 'streamlit_app.py (📊 Analytics section) - Market-wide statistics',
                'Pre-IPO Pipeline': 'pre_ipo_database.py + streamlit_app.py - Pre-IPO SPAC tracking'
            }
            if issue.page_location in page_contexts:
                context_parts.append(f"\n**Page Context:** {page_contexts[issue.page_location]}")

        # Add issue type-specific context
        if issue.issue_type == 'bug':
            context_parts.append("\n**Common Bug Sources:**")
            context_parts.append("- Database null values (trust_cash, premium, etc.)")
            context_parts.append("- SEC data parsing errors")
            context_parts.append("- Price update failures (yfinance, Alpha Vantage)")
            context_parts.append("- AI agent errors (DeepSeek API issues)")
        elif issue.issue_type == 'data_quality':
            context_parts.append("\n**Data Quality Checks:**")
            context_parts.append("- Trust value calculation: trust_cash / shares_outstanding")
            context_parts.append("- Premium calculation: (price - trust_value) / trust_value * 100")
            context_parts.append("- Trust cash should not exceed IPO proceeds")
            context_parts.append("- Validation agents: data_validator_agent.py, investigation_agent.py")

        return '\n'.join(context_parts)

    def send_telegram_notification(self, issue: UserIssue, analysis: Dict) -> bool:
        """
        Send Telegram notification with proposed solution

        Returns True if sent successfully
        """
        if not self.telegram_bot_token or not self.telegram_chat_id:
            print("   ⚠️  Telegram credentials not configured")
            return False

        try:
            import requests

            # Format implementation plan
            impl_plan = '\n'.join([f"  {step}" for step in analysis.get('implementation_plan', [])])

            # Format files to modify
            files = '\n'.join([f"  • {f}" for f in analysis.get('files_to_modify', [])])

            message = f"""🐛 <b>Issue Resolution Proposal</b>

<b>Issue #{issue.id}:</b> {issue.title}
<b>Type:</b> {issue.issue_type.replace('_', ' ').title()}
<b>Submitted:</b> {issue.submitted_at.strftime('%Y-%m-%d %H:%M')}

<b>📋 Diagnosis:</b>
{analysis.get('diagnosis', 'N/A')}

<b>💡 Suggested Fix:</b>
{analysis.get('suggested_fix', 'N/A')}

<b>📝 Implementation Plan:</b>
{impl_plan}

<b>📁 Files to Modify:</b>
{files if files else '  (None specified)'}

<b>🧪 Testing:</b>
{analysis.get('testing_notes', 'N/A')}

<b>⏱️ Estimated Effort:</b> {analysis.get('estimated_effort_minutes', 'N/A')} minutes
<b>🎯 Priority:</b> {analysis.get('priority_recommendation', 'medium').upper()}

---
<b>Action Required:</b> Review and approve this solution to proceed with implementation.
"""

            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }

            response = requests.post(url, json=payload)

            if response.status_code == 200:
                print(f"   ✅ Telegram notification sent successfully")
                return True
            else:
                print(f"   ⚠️  Telegram API error: {response.status_code}")
                return False

        except Exception as e:
            print(f"   ⚠️  Error sending Telegram notification: {e}")
            return False

    def process_new_issues(self):
        """
        Process all open issues that haven't been analyzed yet

        Workflow:
        1. Find open issues without resolution analysis
        2. Analyze each issue with AI
        3. Send Telegram notification with proposed fix
        4. Mark issue as 'in_progress' (awaiting approval)
        """
        db = SessionLocal()
        try:
            # Find open issues
            open_issues = db.query(UserIssue).filter(
                UserIssue.status == 'open'
            ).order_by(UserIssue.submitted_at).all()

            if not open_issues:
                print("📭 No new issues to process")
                return

            print(f"\n{'='*80}")
            print(f"ISSUE RESOLUTION AGENT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*80}")
            print(f"Found {len(open_issues)} open issues\n")

            for issue in open_issues:
                # Analyze issue
                analysis = self.analyze_issue(issue)

                # Send Telegram notification
                telegram_sent = self.send_telegram_notification(issue, analysis)

                # Update issue status
                if telegram_sent:
                    issue.status = 'in_progress'
                    # Store analysis in resolution_notes temporarily (will be updated with actual resolution when fixed)
                    analysis_summary = f"AI Analysis:\n{analysis.get('diagnosis', '')}\n\nSuggested Fix:\n{analysis.get('suggested_fix', '')}"
                    issue.resolution_notes = analysis_summary
                    db.commit()
                    print(f"   ✓ Issue #{issue.id} status updated to 'in_progress'\n")
                else:
                    print(f"   ⚠️  Issue #{issue.id} not updated (Telegram failed)\n")

            print(f"{'='*80}")
            print(f"Issue processing complete")
            print(f"{'='*80}\n")

        except Exception as e:
            print(f"❌ Error processing issues: {e}")
            db.rollback()
        finally:
            db.close()


def main():
    """Run the issue resolution agent"""
    agent = IssueResolutionAgent()
    agent.process_new_issues()


if __name__ == "__main__":
    main()
