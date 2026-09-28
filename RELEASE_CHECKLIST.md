# EmberBurn Release Checklist

Use this checklist every time you cut a new version. Copy/paste the raw markdown into your commit message or PR description and check items off as you go.

---

## 1. Pre-Flight: Verify Before You Touch Anything

- [ ] **Working tree clean**, `git status` shows no uncommitted changes
- [ ] **On `main` branch**, `git branch --show-current` returns `main`
- [ ] **Pulled latest**, `git pull origin main` (org repo is source of truth, see
      the remotes table at the bottom; check `git remote -v` before assuming names)
- [ ] **Dependency audit clean**, `pip-audit -r requirements.txt --strict` passes.
      `PYSEC-2026-888` / `GHSA-mfpj-3qhm-976m` (opcua chunk DoS) are expected: no
      upstream fix exists, and it is mitigated in-process by `apply_chunk_limits()`.
      Ignore those two and **nothing else**. CI enforces this in `security-audit.yml`.

---

## 2. GHCR Image Link Verification

> **Why this exists:** In v3.9.0 we discovered a 403 Forbidden on every image pull.
> The Dockerfile `org.opencontainers.image.source` label pointed to a repo name
> (`Small-Application`) that doesn't exist on the Embernet-ai org, the org repo is
> called `Emberburn`. GHCR uses this label to link packages to repos. Unlinked
> packages default to **private**, causing 403 even though the repo itself is public.

- [ ] **Dockerfile `image.source` label** matches the org repo exactly:
  ```
  LABEL org.opencontainers.image.source="https://github.com/Embernet-ai/Emberburn"
  ```
  If this says `Small-Application` or any other name → **STOP and fix it**.

- [ ] **GHCR package visibility is Public**: verify at:
  https://github.com/orgs/Embernet-ai/packages → `emberburn` → Package settings
  If the package doesn't exist yet (first release), you must set it to Public
  immediately after the first successful workflow run.

- [ ] **Workflow `IMAGE_NAME`** in `.github/workflows/docker-publish.yml` matches:
  ```yaml
  IMAGE_NAME: embernet-ai/emberburn
  ```

---

## 3. Version Bump (replace `X.Y.Z` with new version)

Chart, image, and app have shared one number since 4.4.20, so all five fields
carry the **same** version string. `release.yml` refuses to publish when
`appVersion` and the image tag disagree, but it never looks at `version.py` or the
upstream-version annotation, so those two are on you.

| File | Field(s) | Example |
|------|----------|---------|
| `helm/opcua-server/Chart.yaml` | `version`, `appVersion`, `catalog.cattle.io/upstream-version` | `4.4.28` |
| `helm/opcua-server/values.yaml` | `emberburn.image.tag` | `"4.4.28"` |
| `version.py` | `__version__` | `"4.4.28"` |

- [ ] `Chart.yaml`, `version: X.Y.Z`
- [ ] `Chart.yaml`, `appVersion: "X.Y.Z"`
- [ ] `Chart.yaml`, `catalog.cattle.io/upstream-version: "X.Y.Z"`
- [ ] `values.yaml`, `tag: "X.Y.Z"`
- [ ] `version.py`, `__version__ = "X.Y.Z"`

```bash
grep -nE '^version:|^appVersion:|upstream-version' helm/opcua-server/Chart.yaml
grep -nE '^\s+tag:' helm/opcua-server/values.yaml | head -1
grep -n __version__ version.py
```

---

## 4. EmberNET Template Alignment

> **Added in v4.0.9:** Verify alignment with the canonical EmberNET Helm chart template.

### 4a. Store Labels (The Big Four)

Verify all four labels exist on **pod template** AND **Service (webui)** objects:

| Label | Pod Template | Service |
|-------|-------------|---------|
| `embernet.ai/store-app: "true"` | - [ ] Present | - [ ] Present |
| `embernet.ai/gui-type: "web"` | - [ ] Present | - [ ] Present |
| `embernet.ai/app-name: "EmberBurn"` | - [ ] Present | - [ ] Present |
| `embernet.ai/gui-port: "5000"` | - [ ] Present | - [ ] Present |

> `app-name` became `"EmberBurn"` in v4.1.7 (was `"emberburn"` from `.Chart.Name`).
> Store-catalog lookup is case-insensitive so both resolve, but pre-4.1.8 instances
> in the field still emit the lowercase form.

### 4e. Tenant Labels: the silent-failure one

`.Values.tenantLabels` is injected by the dashboard at deploy time. A chart that
does not render it carries no `embernet.ai/tenant`, so its Services are filtered out
of every tenant-scoped view, visible to SuperAdmin, **invisible to the customer who
deployed it**: and POD SHELL returns 403. It looks fine from our side. Wired in
v4.1.9; verify it stays wired:

```bash
helm template t helm/opcua-server --set tenantLabels."embernet\.ai/tenant"=acme \
  | grep -c "embernet.ai/tenant: acme"   # expect 4 — pod template + 3 Services
```

- [ ] `tenantLabels` rendered on pod template **and** all three Services

### 4f. App Icon: must be an annotation, never a label

Kubernetes label values cannot contain `/` or `:`, so an icon URL or data URI is
only legal as an **annotation**. The dashboard reads it from pod annotations as well
as the Service; Service-only leaves node cards showing a generic glyph.

- [ ] `embernet.ai/app-icon` is an **annotation** on pod template **and** Service
- [ ] Its value is **not** an external URL: air-gapped clusters cannot fetch one.
      It is an embedded data URI from `emberburn.appIcon`; regenerate with
      `python scripts/build-chart-icon.py`

### 4g. Store card name and GUI port

The EmberNET App Store prints `catalog.cattle.io/display-name` on the store card.
Until 4.4.28 ours carried the product name plus a "Multi-Protocol IoT Gateway"
tagline, which is a slogan wearing a name tag. It is the product name and nothing
else.

`embernet.ai/gui-port` is where the dashboard sends "OPEN". It follows
`service.webui.port`, the Service forwards to `service.webui.targetPort`, and the
container listens on `emberburn.ports.webui`. All three are 5000 by default; change
one without the others and the label points at nothing, and nothing fails until
somebody clicks the button.

```bash
grep -n 'display-name' helm/opcua-server/Chart.yaml   # expect "EmberBurn"
helm template t helm/opcua-server | grep -nE 'gui-port|containerPort: 5000|port: 5000|targetPort: 5000'
```

- [ ] `catalog.cattle.io/display-name: "EmberBurn"`
- [ ] `gui-port` equals the webui Service port, and the Service's targetPort is a
      port the container actually declares

### 4b. Network Configuration

- [ ] `values.yaml` has `network.hostNetwork: false` (dashboard proxy requires ClusterIP networking)
- [ ] `deployment.yaml` has `hostNetwork` / `dnsPolicy` conditional block

### 4c. `_helpers.tpl`

- [ ] `emberburn.storeLabels` helper function exists
- [ ] Used in `deployment.yaml` pod template labels
- [ ] Used in `service-webui.yaml` labels

### 4d. Dashboard Integration

- [ ] Service name uses `{{ .Release.Name }}` directly (required for dashboard FQDN proxy routing)
- [ ] Service selector matches pod selector labels
- [ ] `gui-port` label value is a quoted number (`"5000"`)

---

## 5. Quality Gates

All must pass before committing:

- [ ] **Helm lint**, `helm lint helm/opcua-server` → `0 chart(s) failed`
- [ ] **Helm template**, `helm template test-release helm/opcua-server` renders without errors
- [ ] **Chunk-limit guard**, `python test_chunk_limits.py` → `12/12`. This is the
      CVE-2022-25304 mitigation; it monkeypatches a private python-opcua method, so
      a dependency bump can silently un-apply it. The test drives the *unpatched*
      library first, so it fails rather than passing vacuously.
- [ ] **Sparkplug B wire format**, `pip install amqtt && python test_sparkplug.py`
      → `15/15`. Asserts payloads are protobuf and **not** JSON, which is the bug
      that hid behind an import guard for the life of the project.
- [ ] **Docker build** (optional, CI handles multi-arch), `docker build -t emberburn:X.Y.Z .`

---

## 6. Helm Chart Packaging (Automated)

> **As of v4.0.9:** The `release.yml` GitHub Actions workflow automatically
> runs `helm package` and `helm repo index --merge` whenever `helm/**` files
> change on `main`. You do not package or touch `index.yaml` by hand.
>
> The chain is: `release.yml` commits the `.tgz` and `index.yaml` to `main` as
> `github-actions[bot]`, and GitHub Pages serves `main` straight from the repo
> root (legacy branch build), so the `pages-build-deployment` run that fires on
> that commit is what puts it online. `pages.yml` does **not** run for it. The bot
> pushes with `GITHUB_TOKEN`, and GitHub does not start workflows from events that
> token creates, so `pages.yml` only fires when a human pushes an index or `.tgz`
> change. That is how 4.4.28 went out: `pages-build-deployment` on `5c3b8c3`, no
> `pages.yml` run at all, and the index was correct anyway.

Manual fallback (only if CI is broken):

- [ ] **Do not delete the old `.tgz` files.** This step used to say
      `Remove-Item emberburn-*.tgz`, and deleting every package before indexing
      is exactly what cut `index.yaml` down to one entry per release (the long
      comment in `release.yml` step 5 has the whole story). The repo is a catalog.
- [ ] **Package**, `helm package helm/opcua-server -d .` (run from repo root)
- [ ] **Merge into the index**, `helm repo index . --url https://embernet-ai.github.io/Emberburn/ --merge index.yaml`
- [ ] **Verify `index.yaml`**, the new `version:` and `urls:` are there **and**
      every older version is still listed

---

## 7. Release Notes

> These two rules used to be stated as "add an entry for the version you are
> cutting" **and** "remove the entry for the version you are cutting", which cannot
> both be satisfied. The intent is that `RELEASE_NOTES.md` **lags one version
> behind**: it documents what has shipped, and the release in your working tree has
> not shipped yet. So when cutting `X.Y.Z` you write the entry for the *previous*
> release, not this one.

- [ ] `RELEASE_NOTES.md` top entry is the **previous** version: no entry for the
      version being cut
- [ ] `CHANGELOG.md` **does** carry the current version. It is not governed by the
      lag rule; it is the Keep-a-Changelog record and should be written as you go

---

## 8. Commit, Tag, Push

> **There is one remote.** `origin` is `https://github.com/Embernet-ai/Emberburn.git`
> and nothing else gets pushed. The personal copy this used to sync to,
> `patrickryan01/Small-Application`, drifted by rewritten history until it could
> only be synced with a force push, so as of 2026-09-27 it is private and archived
> and Emberburn stands alone. If a clone still has an `upstream` remote, remove it
> (`git remote remove upstream`).

**Order matters, and it is not the order this section used to give.** The tag must
be pushed and the image must finish building *before* the chart bump reaches `main`,
because `release.yml` publishes the chart on push-to-main while `docker-publish.yml`
only builds on a `v*` tag. Pushing `main --tags` in one shot races them and can
publish a chart referencing an image that does not exist yet, that is what the
v4.0.9 ImagePullBackOff was. `release.yml` now hard-fails in that case rather than
shipping it, so getting this wrong costs you a red build instead of a broken deploy.

```bash
# 1. commit on a release branch, not directly on main
git checkout -b release/vX.Y.Z
git add .
git commit -m "vX.Y.Z: <short description>"
git push -u origin release/vX.Y.Z

# 2. tag it — this and only this triggers the multi-arch image build
git tag -a vX.Y.Z -m "EmberBurn X.Y.Z - <short description>"
git push origin vX.Y.Z

# 3. WAIT for docker-publish.yml to finish (~6 min), then confirm the image exists
gh run list -R Embernet-ai/Emberburn --limit 1
docker manifest inspect ghcr.io/embernet-ai/emberburn:X.Y.Z

# 4. only now merge to main — this triggers the chart publish
git checkout main && git merge --ff-only release/vX.Y.Z && git push origin main
```

- [ ] Committed on a `release/vX.Y.Z` branch
- [ ] Tagged `vX.Y.Z` and pushed the tag
- [ ] **Image build finished and image confirmed present in GHCR**
- [ ] Merged to `main` on the **org** repo (`Embernet-ai/Emberburn`)

---

## 9. Post-Push Verification

- [ ] **GitHub Actions (Docker)**: check Actions tab, `docker-publish.yml` triggered on `vX.Y.Z` tag
- [ ] **GitHub Actions (Chart)**: `release.yml` (Package & Publish Helm Chart) passed on
      the merge, and its `ci: publish emberburn-X.Y.Z helm chart` commit landed on `main`
- [ ] **GitHub Pages**: `pages-build-deployment` succeeded on that bot commit (see §6
      for why it is not `pages.yml`), and the live index actually has the version:
      ```bash
      gh run list -R Embernet-ai/Emberburn --limit 5
      curl -s https://embernet-ai.github.io/Emberburn/index.yaml | grep -n "emberburn-X.Y.Z.tgz"
      ```
- [ ] **Image pull**, `docker pull ghcr.io/embernet-ai/emberburn:X.Y.Z` succeeds (no 403)
- [ ] **GitHub Release**: create one on `Embernet-ai/Emberburn` for tag `vX.Y.Z`:
      ```bash
      gh release create vX.Y.Z -R Embernet-ai/Emberburn \
        --title "vX.Y.Z: <short description>" --notes-file <(...)
      ```
      Not optional. This was marked "if desired" and consequently skipped for every
      release between v4.0.7 and v4.1.10, leaving the Releases page eight versions
      stale while the tags and images were all published.
- [ ] **Helm chart**, `helm repo update` shows new version in Rancher catalog

### Post-Deploy Dashboard Verification

- [ ] **App appears in dashboard**: EmberBurn card visible in "Deployed Apps"
- [ ] **"OPEN" button works**: Opens Flask web UI in iframe
- [ ] **Web UI loads**: All pages (Dashboard, Tags, Publishers, Alarms, Config, Tag Generator) load
- [ ] **API endpoints work**, `/api/tags`, `/api/publishers` return data through proxy
- [ ] **OPC UA working**: Port 4840 accessible from other pods
- [ ] **Prometheus metrics**: `<release>-metrics` Service on 8000 returns `/metrics`.
      That is a Service port only; it forwards to the Flask app on 5000, and
      nothing in the pod listens on 8000, so test it through the Service. The
      pod's `prometheus.io/port` annotation says 5000 for the same reason (it said
      8000 until 4.4.29, and every annotation scrape hit a closed port)

---

## Quick Reference: Git Remotes

| Remote | URL | Purpose |
|--------|-----|---------|
| `origin` | `https://github.com/Embernet-ai/Emberburn.git` | The repo. CI runs here |

There used to be a second remote for the personal copy,
`patrickryan01/Small-Application`. Clones had the two names swapped, which is how
that copy silently drifted 17 commits behind between v4.0.8 and v4.1.10, and later
its history was rewritten until it could not be synced without a force push. It is
private and archived now; nothing syncs to it.

---

## Quick Reference: Sidecar Proxy

**EmberBurn does NOT need the sidecar proxy.**
Server-rendered Flask app with relative URL paths. Proxy-aware middleware handles URL rewriting natively (since v3.5.8).

---

*EmberBurn: Where Data Meets Fire 🔥*
