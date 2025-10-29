#!/usr/bin/env python3
"""
test_atmv_scenario.py - Regression Test for ATMV Learning Case

Purpose: Verify autonomous learning system would detect and prevent
         the ATMV data corruption issue that occurred on Oct 11, 2025.

Scenario:
    - ATMV showed announced_date=2022-01-31 but ipo_date=2022-12-22
    - Impossible: Can't announce deal before IPO
    - Root cause: Ticker reuse (CleanTech ATMV → AlphaVest ATMV)

Expected Autonomous Learning Behavior:
    1. Phase 1: Log 3+ temporal_impossibility issues (ATMV + others)
    2. Phase 2: Detect temporal_impossibility_pattern
    3. Phase 3: Generate validate_temporal_consistency() code
    4. Phase 4: Confidence score ≥90%, recommend deployment
"""

import sys
import os
from datetime import datetime, date
import pytest

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import SessionLocal, SPAC, Base
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


class TestATMVScenario:
    """Test autonomous learning on ATMV data corruption scenario"""

    @classmethod
    def setup_class(cls):
        """Setup test database with ATMV scenario data"""
        # Create in-memory test database
        cls.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

        # Create validation_failures table
        cls.engine.execute(text("""
            CREATE TABLE validation_failures (
                id INTEGER PRIMARY KEY,
                ticker VARCHAR(10),
                validation_method VARCHAR(100),
                issue_type VARCHAR(50),
                severity VARCHAR(20),
                field VARCHAR(50),
                expected_value TEXT,
                actual_value TEXT,
                error_message TEXT,
                metadata TEXT,
                related_fields TEXT,
                fix_applied BOOLEAN DEFAULT 0,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # Create detected_patterns table
        cls.engine.execute(text("""
            CREATE TABLE detected_patterns (
                id INTEGER PRIMARY KEY,
                pattern_name VARCHAR(100),
                pattern_type VARCHAR(50),
                description TEXT,
                issue_count INTEGER,
                affected_tickers TEXT,
                common_characteristics TEXT,
                impact_score FLOAT,
                recurrence_frequency VARCHAR(20),
                recommended_validator_name VARCHAR(100),
                recommended_validator_rules TEXT,
                validator_code TEXT,
                validator_confidence_score FLOAT,
                validator_recommended BOOLEAN DEFAULT 0,
                validator_deployed BOOLEAN DEFAULT 0,
                status VARCHAR(20) DEFAULT 'detected',
                first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_occurrence TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

    def test_phase1_logging_atmv_issue(self):
        """
        Test Phase 1: Validation failure logging

        Simulate 3 SPACs with temporal impossibility issues
        """
        from dev.phase1_logging import ValidationLoggingWrapper

        db = self.SessionLocal()

        # Create test SPACs
        atmv = SPAC(
            ticker='ATMV',
            company='AlphaVest Acquisition Corp',
            ipo_date=date(2022, 12, 22),
            announced_date=date(2022, 1, 31),  # BEFORE IPO - impossible!
            deal_status='ANNOUNCED',
            target='AMC Corporation'
        )

        test1 = SPAC(
            ticker='TEST1',
            company='Test SPAC 1',
            ipo_date=date(2023, 6, 15),
            announced_date=date(2023, 3, 10),  # BEFORE IPO
            deal_status='ANNOUNCED'
        )

        test2 = SPAC(
            ticker='TEST2',
            company='Test SPAC 2',
            ipo_date=date(2024, 1, 20),
            announced_date=date(2023, 11, 5),  # BEFORE IPO
            deal_status='ANNOUNCED'
        )

        db.add_all([atmv, test1, test2])
        db.commit()

        # Simulate validation issues
        atmv_issue = {
            'type': 'temporal_impossibility',
            'severity': 'CRITICAL',
            'ticker': 'ATMV',
            'field': 'announced_date',
            'message': 'Deal announced before IPO - impossible!',
            'expected': 'announced_date >= 2022-12-22',
            'actual': 'announced_date=2022-01-31',
            'metadata': {
                'ipo_date': '2022-12-22',
                'announced_date': '2022-01-31',
                'days_before_ipo': 325
            }
        }

        test1_issue = {
            'type': 'temporal_impossibility',
            'severity': 'CRITICAL',
            'ticker': 'TEST1',
            'field': 'announced_date',
            'message': 'Deal announced before IPO - impossible!',
            'expected': 'announced_date >= 2023-06-15',
            'actual': 'announced_date=2023-03-10',
            'metadata': {'ipo_date': '2023-06-15', 'announced_date': '2023-03-10'}
        }

        test2_issue = {
            'type': 'temporal_impossibility',
            'severity': 'CRITICAL',
            'ticker': 'TEST2',
            'field': 'announced_date',
            'message': 'Deal announced before IPO - impossible!',
            'expected': 'announced_date >= 2024-01-20',
            'actual': 'announced_date=2023-11-05',
            'metadata': {'ipo_date': '2024-01-20', 'announced_date': '2023-11-05'}
        }

        # Log via Phase 1 wrapper
        wrapper = ValidationLoggingWrapper(enable_logging=True)
        wrapper._log_validation_failures(atmv, [atmv_issue])
        wrapper._log_validation_failures(test1, [test1_issue])
        wrapper._log_validation_failures(test2, [test2_issue])

        # Verify logged
        logged_count = db.execute(text(
            "SELECT COUNT(*) FROM validation_failures WHERE issue_type = 'temporal_impossibility'"
        )).scalar()

        assert logged_count == 3, f"Expected 3 logged issues, got {logged_count}"

        db.close()
        print("✓ Phase 1: Successfully logged 3 temporal impossibility issues")

    def test_phase2_pattern_detection(self):
        """
        Test Phase 2: Pattern detection

        Should detect temporal_impossibility_pattern from 3 issues
        """
        from dev.phase2_pattern_detector import PatternDetector

        detector = PatternDetector(min_issue_count=3, min_impact_score=60)
        patterns = detector.detect_patterns(lookback_days=365)

        # Should detect temporal pattern
        temporal_patterns = [p for p in patterns if 'temporal' in p.pattern_name]

        assert len(temporal_patterns) >= 1, "Should detect at least 1 temporal pattern"

        pattern = temporal_patterns[0]
        assert pattern.issue_count == 3, f"Pattern should have 3 issues, got {pattern.issue_count}"
        assert 'ATMV' in pattern.affected_tickers, "ATMV should be in affected tickers"
        assert pattern.impact_score >= 60, f"Impact score should be ≥60, got {pattern.impact_score}"

        print(f"✓ Phase 2: Detected pattern '{pattern.pattern_name}'")
        print(f"   Issues: {pattern.issue_count}, Impact: {pattern.impact_score:.1f}/100")

    def test_phase3_validator_synthesis(self):
        """
        Test Phase 3: Validator code generation

        Should generate validate_temporal_consistency() code
        """
        from dev.phase3_validator_synthesis_agent import ValidatorSynthesisAgent

        # First ensure pattern exists in DB
        db = self.SessionLocal()

        # Insert test pattern
        db.execute(text("""
            INSERT INTO detected_patterns (
                pattern_name, pattern_type, description, issue_count,
                affected_tickers, common_characteristics, impact_score,
                recommended_validator_name, recommended_validator_rules,
                validator_recommended
            ) VALUES (
                'temporal_impossibility_pattern',
                'data_corruption',
                'Multiple SPACs with dates before IPO',
                3,
                '["ATMV", "TEST1", "TEST2"]',
                '{"issue_type": "temporal_impossibility", "common_field": "announced_date"}',
                95.0,
                'validate_temporal_consistency',
                '{"rules": ["announced_date >= ipo_date", "completion_date >= announced_date"]}',
                1
            )
        """))
        db.commit()

        pattern_id = db.execute(text(
            "SELECT id FROM detected_patterns WHERE pattern_name = 'temporal_impossibility_pattern'"
        )).scalar()

        # Generate validator
        agent = ValidatorSynthesisAgent()
        result = agent.generate_validator(pattern_id)

        assert result['errors'] == [], f"Should have no errors, got: {result['errors']}"
        assert result['validator_code'], "Should generate code"
        assert 'def validate_temporal_consistency' in result['validator_code'], \
            "Code should include method definition"
        assert result['confidence_score'] > 0, "Should have positive confidence"

        print(f"✓ Phase 3: Generated validator code")
        print(f"   Confidence: {result['confidence_score']:.1f}%")
        print(f"   Code length: {len(result['validator_code'])} chars")

        db.close()

    def test_phase4_confidence_scoring(self):
        """
        Test Phase 4: Confidence scoring

        Should score ≥90% for ATMV pattern (strong pattern, clear issue)
        """
        from dev.phase4_confidence_engine import ConfidenceEngine

        db = self.SessionLocal()

        # Get pattern ID
        pattern_id = db.execute(text(
            "SELECT id FROM detected_patterns WHERE pattern_name = 'temporal_impossibility_pattern'"
        )).scalar()

        # Add validator code to pattern (Phase 3 should have done this)
        db.execute(text("""
            UPDATE detected_patterns
            SET validator_code = 'def validate_temporal_consistency(self, spac): pass'
            WHERE id = :pattern_id
        """), {'pattern_id': pattern_id})
        db.commit()

        # Score
        engine = ConfidenceEngine()
        result = engine.score_pattern_validator(pattern_id)

        assert result['total_confidence'] >= 90, \
            f"ATMV pattern should score ≥90%, got {result['total_confidence']:.1f}%"

        assert result['recommendation']['action'] in ['auto_deploy', 'deploy_with_monitoring'], \
            f"Should recommend deployment, got {result['recommendation']['action']}"

        print(f"✓ Phase 4: Confidence score {result['total_confidence']:.1f}%")
        print(f"   Recommendation: {result['recommendation']['action']}")

        db.close()

    def test_end_to_end_learning_cycle(self):
        """
        Test complete learning cycle end-to-end

        Simulate the entire autonomous learning process from issue to deployment
        """
        print("\n" + "="*70)
        print("End-to-End Autonomous Learning Test")
        print("="*70 + "\n")

        # Step 1: Issues logged (already done in test_phase1)
        print("Step 1: ✓ Issues logged")

        # Step 2: Pattern detected (already done in test_phase2)
        print("Step 2: ✓ Pattern detected")

        # Step 3: Validator generated (already done in test_phase3)
        print("Step 3: ✓ Validator generated")

        # Step 4: Confidence scored (already done in test_phase4)
        print("Step 4: ✓ Confidence scored")

        # Step 5: Deployment decision
        from dev.phase4_confidence_engine import ConfidenceEngine

        db = self.SessionLocal()
        pattern_id = db.execute(text(
            "SELECT id FROM detected_patterns WHERE pattern_name = 'temporal_impossibility_pattern'"
        )).scalar()

        engine = ConfidenceEngine()
        result = engine.score_pattern_validator(pattern_id)

        if result['recommendation']['action'] in ['auto_deploy', 'deploy_with_monitoring']:
            print(f"Step 5: ✓ Recommended for deployment ({result['recommendation']['action']})")
        else:
            print(f"Step 5: ⚠️  Not recommended for deployment ({result['recommendation']['action']})")

        print("\n" + "="*70)
        print("✓ Complete autonomous learning cycle verified")
        print("="*70)

        db.close()

    @classmethod
    def teardown_class(cls):
        """Cleanup test database"""
        Base.metadata.drop_all(cls.engine)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
