#!/usr/bin/env python3
"""
Service Health Monitor - Checks critical services and sends alerts if down

Monitors:
- orchestrator.service
- sec-filing-monitor.service
- price updater (via orchestrator)
- Telegram bot

Sends Telegram alert if any service is down.
"""

import subprocess
import sys
import os
from datetime import datetime

sys.path.append('/home/ubuntu/spac-research')

# Import Telegram from orchestrator
from agent_orchestrator import Orchestrator, AgentTask, TaskPriority, TaskStatus

CRITICAL_SERVICES = [
    'orchestrator.service'  # All monitoring (SEC, Reddit, News, Prices) runs through orchestrator
]

def check_service_status(service_name: str) -> dict:
    """Check if a systemd service is running"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', service_name],
            capture_output=True,
            text=True,
            timeout=5
        )

        is_active = result.stdout.strip() == 'active'

        # Get more details if needed
        if not is_active:
            status_result = subprocess.run(
                ['systemctl', 'status', service_name, '--no-pager', '-n', '5'],
                capture_output=True,
                text=True,
                timeout=5
            )
            details = status_result.stdout
        else:
            details = None

        return {
            'name': service_name,
            'status': 'running' if is_active else 'stopped',
            'is_healthy': is_active,
            'details': details
        }

    except Exception as e:
        return {
            'name': service_name,
            'status': 'error',
            'is_healthy': False,
            'details': str(e)
        }

def send_alert(failed_services: list):
    """Send Telegram alert for failed services"""

    orchestrator = Orchestrator()

    alert_text = f"""🚨 <b>SERVICE HEALTH ALERT</b> 🚨

<b>{len(failed_services)} Critical Service(s) Down</b>

"""

    for service in failed_services:
        alert_text += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>Service:</b> {service['name']}
<b>Status:</b> {service['status']}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

"""
        if service['details']:
            # Truncate details to avoid message length issues
            details = service['details'][:500]
            alert_text += f"<b>Details:</b>\n<code>{details}</code>\n"

    alert_text += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ <b>Action Required:</b> Restart services manually or investigate issue.

<b>To restart:</b>
<code>sudo systemctl restart orchestrator.service</code>
"""

    task = AgentTask(
        task_id=f"service_health_alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        agent_name="telegram",
        task_type="send_alert",
        priority=TaskPriority.CRITICAL,
        status=TaskStatus.PENDING,
        created_at=datetime.now(),
        parameters={'alert_text': alert_text}
    )

    result = orchestrator.agents['telegram'].execute(task)
    return result.status == TaskStatus.COMPLETED

def main():
    print("=" * 80)
    print(f"SERVICE HEALTH CHECK - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    all_healthy = True
    failed_services = []

    for service in CRITICAL_SERVICES:
        status = check_service_status(service)

        symbol = "✅" if status['is_healthy'] else "❌"
        print(f"{symbol} {status['name']}: {status['status']}")

        if not status['is_healthy']:
            all_healthy = False
            failed_services.append(status)

    print("=" * 80)

    if all_healthy:
        print("✅ All services healthy")
        return 0
    else:
        print(f"❌ {len(failed_services)} service(s) failed")
        print("\nSending Telegram alert...")

        if send_alert(failed_services):
            print("✅ Alert sent successfully")
        else:
            print("⚠️  Failed to send alert")

        return 1

if __name__ == "__main__":
    sys.exit(main())
