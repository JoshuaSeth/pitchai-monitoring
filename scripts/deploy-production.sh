#!/bin/bash

# Production Deployment Script for PitchAI Monitoring System
# Configures and deploys the monitoring system for monitoring.pitchai.net

set -e

echo "🚀 Starting PitchAI Monitoring System Production Deployment"
echo "========================================================="

# Check if running as root or with Docker permissions
if ! docker ps >/dev/null 2>&1; then
    echo "❌ Error: Docker is not accessible. Please ensure:"
    echo "   1. Docker is installed and running"
    echo "   2. Current user is in the docker group, or run with sudo"
    exit 1
fi

# Set production environment variables
export MONITORING_ENV=production
export LOG_LEVEL=INFO
export BROWSER_HEADLESS=true

echo "✅ Docker accessibility confirmed"

# Create necessary directories with proper permissions
echo "📁 Creating production directories..."
mkdir -p reports logs incidents
chmod 755 reports logs incidents

# Ensure Docker socket has appropriate permissions
echo "🔧 Checking Docker socket permissions..."
if [ -S /var/run/docker.sock ]; then
    echo "✅ Docker socket found"
else
    echo "❌ Docker socket not found at /var/run/docker.sock"
    exit 1
fi

# Build the monitoring image
echo "🏗️  Building monitoring container..."
docker-compose build --no-cache

# Stop any existing monitoring containers
echo "🛑 Stopping existing monitoring containers..."
docker-compose down 2>/dev/null || true

# Start the monitoring system
echo "🚦 Starting monitoring system..."
docker-compose up -d

# Wait for system to be ready
echo "⏳ Waiting for monitoring system to start..."
sleep 10

# Health check
echo "🏥 Performing health check..."
for i in {1..12}; do
    if curl -f http://localhost:8000/ >/dev/null 2>&1; then
        echo "✅ Monitoring system is healthy and responding"
        break
    fi
    if [ $i -eq 12 ]; then
        echo "❌ Health check failed - monitoring system may not be ready"
        docker-compose logs
        exit 1
    fi
    echo "   Attempt $i/12 - waiting..."
    sleep 5
done

# Test Docker integration
echo "🐳 Testing Docker integration..."
if curl -f http://localhost:8000/health/docker >/dev/null 2>&1; then
    echo "✅ Docker integration working"
else
    echo "⚠️  Warning: Docker integration may have issues"
fi

# Display deployment information
echo ""
echo "🎉 Deployment Complete!"
echo "======================"
echo "Monitoring System: http://localhost:8000"
echo "Production URL: https://monitoring.pitchai.net (configure reverse proxy)"
echo "Docker Status: $(docker-compose ps)"
echo ""
echo "📊 Key Endpoints:"
echo "   - Health Check: http://localhost:8000/"
echo "   - System Status: http://localhost:8000/status"
echo "   - Docker Health: http://localhost:8000/health/docker"
echo "   - Latest AI Summary: http://localhost:8000/reports/latest-ai-summary"
echo ""
echo "🕐 AI Agent Schedule:"
echo "   - Daily Tests: 6:00 AM (cron: 0 6 * * *)"
echo "   - Daily Report: 6:30 AM"
echo "   - Log Collection: Every hour"
echo ""
echo "📝 Next Steps:"
echo "   1. Configure reverse proxy to route monitoring.pitchai.net to port 8000"
echo "   2. Set up SSL certificate for monitoring.pitchai.net"
echo "   3. Configure firewall to allow access to port 8000"
echo "   4. Set up log rotation for the reports, logs, and incidents directories"
echo "   5. Configure monitoring system backup"
echo ""
echo "🔍 Monitor logs with: docker-compose logs -f"
echo "🛑 Stop system with: docker-compose down"
echo "📚 View this deployment script: cat scripts/deploy-production.sh"