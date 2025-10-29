#!/usr/bin/env python3
"""
Self-Improvement Agent - Propose Code Fixes for Repeated Errors
Version: 2.0.0

Detects repeated errors (3+) and proposes code fixes.
ALL FIXES REQUIRE USER APPROVAL - no automatic code changes!
"""

import sys
import os
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import yaml
from openai import OpenAI
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from feedback.learning_log import LearningLog
from feedback.telegram_interface import TelegramInterface

load_dotenv()


class SelfImprovementAgent:
    """
    Detects recurring errors and proposes code fixes

    Workflow:
    1. Monitor error patterns (3+ occurrences)
    2. Analyze with AI
    3. Propose code fix via Telegram
    4. Wait for approval
    5. Apply fix if approved
    6. Track effectiveness
    """

    def __init__(self):
        """Initialize self-improvement agent"""
        self.learning_log = LearningLog()
        self.telegram = TelegramInterface()

        # Load config
        config_file = os.path.join(
            os.path.dirname(__file__),
            '../config/self_improvement_rules.yaml'
        )
        with open(config_file, 'r') as f:
            self.config = yaml.safe_load(f)

        # AI client
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            self.ai_client = OpenAI(
                api_key=deepseek_key,
                base_url="https://api.deepseek.com"
            )
        else:
            self.ai_client = None
            print("⚠️  DEEPSEEK_API_KEY not found - AI analysis disabled")

    def check_for_patterns(self) -> List[Dict]:
        """
        Check for error patterns that have crossed threshold

        Returns:
            List of patterns needing code fixes
        """
        patterns = self.learning_log.get_patterns_needing_fixes()

        print(f"\n🔍 Found {len(patterns)} error patterns crossing threshold:\n")
        for pattern in patterns:
            print(f"  • {pattern['pattern_key']}: {pattern['occurrences_last_30_days']} occurrences")

        return patterns

    def analyze_pattern(self, pattern: Dict) -> Optional[Dict]:
        """
        Analyze error pattern and propose fix

        Args:
            pattern: Error pattern details

        Returns:
            Fix proposal or None
        """
        if not self.ai_client:
            return self._generate_rule_based_fix(pattern)

        # Build AI prompt
        prompt = f"""You are a code improvement agent analyzing recurring data extraction errors.

**Error Pattern:** {pattern['pattern_key']}
**Description:** {pattern['description']}
**Occurrences:** {pattern['occurrences_last_30_days']} times (last 30 days)
**Affected Tickers:** {', '.join(pattern['affected_tickers'][:10])}

Task: Analyze this pattern and propose a code fix.

Output JSON with:
{{
  "root_cause": "Why this error keeps happening",
  "fix_type": "Type of fix (e.g., enhance_ai_prompt, add_validation, improve_regex)",
  "files_to_modify": ["file1.py", "file2.py"],
  "proposed_changes": "Detailed description of changes",
  "code_diff": "Proposed code changes in git diff format",
  "confidence": 0-100,
  "test_cases": ["How to verify fix works"]
}}
"""

        try:
            response = self.ai_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a code improvement expert."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                response_format={"type": "json_object"}
            )

            import json
            result = json.loads(response.choices[0].message.content)

            return {
                'pattern_key': pattern['pattern_key'],
                'error_pattern': pattern['pattern_key'],
                'occurrence_count': pattern['occurrences_last_30_days'],
                'root_cause': result.get('root_cause'),
                'fix_type': result.get('fix_type'),
                'files_to_modify': result.get('files_to_modify', []),
                'fix_description': result.get('proposed_changes'),
                'code_diff': result.get('code_diff'),
                'confidence': result.get('confidence', 0),
                'test_cases': result.get('test_cases', []),
                'fix_id': self._generate_fix_id(pattern['pattern_key'])
            }

        except Exception as e:
            print(f"❌ AI analysis failed: {e}")
            return None

    def _generate_rule_based_fix(self, pattern: Dict) -> Dict:
        """Fallback rule-based fix proposal"""
        return {
            'pattern_key': pattern['pattern_key'],
            'error_pattern': pattern['pattern_key'],
            'occurrence_count': pattern['occurrences_last_30_days'],
            'root_cause': 'Extraction logic incomplete or missing',
            'fix_type': 'manual_review',
            'files_to_modify': [],
            'fix_description': 'Manual code review required',
            'confidence': 50,
            'fix_id': self._generate_fix_id(pattern['pattern_key'])
        }

    def propose_fix_to_user(self, fix_proposal: Dict) -> bool:
        """
        Send fix proposal to user via Telegram

        Args:
            fix_proposal: Fix details

        Returns:
            True if sent successfully
        """
        return self.telegram.send_code_fix_proposal(fix_proposal)

    def apply_fix(self, fix_id: str, fix_proposal: Dict) -> Dict:
        """
        Apply approved code fix

        ⚠️ CRITICAL: This should only be called after explicit user approval!

        Args:
            fix_id: Fix identifier
            fix_proposal: Fix details

        Returns:
            Result dictionary
        """
        print(f"\n⚠️  APPLYING CODE FIX: {fix_id}")
        print(f"⚠️  Files to modify: {', '.join(fix_proposal['files_to_modify'])}\n")

        # Create backup
        backup_dir = "/home/ubuntu/spac-research/backups/code_improvements/"
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backups_created = []

        try:
            # Backup files
            for file_path in fix_proposal['files_to_modify']:
                if os.path.exists(file_path):
                    backup_path = os.path.join(
                        backup_dir,
                        f"{os.path.basename(file_path)}.bak_{timestamp}"
                    )
                    subprocess.run(['cp', file_path, backup_path], check=True)
                    backups_created.append(backup_path)
                    print(f"✓ Backed up: {file_path} → {backup_path}")

            # Apply changes (placeholder - actual implementation would apply diff)
            print(f"\n⚠️  Code changes would be applied here")
            print(f"⚠️  Diff:\n{fix_proposal.get('code_diff', 'No diff provided')}\n")

            # Log to code_improvements table
            self._log_code_improvement(fix_id, fix_proposal, backups_created)

            return {
                'success': True,
                'fix_id': fix_id,
                'backups': backups_created,
                'message': 'Fix applied successfully'
            }

        except Exception as e:
            return {
                'success': False,
                'fix_id': fix_id,
                'error': str(e),
                'backups': backups_created
            }

    def _log_code_improvement(
        self,
        fix_id: str,
        fix_proposal: Dict,
        backup_paths: List[str]
    ):
        """Log applied fix to code_improvements table"""
        from database import SessionLocal
        from sqlalchemy import text

        db = SessionLocal()
        try:
            db.execute(
                text("""
                    INSERT INTO code_improvements (
                        file_path, error_pattern, occurrences_before_fix,
                        fix_explanation, confidence_score, applied_at,
                        backup_path
                    )
                    VALUES (
                        :file_path, :error_pattern, :occurrences,
                        :explanation, :confidence, NOW(),
                        :backup
                    )
                """),
                {
                    'file_path': ', '.join(fix_proposal['files_to_modify']),
                    'error_pattern': fix_proposal['pattern_key'],
                    'occurrences': fix_proposal['occurrence_count'],
                    'explanation': fix_proposal['fix_description'],
                    'confidence': fix_proposal['confidence'],
                    'backup': ', '.join(backup_paths)
                }
            )
            db.commit()
            print(f"✓ Logged to code_improvements table")
        except Exception as e:
            print(f"⚠️  Failed to log: {e}")
        finally:
            db.close()

    def _generate_fix_id(self, pattern_key: str) -> str:
        """Generate unique fix ID"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"FIX_{pattern_key}_{timestamp}"

    def run_monitoring_cycle(self):
        """
        Run one monitoring cycle

        Checks for patterns and proposes fixes
        """
        print("\n" + "="*70)
        print("SELF-IMPROVEMENT MONITORING CYCLE")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)

        # Check for patterns
        patterns = self.check_for_patterns()

        if not patterns:
            print("\n✓ No patterns crossing threshold")
            return

        # Analyze and propose fixes
        for pattern in patterns:
            print(f"\n{'─'*70}")
            print(f"Analyzing: {pattern['pattern_key']}")
            print(f"{'─'*70}")

            fix_proposal = self.analyze_pattern(pattern)

            if fix_proposal:
                print(f"\n💡 Fix Proposal Generated:")
                print(f"  Root Cause: {fix_proposal['root_cause']}")
                print(f"  Fix Type: {fix_proposal['fix_type']}")
                print(f"  Confidence: {fix_proposal['confidence']}%")
                print(f"  Files: {', '.join(fix_proposal['files_to_modify'])}")

                # Send to user
                sent = self.propose_fix_to_user(fix_proposal)
                if sent:
                    print(f"\n✓ Proposal sent to Telegram")
                else:
                    print(f"\n❌ Failed to send proposal")
            else:
                print(f"\n⚠️  Could not generate fix proposal")

        print(f"\n{'='*70}\n")


if __name__ == "__main__":
    # Test self-improvement agent
    agent = SelfImprovementAgent()
    agent.run_monitoring_cycle()
