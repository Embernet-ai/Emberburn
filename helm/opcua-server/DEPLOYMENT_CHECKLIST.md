# EmberBurn: Chart Deployment Checklist

What the `emberburn` chart in this directory actually ships, and how to prove it
before a customer finds out otherwise.

This file used to describe the 1.0.0 chart from January: a namespace template, an
RBAC Role and RoleBinding, a LoadBalancer web UI, a 10Gi volume, and a packaging
flow that copied the tarball into a `fireball-industries/helm-charts` repo from a
`Small-Application` checkout. None of that exists anymore, and a checklist that
ticks boxes for templates that were deleted months ago is worse than no checklist,
because it reads as verified. Every line below was checked against the chart at
4.4.28.

The release process itself (version bump, tag, image, merge, publish) lives in
`RELEASE_CHECKLIST.md` at the repo root. This file is about the chart.

---

## File structure

`.helmignore` keeps every internal `.md` in this directory out of the package, this
one included. What ships is:

- [ ] `Chart.yaml`, `values.yaml`, `questions.yaml`, `README.md`, `app-readme.md`
- [ ] 15 templates: `_helpers.tpl`, `NOTES.txt`, `configmap.yaml`, `deployment.yaml`,
      `hpa.yaml`, `ingress.yaml`, `networkpolicy.yaml`, `pod-disruption-budget.yaml`,
      `pvc.yaml`, `secret.yaml`, `service-opcua.yaml`, `service-prometheus.yaml`,
      `service-webui.yaml`, `serviceaccount.yaml`, `servicemonitor.yaml`

There is no `namespace.yaml`, `role.yaml`, or `rolebinding.yaml`. The chart installs
into the release namespace (the dashboard picks it, or `-n` does) and its
ServiceAccount has no Role bound to it, because the app never talks to the
Kubernetes API.

---

## Chart.yaml

- [ ] `apiVersion: v2`, `name: emberburn`, `type: application`
- [ ] `version`, `appVersion`, and `catalog.cattle.io/upstream-version` are the same
      number (see `RELEASE_CHECKLIST.md` §3)
- [ ] `catalog.cattle.io/display-name: "EmberBurn"`. The App Store prints this on the
      card, so it is the product name and nothing more
- [ ] `catalog.cattle.io/release-name: "emberburn"`, `certified: "fireball"`,
      `featured: "true"`, and the `categories` list
- [ ] `icon:` is an embedded `data:image/png;base64` URI, not a URL. Clusters in the
      field are air gapped, and a data URI also sidesteps the CORS problem that
      blanks remote icons in the dashboard's `crossorigin` image. Regenerate it with
      `python scripts/build-chart-icon.py` from the repo root

---

## values.yaml defaults

### Security context
- [ ] Pod: `fsGroup: 1000`, so the PVC is writable by the app
- [ ] Container: `runAsUser: 1000`, `runAsGroup: 1000`, `runAsNonRoot: true`,
      `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`
- [ ] `readOnlyRootFilesystem: false`, on purpose: the app writes logs and data

### Storage
- [ ] `persistence.enabled: true`, `size: "2Gi"`, `accessMode: ReadWriteOnce`,
      `mountPath: /app/data`, empty `storageClass` (cluster default)

### Services (all ClusterIP)
| Service | Port | Target | Why |
|---|---|---|---|
| `<release>` | 5000 | 5000 | Web UI and REST API. Named after the release because the dashboard proxies to `<release>.<ns>.svc` |
| `<release>-opcua` | 4840 | 4840 | OPC UA clients |
| `<release>-metrics` | 8000 | 5000 | Metrics. 8000 is the Service port only; `/metrics` is served by Flask on 5000 |

- [ ] Nothing is a LoadBalancer. The dashboard reaches the UI over ClusterIP, and a
      LoadBalancer per instance just burns addresses
- [ ] `network.hostNetwork: false`. Host networking breaks the dashboard proxy and
      makes a second instance on the same node fight over ports

### Resources
- [ ] `emberburn.resources.preset: "medium"` (250m / 512Mi requested, 1000m / 2Gi limit)
- [ ] `small`, `large`, and `custom` presets defined

### App Store contract
- [ ] Store labels `embernet.ai/store-app`, `gui-type`, `app-name: "EmberBurn"`, and
      `gui-port: "5000"` on the pod template **and** the `<release>` Service
- [ ] `embernet.ai/app-icon` is an **annotation** (a data URI is not a legal label
      value) on the pod template **and** the `<release>` Service
- [ ] `tenantLabels: {}` in values, rendered onto the pod template and all three
      Services. Miss it and the app is invisible to the tenant who deployed it

---

## Pre-deployment tests

Run from the repo root. None of these need a cluster.

```bash
# 1. Lint. Expect "1 chart(s) linted, 0 chart(s) failed"
helm lint helm/opcua-server

# 2. Render the defaults
helm template emberburn helm/opcua-server --debug > /dev/null

# 3. Client side dry run of an install (no cluster contact)
helm install emberburn-test helm/opcua-server \
  --namespace test-emberburn --create-namespace --dry-run=client > /dev/null

# 4. questions.yaml parses
python -c "import yaml; yaml.safe_load(open('helm/opcua-server/questions.yaml', encoding='utf-8')); print('ok')"

# 5. Store labels on pod and Service, tenant labels on pod and 3 Services
helm template t helm/opcua-server | grep -c 'embernet.ai/gui-port'          # expect 2
helm template t helm/opcua-server --set tenantLabels."embernet\.ai/tenant"=acme \
  | grep -c "embernet.ai/tenant: acme"                                         # expect 4

# 6. Every optional template renders when switched on
helm template t helm/opcua-server \
  --set ingress.enabled=true --set autoscaling.enabled=true \
  --set podDisruptionBudget.enabled=true --set networkPolicy.enabled=true \
  --set monitoring.enabled=true --set monitoring.serviceMonitor.enabled=true \
  | grep -E '^kind:' | sort | uniq -c
# expect HorizontalPodAutoscaler, Ingress, NetworkPolicy, PodDisruptionBudget,
# and ServiceMonitor alongside the defaults. The ServiceMonitor needs BOTH
# monitoring flags; serviceMonitor.enabled alone renders nothing.
```

- [ ] All six pass

### Known open item
- [ ] **Pod scrape annotation points at a dead port.** `pod.annotations` sets
      `prometheus.io/port: "8000"`, and annotation based scrapers go to the pod IP
      on that port, where nothing listens (the app serves `/metrics` on 5000; a
      4.4.28 container answers 200 on 5000 and refuses 8000). The `-metrics`
      Service and the ServiceMonitor are fine because they go through the Service.
      This box stays unchecked until a release fixes the annotation.

---

## Packaging

Nobody packages this by hand. `release.yml` packages the chart and merges it into
`index.yaml` at the repo root on every push to `main` that touches `helm/**`, after
confirming the image for that version exists in GHCR. GitHub Pages serves `main`,
so the catalog URL is:

```
https://embernet-ai.github.io/Emberburn/index.yaml
```

- [ ] The new version resolves from the published repo:
      ```bash
      helm repo add emberburn https://embernet-ai.github.io/Emberburn/
      helm repo update
      helm search repo emberburn/emberburn --versions | head -3
      ```
- [ ] Older versions are still listed. The index is a catalog, not a pointer at
      the newest build

---

## Post-deployment verification

Install from the App Store, or by hand into a scratch namespace:

```bash
helm install eb emberburn/emberburn --version X.Y.Z -n eb-check --create-namespace
kubectl -n eb-check rollout status deploy/eb --timeout=180s
kubectl -n eb-check get pvc,svc,sa,cm

# Web UI and API, through the Service the dashboard uses
kubectl -n eb-check port-forward svc/eb 5000:5000 &
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5000/            # 200
curl -s http://127.0.0.1:5000/api/tags | head -c 200

# Metrics, through the metrics Service
kubectl -n eb-check port-forward svc/eb-metrics 8000:8000 &
curl -s http://127.0.0.1:8000/metrics | head

# PVC is writable by uid 1000
kubectl -n eb-check exec deploy/eb -- sh -c 'echo ok > /app/data/write-test && cat /app/data/write-test'

# OPC UA answers inside the cluster
kubectl -n eb-check run opc --rm -i --restart=Never --image=busybox:1.36 -- \
  nc -zv -w 5 eb-opcua 4840
```

- [ ] Pod Running and Ready, PVC Bound
- [ ] Web UI returns 200, `/api/tags` returns JSON
- [ ] `/metrics` returns data through `eb-metrics`
- [ ] PVC write succeeds
- [ ] Port 4840 open from another pod
- [ ] In the dashboard: the card reads **EmberBurn** with the flame icon, and
      "OPEN" loads the UI in the iframe

Clean up with `helm uninstall eb -n eb-check && kubectl delete ns eb-check`.

---

## Sign-off

- [ ] Pre-deployment tests pass
- [ ] Post-deployment verification done on a real cluster
- [ ] Non-root, no privilege escalation, all capabilities dropped (rendered, not assumed)
- [ ] No credentials in `values.yaml`: `security.apiKey` and `security.opcua.users`
      default empty, and real ones belong in `security.existingSecret`
- [ ] `app-readme.md` and `README.md` describe the chart as it is

---

**EmberBurn: Where Data Meets Fire 🔥**
