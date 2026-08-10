# Embernet Helm Chart Compatibility Requirements

> ## ⚠️ PARTIALLY SUPERSEDED: verify against the source-derived contract
>
> The **EmberNET App Store Chart Contract** (generated 2026-07-19 against dashboard
> v4.1.34, derived from the dashboard Go source rather than from documentation) is
> authoritative where the two disagree. Known incorrect claims in this document:
>
> | This document says | The code actually does |
> |---|---|
> | `embernet.ai/app-icon` is a **label**, resolved from `pod.Labels` (§2, §7, §11) | It is an **annotation**, read at `client.go:307-309` from **both** pod and Service annotations. Service-only leaves node cards showing a generic glyph |
> | Icon value is an "emoji or icon identifier" | Annotation values have no charset restriction, so a URL or `data:` URI is legal, and necessary, since a label value cannot contain `/` or `:` |
> | `embernet.ai/tenant` is not listed as required | It is **mandatory**. Injected via `.Values.tenantLabels`; a chart that drops it has its Services filtered out of every tenant-scoped view (`services.go:226`) and POD SHELL returns 403 (`shell.go:602-615`) |
> | `gui-type: "web+shell"` is a valid value | Rejected by kube-apiserver, `+` is not in the K8s label-value character class |
>
> Following this document's icon guidance is what produced the broken app tile
> fixed in EmberBurn v4.1.9. Treat the sections below as historical context and
> confirm anything load-bearing against the contract before relying on it.

> **What every Helm chart published to the Embernet ecosystem must include to work with the Industrial Dashboard.**

This document specifies the labels, annotations, values, and structural requirements that **all application Helm charts** (Node-RED, Grafana, PostgreSQL, Mosquitto, etc.) must follow to be fully compatible with the Embernet Industrial Dashboard's discovery engine, App Store, shell access, and digital twin mapping.

---

## Table of Contents

1. [How the Dashboard Discovers Apps](#1-how-the-dashboard-discovers-apps)
2. [Required Labels](#2-required-labels)
3. [Required Values (values.yaml)](#3-required-values-valuesyaml)
4. [Recommended Labels & Annotations](#4-recommended-labels--annotations)
5. [Auto-Applied Labels (Store Deploy)](#5-auto-applied-labels-store-deploy)
6. [GUI Type Behavior Matrix](#6-gui-type-behavior-matrix)
7. [Label Precedence & Fallback Chain](#7-label-precedence--fallback-chain)
8. [Shell Access Requirements](#8-shell-access-requirements)
9. [HelmChart CRD Format](#9-helmchart-crd-format)
10. [Chart Structure Checklist](#10-chart-structure-checklist)
11. [Example: Minimal Compatible Chart](#11-example-minimal-compatible-chart)
12. [Example: Full-Featured Chart](#12-example-full-featured-chart)
13. [Common Mistakes](#13-common-mistakes)

---

## 1. How the Dashboard Discovers Apps

The dashboard backend (`internal/k8s/client.go`) uses a single Kubernetes label selector to find every app across the cluster:

```go
LabelSelector: "embernet.ai/store-app=true"
```

**If a pod does not have this label, it is invisible to the dashboard.** No exceptions.

Once a pod is discovered, the dashboard reads additional labels and annotations to determine:

| What | Where it looks |
|------|---------------|
| App name | `embernet.ai/app-name` label → `app` label → pod name |
| Display name | `embernet.ai/display-name` annotation → app name fallback |
| Release name | `app.kubernetes.io/instance` label → `app` label |
| GUI port | `embernet.ai/gui-port` label → annotation → container port scan |
| GUI type | `embernet.ai/gui-type` label → annotation → auto-detect |
| Icon | `embernet.ai/app-icon` label → store catalog cross-reference |
| Device | `embernet.ai/device` label → node name fallback |

---

## 2. Required Labels

These labels **must** be present on every pod created by the chart's Deployment/StatefulSet/DaemonSet template.

### 2.1 `embernet.ai/store-app: "true"`

**Purpose:** Visibility gate. Without this label, the pod does not exist to the dashboard.

```yaml
# templates/deployment.yaml
spec:
  template:
    metadata:
      labels:
        embernet.ai/store-app: "true"
```

### 2.2 `embernet.ai/gui-port: "<port>"`

**Purpose:** Tells the dashboard which container port serves the web UI.

- Must be a string (K8s labels are always strings): `"1880"`, `"3000"`, `"9090"`
- If the chart has no web UI (e.g., PostgreSQL, Mosquitto), use `embernet.ai/gui-type: "shell"` or `"none"` instead and omit this label
- **Fallback behavior:** If omitted, the dashboard scans all container ports and picks the first one, this is unreliable for multi-port pods

```yaml
labels:
  embernet.ai/gui-port: "1880"    # Node-RED
  embernet.ai/gui-port: "3000"    # Grafana
  embernet.ai/gui-port: "9090"    # Prometheus
```

### 2.3 `embernet.ai/gui-type: "<type>"`

**Purpose:** Controls how the dashboard renders the app card's action buttons.

| Value | Behavior |
|-------|----------|
| `web` | Shows "Open" button → launches iframe/proxy to the GUI port |
| `shell` | Shows "Terminal" button → opens xterm.js WebSocket shell into the pod |
| `none` | Shows no action buttons → informational card only |

- If omitted and a GUI port is found, defaults to `"web"`
- If omitted and no GUI port is found, defaults to `"none"`

```yaml
labels:
  embernet.ai/gui-type: "web"     # Node-RED, Grafana
  embernet.ai/gui-type: "shell"   # PostgreSQL (psql shell)
  embernet.ai/gui-type: "none"    # Mosquitto broker (no interactive UI)
```

### 2.4 `app` (standard Kubernetes label)

**Purpose:** Used as the Kubernetes Service selector and as a fallback for app name resolution and Rancher proxy URL construction.

```yaml
labels:
  app: node-red
```

- The Service in the chart **must** select on this same label
- The Rancher K8s API proxy URL is built as: `<RANCHER>/k8s/clusters/local/api/v1/namespaces/<ns>/services/http:<app-label>:<port>/proxy/`
- If this label doesn't match the Service name, the "Open" button will 404

---

## 3. Required Values (values.yaml)

### 3.1 `nodeSelector` Support

The dashboard deploys apps to specific nodes via `valuesContent` in the HelmChart CRD:

```yaml
nodeSelector:
  kubernetes.io/hostname: <target-node>
```

**Your chart's Deployment template must honor `nodeSelector`:**

```yaml
# templates/deployment.yaml
spec:
  template:
    spec:
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
```

**Your `values.yaml` must define it as an empty default:**

```yaml
# values.yaml
nodeSelector: {}
```

> **If your chart ignores nodeSelector, apps will schedule on random nodes instead of the node the operator selected in the dashboard.**

### 3.2 `imagePullSecrets` Support (if using private registry)

If the chart pulls from a private container registry (e.g., GitHub Container Registry), the template must support `imagePullSecrets`:

```yaml
# values.yaml
imagePullSecrets:
  - name: ghcr-pull-secret

# templates/deployment.yaml
spec:
  template:
    spec:
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
```

### 3.3 Service Definition

Every chart with `gui-type: web` **must** include a Service that:

1. Selects on the `app` label
2. Exposes the same port declared in `embernet.ai/gui-port`
3. Uses the release name or `app` label as the Service name

```yaml
# templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "mychart.fullname" . }}
  labels:
    app: {{ .Values.appLabel }}
spec:
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.port }}
  selector:
    app: {{ .Values.appLabel }}
```

---

## 4. Recommended Labels & Annotations

These are optional but strongly recommended for production deployments.

### 4.1 `embernet.ai/display-name` (Annotation)

**Purpose:** Human-readable name shown in the dashboard UI. Supports multi-instance disambiguation.

- Use as an **annotation** (not a label): annotations have no 63-character limit
- Example: `"Plant Floor / Node-RED Production"` or `"Building-A PostgreSQL"`

```yaml
annotations:
  embernet.ai/display-name: "Plant Floor / Node-RED Production"
```

- **Fallback:** If not set, the dashboard uses `embernet.ai/app-name` label → `app` label → pod name

### 4.2 `embernet.ai/device` (Label)

**Purpose:** Maps the app to a digital twin device in the dashboard's device view.

```yaml
labels:
  embernet.ai/device: "plc-conveyor-01"
```

- **Fallback:** If not set, defaults to the Kubernetes node name (`pod.Spec.NodeName`)
- Useful when multiple apps on the same node represent different physical devices

### 4.3 `app.kubernetes.io/instance` (Label)

**Purpose:** Standard Kubernetes label identifying the Helm release. The dashboard uses this as a unique identifier for multi-instance apps.

```yaml
labels:
  app.kubernetes.io/instance: {{ .Release.Name }}
```

- **Fallback:** If not set, falls back to `app` label
- Helm charts using the standard `helm create` scaffold include this automatically

---

## 5. Auto-Applied Labels (Store Deploy)

When the dashboard's App Store deploys a chart, it creates a HelmChart CRD with these labels on the **CRD object itself** (not the pod). The chart does NOT need to set these, they are injected by the deploy pipeline:

| Label | Source | Purpose |
|-------|--------|---------|
| `embernet.ai/store-app: "true"` | Hardcoded | CRD-level visibility flag |
| `embernet.ai/app-id` | Store catalog | Unique app identifier |
| `embernet.ai/app-name` | Store catalog | Human-readable chart name |
| `embernet.ai/app-icon` | Store catalog | Emoji or icon identifier |

> **Important:** These CRD labels do not propagate to pods automatically. The chart's pod template **must still include `embernet.ai/store-app: "true"`** on its own pods for dashboard discovery to work.

---

## 6. GUI Type Behavior Matrix

| `gui-type` | `gui-port` set? | Dashboard renders | Shell button | Open button |
|------------|-----------------|-------------------|-------------|-------------|
| `web` | Yes | App card with iframe proxy | Yes | Yes |
| `web` | No (falls back to port scan) | App card, unreliable proxy | Yes | Yes (may fail) |
| `shell` | Ignored | App card, terminal only | Yes | No |
| `none` | Ignored | Info card, no actions | No | No |
| *(omitted)* | Yes (label/annotation/scan) | Treated as `web` | Yes | Yes |
| *(omitted)* | No ports found | Treated as `none` | No | No |

---

## 7. Label Precedence & Fallback Chain

The dashboard reads metadata in this exact order. First match wins.

### App Name
1. `pod.Labels["embernet.ai/app-name"]`
2. `pod.Labels["app"]`
3. `pod.Name`

### Display Name
1. `pod.Annotations["embernet.ai/display-name"]`
2. App Name (from above chain)

### Release Name
1. `pod.Labels["app.kubernetes.io/instance"]`
2. `pod.Labels["app"]`

### GUI Port
1. `pod.Labels["embernet.ai/gui-port"]` (string → int)
2. `pod.Annotations["embernet.ai/gui-port"]` (string → int)
3. First `containerPort` found in pod spec (unreliable)

### GUI Type
1. `pod.Labels["embernet.ai/gui-type"]`
2. `pod.Annotations["embernet.ai/gui-type"]`
3. `"web"` if a GUI port was found
4. `"none"` if no GUI port exists

### Icon
1. `pod.Labels["embernet.ai/app-icon"]` (URL-decoded if encoded)
2. Store catalog cross-reference by app name (case-insensitive)
3. Store catalog cross-reference by `app` label (case-insensitive)
4. `"default"` (frontend renders a generic icon)

### Device
1. `pod.Labels["embernet.ai/device"]`
2. `pod.Spec.NodeName` (auto-maps to the hosting K8s node)

---

## 8. Shell Access Requirements

The dashboard provides WebSocket-based terminal access (`xterm.js`) into pods. Security rules:

1. **`embernet.ai/store-app: "true"` is required**: pods in system namespaces (`kube-system`, `cattle-system`, `longhorn-system`, `fireball-system`, `cert-manager`) are blocked from shell access unless they carry this label
2. The shell connects to the pod's **first container** by default
3. Read-only shells are enforced for Operator role users
4. The pod must have a shell binary available (`/bin/sh` or `/bin/bash`)

> **For `gui-type: shell` apps** (e.g., PostgreSQL), the Terminal button is the primary interaction method. Ensure the container image includes the CLI tools users would need (`psql`, `redis-cli`, `mosquitto_sub`, etc.).

---

## 9. HelmChart CRD Format

The dashboard creates K3s HelmChart CRDs (not Helm CLI). Charts must be compatible with K3s Helm controller.

```yaml
apiVersion: helm.cattle.io/v1
kind: HelmChart
metadata:
  name: <app-id>-<node-name>    # e.g., "node-red-worker01"
  namespace: default
  labels:
    embernet.ai/store-app: "true"
    embernet.ai/app-id: "node-red"
    embernet.ai/app-name: "Node-RED"
    embernet.ai/app-icon: "🔴"
spec:
  chart: node-red              # Chart name in the repo
  repo: https://helm.example.com/charts   # Helm repo URL
  version: "1.0.0"
  valuesContent: |
    nodeSelector:
      kubernetes.io/hostname: worker01
```

### Compatibility notes:
- Chart must be a standard Helm 3 chart (Chart.yaml `apiVersion: v2`)
- The K3s Helm controller installs into namespace `default` unless overridden
- `valuesContent` is YAML merged with the chart's `values.yaml`: your chart must not break when extra keys are injected

---

## 10. Chart Structure Checklist

Use this checklist when packaging any chart for the Embernet App Store.

### Must Have
- [ ] Pod template has `embernet.ai/store-app: "true"` label
- [ ] Pod template has `embernet.ai/gui-port: "<port>"` label (or `gui-type: shell/none` if no web UI)
- [ ] Pod template has `embernet.ai/gui-type: "web|shell|none"` label
- [ ] Pod template has `app: <chart-name>` label
- [ ] Deployment template supports `nodeSelector` from values
- [ ] `values.yaml` has `nodeSelector: {}` default
- [ ] Service selects on `app` label and exposes the GUI port (if `gui-type: web`)
- [ ] Chart.yaml has `apiVersion: v2` (Helm 3)
- [ ] Chart works when `valuesContent` injects unknown keys (no strict schema)

### Should Have
- [ ] Pod template has `app.kubernetes.io/instance: {{ .Release.Name }}`
- [ ] Pod template has `embernet.ai/display-name` annotation (via values)
- [ ] Pod template has `embernet.ai/device` label (via values)
- [ ] `values.yaml` has `imagePullSecrets` support
- [ ] Container image includes shell binary (`/bin/sh`)
- [ ] Icon defined in Chart.yaml `icon:` field (used by store catalog)
- [ ] README.md with Embernet-specific configuration section

### Nice to Have
- [ ] `embernet.ai/app-name` label on pod (in addition to CRD-level)
- [ ] Resource requests and limits defined in values.yaml
- [ ] Health check probes (liveness/readiness)
- [ ] PersistentVolumeClaim for stateful apps
- [ ] `NOTES.txt` with post-install instructions

---

## 11. Example: Minimal Compatible Chart

A bare-minimum chart that the dashboard can discover and proxy.

### `values.yaml`
```yaml
image:
  repository: nodered/node-red
  tag: "3.1"
  pullPolicy: IfNotPresent

service:
  port: 1880

nodeSelector: {}
```

### `templates/deployment.yaml`
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {{ .Chart.Name }}
      app.kubernetes.io/instance: {{ .Release.Name }}
  template:
    metadata:
      labels:
        app: {{ .Chart.Name }}
        app.kubernetes.io/instance: {{ .Release.Name }}
        embernet.ai/store-app: "true"
        embernet.ai/gui-port: "{{ .Values.service.port }}"
        embernet.ai/gui-type: "web"
    spec:
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          ports:
            - containerPort: {{ .Values.service.port }}
```

### `templates/service.yaml`
```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}
spec:
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.service.port }}
  selector:
    app: {{ .Chart.Name }}
    app.kubernetes.io/instance: {{ .Release.Name }}
```

---

## 12. Example: Full-Featured Chart

A production-ready chart using all available Embernet labels.

### `values.yaml`
```yaml
image:
  repository: nodered/node-red
  tag: "3.1"
  pullPolicy: IfNotPresent

imagePullSecrets: []

service:
  port: 1880

embernet:
  displayName: ""          # Override: "Plant Floor / Node-RED Production"
  device: ""               # Override: "plc-conveyor-01"
  guiType: "web"           # web | shell | none

nodeSelector: {}

resources:
  requests:
    cpu: 50m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

persistence:
  enabled: true
  size: 1Gi
```

### `templates/deployment.yaml`
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
  labels:
    app: {{ .Chart.Name }}
    app.kubernetes.io/instance: {{ .Release.Name }}
    app.kubernetes.io/managed-by: {{ .Release.Service }}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {{ .Chart.Name }}
      app.kubernetes.io/instance: {{ .Release.Name }}
  template:
    metadata:
      labels:
        app: {{ .Chart.Name }}
        app.kubernetes.io/instance: {{ .Release.Name }}
        embernet.ai/store-app: "true"
        embernet.ai/gui-port: "{{ .Values.service.port }}"
        embernet.ai/gui-type: {{ .Values.embernet.guiType | quote }}
        {{- if .Values.embernet.device }}
        embernet.ai/device: {{ .Values.embernet.device | quote }}
        {{- end }}
      annotations:
        {{- if .Values.embernet.displayName }}
        embernet.ai/display-name: {{ .Values.embernet.displayName | quote }}
        {{- end }}
    spec:
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.service.port }}
              protocol: TCP
          livenessProbe:
            httpGet:
              path: /
              port: {{ .Values.service.port }}
            initialDelaySeconds: 30
          readinessProbe:
            httpGet:
              path: /
              port: {{ .Values.service.port }}
            initialDelaySeconds: 10
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          {{- if .Values.persistence.enabled }}
          volumeMounts:
            - name: data
              mountPath: /data
          {{- end }}
      {{- if .Values.persistence.enabled }}
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: {{ .Release.Name }}-data
      {{- end }}
```

---

## 13. Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Missing `embernet.ai/store-app: "true"` on pods | App deploys but doesn't appear in dashboard | Add the label to pod template |
| `gui-port` on Deployment metadata instead of pod template | Dashboard can't read it from the pod | Move to `spec.template.metadata.labels` |
| Service name doesn't match `app` label | "Open" button returns 404 via Rancher proxy | Ensure Service name = `app` label value or use `{{ .Release.Name }}` consistently |
| No `nodeSelector` in Deployment template | App lands on random node, not the one operator selected | Add `{{- with .Values.nodeSelector }}` block |
| `gui-port` set to named port instead of number | Parse failure, falls back to port scan | Use numeric string: `"1880"` not `"http"` |
| `embernet.ai/display-name` as a label | Truncated at 63 characters | Use as annotation instead |
| `gui-type: "shell"` but no shell binary in image | Terminal opens then immediately disconnects | Ensure `/bin/sh` or `/bin/bash` exists in the image |
| Chart breaks on unknown values keys | K3s Helm controller fails during install | Don't use strict JSON schema validation on values |
| `embernet.ai/app-icon` with raw emoji in label | K8s rejects the label value | URL-encode or use store catalog icon resolution instead |
| Pod in `kube-system` namespace with store-app label | Works, but bypasses namespace security boundary | Deploy to `default` namespace |

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────┐
│              EMBERNET HELM CHART LABELS                 │
├──────────────────────────┬──────────────────────────────┤
│ REQUIRED (pod template)  │                              │
│  embernet.ai/store-app   │ "true"                       │
│  embernet.ai/gui-port    │ "1880" (or use gui-type)     │
│  embernet.ai/gui-type    │ "web" | "shell" | "none"     │
│  app                     │ "<chart-name>"               │
├──────────────────────────┼──────────────────────────────┤
│ RECOMMENDED              │                              │
│  embernet.ai/display-name│ annotation (no 63-char limit)│
│  embernet.ai/device      │ label (digital twin mapping) │
│  app.kubernetes.io/      │                              │
│    instance              │ {{ .Release.Name }}          │
├──────────────────────────┼──────────────────────────────┤
│ AUTO-APPLIED (by store)  │                              │
│  embernet.ai/app-id      │ from catalog                 │
│  embernet.ai/app-name    │ from catalog                 │
│  embernet.ai/app-icon    │ from catalog                 │
├──────────────────────────┼──────────────────────────────┤
│ REQUIRED VALUES          │                              │
│  nodeSelector: {}        │ must be in values.yaml       │
│  nodeSelector support    │ must be in deployment.yaml   │
└──────────────────────────┴──────────────────────────────┘
```
