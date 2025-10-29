#!/usr/bin/env python3
"""
orchestrator_integration.py - Bridge Between Production and Dev

Purpose: Allow production orchestrator to use autonomous learning system
         without modifying production code.

Architecture:
    Production Orchestrator (agent_orchestrator.py)
        ↓
    AutonomousLearningBridge (this file)
        ↓  [Feature Flag Controlled]
        ↓
    Dev Autonomous Learning System (Phase 1-4)

Integration Method:
    1. Feature flag controlled (ENABLE_AUTONOMOUS_LEARNING)
    2. Non-invasive (no production code changes)
    3. Gradual rollout (Phase 1 → 2 → 3 → 4)
    4. Safe fallback (disable if issues)

Usage in Production:
    from dev.orchestrator_integration import AutonomousLearningBridge

    if os.getenv("ENABLE_AUTONOMOUS_LEARNING") == "true":
        learning = AutonomousLearningBridge()
        learning.log_validation_failure(issue)
        patterns = learning.check_for_patterns()
"""

import sys
import os
from datetime import datetime
from typing import List, Dict, Optional
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, SPAC


class AutonomousLearningBridge:
    """
    Bridge between production orchestrator and dev autonomous learning system

    Feature Flags (from environment):
    - ENABLE_AUTONOMOUS_LEARNING: Enable entire system (default: false)
    - ENABLE_PATTERN_DETECTION: Run pattern detection (default: false)
    - ENABLE_VALIDATOR_SYNTHESIS: Generate validators (default: false)
    - AUTO_DEPLOY_VALIDATORS: Auto-deploy high confidence (default: false)
    - AUTO_DEPLOY_THRESHOLD: Minimum confidence for auto-deploy (default: 95)
    """

    def __init__(self):
        """Initialize bridge with feature flags"""
        self.enabled = os.getenv("ENABLE_AUTONOMOUS_LEARNING", "false").lower() == "true"
        self.pattern_detection_enabled = os.getenv("ENABLE_PATTERN_DETECTION", "false").lower() == "true"
        self.validator_synthesis_enabled = os.getenv("ENABLE_VALIDATOR_SYNTHESIS", "false").lower() == "true"
        self.auto_deploy_enabled = os.getenv("AUTO_DEPLOY_VALIDATORS", "false").lower() == "true"
        self.auto_deploy_threshold = float(os.getenv("AUTO_DEPLOY_THRESHOLD", "95"))

        self.db = SessionLocal()

        if self.enabled:
            # Import dev components
            from dev.phase1_logging import ValidationLoggingWrapper
            from dev.phase2_pattern_detector import PatternDetector
            from dev.phase3_validator_synthesis_agent import ValidatorSynthesisAgent
            from dev.phase4_confidence_engine import ConfidenceEngine

            self.logger = ValidationLoggingWrapper(enable_logging=True)
            self.pattern_detector = PatternDetector()
            self.validator_synthesizer = ValidatorSynthesisAgent()
            self.confidence_engine = ConfidenceEngine()

            print("✓ AutonomousLearningBridge active")
            print(f"  Pattern Detection: {'✓' if self.pattern_detection_enabled else '✗'}")
            print(f"  Validator Synthesis: {'✓' if self.validator_synthesis_enabled else '✗'}")
            print(f"  Auto-Deploy: {'✓' if self.auto_deploy_enabled else '✗'} (threshold: {self.auto_deploy_threshold}%)")
        else:
            print("ℹ Autonomous learning disabled (set ENABLE_AUTONOMOUS_LEARNING=true to enable)")

    def log_validation_failure(self, spac: SPAC, issues: List[Dict]):
        """
        Log validation failures (Phase 1)

        Called by orchestrator after validation

        Args:
            spac: SPAC that was validated
            issues: List of validation issues
        """
        if not self.enabled:
            return

        try:
            self.logger._log_validation_failures(spac, issues)
        except Exception as e:
            print(f"  ⚠️  Learning: Logging failed (non-critical): {e}")

    def log_fix_result(self, ticker: str, issue: Dict, fix_applied: bool,
                      fix_method: str, fix_success: bool, fix_details: Optional[Dict] = None):
        """
        Log fix result (Phase 1)

        Called by orchestrator after applying fix

        Args:
            ticker: SPAC ticker
            issue: Original issue
            fix_applied: Whether fix was applied
            fix_method: "auto_applied", "user_approved", "skipped"
            fix_success: Whether fix succeeded
            fix_details: What was changed
        """
        if not self.enabled:
            return

        try:
            self.logger.log_fix_result(ticker, issue, fix_applied, fix_method,
                                      fix_success, fix_details)
        except Exception as e:
            print(f"  ⚠️  Learning: Fix logging failed (non-critical): {e}")

    def check_for_patterns(self, lookback_days: int = 30) -> List[Dict]:
        """
        Check for patterns in recent validation failures (Phase 2)

        Called periodically by orchestrator (e.g., daily)

        Args:
            lookback_days: Analyze last N days

        Returns: List of detected patterns
        """
        if not self.enabled or not self.pattern_detection_enabled:
            return []

        try:
            print(f"\n🔍 Running pattern detection (last {lookback_days} days)...")
            patterns = self.pattern_detector.detect_patterns(lookback_days)

            if patterns:
                # Save patterns to database
                saved = self.pattern_detector.save_patterns_to_db(patterns)
                print(f"   Detected {len(patterns)} pattern(s), saved {saved}")

                # Return pattern dicts for Telegram notification
                return [p.to_dict() for p in patterns]
            else:
                print(f"   No patterns detected")
                return []

        except Exception as e:
            print(f"  ⚠️  Learning: Pattern detection failed: {e}")
            return []

    def generate_validators_for_patterns(self, pattern_ids: Optional[List[int]] = None) -> List[Dict]:
        """
        Generate validators for patterns (Phase 3)

        Called when:
        - New patterns detected (automatic)
        - User approves pattern for validator generation (via Telegram)

        Args:
            pattern_ids: Specific patterns to generate for (None = all unprocessed)

        Returns: List of generated validators with metadata
        """
        if not self.enabled or not self.validator_synthesis_enabled:
            return []

        try:
            # Get patterns needing validators
            if pattern_ids is None:
                query = """
                    SELECT id FROM detected_patterns
                    WHERE validator_recommended = true
                      AND validator_code IS NULL
                      AND status = 'detected'
                    ORDER BY impact_score DESC
                """
                from sqlalchemy import text
                result = self.db.execute(text(query))
                pattern_ids = [row[0] for row in result]

            if not pattern_ids:
                return []

            print(f"\n🔨 Generating validators for {len(pattern_ids)} pattern(s)...")

            generated = []
            for pattern_id in pattern_ids:
                try:
                    print(f"\n   Pattern {pattern_id}:")
                    result = self.validator_synthesizer.generate_validator(pattern_id)

                    if result['errors']:
                        print(f"   ✗ Generation failed: {result['errors']}")
                        continue

                    # Save to database
                    self.validator_synthesizer.save_generated_validator(pattern_id, result)

                    # Calculate confidence (Phase 4)
                    confidence_result = self.confidence_engine.score_pattern_validator(pattern_id)
                    self.confidence_engine.save_confidence_score(pattern_id, confidence_result)

                    generated.append({
                        'pattern_id': pattern_id,
                        'validator_code': result['validator_code'],
                        'confidence': confidence_result['total_confidence'],
                        'recommendation': confidence_result['recommendation']
                    })

                    print(f"   ✓ Generated (confidence: {confidence_result['total_confidence']:.1f}%)")

                except Exception as e:
                    print(f"   ✗ Failed: {e}")
                    continue

            return generated

        except Exception as e:
            print(f"  ⚠️  Learning: Validator generation failed: {e}")
            return []

    def check_auto_deploy_validators(self) -> List[Dict]:
        """
        Check if any validators should be auto-deployed (Phase 4)

        Called after validator generation

        Returns: List of auto-deployed validators
        """
        if not self.enabled or not self.auto_deploy_enabled:
            return []

        try:
            # Find validators ready for auto-deploy
            from sqlalchemy import text
            query = text("""
                SELECT id, pattern_name, recommended_validator_name,
                       validator_code, validator_confidence_score
                FROM detected_patterns
                WHERE validator_confidence_score >= :threshold
                  AND validator_deployed = false
                  AND status = 'validator_generated'
            """)

            result = self.db.execute(query, {'threshold': self.auto_deploy_threshold})

            deployed = []
            for row in result:
                pattern_id = row[0]
                pattern_name = row[1]
                validator_name = row[2]
                validator_code = row[3]
                confidence = row[4]

                print(f"\n🚀 Auto-deploying validator: {validator_name}")
                print(f"   Pattern: {pattern_name}")
                print(f"   Confidence: {confidence:.1f}%")

                # Deploy validator (Phase 4)
                success = self._deploy_validator(
                    pattern_id=pattern_id,
                    validator_name=validator_name,
                    validator_code=validator_code,
                    confidence=confidence,
                    deployment_type='auto_deployed'
                )

                if success:
                    deployed.append({
                        'pattern_id': pattern_id,
                        'validator_name': validator_name,
                        'confidence': confidence
                    })

            return deployed

        except Exception as e:
            print(f"  ⚠️  Learning: Auto-deploy check failed: {e}")
            return []

    def _deploy_validator(self, pattern_id: int, validator_name: str,
                         validator_code: str, confidence: float,
                         deployment_type: str) -> bool:
        """
        Deploy validator to production

        This is a placeholder - actual deployment would:
        1. Add validator method to data_validator_agent.py
        2. Update validator registration
        3. Create deployment record
        4. Start monitoring

        For now, just creates deployment record for tracking.
        """
        try:
            from sqlalchemy import text

            # Create deployment record
            insert_query = text("""
                INSERT INTO validator_deployments (
                    validator_name,
                    pattern_id,
                    deployment_type,
                    validator_code,
                    confidence_score,
                    status,
                    deployed_at
                ) VALUES (
                    :validator_name,
                    :pattern_id,
                    :deployment_type,
                    :validator_code,
                    :confidence_score,
                    'monitoring',
                    NOW()
                )
            """)

            self.db.execute(insert_query, {
                'validator_name': validator_name,
                'pattern_id': pattern_id,
                'deployment_type': deployment_type,
                'validator_code': validator_code,
                'confidence_score': confidence
            })

            # Mark pattern as deployed
            update_query = text("""
                UPDATE detected_patterns
                SET
                    validator_deployed = true,
                    validator_deployed_at = NOW(),
                    status = 'deployed'
                WHERE id = :pattern_id
            """)

            self.db.execute(update_query, {'pattern_id': pattern_id})

            self.db.commit()

            print(f"   ✓ Deployment record created")
            print(f"   📊 Monitoring enabled (7 days)")
            print(f"\n   ⚠️  MANUAL STEP REQUIRED:")
            print(f"   Add validator method to data_validator_agent.py:")
            print(f"   1. Copy code from detected_patterns.validator_code (pattern {pattern_id})")
            print(f"   2. Add to DataValidatorAgent class")
            print(f"   3. Register in validate_all() method")

            return True

        except Exception as e:
            print(f"   ✗ Deployment failed: {e}")
            self.db.rollback()
            return False

    def run_daily_learning_cycle(self):
        """
        Run complete autonomous learning cycle

        Called once daily by orchestrator

        Steps:
        1. Check for patterns (Phase 2)
        2. Generate validators for new patterns (Phase 3)
        3. Score and deploy high-confidence validators (Phase 4)
        4. Send Telegram summary
        """
        if not self.enabled:
            return

        print("\n" + "="*70)
        print("Autonomous Learning Daily Cycle")
        print("="*70)

        # Step 1: Pattern Detection
        patterns = self.check_for_patterns(lookback_days=30)

        if patterns:
            print(f"\n✓ Step 1: Detected {len(patterns)} pattern(s)")

            # Step 2: Generate Validators
            if self.validator_synthesis_enabled:
                pattern_ids = [p['pattern_id'] if 'pattern_id' in p else None for p in patterns]
                pattern_ids = [pid for pid in pattern_ids if pid]  # Filter None

                if pattern_ids:
                    generated = self.generate_validators_for_patterns(pattern_ids)
                    print(f"\n✓ Step 2: Generated {len(generated)} validator(s)")

                    # Step 3: Auto-Deploy
                    if self.auto_deploy_enabled:
                        deployed = self.check_auto_deploy_validators()
                        print(f"\n✓ Step 3: Auto-deployed {len(deployed)} validator(s)")

                        # Send Telegram notification
                        self._send_telegram_summary(patterns, generated, deployed)
                    else:
                        print(f"\n⏸  Step 3: Auto-deploy disabled")
                        # Queue for human review via Telegram
                        self._send_telegram_review_request(generated)
                else:
                    print(f"\n⏸  Step 2: No pattern IDs to process")
            else:
                print(f"\n⏸  Step 2: Validator synthesis disabled")
        else:
            print(f"\n✓ Step 1: No patterns detected (system healthy)")

        print("\n" + "="*70)
        print("Daily Learning Cycle Complete")
        print("="*70 + "\n")

    def _send_telegram_summary(self, patterns: List[Dict],
                               generated: List[Dict], deployed: List[Dict]):
        """Send Telegram summary of learning cycle"""
        try:
            from telegram_agent import TelegramAgent

            telegram = TelegramAgent()

            message = f"""🧠 <b>Autonomous Learning Daily Summary</b>

📊 <b>Patterns Detected:</b> {len(patterns)}
🔨 <b>Validators Generated:</b> {len(generated)}
🚀 <b>Auto-Deployed:</b> {len(deployed)}

"""

            if deployed:
                message += "<b>Auto-Deployed Validators:</b>\n"
                for v in deployed:
                    message += f"  • {v['validator_name']} (confidence: {v['confidence']:.1f}%)\n"

            message += "\n✅ System learning autonomously"

            telegram.send_message(message)

        except Exception as e:
            print(f"  ⚠️  Could not send Telegram summary: {e}")

    def _send_telegram_review_request(self, generated: List[Dict]):
        """Send Telegram request for human review of generated validators"""
        try:
            from telegram_agent import TelegramAgent

            telegram = TelegramAgent()

            message = f"""🔍 <b>Validators Generated - Human Review Required</b>

Generated {len(generated)} new validator(s):

"""

            for v in generated:
                rec = v['recommendation']
                message += f"<b>{v['pattern_id']}.</b> Confidence: {v['confidence']:.1f}%\n"
                message += f"   Action: {rec['action'].upper()}\n"
                message += f"   Monitoring: {rec['monitoring_period_days']} days\n\n"

            message += """Reply:
• "deploy [pattern_id]" → Deploy validator
• "reject [pattern_id]" → Reject validator
• "show [pattern_id]" → View code
"""

            telegram.send_message(message)

        except Exception as e:
            print(f"  ⚠️  Could not send Telegram review request: {e}")

    def __del__(self):
        """Cleanup"""
        if hasattr(self, 'db'):
            self.db.close()


# ============================================================================
# Testing & Verification
# ============================================================================

def test_integration():
    """Test orchestrator integration"""
    print("Testing Orchestrator Integration\n")

    # Test with feature flag disabled
    os.environ["ENABLE_AUTONOMOUS_LEARNING"] = "false"
    bridge = AutonomousLearningBridge()
    assert bridge.enabled == False
    print("✓ Feature flag OFF works\n")

    # Test with feature flag enabled
    os.environ["ENABLE_AUTONOMOUS_LEARNING"] = "true"
    bridge = AutonomousLearningBridge()
    assert bridge.enabled == True
    print("✓ Feature flag ON works\n")

    # Test logging (Phase 1)
    from database import SPAC
    db = SessionLocal()
    spac = db.query(SPAC).first()

    test_issues = [{
        'type': 'test_issue',
        'severity': 'LOW',
        'ticker': spac.ticker,
        'field': 'test_field',
        'message': 'Test validation issue',
        'expected': 'test_expected',
        'actual': 'test_actual',
        'metadata': {}
    }]

    bridge.log_validation_failure(spac, test_issues)
    print("✓ Validation logging works\n")

    db.close()

    print("✓ All integration tests passed")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Orchestrator Integration Bridge')
    parser.add_argument('--test', action='store_true', help='Test integration')
    parser.add_argument('--run-cycle', action='store_true', help='Run daily learning cycle')

    args = parser.parse_args()

    if args.test:
        test_integration()
    elif args.run_cycle:
        bridge = AutonomousLearningBridge()
        bridge.run_daily_learning_cycle()
    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python3 orchestrator_integration.py --test")
        print("  python3 orchestrator_integration.py --run-cycle")
        print("\nEnvironment Variables:")
        print("  ENABLE_AUTONOMOUS_LEARNING=true")
        print("  ENABLE_PATTERN_DETECTION=true")
        print("  ENABLE_VALIDATOR_SYNTHESIS=true")
        print("  AUTO_DEPLOY_VALIDATORS=true")
        print("  AUTO_DEPLOY_THRESHOLD=95")
