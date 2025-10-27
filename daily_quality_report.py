#!/usr/bin/env python3
"""
Daily Data Quality Report - Sends summary to Telegram
Run via cron: 0 8 * * * python3 daily_quality_report.py
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from data_quality_agent import DataQualityAgent
from database import SessionLocal, SPAC
from utils.telegram_notifier import send_telegram_alert

def send_daily_report():
    """Run audit and send summary to Telegram"""

    print("="*60)
    print("DAILY DATA QUALITY REPORT")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*60 + "\n")

    # Run audit in live mode
    agent = DataQualityAgent(dry_run=False)
    db = SessionLocal()

    try:
        # Detect all issues
        issues = agent.detect_issues()

        # Count by severity
        critical = sum(1 for i in issues if i.severity.value == 'critical')
        high = sum(1 for i in issues if i.severity.value == 'high')
        medium = sum(1 for i in issues if i.severity.value == 'medium')
        low = sum(1 for i in issues if i.severity.value == 'low')

        # Count by type (top 5)
        type_counts = {}
        for issue in issues:
            typ = issue.issue_type.value
            type_counts[typ] = type_counts.get(typ, 0) + 1
        top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Auto-fix safe issues
        fixed_count = 0
        manual_count = 0

        for issue in issues:
            if issue.auto_fixable:
                # Try to fix
                diagnosis = agent._rule_based_diagnosis(issue)
                success = agent.auto_fix(issue, diagnosis)
                if success:
                    fixed_count += 1
                else:
                    manual_count += 1
                    # Only send notification if fix failed
                    agent.notify_human(issue, diagnosis)
            else:
                # Needs manual review - investigate with AI
                diagnosis = agent.investigate(issue)
                if diagnosis.confidence >= 0.8 and diagnosis.fixable:
                    # High-confidence fix
                    success = agent.auto_fix(issue, diagnosis)
                    if success:
                        fixed_count += 1
                    else:
                        manual_count += 1
                        agent.notify_human(issue, diagnosis)
                else:
                    # Send for manual review
                    manual_count += 1
                    agent.notify_human(issue, diagnosis)

        # Send summary to Telegram
        total_spacs = db.query(SPAC).count()

        # Create emoji status
        if len(issues) == 0:
            status_emoji = "✅"
            status_text = "All systems green"
        elif critical > 0:
            status_emoji = "🔴"
            status_text = "Critical issues detected"
        elif high > 5:
            status_emoji = "🟠"
            status_text = "Action required"
        else:
            status_emoji = "🟢"
            status_text = "Minor issues only"

        summary = f"""📊 <b>Daily Data Quality Report</b>
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

{status_emoji} <b>{status_text}</b>

<b>Database Status:</b>
• {total_spacs} SPACs monitored
• {len(issues)} issues detected

<b>By Severity:</b>
• 🔴 Critical: {critical}
• 🟠 High: {high}
• 🟡 Medium: {medium}
• ⚪ Low: {low}

<b>Top Issues:</b>"""

        for typ, count in top_types:
            summary += f"\n• {typ.replace('_', ' ').title()}: {count}"

        summary += f"""

<b>Actions Taken:</b>
• ✅ Auto-fixed: {fixed_count}
• 📝 Manual review needed: {manual_count}

<b>Auto-Fixes Applied:</b>
• Re-scraped SEC filings
• Updated prices from Yahoo Finance
• Recalculated premiums
• Set default trust values

{"⚠️ <b>Manual review notifications sent for complex issues</b>" if manual_count > 0 else "✅ <b>No manual intervention needed</b>"}

<i>Log: /home/ubuntu/spac-research/data_quality_agent.log</i>
"""

        # Send to Telegram (with automatic chunking for long messages)
        print("\n📱 Sending to Telegram...")
        success = send_telegram_alert(summary)

        if success:
            print("✅ Daily report sent to Telegram")
        else:
            print("❌ Failed to send Telegram report")

        # Print to console
        print("\n" + summary.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', ''))

        print("\n" + "="*60)
        print("Report complete!")
        print("="*60)

    finally:
        agent.close()
        db.close()

if __name__ == "__main__":
    send_daily_report()
