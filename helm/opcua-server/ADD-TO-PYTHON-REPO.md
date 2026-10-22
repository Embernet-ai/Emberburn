# Files to Add to Small-Application Repository

**Add these 3 files to: https://github.com/fireball-industries/Small-Application**

---

## File 1: Dockerfile (Runtime Git Clone Approach)

**Location:** `Dockerfile` (root of repository)

**Why this approach?**
- No need for `requirements.txt` in repo
- Code pulled fresh at container startup
- Dependencies installed at runtime
- Perfect for rapid development
- Easy to update code without rebuilding image

```dockerfile
FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/fireball-industries/Small-Application"
LABEL org.opencontainers.image.description="EmberBurn Industrial IoT Gateway"
LABEL maintainer="patrick@fireballz.ai"

WORKDIR /app

# Install git and build dependencies
RUN apt-get update && apt-get install -y \
    git \
    gcc g++ \
    libxml2-dev libxslt-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 emberburn && \
    mkdir -p /app/data && \
    chown -R emberburn:emberburn /app

USER emberburn

EXPOSE 4840 5000 8000

ENV PYTHONUNBUFFERED=1 \
    UPDATE_INTERVAL=2.0 \
    LOG_LEVEL=INFO \
    REPO_URL=https://github.com/fireball-industries/Small-Application.git \
    REPO_BRANCH=main

# Entrypoint script that clones code and runs it
COPY --chown=emberburn:emberburn entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

---

## File 1b: entrypoint.sh

**Location:** `entrypoint.sh` (root of repository)

```bash
#!/bin/bash
set -e

echo "🔥 EmberBurn Industrial IoT Gateway Starting..."

# Clone repository if not already present
if [ ! -d "/app/code/.git" ]; then
    echo "📦 Cloning repository from ${REPO_URL}..."
    git clone --depth 1 --branch ${REPO_BRANCH} ${REPO_URL} /app/code
else
    echo "📦 Repository already cloned, pulling latest..."
    cd /app/code && git pull origin ${REPO_BRANCH}
fi

cd /app/code

# Install dependencies
echo "📚 Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip install --no-cache-dir -r requirements.txt
else
    echo "⚠️  No requirements.txt found, installing common packages..."
    pip install --no-cache-dir opcua paho-mqtt influxdb-client prometheus-client
fi

echo "🚀 Starting EmberBurn..."
exec python main.py
```

---

## File 2: .dockerignore

**Location:** `.dockerignore` (root of repository)

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

---

## File 3: .github/workflows/docker-publish.yml

**Location:** `.github/workflows/docker-publish.yml`

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

---

## Comparison: Build-time vs Runtime Approach

| Aspect | Build-time (Traditional) | Runtime (Git Clone) |
|--------|--------------------------|---------------------|
| **Speed** | Fast startup, slow builds | Slow startup (~30s), instant builds |
| **Image Size** | Larger (includes code) | Smaller (only base dependencies) |
| **Code Updates** | Rebuild image required | Just restart pod - pulls latest |
| **Dependencies** | Needs requirements.txt | Auto-installs common packages |
| **Production** | ✅ Recommended | ⚠️ Development only |
| **Security** | ✅ Immutable | ⚠️ Pulls from internet |

**For your use case (rapid development):** Runtime approach is perfect!

---

## How to Add These Files

### Option 1: Via GitHub Web Interface

1. Go to https://github.com/fireball-industries/Small-Application
2. Click "Add file" → "Create new file"
3. Name it `Dockerfile`, paste content from File 1, commit
4. Create `entrypoint.sh`, paste content from File 1b, commit
5. Create `.dockerignore`, paste content from File 2, commit
6. For workflow: Create `.github/workflows/docker-publish.yml`, paste content from File 3, commit

### Option 2: Via Git Command Line

```bash
cd /path/to/Small-Application

# Create Dockerfile
cat > Dockerfile << 'EOF'
[paste File 1 content]
EOF

# Create entrypoint script
cat > entrypoint.sh << 'EOF'
[paste File 1b content]
EOF

# Create .dockerignore
cat > .dockerignore << 'EOF'
[paste File 2 content]
EOF

# Create workflow
mkdir -p .github/workflows
cat > .github/workflows/docker-publish.yml << 'EOF'
[paste File 3 content]
EOF

# Commit and push
git add Dockerfile entrypoint.sh .dockerignore .github/
git commit -m "Add Docker runtime build for EmberBurn"
git push
```

### Option 3: Copy-Paste to Local Files

1. Clone the repo locally
2. Create each file with the content above
3. Commit and push

---

## What Happens Next

Once you push these files to GitHub:

1. **GitHub Actions automatically triggers** (within seconds)
2. **Builds lightweight base image** (~1 minute - no code, just dependencies)
3. **Pushes to GitHub Container Registry**: `ghcr.io/fireball-industries/emberburn:latest`
4. **When pod starts**: Pulls code from GitHub, installs packages, runs main.py

## Verify the Build

Check GitHub Actions:
- Go to: https://github.com/fireball-industries/Small-Application/actions
- You should see "Build EmberBurn Docker Image" workflow running
- Wait for green checkmark ✅

Check the image:
- Go to: https://github.com/orgs/fireball-industries/packages
- You should see `emberburn` package
- Make it **public** so Kubernetes can pull without credentials

## Deploy from Rancher

Once the image is built:

```bash
# Option 1: Via Rancher UI
Rancher → Apps → Charts → EmberBurn → Install

# Option 2: Via Helm CLI
helm install emberburn ./charts/emberburn \
  --namespace emberburn \
  --create-namespace
```

## Customize Git Repository (Optional)

To pull from a different branch or private repo:

```yaml
# In Helm values.yaml or Rancher UI
env:
  - name: REPO_URL
    value: "https://github.com/your-org/your-repo.git"
  - name: REPO_BRANCH
    value: "develop"
```

For private repos, add GitHub token:

```yaml
env:
  - name: REPO_URL
    value: "https://YOUR_TOKEN@github.com/fireball-industries/Small-Application.git"
```

---

**Fireball Industries - We Play With Fire So You Don't Have To™**

