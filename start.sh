#!/bin/bash
# ============================================================
# Dead Lead Follow-Up Automation — Startup Script
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check .env file exists
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found."
    echo "Please copy .env.example to .env and fill in your credentials."
    exit 1
fi

# Create necessary directories
mkdir -p data logs

# Install dependencies if needed
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
fi

PORT="${APP_PORT:-8000}"

echo "============================================================"
echo "  Dead Lead Follow-Up Automation"
echo "  Server starting on port $PORT"
echo "  Scheduler: Monday & Thursday at 8:00 AM EST"
echo "============================================================"
echo ""
echo "  Slack Webhook URL (set this in your Slack App):"
echo "  https://YOUR_DOMAIN_OR_NGROK_URL/slack/interactions"
echo ""
echo "  Manual trigger: POST http://localhost:$PORT/run-now"
echo "  Health check:   GET  http://localhost:$PORT/health"
echo "============================================================"

# Start the FastAPI server
python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --reload \
    --log-level info
