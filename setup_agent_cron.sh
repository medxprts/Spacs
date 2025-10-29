#!/bin/bash
# Setup cron jobs for AI agent orchestrator

echo "Setting up AI Agent Orchestrator cron jobs..."

# Add to crontab
(crontab -l 2>/dev/null; echo "# SPAC AI Agent Orchestrator") | crontab -

# Run every 2 hours
(crontab -l 2>/dev/null; echo "0 */2 * * * /home/ubuntu/spac-research/venv/bin/python3 /home/ubuntu/spac-research/agent_orchestrator.py >> /home/ubuntu/spac-research/logs/orchestrator.log 2>&1") | crontab -

# Show installed cron jobs
echo ""
echo "Installed cron jobs:"
crontab -l | grep -A 1 "Orchestrator"

echo ""
echo "✓ Agent orchestrator will run every 2 hours"
echo "  Logs: /home/ubuntu/spac-research/logs/orchestrator.log"
echo "  State: /home/ubuntu/spac-research/agent_state.json"
