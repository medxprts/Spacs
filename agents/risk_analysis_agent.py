"""
Risk Analysis Agent
Analyzes risk levels and flags urgent situations for SPACs approaching deadlines
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.append('/home/ubuntu/spac-research')

from agents.orchestrator_agent_base import OrchestratorAgentBase
from database import SessionLocal, SPAC


class RiskAnalysisAgent(OrchestratorAgentBase):
    """Analyzes risk levels and flags urgent situations"""

    def execute(self, task):
        self._start_task(task)

        try:
            db = SessionLocal()
            now = datetime.now()

            # Find urgent SPACs (deadline < 90 days)
            urgent_spacs = db.query(SPAC).filter(
                SPAC.deadline_date.isnot(None),
                SPAC.deadline_date <= now + timedelta(days=90),
                SPAC.deal_status == 'SEARCHING'
            ).all()

            risk_alerts = [
                {
                    'ticker': s.ticker,
                    'days_to_deadline': (s.deadline_date - now).days,
                    'premium': s.premium,
                    'risk_level': 'URGENT' if (s.deadline_date - now).days < 30 else 'HIGH'
                }
                for s in urgent_spacs
            ]

            db.close()

            result = {
                'urgent_count': len(risk_alerts),
                'alerts': risk_alerts
            }

            self._complete_task(task, result)

        except Exception as e:
            self._fail_task(task, str(e))

        return task
