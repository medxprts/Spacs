#!/usr/bin/env python3
"""
Unified Deal Signal Aggregator
Combines signals from multiple sources (SEC RSS, News API, Twitter, etc.)
Deduplicates, validates with AI, and updates database
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict
import logging
import sys

sys.path.append('/home/ubuntu/spac-research')
from database import SessionLocal, SPAC
from auto_log_data_changes import init_logger, log_data_change
from orchestrator_trigger import trigger_confirmed_deal, trigger_deal_rumor

# AI Setup for validation
try:
    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    if DEEPSEEK_API_KEY:
        AI_CLIENT = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        AI_AVAILABLE = True
    else:
        AI_AVAILABLE = False
        print("⚠️  DEEPSEEK_API_KEY not found - AI validation disabled")
except Exception as e:
    AI_AVAILABLE = False
    print(f"⚠️  AI not available: {e}")

# Telegram notifications (optional)
try:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
except:
    TELEGRAM_ENABLED = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DealSignal:
    """Represents a potential deal announcement signal"""

    def __init__(self, ticker: str, target: str, source: str, raw_data: Dict):
        self.ticker = ticker
        self.target = target
        self.source = source  # 'sec_rss', 'news_api', 'twitter', etc.
        self.raw_data = raw_data
        self.timestamp = datetime.now()
        self.confidence = 0  # 0-100, calculated by AI
        self.validated = False
        self.is_real_deal = False

        # Generate unique ID for deduplication
        self.signal_id = self._generate_id()

    def _generate_id(self) -> str:
        """Generate unique ID based on ticker + target + date"""
        key = f"{self.ticker}_{self.target}_{self.timestamp.date()}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'signal_id': self.signal_id,
            'ticker': self.ticker,
            'target': self.target,
            'source': self.source,
            'confidence': self.confidence,
            'validated': self.validated,
            'is_real_deal': self.is_real_deal,
            'timestamp': self.timestamp.isoformat(),
            'raw_data': self.raw_data
        }


class DealSignalAggregator:
    """Aggregates and validates deal signals from multiple sources"""

    def __init__(self, auto_commit: bool = False):
        self.db = SessionLocal()
        self.signals_cache: Dict[str, List[DealSignal]] = defaultdict(list)
        self.auto_commit = auto_commit
        init_logger()

    def add_signal(self, signal: DealSignal) -> bool:
        """
        Add a new signal to the aggregator
        Returns True if signal is new (not duplicate)
        """
        # Check if we've seen this signal before
        for existing_signal in self.signals_cache[signal.ticker]:
            if existing_signal.signal_id == signal.signal_id:
                logger.info(f"  Duplicate signal ignored: {signal.ticker} from {signal.source}")
                return False

        self.signals_cache[signal.ticker].append(signal)
        logger.info(f"  ✓ New signal: {signal.ticker} from {signal.source}")
        return True

    def validate_signal(self, signal: DealSignal) -> bool:
        """
        Validate signal using AI
        Returns True if validated as real deal
        """
        if not AI_AVAILABLE:
            logger.warning("AI validation not available - accepting signal with low confidence")
            signal.confidence = 50
            signal.validated = True
            signal.is_real_deal = True
            return True

        try:
            # Prepare validation prompt
            text_excerpt = signal.raw_data.get('full_text', '')[:15000]

            prompt = f"""Analyze this potential SPAC deal announcement. Is this a REAL definitive business combination agreement?

SPAC Ticker: {signal.ticker}
Potential Target: {signal.target}
Source: {signal.source}

Text excerpt:
{text_excerpt}

Return JSON only:
{{
  "is_real_deal": true/false,
  "confidence": 0-100,
  "corrected_target": "Full company name" or null,
  "reason": "Brief explanation"
}}

Real deal criteria:
- "definitive agreement" or "merger agreement" (NOT just "in discussions" or "exploring")
- Specific target company named
- NOT just LOI or non-binding term sheet (unless binding LOI)
- NOT proxy vote reminder (unless first announcement)"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=300
            )

            result = response.choices[0].message.content.strip()
            import re
            result = re.sub(r'```json\s*|\s*```', '', result)
            validation = json.loads(result)

            # Update signal with validation results
            signal.validated = True
            signal.is_real_deal = validation.get('is_real_deal', False)
            signal.confidence = validation.get('confidence', 0)

            if validation.get('corrected_target'):
                signal.target = validation['corrected_target']

            logger.info(f"  AI Validation: {'✓ REAL' if signal.is_real_deal else '✗ FALSE'} "
                       f"({signal.confidence}% confidence)")
            logger.info(f"    Reason: {validation.get('reason', 'N/A')}")

            return signal.is_real_deal

        except Exception as e:
            logger.error(f"  AI validation error: {e}")
            signal.validated = False
            return False

    def process_signals(self, ticker: Optional[str] = None) -> List[Dict]:
        """
        Process all pending signals (validate and update database)
        If ticker specified, only process that ticker
        Returns list of confirmed deals
        """
        confirmed_deals = []

        tickers_to_process = [ticker] if ticker else list(self.signals_cache.keys())

        for ticker_key in tickers_to_process:
            signals = self.signals_cache.get(ticker_key, [])

            if not signals:
                continue

            logger.info(f"\n{'='*60}")
            logger.info(f"Processing {len(signals)} signal(s) for {ticker_key}")
            logger.info(f"{'='*60}")

            for signal in signals:
                # Skip if already validated
                if signal.validated:
                    if signal.is_real_deal:
                        confirmed_deals.append(signal.to_dict())
                    continue

                # Validate with AI
                logger.info(f"\n[{signal.source}] {signal.ticker} -> {signal.target}")

                is_valid = self.validate_signal(signal)

                if is_valid:
                    # Update database
                    updated = self._update_database(signal)

                    if updated:
                        confirmed_deals.append(signal.to_dict())

                        # Trigger orchestrator for confirmed deal
                        # Use confidence threshold to differentiate rumors vs confirmed
                        if signal.confidence >= 85 and signal.is_real_deal:
                            # High confidence = confirmed deal
                            trigger_confirmed_deal(
                                ticker=signal.ticker,
                                target=signal.target,
                                source=signal.source,
                                filing_url=signal.raw_data.get('filing_url'),
                                raw_data=signal.raw_data
                            )
                        elif signal.confidence >= 70:
                            # Medium confidence = rumored deal
                            trigger_deal_rumor(
                                ticker=signal.ticker,
                                rumored_target=signal.target,
                                confidence=signal.confidence,
                                source=signal.source,
                                raw_data=signal.raw_data
                            )

                        # Send notification (legacy - orchestrator_trigger now handles this)
                        if TELEGRAM_ENABLED:
                            self._send_telegram_notification(signal)

        return confirmed_deals

    def _update_database(self, signal: DealSignal) -> bool:
        """Update SPAC record with deal information"""
        try:
            spac = self.db.query(SPAC).filter(SPAC.ticker == signal.ticker).first()

            if not spac:
                logger.warning(f"  SPAC {signal.ticker} not found in database")
                return False

            # Check if already marked as announced
            if spac.deal_status == 'ANNOUNCED':
                logger.info(f"  {signal.ticker} already marked as ANNOUNCED")
                return False

            # Update fields
            updated_fields = []

            if spac.deal_status != 'ANNOUNCED':
                spac.deal_status = 'ANNOUNCED'
                updated_fields.append('deal_status')
                log_data_change(
                    signal.ticker, 'deal_status', 'SEARCHING', 'ANNOUNCED',
                    f'Deal detected from {signal.source}', 'deal_signal_aggregator'
                )

            if signal.target and spac.target != signal.target:
                log_data_change(
                    signal.ticker, 'target', spac.target, signal.target,
                    f'Extracted from {signal.source} (confidence: {signal.confidence}%)',
                    'deal_signal_aggregator'
                )
                spac.target = signal.target
                updated_fields.append('target')

            # Set announced date to today if not set
            if not spac.announced_date:
                announced_date = datetime.now().date()
                log_data_change(
                    signal.ticker, 'announced_date', None, announced_date,
                    f'Set to signal detection date from {signal.source}',
                    'deal_signal_aggregator'
                )
                spac.announced_date = announced_date
                updated_fields.append('announced_date')

            # Capture source document URLs
            if signal.raw_data:
                # Deal filing URL (8-K/425)
                if 'filing_url' in signal.raw_data or 'deal_filing_url' in signal.raw_data:
                    filing_url = signal.raw_data.get('filing_url') or signal.raw_data.get('deal_filing_url')
                    if filing_url and not spac.deal_filing_url:
                        spac.deal_filing_url = filing_url
                        updated_fields.append('deal_filing_url')

                # Press release URL
                if 'url' in signal.raw_data and signal.source == 'news_api':
                    if not spac.press_release_url:
                        spac.press_release_url = signal.raw_data.get('url')
                        updated_fields.append('press_release_url')

                # Twitter URL
                if 'tweet_url' in signal.raw_data and signal.source == 'twitter':
                    if not spac.press_release_url:  # Use press_release_url field for tweets too
                        spac.press_release_url = signal.raw_data.get('tweet_url')
                        updated_fields.append('press_release_url')

            # Generate SEC company URL if we have CIK
            if spac.cik and not spac.sec_company_url:
                cik_padded = spac.cik.zfill(10)
                spac.sec_company_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_padded}"
                updated_fields.append('sec_company_url')

            # Commit changes (last_updated auto-updates via SQLAlchemy)
            if self.auto_commit:
                self.db.commit()
                logger.info(f"  ✅ Database updated: {', '.join(updated_fields)}")
                return True
            else:
                logger.info(f"  [DRY RUN] Would update: {', '.join(updated_fields)}")
                self.db.rollback()
                return False

        except Exception as e:
            logger.error(f"  Database update error: {e}")
            self.db.rollback()
            return False

    def _send_telegram_notification(self, signal: DealSignal):
        """Send Telegram notification for new deal"""
        try:
            import requests

            message = f"""🎯 NEW SPAC DEAL DETECTED

Ticker: {signal.ticker}
Target: {signal.target}
Source: {signal.source}
Confidence: {signal.confidence}%

Time: {signal.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
"""

            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown'
            })

            logger.info("  📱 Telegram notification sent")

        except Exception as e:
            logger.error(f"  Telegram notification error: {e}")

    def get_summary(self) -> Dict:
        """Get summary of all signals"""
        total_signals = sum(len(signals) for signals in self.signals_cache.values())
        validated = sum(1 for signals in self.signals_cache.values()
                       for signal in signals if signal.validated)
        real_deals = sum(1 for signals in self.signals_cache.values()
                        for signal in signals if signal.is_real_deal)

        by_source = defaultdict(int)
        for signals in self.signals_cache.values():
            for signal in signals:
                by_source[signal.source] += 1

        return {
            'total_signals': total_signals,
            'validated': validated,
            'real_deals': real_deals,
            'by_source': dict(by_source),
            'tickers': list(self.signals_cache.keys())
        }

    def close(self):
        """Clean up resources"""
        self.db.close()


def main():
    """Test with sample signals"""
    aggregator = DealSignalAggregator(auto_commit=False)

    # Example usage
    print("Deal Signal Aggregator - Test Mode")
    print("="*60)
    print("\nTo use in your scripts:")
    print("""
from deal_signal_aggregator import DealSignalAggregator, DealSignal

aggregator = DealSignalAggregator(auto_commit=True)

# Add signal from any source
signal = DealSignal(
    ticker='CEP',
    target='Example Corp',
    source='sec_rss',
    raw_data={'full_text': '...', 'filing_url': '...'}
)

aggregator.add_signal(signal)
confirmed_deals = aggregator.process_signals()

print(f"Confirmed {len(confirmed_deals)} deals")
aggregator.close()
    """)

    aggregator.close()


if __name__ == "__main__":
    main()
