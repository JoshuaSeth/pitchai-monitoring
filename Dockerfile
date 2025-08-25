FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (including docker CLI for log collection)
RUN apt-get update && apt-get install -y \
    curl \
    docker.io \
    ca-certificates \
    git \
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

# Install Playwright browsers (needed for UI testing)
RUN uv run playwright install --with-deps chromium

# Create necessary directories
RUN mkdir -p logs reports incidents

# Set environment variables for production
ENV MONITORING_ENV=production
ENV DOCKER_HOST=unix:///var/run/docker.sock

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Note: When running this container, mount the Docker socket:
# docker run -v /var/run/docker.sock:/var/run/docker.sock monitoring

# Run the application
CMD ["uv", "run", "python", "main.py"]