# ARM64 Deployment Guide 🏗️

**EmberBurn Industrial IoT Gateway - ARM64 Architecture Support**

> *"From Raspberry Pi to AWS Graviton: Your Data Runs Everywhere"*
>
> **Patrick Ryan, Fireball Industries**  
> *"ARM yourself with the best industrial IoT gateway"*

## Overview

EmberBurn now provides **native ARM64/aarch64 support** for running on:

- 🥧 **Raspberry Pi** (4, 5, and newer with 64-bit OS)
- ☁️ **AWS Graviton** instances (EC2, ECS, EKS)
- 🍎 **Apple Silicon** (M1, M2, M3 Macs - for development/testing)
- 🎮 **NVIDIA Jetson** (Nano, Xavier, Orin - edge AI platforms)
- 🚀 **ARM-based servers** (Ampere Altra, Marvell ThunderX)
- 🔧 **Industrial edge computers** with ARM processors

## Multi-Architecture Docker Images

EmberBurn Docker images are built for **both AMD64 and ARM64** architectures automatically:

```bash
# Docker automatically pulls the correct architecture for your platform
docker pull ghcr.io/fireball-industries/emberburn:latest

# Verify the architecture
docker image inspect ghcr.io/fireball-industries/emberburn:latest | grep Architecture
```

**Available Images**:
- `ghcr.io/fireball-industries/emberburn:latest` - Multi-arch manifest (auto-selects platform)
- Platform-specific manifests are automatically resolved by Docker

## Quick Start on ARM64

### Raspberry Pi Deployment

**Prerequisites**:
- Raspberry Pi 4 or 5 (4GB+ RAM recommended)
- 64-bit Raspberry Pi OS (Bookworm or newer)
- Docker installed

**Installation**:

```bash
# Install Docker (if not already installed)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker

# Pull and run EmberBurn
docker run -d \
  --name emberburn \
  --restart unless-stopped \
  -p 4840:4840 \
  -p 5000:5000 \
  -p 8000:8000 \
  -v /opt/emberburn/data:/app/data \
  ghcr.io/fireball-industries/emberburn:latest

# Check logs
docker logs -f emberburn

# Access Web UI
# Open browser to: http://<raspberry-pi-ip>:5000
```

### AWS Graviton (ARM64) Deployment

**EC2 Instance Types**:
- `t4g.*` - Burstable general purpose (cost-effective)
- `c7g.*` - Compute optimized (high performance)
- `m7g.*` - General purpose (balanced)

**ECS/Fargate Deployment**:

```json
{
  "family": "emberburn",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "runtimePlatform": {
    "cpuArchitecture": "ARM64",
    "operatingSystemFamily": "LINUX"
  },
  "containerDefinitions": [
    {
      "name": "emberburn",
      "image": "ghcr.io/fireball-industries/emberburn:latest",
      "cpu": 256,
      "memory": 512,
      "essential": true,
      "portMappings": [
        {"containerPort": 4840, "protocol": "tcp"},
        {"containerPort": 5000, "protocol": "tcp"},
        {"containerPort": 8000, "protocol": "tcp"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/emberburn",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

**EKS Deployment** (ARM64 Node Groups):

```yaml
# Use standard Helm chart - it works on ARM64!
helm install emberburn ./helm/opcua-server \
  --set emberburn.image.repository=ghcr.io/fireball-industries/emberburn \
  --set emberburn.image.tag=latest \
  --set emberburn.resources.preset=small \
  --set nodeSelector."kubernetes\.io/arch"=arm64
```

### Docker Compose (ARM64)

```yaml
version: '3.8'

services:
  emberburn:
    image: ghcr.io/fireball-industries/emberburn:latest
    container_name: emberburn
    restart: unless-stopped
    ports:
      - "4840:4840"  # OPC UA
      - "5000:5000"  # Web UI
      - "8000:8000"  # Prometheus
    environment:
      - UPDATE_INTERVAL=2.0
      - LOG_LEVEL=INFO
    volumes:
      - ./data:/app/data
    # Optional: Force ARM64 (usually auto-detected)
    platform: linux/arm64
```

## Kubernetes Deployment (ARM64)

### K3s on Raspberry Pi Cluster

**Install K3s**:

```bash
# On master node
curl -sfL https://get.k3s.io | sh -

# Get node token
sudo cat /var/lib/rancher/k3s/server/node-token

# On worker nodes
curl -sfL https://get.k3s.io | K3S_URL=https://<master-ip>:6443 \
  K3S_TOKEN=<node-token> sh -
```

**Deploy EmberBurn**:

```bash
# Deploy via Helm
helm install emberburn ./helm/opcua-server \
  --set emberburn.resources.preset=small \
  --namespace emberburn \
  --create-namespace

# Verify deployment
kubectl get pods -n emberburn

# Access via NodePort
kubectl get svc -n emberburn
```

### Node Affinity for ARM64

If you have a mixed-architecture cluster, pin EmberBurn to ARM64 nodes:

```yaml
# values.yaml
nodeSelector:
  kubernetes.io/arch: arm64

# Or use affinity for more control
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/arch
          operator: In
          values:
          - arm64
```

## Building Custom ARM64 Images

### Cross-Platform Build from x86

```bash
# Enable multi-arch support
docker run --privileged --rm tonistiigi/binfmt --install all

# Build for ARM64 only
docker buildx build --platform linux/arm64 \
  -t myregistry.com/emberburn:arm64 \
  --push .

# Build for both platforms
./scripts/build-multi-arch.sh --push --tag 1.0.0
```

### Native ARM64 Build

```bash
# On ARM64 host (faster than cross-compilation)
git clone https://github.com/fireball-industries/Small-Application.git
cd Small-Application

docker build -t emberburn:local .
docker run -p 4840:4840 -p 5000:5000 emberburn:local
```

## Performance Considerations

### ARM64 vs AMD64 Performance

| Metric | ARM64 (Graviton 3) | AMD64 (Intel Xeon) | Notes |
|--------|-------------------|-------------------|-------|
| **CPU Performance** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ARM64 often faster per core |
| **Cost** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 20-40% cheaper on AWS |
| **Power Efficiency** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | Better for edge/battery |
| **Memory Bandwidth** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Graviton 3 excels |

### Resource Recommendations

**Raspberry Pi**:
- **Model**: Pi 4 (4GB) or Pi 5 (8GB)
- **Resources**: 512MB RAM, 0.5 CPU cores
- **Concurrent Tags**: Up to 500 tags @ 1s update rate

**AWS Graviton**:
- **Instance**: `t4g.small` (2 vCPU, 2GB RAM)
- **Resources**: 1GB RAM, 1 CPU core
- **Concurrent Tags**: Up to 5,000 tags @ 1s update rate

**Industrial ARM Servers**:
- **Resources**: 2GB RAM, 2 CPU cores
- **Concurrent Tags**: Up to 10,000 tags @ 1s update rate

## Troubleshooting

### Architecture Mismatch Error

```
standard_init_linux.go:228: exec user process caused: exec format error
```

**Solution**: Ensure you're using the multi-arch image or correct platform-specific image:

```bash
# Force ARM64 pull
docker pull --platform linux/arm64 ghcr.io/fireball-industries/emberburn:latest

# Or specify in docker run
docker run --platform linux/arm64 \
  ghcr.io/fireball-industries/emberburn:latest
```

### QEMU Errors During Build

```
exec /usr/local/bin/python: exec format error
```

**Solution**: Install QEMU binfmt support:

```bash
# Linux
sudo apt-get install qemu-user-static binfmt-support
docker run --privileged --rm tonistiigi/binfmt --install all

# macOS
docker run --privileged --rm tonistiigi/binfmt --install all

# Windows (WSL2)
wsl --install
# Then run binfmt in WSL2
```

### Slow Multi-Arch Builds

Cross-compilation via QEMU is slower than native builds.

**Solutions**:
1. Use GitHub Actions (builds in parallel for both architectures)
2. Use native ARM64 builder (Raspberry Pi, AWS Graviton instance)
3. Enable build caching:

```bash
docker buildx build --platform linux/arm64 \
  --cache-from type=registry,ref=myregistry.com/emberburn:buildcache \
  --cache-to type=registry,ref=myregistry.com/emberburn:buildcache,mode=max \
  .
```

### Python Package Compatibility

Most Python packages work on ARM64, but some may require compilation:

**Known Compatible**:
- ✅ opcua
- ✅ paho-mqtt
- ✅ flask
- ✅ influxdb-client
- ✅ prometheus-client
- ✅ pymodbus

**May Require Build Tools**:
- Some packages need `gcc`, `g++` (already in Dockerfile)

## Production Deployment Examples

### Edge Gateway on Raspberry Pi

```bash
# Install on Raspberry Pi OS Lite (64-bit)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Create systemd service
sudo tee /etc/systemd/system/emberburn.service > /dev/null <<EOF
[Unit]
Description=EmberBurn Industrial IoT Gateway
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=always
RestartSec=10
ExecStartPre=-/usr/bin/docker stop emberburn
ExecStartPre=-/usr/bin/docker rm emberburn
ExecStart=/usr/bin/docker run --rm --name emberburn \
  -p 4840:4840 -p 5000:5000 -p 8000:8000 \
  -v /opt/emberburn/data:/app/data \
  ghcr.io/fireball-industries/emberburn:latest

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl enable emberburn
sudo systemctl start emberburn
sudo systemctl status emberburn
```

### AWS Graviton Auto Scaling

```yaml
# AWS ECS Task Definition (ARM64)
{
  "taskDefinitionArn": "arn:aws:ecs:region:account:task-definition/emberburn:1",
  "containerDefinitions": [{
    "name": "emberburn",
    "image": "ghcr.io/fireball-industries/emberburn:latest",
    "cpu": 256,
    "memory": 512,
    "portMappings": [
      {"containerPort": 4840},
      {"containerPort": 5000},
      {"containerPort": 8000}
    ]
  }],
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "runtimePlatform": {
    "cpuArchitecture": "ARM64"
  },
  "cpu": "256",
  "memory": "512"
}
```

## Best Practices

1. **Use Multi-Arch Images**: Let Docker auto-select the right platform
2. **Resource Limits**: Set appropriate limits for ARM devices
3. **Monitoring**: Use Prometheus metrics endpoint on port 8000
4. **Persistence**: Mount `/app/data` for SQLite and logs
5. **Updates**: Use `docker pull` to get latest multi-arch images
6. **Security**: Run as non-root user (already configured)
7. **Networking**: Ensure OPC UA port 4840 is accessible

## Cost Comparison (AWS)

| Instance Type | Architecture | vCPU | RAM | Cost/Month | Savings |
|--------------|--------------|------|-----|------------|---------|
| t3.small | AMD64 | 2 | 2GB | $15.18 | - |
| **t4g.small** | **ARM64** | **2** | **2GB** | **$12.26** | **19%** |
| t3.medium | AMD64 | 2 | 4GB | $30.37 | - |
| **t4g.medium** | **ARM64** | **2** | **4GB** | **$24.53** | **19%** |
| c6i.large | AMD64 | 2 | 4GB | $62.93 | - |
| **c7g.large** | **ARM64** | **2** | **4GB** | **$50.11** | **20%** |

*Prices are approximate US East (N. Virginia) on-demand rates*

## Support Matrix

| Platform | Architecture | Status | Notes |
|----------|-------------|--------|-------|
| Linux x86-64 | AMD64 | ✅ Supported | Traditional servers |
| Linux ARM64 | ARM64 | ✅ Supported | Raspberry Pi, Graviton |
| macOS Intel | AMD64 | ✅ Supported | Development only |
| macOS Apple Silicon | ARM64 | ✅ Supported | M1/M2/M3 Macs |
| Windows x86-64 | AMD64 | ✅ Supported | Docker Desktop/WSL2 |
| Windows ARM64 | ARM64 | ⚠️ Experimental | Limited testing |

## Useful Links

- **GitHub Repository**: https://github.com/fireball-industries/Small-Application
- **Docker Hub**: https://ghcr.io/fireball-industries/emberburn
- **Documentation**: https://fireballz.ai/emberburn
- **ARM Architecture Guide**: https://www.arm.com/architecture
- **AWS Graviton**: https://aws.amazon.com/ec2/graviton/
- **Raspberry Pi**: https://www.raspberrypi.com/

## Getting Help

**Issues/Questions**:
- GitHub Issues: https://github.com/fireball-industries/Small-Application/issues
- Email: patrick@fireballz.ai

**Community**:
- Discord: https://discord.gg/fireballindustries
- Discussions: https://github.com/fireball-industries/Small-Application/discussions

---

**EmberBurn - Where Data Meets Fire** 🔥  
*Now available on ARM64! Because your industrial data should run anywhere.*
