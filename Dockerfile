FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/fireball-industries/Small-Application"
LABEL org.opencontainers.image.description="EmberBurn Industrial IoT Gateway"
LABEL maintainer="patrick@fireball-industries.com"

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc g++ \
    libxml2-dev libxslt-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite and logs
RUN mkdir -p /app/data && \
    chmod 755 /app/data

# Create non-root user
RUN useradd -m -u 1000 emberburn && \
    chown -R emberburn:emberburn /app

# Switch to non-root user
USER emberburn

EXPOSE 4840 5000 8000

ENV PYTHONUNBUFFERED=1 \
    UPDATE_INTERVAL=2.0 \
    LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import socket; s=socket.socket(); s.connect(('localhost', 4840)); s.close()" || exit 1

# Run the OPC UA server with default config
CMD ["python", "opcua_server.py", "-c", "config/config_web_ui.json"]
