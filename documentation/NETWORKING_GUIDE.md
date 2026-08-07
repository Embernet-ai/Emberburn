# Embernet Helm Chart Compliance Specification

> **This document is an executable specification.** If you are an AI agent working on a Helm chart that will be deployed via the Embernet Industrial Dashboard, follow every section in order. Each section ends with a validation step. Do not skip sections. When you are done, every validation must pass.

---

## Context: How the Dashboard Discovers and Proxies to Your App

The Embernet Industrial Dashboard is a Go binary running on `:8080` inside a K3s cluster. It provides a **"Launch UI"** button on every deployed app card. When clicked:

```
Browser → Dashboard /api/proxy?target=http://<PodIP>:<ContainerPort> → Your App's Pod
```

The dashboard's Go reverse proxy (`httputil.ReverseProxy`) connects to your pod's **internal cluster IP** on the **first declared container port**. It does NOT use Ingress, Services-of-type-LoadBalancer, or NodePort to reach your app. It goes **directly to the pod IP**.

However, the dashboard discovers the **Service name** for Rancher-mode URLs using:
```go
svcName := pod.Labels["app"]
```

And it detects whether your app has a GUI by checking:
```go
for _, port := range container.Ports {
    if port.ContainerPort > 0 {
        hasGUI = true
        guiPort = port.ContainerPort
        break
    }
}
```

**If your pod has no `containerPort` declared, there will be no "Launch UI" button. If your pod has no `app` label matching a Service name, Rancher-mode URLs will break.**

Your app does NOT need its own Ingress, OAuth2 Proxy, or TLS configuration. The dashboard handles all of that. Your app just needs to serve HTTP on a declared port.

---

## 1. MANDATORY: `_helpers.tpl`: Template Helpers

Your chart **must** have a `templates/_helpers.tpl` with at minimum these defines. If your chart already has helpers, verify they produce equivalent output. If they don't, replace them.

The placeholder `CHARTNAME` below must be replaced with your actual chart name (e.g., `emberburn`, `nodered`, `ignition`).

```yaml
{{/*
Expand the name of the chart.
*/}}
{{- define "CHARTNAME.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
*/}}
{{- define "CHARTNAME.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart label value.
*/}}
{{- define "CHARTNAME.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels — applied to ALL resources.
*/}}
{{- define "CHARTNAME.labels" -}}
helm.sh/chart: {{ include "CHARTNAME.chart" . }}
{{ include "CHARTNAME.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels — used in Deployment.spec.selector.matchLabels AND Service.spec.selector.
The `app:` label MUST equal the fullname so the dashboard can match pods to services.
*/}}
{{- define "CHARTNAME.selectorLabels" -}}
app.kubernetes.io/name: {{ include "CHARTNAME.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app: {{ include "CHARTNAME.fullname" . }}
{{- end }}
```

**Action:** Open your `templates/_helpers.tpl`. If these defines don't exist or differ, add/replace them. Replace every occurrence of `CHARTNAME` with your chart's actual name (the `name:` field from `Chart.yaml`).

**Validation:** Run `helm template test-release ./your-chart` and confirm:
- Every resource's `metadata.name` equals `test-release-CHARTNAME` (or just `test-release` if the release name contains the chart name)
- Every resource has labels `app.kubernetes.io/managed-by: Helm` and `app: test-release-CHARTNAME`

---

## 2. MANDATORY: `templates/deployment.yaml`: Pod Spec

Your Deployment template must satisfy these exact requirements:

### 2a. Resource Naming

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "CHARTNAME.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "CHARTNAME.labels" . | nindent 4 }}
```

**`metadata.name` must use the fullname helper. `metadata.namespace` must use `{{ .Release.Namespace }}`. NEVER hardcode either.**

### 2b. Selector Labels

```yaml
spec:
  replicas: {{ .Values.replicaCount | default 1 }}
  selector:
    matchLabels:
      {{- include "CHARTNAME.selectorLabels" . | nindent 6 }}
```

### 2c. Pod Labels: Including Embernet Discovery Labels

```yaml
  template:
    metadata:
      labels:
        {{- include "CHARTNAME.selectorLabels" . | nindent 8 }}
        embernet.io/store-app: "true"
        embernet.io/app-name: {{ .Chart.Name | quote }}
```

The `embernet.io/store-app: "true"` label is **required**. Without it, the dashboard will not show your app to Operator or Engineer roles. The `embernet.io/app-name` label provides the display name on the dashboard card.

### 2d. Container Ports: CRITICAL

```yaml
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy | default "IfNotPresent" }}
          ports:
            - name: http
              containerPort: {{ .Values.service.port }}
              protocol: TCP
```

**You MUST declare at least one `containerPort`.** The dashboard iterates `pod.Spec.Containers[].Ports` to detect if your app has a GUI. If `ports:` is missing or empty, your app card will have **no "Launch UI" button**.

> [!CAUTION]
> **The FIRST port listed becomes the "Launch UI" proxy target.** For multi-port apps (e.g., OPC UA + Web UI + Prometheus), the web UI / HTTP port **MUST be listed first**. If a non-HTTP port (like OPC UA binary on 4840) is first, the dashboard will try to reverse-proxy to a binary protocol and fail with `dial tcp: connection refused` or garbage responses.

**Correct order for multi-port apps:**
```yaml
          ports:
            # Web UI MUST be first — dashboard picks this for "Launch UI"
            - name: http
              containerPort: 5000
              protocol: TCP
            # Industrial protocol ports listed after
            - name: opcua
              containerPort: 4840
              protocol: TCP
            - name: prometheus
              containerPort: 8000
              protocol: TCP
```

### 2e. Full Deployment Template (Copy-Paste Starting Point)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "CHARTNAME.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "CHARTNAME.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount | default 1 }}
  selector:
    matchLabels:
      {{- include "CHARTNAME.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "CHARTNAME.selectorLabels" . | nindent 8 }}
        embernet.io/store-app: "true"
        embernet.io/app-name: {{ .Chart.Name | quote }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy | default "IfNotPresent" }}
          ports:
            - name: http
              containerPort: {{ .Values.service.port }}
              protocol: TCP
          {{- with .Values.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
```

**Action:** Compare your existing `templates/deployment.yaml` against this. Fix any deviations.

**Validation:**
```bash
helm template test-release ./your-chart | grep -A 5 "embernet.io"
# Must show: embernet.io/store-app: "true" and embernet.io/app-name: "yourchartname"

helm template test-release ./your-chart | grep "containerPort"
# Must show at least one containerPort with a numeric value
```

---

## 3. MANDATORY: `templates/service.yaml`

The dashboard resolves launch URLs using `pod.Labels["app"]` as the service name. Your Service must have the same name as the pod's `app` label (both come from the fullname helper, so this works automatically if you follow this spec).

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "CHARTNAME.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "CHARTNAME.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type | default "ClusterIP" }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    {{- include "CHARTNAME.selectorLabels" . | nindent 4 }}
```

**Key rules:**
- `metadata.name` must use the fullname helper (same as the Deployment)
- `spec.selector` must use the selectorLabels helper (same as Deployment `matchLabels`)
- `type` should default to `ClusterIP`. Your app does NOT need NodePort or LoadBalancer for the dashboard proxy to work.
- The `targetPort: http` must match the `name: http` on the container port in the Deployment

**Action:** Verify or create `templates/service.yaml` matching this template.

**Validation:**
```bash
helm template test-release ./your-chart | grep -B2 -A10 "kind: Service"
# Confirm: name matches deployment name, selector matches deployment selector labels
```

---

## 4. MANDATORY: Delete `templates/namespace.yaml`

**Search your chart's `templates/` directory for any file that creates a `Namespace` resource.**

```bash
grep -rn "kind: Namespace" templates/
```

If found: **DELETE THAT FILE.** Also remove any `namespace.create` logic from `values.yaml`.

### Why

Helm 3.2+ requires ownership labels (`app.kubernetes.io/managed-by: Helm`, `meta.helm.sh/release-name`) on every resource it manages. If your chart creates a Namespace and that namespace already exists (from a previous install, `kubectl create ns`, or K3s auto-creation), Helm will refuse to install with this error:

```
Error: INSTALLATION FAILED: Unable to continue with install: Namespace "yourns" 
in namespace "" exists and cannot be imported into the current release: invalid 
ownership metadata; label validation error: missing key "app.kubernetes.io/managed-by"
```

The correct approach is `helm install ... --create-namespace`. Helm handles namespace creation externally, not as a chart resource.

**Action:**
1. Run `grep -rn "kind: Namespace" templates/` in your chart directory
2. If any file is found, delete it: `rm templates/namespace.yaml` (or whatever filename)
3. If `values.yaml` has a `namespace.create` field, set it to `false` or remove the block entirely
4. Update your install documentation to include `--create-namespace`

**Validation:**
```bash
helm template test-release ./your-chart | grep "kind: Namespace"
# Must return NOTHING. If it outputs a Namespace resource, you still have the problem.
```

---

## 5. MANDATORY: No Hardcoded Names or Namespaces

Search your entire `templates/` directory for hardcoded resource names and namespaces:

```bash
# Check for hardcoded namespace values (not using .Release.Namespace)
grep -rn "namespace:" templates/ | grep -v "Release.Namespace" | grep -v "#"

# Check for hardcoded metadata.name values (not using include helper)
grep -rn "name:" templates/ | grep -v "include" | grep -v "Chart.Name" | grep -v "#" | grep -v "port" | grep -v "container"
```

Every `metadata.namespace` must be `{{ .Release.Namespace }}`.
Every `metadata.name` must use `{{ include "CHARTNAME.fullname" . }}` (or a derivative like appending `-config`).

**Why:** Hardcoded names prevent multi-instance deployment. If two Helm releases in the same namespace both create a Deployment named `emberburn`, the second install fails. Using the fullname helper makes names unique per release (e.g., `release1-emberburn`, `release2-emberburn`).

**Action:** Fix every hardcoded name/namespace found by the grep commands above.

**Validation:**
```bash
# Install two releases in the same namespace — both must succeed
helm template release-a ./your-chart | grep "name:" | head -20
helm template release-b ./your-chart | grep "name:" | head -20
# Every name in release-a must differ from release-b (prefixed with release name)
```

---

## 6. RECOMMENDED: `values.yaml` Defaults

Your `values.yaml` should have at minimum these fields (used by the templates above):

```yaml
replicaCount: 1

image:
  repository: ghcr.io/your-org/your-app
  tag: ""  # Defaults to .Chart.AppVersion
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 3000    # ← Set this to whatever port your app listens on

ingress:
  enabled: false
  host: ""

resources: {}

nameOverride: ""
fullnameOverride: ""
```

**Key points:**
- `service.port` must match the port your app actually listens on inside the container
- `ingress.enabled` should default to `false`: apps accessed through the dashboard proxy don't need their own Ingress
- `image.tag` can default to empty and fall back to `Chart.AppVersion`

**Action:** Verify your `values.yaml` has these fields. Add any that are missing.

---

## 7. OPTIONAL: `templates/ingress.yaml` (Only If Needed)

Most apps do NOT need this. The dashboard's `/api/proxy` handles routing. Only create an Ingress if your app needs a **separate public URL** (e.g., a webhook endpoint that external systems call, or an OPC UA discovery endpoint).

If needed:

```yaml
{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "CHARTNAME.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "CHARTNAME.labels" . | nindent 4 }}
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - {{ .Values.ingress.host | quote }}
      secretName: {{ include "CHARTNAME.fullname" . }}-tls
  rules:
    - host: {{ .Values.ingress.host | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ include "CHARTNAME.fullname" . }}
                port:
                  number: {{ .Values.service.port }}
{{- end }}
```

**Rules:**
- Guarded by `{{- if .Values.ingress.enabled -}}`: off by default
- `ingressClassName: traefik` (K3s built-in)
- TLS via cert-manager with `letsencrypt-prod` ClusterIssuer
- Hostname must come from `values.yaml`, never hardcoded (prevents multi-instance conflicts)

---

## 8. REFERENCE: Things Your Chart Must NOT Do

| Anti-Pattern | Why It Breaks | Fix |
|---|---|---|
| `templates/namespace.yaml` with `kind: Namespace` | Causes ownership error on reinstall or if namespace pre-exists | Delete the file, use `--create-namespace` |
| `metadata.name: my-app-deployment` (hardcoded) | Second install in same namespace fails with conflict | Use `{{ include "CHARTNAME.fullname" . }}` |
| `metadata.namespace: my-namespace` (hardcoded) | Can't install into a different namespace | Use `{{ .Release.Namespace }}` |
| `selector.matchLabels.app: my-app` (hardcoded) | Multi-instance pods all match each other's selectors | Use `{{ include "CHARTNAME.selectorLabels" . }}` |
| No `ports:` in container spec | Dashboard shows no "Launch UI" button | Add `containerPort` matching your app's HTTP port |
| Missing `embernet.io/store-app: "true"` label on pod | Operators and Engineers can't see the app | Add the label to `template.metadata.labels` |
| `service.type: LoadBalancer` as default | Wastes external IPs; dashboard proxy doesn't need it | Default to `ClusterIP` |
| Own OAuth2 Proxy or auth sidecar | Redundant; dashboard already authenticates all proxy requests | Remove it; rely on dashboard auth |
| HTTPS/TLS on the container itself | Dashboard proxy connects via plain HTTP to pod IPs | Serve HTTP internally; TLS terminates at Traefik |

---

## 9. REFERENCE: Install Commands

```bash
# Standard install (accessed through dashboard "Launch UI")
helm install <release-name> ./your-chart -n <namespace> --create-namespace

# Multi-instance of same app in same namespace
helm install instance-a ./your-chart -n my-namespace --create-namespace
helm install instance-b ./your-chart -n my-namespace

# Multi-instance across namespaces
helm install my-app ./your-chart -n client-a --create-namespace
helm install my-app ./your-chart -n client-b --create-namespace

# If you hit the namespace ownership error on an existing namespace
kubectl label namespace <ns> app.kubernetes.io/managed-by=Helm
kubectl annotate namespace <ns> meta.helm.sh/release-name=<release> meta.helm.sh/release-namespace=<ns>
# Then retry the helm install
```

---

## 10. FINAL VALIDATION CHECKLIST

Run all of these. Every check must pass before the chart is compliant.

```bash
# 1. Template renders without errors
helm template test-release ./your-chart --debug

# 2. Lint passes clean
helm lint ./your-chart
# Expected: "0 chart(s) failed"

# 3. No Namespace resource in output
helm template test-release ./your-chart | grep "kind: Namespace"
# Expected: NO OUTPUT

# 4. All resources use dynamic names (not hardcoded)
helm template test-release ./your-chart | grep "name: test-release"
# Expected: Every resource name starts with "test-release"

# 5. All resources use release namespace
helm template test-release ./your-chart | grep "namespace:"
# Expected: Every namespace line should NOT be a hardcoded value
# (helm template doesn't resolve .Release.Namespace, so look for the raw template string or "default")

# 6. Embernet discovery labels present on pod
helm template test-release ./your-chart | grep "embernet.io"
# Expected: embernet.io/store-app: "true" and embernet.io/app-name

# 7. Container port declared
helm template test-release ./your-chart | grep "containerPort"
# Expected: At least one numeric containerPort value

# 8. Service exists and matches deployment selector
helm template test-release ./your-chart | grep -A 20 "kind: Service"
# Expected: Service with selector labels matching the Deployment's matchLabels

# 9. Multi-instance names are unique
diff <(helm template rel-a ./your-chart | grep "name:") <(helm template rel-b ./your-chart | grep "name:")
# Expected: Every line differs (rel-a- prefix vs rel-b- prefix)
```

If all 9 checks pass, your chart is compliant with the Embernet Industrial Dashboard and "Launch UI" will work.

---

## 8. Troubleshooting

### "Launch UI" shows "Not Found" or "connection refused"

**Symptom:** Clicking "Launch UI" on a deployed app card opens an iframe that shows a Flask 404, a binary protocol error, or `connection refused`.

**Cause:** The dashboard picks the **first `containerPort`** in the pod spec for the reverse proxy target. If a non-HTTP port (e.g., OPC UA on 4840) is listed before the web UI port, the dashboard proxies to the wrong service.

**Fix:** Reorder `ports:` in your `deployment.yaml` so the **web UI / HTTP port is listed first**:

```yaml
        ports:
          # Web UI MUST be first — dashboard picks this for "Launch UI"
          - name: http
            containerPort: 5000
            protocol: TCP
          # Industrial protocol ports listed after
          - name: opcua
            containerPort: 4840
            protocol: TCP
```

---

### CrashLoopBackOff: liveness probe on wrong port

**Symptom:** Pod starts, runs briefly, then enters `CrashLoopBackOff`. Events show `Liveness probe failed: dial tcp <IP>:<PORT>: connect: connection refused`.

**Cause:** Liveness/readiness probes are targeting a port that is slow to bind (e.g., OPC UA 4840 takes time to load tags and initialize the protocol handler). K8s kills the container before the port is ready.

**Fix:** Point probes at your **fastest-starting port** (usually the web UI / Flask / HTTP server):

```yaml
  livenessProbe:
    enabled: true
    tcpSocket:
      port: 5000        # Flask starts instantly — don't probe slow ports
    initialDelaySeconds: 45
    periodSeconds: 15
    failureThreshold: 6  # Give extra startup headroom

  readinessProbe:
    enabled: true
    tcpSocket:
      port: 5000
    initialDelaySeconds: 15
    periodSeconds: 10
    failureThreshold: 3
```

---

### Server dies immediately after startup

**Symptom:** All ports bind successfully during startup, but within seconds everything stops listening. Probes fail, pod crashes. Logs may show `Server stopped. Goodbye!` immediately after `Publishers started`.

**Cause:** Shutdown logic (e.g., `publisher_manager.stop_all()`, `server.stop()`) is accidentally placed in a method called during initialization instead of the `shutdown()` method. The server starts, initializes, then immediately shuts itself down.

**Diagnostic:**
```bash
kubectl logs <pod-name> | head -50
# Look for "Server stopped" appearing right after "Server started"
```

**Fix:** Ensure all `stop()` / `stop_all()` calls are **only** inside the `shutdown()` method or signal handler, never in `__init__()`, `setup()`, or callback registration methods.

---

### Invalid Kubernetes label values

**Symptom:** `helm install` fails with `invalid label value` or pod fails to schedule.

**Cause:** K8s label values must match the regex `^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$` (max 63 chars). Emojis, spaces, and special characters are **not valid**.

**Fix:**
```yaml
# ❌ Invalid
embernet.io/app-icon: "🔥"

# ✅ Valid
embernet.io/app-icon: "fire"
```

---

### App works locally but not through dashboard proxy

**Static assets (CSS/JS/images) broken in iframe:**

When the dashboard proxies to your app via `/api/proxy?target=http://PodIP:PORT`, Flask templates generate absolute paths like `/static/web/css/style.css`. The browser resolves these against the dashboard domain (`https://industrial.embernet.ai/static/web/...`), not your app. Result: no CSS, no JS, no images.

**Fix:** Add a Flask `after_request` middleware that detects the proxy and rewrites all absolute paths to route back through it:

```python
@app.after_request
def rewrite_proxy_urls(response):
    # Only rewrite when behind a reverse proxy (Go's httputil sets X-Forwarded-For)
    if not request.headers.get('X-Forwarded-For'):
        return response
    if not response.content_type or 'text/html' not in response.content_type:
        return response
    
    # Build proxy prefix using our own host (Pod IP:port)
    proxy_base = f'/api/proxy?target=http://{request.host}'
    
    data = response.get_data(as_text=True)
    data = data.replace('href="/', f'href="{proxy_base}/')
    data = data.replace("href='/", f"href='{proxy_base}/")
    data = data.replace('src="/', f'src="{proxy_base}/')
    data = data.replace("src='/", f"src='{proxy_base}/")
    data = data.replace("fetch('/", f"fetch('{proxy_base}/")
    data = data.replace('fetch("/', f'fetch("{proxy_base}/')
    response.set_data(data)
    return response
```

> [!IMPORTANT]
> This pattern applies to **any** web app served through the Embernet Dashboard proxy, not just Flask. Node.js, Go, etc. need equivalent response rewriting if they serve HTML with absolute asset paths.

---

**Diagnostic steps:**

```bash
# 1. Get the pod IP
kubectl get pod <pod> -o wide
# Look for IP in 10.42.x.x range (K3s pod network)

# 2. Test from inside the cluster (exec into any pod)
kubectl exec -it <any-running-pod> -- curl -s http://<POD_IP>:<PORT>/
# Expected: 200 OK with HTML

# 3. Check the pod has the right labels
kubectl get pod <pod> --show-labels
# Must have: embernet.io/store-app=true, app=<release-fullname>

# 4. Check the service matches
kubectl get svc -l app=<release-fullname>
# Must exist with matching selector

# 5. Check container ports are declared
kubectl get pod <pod> -o jsonpath='{.spec.containers[*].ports[*].containerPort}'
# Must show at least one port, HTTP port should be first
```
