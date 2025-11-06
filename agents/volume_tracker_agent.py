#!/usr/bin/env python3
"""
Volume Tracker Agent - Orchestrator-integrated volume monitoring

Tracks trading volume patterns and detects unusual activity that may signal deal rumors.

Features:
- Calculates 30-day average volume
- Detects volume spikes (3x, 5x, 10x average)
- Updates database with volume metrics
- Triggers investigation for extreme spikes
- Integrates with orchestrator scheduling

Usage:
    From orchestrator: Runs on schedule (every 30 minutes during market hours)
    Standalone: python3 agents/volume_tracker_agent.py
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from database import SessionLocal, SPAC
from agents.orchestrator_agent_base import OrchestratorAgentBase
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VolumeTrackerAgent(OrchestratorAgentBase):
    """
    Tracks volume patterns and detects unusual trading activity

    Runs on schedule to:
    1. Calculate 30-day average volume for all active SPACs
    2. Detect volume spikes (3x, 5x, 10x average)
    3. Flag SPACs with unusual activity for investigation
    4. Update volume_avg_30d in database
    """

    def __init__(self):
        super().__init__('VolumeTracker')
        self.spike_threshold_moderate = 3.0  # 3x average
        self.spike_threshold_high = 5.0      # 5x average
        self.spike_threshold_extreme = 10.0  # 10x average

    def execute(self, task: Dict) -> Dict:
        """
        Execute volume tracking task

        Task types:
        - 'update_all': Update volume metrics for all active SPACs
        - 'check_ticker': Check volume for specific ticker
        """
        # Handle both dict and task object
        if hasattr(task, 'status'):
            self._start_task(task)
            task_dict = task.parameters or {}
        else:
            task_dict = task

        try:
            task_type = task_dict.get('task_type', 'update_all')

            if task_type == 'update_all':
                result = self._update_all_volumes()
            elif task_type == 'check_ticker':
                ticker = task_dict.get('ticker')
                result = self._check_ticker_volume(ticker)
            else:
                raise ValueError(f"Unknown task type: {task_type}")

            if hasattr(task, 'status'):
                self._complete_task(task, result)
            return result

        except Exception as e:
            error_msg = f"Volume tracking failed: {str(e)}"
            logger.error(error_msg)
            if hasattr(task, 'status'):
                self._fail_task(task, error_msg)
            return {'success': False, 'error': error_msg}

    def _update_all_volumes(self) -> Dict:
        """Update volume metrics for all active SPACs"""
        db = SessionLocal()

        try:
            # Get all SPACs that are SEARCHING or ANNOUNCED
            spacs = db.query(SPAC).filter(
                SPAC.deal_status.in_(['SEARCHING', 'ANNOUNCED'])
            ).all()

            logger.info(f"📊 Updating volume tracking for {len(spacs)} SPACs...")

            updated = 0
            spikes_detected = 0
            spike_details = []

            for spac in spacs:
                metrics = self._calculate_volume_metrics(spac.ticker)

                if not metrics:
                    continue

                # Update database
                old_avg = spac.volume_avg_30d
                spac.volume_avg_30d = metrics['avg_volume_30d']

                # Log significant spikes
                if metrics['is_volume_spike']:
                    spike_info = {
                        'ticker': spac.ticker,
                        'level': metrics['spike_level'],
                        'current_volume': metrics['current_volume'],
                        'avg_volume': metrics['avg_volume_30d'],
                        'spike_ratio': metrics['volume_spike_ratio']
                    }
                    spike_details.append(spike_info)

                    logger.info(
                        f"🔥 {spac.ticker}: {metrics['spike_level']} volume spike - "
                        f"{metrics['current_volume']:,} vs {metrics['avg_volume_30d']:,.0f} avg "
                        f"({metrics['volume_spike_ratio']}x)"
                    )
                    spikes_detected += 1

                    # Trigger investigation for EXTREME spikes (10x+)
                    if metrics['spike_level'] == 'EXTREME':
                        self._trigger_volume_investigation(spac.ticker, metrics)

                updated += 1

                if updated % 20 == 0:
                    db.commit()
                    logger.info(f"   Processed {updated}/{len(spacs)}...")

            db.commit()
            logger.info(f"✅ Volume tracking updated: {updated} SPACs, {spikes_detected} spikes detected")

            return {
                'success': True,
                'spacs_updated': updated,
                'spikes_detected': spikes_detected,
                'spike_details': spike_details
            }

        finally:
            db.close()

    def _check_ticker_volume(self, ticker: str) -> Dict:
        """Check volume for specific ticker"""
        if not ticker:
            return {'success': False, 'error': 'No ticker provided'}

        db = SessionLocal()
        try:
            spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
            if not spac:
                return {'success': False, 'error': f'SPAC {ticker} not found'}

            metrics = self._calculate_volume_metrics(ticker)
            if not metrics:
                return {'success': False, 'error': f'Could not fetch volume data for {ticker}'}

            # Update database
            spac.volume_avg_30d = metrics['avg_volume_30d']
            db.commit()

            return {
                'success': True,
                'ticker': ticker,
                'metrics': metrics
            }
        finally:
            db.close()

    def _calculate_volume_metrics(self, ticker: str, period: str = "30d") -> Optional[Dict]:
        """
        Calculate volume metrics for a ticker

        Returns:
            {
                'avg_volume_30d': float,
                'current_volume': int,
                'volume_spike_ratio': float,
                'is_volume_spike': bool,
                'spike_level': str  # 'EXTREME' (10x), 'HIGH' (5x), 'MODERATE' (3x), 'NORMAL'
            }
        """
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period, auto_adjust=True)

            if hist.empty or len(hist) < 5:
                logger.warning(f"{ticker}: Insufficient data ({len(hist)} days)")
                return None

            # Get current volume (most recent day)
            current_volume = int(hist['Volume'].iloc[-1])

            # Calculate 30-day average (excluding today for comparison)
            if len(hist) > 1:
                avg_volume_30d = hist['Volume'].iloc[:-1].mean()
            else:
                avg_volume_30d = current_volume

            # Calculate spike ratio
            spike_ratio = current_volume / avg_volume_30d if avg_volume_30d > 0 else 1.0

            # Classify spike level
            if spike_ratio >= self.spike_threshold_extreme:
                spike_level = 'EXTREME'
                is_spike = True
            elif spike_ratio >= self.spike_threshold_high:
                spike_level = 'HIGH'
                is_spike = True
            elif spike_ratio >= self.spike_threshold_moderate:
                spike_level = 'MODERATE'
                is_spike = True
            else:
                spike_level = 'NORMAL'
                is_spike = False

            return {
                'avg_volume_30d': round(avg_volume_30d, 2),
                'current_volume': current_volume,
                'volume_spike_ratio': round(spike_ratio, 2),
                'is_volume_spike': is_spike,
                'spike_level': spike_level
            }

        except Exception as e:
            logger.error(f"{ticker}: Error calculating volume metrics - {e}")
            return None

    def _trigger_volume_investigation(self, ticker: str, metrics: Dict):
        """
        Trigger investigation for extreme volume spike

        This could indicate:
        - Deal rumor leaking
        - Insider trading
        - Major news pending
        """
        try:
            logger.info(f"🔍 Triggering investigation for {ticker} - EXTREME volume spike ({metrics['volume_spike_ratio']}x)")

            # Optional: Trigger orchestrator investigation
            # This would check for recent news, SEC filings, Reddit mentions
            # For now, just log it

            # Optional: Send Telegram alert
            try:
                from utils.telegram_notifier import send_telegram_alert
                send_telegram_alert(f"""
🚨 <b>EXTREME VOLUME SPIKE DETECTED</b>

<b>Ticker:</b> {ticker}
<b>Current Volume:</b> {metrics['current_volume']:,}
<b>30-Day Average:</b> {metrics['avg_volume_30d']:,.0f}
<b>Spike Ratio:</b> {metrics['volume_spike_ratio']}x

⚠️ Possible deal rumor or major news pending
                """)
            except:
                pass  # Telegram not configured

        except Exception as e:
            logger.error(f"Error triggering investigation: {e}")

    def get_volume_spike_candidates(self, min_spike_ratio: float = 3.0) -> List[Dict]:
        """
        Get SPACs with unusual volume spikes (potential deal rumors)

        Args:
            min_spike_ratio: Minimum volume spike ratio (default 3x)

        Returns:
            List of dicts with SPAC info and volume metrics
        """
        db = SessionLocal()

        try:
            spacs = db.query(SPAC).filter(
                SPAC.deal_status == 'SEARCHING',
                SPAC.volume.isnot(None),
                SPAC.volume_avg_30d.isnot(None)
            ).all()

            candidates = []

            for spac in spacs:
                if spac.volume_avg_30d > 0:
                    spike_ratio = spac.volume / spac.volume_avg_30d

                    if spike_ratio >= min_spike_ratio:
                        candidates.append({
                            'ticker': spac.ticker,
                            'company': spac.company,
                            'volume': spac.volume,
                            'avg_volume_30d': spac.volume_avg_30d,
                            'spike_ratio': round(spike_ratio, 2),
                            'premium': spac.premium,
                            'ipo_proceeds': spac.ipo_proceeds,
                            'banker': spac.banker,
                            'sector': spac.sector
                        })

            # Sort by spike ratio descending
            candidates.sort(key=lambda x: x['spike_ratio'], reverse=True)

            return candidates

        finally:
            db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Volume Tracker Agent')
    parser.add_argument('--update', action='store_true', help='Update volume tracking for all SPACs')
    parser.add_argument('--ticker', type=str, help='Check volume for specific ticker')
    parser.add_argument('--spikes', action='store_true', help='Show current volume spike candidates')
    parser.add_argument('--min-spike', type=float, default=3.0, help='Minimum spike ratio (default 3.0)')

    args = parser.parse_args()

    agent = VolumeTrackerAgent()

    if args.update:
        task = {'task_type': 'update_all'}
        result = agent.execute(task)
        print(f"\n✅ Updated: {result.get('spacs_updated')} SPACs")
        print(f"🔥 Spikes: {result.get('spikes_detected')} detected")

    elif args.ticker:
        task = {'task_type': 'check_ticker', 'ticker': args.ticker}
        result = agent.execute(task)
        if result['success']:
            metrics = result['metrics']
            print(f"\n{args.ticker} Volume Metrics:")
            print(f"  Current: {metrics['current_volume']:,}")
            print(f"  30-Day Avg: {metrics['avg_volume_30d']:,.0f}")
            print(f"  Spike Ratio: {metrics['volume_spike_ratio']}x")
            print(f"  Level: {metrics['spike_level']}")

    elif args.spikes:
        candidates = agent.get_volume_spike_candidates(min_spike_ratio=args.min_spike)

        if candidates:
            print(f"\n🔥 {len(candidates)} Volume Spike Candidates ({args.min_spike}x+ average):\n")
            print(f"{'Ticker':<8} {'Company':<30} {'Volume':>12} {'30d Avg':>12} {'Spike':>8} {'Premium':>8} {'IPO Size':<10}")
            print("-" * 110)

            for c in candidates:
                print(
                    f"{c['ticker']:<8} {c['company'][:28]:<30} "
                    f"{c['volume']:>12,} {c['avg_volume_30d']:>12,.0f} "
                    f"{c['spike_ratio']:>7.1f}x {c['premium']:>7.1f}% {c['ipo_proceeds'] or 'N/A':<10}"
                )
        else:
            print(f"\nNo volume spikes detected (min {args.min_spike}x)")

    else:
        parser.print_help()
