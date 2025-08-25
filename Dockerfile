FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (minimal set to avoid package conflicts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Install uv - using the official Python method
ADD --chmod=755 https://astral.sh/uv/install.sh /install.sh
RUN /install.sh && rm /install.sh
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files and README (required by pyproject.toml)
COPY pyproject.toml uv.lock README.md ./

# Install dependencies (skip installing the package itself to avoid build issues)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY . .

# Install Playwright browsers (needed for UI testing) - install dependencies first
RUN apt-get update && apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxss1 \
    libasound2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

RUN uv run playwright install chromium

# Install Claude Code CLI (already installed via install.sh)

ENV PATH="/root/.local/bin:$PATH"

# Create necessary directories
RUN mkdir -p logs reports incidents

# Set up cron jobs for Claude monitoring agent
# 5:00 AM CET (4:00 UTC in winter, 3:00 UTC in summer - using 3:00 UTC to cover both)
# 12:15 PM CET (11:15 UTC in winter, 10:15 UTC in summer - using 10:15 UTC to cover both)
RUN echo "0 3 * * * cd /app && /root/.local/bin/uv run python claude_monitoring_agent.py >> /var/log/claude-monitoring-morning.log 2>&1" > /tmp/cron-claude-monitoring
RUN echo "15 10 * * * cd /app && /root/.local/bin/uv run python claude_monitoring_agent.py >> /var/log/claude-monitoring-afternoon.log 2>&1" >> /tmp/cron-claude-monitoring
RUN crontab /tmp/cron-claude-monitoring
RUN rm /tmp/cron-claude-monitoring

# Set environment variables for production
ENV MONITORING_ENV=production
ENV DOCKER_HOST=unix:///var/run/docker.sock
ENV TZ=Europe/Amsterdam
# CLAUDE_CODE_OAUTH_TOKEN will be provided by the deployment environment

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Note: When running this container, mount the Docker socket:
# docker run -v /var/run/docker.sock:/var/run/docker.sock monitoring

# Create startup script to run both cron and the main application
RUN echo '#!/bin/bash' > /start.sh && \
    echo 'set -e' >> /start.sh && \
    echo 'echo "🚀 Starting PitchAI Monitoring System..."' >> /start.sh && \
    echo 'echo "⏰ Cron jobs scheduled: 03:00 UTC (morning), 10:15 UTC (afternoon)"' >> /start.sh && \
    echo 'echo "🔑 Claude CLI token configured: ${CLAUDE_CODE_OAUTH_TOKEN:0:20}..."' >> /start.sh && \
    echo 'cron' >> /start.sh && \
    echo 'echo "✅ Cron daemon started"' >> /start.sh && \
    echo 'echo "🧪 Testing Claude monitoring agent..."' >> /start.sh && \
    echo 'cd /app && timeout 300 uv run python claude_monitoring_agent.py --hours 1 || echo "⚠️ Initial Claude test completed with timeout"' >> /start.sh && \
    echo 'echo "🤖 Starting monitoring web server..."' >> /start.sh && \
    echo 'exec uv run python main.py' >> /start.sh && \
    chmod +x /start.sh

# Run the startup script
CMD ["/start.sh"]