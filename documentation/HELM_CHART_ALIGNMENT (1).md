# Helm Chart Interface Alignment Guide

> How to classify and label every Helm chart deployed into our K3s environment based on what user-facing interface it provides: **GUI**, **Shell**, **GUI + Shell**, or **Headless (None)**.

---

## Why This Matters

The Embernet Dashboard uses the `embernet.ai/gui-type` label on pod templates to decide which action buttons to show on app cards:

| `gui-type` Value | Card Behavior |
|------------------|---------------|
| `web` | **"Open" button** → launches iframe/proxy to the GUI port |
| `shell` | **"Terminal" button** → opens xterm.js WebSocket shell into the pod |
| `web+shell` | **Both buttons** → user can open the GUI or terminal |
| `none` | **No buttons** → informational card only (metrics/status display) |

Every chart imported into the K3s environment **must** include these labels on its pod template to work correctly with the dashboard.

---

## Required Labels Per Chart

### Label Template

```yaml
# In your chart's templates/deployment.yaml (or statefulset.yaml)
metadata:
  labels:
    embernet.ai/gui-type: "<web|shell|web+shell|none>"
    embernet.ai/gui-port: "<port>"    # Only if gui-type includes "web"
    embernet.ai/app-name: "<name>"    # Human-readable name for the dashboard
    app: "<selector>"                 # Standard K8s app label (required for Service selector)
```

---

## Chart Classification Table

### GUI Only (`web`)

These apps have a web-based management interface. Users interact through the browser.

| Chart | GUI Port | Notes |
|-------|----------|-------|
| **Ignition Edge** (`Ignition-Edge-Pod`) | `8088` | SCADA/HMI web designer & runtime |
| **Node-RED** (`nodered-pod`) | `1880` | Flow-based automation editor |
| **Grafana** (`Grafana-Loki-Pod`) | `3000` | Dashboards & analytics |
| **Prometheus** (`prometheus-pod`) | `9090` | Metrics query UI |
| **n8n** (`n8n-pod`) | `5678` | Workflow automation UI |
| **GoRules BRMS** (`gorules-BRMS`) | `8080` | Business rules management UI |
| **CODESYS Edge Gateway** (`codesys-edgegateway-linux`) | `8443` | PLC gateway web config |
| **Traefik** (`traefik-pod`) | `8080` | Reverse proxy dashboard |
| **Emberburn** (`Emberburn`) | `5000` | Multi-protocol IoT gateway with Flask web UI (OPC UA, MQTT, Modbus, etc.) |
| **Embernet Dashboard** (`industrial-dashboard`) | `8080` | This dashboard itself |

**Label example:**
```yaml
labels:
  embernet.ai/gui-type: "web"
  embernet.ai/gui-port: "1880"
  embernet.ai/app-name: "Node-RED"
  app: node-red
```

---

### Shell Only (`shell`)

These apps have no web UI but benefit from terminal access for administration.

| Chart | Shell Command | Notes |
|-------|---------------|-------|
| **PostgreSQL** (`PostgreSQL-POD`) | `psql` | SQL database, admin via `psql` CLI |
| **SQLite** (`sqlite-pod`) | `sqlite3` | Lightweight DB, admin via `sqlite3` CLI |
| **InfluxDB** (`influxdb-pod`) | `influx` | Time-series DB, admin via `influx` CLI |
| **TimescaleDB** (`timescale-db-pod`) | `psql` | PostgreSQL-based time-series, admin via `psql` |
| **Mosquitto** (`Mosquitto-Exporter-Pod`) | `mosquitto_sub` / `mosquitto_pub` | MQTT broker, debug via CLI pub/sub tools |

**Label example:**
```yaml
labels:
  embernet.ai/gui-type: "shell"
  embernet.ai/app-name: "PostgreSQL"
  app: postgresql
```

---

### GUI + Shell (`web+shell`)

These apps have both a web UI and useful terminal access.

| Chart | GUI Port | Shell Use Case | Notes |
|-------|----------|----------------|-------|
| **CODESYS Control** (`Codesys-AMD-64-x86`, `codesys_arm_64`) | `8080` | PLC runtime shell, log inspection | IEC 61131-3 soft-PLC |
| **Micro VM Pod** (`micro-vm-pod`) | varies | Full VM shell access | Lightweight VM with web console |
| **Sorbotics Pod** (`sorbotics-pod`) | `8080` | Robot control + diagnostics shell | Robotics control platform |
| **Industrial IoT / Home Assistant** (`industrial-iot`) | `8123` | Terminal add-ons, SSH access | Home Assistant IoT automation platform |

**Label example:**
```yaml
labels:
  embernet.ai/gui-type: "web+shell"
  embernet.ai/gui-port: "8080"
  embernet.ai/app-name: "CODESYS Control"
  app: codesys
```

---

### Headless / None (`none`)

These apps have no interactive UI. They run as background services, exporters, or agents.

| Chart | Purpose | Notes |
|-------|---------|-------|
| **Telegraf** (`telegraf-pod`) | Metrics collection agent | Ships metrics to InfluxDB/Prometheus |
| **Node Exporter** (`Node-Exporter-Pod`) | Hardware metrics exporter | Prometheus scrape target |
| **Mosquitto Exporter** (`Mosquitto-Exporter-Pod`) | MQTT metrics exporter | Prometheus scrape target for Mosquitto |

| **GoRules Engine Pod** (`gorules-engine-pod`) | Headless rules engine | API-only, no interactive UI |
| **MACVLAN K3S** (`MACVLAN-K3S-Implementation`) | Network plugin | DaemonSet, no UI |


**Label example:**
```yaml
labels:
  embernet.ai/gui-type: "none"
  embernet.ai/app-name: "Telegraf"
  app: telegraf
```

---

## How to Apply Labels to Existing Charts

For each chart repository:

### Step 1: Add labels to the Deployment pod template

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "chart.fullname" . }}
spec:
  template:
    metadata:
      labels:
        app: {{ include "chart.name" . }}
        embernet.ai/app-name: {{ .Values.appName | default .Chart.Name | quote }}
        embernet.ai/gui-type: {{ .Values.guiType | default "none" | quote }}
        {{- if .Values.guiPort }}
        embernet.ai/gui-port: {{ .Values.guiPort | quote }}
        {{- end }}
```

### Step 2: Add defaults to values.yaml

```yaml
# values.yaml
appName: ""       # Human-readable name (defaults to Chart.Name)
guiType: "web"    # "web", "shell", "web+shell", or "none"
guiPort: 8080     # Port for the web UI (omit for shell/none)
nodeSelector: {}  # Required for dashboard node-targeting
```

### Step 3: Ensure the Service selector matches

```yaml
# templates/service.yaml
spec:
  selector:
    app: {{ include "chart.name" . }}
  ports:
    - port: {{ .Values.guiPort | default 8080 }}
      targetPort: {{ .Values.guiPort | default 8080 }}
```

---

## Quick Reference Matrix

| Chart | Repo | Type | GUI Port | Action |
|-------|------|------|----------|--------|
| CODESYS AMD64 | `Codesys-AMD-64-x86` | `web+shell` | 8080 | Add labels |
| CODESYS ARM64 | `codesys_arm_64` | `web+shell` | 8080 | Add labels |
| CODESYS Edge GW | `codesys-edgegateway-linux` | `web` | 8443 | Add labels |
| Emberburn | `Emberburn` | `web` | 5000 | Add labels |
| GoRules BRMS | `gorules-BRMS` | `web` | 8080 | Add labels |
| GoRules Engine | `gorules-engine-pod` | `none` | — | Add labels |
| Grafana + Loki | `Grafana-Loki-Pod` | `web` | 3000 | Add labels |
| Ignition Edge | `Ignition-Edge-Pod` | `web` | 8088 | Add labels |
| Industrial IoT | `industrial-iot` | `web+shell` | 8123 | Add labels |
| Embernet Dashboard | `industrial-dashboard` | `web` | 8080 | ✅ Already labeled |
| InfluxDB | `influxdb-pod` | `shell` | — | Add labels |
| MACVLAN K3S | `MACVLAN-K3S-Implementation` | `none` | — | Add labels |
| Micro VM | `micro-vm-pod` | `web+shell` | varies | Add labels |
| Mosquitto Exporter | `Mosquitto-Exporter-Pod` | `none` | — | Add labels |
| n8n | `n8n-pod` | `web` | 5678 | Add labels |
| Node Exporter | `Node-Exporter-Pod` | `none` | — | Add labels |
| Node-RED | `nodered-pod` | `web` | 1880 | Add labels |
| PostgreSQL | `PostgreSQL-POD` | `shell` | — | Add labels |
| Prometheus | `prometheus-pod` | `web` | 9090 | Add labels |
| Sorbotics | `sorbotics-pod` | `web+shell` | 8080 | Add labels |
| SQLite | `sqlite-pod` | `shell` | — | Add labels |
| Telegraf | `telegraf-pod` | `none` | — | Add labels |
| TimescaleDB | `timescale-db-pod` | `shell` | — | Add labels |
| Traefik | `traefik-pod` | `web` | 8080 | Add labels |

---

## Validation

After labeling all charts, verify from inside the cluster:

```bash
# List all pods with their gui-type label:
kubectl get pods -A -l embernet.ai/gui-type --show-labels

# Check a specific app:
kubectl get pods -n fireball-system -l app=node-red -o jsonpath='{.items[*].metadata.labels}'
```

From the dashboard, each app card should now show the correct action buttons:
- **Web apps** → "Open" button
- **Shell apps** → "Terminal" button  
- **Web+Shell apps** → Both buttons
- **Headless apps** → Status card only (no action buttons)
