#!/usr/bin/env python3
"""
Orchestrator Trigger Module

Allows external monitors (news, reddit, etc.) to trigger the orchestrator
for accelerated SEC polling and deal processing.

Usage:
    from orchestrator_trigger import trigger_deal_rumor, trigger_confirmed_deal

    # When a deal rumor is detected
    trigger_deal_rumor(ticker="CEP", rumored_target="TechCorp", confidence=85, source="reddit")

    # When a deal is confirmed from news
    trigger_confirmed_deal(ticker="CEP", target="TechCorp", source="news_api", raw_data={...})
"""

import os
import sys
from datetime import datetime, timedelta, date
from typing import Optional, Dict
import logging

sys.path.append('/home/ubuntu/spac-research')
from database import SessionLocal, SPAC, PriceSpikeAlert
from utils.telegram_notifier import send_telegram_alert
from utils.alert_deduplication import should_send_alert, mark_alert_sent

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def trigger_deal_rumor(
    ticker: str,
    rumored_target: str,
    confidence: int,
    source: str,
    raw_data: Optional[Dict] = None
) -> bool:
    """
    Trigger orchestrator when a deal RUMOR is detected (from news/reddit).

    Actions:
    1. Update database with rumor info
    2. Enable accelerated SEC polling for 48 hours
    3. Send Telegram alert (RUMORED status)
    4. Return True if triggered successfully

    Args:
        ticker: SPAC ticker
        rumored_target: Rumored target company name
        confidence: Confidence level 0-100
        source: 'reddit', 'news_api', 'twitter', etc.
        raw_data: Optional dict with additional context
    """
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()

        if not spac:
            logger.warning(f"SPAC {ticker} not found in database")
            return False

        # Check if already announced (don't overwrite confirmed deals)
        if spac.deal_status == 'ANNOUNCED':
            logger.info(f"{ticker} already has confirmed deal, skipping rumor")
            return False

        # Update database
        spac.deal_status_detail = 'RUMORED_DEAL'
        spac.rumored_target = rumored_target
        spac.rumor_confidence = confidence
        spac.rumor_detected_date = datetime.now().date()

        # Enable accelerated polling for 48 hours
        spac.accelerated_polling_until = datetime.now() + timedelta(hours=48)

        db.commit()  # last_updated auto-updates via SQLAlchemy
        logger.info(f"✅ Deal rumor recorded: {ticker} → {rumored_target} ({confidence}% confidence)")

        # Send Telegram alert for RUMORED deals
        if confidence >= 70:
            alert_emoji = "⚠️" if confidence < 85 else "🚨"
            message = f"""{alert_emoji} <b>DEAL RUMOR DETECTED</b> {alert_emoji}

<b>{ticker}</b> - Rumored Deal
<b>Target:</b> {rumored_target}
<b>Confidence:</b> {confidence}%
<b>Source:</b> {source}

📡 <b>Accelerated Monitoring:</b> Enabled for 48 hours
Will poll SEC filings more frequently to catch 8-K filing.

⏰ <b>Detected:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔔 <b>Status:</b> RUMORED (not yet confirmed by SEC filing)
Watch for official 8-K announcement!"""

            # Send alert only once per day per ticker (deduplicate)
            alert_key = f"{ticker}_{rumored_target}"
            if should_send_alert('deal_rumor', ticker=ticker, alert_key=alert_key, dedup_hours=24):
                send_telegram_alert(message)
                mark_alert_sent('deal_rumor', ticker=ticker, alert_key=alert_key, message_preview=message)
                logger.info("📱 Telegram alert sent for deal rumor")
            else:
                logger.info(f"⏭️  Skipped duplicate deal rumor alert for {ticker}")

        return True

    except Exception as e:
        logger.error(f"Error triggering deal rumor: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def trigger_confirmed_deal(
    ticker: str,
    target: str,
    source: str,
    filing_url: Optional[str] = None,
    raw_data: Optional[Dict] = None
) -> bool:
    """
    Trigger orchestrator when a deal is CONFIRMED (from SEC filing or validated news).

    Actions:
    1. Update database with confirmed deal
    2. Send Telegram alert (CONFIRMED status)
    3. Route to agent orchestrator for full processing
    4. Return True if triggered successfully

    Args:
        ticker: SPAC ticker
        target: Confirmed target company name
        source: 'sec_filing', 'news_api', etc.
        filing_url: URL to SEC filing if available
        raw_data: Optional dict with filing/article data
    """
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()

        if not spac:
            logger.warning(f"SPAC {ticker} not found in database")
            return False

        # Check if already announced
        if spac.deal_status == 'ANNOUNCED' and spac.target == target:
            logger.info(f"{ticker} already has confirmed deal with {target}")
            return False

        # Clear rumor status (if any)
        was_rumored = (spac.deal_status_detail == 'RUMORED_DEAL')
        rumor_confirmed = (was_rumored and spac.rumored_target == target)

        # Update database
        spac.deal_status = 'ANNOUNCED'
        spac.deal_status_detail = 'CONFIRMED_DEAL'
        spac.target = target

        if not spac.announced_date:
            spac.announced_date = datetime.now().date()

        if filing_url and not spac.deal_filing_url:
            spac.deal_filing_url = filing_url

        # Clear accelerated polling (deal confirmed, no longer needed)
        spac.accelerated_polling_until = None

        db.commit()  # last_updated auto-updates via SQLAlchemy
        logger.info(f"✅ Confirmed deal recorded: {ticker} → {target}")

        # Send Telegram alert for CONFIRMED deals
        alert_emoji = "🎉" if rumor_confirmed else "🎯"
        rumor_note = "\n\n✅ <b>Rumor Confirmed!</b> Earlier leak was accurate." if rumor_confirmed else ""

        message = f"""{alert_emoji} <b>DEAL CONFIRMED</b> {alert_emoji}

<b>{ticker}</b> - Business Combination
<b>Target:</b> {target}
<b>Source:</b> {source}
{rumor_note}

📅 <b>Announced:</b> {datetime.now().strftime('%Y-%m-%d')}
"""

        if filing_url:
            message += f"\n📄 <b>Filing:</b> {filing_url}"

        message += f"\n\n🤖 Routing to specialist agents for full analysis..."

        # Send alert only once per day per ticker (deduplicate)
        alert_key = f"{ticker}_{target}"
        if should_send_alert('deal_confirmed', ticker=ticker, alert_key=alert_key, dedup_hours=24):
            send_telegram_alert(message)
            mark_alert_sent('deal_confirmed', ticker=ticker, alert_key=alert_key, message_preview=message)
            logger.info("📱 Telegram alert sent for confirmed deal")
        else:
            logger.info(f"⏭️  Skipped duplicate confirmed deal alert for {ticker}")

        # TODO: Route to agent orchestrator for full processing
        # This will trigger deal_detector_agent, s4_processor, etc.
        # orchestrator.process_filing(filing_data)

        return True

    except Exception as e:
        logger.error(f"Error triggering confirmed deal: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def trigger_price_spike(
    ticker: str,
    price: float,
    change_pct: float,
    deal_status: Optional[str] = None,
    volume_spike: bool = False,
    volume_pct_float: Optional[float] = None
) -> bool:
    """
    Trigger orchestrator when a significant price or volume spike is detected.

    Actions:
    1. Send Telegram alert with price/volume movement details
    2. For spikes >10%, enable accelerated SEC polling for 24 hours
    3. Trigger investigation: check news, Reddit, recent filings
    4. Return True if triggered successfully

    Args:
        ticker: SPAC ticker
        price: Current price
        change_pct: Percentage change (positive or negative)
        deal_status: Current deal status ('SEARCHING', 'ANNOUNCED', etc.)
        volume_spike: True if this is a volume spike alert
        volume_pct_float: Percentage of float traded (for volume spikes)
    """
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()

        if not spac:
            logger.warning(f"SPAC {ticker} not found in database")
            return False

        # Check if alert already sent for this ticker today
        today = date.today()
        existing_alert = db.query(PriceSpikeAlert).filter(
            PriceSpikeAlert.ticker == ticker,
            PriceSpikeAlert.alert_date == today
        ).first()

        if existing_alert:
            logger.info(f"⏭️  Skipping alert for {ticker} - already sent today ({existing_alert.change_pct:+.1f}%)")
            return False

        # Determine if spike is significant enough for accelerated polling
        # >10% spikes may indicate material news
        is_major_spike = abs(change_pct) >= 10

        if is_major_spike:
            # Enable accelerated SEC polling for 24 hours
            spac.accelerated_polling_until = datetime.now() + timedelta(hours=24)
            logger.info(f"✅ Enabled 24-hour accelerated polling for {ticker} due to {change_pct:+.1f}% spike")

        db.commit()  # last_updated auto-updates via SQLAlchemy

        # Send investigation alert
        if volume_spike:
            emoji = "📊"
            alert_type = "VOLUME SPIKE"
        else:
            is_spike = change_pct > 0
            emoji = "🚀" if change_pct >= 10 else ("📈" if change_pct > 0 else ("📉" if change_pct <= -10 else "⬇️"))
            alert_type = "PRICE SPIKE"

        message = f"""{emoji} <b>{alert_type} DETECTED - INVESTIGATING</b> {emoji}

<b>{ticker}</b> - {spac.company}
<b>Price:</b> ${price:.2f} ({change_pct:+.2f}%)
<b>Deal Status:</b> {deal_status or 'SEARCHING'}
"""

        if volume_spike and volume_pct_float:
            message += f"<b>Volume:</b> {volume_pct_float:.1f}% of float traded\n"
            if spac.volume:
                message += f"<b>Shares Traded:</b> {spac.volume:,}\n"

        if spac.target:
            message += f"<b>Target:</b> {spac.target}\n"

        if is_major_spike or (volume_spike and volume_pct_float and volume_pct_float >= 10):
            message += f"\n🔍 <b>Auto-Investigation Initiated:</b>\n"
            message += f"• Checking latest SEC filings\n"
            message += f"• Scanning news sources\n"
            message += f"• Monitoring Reddit sentiment\n"
            if is_major_spike:
                message += f"• Accelerated SEC polling enabled for 24 hours\n"
        else:
            if volume_spike:
                message += f"\n💡 <b>Possible causes:</b> Deal news, unusual trading activity, market interest\n"
            else:
                message += f"\n💡 <b>Possible causes:</b> News leak, filing, or market movement\n"

        message += f"\n⏰ <b>Detected:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Send alert only once per day per ticker (deduplicate)
        if should_send_alert('price_spike', ticker=ticker, dedup_hours=24):
            send_telegram_alert(message)
            mark_alert_sent('price_spike', ticker=ticker, message_preview=message)
            logger.info(f"📱 Telegram alert sent for {ticker} price spike ({change_pct:+.1f}%)")
        else:
            logger.info(f"⏭️  Skipped duplicate price spike alert for {ticker}")

        # Record alert in price_spike_alerts table (for historical tracking)
        alert_record = PriceSpikeAlert(
            ticker=ticker,
            alert_date=today,
            price=price,
            change_pct=change_pct
        )
        db.add(alert_record)
        db.commit()
        logger.info(f"✅ Recorded alert for {ticker} in database")

        # Investigation happens automatically via:
        # 1. Accelerated SEC polling (every 5 min for 24 hours if spike >10%)
        # 2. SEC filing monitor processes any new filings immediately
        # 3. Deal detector, redemption extractor, etc. analyze findings
        # 4. Telegram alert sent with results (deal announcement, extension, etc.)
        #
        # No additional investigation trigger needed - the orchestrator's
        # continuous monitoring handles this automatically.

        return True

    except Exception as e:
        logger.error(f"Error triggering price spike investigation: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def trigger_volume_spike(
    ticker: str,
    current_volume: int,
    avg_volume_30d: float,
    spike_ratio: float,
    deal_status: Optional[str] = None
) -> bool:
    """
    Trigger orchestrator when unusual volume spike is detected on pre-deal SPAC.

    Actions:
    1. Send Telegram alert with volume spike details
    2. For spikes >5x, enable accelerated SEC polling for 24 hours
    3. Suggest potential deal speculation or leaked information
    4. Return True if triggered successfully

    Args:
        ticker: SPAC ticker
        current_volume: Today's volume
        avg_volume_30d: 30-day average volume
        spike_ratio: Current volume / 30-day average (e.g., 5.2 = 5.2x)
        deal_status: Current deal status ('SEARCHING', 'ANNOUNCED', etc.)
    """
    db = SessionLocal()
    try:
        spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()

        if not spac:
            logger.warning(f"SPAC {ticker} not found in database")
            return False

        # Only alert on pre-deal SPACs (volume spikes on announced deals are normal)
        if deal_status != 'SEARCHING':
            logger.info(f"⏭️  Skipping volume alert for {ticker} - not searching (status: {deal_status})")
            return False

        # Check if alert already sent for this ticker today
        alert_key = f"volume_spike_{ticker}"
        if not should_send_alert('volume_spike', ticker=ticker, dedup_hours=24):
            logger.info(f"⏭️  Skipping volume spike alert for {ticker} - already sent today")
            return False

        # Determine spike severity
        if spike_ratio >= 10:
            severity = "EXTREME"
            emoji = "🔥"
        elif spike_ratio >= 5:
            severity = "HIGH"
            emoji = "📊"
            # Enable accelerated SEC polling for 24 hours (might be deal leak)
            spac.accelerated_polling_until = datetime.now() + timedelta(hours=24)
            logger.info(f"✅ Enabled 24-hour accelerated polling for {ticker} due to {spike_ratio:.1f}x volume spike")
        elif spike_ratio >= 3:
            severity = "MODERATE"
            emoji = "📈"
        else:
            # Don't alert on <3x spikes
            return False

        db.commit()  # last_updated auto-updates via SQLAlchemy

        # Build alert message
        message = f"""{emoji} <b>VOLUME SPIKE - {severity}</b> {emoji}

<b>{ticker}</b> - {spac.company}
<b>Volume Today:</b> {current_volume:,} ({spike_ratio:.1f}x average)
<b>30-Day Avg:</b> {avg_volume_30d:,.0f}
<b>Deal Status:</b> {deal_status or 'SEARCHING'}
"""

        # Add context
        if spac.ipo_proceeds:
            message += f"<b>IPO Size:</b> {spac.ipo_proceeds}\n"
        if spac.banker:
            message += f"<b>Banker:</b> {spac.banker}\n"
        if spac.sector:
            message += f"<b>Target Sector:</b> {spac.sector}\n"

        # Add investigation recommendations
        message += f"\n🔍 <b>Possible Causes:</b>\n"
        message += f"• Deal rumor or leak\n"
        message += f"• Upcoming announcement\n"
        message += f"• Sector rotation or market movement\n"
        message += f"• Social media speculation\n"

        if spike_ratio >= 5:
            message += f"\n⚡ Accelerated SEC polling enabled for 24 hours\n"

        message += f"\n⏰ <b>Detected:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Send Telegram alert
        send_telegram_alert(message)
        mark_alert_sent('volume_spike', ticker=ticker, message_preview=message)
        logger.info(f"📱 Telegram alert sent for {ticker} volume spike ({spike_ratio:.1f}x)")

        return True

    except Exception as e:
        logger.error(f"Error triggering volume spike alert: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def get_accelerated_polling_tickers() -> list:
    """
    Get list of tickers that need accelerated SEC polling.

    Returns list of tickers where accelerated_polling_until > now
    """
    db = SessionLocal()
    try:
        spacs = db.query(SPAC).filter(
            SPAC.accelerated_polling_until.isnot(None),
            SPAC.accelerated_polling_until > datetime.now()
        ).all()

        return [spac.ticker for spac in spacs]

    finally:
        db.close()


if __name__ == "__main__":
    # Test the trigger
    import argparse

    parser = argparse.ArgumentParser(description='Test orchestrator trigger')
    parser.add_argument('--test-rumor', action='store_true', help='Test rumor trigger')
    parser.add_argument('--test-confirmed', action='store_true', help='Test confirmed trigger')
    parser.add_argument('--ticker', default='CEP', help='Ticker to test with')

    args = parser.parse_args()

    if args.test_rumor:
        print("Testing deal rumor trigger...")
        result = trigger_deal_rumor(
            ticker=args.ticker,
            rumored_target="Test Target Corp",
            confidence=85,
            source="test"
        )
        print(f"Result: {result}")

    elif args.test_confirmed:
        print("Testing confirmed deal trigger...")
        result = trigger_confirmed_deal(
            ticker=args.ticker,
            target="Test Target Corp",
            source="test"
        )
        print(f"Result: {result}")

    else:
        # Show accelerated polling tickers
        tickers = get_accelerated_polling_tickers()
        print(f"Tickers with accelerated polling: {tickers}")
