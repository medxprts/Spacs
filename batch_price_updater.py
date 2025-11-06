#!/usr/bin/env python3
"""
Optimized Batch Price Updater - Uses yfinance batch download for 10x+ speed improvement

Instead of sequential API calls (1-2 seconds per ticker),
this uses yfinance.download() to fetch all tickers in parallel batches.

Performance:
- Old: ~480 seconds for 22 SPACs (~22 sec/ticker)
- New: ~30-60 seconds for 145 SPACs (~0.4 sec/ticker)
"""

import yfinance as yf
from database import SessionLocal, SPAC
from datetime import datetime
from typing import Dict, List
import logging
import warnings

# Suppress yfinance FutureWarnings to reduce log spam
warnings.filterwarnings('ignore', category=FutureWarning, module='yfinance')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress yfinance download errors (expected for delisted tickers)
logging.getLogger('yfinance').setLevel(logging.CRITICAL)


def batch_update_prices(batch_size=20, delay_seconds=3) -> int:
    """
    Update all SPAC prices using batch downloads

    Args:
        batch_size: Number of tickers to fetch in each batch (default 20, reduced from 30)
        delay_seconds: Seconds to wait between batches (default 3, increased from 2)

    Returns:
        Number of SPACs successfully updated
    """
    import time

    db = SessionLocal()

    try:
        # Get all active SPACs
        spacs = db.query(SPAC).filter(
            SPAC.deal_status.in_(['SEARCHING', 'ANNOUNCED'])
        ).all()

        total = len(spacs)
        logger.info(f"📊 Batch updating prices for {total} active SPACs...")

        # Build list of all tickers to fetch (common + units + warrants + rights)
        common_tickers = [s.ticker for s in spacs]
        unit_tickers = [s.unit_ticker for s in spacs if s.unit_ticker]
        warrant_tickers = [s.warrant_ticker for s in spacs if s.warrant_ticker]
        rights_tickers = [s.right_ticker for s in spacs if s.right_ticker]

        # Combine all unique tickers
        all_tickers = list(set(common_tickers + unit_tickers + warrant_tickers + rights_tickers))

        logger.info(f"   Fetching {len(common_tickers)} common + {len(unit_tickers)} units + {len(warrant_tickers)} warrants + {len(rights_tickers)} rights = {len(all_tickers)} total tickers")

        # Group into batches
        batches = [all_tickers[i:i + batch_size] for i in range(0, len(all_tickers), batch_size)]

        all_data = {}  # ticker -> price data
        retry_tickers = []  # Track tickers that need retry

        # Download all batches (common, units, warrants, rights together)
        for batch_num, batch_tickers in enumerate(batches, 1):
            logger.info(f"   Fetching batch {batch_num}/{len(batches)} ({len(batch_tickers)} tickers)...")

            # Rate limiting: Wait between batches (except first)
            if batch_num > 1:
                time.sleep(delay_seconds)

            try:
                # Download batch with 5 days of data (captures recent IPOs better than 2d)
                batch_str = ' '.join(batch_tickers)
                data = yf.download(
                    batch_str,
                    period='5d',
                    group_by='ticker',
                    threads=True,  # Parallel downloads
                    progress=False,
                    auto_adjust=True  # Suppress FutureWarning
                )

                # Process each ticker in the batch
                for ticker in batch_tickers:
                    try:
                        if len(batch_tickers) == 1:
                            # Single ticker - data is not grouped
                            ticker_data = data
                        else:
                            # Multiple tickers - data is grouped by ticker
                            ticker_data = data[ticker] if ticker in data else None

                        if ticker_data is None or ticker_data.empty:
                            continue

                        # Get latest close and volume
                        close_prices = ticker_data['Close']
                        volumes = ticker_data['Volume'] if 'Volume' in ticker_data else None

                        if close_prices.empty:
                            continue

                        current_price = float(close_prices.iloc[-1])
                        current_volume = int(volumes.iloc[-1]) if volumes is not None and not volumes.empty else 0

                        # Calculate 24h change
                        price_change_24h = None
                        if len(close_prices) >= 2:
                            prev_price = float(close_prices.iloc[-2])
                            price_change_24h = ((current_price - prev_price) / prev_price) * 100

                        all_data[ticker] = {
                            'price': current_price,
                            'volume': current_volume,
                            'price_change_24h': price_change_24h
                        }

                    except Exception as e:
                        logger.debug(f"      {ticker}: {e}")
                        continue

            except Exception as e:
                logger.error(f"   Batch {batch_num} download failed: {e}")
                continue

        # Update database
        logger.info(f"   💾 Updating database with {len(all_data)} prices...")

        updates = 0
        now = datetime.now()

        for spac in spacs:
            try:
                updated_any = False

                # Check if units have split
                # Units are split when: unit ticker stops trading AND common ticker has trading
                unit_has_data = spac.unit_ticker and spac.unit_ticker in all_data
                common_has_data = spac.ticker in all_data

                # Detect split status
                if unit_has_data and common_has_data:
                    # Both trading - units haven't split yet, use unit price
                    unit_volume = all_data[spac.unit_ticker].get('volume', 0)
                    common_volume = all_data[spac.ticker].get('volume', 0)

                    if unit_volume > common_volume:
                        # Units are still primary trading vehicle
                        units_split = False
                    else:
                        # Common is now primary - units have split
                        units_split = True
                elif unit_has_data and not common_has_data:
                    # Only units trading - not split yet
                    units_split = False
                elif not unit_has_data and common_has_data:
                    # Only common trading - definitely split
                    units_split = True
                else:
                    # No data for either - assume not split
                    units_split = False

                # Update common share price ONLY if units have split
                if common_has_data and units_split:
                    data = all_data[spac.ticker]
                    nav = float(spac.trust_value) if spac.trust_value else 10.00
                    premium = ((data['price'] - nav) / nav) * 100

                    spac.price = data['price']
                    spac.volume = data['volume']
                    spac.price_change_24h = data['price_change_24h']
                    spac.premium = premium
                    updated_any = True

                # Update unit price (always update if available)
                if unit_has_data:
                    spac.unit_price = all_data[spac.unit_ticker]['price']
                    updated_any = True

                # Update warrant price (always update if available)
                if spac.warrant_ticker and spac.warrant_ticker in all_data:
                    spac.warrant_price = all_data[spac.warrant_ticker]['price']
                    updated_any = True

                # Update rights price (always update if available)
                if spac.right_ticker and spac.right_ticker in all_data:
                    spac.rights_price = all_data[spac.right_ticker]['price']
                    updated_any = True

                if updated_any:
                    # last_updated auto-updates via SQLAlchemy onupdate
                    spac.last_price_update = now
                    updates += 1

            except Exception as e:
                logger.error(f"      {spac.ticker}: Database update failed - {e}")
                continue

        db.commit()
        logger.info(f"   ✅ Updated {updates}/{total} SPACs successfully")

        return updates

    finally:
        db.close()


def main():
    """Run batch price update"""
    import time

    start = time.time()
    updated = batch_update_prices()
    elapsed = time.time() - start

    logger.info(f"\n📊 Batch Update Complete")
    logger.info(f"   Updated: {updated} SPACs")
    logger.info(f"   Time: {elapsed:.1f}s")
    logger.info(f"   Speed: {elapsed/updated:.2f}s per SPAC" if updated > 0 else "   Speed: N/A")


if __name__ == "__main__":
    main()
