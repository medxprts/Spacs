"""
Price Monitor Agent
Updates SPAC prices and detects price anomalies/spikes
"""

import sys
import os

sys.path.append('/home/ubuntu/spac-research')

from agents.orchestrator_agent_base import OrchestratorAgentBase
from database import SessionLocal, SPAC


class PriceMonitorAgent(OrchestratorAgentBase):
    """Updates prices and detects anomalies"""

    def execute(self, task):
        self._start_task(task)

        try:
            from batch_price_updater import batch_update_prices
            from orchestrator_trigger import trigger_price_spike

            print(f"   📊 Batch updating prices for all active SPACs...")

            # Use optimized batch updater (62-165x faster than sequential)
            # Old: ~22 seconds per SPAC × 145 = ~53 minutes
            # New: ~0.35 seconds per SPAC × 145 = ~51 seconds
            # Batch size 20 with 3-second delays to avoid Yahoo Finance rate limits
            updates = batch_update_prices(batch_size=20, delay_seconds=3)

            # Now check for price spikes in updated SPACs
            db = SessionLocal()
            spacs = db.query(SPAC).filter(
                SPAC.deal_status.in_(['SEARCHING', 'ANNOUNCED'])
            ).all()

            spikes = []
            volume_spikes = []

            for spac in spacs:
                # Check for price spike (≥5% change)
                if spac.price_change_24h and abs(spac.price_change_24h) >= 5.0:
                    # Trigger orchestrator investigation
                    triggered = trigger_price_spike(
                        ticker=spac.ticker,
                        price=spac.price,
                        change_pct=spac.price_change_24h,
                        deal_status=spac.deal_status
                    )

                    if triggered:
                        spikes.append({
                            'ticker': spac.ticker,
                            'price': spac.price,
                            'change': spac.price_change_24h,
                            'status': spac.deal_status
                        })
                        print(f"   🚨 Price spike detected: {spac.ticker} {spac.price_change_24h:+.1f}%")

                # Check for volume spike (>5% of float traded)
                if spac.volume and spac.shares_outstanding and spac.shares_outstanding > 0:
                    volume_pct_float = (spac.volume / spac.shares_outstanding) * 100

                    if volume_pct_float >= 5.0:
                        # Trigger volume spike investigation
                        triggered = trigger_price_spike(
                            ticker=spac.ticker,
                            price=spac.price,
                            change_pct=spac.price_change_24h or 0.0,
                            deal_status=spac.deal_status,
                            volume_spike=True,
                            volume_pct_float=volume_pct_float
                        )

                        if triggered:
                            volume_spikes.append({
                                'ticker': spac.ticker,
                                'volume': spac.volume,
                                'volume_pct_float': volume_pct_float,
                                'price_change': spac.price_change_24h
                            })
                            print(f"   📊 Volume spike detected: {spac.ticker} {volume_pct_float:.1f}% of float traded ({spac.volume:,} shares)")

            db.close()

            result = {
                'prices_updated': updates,
                'total_spacs': len(spacs),
                'spikes_detected': len(spikes),
                'spikes': spikes,
                'volume_spikes_detected': len(volume_spikes),
                'volume_spikes': volume_spikes
            }

            total_alerts = len(spikes) + len(volume_spikes)
            print(f"   ✅ Updated {updates}/{len(spacs)} SPACs, detected {len(spikes)} price spikes, {len(volume_spikes)} volume spikes")

            self._complete_task(task, result)

        except Exception as e:
            print(f"   ❌ Price monitor error: {e}")
            self._fail_task(task, str(e))

        return task
