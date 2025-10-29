# Development Environment - Autonomous Learning System

**Created**: October 11, 2025
**Purpose**: Implement autonomous learning capability for SPAC data quality system

## Development vs Production

### Production Code (Root Directory)
All existing code in `/home/ubuntu/spac-research/` is **PRODUCTION** and should not be modified during development.

**Key Production Files**:
- `data_validator_agent.py` - Current validation engine (97 validation methods)
- `investigation_agent.py` - Individual issue hypothesis generation
- `agent_orchestrator.py` - Main orchestration system
- `database.py` - Schema definitions
- All other `.py` files in root

### Development Code (This Directory)
New autonomous learning features built in `/home/ubuntu/spac-research/dev/` until tested and ready for integration.

**Development Structure**:
```
dev/
├── README.md                          # This file
├── INTEGRATION_PLAN.md                # How to promote dev → production
├── validation_failures.sql            # New database schema
├── phase1_logging.py                  # Enhanced validation failure logging
├── phase2_pattern_detector.py         # Meta-analysis engine
├── phase3_validator_synthesis_agent.py # Code generation for new validators
├── phase4_confidence_engine.py        # Auto-apply decision system
├── orchestrator_integration.py        # Bridge between dev and production
├── tests/                             # Test suite for all dev features
│   ├── test_pattern_detection.py
│   ├── test_validator_synthesis.py
│   └── test_autonomous_learning.py
└── examples/                          # Example outputs
    ├── atmv_pattern_detection.json
    └── generated_validator_example.py
```

## Autonomous Learning System Architecture

### Problem Statement (ATMV Lesson - Oct 11, 2025)
**What happened**: ATMV showed data corruption (deal announced before IPO - impossible)

**Manual learning process**:
1. Detected issue → ATMV announced_date before ipo_date
2. Analyzed root cause → Ticker reuse data corruption
3. Identified pattern → "Temporal impossibilities indicate systemic issue"
4. Created prevention → New validator: `validate_temporal_consistency()`
5. Deployed → Now ALL SPACs checked for temporal consistency

**Current system limitation**: Investigation Agent can fix ATMV but can't:
- Detect this is a recurring pattern
- Generate new validation methods
- Self-modify code to prevent future occurrences

**Goal**: Automate steps 3-5 so the system learns from mistakes autonomously.

---

## Phase 1: Enhanced Validation Failure Logging

**Objective**: Create structured logging system to track validation failures for pattern analysis.

### New Database Schema: `validation_failures` Table

```sql
CREATE TABLE IF NOT EXISTS validation_failures (
    id SERIAL PRIMARY KEY,

    -- Issue identification
    ticker VARCHAR(10) NOT NULL,
    validation_method VARCHAR(100) NOT NULL,  -- e.g., "validate_temporal_consistency"
    issue_type VARCHAR(50) NOT NULL,          -- e.g., "temporal_impossibility"
    severity VARCHAR(20) NOT NULL,            -- CRITICAL, HIGH, MEDIUM, LOW

    -- Issue details
    field VARCHAR(50),                        -- Affected field (e.g., "announced_date")
    expected_value TEXT,
    actual_value TEXT,
    error_message TEXT,

    -- Context for pattern detection
    metadata JSONB,                           -- Full issue context
    related_fields JSONB,                     -- Other fields involved

    -- Fix tracking
    fix_applied BOOLEAN DEFAULT FALSE,
    fix_method VARCHAR(50),                   -- "auto_applied", "user_approved", "skipped"
    fix_success BOOLEAN,
    fix_applied_at TIMESTAMP,

    -- Learning tracking
    pattern_id INTEGER,                       -- Links to detected patterns
    contributed_to_new_validator BOOLEAN DEFAULT FALSE,
    validator_generated VARCHAR(100),         -- Name of validator created from this issue

    -- Timestamps
    detected_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP,

    -- Indexes for pattern detection queries
    INDEX idx_validation_method (validation_method),
    INDEX idx_issue_type (issue_type),
    INDEX idx_ticker (ticker),
    INDEX idx_detected_at (detected_at),
    INDEX idx_pattern_id (pattern_id)
);

CREATE TABLE IF NOT EXISTS detected_patterns (
    id SERIAL PRIMARY KEY,

    -- Pattern identification
    pattern_name VARCHAR(100) NOT NULL,       -- e.g., "temporal_impossibility_pattern"
    pattern_type VARCHAR(50) NOT NULL,        -- "data_corruption", "extraction_bug", "logic_error"

    -- Pattern characteristics
    description TEXT,
    issue_count INTEGER DEFAULT 1,            -- How many issues match this pattern
    affected_tickers TEXT[],                  -- List of affected tickers
    common_characteristics JSONB,             -- What issues have in common

    -- Severity assessment
    impact_score FLOAT,                       -- 0-100: How severe is this pattern
    recurrence_frequency VARCHAR(20),         -- "daily", "weekly", "monthly", "rare"

    -- Learning outcomes
    validator_recommended BOOLEAN DEFAULT FALSE,
    validator_generated VARCHAR(100),         -- Name of validator created
    validator_deployed BOOLEAN DEFAULT FALSE,
    validator_deployed_at TIMESTAMP,

    -- Effectiveness tracking
    prevented_issues_count INTEGER DEFAULT 0, -- How many issues prevented after fix
    false_positive_rate FLOAT,                -- Track validator accuracy

    -- Timestamps
    first_detected TIMESTAMP DEFAULT NOW(),
    last_occurrence TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP,

    INDEX idx_pattern_type (pattern_type),
    INDEX idx_validator_deployed (validator_deployed)
);
```

### Implementation: `phase1_logging.py`

Wrapper around production DataValidatorAgent that logs all failures to `validation_failures` table.

**Key Features**:
- Non-invasive: Wraps existing validators without modifying them
- Captures full context for each failure
- Structured for efficient pattern detection queries
- Tracks fix effectiveness for learning feedback loop

---

## Phase 2: Pattern Detection Engine

**Objective**: Analyze validation failures to detect recurring patterns indicating systemic issues.

### Implementation: `phase2_pattern_detector.py`

**Core Capabilities**:

1. **Temporal Analysis**: Detect patterns over time
   - "5 SPACs in last 30 days had announced_date < ipo_date" → Systemic issue

2. **Field Correlation**: Detect field relationships
   - "All trust_cash errors occur when ipo_proceeds also wrong" → Related extraction bug

3. **Banker/Sector Clustering**: Detect entity-specific patterns
   - "Goldman SPACs consistently missing warrant_ratio" → Banker-specific scraping issue

4. **Rule Gap Detection**: Identify validation gaps
   - "10 issues of type X but no validator catches them" → Missing validator

**Pattern Detection Algorithm**:
```python
class PatternDetector:
    def detect_patterns(self, lookback_days=30) -> List[Pattern]:
        """
        Analyzes validation_failures table for patterns

        Returns patterns meeting threshold:
        - Issue count >= 3 (minimum for pattern)
        - Confidence >= 70% (similarity score)
        - Impact score >= 60 (severity assessment)
        """
```

**Output Example** (ATMV scenario):
```json
{
  "pattern_id": 1,
  "pattern_name": "temporal_impossibility_pattern",
  "pattern_type": "data_corruption",
  "description": "Multiple SPACs showing deal announced before IPO (impossible)",
  "issue_count": 3,
  "affected_tickers": ["ATMV", "GSRT", "CCCX"],
  "common_characteristics": {
    "issue_type": "temporal_impossibility",
    "validation_gap": "No validator checking announced_date >= ipo_date",
    "likely_cause": "Ticker reuse data corruption"
  },
  "impact_score": 95,
  "validator_recommended": true,
  "recommended_validator": {
    "name": "validate_temporal_consistency",
    "description": "Check all dates respect causality (IPO → announcement → completion)",
    "rules": [
      "announced_date >= ipo_date",
      "completion_date >= announced_date",
      "merger_termination_date >= announced_date"
    ]
  }
}
```

---

## Phase 3: Validator Synthesis Agent

**Objective**: Generate new validation method code from detected patterns.

### Implementation: `phase3_validator_synthesis_agent.py`

**Core Capabilities**:

1. **Pattern → Validation Logic**: Convert pattern description to Python code
2. **Code Quality Assurance**: Generated code follows existing validator patterns
3. **Test Case Generation**: Auto-generate test cases for new validator
4. **Documentation Generation**: Auto-generate docstrings with lessons learned

**Synthesis Process**:
```
Detected Pattern
    ↓
DeepSeek API (with examples from existing validators)
    ↓
Generated Validator Code
    ↓
Syntax Validation
    ↓
Test Case Generation
    ↓
Human Review (via Telegram)
    ↓
Approval → Add to data_validator_agent.py
```

**Example Output** (ATMV temporal validator):
```python
def validate_temporal_consistency(self, spac: SPAC) -> List[Dict]:
    """
    Validate temporal consistency: dates must respect causality

    Auto-generated from pattern: temporal_impossibility_pattern
    Detected: 2025-10-11 (3 occurrences: ATMV, GSRT, CCCX)

    Lesson: ATMV showed announced_date=2022-01-31 but ipo_date=2022-12-22
    Cause: Ticker reuse data corruption (CleanTech ATMV → AlphaVest ATMV)

    Prevention Rules:
    1. announced_date >= ipo_date (can't announce before IPO)
    2. completion_date >= announced_date (can't complete before announcing)
    3. merger_termination_date >= announced_date (can't terminate before announcing)
    """
    issues = []

    if not spac.ipo_date:
        return issues

    ipo_date = spac.ipo_date.date() if isinstance(spac.ipo_date, datetime) else spac.ipo_date

    # Rule 1: announced_date >= ipo_date
    if spac.announced_date:
        announced_date = spac.announced_date.date() if isinstance(spac.announced_date, datetime) else spac.announced_date

        if announced_date < ipo_date:
            issues.append({
                'type': 'temporal_impossibility',
                'severity': 'CRITICAL',
                'ticker': spac.ticker,
                'field': 'announced_date',
                'rule': 'Deal Announced Before IPO',
                'message': f'Deal announced before IPO - impossible! Likely ticker reuse.',
                'auto_fix': 'investigate_data_source',
                'expected': f'announced_date >= {ipo_date}',
                'actual': f'announced_date={announced_date}',
                'metadata': {
                    'pattern_id': 1,
                    'auto_generated': True,
                    'generated_from': ['ATMV', 'GSRT', 'CCCX']
                }
            })

    # Additional rules...

    return issues
```

**Integration with Telegram**: User receives message like:
```
🧠 NEW VALIDATOR RECOMMENDED

Pattern Detected: temporal_impossibility_pattern
Occurrences: 3 (ATMV, GSRT, CCCX)
Confidence: 95%

📋 PROPOSED VALIDATOR:
Name: validate_temporal_consistency()
Purpose: Check dates respect causality (IPO → announcement → completion)

📊 EXPECTED IMPACT:
- Would have caught ATMV issue immediately
- Prevents ticker reuse data corruption
- Applies to all 155 SPACs

🔍 PREVIEW CODE: /dev/examples/validate_temporal_consistency.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reply:
• "APPROVE" → Deploy to production
• "show code" → View full implementation
• "test on [TICKER]" → Test on specific SPAC
• "reject" → Reject recommendation
```

---

## Phase 4: Confidence Engine & Autonomous Deployment

**Objective**: Decide which validators to auto-deploy vs queue for human review.

### Implementation: `phase4_confidence_engine.py`

**Confidence Scoring Factors**:

1. **Pattern Strength** (40% weight):
   - Issue count (more occurrences = higher confidence)
   - Recurrence frequency (consistent pattern vs one-time)
   - Impact score (severity of issues)

2. **Generated Code Quality** (30% weight):
   - Syntax validation pass
   - Follows existing validator patterns
   - Test coverage (auto-generated tests pass)

3. **Historical Accuracy** (20% weight):
   - Similar patterns detected before
   - Previous validator effectiveness
   - False positive rate

4. **Blast Radius** (10% weight):
   - How many SPACs affected by new validator
   - Potential for false positives
   - Reversibility (easy to rollback?)

**Confidence Thresholds**:
- **≥95%**: Auto-deploy to production (high confidence)
- **80-94%**: Deploy to production with monitoring (medium-high)
- **70-79%**: Queue for human review (medium)
- **<70%**: Flag for investigation, don't deploy (low)

**Example Decision Matrix**:
```python
Pattern: temporal_impossibility_pattern
├─ Pattern Strength: 95/100 (3 issues, critical severity, clear cause)
├─ Code Quality: 90/100 (syntax valid, follows patterns, tests pass)
├─ Historical Accuracy: N/A (new pattern type)
└─ Blast Radius: 85/100 (affects all SPACs but low false positive risk)

Overall Confidence: 91%
Decision: Deploy to production with monitoring
Action: Add to data_validator_agent.py + alert on first 10 runs
```

**Monitoring After Deployment**:
```python
class ValidatorMonitor:
    def monitor_new_validator(self, validator_name: str, monitoring_period_days: int = 7):
        """
        Track new validator performance:
        - Issues detected count
        - False positive rate
        - User feedback (approved/rejected fixes)
        - Performance impact (execution time)

        If false positive rate > 10% within 7 days:
        → Alert user
        → Suggest refinement
        → Option to rollback
        """
```

---

## Orchestrator Integration

### How Dev Code Connects to Production

**File**: `orchestrator_integration.py`

This bridge allows production orchestrator to use dev features without modifying production code.

**Architecture**:
```
Production Orchestrator (agent_orchestrator.py)
    ↓
Orchestrator Integration Bridge (dev/orchestrator_integration.py)
    ↓
┌──────────────────────────────────┐
│  Dev Autonomous Learning System  │
│  ├─ Phase 1: Logging             │
│  ├─ Phase 2: Pattern Detection   │
│  ├─ Phase 3: Validator Synthesis │
│  └─ Phase 4: Confidence Engine   │
└──────────────────────────────────┘
```

**Usage in Production**:
```python
# In agent_orchestrator.py (NO MODIFICATION NEEDED)
# Dev code accessed via feature flag

if os.getenv("ENABLE_AUTONOMOUS_LEARNING") == "true":
    from dev.orchestrator_integration import AutonomousLearningBridge
    learning_bridge = AutonomousLearningBridge()

    # Log validation failures for pattern detection
    learning_bridge.log_validation_failure(issue_data)

    # Check for patterns after each validation run
    patterns = learning_bridge.check_for_patterns()
    if patterns:
        # Queue for Telegram review
        telegram_agent.queue_validator_recommendations(patterns)
```

**Feature Flag Control** (.env):
```bash
# Development
ENABLE_AUTONOMOUS_LEARNING=true
AUTO_DEPLOY_VALIDATORS=false  # Human review required

# Production (after testing)
ENABLE_AUTONOMOUS_LEARNING=true
AUTO_DEPLOY_VALIDATORS=true   # High confidence validators auto-deploy
AUTO_DEPLOY_THRESHOLD=95      # Only deploy if confidence >= 95%
```

---

## Testing Strategy

### Test Suite Structure

**Directory**: `dev/tests/`

1. **Unit Tests**: Each phase tested independently
   - `test_logging.py`: Validation failure capture
   - `test_pattern_detection.py`: Pattern recognition accuracy
   - `test_validator_synthesis.py`: Code generation quality
   - `test_confidence_engine.py`: Confidence scoring logic

2. **Integration Tests**: End-to-end workflows
   - `test_autonomous_learning.py`: Full pipeline (issue → pattern → validator → deploy)

3. **Regression Tests**: Use known issues (ATMV) to verify
   - `test_atmv_scenario.py`: Would system detect temporal impossibility pattern?

### Example Test Case: ATMV Scenario
```python
def test_atmv_temporal_pattern_detection():
    """
    Simulate ATMV scenario: 3 SPACs with announced_date < ipo_date

    Expected behavior:
    1. Phase 1: Log all 3 issues to validation_failures
    2. Phase 2: Detect temporal_impossibility_pattern
    3. Phase 3: Generate validate_temporal_consistency() code
    4. Phase 4: Confidence score >= 90%, recommend deployment
    """
    # Insert test data (3 SPACs with temporal issues)
    insert_test_validation_failures([
        {'ticker': 'ATMV', 'issue_type': 'temporal_impossibility', ...},
        {'ticker': 'TEST1', 'issue_type': 'temporal_impossibility', ...},
        {'ticker': 'TEST2', 'issue_type': 'temporal_impossibility', ...}
    ])

    # Run pattern detection
    detector = PatternDetector()
    patterns = detector.detect_patterns(lookback_days=30)

    # Assert pattern detected
    assert len(patterns) == 1
    assert patterns[0].pattern_name == 'temporal_impossibility_pattern'
    assert patterns[0].issue_count == 3

    # Generate validator
    synthesizer = ValidatorSynthesisAgent()
    validator_code = synthesizer.generate_validator(patterns[0])

    # Assert code quality
    assert 'def validate_temporal_consistency' in validator_code
    assert validator_code.count('if') >= 3  # At least 3 rules

    # Calculate confidence
    confidence = ConfidenceEngine().score(patterns[0], validator_code)
    assert confidence >= 90
```

---

## Promotion Process: Dev → Production

**File**: `INTEGRATION_PLAN.md` (to be created)

### Checklist for Promoting Dev Features

**Phase 1 Promotion**:
- [ ] Validation failures table created in production DB
- [ ] Logging wrapper tested on 155 SPACs
- [ ] No performance degradation (< 5% overhead)
- [ ] 7 days of logging data collected for Phase 2

**Phase 2 Promotion**:
- [ ] Pattern detector tested on historical issues
- [ ] ATMV scenario correctly identified
- [ ] False positive rate < 10%
- [ ] Telegram integration tested

**Phase 3 Promotion**:
- [ ] Validator synthesis generates valid Python code
- [ ] Generated code passes all syntax checks
- [ ] Human review approved 3+ generated validators
- [ ] Generated validators effective (caught real issues)

**Phase 4 Promotion**:
- [ ] Confidence scoring accurate (tested on known patterns)
- [ ] Auto-deploy feature flag controlled
- [ ] Rollback mechanism tested
- [ ] Monitoring dashboard functional

### Integration Steps

1. **Phase 1 → Production** (Week 1):
   ```bash
   # Add logging table to production DB
   psql spac_db < dev/validation_failures.sql

   # Enable logging feature flag
   echo "ENABLE_AUTONOMOUS_LEARNING=true" >> .env

   # Monitor for 7 days, collect data
   ```

2. **Phase 2 → Production** (Week 2):
   ```bash
   # Run pattern detection on collected data
   python3 dev/phase2_pattern_detector.py --test-run

   # If patterns detected, review in Telegram
   # Promote code to production/pattern_detector.py
   ```

3. **Phase 3 → Production** (Week 3):
   ```bash
   # Generate first validator from detected pattern
   # Human review and approve
   # Add to data_validator_agent.py manually
   # Verify effectiveness over 7 days
   ```

4. **Phase 4 → Production** (Week 4):
   ```bash
   # Enable auto-deploy with high threshold
   echo "AUTO_DEPLOY_VALIDATORS=true" >> .env
   echo "AUTO_DEPLOY_THRESHOLD=95" >> .env

   # Monitor for 30 days with safety checks
   ```

---

## Success Metrics

### How We'll Know This Works

**Quantitative Metrics**:
1. **Pattern Detection Rate**: % of recurring issues that trigger pattern detection
   - Target: ≥80% of issues with 3+ occurrences detected as patterns

2. **Validator Effectiveness**: Issues prevented by auto-generated validators
   - Target: ≥90% of issues caught by new validators that would have been missed

3. **False Positive Rate**: Invalid issues flagged by auto-generated validators
   - Target: ≤5% false positive rate

4. **Time to Fix**: Days from issue occurrence to validator deployment
   - Current (manual): 1-7 days (as with ATMV)
   - Target (autonomous): <24 hours for high-confidence patterns

**Qualitative Metrics**:
1. **User Trust**: % of generated validators approved without modification
2. **Learning Accuracy**: Do generated validators match what human would create?
3. **System Stability**: No degradation to production validation performance

---

## Quick Start

### For Development
```bash
# Setup dev environment
cd /home/ubuntu/spac-research/dev

# Run Phase 1 (logging)
python3 phase1_logging.py --setup  # Create tables
python3 phase1_logging.py --test   # Test logging

# Run Phase 2 (pattern detection)
python3 phase2_pattern_detector.py --analyze --lookback 30

# Run Phase 3 (validator synthesis)
python3 phase3_validator_synthesis_agent.py --pattern-id 1 --preview

# Run Phase 4 (confidence scoring)
python3 phase4_confidence_engine.py --score-pattern 1
```

### For Testing
```bash
cd /home/ubuntu/spac-research/dev/tests

# Run all tests
python3 -m pytest

# Run specific test
python3 -m pytest test_atmv_scenario.py -v

# Run integration test
python3 test_autonomous_learning.py
```

---

## Risk Mitigation

### What Could Go Wrong?

1. **Bad Validator Generated**
   - **Mitigation**: Confidence thresholds, human review, monitoring, rollback
   - **Fallback**: All validators logged, can disable individual validators

2. **Performance Degradation**
   - **Mitigation**: Phase 1 logging has < 5% overhead, async pattern detection
   - **Fallback**: Feature flag can disable immediately

3. **Pattern False Positives**
   - **Mitigation**: Minimum threshold (3+ issues), confidence scoring
   - **Fallback**: Human review before deployment for medium confidence

4. **Database Corruption**
   - **Mitigation**: All changes logged, all fixes reversible
   - **Fallback**: Database backups, rollback capability

---

## Contact & Support

**Development Lead**: Claude Code
**Production Owner**: [Your Name]
**Review Process**: All generated validators reviewed via Telegram before production deployment

**Documentation**:
- Production System: `/home/ubuntu/spac-research/CLAUDE.md`
- Autonomous Learning: This file
- Integration Plan: `INTEGRATION_PLAN.md` (to be created)

---

## Changelog

- **2025-10-11**: Initial autonomous learning system design
- **2025-10-11**: Dev environment created, separation from production established
