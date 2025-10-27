"""
Tracks upcoming shareholder votes for mergers
"""

import sys
import os

sys.path.append('/home/ubuntu/spac-research')

from agents.orchestrator_agent_base import OrchestratorAgentBase
from database import SessionLocal, SPAC
from datetime import datetime, timedelta


class VoteTrackerAgent(OrchestratorAgentBase):
    """Monitors shareholder votes and deadlines"""

    def execute(self, task):
        self._start_task(task)

        try:
            # Check for upcoming votes
            db = SessionLocal()
            now = datetime.now()
            week_out = now + timedelta(days=7)
            two_weeks_out = now + timedelta(days=14)

            upcoming_votes = db.query(SPAC).filter(
                SPAC.shareholder_vote_date.isnot(None),
                SPAC.shareholder_vote_date >= week_out,
                SPAC.shareholder_vote_date <= two_weeks_out
            ).all()

            critical_votes = [
                {
                    'ticker': s.ticker,
                    'vote_date': s.shareholder_vote_date.isoformat(),
                    'days_until': (s.shareholder_vote_date - now).days,
                    'vote_purpose': s.vote_purpose
                }
                for s in upcoming_votes
            ]

            db.close()

            result = {
                'upcoming_votes': len(critical_votes),
                'votes': critical_votes
            }

            self._complete_task(task, result)

        except Exception as e:
            self._fail_task(task, str(e))

        return task


# PriceMonitorAgent moved to agents/price_monitor_agent.py
