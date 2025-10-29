#!/usr/bin/env python3
"""
phase3_validator_synthesis_agent.py - Validator Code Generation

Purpose: Generate new validation method code from detected patterns using AI.

Key Capabilities:
    1. Pattern → Validation Logic: Convert pattern to Python code
    2. Code Quality Assurance: Follow existing validator patterns
    3. Test Generation: Auto-generate test cases
    4. Documentation: Auto-generate docstrings with lessons learned

Architecture:
    detected_patterns table
        ↓
    ValidatorSynthesisAgent (this file)
        ↓  [DeepSeek API]
        ↓
    Generated validator code → Human Review → Deployment (Phase 4)

Usage:
    # Generate validator from pattern ID
    python3 phase3_validator_synthesis_agent.py --pattern-id 1

    # Preview without saving
    python3 phase3_validator_synthesis_agent.py --pattern-id 1 --preview

    # Generate and save to file
    python3 phase3_validator_synthesis_agent.py --pattern-id 1 --output validator.py
"""

import sys
import os
from datetime import datetime
from typing import Dict, Optional, Tuple
import json
import ast

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from sqlalchemy import text
import openai  # DeepSeek uses OpenAI-compatible API


class ValidatorSynthesisAgent:
    """
    AI-powered agent that generates validation method code from patterns

    Process:
        1. Load pattern from database
        2. Load examples of existing validators
        3. Use DeepSeek to generate new validator code
        4. Validate syntax
        5. Generate test cases
        6. Save to detected_patterns table
    """

    def __init__(self):
        """Initialize synthesis agent"""
        self.db = SessionLocal()

        # Setup DeepSeek API (OpenAI-compatible)
        api_key = os.getenv('DEEPSEEK_API_KEY')
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment")

        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        )

        print("✓ ValidatorSynthesisAgent initialized")

    def generate_validator(self, pattern_id: int) -> Dict:
        """
        Generate validator code from pattern

        Args:
            pattern_id: ID from detected_patterns table

        Returns: Dict with validator_code, test_code, confidence_score
        """
        print(f"\n{'='*70}")
        print(f"Validator Synthesis for Pattern ID {pattern_id}")
        print(f"{'='*70}\n")

        # Load pattern
        pattern = self._load_pattern(pattern_id)
        if not pattern:
            raise ValueError(f"Pattern {pattern_id} not found")

        print(f"Pattern: {pattern['pattern_name']}")
        print(f"Type: {pattern['pattern_type']}")
        print(f"Issues: {pattern['issue_count']}")
        print(f"Impact: {pattern['impact_score']:.1f}/100\n")

        # Load example validators from production
        example_validators = self._load_example_validators()

        # Generate validator code
        print("Generating validator code with DeepSeek AI...")
        validator_code = self._generate_code_with_ai(pattern, example_validators)

        # Validate syntax
        print("Validating syntax...")
        syntax_valid, syntax_error = self._validate_syntax(validator_code)

        if not syntax_valid:
            print(f"✗ Syntax validation failed: {syntax_error}")
            return {
                'validator_code': validator_code,
                'test_code': None,
                'confidence_score': 0.0,
                'errors': [f"Syntax error: {syntax_error}"]
            }

        print("✓ Syntax valid")

        # Generate test cases
        print("Generating test cases...")
        test_code = self._generate_test_cases(pattern, validator_code)

        # Calculate confidence score (Phase 4 does more sophisticated scoring)
        confidence = self._calculate_basic_confidence(pattern, validator_code, syntax_valid)

        print(f"\n✓ Validator generated successfully")
        print(f"  Confidence: {confidence:.1f}%")

        return {
            'validator_code': validator_code,
            'test_code': test_code,
            'confidence_score': confidence,
            'errors': []
        }

    def _load_pattern(self, pattern_id: int) -> Optional[Dict]:
        """Load pattern from database"""
        query = text("""
            SELECT
                id,
                pattern_name,
                pattern_type,
                description,
                issue_count,
                affected_tickers,
                common_characteristics,
                impact_score,
                recommended_validator_name,
                recommended_validator_rules
            FROM detected_patterns
            WHERE id = :pattern_id
        """)

        result = self.db.execute(query, {'pattern_id': pattern_id}).fetchone()

        if not result:
            return None

        return {
            'id': result[0],
            'pattern_name': result[1],
            'pattern_type': result[2],
            'description': result[3],
            'issue_count': result[4],
            'affected_tickers': result[5],
            'common_characteristics': json.loads(result[6]) if result[6] else {},
            'impact_score': result[7],
            'recommended_validator_name': result[8],
            'recommended_validator_rules': json.loads(result[9]) if result[9] else {}
        }

    def _load_example_validators(self) -> str:
        """
        Load example validators from production data_validator_agent.py

        These serve as templates for code generation
        """
        try:
            # Read production validator
            validator_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data_validator_agent.py'
            )

            with open(validator_path, 'r') as f:
                content = f.read()

            # Extract 2-3 example validator methods
            # For simplicity, extract temporal_consistency and cik_consistency as examples
            examples = []

            # Find validate_temporal_consistency
            start = content.find('def validate_temporal_consistency(')
            if start != -1:
                end = content.find('\n    def ', start + 1)
                if end == -1:
                    end = content.find('\nclass ', start + 1)
                examples.append(content[start:end].strip())

            # Find validate_cik_consistency
            start = content.find('def validate_cik_consistency(')
            if start != -1:
                end = content.find('\n    def ', start + 1)
                if end == -1:
                    end = content.find('\nclass ', start + 1)
                examples.append(content[start:end].strip())

            return "\n\n".join(examples)

        except Exception as e:
            print(f"⚠️  Could not load examples: {e}")
            return ""

    def _generate_code_with_ai(self, pattern: Dict, examples: str) -> str:
        """
        Use DeepSeek AI to generate validator code

        Args:
            pattern: Pattern dict with all characteristics
            examples: Example validator code from production

        Returns: Python code for new validator method
        """
        # Build prompt
        prompt = f"""You are an expert Python developer working on a SPAC data quality system.

TASK: Generate a new validation method for the DataValidatorAgent class.

PATTERN DETECTED:
- Name: {pattern['pattern_name']}
- Type: {pattern['pattern_type']}
- Description: {pattern['description']}
- Issue Count: {pattern['issue_count']}
- Impact Score: {pattern['impact_score']:.1f}/100
- Affected Tickers: {', '.join(pattern['affected_tickers'][:5])}

PATTERN CHARACTERISTICS:
{json.dumps(pattern['common_characteristics'], indent=2)}

RECOMMENDED VALIDATOR:
{json.dumps(pattern['recommended_validator_rules'], indent=2)}

EXISTING VALIDATOR EXAMPLES:
```python
{examples}
```

REQUIREMENTS:
1. Method name: {pattern['recommended_validator_name']}(self, spac: SPAC) -> List[Dict]
2. Follow the exact structure and style of the example validators above
3. Include comprehensive docstring explaining:
   - Purpose
   - Auto-generated from pattern (with date and affected tickers)
   - Lesson learned (why this validator was needed)
   - Validation rules
4. Return List[Dict] where each dict has keys:
   - type: issue type (str)
   - severity: CRITICAL/HIGH/MEDIUM/LOW
   - ticker: spac.ticker
   - field: affected field name
   - rule: rule name that failed
   - message: human-readable error message
   - auto_fix: suggested fix strategy
   - expected: what value should be
   - actual: what value is
   - metadata: dict with context (include pattern_id, auto_generated=True)
5. Handle edge cases (None values, type conversions)
6. Use same coding patterns as examples (early returns, clear variable names)

OUTPUT:
Generate ONLY the Python method code. No explanations, no markdown.
Start with "def {pattern['recommended_validator_name']}(self, spac: SPAC) -> List[Dict]:"
"""

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an expert Python developer specializing in data validation code generation."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3  # Lower temperature for more consistent code
            )

            code = response.choices[0].message.content.strip()

            # Clean up code (remove markdown if present)
            if code.startswith('```python'):
                code = code.split('```python')[1].split('```')[0].strip()
            elif code.startswith('```'):
                code = code.split('```')[1].split('```')[0].strip()

            return code

        except Exception as e:
            print(f"✗ AI generation failed: {e}")
            raise

    def _validate_syntax(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        Validate Python syntax

        Returns: (is_valid, error_message)
        """
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, str(e)

    def _generate_test_cases(self, pattern: Dict, validator_code: str) -> str:
        """
        Generate test cases for validator

        Uses AI to create pytest test cases
        """
        prompt = f"""Generate pytest test cases for this validator method:

PATTERN:
{json.dumps(pattern, indent=2)}

VALIDATOR CODE:
```python
{validator_code}
```

REQUIREMENTS:
1. Generate 3 test cases:
   - test_validator_catches_issue: Should detect the issue pattern is designed for
   - test_validator_passes_valid_data: Should pass when data is correct
   - test_validator_handles_edge_cases: Should handle None/missing values gracefully

2. Use pytest and mock SPAC objects

3. Test against the specific issues this pattern addresses (tickers: {', '.join(pattern['affected_tickers'][:3])})

OUTPUT:
Generate ONLY the Python test code. No explanations, no markdown.
"""

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an expert in writing Python unit tests."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )

            test_code = response.choices[0].message.content.strip()

            # Clean up
            if test_code.startswith('```python'):
                test_code = test_code.split('```python')[1].split('```')[0].strip()
            elif test_code.startswith('```'):
                test_code = test_code.split('```')[1].split('```')[0].strip()

            return test_code

        except Exception as e:
            print(f"⚠️  Test generation failed: {e}")
            return "# Test generation failed"

    def _calculate_basic_confidence(self, pattern: Dict, code: str,
                                    syntax_valid: bool) -> float:
        """
        Calculate basic confidence score for generated validator

        Phase 4 (confidence_engine.py) will do more sophisticated scoring.
        This is a simple heuristic for now.

        Factors:
        - Pattern impact score (weight: 40%)
        - Syntax valid (weight: 30%)
        - Code completeness (weight: 30%)
        """
        if not syntax_valid:
            return 0.0

        # Pattern strength (0-40 points)
        pattern_score = pattern['impact_score'] * 0.4

        # Syntax valid (30 points)
        syntax_score = 30.0

        # Code completeness (0-30 points)
        # Check for key components
        completeness_checks = [
            'def ' in code,
            'spac: SPAC' in code,
            'List[Dict]' in code,
            'issues = []' in code or 'issues = list()' in code,
            'return issues' in code,
            'severity' in code,
            'type' in code or "'type'" in code
        ]
        completeness_score = (sum(completeness_checks) / len(completeness_checks)) * 30

        total = pattern_score + syntax_score + completeness_score

        return round(min(100, total), 1)

    def save_generated_validator(self, pattern_id: int, result: Dict) -> bool:
        """
        Save generated validator to detected_patterns table

        Args:
            pattern_id: Pattern ID
            result: Result from generate_validator()

        Returns: Success boolean
        """
        try:
            update_query = text("""
                UPDATE detected_patterns
                SET
                    validator_code = :validator_code,
                    validator_confidence_score = :confidence_score,
                    validator_recommended = true,
                    status = 'validator_generated'
                WHERE id = :pattern_id
            """)

            self.db.execute(update_query, {
                'pattern_id': pattern_id,
                'validator_code': result['validator_code'],
                'confidence_score': result['confidence_score']
            })

            self.db.commit()
            print(f"✓ Saved validator to pattern {pattern_id}")
            return True

        except Exception as e:
            print(f"✗ Save failed: {e}")
            self.db.rollback()
            return False

    def __del__(self):
        """Cleanup"""
        if hasattr(self, 'db'):
            self.db.close()


# ============================================================================
# CLI Interface
# ============================================================================

def preview_generated_validator(pattern_id: int):
    """Generate and preview validator without saving"""
    agent = ValidatorSynthesisAgent()
    result = agent.generate_validator(pattern_id)

    if result['errors']:
        print(f"\n✗ Generation failed:")
        for error in result['errors']:
            print(f"  {error}")
        return

    print("\n" + "="*70)
    print("GENERATED VALIDATOR CODE")
    print("="*70 + "\n")
    print(result['validator_code'])

    print("\n" + "="*70)
    print("GENERATED TEST CODE")
    print("="*70 + "\n")
    print(result['test_code'])

    print(f"\nConfidence Score: {result['confidence_score']:.1f}/100")


def generate_and_save(pattern_id: int, output_file: Optional[str] = None):
    """Generate validator and save to database and/or file"""
    agent = ValidatorSynthesisAgent()
    result = agent.generate_validator(pattern_id)

    if result['errors']:
        print(f"\n✗ Generation failed:")
        for error in result['errors']:
            print(f"  {error}")
        return False

    # Save to database
    success = agent.save_generated_validator(pattern_id, result)

    # Save to file if requested
    if output_file:
        try:
            with open(output_file, 'w') as f:
                f.write("# Auto-generated validator code\n")
                f.write(f"# Pattern ID: {pattern_id}\n")
                f.write(f"# Generated: {datetime.now().isoformat()}\n")
                f.write(f"# Confidence: {result['confidence_score']:.1f}/100\n\n")
                f.write(result['validator_code'])
                f.write("\n\n# Test cases\n\n")
                f.write(result['test_code'])

            print(f"✓ Saved to {output_file}")
        except Exception as e:
            print(f"⚠️  Could not save to file: {e}")

    return success


def list_patterns_needing_validators():
    """Show patterns that need validators generated"""
    db = SessionLocal()
    try:
        query = text("""
            SELECT
                id,
                pattern_name,
                issue_count,
                impact_score,
                status,
                recommended_validator_name
            FROM detected_patterns
            WHERE validator_deployed = false
              AND status IN ('detected', 'validator_generated')
            ORDER BY impact_score DESC
        """)

        result = db.execute(query)

        print("\n" + "="*70)
        print("Patterns Needing Validator Generation")
        print("="*70 + "\n")

        for row in result:
            status_icon = "🔨" if row[4] == 'validator_generated' else "❌"
            print(f"{status_icon} Pattern {row[0]}: {row[1]}")
            print(f"   Issues: {row[2]} | Impact: {row[3]:.1f}/100 | Status: {row[4]}")
            print(f"   Recommended: {row[5]}")
            print()

    finally:
        db.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Phase 3: Validator Synthesis Agent')
    parser.add_argument('--pattern-id', type=int, metavar='ID',
                       help='Pattern ID to generate validator for')
    parser.add_argument('--preview', action='store_true',
                       help='Preview without saving')
    parser.add_argument('--output', type=str, metavar='FILE',
                       help='Save generated code to file')
    parser.add_argument('--list', action='store_true',
                       help='List patterns needing validators')

    args = parser.parse_args()

    if args.list:
        list_patterns_needing_validators()

    elif args.pattern_id:
        if args.preview:
            preview_generated_validator(args.pattern_id)
        else:
            generate_and_save(args.pattern_id, args.output)

    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python3 phase3_validator_synthesis_agent.py --list")
        print("  python3 phase3_validator_synthesis_agent.py --pattern-id 1 --preview")
        print("  python3 phase3_validator_synthesis_agent.py --pattern-id 1 --output validator.py")
