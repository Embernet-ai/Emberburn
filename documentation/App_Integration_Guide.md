# App Integration Guide

This guide explains **everything** you need to do to integrate an application into the Embernet Industrial Dashboard ecosystem. This covers:

1. **Helm Chart Requirements**: Labels, annotations, and templates
2. **Application-Level Configuration**: What the app itself needs
3. **GUI Type Configurations**: Web, Shell, Web+Shell, None
4. **Complete Reference**: Every app in the ecosystem with exact settings

---

## TL;DR: Minimum Requirements

To make ANY pod visible in the dashboard:

```yaml
# On the pod template (Deployment/StatefulSet/DaemonSet)
metadata:
  labels:
    embernet.ai/store-app: "true"      # REQUIRED — no label = invisible
    embernet.ai/gui-type: "web"        # REQUIRED — "web", "shell", "web+shell", "none"
    embernet.ai/gui-port: "8080"       # REQUIRED for web/web+shell types
    embernet.ai/app-name: "My App"     # Recommended — display name
    app: myapp                          # REQUIRED — Service selector match
```

**Without `embernet.ai/store-app: "true"`, the pod does not exist to the dashboard.**

---

## Part 1: How the Dashboard Discovers Apps

The dashboard backend queries Kubernetes with a single label selector:

```go
LabelSelector: "embernet.ai/store-app=true"
```

Every 5 seconds, the dashboard:
1. Queries the K8s API for all pods with this label
2. Reads additional labels/annotations to determine display properties
3. Cross-references with the Helm store catalog for icons
4. Renders app cards with appropriate action buttons

### What Gets Read From Each Pod

| Property | Source (Priority Order) |
|----------|------------------------|
| **Visibility** | `embernet.ai/store-app` label (must be `"true"`) |
| **App Name** | `embernet.ai/app-name` label → `app` label → pod name |
| **Display Name** | `embernet.ai/display-name` annotation → App Name |
| **Release Name** | `app.kubernetes.io/instance` label → `app` label |
| **GUI Port** | `embernet.ai/gui-port` label → annotation → first containerPort |
| **GUI Type** | `embernet.ai/gui-type` label → annotation → auto-detect |
| **Icon** | `embernet.ai/app-icon` label → store catalog lookup |
| **Device** | `embernet.ai/device` label → node name |

---

## Part 2: Required Labels (Helm Chart)

Every pod created by your Helm chart **MUST** have these labels.

### `embernet.ai/store-app: "true"`: THE GATEKEEPER

```yaml
spec:
  template:
    metadata:
      labels:
        embernet.ai/store-app: "true"
```

**This is the bouncer at the door. No label = pod is invisible. No exceptions.**

### `embernet.ai/gui-type: "<type>"`: DETERMINES UI RENDERING

| Value | Card Shows | What Happens |
|-------|-----------|--------------|
| `web` | Blue "OPEN" button | Opens iframe to GUI port via Rancher proxy |
| `shell` | Green "TERMINAL" button | Opens xterm.js WebSocket shell into pod |
| `web+shell` | Both buttons | User chooses GUI or terminal |
| `none` | "● Running" status only | No action buttons, informational card |

```yaml
labels:
  embernet.ai/gui-type: "web"        # Has web UI
  embernet.ai/gui-type: "shell"      # CLI only (databases)
  embernet.ai/gui-type: "web+shell"  # Both (CODESYS, Home Assistant)
  embernet.ai/gui-type: "none"       # Background service (Telegraf)
```

### `embernet.ai/gui-port: "<port>"`: WHERE THE WEB UI LIVES

**Required for `web` and `web+shell` types. Omit for `shell` and `none`.**

```yaml
labels:
  embernet.ai/gui-port: "1880"       # Node-RED
  embernet.ai/gui-port: "3000"       # Grafana
  embernet.ai/gui-port: "8088"       # Ignition Edge
  embernet.ai/gui-port: "8080"       # Generic
```

**IMPORTANT: Must be a STRING, not an integer!** YAML interprets unquoted numbers as integers, but K8s labels are always strings.

### `app: <name>`: SERVICE SELECTOR MATCH

This standard K8s label is used for:
1. Service selector matching
2. Rancher proxy URL construction
3. Fallback app name resolution

```yaml
labels:
  app: node-red
  app: grafana
  app: postgresql
```

**The Service in your chart MUST select on this same label, or the "Open" button returns 404.**

---

## Part 3: Recommended Labels & Annotations

### `embernet.ai/app-name` (Label)

Human-readable name shown on app cards. Defaults to `app` label if not set.

```yaml
labels:
  embernet.ai/app-name: "Node-RED"
  embernet.ai/app-name: "Grafana"
  embernet.ai/app-name: "PostgreSQL"
```

### `embernet.ai/display-name` (Annotation)

Longer display name for multi-instance disambiguation. Use an **annotation** because labels have a 63-character limit.

```yaml
annotations:
  embernet.ai/display-name: "Node-RED — Production Line A"
  embernet.ai/display-name: "PostgreSQL — Staging Database"
```

### `embernet.ai/device` (Label)

Maps the app to a physical device in the digital twin. Defaults to the K8s node name.

```yaml
labels:
  embernet.ai/device: "plc-conveyor-01"
  embernet.ai/device: "hmi-panel-03"
```

### `app.kubernetes.io/instance` (Label)

Standard Helm release name label. Used for unique identification when multiple instances of the same app are deployed.

```yaml
labels:
  app.kubernetes.io/instance: {{ .Release.Name }}
```

---

## Part 4: GUI Type Deep Dive

### TYPE: `web`: Apps With Web UI

For applications that have a browser-based management interface.

**Dashboard Behavior:**
- Shows blue "OPEN" button on card
- Clicking opens full-screen iframe overlay
- Traffic proxied through Rancher K8s API: `/k8s/clusters/local/api/v1/namespaces/<ns>/services/http:<app>:<port>/proxy/`

**Required Labels:**
```yaml
labels:
  embernet.ai/store-app: "true"
  embernet.ai/gui-type: "web"
  embernet.ai/gui-port: "<port>"
  embernet.ai/app-name: "<name>"
  app: <selector>
```

**Complete Example: Node-RED:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nodered
spec:
  template:
    metadata:
      labels:
        app: node-red
        embernet.ai/store-app: "true"
        embernet.ai/gui-type: "web"
        embernet.ai/gui-port: "1880"
        embernet.ai/app-name: "Node-RED"
        app.kubernetes.io/instance: {{ .Release.Name }}
      annotations:
        embernet.ai/display-name: "Node-RED — {{ .Values.environment }}"
    spec:
      containers:
        - name: node-red
          image: nodered/node-red:latest
          ports:
            - containerPort: 1880
```

**Apps in This Category:**

| App | Chart Repo | GUI Port | Notes |
|-----|-----------|----------|-------|
| Node-RED | `nodered-pod` | 1880 | Flow-based automation |
| Grafana | `Grafana-Loki-Pod` | 3000 | Dashboards & analytics |
| Prometheus | `prometheus-pod` | 9090 | Metrics query UI |
| Ignition Edge | `Ignition-Edge-Pod` | 8088 | SCADA/HMI designer |
| n8n | `n8n-pod` | 5678 | Workflow automation |
| GoRules BRMS | `gorules-BRMS` | 8080 | Business rules UI |
| CODESYS Edge Gateway | `codesys-edgegateway-linux` | 8443 | PLC gateway config |
| Traefik | `traefik-pod` | 8080 | Reverse proxy dashboard |
| Emberburn | `Emberburn` | 5000 | Multi-protocol IoT gateway |
| Embernet Dashboard | `industrial-dashboard` | 8080 | This dashboard |

---

### TYPE: `shell`: CLI-Only Apps (Databases, Brokers)

For applications with no web UI but useful CLI administration.

**Dashboard Behavior:**
- Shows green "TERMINAL" button on card
- Clicking opens xterm.js WebSocket terminal
- Connects via K8s exec API to first container in pod
- Clicking the entire card (not just button) also opens shell

**Required Labels:**
```yaml
labels:
  embernet.ai/store-app: "true"
  embernet.ai/gui-type: "shell"
  embernet.ai/app-name: "<name>"
  app: <selector>
```

**DO NOT include `embernet.ai/gui-port`: it's ignored for shell-only apps.**

**Complete Example: PostgreSQL:**
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
spec:
  template:
    metadata:
      labels:
        app: postgresql
        embernet.ai/store-app: "true"
        embernet.ai/gui-type: "shell"
        embernet.ai/app-name: "PostgreSQL"
        app.kubernetes.io/instance: {{ .Release.Name }}
      annotations:
        embernet.ai/display-name: "PostgreSQL — {{ .Values.database }}"
    spec:
      containers:
        - name: postgresql
          image: postgres:15
          ports:
            - containerPort: 5432    # Database port (NOT a GUI!)
          env:
            - name: POSTGRES_DB
              value: {{ .Values.database }}
```

**Apps in This Category:**

| App | Chart Repo | Shell Command | Notes |
|-----|-----------|---------------|-------|
| PostgreSQL | `PostgreSQL-POD` | `psql` | SQL database |
| SQLite | `sqlite-pod` | `sqlite3` | Embedded DB |
| InfluxDB | `influxdb-pod` | `influx` | Time-series DB |
| TimescaleDB | `timescale-db-pod` | `psql` | Time-series PostgreSQL |
| Mosquitto | `Mosquitto-Exporter-Pod` | `mosquitto_sub` / `mosquitto_pub` | MQTT broker |

**Application-Level Requirements for Shell Apps:**

1. **Shell must be available in container image:**
   - PostgreSQL: Has `psql` in official image
   - InfluxDB: Has `influx` CLI in official image
   - Alpine-based: May need `apk add bash` if shell is missing

2. **User must have shell access:**
   - Container shouldn't run as a restricted user that can't exec
   - `securityContext.runAsNonRoot: true` is fine, but the user needs a shell

---

### TYPE: `web+shell`: Apps With Both

For applications that have a web UI AND benefit from terminal access.

**Dashboard Behavior:**
- Shows BOTH blue "OPEN" and green "TERMINAL" buttons
- User can access web UI or shell as needed

**Required Labels:**
```yaml
labels:
  embernet.ai/store-app: "true"
  embernet.ai/gui-type: "web+shell"
  embernet.ai/gui-port: "<port>"
  embernet.ai/app-name: "<name>"
  app: <selector>
```

**Complete Example: CODESYS Control:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: codesys-control
spec:
  template:
    metadata:
      labels:
        app: codesys
        embernet.ai/store-app: "true"
        embernet.ai/gui-type: "web+shell"
        embernet.ai/gui-port: "8080"
        embernet.ai/app-name: "CODESYS Control"
        app.kubernetes.io/instance: {{ .Release.Name }}
    spec:
      containers:
        - name: codesys
          image: codesys/codesyscontrol:latest
          ports:
            - containerPort: 8080    # Web config UI
            - containerPort: 11740   # PLC communication port
```

**Apps in This Category:**

| App | Chart Repo | GUI Port | Shell Use Case |
|-----|-----------|----------|----------------|
| CODESYS Control AMD64 | `Codesys-AMD-64-x86` | 8080 | PLC runtime logs, diagnostics |
| CODESYS Control ARM64 | `codesys_arm_64` | 8080 | PLC runtime logs, diagnostics |
| Home Assistant | `industrial-iot` | 8123 | Add-on management, SSH |
| Micro VM Pod | `micro-vm-pod` | varies | Full VM shell access |
| Sorbotics | `sorbotics-pod` | 8080 | Robot diagnostics |

---

### TYPE: `none`: Background Services (Headless)

For applications with no interactive UI. Exporters, agents, data collectors.

**Dashboard Behavior:**
- Card shows "● Running" status indicator (green dot)
- Dashed border, slightly reduced opacity (0.85)
- No action buttons
- Purely informational: shows the service is alive

**Required Labels:**
```yaml
labels:
  embernet.ai/store-app: "true"
  embernet.ai/gui-type: "none"
  embernet.ai/app-name: "<name>"
  app: <selector>
```

**Complete Example: Telegraf:**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: telegraf
spec:
  template:
    metadata:
      labels:
        app: telegraf
        embernet.ai/store-app: "true"
        embernet.ai/gui-type: "none"
        embernet.ai/app-name: "Telegraf"
    spec:
      containers:
        - name: telegraf
          image: telegraf:latest
          # No exposed ports needed for dashboard
```

**Apps in This Category:**

| App | Chart Repo | Purpose |
|-----|-----------|---------|
| Telegraf | `telegraf-pod` | Metrics collection agent |
| Node Exporter | `Node-Exporter-Pod` | Hardware metrics for Prometheus |
| Mosquitto Exporter | `Mosquitto-Exporter-Pod` | MQTT metrics exporter |
| GoRules Engine | `gorules-engine-pod` | Headless rules execution |
| MACVLAN K3S | `MACVLAN-K3S-Implementation` | Network plugin (DaemonSet) |

---

## Part 5: Helm Chart Template Requirements

### Deployment Template (Complete)

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "mychart.fullname" . }}
  labels:
    app: {{ include "mychart.name" . }}
    app.kubernetes.io/instance: {{ .Release.Name }}
spec:
  replicas: {{ .Values.replicaCount | default 1 }}
  selector:
    matchLabels:
      app: {{ include "mychart.name" . }}
  template:
    metadata:
      labels:
        # === STANDARD K8S LABELS ===
        app: {{ include "mychart.name" . }}
        app.kubernetes.io/instance: {{ .Release.Name }}
        app.kubernetes.io/name: {{ include "mychart.name" . }}
        
        # === EMBERNET REQUIRED LABELS ===
        embernet.ai/store-app: "true"
        embernet.ai/gui-type: {{ .Values.guiType | quote }}
        {{- if .Values.guiPort }}
        embernet.ai/gui-port: {{ .Values.guiPort | quote }}
        {{- end }}
        embernet.ai/app-name: {{ .Values.appName | default .Chart.Name | quote }}
        
        # === EMBERNET OPTIONAL LABELS ===
        {{- if .Values.device }}
        embernet.ai/device: {{ .Values.device | quote }}
        {{- end }}
      annotations:
        {{- if .Values.displayName }}
        embernet.ai/display-name: {{ .Values.displayName | quote }}
        {{- end }}
    spec:
      # === NODE SELECTOR (REQUIRED FOR DASHBOARD TARGETING) ===
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      
      # === IMAGE PULL SECRETS (FOR PRIVATE REGISTRIES) ===
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      
      # === TOLERATIONS ===
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      
      # === AFFINITY ===
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy | default "IfNotPresent" }}
          {{- if .Values.guiPort }}
          ports:
            - name: http
              containerPort: {{ .Values.guiPort }}
              protocol: TCP
          {{- end }}
          {{- with .Values.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.env }}
          env:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.volumeMounts }}
          volumeMounts:
            {{- toYaml . | nindent 12 }}
          {{- end }}
      {{- with .Values.volumes }}
      volumes:
        {{- toYaml . | nindent 8 }}
      {{- end }}
```

### Service Template (Required for Web Apps)

```yaml
# templates/service.yaml
{{- if or (eq .Values.guiType "web") (eq .Values.guiType "web+shell") }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "mychart.fullname" . }}
  labels:
    app: {{ include "mychart.name" . }}
    app.kubernetes.io/instance: {{ .Release.Name }}
spec:
  type: {{ .Values.service.type | default "ClusterIP" }}
  ports:
    - port: {{ .Values.guiPort }}
      targetPort: {{ .Values.guiPort }}
      protocol: TCP
      name: http
  selector:
    app: {{ include "mychart.name" . }}
{{- end }}
```

### Values File (Complete)

```yaml
# values.yaml

# === IMAGE CONFIGURATION ===
image:
  repository: myregistry/myapp
  tag: "latest"
  pullPolicy: IfNotPresent

imagePullSecrets: []
  # - name: ghcr-pull-secret

# === EMBERNET DASHBOARD INTEGRATION ===
# REQUIRED: Set these for dashboard visibility
appName: ""              # Display name (defaults to Chart.Name)
displayName: ""          # Longer name for multi-instance disambiguation
guiType: "web"           # "web", "shell", "web+shell", or "none"
guiPort: 8080            # Port for web UI (omit for shell/none types)
device: ""               # Physical device mapping (defaults to node name)

# === KUBERNETES SCHEDULING ===
# CRITICAL: nodeSelector must be supported for dashboard node targeting
nodeSelector: {}
tolerations: []
affinity: {}

# === RESOURCES ===
replicaCount: 1
resources: {}
  # limits:
  #   cpu: 500m
  #   memory: 512Mi
  # requests:
  #   cpu: 100m
  #   memory: 128Mi

# === SERVICE ===
service:
  type: ClusterIP

# === APPLICATION-SPECIFIC ===
env: []
volumes: []
volumeMounts: []
```

---

## Part 6: Application-Level Requirements (Non-Helm)

Beyond Helm labels, applications themselves may need configuration:

### Web Apps: iframe Compatibility

The dashboard opens web UIs in an iframe. Some apps block this by default.

**X-Frame-Options / CSP Headers:**

Many apps set `X-Frame-Options: DENY` or `Content-Security-Policy: frame-ancestors 'none'`. You must disable this:

| App | How to Allow iframe |
|-----|---------------------|
| **Grafana** | `grafana.ini`: `allow_embedding = true` and `security.cookie_samesite = none` |
| **Node-RED** | `settings.js`: `httpAdminRoot: '/'` and `ui: { page: { title: 'Node-RED' } }` |
| **Prometheus** | Default allows iframe (no change needed) |
| **n8n** | Environment: `N8N_EDITOR_BASE_URL` must match dashboard URL |
| **Home Assistant** | `configuration.yaml`: Add `http: { use_x_frame_options: false }` |

**Example: Grafana ConfigMap:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-config
data:
  grafana.ini: |
    [security]
    allow_embedding = true
    cookie_samesite = none
    
    [auth.anonymous]
    enabled = false
```

### Shell Apps: Container Requirements

For shell access to work:

1. **Shell binary must exist:**
   - `/bin/sh` or `/bin/bash` must be in the container
   - Alpine images: Usually have `/bin/sh` (busybox)
   - Distroless images: **DO NOT WORK**, no shell available

2. **Process must allow exec:**
   - Don't run with `readOnlyRootFilesystem: true` if shell needs to write temp files
   - PID 1 process must keep running (shell attaches to the container)

3. **User permissions:**
   - The container user needs exec permissions
   - Root is not required, but the user needs a valid shell

### Headless Apps: Health Endpoints

For `none` type apps, consider adding:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
```

This ensures K8s knows the app is healthy even without dashboard interaction.

---

## Part 7: Complete App Reference Table

| App | Chart Repo | GUI Type | GUI Port | Shell | Notes |
|-----|-----------|----------|----------|-------|-------|
| **Node-RED** | `nodered-pod` | `web` | 1880 | N/A | Flow automation |
| **Grafana** | `Grafana-Loki-Pod` | `web` | 3000 | N/A | Dashboards |
| **Prometheus** | `prometheus-pod` | `web` | 9090 | N/A | Metrics query |
| **Ignition Edge** | `Ignition-Edge-Pod` | `web` | 8088 | N/A | SCADA designer |
| **n8n** | `n8n-pod` | `web` | 5678 | N/A | Workflow automation |
| **GoRules BRMS** | `gorules-BRMS` | `web` | 8080 | N/A | Business rules UI |
| **CODESYS Edge GW** | `codesys-edgegateway-linux` | `web` | 8443 | N/A | Gateway config |
| **Traefik** | `traefik-pod` | `web` | 8080 | N/A | Proxy dashboard |
| **Emberburn** | `Emberburn` | `web` | 5000 | N/A | IoT gateway |
| **PostgreSQL** | `PostgreSQL-POD` | `shell` | N/A | `psql` | SQL database |
| **SQLite** | `sqlite-pod` | `shell` | N/A | `sqlite3` | Embedded DB |
| **InfluxDB** | `influxdb-pod` | `shell` | N/A | `influx` | Time-series DB |
| **TimescaleDB** | `timescale-db-pod` | `shell` | N/A | `psql` | Time-series |
| **Mosquitto** | `Mosquitto-Exporter-Pod` | `shell` | N/A | `mosquitto_sub` | MQTT broker |
| **CODESYS AMD64** | `Codesys-AMD-64-x86` | `web+shell` | 8080 | PLC logs | Soft-PLC |
| **CODESYS ARM64** | `codesys_arm_64` | `web+shell` | 8080 | PLC logs | Soft-PLC |
| **Home Assistant** | `industrial-iot` | `web+shell` | 8123 | Add-ons | IoT platform |
| **Micro VM** | `micro-vm-pod` | `web+shell` | varies | Full VM | VM container |
| **Sorbotics** | `sorbotics-pod` | `web+shell` | 8080 | Diagnostics | Robotics |
| **Telegraf** | `telegraf-pod` | `none` | N/A | N/A | Metrics agent |
| **Node Exporter** | `Node-Exporter-Pod` | `none` | N/A | N/A | HW metrics |
| **Mosquitto Exporter** | `Mosquitto-Exporter-Pod` | `none` | N/A | N/A | MQTT metrics |
| **GoRules Engine** | `gorules-engine-pod` | `none` | N/A | N/A | Headless rules |
| **MACVLAN K3S** | `MACVLAN-K3S-Implementation` | `none` | N/A | N/A | Network plugin |

---

## Part 8: Adding Labels to Existing Charts

If you have an existing Helm chart that works but doesn't appear in the dashboard, follow these steps:

### Step 1: Edit the Deployment Template

Open `templates/deployment.yaml` and add the Embernet labels to the pod template:

```yaml
spec:
  template:
    metadata:
      labels:
        # YOUR EXISTING LABELS (keep these)
        app: {{ include "mychart.name" . }}
        
        # ADD THESE EMBERNET LABELS
        embernet.ai/store-app: "true"
        embernet.ai/gui-type: {{ .Values.guiType | default "web" | quote }}
        {{- if .Values.guiPort }}
        embernet.ai/gui-port: {{ .Values.guiPort | quote }}
        {{- end }}
        embernet.ai/app-name: {{ .Values.appName | default .Chart.Name | quote }}
        app.kubernetes.io/instance: {{ .Release.Name }}
```

### Step 2: Add Values Defaults

Open `values.yaml` and add:

```yaml
# Embernet Dashboard Integration
appName: ""              # Human-readable name (defaults to Chart.Name)
guiType: "web"           # "web", "shell", "web+shell", or "none"
guiPort: 8080            # Port for web UI (omit for shell/none)

# IMPORTANT: nodeSelector must be supported for dashboard node targeting
nodeSelector: {}
```

### Step 3: Verify Service Selector

The biggest mistake: Service doesn't select the pod. Open `templates/service.yaml`:

```yaml
spec:
  selector:
    app: {{ include "mychart.name" . }}   # MUST match deployment labels
```

### Step 4: Deploy and Test

```bash
helm upgrade --install myapp ./mychart --set guiType=web --set guiPort=8080
```

The app should now appear in the dashboard.

---

## Part 9: Rancher Proxy URL Construction

**This is how the dashboard routes traffic to your app's web UI.**

When you click "Open" on an app card, the dashboard constructs a URL:

```
/k8s/clusters/local/api/v1/namespaces/<namespace>/services/http:<service-name>:<port>/proxy/
```

For this to work:

| Requirement | How to Satisfy |
|-------------|---------------|
| **Namespace** | Read from pod metadata |
| **Service Name** | Must match `app` label value |
| **Port** | Read from `embernet.ai/gui-port` label |

**Example:**

Pod labels:
```yaml
app: node-red
embernet.ai/gui-port: "1880"
```

Generated URL:
```
/k8s/clusters/local/api/v1/namespaces/default/services/http:node-red:1880/proxy/
```

**If Service name doesn't match `app` label, you get 404.**

---

## Part 10: WebSocket Shell Connection

**This is how the dashboard opens terminals into your pods.**

When you click "Terminal" on an app card, the dashboard:

1. Reads pod name and namespace from K8s API
2. Opens WebSocket to Rancher exec endpoint:
   ```
   wss://<rancher>/k8s/clusters/local/api/v1/namespaces/<ns>/pods/<pod>/exec?
   command=/bin/sh&stdin=true&stdout=true&stderr=true&tty=true
   ```
3. Connects xterm.js to the WebSocket
4. Renders interactive terminal in overlay

**Requirements for shell to work:**

1. **Container must have a shell** (`/bin/sh` or `/bin/bash`)
2. **Pod must be Running** (not CrashLoopBackOff)
3. **User must have K8s exec permissions** (inherited from Rancher SSO)

---

## Part 11: Complete App Configuration Examples

### Example A: Web-Only App (n8n Workflow Automation)

**Helm Values:**
```yaml
appName: "n8n"
guiType: "web"
guiPort: 5678
nodeSelector: {}

image:
  repository: n8nio/n8n
  tag: latest

env:
  # CRITICAL: Allow iframe embedding
  - name: N8N_PROTOCOL
    value: "http"
  - name: VUE_APP_URL_BASE_API
    value: "/"
  # Allow cross-origin for Rancher proxy
  - name: N8N_EDITOR_BASE_URL
    value: "/"
```

**Application Configuration:**

n8n needs these environment variables to work in an iframe:

| Variable | Value | Purpose |
|----------|-------|---------|
| `N8N_PROTOCOL` | `http` | Match Rancher proxy protocol |
| `VUE_APP_URL_BASE_API` | `/` | Relative API paths |
| `N8N_EDITOR_BASE_URL` | `/` | Relative editor paths |

---

### Example B: Shell-Only App (InfluxDB Time-Series)

**Helm Values:**
```yaml
appName: "InfluxDB"
guiType: "shell"
# NO guiPort — shell apps don't use it
nodeSelector: {}

image:
  repository: influxdb
  tag: "2.7"

persistence:
  enabled: true
  size: 10Gi
```

**Application Configuration:**

InfluxDB CLI must be available in container:
- Official `influxdb` image includes `influx` CLI
- Use `influx` command once shell opens

**Container shell commands useful in terminal:**
```bash
# Query databases
influx bucket list

# Write test data
influx write --bucket mybucket --precision s "cpu,host=server01 usage=42"

# Query data
influx query 'from(bucket:"mybucket") |> range(start: -1h)'
```

---

### Example C: Web+Shell App (Home Assistant)

**Helm Values:**
```yaml
appName: "Home Assistant"
guiType: "web+shell"
guiPort: 8123
nodeSelector: {}

image:
  repository: ghcr.io/home-assistant/home-assistant
  tag: stable

persistence:
  enabled: true
  size: 5Gi
  path: /config
```

**Application Configuration:**

Home Assistant needs `configuration.yaml` changes:

```yaml
# /config/configuration.yaml

# CRITICAL: Allow iframe embedding
http:
  use_x_frame_options: false
  # If behind proxy:
  use_x_forwarded_for: true
  trusted_proxies:
    - 10.0.0.0/8
    - 172.16.0.0/12
```

**Shell use cases:**
- Edit `configuration.yaml` directly
- Restart Home Assistant core
- View real-time logs
- Install custom integrations

---

### Example D: Headless App (Telegraf Metrics Agent)

**Helm Values:**
```yaml
appName: "Telegraf Agent"
guiType: "none"
# NO guiPort — headless apps don't use it
nodeSelector: {}

image:
  repository: telegraf
  tag: latest

# Deploy on every node
kind: DaemonSet
```

**Application Configuration:**

Telegraf config via ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: telegraf-config
data:
  telegraf.conf: |
    [global_tags]
      dc = "us-east-1"
    
    [agent]
      interval = "10s"
      round_interval = true
      metric_buffer_limit = 10000
    
    [[inputs.cpu]]
      percpu = true
      totalcpu = true
    
    [[inputs.mem]]
    
    [[inputs.disk]]
      ignore_fs = ["tmpfs", "devtmpfs"]
    
    [[outputs.influxdb_v2]]
      urls = ["http://influxdb:8086"]
      token = "$INFLUX_TOKEN"
      organization = "embernet"
      bucket = "telegraf"
```

**Dashboard shows:**
- Green "● Running" status indicator
- No action buttons
- App card with dashed border

---

## Part 12: Label Precedence Reference

The dashboard resolves metadata in this priority order:

| Property | Priority 1 | Priority 2 | Priority 3 | Fallback |
|----------|------------|------------|------------|----------|
| **Visibility** | `embernet.ai/store-app` label | - | - | Not visible |
| **App Name** | `embernet.ai/app-name` label | `app` label | - | Pod name |
| **Display Name** | `embernet.ai/display-name` annotation | App Name | - | - |
| **Release Name** | `app.kubernetes.io/instance` label | `app` label | - | - |
| **GUI Port** | `embernet.ai/gui-port` label | annotation | First containerPort | None |
| **GUI Type** | `embernet.ai/gui-type` label | annotation | "web" if port exists | "none" |
| **Device** | `embernet.ai/device` label | - | - | Node name |

---

## Part 13: Troubleshooting Guide

### Pod Not Visible in Dashboard

**Symptom:** Deployed app doesn't appear on any dashboard screen.

**Check:**
```bash
# Verify label exists
kubectl get pods -l embernet.ai/store-app=true

# Check specific pod labels
kubectl get pod <podname> -o jsonpath='{.metadata.labels}'
```

**Fix:** Add `embernet.ai/store-app: "true"` label to pod template.

---

### "Open" Button Returns 404

**Symptom:** Clicking "OPEN" shows blank page or 404 error.

**Check:**
```bash
# Verify Service exists
kubectl get svc

# Verify Service selector matches pod labels
kubectl get svc <name> -o jsonpath='{.spec.selector}'
kubectl get pod <name> -o jsonpath='{.metadata.labels.app}'
```

**Fix:** Service `selector.app` must match pod `labels.app`.

---

### "Open" Button Returns 503

**Symptom:** Service is found but returns 503 Service Unavailable.

**Check:**
```bash
# Verify pod is running
kubectl get pods

# Check if endpoints exist
kubectl get endpoints <servicename>
```

**Fix:** Pod is not ready. Check container logs and readiness probes.

---

### Terminal Button Does Nothing

**Symptom:** Clicking "TERMINAL" doesn't open shell overlay.

**Check:**
```bash
# Test exec manually
kubectl exec -it <podname> -- /bin/sh
```

**Fix:** 
- Container might not have a shell (distroless image)
- User might lack K8s exec permissions
- Pod might be in CrashLoopBackOff

---

### App Shows Wrong GUI Type

**Symptom:** Database shows "OPEN" instead of "TERMINAL".

**Check:**
```bash
kubectl get pod <name> -o jsonpath='{.metadata.labels.embernet\.ai/gui-type}'
```

**Fix:** Set correct `embernet.ai/gui-type` label.

---

### App Deploys to Wrong Node

**Symptom:** Dashboard deployed app to node A, wanted node B.

**Check:**
- Chart supports `nodeSelector` in values.yaml
- Deployment template uses `{{- with .Values.nodeSelector }}`

**Fix:**
```yaml
# values.yaml
nodeSelector:
  kubernetes.io/hostname: "node-b"
```

---

### Web UI Blank in iframe

**Symptom:** "OPEN" works but iframe is empty/blocked.

**Check (browser console):**
- `Refused to display in a frame because it set 'X-Frame-Options' to 'deny'`
- `Refused to frame because an ancestor violates Content-Security-Policy`

**Fix:** Configure app to allow iframe embedding (see Part 6).

---

## Part 14: Flux Overlay Integration

For apps that need remote site access via the Flux zero-trust overlay:

### Service Annotations

```yaml
# templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "mychart.fullname" . }}
  annotations:
    # Enable Flux overlay exposure
    flux.embernet.ai/expose: "true"
    
    # Service name in overlay (defaults to K8s service name)
    flux.embernet.ai/service-name: "myapp"
    
    # Port to expose (defaults to first port)
    flux.embernet.ai/port: "8080"
    
    # OpenZiti role attributes for policy
    flux.embernet.ai/role-attributes: "gui-services"
spec:
  ports:
    - port: 8080
  selector:
    app: {{ include "mychart.name" . }}
```

### How It Works

1. Edge tunnel (OpenZiti SDK) watches Services with `flux.embernet.ai/expose: "true"`
2. Registers service with Flux controller
3. Remote users access via `myapp.flux.embernet.ai` (internal DNS)
4. Traffic tunneled through OpenZiti overlay

### Role Attributes

| Attribute | Access Level |
|-----------|-------------|
| `gui-services` | Web UI access only |
| `industrial-protocols` | OPC-UA, Modbus, etc. |
| `database` | Direct DB access |
| `admin` | Full unrestricted access |

---

## Part 15: Quick Reference Card

### Required Labels (Minimum)

```yaml
labels:
  embernet.ai/store-app: "true"    # Makes pod visible
  embernet.ai/gui-type: "<type>"   # web, shell, web+shell, none
  embernet.ai/gui-port: "<port>"   # Required for web types
  app: <name>                       # Service selector match
```

### GUI Types Summary

| Type | Has Web UI | Has Shell | Dashboard Shows |
|------|-----------|----------|-----------------|
| `web` | Yes | No | OPEN button |
| `shell` | No | Yes | TERMINAL button |
| `web+shell` | Yes | Yes | Both buttons |
| `none` | No | No | Status indicator |

### Files to Edit

| File | What to Add |
|------|-------------|
| `templates/deployment.yaml` | Embernet labels on pod template |
| `templates/service.yaml` | Service with matching selector |
| `values.yaml` | `guiType`, `guiPort`, `nodeSelector` |

### Debug Commands

```bash
# Check if pod has correct labels
kubectl get pods -l embernet.ai/store-app=true

# Verify specific label values
kubectl get pod <name> -o jsonpath='{.metadata.labels}'

# Test service connectivity
kubectl port-forward svc/<name> 8080:8080

# Test shell access
kubectl exec -it <podname> -- /bin/sh
```

---

## Next Steps

- [Getting Started](Getting_Started.md): Dashboard deployment
- [Administrator Guide](Administrator_Guide.md): App Store management
- [Architecture Overview](Architecture_Overview.md): System design
- [Network Configuration](Network_Configuration.md): Flux overlay setup
