#!/usr/bin/env python3
"""
Daily Volume Tracker
Collects and stores daily trading volume and turnover rate for all SPACs
"""

import yfinance as yf
from datetime import datetime, date, timedelta
from database import SessionLocal, SPAC
from sqlalchemy import text
from typing import Optional, List, Dict
import time


class DailyVolumeTracker:
    """Track daily volume and calculate turnover rates"""

    def __init__(self):
        self.db = SessionLocal()

    def __del__(self):
        """Cleanup database connection"""
        if hasattr(self, 'db'):
            self.db.close()

    def get_volume_data(self, ticker: str, trade_date: Optional[date] = None) -> Optional[Dict]:
        """
        Fetch volume and price data for a ticker

        Args:
            ticker: SPAC ticker
            trade_date: Date to fetch (default: yesterday for completed trading day)

        Returns:
            Dict with volume, price data, or None if no data
        """
        if trade_date is None:
            # Default to yesterday (last completed trading day)
            trade_date = date.today() - timedelta(days=1)

        try:
            # Fetch data for the specific date
            stock = yf.Ticker(ticker)

            # Get 2 days of data to ensure we have the target date
            start_date = trade_date - timedelta(days=1)
            end_date = trade_date + timedelta(days=1)

            hist = stock.history(start=start_date.strftime('%Y-%m-%d'),
                                end=end_date.strftime('%Y-%m-%d'))

            if hist.empty or trade_date.strftime('%Y-%m-%d') not in hist.index.strftime('%Y-%m-%d').tolist():
                return None

            # Get the specific date's data
            day_data = hist[hist.index.strftime('%Y-%m-%d') == trade_date.strftime('%Y-%m-%d')].iloc[0]

            return {
                'volume': int(day_data['Volume']) if day_data['Volume'] > 0 else None,
                'price_close': float(day_data['Close']),
                'price_open': float(day_data['Open']),
                'price_high': float(day_data['High']),
                'price_low': float(day_data['Low'])
            }

        except Exception as e:
            print(f"⚠️  {ticker}: Failed to fetch volume data: {e}")
            return None

    def calculate_turnover_rate(self, volume: int, shares_outstanding: int) -> Optional[float]:
        """
        Calculate turnover rate as percentage

        Args:
            volume: Daily trading volume
            shares_outstanding: Total shares outstanding

        Returns:
            Turnover rate as percentage (e.g., 2.5 for 2.5%)
        """
        if not volume or not shares_outstanding or shares_outstanding == 0:
            return None

        return round((volume / shares_outstanding) * 100, 4)

    def record_daily_volume(
        self,
        ticker: str,
        trade_date: date,
        volume: int,
        shares_outstanding: int,
        price_close: float,
        price_open: float = None,
        price_high: float = None,
        price_low: float = None,
        market_cap: float = None
    ):
        """
        Record daily volume to database

        Uses INSERT ... ON CONFLICT to handle duplicates
        """
        turnover_rate = self.calculate_turnover_rate(volume, shares_outstanding)

        try:
            self.db.execute(text("""
                INSERT INTO daily_volume (
                    ticker, trade_date, volume, shares_outstanding, turnover_rate,
                    price_close, price_open, price_high, price_low, market_cap
                ) VALUES (
                    :ticker, :trade_date, :volume, :shares_outstanding, :turnover_rate,
                    :price_close, :price_open, :price_high, :price_low, :market_cap
                )
                ON CONFLICT (ticker, trade_date)
                DO UPDATE SET
                    volume = EXCLUDED.volume,
                    shares_outstanding = EXCLUDED.shares_outstanding,
                    turnover_rate = EXCLUDED.turnover_rate,
                    price_close = EXCLUDED.price_close,
                    price_open = EXCLUDED.price_open,
                    price_high = EXCLUDED.price_high,
                    price_low = EXCLUDED.price_low,
                    market_cap = EXCLUDED.market_cap
            """), {
                'ticker': ticker,
                'trade_date': trade_date,
                'volume': volume,
                'shares_outstanding': shares_outstanding,
                'turnover_rate': turnover_rate,
                'price_close': price_close,
                'price_open': price_open,
                'price_high': price_high,
                'price_low': price_low,
                'market_cap': market_cap
            })
            self.db.commit()
            return True
        except Exception as e:
            print(f"⚠️  {ticker}: Failed to record volume: {e}")
            self.db.rollback()
            return False

    def collect_daily_volumes(self, trade_date: Optional[date] = None, limit: Optional[int] = None):
        """
        Collect volume data for all active SPACs

        Args:
            trade_date: Date to collect (default: yesterday)
            limit: Optional limit for testing
        """
        if trade_date is None:
            trade_date = date.today() - timedelta(days=1)

        print(f"📊 Collecting volume data for {trade_date.strftime('%Y-%m-%d')}")

        # Get all active SPACs
        query = self.db.query(SPAC).filter(
            SPAC.deal_status.in_(['SEARCHING', 'ANNOUNCED', 'RUMORED_DEAL'])
        ).order_by(SPAC.ticker)

        if limit:
            query = query.limit(limit)

        spacs = query.all()

        print(f"Found {len(spacs)} active SPACs")

        success_count = 0
        failed_count = 0
        no_data_count = 0

        for i, spac in enumerate(spacs, 1):
            print(f"[{i}/{len(spacs)}] {spac.ticker}...", end=" ", flush=True)

            # Get volume data from yfinance
            volume_data = self.get_volume_data(spac.ticker, trade_date)

            if volume_data is None or volume_data['volume'] is None:
                print("No data")
                no_data_count += 1
                continue

            # Get shares outstanding from database
            shares_outstanding = spac.shares_outstanding
            if not shares_outstanding:
                print("No shares_outstanding")
                no_data_count += 1
                continue

            # Calculate market cap
            market_cap = volume_data['price_close'] * shares_outstanding if shares_outstanding else None

            # Record to database
            success = self.record_daily_volume(
                ticker=spac.ticker,
                trade_date=trade_date,
                volume=volume_data['volume'],
                shares_outstanding=shares_outstanding,
                price_close=volume_data['price_close'],
                price_open=volume_data['price_open'],
                price_high=volume_data['price_high'],
                price_low=volume_data['price_low'],
                market_cap=market_cap
            )

            if success:
                turnover = self.calculate_turnover_rate(volume_data['volume'], shares_outstanding)
                print(f"✅ Vol: {volume_data['volume']:,} ({turnover:.2f}%)")
                success_count += 1
            else:
                print("❌ Failed")
                failed_count += 1

            # Rate limiting
            time.sleep(0.1)

        print(f"\n✅ Complete: {success_count} recorded, {no_data_count} no data, {failed_count} failed")

    def get_high_turnover_spacs(self, days: int = 1, min_turnover: float = 5.0) -> List[Dict]:
        """
        Find SPACs with unusually high turnover

        Args:
            days: Number of recent days to check
            min_turnover: Minimum turnover rate (%)

        Returns:
            List of high-turnover SPACs
        """
        cutoff_date = date.today() - timedelta(days=days)

        result = self.db.execute(text("""
            SELECT ticker, trade_date, volume, turnover_rate, price_close
            FROM daily_volume
            WHERE trade_date >= :cutoff_date
              AND turnover_rate >= :min_turnover
            ORDER BY turnover_rate DESC
            LIMIT 20
        """), {
            'cutoff_date': cutoff_date,
            'min_turnover': min_turnover
        })

        return [
            {
                'ticker': row.ticker,
                'date': row.trade_date,
                'volume': row.volume,
                'turnover_rate': float(row.turnover_rate),
                'price': float(row.price_close)
            }
            for row in result
        ]

    def get_turnover_history(self, ticker: str, days: int = 30) -> List[Dict]:
        """
        Get turnover history for a SPAC

        Args:
            ticker: SPAC ticker
            days: Number of days to retrieve

        Returns:
            List of daily turnover data
        """
        cutoff_date = date.today() - timedelta(days=days)

        result = self.db.execute(text("""
            SELECT trade_date, volume, shares_outstanding, turnover_rate, price_close
            FROM daily_volume
            WHERE ticker = :ticker
              AND trade_date >= :cutoff_date
            ORDER BY trade_date DESC
        """), {
            'ticker': ticker,
            'cutoff_date': cutoff_date
        })

        return [
            {
                'date': row.trade_date,
                'volume': row.volume,
                'shares_outstanding': row.shares_outstanding,
                'turnover_rate': float(row.turnover_rate) if row.turnover_rate else None,
                'price': float(row.price_close)
            }
            for row in result
        ]


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Track daily SPAC trading volume')
    parser.add_argument('--date', type=str, help='Date to collect (YYYY-MM-DD), default: yesterday')
    parser.add_argument('--limit', type=int, help='Limit number of SPACs (for testing)')
    parser.add_argument('--high-turnover', action='store_true', help='Show high turnover SPACs')
    parser.add_argument('--history', type=str, help='Show turnover history for ticker')
    parser.add_argument('--days', type=int, default=30, help='Number of days for history')

    args = parser.parse_args()

    tracker = DailyVolumeTracker()

    if args.high_turnover:
        # Show high turnover SPACs
        high_turnover = tracker.get_high_turnover_spacs(days=args.days)
        print(f"\n🔥 High Turnover SPACs (Last {args.days} days):\n")
        for item in high_turnover:
            print(f"  {item['ticker']}: {item['turnover_rate']:.2f}% on {item['date']} "
                  f"(Vol: {item['volume']:,}, Price: ${item['price']:.2f})")

    elif args.history:
        # Show turnover history
        history = tracker.get_turnover_history(args.history, args.days)
        print(f"\n📈 Turnover History for {args.history} (Last {args.days} days):\n")
        for item in history:
            turnover_str = f"{item['turnover_rate']:.2f}%" if item['turnover_rate'] else "N/A"
            print(f"  {item['date']}: {turnover_str:>7} (Vol: {item['volume']:>10,}, Price: ${item['price']:.2f})")

    else:
        # Collect daily volumes
        if args.date:
            trade_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        else:
            trade_date = None

        tracker.collect_daily_volumes(trade_date=trade_date, limit=args.limit)


if __name__ == '__main__':
    main()
