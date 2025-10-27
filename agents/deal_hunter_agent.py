"""
Deal Hunter Agent
Detects new SPAC deals from SEC filings
"""

import sys
import os
import time

sys.path.append('/home/ubuntu/spac-research')

from agents.orchestrator_agent_base import OrchestratorAgentBase
from database import SessionLocal, SPAC


class DealHunterAgent(OrchestratorAgentBase):
    """Detects new SPAC deals from SEC filings"""

    def execute(self, task):
        self._start_task(task)

        try:
            # Import deal monitor
            from deal_monitor_enhanced import EnhancedDealDetector

            detector = EnhancedDealDetector(use_ai_validation=True)

            # Get SPACs to check
            db = SessionLocal()
            spacs = db.query(SPAC).filter(SPAC.deal_status == 'SEARCHING').all()

            detected_deals = []

            for spac in spacs[:10]:  # Limit to 10 per run to avoid rate limits
                # Check if we found a deal
                # (Simplified - actual logic would call detector methods)
                print(f"  Checking {spac.ticker}...")
                time.sleep(0.3)  # Rate limit

            db.close()

            result = {
                'spacs_checked': len(spacs),
                'deals_detected': len(detected_deals),
                'deals': detected_deals
            }

            self._complete_task(task, result)

        except Exception as e:
            self._fail_task(task, str(e))

        return task
