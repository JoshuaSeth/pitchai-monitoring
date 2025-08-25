#!/bin/bash
# Production deployment script for PitchAI Monitoring System

set -e

echo "🤖 Deploying PitchAI Monitoring System to Production"
echo "=================================================="

# Check if environment variables are set
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "⚠️  Warning: TELEGRAM_BOT_TOKEN not set. Telegram notifications will be disabled."
fi

if [ -z "$TELEGRAM_CHAT_ID" ]; then
    echo "⚠️  Warning: TELEGRAM_CHAT_ID not set. Telegram notifications will be disabled."
fi

# Create necessary directories
echo "📁 Creating monitoring directories..."
mkdir -p reports logs incidents

# Stop existing monitoring container if running
echo "🛑 Stopping existing monitoring container..."
docker-compose -f docker-compose.monitoring.yml down || echo "No existing container to stop"

# Build and start the monitoring system
echo "🔨 Building monitoring container..."
docker-compose -f docker-compose.monitoring.yml build

echo "🚀 Starting monitoring system..."
docker-compose -f docker-compose.monitoring.yml up -d

# Wait for health check
echo "🏥 Waiting for health check..."
sleep 10

# Check if container is healthy
if docker-compose -f docker-compose.monitoring.yml ps --services --filter "status=running" | grep -q monitoring; then
    echo "✅ Monitoring system deployed successfully!"
    echo ""
    echo "📊 Access points:"
    echo "   Web API: http://monitoring.pitchai.net:8000"
    echo "   Status:  http://monitoring.pitchai.net:8000/status"
    echo "   Health:  http://monitoring.pitchai.net:8000/api/health"
    echo ""
    echo "⏰ Daily monitoring will run at 06:00 UTC"
    echo "📱 Telegram notifications: $([ -n "$TELEGRAM_BOT_TOKEN" ] && echo "Enabled" || echo "Disabled")"
    echo ""
    echo "🔧 Manual commands:"
    echo "   Run tests:  docker exec pitchai-monitoring uv run python main.py test"
    echo "   Check logs: docker exec pitchai-monitoring uv run python main.py logs 1"
    echo "   AI monitor: docker exec pitchai-monitoring uv run python main.py ai"
    echo ""
    echo "📱 To enable Telegram notifications:"
    echo "   1. Create a Telegram bot with @BotFather"
    echo "   2. Get your chat ID"
    echo "   3. Set environment variables:"
    echo "      export TELEGRAM_BOT_TOKEN='your_bot_token'"
    echo "      export TELEGRAM_CHAT_ID='your_chat_id'"
    echo "   4. Redeploy: ./deploy-production.sh"
else
    echo "❌ Deployment failed! Check logs:"
    docker-compose -f docker-compose.monitoring.yml logs
    exit 1
fi