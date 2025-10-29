#!/bin/bash

echo "🚀 Deploying Updated Streamlit App..."

# Navigate to project
cd ~/spac-research

# Backup current version
echo "📦 Backing up current version..."
cp streamlit_app.py streamlit_app.py.backup.$(date +%Y%m%d_%H%M%S)

# Download updated version (we'll paste it)
echo "📝 Ready to update streamlit_app.py"
echo "Press Enter when you've pasted the new code..."

# Restart Streamlit service
echo "🔄 Restarting Streamlit service..."
sudo systemctl restart streamlit

# Check status
echo "✅ Checking service status..."
sudo systemctl status streamlit --no-pager -l

# Show logs
echo "📋 Recent logs:"
sudo journalctl -u streamlit -n 20 --no-pager

echo ""
echo "🎉 Deployment complete!"
echo "Access your dashboard at: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8501"
