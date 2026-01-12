FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/fireball-industries/Small-Application"
LABEL org.opencontainers.image.description="EmberBurn Industrial IoT Gateway"
LABEL maintainer="patrick@fireball-industries.com"

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y \
    gcc g++ libxml2-dev libxslt-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data && \
    useradd -m -u 1000 emberburn && \
    chown -R emberburn:emberburn /app

USER emberburn

EXPOSE 4840 5000 8000

ENV PYTHONUNBUFFERED=1 UPDATE_INTERVAL=2.0 LOG_LEVEL=INFO

CMD ["python", "main.py"]
