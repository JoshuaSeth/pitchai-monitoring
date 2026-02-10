FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install Chromium for Playwright/Puppeteer and Node.js for submitted JS tests.
# We do NOT download Playwright browsers; Playwright Python drives system Chromium.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    ca-certificates \
    nodejs \
    npm \
  && rm -rf /var/lib/apt/lists/*

ENV CHROMIUM_PATH=/usr/bin/chromium
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV PUPPETEER_SKIP_DOWNLOAD=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Provide a stable Node module path for developer-submitted Puppeteer tests.
RUN mkdir -p /opt/pitchai-e2e \
  && cd /opt/pitchai-e2e \
  && npm init -y >/dev/null 2>&1 \
  && npm install --no-audit --no-fund puppeteer@23.11.1 \
  && npm cache clean --force

ENV NODE_PATH=/opt/pitchai-e2e/node_modules

COPY domain_checks ./domain_checks
COPY e2e_registry ./e2e_registry
COPY e2e_runner ./e2e_runner
COPY e2e_sandbox ./e2e_sandbox
COPY specs ./specs

CMD ["python", "-m", "domain_checks.main"]
