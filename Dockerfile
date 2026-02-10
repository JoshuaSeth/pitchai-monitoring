FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install Chromium for Playwright (we do NOT download Playwright browsers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

ENV CHROMIUM_PATH=/usr/bin/chromium

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY domain_checks ./domain_checks
COPY e2e_registry ./e2e_registry
COPY e2e_runner ./e2e_runner
COPY specs ./specs

CMD ["python", "-m", "domain_checks.main"]
