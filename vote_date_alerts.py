#!/usr/bin/env python3
"""
Vote Date Alert System - 10 Day Warning

Sends Telegram alerts for shareholder votes happening in 7-10 days.
Tracks alerts to avoid duplicates.
"""

import sys
import os
from datetime import datetime, timedelta
import json

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from telegram_agent import TelegramAgent
from dotenv import load_dotenv

load_dotenv()

STATE_FILE = '/home/ubuntu/spac-research/.vote_alerts_sent.json'


def load_alert_state():
    """Load which votes we've already alerted on"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_alert_state(state):
    """Save alert state to file"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def get_upcoming_votes(days_min=7, days_max=10):
    """Get votes happening in 7-10 days"""
    db = SessionLocal()
    try:
        now = datetime.now().date()
        start_date = now + timedelta(days=days_min)
        end_date = now + timedelta(days=days_max)

        votes = db.query(SPAC).filter(
            SPAC.shareholder_vote_date.isnot(None),
            SPAC.shareholder_vote_date >= start_date,
            SPAC.shareholder_vote_date <= end_date
        ).order_by(SPAC.shareholder_vote_date).all()

        return votes
    finally:
        db.close()


def send_vote_alert(spac, days_until):
    """Send Telegram alert for upcoming vote"""

    agent = TelegramAgent()

    # Convert datetime to date if needed
    vote_date = spac.shareholder_vote_date
    if isinstance(vote_date, datetime):
        vote_date = vote_date.date()

    # Format alert message
    alert_text = f"""🗳️ <b>SHAREHOLDER VOTE ALERT</b>

<b>{spac.ticker}</b> - {spac.company}
Target: {spac.target or 'Unknown'}

📅 <b>Vote Date:</b> {vote_date.strftime('%A, %B %d, %Y')}
⏰ <b>Days Until Vote:</b> {days_until} days

💰 <b>Deal Details:</b>
• Deal Value: {f'${spac.deal_value}M' if spac.deal_value else 'TBD'}
• Premium: {f'{spac.premium:.1f}%' if spac.premium else 'N/A'}
• Current Price: {f'${spac.price:.2f}' if spac.price else 'N/A'}
• Trust Value: {f'${spac.trust_value:.2f}' if spac.trust_value else '$10.00'}

📊 <b>Status:</b>
• Announced: {spac.announced_date.strftime('%Y-%m-%d') if spac.announced_date else 'Unknown'}
• Expected Close: {spac.expected_close or 'TBD'}

⚠️ <b>ACTION REQUIRED:</b>
• Review proxy materials (DEF 14A)
• Decide: Vote YES/NO or Redeem shares
• Redemption deadline typically 2 days before vote

🔗 SEC Filings: https://www.sec.gov/cgi-bin/browse-edgar?CIK={spac.cik}
"""

    try:
        agent.send_message(alert_text, parse_mode='HTML')
        print(f"✅ Alert sent for {spac.ticker} vote on {spac.shareholder_vote_date}")
        return True
    except Exception as e:
        print(f"⚠️  Failed to send alert for {spac.ticker}: {e}")
        return False


def main():
    print("🗳️  VOTE DATE ALERT SYSTEM")
    print("=" * 70)
    print(f"Checking for votes in 7-10 days from {datetime.now().date()}\n")

    # Load alert state
    alert_state = load_alert_state()

    # Get upcoming votes
    upcoming_votes = get_upcoming_votes(days_min=7, days_max=10)

    if not upcoming_votes:
        print("✅ No upcoming votes in the next 7-10 days\n")
        return

    print(f"Found {len(upcoming_votes)} upcoming vote(s):\n")

    alerts_sent = 0

    for spac in upcoming_votes:
        # Convert datetime to date if needed
        vote_date = spac.shareholder_vote_date
        if isinstance(vote_date, datetime):
            vote_date = vote_date.date()

        days_until = (vote_date - datetime.now().date()).days

        # Check if we've already alerted for this vote
        alert_key = f"{spac.ticker}_{vote_date.isoformat()}"

        if alert_key in alert_state:
            print(f"⏭️  {spac.ticker} - Already alerted (vote in {days_until} days)")
            continue

        print(f"📢 {spac.ticker} - {spac.target}")
        print(f"   Vote: {vote_date.strftime('%Y-%m-%d')} ({days_until} days)")

        # Send alert
        if send_vote_alert(spac, days_until):
            # Mark as alerted
            alert_state[alert_key] = {
                'alerted_at': datetime.now().isoformat(),
                'vote_date': vote_date.isoformat(),
                'days_until': days_until
            }
            alerts_sent += 1

        print()

    # Save state
    save_alert_state(alert_state)

    print("=" * 70)
    print(f"📊 SUMMARY")
    print(f"   Upcoming votes: {len(upcoming_votes)}")
    print(f"   Alerts sent: {alerts_sent}")
    print(f"   Already alerted: {len(upcoming_votes) - alerts_sent}")

    # Cleanup old entries (remove votes older than 30 days)
    cleanup_threshold = datetime.now().date() - timedelta(days=30)
    original_count = len(alert_state)

    alert_state = {
        k: v for k, v in alert_state.items()
        if datetime.fromisoformat(v['vote_date']).date() > cleanup_threshold
    }

    if len(alert_state) < original_count:
        save_alert_state(alert_state)
        print(f"   Cleaned up {original_count - len(alert_state)} old alert records")


if __name__ == "__main__":
    main()
