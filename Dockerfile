FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (including docker CLI for log collection)
RUN apt-get update && apt-get install -y \
    curl \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

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