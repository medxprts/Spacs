#!/usr/bin/env python3
"""
Fix Applier - Centralized Fix Execution
Version: 2.0.0

Applies approved fixes to database with validation and rollback support.
"""

import sys
import os
from datetime import datetime
from typing import Dict, List, Optional
import yaml

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import SessionLocal, SPAC


class FixApplier:
    """
    Centralized fix application with validation and logging

    Features:
    - Apply fixes from YAML templates
    - Validate before/after
    - Log all changes
    - Support rollback
    """

    def __init__(self, db_session=None):
        """
        Initialize fix applier

        Args:
            db_session: Optional database session
        """
        self.db = db_session or SessionLocal()
        self.owns_session = db_session is None

        # Load fix templates
        self.fix_templates = self._load_fix_templates()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.owns_session:
            self.db.close()

    def _load_fix_templates(self) -> Dict:
        """Load fix templates from YAML"""
        template_file = os.path.join(
            os.path.dirname(__file__),
            '../config/fix_templates.yaml'
        )

        if not os.path.exists(template_file):
            print(f"⚠️  Fix templates not found: {template_file}")
            return {}

        with open(template_file, 'r') as f:
            config = yaml.safe_load(f)
            return config.get('fix_templates', {})

    def apply_fix(
        self,
        ticker: str,
        fix_template_id: str,
        custom_changes: Optional[Dict] = None
    ) -> Dict:
        """
        Apply fix to SPAC using template

        Args:
            ticker: SPAC ticker
            fix_template_id: Fix template ID (e.g., 'FIX-001')
            custom_changes: Optional custom changes to override template

        Returns:
            Result dictionary with success status and changes made
        """
        # Get SPAC
        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            return {
                'success': False,
                'error': f'SPAC {ticker} not found'
            }

        # Get fix template
        template = self._get_template(fix_template_id)
        if not template:
            return {
                'success': False,
                'error': f'Fix template {fix_template_id} not found'
            }

        # Check conditions
        if not self._check_conditions(spac, template.get('conditions', [])):
            return {
                'success': False,
                'error': 'Fix conditions not met'
            }

        # Apply changes
        changes_made = {}
        original_values = {}

        try:
            # Use custom changes if provided, otherwise use template
            changes = custom_changes or template.get('changes', [])

            for change in changes:
                field = change.get('field')
                action = change.get('action')

                # Store original value
                original_values[field] = getattr(spac, field, None)

                # Apply change
                if action == 'set_value':
                    new_value = change.get('value')
                    setattr(spac, field, new_value)
                    changes_made[field] = {
                        'old': original_values[field],
                        'new': new_value,
                        'action': 'set_value'
                    }

                elif action == 'set_null':
                    setattr(spac, field, None)
                    changes_made[field] = {
                        'old': original_values[field],
                        'new': None,
                        'action': 'set_null'
                    }

                elif action == 'calculate':
                    formula = change.get('formula')
                    calculated_value = self._calculate(spac, formula)
                    setattr(spac, field, calculated_value)
                    changes_made[field] = {
                        'old': original_values[field],
                        'new': calculated_value,
                        'action': 'calculate',
                        'formula': formula
                    }

            # Validate post-fix
            validation_passed = self._validate_post_fix(
                spac,
                template.get('post_fix_validation', [])
            )

            if not validation_passed:
                # Rollback changes
                for field, original in original_values.items():
                    setattr(spac, field, original)

                return {
                    'success': False,
                    'error': 'Post-fix validation failed',
                    'attempted_changes': changes_made
                }

            # Commit
            self.db.commit()

            return {
                'success': True,
                'changes': changes_made,
                'template_id': fix_template_id,
                'confidence': template.get('confidence', 0.5)
            }

        except Exception as e:
            # Rollback on error
            self.db.rollback()
            for field, original in original_values.items():
                setattr(spac, field, original)

            return {
                'success': False,
                'error': str(e),
                'attempted_changes': changes_made
            }

    def _get_template(self, template_id: str) -> Optional[Dict]:
        """Get fix template by ID"""
        for tid, template in self.fix_templates.items():
            if template.get('id') == template_id:
                return template
        return None

    def _check_conditions(self, spac: SPAC, conditions: List[Dict]) -> bool:
        """Check if all conditions are met"""
        for condition in conditions:
            field = condition.get('field')
            operator = condition.get('operator')
            value = condition.get('value')

            field_value = getattr(spac, field, None)

            if operator == 'age_days_less_than':
                if not spac.ipo_date:
                    return False
                age_days = (datetime.now().date() - spac.ipo_date.date()).days
                if age_days >= value:
                    return False

            elif operator == 'equals':
                if field_value != value:
                    return False

            elif operator == 'not_equals':
                if field_value == value:
                    return False

            elif operator == 'greater_than':
                if not field_value or field_value <= value:
                    return False

            elif operator == 'is_null':
                if field_value is not None:
                    return False

        return True

    def _calculate(self, spac: SPAC, formula: str) -> float:
        """
        Calculate value using formula

        Args:
            spac: SPAC object
            formula: Formula string (e.g., "shares_outstanding * 10.00")

        Returns:
            Calculated value
        """
        # Build safe namespace for evaluation
        namespace = {
            'shares_outstanding': getattr(spac, 'shares_outstanding', 0),
            'trust_value': getattr(spac, 'trust_value', 0),
            'price': getattr(spac, 'price', 0),
            'ipo_proceeds': getattr(spac, 'ipo_proceeds', 0)
        }

        try:
            # Evaluate formula
            result = eval(formula, {"__builtins__": {}}, namespace)
            return result
        except Exception as e:
            print(f"⚠️  Formula evaluation failed: {e}")
            return None

    def _validate_post_fix(self, spac: SPAC, validations: List[Dict]) -> bool:
        """Validate SPAC after fix applied"""
        for validation in validations:
            check = validation.get('check')
            error_message = validation.get('error_message')

            # Simple validation checks
            if 'trust_cash < ipo_proceeds' in check:
                if not spac.ipo_proceeds:
                    continue

                ipo_proceeds_value = float(
                    str(spac.ipo_proceeds).replace('$', '').replace('M', '')
                ) * 1_000_000

                if spac.trust_cash and spac.trust_cash >= ipo_proceeds_value:
                    print(f"❌ Validation failed: {error_message}")
                    return False

            elif 'trust_value == 10.00' in check:
                if spac.trust_value != 10.00:
                    print(f"❌ Validation failed: {error_message}")
                    return False

        return True


if __name__ == "__main__":
    # Test fix applier
    with FixApplier() as applier:
        print(f"Loaded {len(applier.fix_templates)} fix templates")

        # Test applying a fix (dry run)
        result = applier.apply_fix('TEST', 'FIX-001')
        print(f"Test result: {result}")
