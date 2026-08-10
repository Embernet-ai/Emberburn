# EmberBurn Release Notes

> These notes lag one version behind by design (RELEASE_CHECKLIST.md §7): they
> record what has shipped, and the version sitting in the working tree has not.

## v4.1.13 — 2026-08-09

### Sparkplug Credentials From A Secret

AnvilMQ enforces per-user ACLs, so every MQTT publisher needs a credential and a
topic namespace that matches it. Both halves existed in the tree and neither was
in anything deployable.

- **Fixed**: published chart 4.1.12 carried no `EMBERBURN_SPARKPLUG_*` env block.
  The two Sparkplug commits landed after 4.1.12 was published and `release.yml`
  skips a version already indexed, so nothing republished. No released image read
  the variables either, since `docker-publish.yml` only builds on a `v*` tag. A
  deploy would have come up healthy and published nothing
- **Added**: `existingSecret` / `usernameKey` / `passwordKey` on the Sparkplug
  publisher, mirroring the Ignition-Edge-Pod convention. The rendered publishers
  ConfigMap carries only non-secret settings
- **Note**: 4.1.13 also derived the Sparkplug `group_id` from
  `tenantLabels."embernet.ai/tenant"`. That was reverted in 4.1.14, because App
  Store deploys on this cluster carry no tenantLabels and the derivation broke
  the install path it was meant to protect

## v4.1.12 — 2026-07-21

### A Default Storage Request The Edge Could Not Satisfy

- **Fixed**: the persistent volume claim asked for more than an edge cluster
  can give it. Longhorn on the Fragua edges runs `default-replica-count=3` at
  `storage-over-provisioning-percentage=100` with most of each node's disk
  already scheduled, so the claim sat Pending on `insufficient storage; precheck
  new replica failed` and the pod never started. EmberBurn's SQLite persistence
  file is small; the old request was sized for a historian it does not run. The
  default is now **2Gi**, which fits what an edge node actually has
- **Docs**: the OPC UA hardening section now describes what the chunk guard
  protects and why, without printing a working recipe for the attack it blocks

## v4.1.11 — 2026-07-21

### Repairing The Release Process, And The Checklist That Misdirected It

4.1.9 and 4.1.10 were both cut without following `RELEASE_CHECKLIST.md`. Three of
the four missed gates were missed because the checklist itself was wrong, so this
release fixed the checklist rather than the symptoms.

- **Remote names were backwards**: the checklist named the personal fork as the
  org repo and vice versa, so every push instruction pointed at the wrong place.
  That is how the fork drifted 17 commits behind between v4.0.8 and v4.1.10. It
  now says to check `git remote -v` and go by URL, not by name
- **Push order was actively dangerous**: it said to push `main --tags` in one
  shot. `release.yml` publishes the chart on push-to-main while
  `docker-publish.yml` only builds on a `v*` tag, so that races them and can
  publish a chart referencing an image that does not exist. That is precisely
  what the v4.0.9 ImagePullBackOff was. Replaced with branch → tag → **wait for
  the image** → merge → sync-fork
- **§7 was self-contradictory**: it demanded both adding and removing the
  current version's release-notes entry. Resolved into the lag rule above
- **Added a hard gate**: `release.yml` now refuses to publish a chart whose
  `appVersion` image is absent from GHCR, so getting the order wrong costs a red
  build instead of a broken deploy

## v4.1.10 — 2026-07-20

### Actually Fixing The CVE Instead Of Documenting It

4.1.9 shipped a known-unfixed CVE with a note saying "keep 4840 off untrusted
networks." That is not a fix, it is a disclaimer.

- **Root cause**: CVE-2022-25304, python-opcua accumulates incoming chunks in
  `SecureConnection._incoming_parts`, a plain list that is only cleared when a
  Final or Abort chunk arrives. A client opens a session, streams unlimited
  Intermediate chunks, never terminates the message, and the process dies.
  Unauthenticated. Affects every version of `opcua` and of its successor
  `asyncua`, so there is nothing to upgrade to
- **Fixed**, `apply_chunk_limits()` in `opcua_server.py` caps chunk count and
  total bytes per message and raises `UaError` past the limit, which python-opcua
  already handles by tearing down that channel. One abusive client loses its
  connection; everyone else keeps getting data. The library is pure Python and we
  own the process, so "unfixable upstream" only meant nobody had made it their
  problem. Tunable via `OPC_MAX_CHUNKS` / `OPC_MAX_MESSAGE_BYTES`
- **Added** `test_chunk_limits.py`, which proves it honestly: it drives the
  **unpatched** library first and shows it retaining 5000 chunks, then installs
  the guard and shows the flood cut off at the limit, then confirms legitimate
  multi-chunk messages still assemble
- **Added** `.github/workflows/security-audit.yml`, `pip-audit --strict` on every
  requirements change, on PRs, and weekly so a CVE published against an unchanged
  pin still surfaces. It also runs the chunk-limit test, so if the mitigation ever
  stops being wired the build says so. 4.1.9's two transitive CVEs went unnoticed
  because nothing was checking
- **Note**: `paho-mqtt` stays pinned `<2` for `pysparkplug`. Confirmed 1.6.1 has
  zero known vulnerabilities, a maintenance constraint, not a security one
- **Chart version**: `4.1.10`, appVersion: `4.1.10`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.1.10`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.1.10.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.1.10` tag

---

## v4.1.9 — 2026-07-20

### The Icons Never Loaded, The Writes Never Worked, GraphQL And Sparkplug Never Started

Audited the chart against the EmberNET App Store contract, the one generated
from the dashboard Go source, not the docs. Found four gaps. Then went looking
at the app and found worse.

**Icons**

- **Root cause**: Every icon in this product pointed at
  `avatars.githubusercontent.com`. We ship into air-gapped clusters. There is no
  public internet. The tile has never rendered.
- **Fixed** `Chart.yaml` icon and the `embernet.ai/app-icon` annotation: both
  are embedded data URIs now. No network, no origin assumptions, no excuses
- **Fixed** `app-icon` being Service-only. Contract §9.5: it is read from pod
  annotations too, and Service-only leaves node cards showing a generic glyph
- **Root cause** (header logo): `base.html` reassigned `logo.src` in JavaScript
  on page load and theme toggle. The proxy rewriter matches `src="/` in markup,
  not `logo.src = "/` in a script, so the JS overwrote the rewritten path with a
  raw absolute one and killed the logo behind the dashboard proxy. Both
  assignments were dead code; same image in both themes
- **Fixed** the Google Fonts `@import` in `style.css`. Also unreachable
  air-gapped, which is why the type has been rendering in fallback fonts
- **Note**: `embernet.appIcon` defaulted to `fireball.png`, the Fireball
  Industries corporate shield, not the EmberBurn logo. Wrong brand on the tile
  even if it had loaded

**Tenant labels: the one that actually mattered**

- **Root cause**: `.Values.tenantLabels` was never consumed anywhere in the
  chart. The dashboard injects it at deploy (`store.go:1304-1315`) and we threw
  it away, so pods and Services carried no `embernet.ai/tenant`
- **Result**: Services filtered out of every tenant-scoped view
  (`services.go:226`) and POD SHELL returning 403. Visible to SuperAdmin, invisible
  to the customer who deployed it. Looks fine from our side. Broken from theirs
- **Fixed**: rendered onto the pod template and all three Services, declared in
  `values.yaml`

**The write path**

- **Root cause**: `write_callback` was only wired to
  `DataTransformationPublisher` by class-name match, so the REST publisher's was
  `None`. Every tag create, write and bulk-create from the web UI returned 501
- **Root cause** (stacked on top): `write_tag()` had no `return` statement.
  Callers branch on the result, so even after wiring it, every success would have
  reported as a failure
- **Root cause** (third one): `DELETE` cleared only the publisher cache, which
  `publish()` repopulated on the next update cycle. The tag came back in under
  two seconds while the API said `success: true`
- **Fixed** all three. The Tag Generator is a real feature now instead of a UI
  wired to nothing

**GraphQL**

- **Root cause**: `flask_graphql` pins `graphql-core<3`; `graphene` 3.x needs
  `graphql-core>=3.1`. They cannot coexist. GraphQL has been in the protocol table
  since day one and has never once started in a shipped image
- **Fixed**: ported onto graphene 3 with a plain Flask view over
  `schema.execute()`. No unmaintained middleman this time
- **Fixed** two bugs that would have broken it anyway: resolvers read
  `self.tags_data` when graphene passes the root value as the first arg, and
  `tag_metadata` was snapshotted before the server attaches it
- **Changed** GraphiQL to default off: its assets come from a CDN. The API does
  not

**Security**

- **Added** token-gated writes on `/api/*`. Reads stay open so the dashboard keeps
  polling; the pod injects the token into its own HTML so the iframe works with no
  login and no usernames. `security.uiWrites: false` drops the UI to read-only for
  internet-facing deployments while automation keeps writing
- **Added** OPC UA signing, encryption and username auth. Opt-in, off by default,
  turning it on breaks every anonymous SCADA client until it is reconfigured.
  Fails loudly at startup if half-configured instead of quietly serving plaintext
- **Fixed** CORS being open to every origin. Same-origin by default now

**Release safety**

- **Root cause**: the chart publishes on push-to-main; the image only builds on a
  `v*` tag. Release them out of order and you ship a chart pointing at an image
  that does not exist. That is what 4.0.9 was
- **Fixed**, `release.yml` now refuses to package unless `appVersion` matches the
  values image tag *and* `ghcr.io/embernet-ai/emberburn:<version>` is already
  published. Order is: push the tag, wait for the build, merge the chart bump

**Everything else**

- **Fixed** the `'REST API'` publisher key that could never match.
  `RESTAPIPublisher` stems to `RESTAPI`. UI showed "RESTAPI", icon fell back to a
  generic glyph, toggle always returned `success: false`. The map was duplicated
  in two methods, which is how one drifted
- **Fixed** publisher status being a one-time snapshot, the UI re-polled every 2s
  and re-rendered stale data, so toggles never appeared to do anything
- **Fixed** the Prometheus tag gauge hardcoded to `1` with a `# Placeholder`
  comment, and a histogram that was created and never observed
- **Fixed** `importTags()` posting to `/api/tags/import`, a route that has never
  existed
- **Fixed** absolute `/api/...` paths breaking behind the dashboard proxy, and
  the relative-path workaround, which was also wrong
- **Replaced** the four "Feature coming soon!" buttons on the Config page. Export
  Config and View Logs are real, backed by new `/api/config` (credentials
  redacted) and `/api/logs`. Restart and Import were deleted rather than faked,
  config is Helm-managed
- **Fixed** modal CSS living inline in one template, so every other page using
  `.modal-overlay` rendered unstyled
- **Added** `websocket-server` and `twilio` to requirements: both missing from the
  shipped image, so the WebSocket publisher and alarm SMS could never start
- **Fixed** `replicas` fighting the HPA on every upgrade, and a NetworkPolicy that
  silently killed Prometheus scraping by omitting port 8000
- **Removed** 19 non-chart files shipping inside the packaged chart, including
  three stale UTF-16 PowerShell error dumps from a machine that no longer exists
- **Added** `version.py` as one source of truth. `setup.py` had drifted to 4.0.7
  while the chart was on 4.1.3
**Sparkplug B: 15/15 protocols now actually run**

- **Root cause**: `SparkplugBPublisher` imported `sparkplug_b`. No such package has
  ever existed on PyPI and it was not vendored here, so the import guard caught the
  `ImportError` and disabled the publisher silently. It has been dead for the life
  of the project while the README counted it
- **Root cause** (second one): where it did build payloads, it published **JSON** to
  `spBv1.0/` topics. Sparkplug B is protobuf. No real consumer. Ignition, Chariot,
  HiveMQ, could have decoded a single message even if the import had worked
- **Fixed**: rewritten onto `pysparkplug`. The library owns protobuf encoding,
  `bdSeq`, sequence numbering and the NBIRTH/DBIRTH/NDEATH lifecycle, so the
  hand-rolled versions are gone rather than ported
- **Fixed** ints mapping to `Int32`, which silently wrapped any counter past 2.1
  billion. Now `INT64`
- **Added** device rebirth when a tag appears after startup, so the metric is
  declared in a DBIRTH before its first DDATA like the spec requires
- **Fixed** `paho-mqtt` being unbounded. `pysparkplug` requires `paho-mqtt<2`; a
  fresh install was resolving 2.x, whose changed callback API stops Sparkplug
  connecting. Same class of bug as the flask-graphql conflict
- **Added** `test_sparkplug.py`: stands up an in-process broker, sniffs the wire,
  and asserts the payloads decode as protobuf and **are not JSON**. Import checks
  would not have caught either original bug

**Dependency security audit**

- **Audited** with `pip-audit`. Pinned `click>=8.3.3` and `cryptography>=48.0.1`,
  neither imported directly, but an unbounded rebuild could resolve a vulnerable
  version
- **Known unfixed**: CVE-2022-25304 in `opcua`, unauthenticated DoS via unlimited
  unterminated chunks. Affects **every** version of `opcua` and of its successor
  `asyncua`, so there is nothing to upgrade to. The chart's NetworkPolicy keeps 4840
  inside the cluster and pod memory limits cap the damage at a restart. Documented
  rather than left to be discovered
- **Chart version**: `4.1.9`, appVersion: `4.1.9`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.1.9`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.1.9.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.1.9` tag

---

## v4.0.8 — 2026-03-04

### Bug Fix & Documentation Reorganization

- **Fixed** `/dashboard` route returning 500 error: now redirects to main index instead of missing template
- **Moved** 9 documentation files from repo root to `documentation/` folder for cleaner structure
- **Added** `App_Integration_Guide.md`: comprehensive guide for Embernet Dashboard integration
- **Added** `GUI_DASHBOARD_TODO.md`: issue tracking and resolution documentation
- **Chart version**: `4.0.8`, appVersion: `4.0.8`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.0.8`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.0.8.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.0.8` tag

---

## v4.0.7 — 2026-03-03

### Flux Mesh Integration: Auto-Discovery Annotations

- **Added** `flux.embernet.ai/*` annotations to all three Service templates (webui, opcua, prometheus)
- **Added** `flux:` values block to `values.yaml` with `expose`, `serviceName`, `port`, `roleAttributes`
- **Web UI** service exposed on the Flux mesh by default (`flux.expose: true`)
- **OPC UA** and **Prometheus** services opt-in via `flux.exposeOpcua` / `flux.exposeMetrics`
- Edge tunnel auto-discovers annotated services: zero per-site configuration required
- Aligns with [flux_operability.md](docs/flux_operability.md) specification
- **Chart version**: `4.0.7`, appVersion: `4.0.7`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.0.7`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.0.7.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.0.7` tag

---

## v4.0.6 — 2026-03-03

### Helm Chart Enhancements & Template Improvements

- **Added** `embernet.ai/app-name` label to webui service for Embernet Dashboard integration
- **Added** `display-name` annotation, `device` label, and `imagePullSecrets` support to Helm chart
- **Updated** deployment template with improved label selectors and resource configuration
- **Updated** `NOTES.txt` with Embernet Dashboard onboarding instructions
- **Added** comprehensive Helm chart README documentation
- **Added** Helm chart alignment & phased implementation planning docs
- **Chart version**: `4.0.6`, appVersion: `4.0.6`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.0.6`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.0.6.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.0.6` tag

---

## v4.0.5 — 2026-02-13

### Fix: Docker tags only from tagged releases

- **Fixed** Docker metadata to stop generating a `main` branch tag that raced with the versioned tag build
- **Removed** `type=ref,event=branch` and `type=ref,event=pr` from workflow metadata: only semver tags are generated now
- **Changed** `latest` condition to explicitly require a `v*` tag ref instead of `is_default_branch`
- **Result**: Pushing a `v*` tag now produces only `X.Y.Z`, `X.Y`, and `latest`, no more phantom `main` image
- **Chart version**: `4.0.5`, appVersion: `4.0.5`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.0.5`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.0.5.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.0.5` tag

---

## v4.0.4 — 2026-02-12

### Cleanup: Remove broken releases, fix workflow triggers

- **Removed** old broken releases (v4.0.1, v4.0.2, v4.0.3) and their tgz files from the repo
- **Cleaned** index.yaml to only contain the current version
- **Docker workflow** now only triggers on `v*` tags and `workflow_dispatch`, no more branch pushes or release events causing racing builds
- **Note**: CodeQL "Push on main" and built-in "pages build and deployment" are GitHub repo settings, disable CodeQL in Settings > Code Security, and set Pages source to "GitHub Actions" in Settings > Pages
- **Chart version**: `4.0.4`, appVersion: `4.0.4`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.0.4`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.0.4.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.0.4` tag

---

## v4.0.3 — 2026-02-12

### Fix: Workflow triggers causing image overwrites

- **Root cause**: Docker build workflow triggered on `push to main`, `v* tags`, AND `release published`, causing 3 simultaneous builds that raced and overwrote the working `latest` manifest with a broken one
- **Fix**: Stripped workflow down to only trigger on `v*` tags and `workflow_dispatch`. No more branch push or release event builds.
- **Chart version**: `4.0.3`, appVersion: `4.0.3`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.0.3`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.0.3.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.0.3` tag

---

## v4.0.2 — 2026-02-12

### Fix: Image tag 4.0.1 never published: 403 on pull

- **Root cause**: Chart.yaml and values.yaml were bumped to `4.0.1` but no `v4.0.1` git tag was pushed, so no container image was built. GHCR returns 403 (not 404) for non-existent tags on public repos, making it look like an auth issue.
- **Fix**: Bumped all versions to `4.0.2`, will push `v4.0.2` git tag to trigger GitHub Actions multi-arch build
- **Chart version**: `4.0.2`, appVersion: `4.0.2`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.0.2`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.0.2.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.0.2` tag

---

## v4.0.0 — 2026-02-12

### Major Release: Complete Helm Chart + Container Image

- **Breaking**: Major version bump to signal production-ready release
- **Helm Chart**: Packaged tarball with proper index.yaml for Helm repository
- **Container Image**: Multi-arch (amd64/arm64) build with working GHCR permissions
- **Workflow**: Cleaned permissions - no attestation features causing private package defaults
- **Chart version**: `4.0.0`, appVersion: `4.0.0`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.0.0`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.0.0.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.0.0` tag

---

## v3.10.4 — 2026-02-12

### Fix: ImagePullBackOff / 403 Forbidden (Final Fix)

- **Root cause**: Workflow still had `id-token: write` and `attestations: write` permissions even though attestation step was disabled. GHCR treats packages with attestation permissions as "security-sensitive" and defaults them to **private** visibility on every new tag.
- **Fix**: Removed `id-token: write` and `attestations: write` permissions from workflow entirely. Only `contents: read` and `packages: write` remain.
- **Manual action still required**: Until GitHub fixes this behavior, new tags may still default to private. Set package visibility to Public at: `https://github.com/orgs/Embernet-ai/packages/container/emberburn/settings`
- Image tag: `ghcr.io/embernet-ai/emberburn:3.10.4`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v3.10.4` tag

---

## v3.10.3 — 2026-02-12 ⚠️ FAILED

### Updates

- Clean release to verify attestation fix from v3.10.2
- **Result**: Still got 403 Forbidden - attestation permissions caused private package visibility
- Image tag: `ghcr.io/embernet-ai/emberburn:3.10.3` (requires manual public toggle)
- Multi-arch build (amd64/arm64) via GitHub Actions on `v3.10.3` tag

---

## v3.10.2 — 2026-02-12

### Fix: ImagePullBackOff / 403 Forbidden on GHCR (Again)

- **Root cause**: `actions/attest-build-provenance@v1` with `push-to-registry: true` creates a **separate SHA-tagged manifest** before the semver-tagged manifest. GHCR links the SHA manifest as a distinct image with private permissions, causing 403 when K8s tries to pull the semver tag that resolves to the SHA digest.
- **Fix**: Disabled attestation step in workflow. Attestations are useful for supply chain security but break GHCR image pulls.
- **Evidence**: Two manifests in GHCR for same digest - one with `sha256-...` tag (0 downloads, private), one with `3.10.2`/`latest` tags (1 download, works after manual public toggle).
- Image tag: `ghcr.io/embernet-ai/emberburn:3.10.2`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v3.10.2` tag

---

## v3.10.1 — 2026-02-12

### Fix: ImagePullBackOff / 403 Forbidden on GHCR

- **Root cause**: `docker-publish.yml` metadata-action included `type=sha`, generating SHA-digest tags (e.g., `sha-02870d...`). When workflow was triggered by branch push instead of semver tag, only SHA/branch tags were pushed, no `3.10.0` version tag existed in GHCR, causing 403 on pull.
- **Fix**: Removed `type=sha` from `docker/metadata-action` tag rules. Only semver, branch, PR, and `latest` tags are now generated.
- Image tag: `ghcr.io/embernet-ai/emberburn:3.10.1`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v3.10.1` tag

---

## v3.10.0 — 2026-02-11

### UI Fixes

- **Fixed**: Navbar logo showed broken Embernet image inside dashboard iframe. Replaced with `emberburn-chart-icon.png`. EmberBurn now uses its own branding, not the Embernet parent logo.
- **Fixed**: Dashboard showed "Loading tag data..." when 0 tags are running. Now shows "No tags configured".
- **Fixed**: Publishers, Alarms, and Config pages stuck on infinite loading spinner when accessed through the Embernet Dashboard iframe proxy.
  - **Root cause**: `api.js` used absolute path `/api` for fetch calls. The proxy URL rewriter in `publishers.py` only rewrites `text/html` responses, `api.js` is served as `application/javascript` so its paths were never rewritten. All API calls hit the dashboard host instead of routing through the proxy.
  - **Fix**: Changed `API_BASE` from `/api` (absolute) to `api` (relative). Browser resolves relative URLs against current page URL, which already includes the proxy prefix.
- Image tag: `ghcr.io/embernet-ai/emberburn:3.10.0`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v3.10.0` tag

---

## v3.9.0 — 2026-02-11

### Fix: GHCR 403 Forbidden (Image Pull Failure)

- **Root cause**: Dockerfile `org.opencontainers.image.source` label pointed to `Embernet-ai/Small-Application` (non-existent). GHCR uses this label to link packages to repositories, unlinked packages default to **private**, causing 403 on pull.
- **Fix**: Corrected label to `https://github.com/Embernet-ai/Emberburn` (the actual org repo name).
- **Action required**: GHCR package visibility must be set to **Public** via org package settings after first successful build.
- Image tag: `ghcr.io/embernet-ai/emberburn:3.9.0`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v3.9.0` tag

---

## v3.5.8 — 2026-02-10

### Feature: Proxy-Aware Static Asset Loading

- **Problem**: When loaded inside the Embernet Dashboard iframe via `/api/proxy`, CSS/JS/images failed to load because absolute paths (`/static/web/...`) resolved against the dashboard domain.
- **Fix**: Added `after_request` middleware in `publishers.py` that detects reverse proxy (`X-Forwarded-For` header) and rewrites all `href`/`src`/`fetch()` paths to route through `/api/proxy?target=http://PodIP:5000/...`.
- Direct access (no proxy) is unaffected: rewriting only activates when proxied.

---

## v3.5.7 — 2026-02-10

### Critical Fix: Server Killing Itself on Startup

- **Root cause**: Shutdown logic (`stop_all()`, `server.stop()`) was inside `_setup_transformation_callback()` instead of `shutdown()`. Called during init → Flask and OPC UA died immediately after starting.
- **Fix**: Moved all stop/shutdown code into `shutdown()` method where it belongs.
- Flask (5000) and OPC UA (4840) now stay alive after initialization.
- Added Troubleshooting section to `NETWORKING_GUIDE.md`.

---

## v3.5.6 — 2026-02-10

### Hotfix: "Launch UI" Proxies to Wrong Port

- **Root cause**: Dashboard picks the **first** `containerPort` for "Launch UI" reverse proxy. `opcua` (4840) was listed before `webui` (5000), so the dashboard proxied to OPC UA binary protocol → `connection refused`.
- **Fix**: Reordered ports in `deployment.yaml`, `webui` (5000) is now **first**.
- Added `CAUTION` block + multi-port example to `NETWORKING_GUIDE.md` Section 2d.

---

## v3.5.5 — 2026-02-10

### Hotfix: CrashLoopBackOff

- **Root cause**: Liveness/readiness probes targeted OPC UA port `4840`, which is slow to bind during container startup (tag loading, protocol initialization). K8s killed the container before OPC UA finished starting.
- **Fix**: Probes now target Flask web UI port `5000` (starts instantly, reliable liveness indicator).
- Liveness: `initialDelaySeconds: 45`, `failureThreshold: 6` (more startup headroom).
- **All container ports unchanged**: `4840` (OPC UA), `5000` (WebUI), `8000` (Prometheus), industrial protocol data still flows on all ports.

---

## v3.5.4 — 2026-02-10

### Hotfix

- **Fixed**: `embernet.io/app-icon` label used emoji `🔥` which is not a valid Kubernetes label value (must be alphanumeric, `-`, `_`, `.`). Changed to `"fire"`.
- **Fixed**: Added `release: types: [published]` trigger to `docker-publish.yml` so GitHub Releases created through the UI fire the container build workflow.
- Chart version: `3.5.4`, appVersion: `3.5.4`
- Image tag: `ghcr.io/embernet-ai/emberburn:3.5.4`

---

## v3.5.3 — 2026-02-10

### 🔥 Highlights

**Embernet UI Redesign**: Complete visual overhaul matching the Embernet Industrial Dashboard design language.  
**OPC UA Tag Generator**: New feature for creating, managing, importing, and exporting OPC UA tags.  
**Helm Chart Fixes**: Corrected index URL, added chart icon, cleaned stale packages.

---

### UI Redesign

- Replaced sidebar navigation with horizontal header (logo, nav links, dark mode toggle, company logo)
- Dark mode is now the default; light mode toggle via localStorage
- Migrated entire CSS from fire/orange theme to Embernet red palette (`--ember-red: #E31837`)
- Added Inter font (Google Fonts), responsive breakpoints at 768px
- Status footer with OPC UA connection indicator and version display
- All 6 page templates updated (`index`, `tags`, `alarms`, `publishers`, `config`, `tag-generator`)

### OPC UA Tag Generator

- **New page** at `/tag-generator` with stat cards, quick actions, and searchable tag table
- **Create tags** with full metadata: name, data type, initial value, units, category, simulation, alarm config
- **Delete tags** with confirmation dialog
- **Write values** to live tags via modal
- **Bulk import** from CSV or JSON files with preview table
- **Export** all tags as CSV or JSON
- **3 built-in templates** for rapid tag setup:
  - 3-Phase Motor (9 tags: current, voltage, power, RPM, temp, vibration, run status, fault, hours)
  - Tank Level (7 tags: level, flow in/out, temp, pressure, high/low alarms)
  - Conveyor (6 tags: speed, running, jam, items counted, motor temp, belt tension)

### Backend API

New REST endpoints in `publishers.py`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tags/create` | POST | Create a tag with type conversion and metadata |
| `/api/tags/<name>` | DELETE | Delete a tag from cache and metadata |
| `/api/tags/bulk` | POST | Bulk create with per-tag error reporting |
| `/api/tags/export` | GET | Export as JSON or CSV (`?format=csv`) |

### Helm Chart

- Added `embernet.io/app-icon` label to pod template
- Chart icon set to Embernet GitHub org avatar
- Added `emberburn-chart-icon.png` asset
- Fixed `index.yaml` URL to `https://embernet-ai.github.io/Emberburn/`
- Fixed `sources` in `Chart.yaml` to point to `Embernet-ai/Emberburn`
- Image tag pinned, pullPolicy set to `IfNotPresent`

### Container Image

- Built and tagged as `ghcr.io/embernet-ai/emberburn:3.5.3`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v3.5.3` tag
- Base image: `python:3.11-slim`

### Artwork Assets

- `embernet-white.png`: Header logo (dark mode)
- `embernet.png`: Header logo (light mode)
- `fireball.png`: Company logo
- `favicon-32x32.png`: Browser tab icon
- `emberburn-chart-icon.png`: Helm chart catalog icon

---

### Bug Fixes (v3.5.1 → v3.5.4)

- **v3.5.1**: Added actual Embernet artwork assets (replaced empty placeholders)
- **v3.5.2**: Fixed GZIP invalid header caused by `index.yaml` pointing to wrong GitHub Pages domain
- **v3.5.3**: Fixed `index.yaml` URL to correct org repo (`Embernet-ai/Emberburn`), fixed `sources` in `Chart.yaml`
- **v3.5.4**: Fixed invalid K8s label (emoji not allowed), added `release` event trigger to GitHub Actions workflow

---

*EmberBurn: Where Data Meets Fire 🔥*  
*Fireball Industries × Embernet*
