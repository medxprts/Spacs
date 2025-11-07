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
                # Check for price change - threshold depends on deal status
                # SEARCHING: 5% (near NAV, so smaller moves are significant)
                # ANNOUNCED: 10% (more volatile post-deal, need higher bar)
                price_threshold = 5.0 if spac.deal_status == 'SEARCHING' else 10.0

                if spac.price_change_24h and abs(spac.price_change_24h) >= price_threshold:
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
                        print(f"   🚨 Price change detected: {spac.ticker} {spac.price_change_24h:+.1f}% ({spac.deal_status})")

                # Check for volume spike with significance filter
                # Must pass significance filter first (prevents low-volume noise)
                if spac.volume and spac.public_float and spac.public_float > 0:
                    volume_pct_float = (spac.volume / spac.public_float) * 100

                    # Also calculate as % of total outstanding for significance filter
                    volume_pct_of_outstanding = (spac.volume / spac.shares_outstanding) * 100 if spac.shares_outstanding else 0

                    # Significance filter: Volume must be meaningful
                    is_significant_volume = (
                        spac.volume > 100_000 or  # Absolute minimum
                        volume_pct_float > 1.0  # Or >1% of public float (tradable shares)
                    )

                    if not is_significant_volume:
                        continue  # Skip low-volume SPACs

                    # Check for volume spike using dual criteria:
                    # 1. Absolute: >5% of float traded (existing)
                    # 2. Relative: >10x the 30-day average (new)
                    is_volume_spike = False
                    spike_reason = None

                    if volume_pct_float >= 5.0:
                        is_volume_spike = True
                        spike_reason = f"{volume_pct_float:.1f}% of float"

                    # Also check 10x 30-day average (if we have baseline data)
                    if spac.volume_avg_30d and spac.volume_avg_30d > 0:
                        volume_ratio = spac.volume / spac.volume_avg_30d
                        if volume_ratio >= 10.0:
                            is_volume_spike = True
                            spike_reason = f"{volume_ratio:.1f}x 30-day avg" if not spike_reason else f"{spike_reason} + {volume_ratio:.1f}x avg"

                    if is_volume_spike:
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
                                'price_change': spac.price_change_24h,
                                'reason': spike_reason
                            })
                            print(f"   📊 Volume spike detected: {spac.ticker} {spac.volume:,} shares ({spike_reason})")

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
