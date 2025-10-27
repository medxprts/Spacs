"""
Checks for duplicate pre-IPO SPAC entries
"""

import sys
import os

sys.path.append('/home/ubuntu/spac-research')

from agents.orchestrator_agent_base import OrchestratorAgentBase
from database import SessionLocal, SPAC
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class PreIPODuplicateCheckerAgent(OrchestratorAgentBase):
    """Checks for pre-IPO SPACs incorrectly added to main table"""

    def execute(self, task):
        self._start_task(task)

        try:
            from pre_ipo_database import SessionLocal as PreIPOSession, PreIPOSPAC

            print("\n🔍 Checking for pre-IPO duplicates...")

            pre_ipo_db = PreIPOSession()
            main_db = SessionLocal()

            # Get all pre-IPO SPACs not yet graduated
            pre_ipo_spacs = pre_ipo_db.query(PreIPOSPAC).filter(
                PreIPOSPAC.moved_to_main_pipeline == False
            ).all()

            duplicates = []

            for pre_ipo_spac in pre_ipo_spacs:
                # Check if exists in main table by ticker or CIK
                main_by_ticker = main_db.query(SPAC).filter(
                    SPAC.ticker == pre_ipo_spac.expected_ticker
                ).first() if pre_ipo_spac.expected_ticker else None

                main_by_cik = main_db.query(SPAC).filter(
                    SPAC.cik == pre_ipo_spac.cik
                ).first() if pre_ipo_spac.cik else None

                if main_by_ticker or main_by_cik:
                    duplicates.append({
                        'company': pre_ipo_spac.company,
                        'expected_ticker': pre_ipo_spac.expected_ticker,
                        'cik': pre_ipo_spac.cik,
                        'main_ticker': (main_by_ticker or main_by_cik).ticker,
                        'ipo_date': (main_by_ticker or main_by_cik).ipo_date
                    })

            pre_ipo_db.close()
            main_db.close()

            result = {
                'duplicates_found': len(duplicates),
                'duplicates': duplicates,
                'pre_ipo_count': len(pre_ipo_spacs)
            }

            if duplicates:
                print(f"   ⚠️  Found {len(duplicates)} duplicate(s)")
                for dup in duplicates:
                    print(f"      - {dup['company']} ({dup['expected_ticker']}) also in main table as {dup['main_ticker']}")

                # Send Telegram alert if configured
                if hasattr(self, 'orchestrator_ref') and 'telegram' in self.orchestrator_ref.agents:
                    alert_text = f"🚨 <b>PRE-IPO DUPLICATE ALERT</b>\n\n"
                    alert_text += f"Found {len(duplicates)} pre-IPO SPAC(s) incorrectly in main table:\n\n"
                    for dup in duplicates:
                        alert_text += f"• {dup['company']} ({dup['expected_ticker']})\n"
                        alert_text += f"  Main ticker: {dup['main_ticker']}\n"
                        alert_text += f"  IPO date: {dup['ipo_date'] or 'N/A'}\n\n"
                    alert_text += "Run: <code>python3 check_pre_ipo_duplicates.py</code> for details"

                    telegram_task = AgentTask(
                        task_id=f"telegram_duplicate_alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        agent_name="telegram",
                        task_type="send_alert",
                        priority=TaskPriority.HIGH,
                        status=TaskStatus.PENDING,
                        created_at=datetime.now(),
                        parameters={'alert_text': alert_text}
                    )
                    self.orchestrator_ref.agents['telegram'].execute(telegram_task)

            else:
                print(f"   ✅ No duplicates found ({len(pre_ipo_spacs)} pre-IPO SPACs checked)")

            self._complete_task(task, result)

        except Exception as e:
            print(f"   ❌ Error checking duplicates: {e}")
            import traceback
            traceback.print_exc()
            self._fail_task(task, str(e))

        return task
