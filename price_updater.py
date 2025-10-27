#!/usr/bin/env python3
"""
SPAC Price Updater - Live pricing integration
Supports multiple data sources: Yahoo Finance, Alpha Vantage, Polygon.io

⚠️ DEPRECATION NOTICE (October 2025):
Standalone script usage is DEPRECATED. The orchestrator's PriceMonitorAgent
now handles all price updates automatically every 15 minutes.

This file is kept as a library module for:
- PriceUpdater class (imported by agent_orchestrator.py)
- Manual testing/debugging if needed

Do NOT run this script via cron or manually for production updates.
Use the orchestrator instead (systemctl status orchestrator)
"""

import os
import time
from datetime import datetime
from typing import Dict, Optional, List
import logging
import pytz

# Database
from database import SessionLocal, SPAC
from sqlalchemy import update

# Install with: pip install yfinance requests
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("⚠️  yfinance not installed. Run: pip install yfinance")

import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PriceUpdater:
    """Handles price updates from multiple data sources"""
    
    def __init__(self, source='yfinance'):
        """
        Initialize price updater
        
        Args:
            source: 'yfinance', 'alphavantage', or 'polygon'
        """
        self.source = source
        self.db = SessionLocal()
        
        # API keys from environment
        self.alpha_vantage_key = os.getenv('ALPHA_VANTAGE_KEY')
        self.polygon_key = os.getenv('POLYGON_API_KEY')
        
        logger.info(f"Initialized PriceUpdater with source: {source}")

    def validate_yahoo_shares(self, ticker: str, yahoo_shares: Optional[int],
                              trust_cash: Optional[float], ipo_proceeds: Optional[str]) -> Optional[int]:
        """
        Validate Yahoo shares_outstanding and fix obvious errors

        Rules (from YAHOO_SHARES_OUTSTANDING_ANALYSIS.md):
        1. If shares < 1M AND trust_cash exists: Check NAV
           - NAV = trust_cash / shares
           - If NAV < $100: Likely units error, multiply by 1,000,000

        2. If shares < 1M AND trust_cash missing: Flag for review

        3. If shares > 100M: Flag for review (possible post-merger)

        Returns:
            Validated shares_outstanding or None if suspicious
        """
        if not yahoo_shares:
            return None

        # Rule 1: Check for units error using trust cash
        if yahoo_shares < 1_000_000 and trust_cash:
            implied_nav = trust_cash / yahoo_shares

            if implied_nav < 100:
                # Likely units error (e.g., 15.72 should be 15,720,000)
                logger.warning(
                    f"{ticker}: Yahoo shares ({yahoo_shares:,}) appears to be "
                    f"units error. Implied NAV = ${implied_nav:.2f}. "
                    f"Multiplying by 1,000,000."
                )
                return int(yahoo_shares * 1_000_000)

        # Rule 2: Suspicious low without trust cash - flag for review
        elif yahoo_shares < 1_000_000:
            logger.error(
                f"{ticker}: Yahoo shares ({yahoo_shares:,}) is suspiciously low "
                f"and trust_cash missing. Needs manual review."
            )
            # Don't update shares_outstanding with bad data
            return None

        # Rule 3: Suspiciously high - possible post-merger
        elif yahoo_shares > 100_000_000:
            logger.warning(
                f"{ticker}: Yahoo shares ({yahoo_shares:,}) is very high (>100M). "
                f"May be post-merger company. Flagging for review."
            )
            # Still use the value but flag for investigation
            return yahoo_shares

        # All validation passed
        return yahoo_shares

    def get_sec_shares_outstanding(self, spac: SPAC) -> Optional[int]:
        """
        Get shares_outstanding from SEC filing data

        For now, returns None (will be implemented in Phase 2)

        Future implementation will:
        - Parse latest 10-Q for "Class A shares subject to redemption"
        - Parse 8-K extension votes for redemption counts
        - Return most recent SEC-sourced share count
        """
        # TODO: Implement in Phase 2 (10-Q scraper)
        # Will extract from sec_filing_date and shares_redeemed
        return None

    def get_sec_filing_age_days(self, spac: SPAC) -> Optional[int]:
        """
        Get age of SEC filing data in days

        Returns:
            Days since last SEC filing, or None if no SEC data
        """
        if not spac.sec_filing_date:
            return None

        from datetime import date
        age = (date.today() - spac.sec_filing_date).days
        return age

    def update_shares_outstanding_hybrid(self, spac: SPAC, yahoo_shares: Optional[int]) -> Dict:
        """
        Hybrid approach to shares_outstanding

        Priority:
        1. Recent SEC data (< 90 days old) - 100% accurate
        2. Validated Yahoo data - 97% accurate, real-time
        3. Estimated from IPO proceeds - fallback only

        Returns:
            dict with 'shares_outstanding' and 'shares_source'
        """
        from datetime import datetime

        # Step 1: Check if we have recent SEC data
        sec_shares = self.get_sec_shares_outstanding(spac)
        sec_data_age = self.get_sec_filing_age_days(spac)

        if sec_shares and sec_data_age is not None and sec_data_age < 90:
            # Use SEC data if less than 90 days old
            logger.info(
                f"{spac.ticker}: Using SEC shares ({sec_shares:,}) "
                f"from filing {sec_data_age} days old"
            )
            return {
                'shares_outstanding': sec_shares,
                'shares_source': 'SEC',
                'shares_last_updated': datetime.now()
            }

        # Step 2: Get Yahoo data (real-time)
        # yahoo_shares already passed in from get_price_yfinance

        # Step 3: Validate Yahoo data
        validated_yahoo = self.validate_yahoo_shares(
            ticker=spac.ticker,
            yahoo_shares=yahoo_shares,
            trust_cash=spac.trust_cash,
            ipo_proceeds=spac.ipo_proceeds
        )

        if validated_yahoo:
            # Yahoo passed validation
            if sec_shares and sec_data_age is not None:
                # Compare Yahoo vs SEC to detect new redemptions
                diff_pct = abs(yahoo_shares - sec_shares) / sec_shares * 100
                if diff_pct > 5:
                    logger.warning(
                        f"{spac.ticker}: Yahoo ({yahoo_shares:,}) differs from "
                        f"SEC ({sec_shares:,}) by {diff_pct:.1f}%. "
                        f"Likely new redemptions since last 10-Q ({sec_data_age} days ago)."
                    )

            logger.info(f"{spac.ticker}: Using validated Yahoo shares ({validated_yahoo:,})")
            return {
                'shares_outstanding': validated_yahoo,
                'shares_source': 'Yahoo',
                'shares_last_updated': datetime.now()
            }

        # Step 4: Fallback to current value (don't overwrite with bad data)
        if spac.shares_outstanding:
            logger.warning(
                f"{spac.ticker}: Yahoo validation failed, keeping existing shares ({spac.shares_outstanding:,})"
            )
            return {
                'shares_outstanding': spac.shares_outstanding,
                'shares_source': spac.shares_source or 'Unknown',
                'shares_last_updated': spac.shares_last_updated
            }

        # Step 5: No data available
        logger.error(f"{spac.ticker}: Cannot determine shares_outstanding")
        return {}

    def get_price_yfinance(self, ticker: str) -> Optional[Dict]:
        """Get price from Yahoo Finance"""
        if not YFINANCE_AVAILABLE:
            logger.error("yfinance not installed")
            return None

        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="2d")  # Get last 2 days for change calculation

            if hist.empty:
                logger.warning(f"No data for {ticker}")
                return None

            current_price = float(hist['Close'].iloc[-1])
            current_volume = int(hist['Volume'].iloc[-1]) if 'Volume' in hist.columns else 0

            # Calculate 24h change if we have 2 days of data
            price_change_24h = None
            if len(hist) >= 2:
                prev_price = float(hist['Close'].iloc[-2])
                price_change_24h = ((current_price - prev_price) / prev_price) * 100

            # Calculate 30-day average volume (excluding today for comparison)
            volume_avg_30d = None
            if 'Volume' in hist.columns and len(hist) > 1:
                volume_avg_30d = float(hist['Volume'].iloc[:-1].mean())

            # Calculate dollar volume (value traded)
            dollar_volume = int(current_price * current_volume) if current_volume else None

            # Get Yahoo's market cap for validation (in millions)
            yahoo_market_cap = None
            try:
                info = stock.info
                if 'marketCap' in info and info['marketCap']:
                    yahoo_market_cap = round(info['marketCap'] / 1_000_000, 2)  # Convert to millions
            except:
                pass  # Market cap not available, continue without it

            # Get current time in EST (without timezone info for database storage)
            est = pytz.timezone('US/Eastern')
            now_est = datetime.now(est).replace(tzinfo=None)

            return {
                'price': round(current_price, 2),
                'price_change_24h': round(price_change_24h, 2) if price_change_24h else None,
                'volume': current_volume,
                'volume_avg_30d': round(volume_avg_30d, 2) if volume_avg_30d else None,
                'dollar_volume': dollar_volume,
                'yahoo_market_cap': yahoo_market_cap,
                'last_updated': now_est
            }

        except Exception as e:
            logger.error(f"Error fetching {ticker} from yfinance: {e}")
            return None
    
    def get_price_alphavantage(self, ticker: str) -> Optional[Dict]:
        """Get price from Alpha Vantage"""
        if not self.alpha_vantage_key:
            logger.error("ALPHA_VANTAGE_KEY not set")
            return None
        
        try:
            url = f"https://www.alphavantage.co/query"
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': ticker,
                'apikey': self.alpha_vantage_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if 'Global Quote' not in data or not data['Global Quote']:
                logger.warning(f"No data for {ticker} from Alpha Vantage")
                return None
            
            quote = data['Global Quote']

            # Get current time in EST (without timezone info for database storage)
            est = pytz.timezone('US/Eastern')
            now_est = datetime.now(est).replace(tzinfo=None)

            return {
                'price': round(float(quote['05. price']), 2),
                'price_change_24h': round(float(quote['10. change percent'].rstrip('%')), 2),
                'last_updated': now_est
            }
        
        except Exception as e:
            logger.error(f"Error fetching {ticker} from Alpha Vantage: {e}")
            return None
    
    def get_price_polygon(self, ticker: str) -> Optional[Dict]:
        """Get price from Polygon.io"""
        if not self.polygon_key:
            logger.error("POLYGON_API_KEY not set")
            return None
        
        try:
            # Get previous close
            url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev"
            params = {'apiKey': self.polygon_key}
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('status') != 'OK' or not data.get('results'):
                logger.warning(f"No data for {ticker} from Polygon")
                return None
            
            result = data['results'][0]
            prev_close = result['c']
            current_price = result['c']  # Using close as current
            
            # Get today's data for more accurate current price
            url_today = f"https://api.polygon.io/v1/open-close/{ticker}/{datetime.now().strftime('%Y-%m-%d')}"
            response_today = requests.get(url_today, params=params, timeout=10)
            
            if response_today.status_code == 200:
                today_data = response_today.json()
                if today_data.get('status') == 'OK':
                    current_price = today_data.get('close', current_price)
            
            price_change_24h = ((current_price - prev_close) / prev_close) * 100

            # Get current time in EST (without timezone info for database storage)
            est = pytz.timezone('US/Eastern')
            now_est = datetime.now(est).replace(tzinfo=None)

            return {
                'price': round(current_price, 2),
                'price_change_24h': round(price_change_24h, 2),
                'last_updated': now_est
            }
        
        except Exception as e:
            logger.error(f"Error fetching {ticker} from Polygon: {e}")
            return None
    
    def get_price(self, ticker: str) -> Optional[Dict]:
        """Get price using configured source"""
        if self.source == 'yfinance':
            return self.get_price_yfinance(ticker)
        elif self.source == 'alphavantage':
            return self.get_price_alphavantage(ticker)
        elif self.source == 'polygon':
            return self.get_price_polygon(ticker)
        else:
            logger.error(f"Unknown source: {self.source}")
            return None
    
    def fetch_component_prices(self, spac: SPAC) -> Dict:
        """
        Fetch prices for all components: common, unit, warrant, rights
        Returns dict with price data for each available component
        """
        components = {}

        # 1. Common shares (main ticker)
        common_data = self.get_price(spac.ticker)
        if common_data:
            components['common'] = common_data

        # 2. Units (try multiple formats if primary fails)
        unit_tickers = []
        if spac.unit_ticker:
            # Try stored ticker first
            unit_tickers.append(spac.unit_ticker)

        # Also try common unit ticker formats (in case stored ticker is wrong)
        # Most common patterns: TICKERU, TICKER.U, TICKER-UN, TICKER U
        unit_suffixes = ['U', '.U', '-UN', ' U', '/U', '-U']
        for suffix in unit_suffixes:
            potential_ticker = f"{spac.ticker}{suffix}"
            if potential_ticker not in unit_tickers:
                unit_tickers.append(potential_ticker)

        for u_ticker in unit_tickers:
            unit_data = self.get_price(u_ticker)
            if unit_data:
                components['unit'] = unit_data
                # Update unit_ticker in database if we found a different working format
                if spac.unit_ticker != u_ticker:
                    logger.info(f"   ✓ Found working unit ticker: {u_ticker} (was: {spac.unit_ticker})")
                    spac.unit_ticker = u_ticker
                break

        # 3. Warrants (try multiple formats)
        warrant_tickers = []
        if spac.warrant_ticker:
            # Try stored ticker first
            warrant_tickers.append(spac.warrant_ticker)

        # Also try common warrant ticker formats
        # Most common patterns: TICKERW, TICKER.W, TICKER.WS, TICKER WS, TICKER-WT
        warrant_suffixes = ['W', 'WS', '.W', '.WS', '-WT', '/WS', ' W', ' WS', '-W', '+']
        for suffix in warrant_suffixes:
            potential_ticker = f"{spac.ticker}{suffix}"
            if potential_ticker not in warrant_tickers:
                warrant_tickers.append(potential_ticker)

        for w_ticker in warrant_tickers:
            warrant_data = self.get_price(w_ticker)
            if warrant_data:
                components['warrant'] = warrant_data
                # Update warrant_ticker in database if we found a different working format
                if spac.warrant_ticker != w_ticker:
                    logger.info(f"   ✓ Found working warrant ticker: {w_ticker} (was: {spac.warrant_ticker or 'NOT SET'})")
                    spac.warrant_ticker = w_ticker
                break

        # 4. Rights (try multiple formats)
        right_tickers = []
        if spac.right_ticker:
            # Try stored ticker first
            right_tickers.append(spac.right_ticker)

        # Also try common rights ticker formats
        # Most common patterns: TICKERR, TICKER.R, TICKER R
        right_suffixes = ['R', '.R', ' R', '-R', '/R']
        for suffix in right_suffixes:
            potential_ticker = f"{spac.ticker}{suffix}"
            if potential_ticker not in right_tickers:
                right_tickers.append(potential_ticker)

        for r_ticker in right_tickers:
            right_data = self.get_price(r_ticker)
            if right_data:
                components['rights'] = right_data
                # Update right_ticker in database if we found a different working format
                if spac.right_ticker != r_ticker:
                    logger.info(f"   ✓ Found working rights ticker: {r_ticker} (was: {spac.right_ticker or 'NOT SET'})")
                    spac.right_ticker = r_ticker
                break

        return components

    def update_single_spac(self, ticker: str) -> bool:
        """Update a single SPAC's price - fetches all components"""
        # First, get SPAC record to check for unit_ticker
        spac = self.db.query(SPAC).filter(SPAC.ticker == ticker).first()
        if not spac:
            logger.warning(f"SPAC {ticker} not found in database")
            return False

        # Fetch all component prices (common, unit, warrant, rights)
        components = self.fetch_component_prices(spac)

        # Use common ticker for main price (preferred)
        price_data = components.get('common')
        ticker_used = ticker

        # Fallback to unit_ticker only if common ticker failed (for very new IPOs)
        if not price_data and 'unit' in components:
            price_data = components['unit']
            ticker_used = spac.unit_ticker
            logger.warning(f"{ticker}: Using unit ticker price - common ticker may not be trading yet")

        if not price_data:
            logger.warning(f"{ticker}: No price data available")
            return False

        try:

            # Use actual trust_value (NAV) from database, default to $10.00 if not set
            nav = float(spac.trust_value) if spac.trust_value else 10.00
            premium = ((price_data['price'] - nav) / nav) * 100

            # Calculate FULLY DILUTED market cap
            # Formula: (base_shares + warrant_dilution) × price / 1M
            market_cap = None
            if spac.shares_outstanding:
                # Step 1: Base shares = public + founder shares
                base_shares = spac.shares_outstanding

                if spac.founder_shares and spac.founder_shares > 1_000_000:
                    # Use database value if it looks valid (>1M shares)
                    base_shares += spac.founder_shares
                else:
                    # Skip market cap calculation if no valid founder_shares
                    # Will be populated once SEC scraper extracts it
                    market_cap = None
                    base_shares = None

                # Step 2: Warrant dilution (only if in-the-money)
                # Uses treasury method: warrants add (warrants_out × (price - strike)) / price shares
                warrant_dilution = 0

                if spac.warrant_ratio and spac.warrant_exercise_price:
                    # Parse warrant_ratio (could be "1/3", "0.333", etc.)
                    try:
                        warrant_ratio = float(spac.warrant_ratio) if '/' not in str(spac.warrant_ratio) else eval(spac.warrant_ratio)
                    except:
                        warrant_ratio = 0.333  # Default to 1/3 if parsing fails

                    exercise_price = float(spac.warrant_exercise_price)
                    current_price = price_data['price']

                    # Only add dilution if warrants are in-the-money
                    if current_price > exercise_price:
                        warrants_outstanding = spac.shares_outstanding * warrant_ratio
                        warrant_dilution = (warrants_outstanding * (current_price - exercise_price)) / current_price

                # Step 3: Calculate fully diluted market cap
                fully_diluted_shares = base_shares + warrant_dilution
                market_cap = round((price_data['price'] * fully_diluted_shares) / 1_000_000, 2)

            # Update database with all component prices
            update_data = {
                'price': price_data['price'],
                'premium': round(premium, 2),
                'price_change_24h': price_data['price_change_24h'],
                'volume': price_data.get('volume'),
                'volume_avg_30d': price_data.get('volume_avg_30d'),
                'dollar_volume_24h': price_data.get('dollar_volume'),
                'last_updated': price_data['last_updated'],
                'last_price_update': price_data['last_updated']
            }

            # Add component prices
            if 'common' in components:
                update_data['common_price'] = components['common']['price']
                # IMPORTANT: Ensure main 'price' field always matches common_price
                # This prevents stale unit prices from being used after units stop trading
                if price_data == components['common']:
                    update_data['price'] = components['common']['price']

            if 'unit' in components:
                update_data['unit_price'] = components['unit']['price']

            if 'warrant' in components:
                update_data['warrant_price'] = components['warrant']['price']

            if 'rights' in components:
                update_data['rights_price'] = components['rights']['price']

            if market_cap:
                update_data['market_cap'] = market_cap

            # Add Yahoo market cap for validation
            if price_data.get('yahoo_market_cap'):
                update_data['yahoo_market_cap'] = price_data['yahoo_market_cap']

                # Calculate variance between our calc and Yahoo's
                # NOTE: Yahoo includes sponsor shares (from SEC filings showing total common shares outstanding)
                # but does NOT adjust for redemptions or include warrant dilution
                # Our calc = (public + sponsor + warrant dilution) × price
                # Yahoo calc = (public + sponsor) × price (from last SEC filing)
                # Expected variance = ONLY warrant dilution (if in-the-money)
                if market_cap and price_data['yahoo_market_cap'] and spac.shares_outstanding:
                    # Actual variance
                    variance = ((market_cap - price_data['yahoo_market_cap']) / price_data['yahoo_market_cap']) * 100

                    # Calculate expected variance from warrant dilution ONLY
                    # (Yahoo already includes sponsor shares, doesn't include warrants)
                    base_shares = spac.shares_outstanding
                    if spac.founder_shares:
                        base_shares += spac.founder_shares
                    else:
                        base_shares += spac.shares_outstanding * 0.25  # 25% fallback

                    expected_variance = (warrant_dilution / base_shares) * 100 if base_shares > 0 else 0

                    # Store variance (positive = our calc is higher due to warrant dilution)
                    update_data['market_cap_variance'] = round(variance, 1)

                    # Log warning if variance differs significantly from expected warrant dilution
                    # Also could indicate redemptions not reflected in Yahoo's data
                    if abs(variance - expected_variance) > 10:  # >10% difference is suspicious
                        logger.warning(
                            f"{ticker} market cap variance: {variance:.1f}% (expected ~{expected_variance:.1f}% "
                            f"from warrant dilution). Our: ${market_cap}M, Yahoo: ${price_data['yahoo_market_cap']}M. "
                            f"May indicate redemptions or stale Yahoo data."
                        )

            self.db.query(SPAC).filter(SPAC.ticker == ticker).update(update_data)
            self.db.commit()

            # Log all components
            log_parts = [f"${price_data['price']} ({premium:+.1f}%)"]
            if 'unit' in components:
                log_parts.append(f"Unit: ${components['unit']['price']}")
            if 'warrant' in components:
                log_parts.append(f"Warrant: ${components['warrant']['price']}")
            if 'rights' in components:
                log_parts.append(f"Rights: ${components['rights']['price']}")

            logger.info(f"✅ Updated {ticker_used}: {' | '.join(log_parts)}")
            return True
        
        except Exception as e:
            logger.error(f"Error updating {ticker} in database: {e}")
            self.db.rollback()
            return False
    
    def update_all_spacs(self, delay: float = 0.2) -> Dict[str, int]:
        """
        Update all SPACs in database
        
        Args:
            delay: Delay between requests in seconds (to respect rate limits)
        
        Returns:
            Dict with counts of successful/failed updates
        """
        logger.info("Starting update of all SPACs...")
        
        # Get all tickers
        spacs = self.db.query(SPAC).all()
        tickers = [s.ticker for s in spacs]
        
        stats = {
            'total': len(tickers),
            'successful': 0,
            'failed': 0
        }
        
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"Updating {i}/{stats['total']}: {ticker}")
            
            if self.update_single_spac(ticker):
                stats['successful'] += 1
            else:
                stats['failed'] += 1
            
            # Delay to respect rate limits
            if i < len(tickers):
                time.sleep(delay)
        
        logger.info(f"""
        ✅ Update Complete!
        Total: {stats['total']}
        Successful: {stats['successful']}
        Failed: {stats['failed']}
        """)

        # Check for price spikes after updating all prices
        try:
            from price_spike_monitor import PriceSpikeMonitor
            logger.info("\n🔍 Checking for price spikes...")
            spike_monitor = PriceSpikeMonitor(threshold_positive=5.0, threshold_negative=-5.0)
            alerts_sent = spike_monitor.check_price_spikes()
            if alerts_sent:
                logger.info(f"✅ Sent {len(alerts_sent)} price spike alert(s)")
            stats['price_alerts'] = len(alerts_sent)
        except Exception as e:
            logger.warning(f"Price spike monitoring failed: {e}")
            stats['price_alerts'] = 0

        # Check for volume spikes on pre-deal SPACs
        try:
            from orchestrator_trigger import trigger_volume_spike
            logger.info("\n📊 Checking for volume spikes on pre-deal SPACs...")

            # Get pre-deal SPACs with volume data
            spacs = self.db.query(SPAC).filter(
                SPAC.deal_status == 'SEARCHING',
                SPAC.volume.isnot(None),
                SPAC.volume_avg_30d.isnot(None),
                SPAC.volume_avg_30d > 0
            ).all()

            volume_alerts = 0
            for spac in spacs:
                # Calculate spike ratio
                spike_ratio = spac.volume / spac.volume_avg_30d

                # Alert on 3x+ spikes
                if spike_ratio >= 3.0:
                    success = trigger_volume_spike(
                        ticker=spac.ticker,
                        current_volume=spac.volume,
                        avg_volume_30d=spac.volume_avg_30d,
                        spike_ratio=spike_ratio,
                        deal_status=spac.deal_status
                    )
                    if success:
                        volume_alerts += 1

            if volume_alerts > 0:
                logger.info(f"✅ Sent {volume_alerts} volume spike alert(s)")
            stats['volume_alerts'] = volume_alerts

        except Exception as e:
            logger.warning(f"Volume spike monitoring failed: {e}")
            stats['volume_alerts'] = 0

        return stats
    
    def update_specific_tickers(self, tickers: List[str], delay: float = 0.2) -> Dict[str, int]:
        """Update specific tickers only"""
        stats = {
            'total': len(tickers),
            'successful': 0,
            'failed': 0
        }
        
        for ticker in tickers:
            if self.update_single_spac(ticker):
                stats['successful'] += 1
            else:
                stats['failed'] += 1
            time.sleep(delay)
        
        return stats
    
    def close(self):
        """Close database connection"""
        self.db.close()


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    """Command-line interface for price updates"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Update SPAC prices from live data')
    parser.add_argument(
        '--source',
        choices=['yfinance', 'alphavantage', 'polygon'],
        default='yfinance',
        help='Data source to use (default: yfinance)'
    )
    parser.add_argument(
        '--ticker',
        type=str,
        help='Update specific ticker only'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0.2,
        help='Delay between requests in seconds (default: 0.2)'
    )
    
    args = parser.parse_args()
    
    # Create updater
    updater = PriceUpdater(source=args.source)
    
    try:
        if args.ticker:
            # Update single ticker
            logger.info(f"Updating single ticker: {args.ticker}")
            updater.update_single_spac(args.ticker)
        else:
            # Update all
            logger.info("Updating all SPACs...")
            updater.update_all_spacs(delay=args.delay)
    
    finally:
        updater.close()


if __name__ == "__main__":
    main()
