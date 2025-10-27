"""
Auto-fixes common data quality issues
"""

import sys
import os

sys.path.append('/home/ubuntu/spac-research')

from agents.orchestrator_agent_base import OrchestratorAgentBase
from database import SessionLocal, SPAC
from datetime import datetime, timedelta


class DataQualityFixerAgent(OrchestratorAgentBase):
    """Auto-fixes common data quality issues"""

    def execute(self, task):
        self._start_task(task)

        try:
            from agents.data_quality_fixer_agent import DataQualityFixerAgent as Fixer

            # Get parameters
            auto_commit = task.parameters.get('auto_commit', True)
            fix_types = task.parameters.get('fix_types', False)  # Decimal/Float
            fix_dates = task.parameters.get('fix_dates', False)  # String→Datetime
            fix_trust = task.parameters.get('fix_trust', False)  # 424B4 re-scrape

            fixer = Fixer(auto_commit=auto_commit)

            result = {
                'type_fixes': 0,
                'date_fixes': 0,
                'trust_errors_found': 0,
                'trust_rescraped': 0,
                'approval_needed': False
            }

            # Run fixes
            if fix_types or (not fix_types and not fix_dates and not fix_trust):
                # Fix type mismatches (Decimal/Float)
                result['type_fixes'] = fixer.fix_decimal_float_mismatch()

            if fix_dates or (not fix_types and not fix_dates and not fix_trust):
                # Fix date formats
                result['date_fixes'] = fixer.fix_expected_close_dates()

            if fix_trust or (not fix_types and not fix_dates and not fix_trust):
                # Fix trust cash errors (may need approval)
                trust_result = fixer.fix_trust_cash_batch(max_spacs=5, auto_approve=False)
                result['trust_errors_found'] = trust_result['errors_found']
                result['trust_rescraped'] = trust_result.get('rescraped', 0)
                result['approval_needed'] = trust_result.get('approval_needed', False)

            result['total_fixes'] = result['type_fixes'] + result['date_fixes'] + result['trust_rescraped']

            fixer.close()

            self._complete_task(task, result)

        except Exception as e:
            self._fail_task(task, str(e))

        return task
