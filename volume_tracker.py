#!/usr/bin/env python3
"""
Volume Tracker - Detect unusual volume spikes for deal speculation

Tracks:
- 30-day average volume
- Volume spikes (3x, 5x, 10x average)
- Updates volume_avg_30d in database
- Flags SPACs with unusual trading activity

Used by Deal Spec Candidates screener to identify potential deal rumors
"""

import yfinance as yf
from datetime import datetime, timedelta
from database import SessionLocal, SPAC
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def calculate_volume_metrics(ticker: str, period: str = "30d") -> dict:
    """
    Calculate volume metrics for a ticker
    
    Returns:
        {
            'avg_volume_30d': float,
            'current_volume': int,
            'volume_spike_ratio': float,  # current / 30d avg
            'is_volume_spike': bool,       # True if 3x+ average
            'spike_level': str             # 'EXTREME' (10x), 'HIGH' (5x), 'MODERATE' (3x), 'NORMAL'
        }
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        
        if hist.empty or len(hist) < 5:
            logger.warning(f"{ticker}: Insufficient data")
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
        if spike_ratio >= 10:
            spike_level = 'EXTREME'
            is_spike = True
        elif spike_ratio >= 5:
            spike_level = 'HIGH'
            is_spike = True
        elif spike_ratio >= 3:
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


def update_volume_tracking():
    """Update volume tracking for all active SPACs"""
    db = SessionLocal()
    
    try:
        # Get all SPACs that are SEARCHING or ANNOUNCED
        spacs = db.query(SPAC).filter(
            SPAC.deal_status.in_(['SEARCHING', 'ANNOUNCED'])
        ).all()
        
        logger.info(f"Updating volume tracking for {len(spacs)} SPACs...")
        
        updated = 0
        spikes_detected = 0
        
        for spac in spacs:
            metrics = calculate_volume_metrics(spac.ticker)
            
            if not metrics:
                continue
            
            # Update database
            spac.volume_avg_30d = metrics['avg_volume_30d']
            
            # Log significant spikes
            if metrics['is_volume_spike']:
                logger.info(
                    f"🔥 {spac.ticker}: {metrics['spike_level']} volume spike - "
                    f"{metrics['current_volume']:,} vs {metrics['avg_volume_30d']:,.0f} avg "
                    f"({metrics['volume_spike_ratio']}x)"
                )
                spikes_detected += 1
            
            updated += 1
            
            if updated % 20 == 0:
                db.commit()
                logger.info(f"   Processed {updated}/{len(spacs)}...")
        
        db.commit()
        logger.info(f"✅ Volume tracking updated: {updated} SPACs, {spikes_detected} spikes detected")
        
        return updated, spikes_detected
    
    finally:
        db.close()


def get_volume_spike_candidates(min_spike_ratio: float = 3.0):
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
    
    parser = argparse.ArgumentParser(description='Track volume spikes for deal speculation')
    parser.add_argument('--update', action='store_true', help='Update volume tracking for all SPACs')
    parser.add_argument('--spikes', action='store_true', help='Show current volume spike candidates')
    parser.add_argument('--min-spike', type=float, default=3.0, help='Minimum spike ratio (default 3.0)')
    
    args = parser.parse_args()
    
    if args.update:
        update_volume_tracking()
    
    if args.spikes:
        candidates = get_volume_spike_candidates(min_spike_ratio=args.min_spike)
        
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
