# Emberburn Helm Chart: Embernet Alignment Phases

> A phased roadmap to bring the Emberburn Helm chart into full compliance with the **Embernet Helm Chart Compatibility Requirements** and **Helm Chart Interface Alignment Guide**.

---

## Current State Summary

The Emberburn chart (`helm/opcua-server/`) already has solid foundations, `nodeSelector` support, `app` and `app.kubernetes.io/instance` selector labels, health probes, resource presets, PVC, and a `NOTES.txt`. However, several critical gaps prevent full Embernet Dashboard integration:

| Area | Current | Required |
|------|---------|----------|
| Discovery label | `embernet.io/store-app` (wrong domain) | `embernet.ai/store-app: "true"` |
| App name label | `embernet.io/app-name` (wrong domain) | `embernet.ai/app-name` |
| App icon label | `embernet.io/app-icon` (wrong domain) | `embernet.ai/app-icon` |
| GUI port label | **Missing** | `embernet.ai/gui-port: "5000"` |
| GUI type label | **Missing** | `embernet.ai/gui-type: "web"` |
| Display name annotation | **Missing** | `embernet.ai/display-name` |
| Device label | **Missing** | `embernet.ai/device` |
| `imagePullSecrets` | **Not supported** | Must be in deployment + values |
| Values schema tolerance | Unknown | Must not break on unknown keys |

---

## Phase 1: Fix Critical Discovery Labels

**Goal:** Make the chart visible to the Embernet Dashboard.

**Priority:** 🔴 Blocking, without these changes, the pod is invisible to the dashboard.

### 1.1 Fix label domain from `embernet.io` → `embernet.ai`

The pod template in `templates/deployment.yaml` currently uses the wrong domain:

```yaml
# BEFORE (wrong)
embernet.io/store-app: "true"
embernet.io/app-name: {{ .Chart.Name | quote }}
embernet.io/app-icon: "fire"

# AFTER (correct)
embernet.ai/store-app: "true"
embernet.ai/app-name: {{ .Values.embernet.appName | default .Chart.Name | quote }}
embernet.ai/app-icon: {{ .Values.embernet.appIcon | default "🔥" | quote }}
```

### 1.2 Add `embernet.ai/gui-port` label to pod template

The dashboard uses this label to know which port to proxy. Without it, the "Open" button may 404 or hit the wrong port.

```yaml
embernet.ai/gui-port: {{ .Values.emberburn.ports.webui | quote }}
```

### 1.3 Add `embernet.ai/gui-type` label to pod template

Emberburn is classified as `gui-type: web` (Flask web UI on port 5000). This label controls which action buttons appear on the dashboard card.

```yaml
embernet.ai/gui-type: {{ .Values.embernet.guiType | default "web" | quote }}
```

### Files Changed
- `templates/deployment.yaml`: pod template labels section

### Validation
```bash
helm template test ./helm/opcua-server | grep "embernet.ai"
# Should show: store-app, app-name, app-icon, gui-port, gui-type
```

---

## Phase 2: Add Embernet Values Block

**Goal:** Expose all Embernet-specific settings as configurable values so operators can customize per-deployment.

**Priority:** 🟠 High, needed for multi-instance and device-mapping scenarios.

### 2.1 Add `embernet` section to `values.yaml`

```yaml
# Embernet Dashboard integration
embernet:
  appName: ""              # Defaults to .Chart.Name ("emberburn")
  displayName: ""          # Annotation: "Plant Floor / EmberBurn Production"
  guiType: "web"           # "web" | "shell" | "web+shell" | "none"
  device: ""               # Digital twin device: "plc-conveyor-01"
  appIcon: ""              # URL-encoded emoji or catalog reference
```

### 2.2 Add `imagePullSecrets` to `values.yaml`

```yaml
imagePullSecrets: []
#  - name: ghcr-pull-secret
```

### Files Changed
- `values.yaml`: new `embernet` block + `imagePullSecrets` key

---

## Phase 3: Add Recommended Labels & Annotations to Pod Template

**Goal:** Enable display name customization, digital twin device mapping, and multi-instance disambiguation.

**Priority:** 🟡 Medium, production readiness and dashboard UX polish.

### 3.1 Add `embernet.ai/display-name` annotation (conditional)

Must be an **annotation** (not a label) to avoid the 63-character K8s label limit.

```yaml
# templates/deployment.yaml — pod template annotations
{{- if .Values.embernet.displayName }}
embernet.ai/display-name: {{ .Values.embernet.displayName | quote }}
{{- end }}
```

### 3.2 Add `embernet.ai/device` label (conditional)

```yaml
# templates/deployment.yaml — pod template labels
{{- if .Values.embernet.device }}
embernet.ai/device: {{ .Values.embernet.device | quote }}
{{- end }}
```

### 3.3 Verify `app.kubernetes.io/instance` is present

Already included via `emberburn.selectorLabels` helper → `app.kubernetes.io/instance: {{ .Release.Name }}`. **No change needed.**

### Files Changed
- `templates/deployment.yaml`: pod template labels + annotations sections

### Validation
```bash
helm template test ./helm/opcua-server \
  --set embernet.displayName="Plant Floor / EmberBurn" \
  --set embernet.device="plc-conveyor-01" \
  | grep "embernet.ai"
```

---

## Phase 4: Add `imagePullSecrets` Support

**Goal:** Allow deployment from private container registries (e.g., GHCR).

**Priority:** 🟡 Medium, required if images are pulled from a private registry.

### 4.1 Add `imagePullSecrets` block to deployment template

```yaml
# templates/deployment.yaml — pod spec
spec:
  {{- with .Values.imagePullSecrets }}
  imagePullSecrets:
    {{- toYaml . | nindent 8 }}
  {{- end }}
```

### Files Changed
- `templates/deployment.yaml`: pod spec section (before `containers:`)

### Validation
```bash
helm template test ./helm/opcua-server \
  --set 'imagePullSecrets[0].name=ghcr-pull-secret' \
  | grep -A2 imagePullSecrets
```

---

## Phase 5: Service Selector & Naming Alignment

**Goal:** Ensure the Rancher API proxy URL resolves correctly when the dashboard constructs `<RANCHER>/k8s/clusters/local/api/v1/namespaces/<ns>/services/http:<app-label>:<port>/proxy/`.

**Priority:** 🟡 Medium, "Open" button may 404 if the Service name doesn't match expectations.

### 5.1 Verify Service name matches `app` label or release name

Currently, `service-webui.yaml` uses `{{ include "emberburn.fullname" . }}` for the Service name, and `emberburn.selectorLabels` defines `app: {{ include "emberburn.fullname" . }}`. These are consistent. **No change needed** as long as the dashboard uses the `app` label value to construct the proxy URL.

### 5.2 Verify Service exposes the correct GUI port

The web UI service exposes port `5000` via `service.webui.port` / `service.webui.targetPort`, which matches `embernet.ai/gui-port`. **No change needed.**

### 5.3 Add Embernet labels to the Service object

For enhanced dashboard discovery, add the same `embernet.ai/app-name` label to the Service:

```yaml
# templates/service-webui.yaml — metadata labels
embernet.ai/app-name: {{ .Values.embernet.appName | default .Chart.Name | quote }}
```

### Files Changed
- `templates/service-webui.yaml`: labels section (optional enhancement)

---

## Phase 6: Values Schema Tolerance

**Goal:** Ensure the chart does not break when the K3s Helm controller injects unknown keys via `valuesContent`.

**Priority:** 🟠 High, chart installs will fail if unknown keys trigger schema validation errors.

### 6.1 Confirm no JSON Schema validation file exists

If a `values.schema.json` file exists in the chart root, it must either be removed or made permissive (use `"additionalProperties": true` at the root level).

**Current status:** No `values.schema.json` found. **No change needed.**

### 6.2 Test with injected unknown keys

```bash
helm template test ./helm/opcua-server \
  --set someUnknownKey=true \
  --set another.nested.key="test"
# Should render without errors
```

---

## Phase 7: Documentation & README Update

**Goal:** Add Embernet-specific configuration section to the chart README so operators know which values control dashboard integration.

**Priority:** 🟢 Low, nice to have for onboarding.

### 7.1 Add Embernet Integration section to chart README

Document the following in `helm/opcua-server/README.md` or `helm/opcua-server/app-readme.md`:

- Required labels and what they do
- How to set `embernet.displayName`, `embernet.device`, `embernet.guiType`
- How `imagePullSecrets` works
- How `nodeSelector` targets specific nodes

### 7.2 Update `NOTES.txt` post-install output

Add a note confirming the Embernet labels that were applied:

```
Embernet Dashboard Integration:
  GUI Type:    {{ .Values.embernet.guiType | default "web" }}
  GUI Port:    {{ .Values.emberburn.ports.webui }}
  Store App:   true
```

### Files Changed
- `helm/opcua-server/app-readme.md` or chart-level `README.md`
- `templates/NOTES.txt`

---

## Phase 8: End-to-End Validation

**Goal:** Confirm the chart works correctly with the Embernet Dashboard in a live K3s environment.

**Priority:** 🔴 Critical, final gating step before release.

### 8.1 Helm lint

```bash
helm lint ./helm/opcua-server
```

### 8.2 Template render check

```bash
helm template emberburn ./helm/opcua-server \
  --set embernet.displayName="Test EmberBurn" \
  --set embernet.device="plc-test-01" \
  --set 'imagePullSecrets[0].name=ghcr-pull-secret'
```

### 8.3 Deploy to test K3s cluster

```bash
helm install emberburn-test ./helm/opcua-server \
  -n default --create-namespace
```

### 8.4 Verify dashboard discovery

```bash
# Pod must appear with correct labels
kubectl get pods -l embernet.ai/store-app=true --show-labels

# Check all required labels exist
kubectl get pods -l app.kubernetes.io/instance=emberburn-test \
  -o jsonpath='{.items[*].metadata.labels}' | python -m json.tool
```

### 8.5 Dashboard UI verification

- [ ] App card appears in Embernet Dashboard
- [ ] "Open" button launches iframe proxy to port 5000
- [ ] Display name shows correctly (if set)
- [ ] Device mapping works in device view (if set)
- [ ] Shell terminal connects successfully

---

## Phase Summary

| Phase | Description | Priority | Effort |
|-------|-------------|----------|--------|
| **1** | Fix critical discovery labels (`embernet.io` → `embernet.ai`, add `gui-port`, `gui-type`) | 🔴 Blocking | Small |
| **2** | Add `embernet` values block + `imagePullSecrets` default | 🟠 High | Small |
| **3** | Add recommended labels & annotations (display-name, device) | 🟡 Medium | Small |
| **4** | Add `imagePullSecrets` support to deployment template | 🟡 Medium | Small |
| **5** | Service selector & naming alignment verification | 🟡 Medium | Minimal |
| **6** | Values schema tolerance verification | 🟠 High | Minimal |
| **7** | Documentation & README updates | 🟢 Low | Medium |
| **8** | End-to-end validation in K3s | 🔴 Critical | Medium |

### Recommended execution order

**Phases 1–2** can be done together as a single commit, they are the minimum required to make the chart visible to the dashboard.

**Phases 3–4** should follow immediately as a second commit, they round out the pod template for production use.

**Phase 5–6** are verification-only and require no code changes based on the current chart state.

**Phase 7** can be done at any time but ideally before publishing to the Embernet App Store.

**Phase 8** is the final gate: do not tag a release until all checks pass.
