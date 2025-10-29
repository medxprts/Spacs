#!/bin/bash
# Deploy RSS News Monitor as systemd service

SERVICE_FILE="/etc/systemd/system/spac-rss-monitor.service"
WORKING_DIR="/home/ubuntu/spac-research"
PYTHON_PATH="/home/ubuntu/spac-research/venv/bin/python3"

echo "Creating systemd service for RSS News Monitor..."

# Create service file
sudo tee $SERVICE_FILE > /dev/null <<EOF
[Unit]
Description=SPAC RSS News Monitor - Continuous News Monitoring
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$WORKING_DIR
Environment="PATH=$WORKING_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$PYTHON_PATH $WORKING_DIR/rss_news_monitor.py --interval 15
Restart=always
RestartSec=30
StandardOutput=append:$WORKING_DIR/logs/rss_monitor.log
StandardError=append:$WORKING_DIR/logs/rss_monitor_error.log

# Resource limits
MemoryMax=1G
CPUQuota=50%

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Service file created: $SERVICE_FILE"

# Create logs directory
mkdir -p $WORKING_DIR/logs

# Reload systemd
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable service
echo "Enabling service..."
sudo systemctl enable spac-rss-monitor

echo ""
echo "✅ RSS Monitor service deployed!"
echo ""
echo "Commands:"
echo "  Start:   sudo systemctl start spac-rss-monitor"
echo "  Stop:    sudo systemctl stop spac-rss-monitor"
echo "  Status:  sudo systemctl status spac-rss-monitor"
echo "  Logs:    tail -f $WORKING_DIR/logs/rss_monitor.log"
echo ""
echo "Service will:"
echo "  - Poll RSS feeds every 15 minutes"
echo "  - Detect SPAC deal announcements"
echo "  - Verify with AI"
echo "  - Send Telegram alerts"
echo "  - Auto-restart if it crashes"
echo ""
