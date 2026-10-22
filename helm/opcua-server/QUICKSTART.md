# Quick Setup: EmberBurn Docker Container

**Add these files to: https://github.com/fireball-industries/Small-Application**

## 1. Dockerfile

```dockerfile
FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/fireball-industries/Small-Application"
LABEL org.opencontainers.image.description="EmberBurn Industrial IoT Gateway"
LABEL maintainer="patrick@fireballz.ai"

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
```

## 2. .dockerignore

```
__pycache__/
*.pyc
.git
.env
venv/
*.md
!README.md
data/*.db
```

## 3. .github/workflows/docker-publish.yml

```yaml
name: Build EmberBurn Docker Image

on:
  push:
    branches: [main, master]
    tags: ['v*']
  workflow_dispatch:

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: fireball-industries/emberburn

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4
      
      - uses: docker/setup-buildx-action@v3
      
      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=raw,value=latest
            type=sha,prefix={{branch}}-
      
      - uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

## 4. Test Locally

```bash
# Build
docker build -t emberburn:test .

# Run
docker run -p 4840:4840 -p 5000:5000 -p 8000:8000 emberburn:test

# Test endpoints
curl http://localhost:5000       # Web UI
curl http://localhost:8000/metrics  # Prometheus
```

## 5. Push to GitHub

```bash
cd Small-Application
git add Dockerfile .dockerignore .github/
git commit -m "Add Docker build for EmberBurn"
git push
```

GitHub Actions will automatically build and push to `ghcr.io/fireball-industries/emberburn:latest`

## 6. Deploy from Rancher

After the image is built:
1. Go to Rancher → Apps → Charts
2. Search "EmberBurn"
3. Click Install
4. Image will pull from `ghcr.io/fireball-industries/emberburn:latest`
5. Everything flows! 🔥
