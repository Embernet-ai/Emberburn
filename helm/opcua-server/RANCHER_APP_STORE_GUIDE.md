# EmberBurn - Rancher App Store Deployment Guide

**Multi-Tenant Industrial IoT Gateway**  
*Where Data Meets Fire* - Fireball Industries

---

## Overview

EmberBurn is now available as a self-service application in the Rancher App Store for all subscribed clients. This guide explains how clients can discover, deploy, and manage EmberBurn pods through the Rancher UI without IT intervention.

### Multi-Tenant Architecture

- **Self-Service Portal**: Clients access EmberBurn through Rancher's Apps & Marketplace
- **Namespace Isolation**: Each deployment creates isolated namespaces with proper RBAC
- **Resource Control**: Clients choose resource presets (small/medium/large/custom) based on their needs
- **Pod Selection**: Clients can deploy multiple instances across different namespaces or projects
- **Fallback Support**: Fleet deployment available for troubleshooting if needed

---

## For Clients: Deploying EmberBurn

### Prerequisites

✅ Active subscription to Fireball Industries services  
✅ Access to your Rancher cluster  
✅ Basic understanding of Kubernetes namespaces (helpful but not required)  
✅ (Optional) External integrations ready (MQTT, InfluxDB, etc.)

---

### Step 1: Access the App Store

1. **Login to Rancher** at your organization's Rancher URL
2. Navigate to **Apps & Marketplace** → **Charts**
3. Search for **"EmberBurn"** or **"Industrial IoT Gateway"**
4. Click on the **EmberBurn** chart tile

---

### Step 2: Configure Your Deployment

The EmberBurn deployment wizard guides you through configuration with organized sections:

#### **Namespace Settings**
- **Namespace Name**: Choose a unique name (e.g., `production-emberburn`, `dev-iot`)
- **Create Namespace**: ✅ Enabled by default (creates namespace automatically)

#### **EmberBurn Settings**
- **Version**: Select EmberBurn version (`1.0.0` recommended)
- **Update Interval**: How often tag values refresh (default: 2 seconds)
- **Log Level**: Choose verbosity (INFO recommended, DEBUG for troubleshooting)

#### **Resources**
Choose a preset based on your workload:

| Preset | CPU Request | Memory Request | CPU Limit | Memory Limit | Best For |
|--------|-------------|----------------|-----------|--------------|----------|
| **Small** | 100m | 256Mi | 500m | 1Gi | Development, Testing |
| **Medium** | 250m | 512Mi | 1000m | 2Gi | Production (default) |
| **Large** | 500m | 1Gi | 2000m | 4Gi | High-volume data |
| **Custom** | User-defined | User-defined | User-defined | User-defined | Specific needs |

#### **Storage**
- **Enable Persistent Storage**: ✅ **REQUIRED** for data persistence
  - **Storage Size**: 10Gi (default), increase for historical data
  - **Storage Class**: Leave empty for default or select from available classes

#### **Service & Networking**

**Web UI Service Type** (how you'll access EmberBurn):
- **LoadBalancer** (recommended): Automatic external IP assignment
- **NodePort**: Access via node IP + static port (30000-32767)
- **ClusterIP**: Internal access only (use with Ingress)

**Ingress** (optional, for domain-based access):
- Enable if you want `https://emberburn.yourcompany.com`
- Requires ingress controller (nginx/traefik) installed in cluster
- Configure hostname and optional TLS/SSL certificate

#### **Protocols**

Enable the protocols you need:

✅ **REST API & Web UI** (always enabled)  
- Access at `http://<external-ip>:5000`

🔧 **OPC UA Server** (always enabled)  
- OPC UA endpoint: `opc.tcp://<external-ip>:4840/freeopcua/server/`

📊 **Prometheus Metrics** (enabled by default)  
- Metrics at `http://<external-ip>:8000/metrics`

🔌 **MQTT Publisher** (optional)  
- Publish tag data to MQTT broker
- Configure broker address, port, credentials

💾 **InfluxDB Storage** (optional)  
- Store historical data in InfluxDB
- Provide InfluxDB URL, bucket, and token

⚡ **Sparkplug B** (optional)  
- Ignition Edge compatibility
- Configure MQTT broker, Group ID, Edge Node ID

📈 **GraphQL API** (optional)  
- Advanced data queries via GraphQL

#### **Monitoring & Data**

✅ **SQLite Persistence**: Enabled by default (stores historical data locally)  
✅ **Data Transformation**: Enabled by default (unit conversions, computed tags)  
✅ **Alarms**: Enabled by default (threshold-based alerts)  

Configure alarm notifications:
- Email notifications (SMTP required)
- Slack webhooks

#### **Advanced Settings**

🔄 **Horizontal Pod Autoscaler** (optional)  
- Automatically scale pods based on CPU/memory
- Configure min/max replicas and target utilization

🎯 **Node Selector** (optional)  
- Pin pods to specific nodes (e.g., edge devices, GPU nodes)

🛡️ **Network Policy** (optional)  
- Restrict network traffic for enhanced security

🔒 **Pod Disruption Budget** (optional)  
- High availability during cluster maintenance

---

### Step 3: Deploy

1. Review all configurations
2. Click **Install** (bottom right)
3. Monitor deployment progress in **Workloads** → **Deployments**
4. Wait for pod status: **Active** (green)

**Typical deployment time**: 1-3 minutes depending on image pull and storage provisioning.

---

### Step 4: Access EmberBurn

Once deployed, access your EmberBurn instance:

#### **Web UI & REST API**
1. Navigate to **Service Discovery** → **Services**
2. Find **emberburn-webui** service
3. Click the external IP/port link (e.g., `http://192.168.1.100:5000`)
4. You'll see the EmberBurn web interface

**Default pages:**
- `/` - Dashboard with live tag values
- `/tags` - Tag configuration and management
- `/publishers` - Protocol configuration
- `/config` - System settings
- `/alarms` - Alarm status and history

#### **OPC UA Client Connection**
Connect your OPC UA client (UaExpert, Ignition, etc.):
- **Endpoint**: `opc.tcp://<external-ip>:4840/freeopcua/server/`
- **Security**: None (configure in advanced settings)
- **Browse**: Navigate to `Objects` → `EmberBurn` → `Tags`

#### **Prometheus Metrics**
Add to Prometheus scrape config:
```yaml
scrape_configs:
  - job_name: 'emberburn'
    static_configs:
      - targets: ['<external-ip>:8000']
```

---

### Step 5: Configure Tags & Publishers

#### **Via Web UI** (recommended for beginners)
1. Access Web UI at `http://<external-ip>:5000/tags`
2. Add/edit tags using the visual interface
3. Configure publishers at `/publishers`
4. Changes apply in real-time

#### **Via Helm Values** (advanced)
1. In Rancher, navigate to **Apps & Marketplace** → **Installed Apps**
2. Click **emberburn** → **Upgrade**
3. Edit YAML values under `config.tags` and `config.publishers`
4. Click **Upgrade** to apply changes

---

## Multi-Tenant Deployment Scenarios

### Scenario 1: Multiple Environments
Deploy separate instances for dev/staging/production:

```
emberburn-dev       (namespace: dev-iot)        - Small preset
emberburn-staging   (namespace: staging-iot)    - Medium preset
emberburn-prod      (namespace: prod-iot)       - Large preset
```

Each environment has isolated:
- Namespaces
- Storage (PVCs)
- Network policies
- Service endpoints

### Scenario 2: Multi-Site Deployment
Deploy per physical site or facility:

```
emberburn-plant-1   (namespace: plant-1-iot)
emberburn-plant-2   (namespace: plant-2-iot)
emberburn-warehouse (namespace: warehouse-iot)
```

Use node selectors to pin pods to edge nodes at each site.

### Scenario 3: Protocol-Specific Instances
Deploy specialized instances for different protocols:

```
emberburn-mqtt      (namespace: mqtt-gateway)    - MQTT enabled
emberburn-influx    (namespace: timeseries)      - InfluxDB enabled
emberburn-ignition  (namespace: sparkplug)       - Sparkplug B enabled
```

### Scenario 4: Multi-Tenant SaaS
Service providers can deploy per customer:

```
emberburn-customer-a (namespace: tenant-customer-a)
emberburn-customer-b (namespace: tenant-customer-b)
emberburn-customer-c (namespace: tenant-customer-c)
```

Each customer gets:
- Isolated namespace with RBAC
- Dedicated storage (PVC)
- Custom resource allocations
- Independent configuration

---

## Managing Your Deployment

### Viewing Logs
1. **Rancher UI**: **Workloads** → **Pods** → click pod → **Logs** tab
2. **kubectl**: `kubectl logs -n <namespace> deployment/emberburn -f`

### Scaling
1. **Manual**: **Workloads** → **Deployments** → **emberburn** → **⋮** → **Edit Config** → adjust replicas
2. **Auto**: Enable HPA in deployment configuration (Advanced Settings)

### Upgrading
1. **Apps & Marketplace** → **Installed Apps** → **emberburn**
2. Click **Upgrade**
3. Select new version or modify configuration
4. Click **Upgrade** to apply

### Backup & Restore
**Backup PVC** (persistent data):
```bash
kubectl get pvc -n <namespace>
# Use Rancher backup/restore or Velero
```

**Export Configuration**:
1. **Apps & Marketplace** → **Installed Apps** → **emberburn** → **YAML**
2. Copy/save YAML for disaster recovery

### Monitoring Health
1. **Workloads** → **Deployments** → **emberburn** - Check replica status
2. **Service Discovery** → **Services** - Verify endpoints
3. **Storage** → **Persistent Volumes** - Check PVC status
4. **Prometheus metrics** at `http://<external-ip>:8000/metrics`

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Pod stuck in **Pending** | Check PVC status, verify storage class exists |
| Pod **CrashLoopBackOff** | Check logs for errors, verify resource limits |
| Can't access Web UI | Check service type (LoadBalancer needs external IP support) |
| OPC UA connection fails | Verify firewall rules, check endpoint URL |
| MQTT/InfluxDB not working | Verify external service accessibility from namespace |

**Fleet Fallback**:  
If self-service deployment fails, contact support for Fleet-based deployment.

---

## Permissions & Security

### Namespace Isolation
Each EmberBurn deployment creates a dedicated namespace with:
- **ServiceAccount**: `emberburn` (auto-created)
- **RBAC Roles**: Limited to namespace resources
- **Network Policies**: Optional traffic restriction
- **Resource Quotas**: Enforced per namespace

### Security Contexts
EmberBurn runs with security hardening:
- **User/Group**: 1000/1000 (non-root)
- **Read-only Root FS**: Disabled (requires `/app/data` write access)
- **Capabilities**: All dropped
- **Privilege Escalation**: Disabled

### Storage Permissions
PersistentVolumeClaim (PVC) has:
- **Access Mode**: `ReadWriteOnce` (single node attachment)
- **FSGroup**: 1000 (write permissions for emberburn user)
- **Mount Path**: `/app/data` (full read/write)

**Files written**:
- `/app/data/emberburn.db` (SQLite database)
- `/app/data/logs/` (application logs)
- `/app/data/backups/` (configuration backups)

### Required Cluster Permissions
To deploy EmberBurn, your Rancher user needs:
- ✅ **Project Member** role (minimum)
- ✅ Create namespaces (if namespace.create=true)
- ✅ Deploy workloads (Deployments, Services)
- ✅ Create storage (PVCs)
- ✅ (Optional) Create ingress resources

**Note**: Your Rancher administrator has configured these permissions as part of your subscription.

---

## External Integrations

### MQTT Broker
If deploying external MQTT broker in cluster:
```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install mosquitto bitnami/mosquitto -n mqtt
```

Then configure EmberBurn:
- **Broker**: `mosquitto.mqtt.svc.cluster.local`
- **Port**: `1883`

### InfluxDB
If deploying external InfluxDB in cluster:
```bash
helm repo add influxdata https://helm.influxdata.com/
helm install influxdb influxdata/influxdb2 -n timeseries
```

Then configure EmberBurn:
- **URL**: `http://influxdb-influxdb2.timeseries.svc.cluster.local:80`
- **Bucket**: `emberburn`
- **Token**: (from InfluxDB setup)

### Prometheus
If Prometheus Operator installed:
1. Enable **ServiceMonitor** in deployment
2. Prometheus auto-discovers EmberBurn metrics
3. Access metrics at `http://<prometheus-url>/graph`

---

## Cost Optimization

### Resource Presets
Choose appropriate preset for your workload:

| Preset | Estimated Monthly Cost* | Use Case |
|--------|------------------------|----------|
| Small | $15-30 | Dev/test, light production |
| Medium | $40-80 | Standard production |
| Large | $100-200 | High-volume, mission-critical |

*Costs vary by cloud provider and region

### Storage Sizing
- **10Gi** (default): ~1-2 months of historical data
- **20Gi**: ~3-6 months
- **50Gi**: 1+ year

Adjust based on:
- Number of tags
- Tag update frequency
- SQLite persistence retention

### Autoscaling
Enable HPA to scale down during off-hours:
- **minReplicas**: 1
- **maxReplicas**: 3
- **Target CPU**: 80%

Can reduce costs by 30-50% for non-24/7 workloads.

---

## Best Practices

### ✅ DO
- Use **persistent storage** for production deployments
- Enable **Prometheus metrics** for monitoring
- Configure **alarms** for critical tags
- Use **LoadBalancer** for easy external access
- Test in **small** preset before scaling up
- Export YAML configuration for backup
- Use **namespace labels** for organization

### ❌ DON'T
- Disable persistent storage in production
- Run as root (security risk)
- Expose OPC UA directly to internet without VPN
- Store secrets in values.yaml (use Kubernetes secrets)
- Delete namespace without backing up PVC
- Exceed resource quotas (pod won't schedule)

---

## Support & Documentation

### Self-Service Resources
- **Web UI Help**: Built-in tooltips and documentation
- **API Documentation**: `http://<external-ip>:5000/api/docs`
- **Sample Configurations**: Check `/config` in web UI
- **Community**: Fireball Industries user forum

### Fleet Deployment Fallback
If you encounter issues with self-service deployment:
1. Contact support: `patrick@fireballz.ai`
2. Provide: Namespace name, error logs, deployment YAML
3. Support team will initiate Fleet deployment

Fleet deployment is automated but requires support ticket.

### Advanced Support
Subscription includes:
- Helm chart updates
- Security patches
- Configuration assistance
- Integration guidance

---

## FAQ

**Q: Can I deploy multiple EmberBurn instances?**  
A: Yes! Deploy as many instances as needed across different namespaces. Each is fully isolated.

**Q: Will this affect other applications in my cluster?**  
A: No. EmberBurn uses namespace isolation and resource limits to prevent interference.

**Q: Can I use my own Docker image?**  
A: Yes, in advanced YAML editing, change `emberburn.image.repository` to your registry.

**Q: What happens if I delete the deployment?**  
A: PVC persists by default. Delete PVC manually if you want to remove all data.

**Q: Can I change configuration after deployment?**  
A: Yes, use **Upgrade** in Rancher Apps or edit via Web UI (some changes require pod restart).

**Q: Is this production-ready?**  
A: Yes, EmberBurn includes health checks, security hardening, and persistent storage for production use.

**Q: What if my namespace has a ResourceQuota?**  
A: Choose a smaller preset or custom resources within your quota. Contact admin to increase quota.

**Q: Can I use this without Rancher?**  
A: Yes, deploy via Helm CLI: `helm install emberburn ./emberburn -n <namespace> -f values.yaml`

---

## Appendix: Quick Reference

### Helm CLI Deployment (Alternative)
```bash
# Add Fireball Industries Helm repo
helm repo add fireball https://fireball-industries.github.io/helm-charts
helm repo update

# Deploy EmberBurn
helm install emberburn fireball/emberburn \
  --namespace emberburn \
  --create-namespace \
  --set persistence.size=20Gi \
  --set service.webui.type=LoadBalancer

# Upgrade
helm upgrade emberburn fireball/emberburn -n emberburn -f custom-values.yaml

# Uninstall
helm uninstall emberburn -n emberburn
```

### Port Reference
| Port | Service | Protocol | Access |
|------|---------|----------|--------|
| 4840 | OPC UA Server | TCP | OPC UA clients |
| 5000 | Web UI + REST API | HTTP | Browser, API clients |
| 8000 | Prometheus Metrics | HTTP | Prometheus scraper |
| 5020 | Modbus TCP | TCP | Modbus clients (if enabled) |
| 9001 | WebSocket | WS | WebSocket clients (if enabled) |

### Environment Variables
Override via `emberburn.env` in values.yaml:
- `PYTHONUNBUFFERED=1` - Real-time logging
- `UPDATE_INTERVAL=2.0` - Tag refresh rate (seconds)
- `LOG_LEVEL=INFO` - Logging verbosity
- `OPC_ENDPOINT` - OPC UA endpoint URL
- `OPC_SERVER_NAME` - OPC UA server display name

### ConfigMap References
- `emberburn-tags-config` - Tag definitions
- `emberburn-publishers-config` - Publisher/protocol configuration

### Service Names
- `emberburn-opcua` - OPC UA server service
- `emberburn-webui` - Web UI + REST API service
- `emberburn-prometheus` - Prometheus metrics service

---

## Conclusion

EmberBurn's Rancher App Store integration provides a **true self-service experience** for multi-tenant industrial IoT deployments. Clients can:

✅ Discover and deploy EmberBurn in minutes  
✅ Choose from preset configurations or customize  
✅ Manage multiple instances across environments  
✅ Scale resources based on workload  
✅ Monitor and troubleshoot via Rancher UI  
✅ Fall back to Fleet support if needed  

This architecture empowers clients to manage their own infrastructure while maintaining enterprise-grade security, isolation, and resource control.

**Where Data Meets Fire** 🔥

---

*EmberBurn v1.0.0 - Fireball Industries*  
*Documentation Version: 2026-01-13*
