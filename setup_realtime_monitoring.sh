#!/bin/bash
# Setup Real-Time Deal Monitoring (Free Tier Optimized)

echo "=========================================="
echo "Real-Time SPAC Deal Monitoring Setup"
echo "=========================================="
echo ""

# Check if already running
if screen -list | grep -q "sec_filing"; then
    echo "⚠️  SEC Filing Monitor already running!"
    echo "   To restart: screen -X -S sec_filing quit"
    echo ""
else
    echo "Starting SEC Filing Monitor (continuous, checks every 15 mins)..."
    screen -dmS sec_filing bash -c "cd /home/ubuntu/spac-research && /home/ubuntu/spac-research/venv/bin/python3 sec_filing_monitor.py --continuous >> logs/sec_filing_continuous.log 2>&1"
    sleep 2

    if screen -list | grep -q "sec_filing"; then
        echo "✅ SEC Filing Monitor started in background (screen session: sec_filing)"
    else
        echo "❌ Failed to start SEC Filing Monitor"
        exit 1
    fi
fi

echo ""
echo "Setting up News API cron job (every 3 hours)..."

# Create cron job
CRON_CMD="0 */3 * * * cd /home/ubuntu/spac-research && /home/ubuntu/spac-research/venv/bin/python3 news_api_monitor.py --commit --max-spacs 60 --days 3 >> logs/news_monitor.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "news_api_monitor.py"; then
    echo "⚠️  News API cron job already exists"
else
    # Add cron job
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "✅ News API cron job added (runs every 3 hours)"
fi

echo ""
echo "=========================================="
echo "Real-Time Monitoring Active!"
echo "=========================================="
echo ""
echo "📊 MONITORING SETUP:"
echo "  • SEC Filing Monitor: Continuous (checks every 15 minutes)"
echo "  • News API: Every 3 hours (60 SPACs each run)"
echo "  • Architecture: SEC RSS → Classifier → Agent Orchestrator → Database"
echo "  • Detection Speed: 15-180 minutes (avg ~95 mins)"
echo ""
echo "📝 LOGS:"
echo "  • SEC Filing Monitor: tail -f logs/sec_filing_continuous.log"
echo "  • News API: tail -f logs/news_monitor.log"
echo ""
echo "🛠️  MANAGEMENT:"
echo "  • View SEC monitor: screen -r sec_filing"
echo "  • Stop SEC monitor: screen -X -S sec_filing quit"
echo "  • View cron jobs: crontab -l"
echo "  • Remove cron: crontab -e (delete the line)"
echo ""
echo "🔍 CHECK STATUS:"
echo "  • SEC Filing Monitor running: screen -list | grep sec_filing"
echo "  • View recent logs: tail -30 logs/sec_filing_continuous.log"
echo "  • Check monitoring status: ./check_monitoring_status.sh"
echo ""
echo "✅ Setup complete! Your system will now detect deals in near real-time."
echo ""
