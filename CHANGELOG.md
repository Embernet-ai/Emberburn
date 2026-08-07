# Changelog

All notable changes to EmberBurn Industrial IoT Gateway will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.1.11] - 2026-07-21: Release Process Repair

4.1.9 and 4.1.10 were cut without following `RELEASE_CHECKLIST.md`. Four gates were
missed. Three of them were missed because the checklist itself was wrong, so this
release fixes the checklist rather than just the symptoms.

### Fixed: RELEASE_CHECKLIST.md

- **§1/§8 remote names:** the checklist said `embernet` = org repo and `origin` =
  personal fork. This clone has `origin` = org repo and `upstream` = personal fork,
  the reverse. Every push instruction pointed at the wrong name. Now says to check
  `git remote -v` and go by URL, with a corrected remotes table. This is how the
  fork silently drifted 17 commits behind between v4.0.8 and v4.1.10.
- **§8 push order was actively dangerous:** it said `git push embernet main --tags`,
  pushing the chart bump and the tag in one shot. `release.yml` publishes the chart
  on push-to-main while `docker-publish.yml` only builds on a `v*` tag, so that
  ordering races them and can publish a chart referencing an image that does not
  exist, which is exactly what the v4.0.9 ImagePullBackOff was. Replaced with the
  branch → tag → **wait for image** → merge → sync-fork sequence that the guard
  added in 4.1.9 actually enforces.
- **§7 was self-contradictory:** it required both adding and removing the current
  version's entry in `RELEASE_NOTES.md`. Clarified: release notes lag one version
  behind because the version in your tree has not shipped yet; `CHANGELOG.md`
  carries the current version and is not subject to the lag.
- **§9 GitHub Release was marked "if desired"** and was consequently skipped for
  every release from v4.0.8 to v4.1.10, eight versions where tags and images
  published but the Releases page stayed at v4.0.7. Now mandatory, with the command.
- **§4a `app-name` expected value** was `"emberburn"`; the chart has emitted
  `"EmberBurn"` since v4.1.7.
- **§4e added: tenant labels.** The gate that would have caught the customer-visible
  bug fixed in 4.1.9, with a one-line command that asserts all four renders.
- **§4f added: app icon.** Records that `app-icon` must be an annotation rather than
  a label (label values cannot contain `/` or `:`) and must not be an external URL.
- **§5 added: the two new test gates.** `test_chunk_limits.py` and
  `test_sparkplug.py`. The chunk-limit test matters most: it guards a monkeypatch of
  a private python-opcua method, which a dependency bump can silently un-apply.

### Fixed: documentation/HELM_CHART_REQUIREMENTS (1).md

- Added a supersession banner. Its claim that `embernet.ai/app-icon` resolves from
  `pod.Labels` is wrong, the dashboard reads it as an **annotation** from both pod
  and Service (`client.go:307-309`). Following this document is what produced the
  broken app tile fixed in 4.1.9. Also corrects its omission of the mandatory
  `embernet.ai/tenant` label and its listing of `web+shell`, which kube-apiserver
  rejects. `.agent/APP_STORE_DEPLOYMENT_FLOW.md`, cited by v4.1.8 as requiring a
  full icon URL, does not exist in this repository at all.

### Notes

- No application code changed in this release. Chart contents are identical to
  4.1.10 apart from the version strings.
- **Chart version**: `4.1.11`, appVersion: `4.1.11`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.1.11`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.1.11.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.1.11` tag

## [4.1.10] - 2026-07-20: Mitigate CVE-2022-25304, Audit Dependencies in CI

4.1.9 shipped with a known-unfixed CVE documented in `requirements.txt` and a
note telling operators to keep port 4840 off untrusted networks. Documenting a
vulnerability is not fixing it. The library is pure Python and we own the
process, so "unfixable upstream" turned out to mean "somebody else's problem
unless we make it ours."

### Added

- **opcua_server.py:** `apply_chunk_limits()` mitigates CVE-2022-25304 in-process.
  python-opcua accumulates incoming chunks in `SecureConnection._incoming_parts`,
  a plain list cleared only when a Final or Abort chunk arrives, so a client can
  stream unlimited Intermediate chunks and never terminate the message. The guard
  caps both chunk count and total bytes per message and raises `UaError` past the
  limit, which the library already handles by tearing down that channel. One
  abusive client loses its connection; the server keeps serving everyone else.
  Applied in `create_server()` before any client can connect. Tunable via
  `OPC_MAX_CHUNKS` (default 512) and `OPC_MAX_MESSAGE_BYTES` (default 16 MiB).
- **opcua_server.py:** the guard reports failure loudly if python-opcua's
  internals move, so a lapsed mitigation is visible rather than silently assumed.
- **test_chunk_limits.py:** new. Drives the **unguarded** library first and
  demonstrates it retaining 5000 chunks, proving the vulnerability is real,
  then installs the guard and asserts the flood is cut off at the limit, the
  buffer is released, the byte cap trips independently of the chunk cap,
  legitimate multi-chunk messages still assemble, and the byte counter does not
  leak between messages.
- **.github/workflows/security-audit.yml:** new. `pip-audit` on every
  `requirements.txt` change, on PRs, and weekly on a schedule so a CVE published
  against an unchanged pin still surfaces. Runs `--strict`, and also executes
  `test_chunk_limits.py` to confirm the opcua mitigation is still wired.
  PYSEC-2026-888 is explicitly ignored, it has no fixed version and is mitigated
  in-process, which keeps the gate meaningful: any *other* vulnerability fails
  the build. 4.1.9's two transitive CVEs sat unnoticed precisely because nothing
  was checking.

### Notes

- `paho-mqtt` remains pinned `<2` because `pysparkplug` requires it. Verified
  `paho-mqtt` 1.6.1 has **zero** known vulnerabilities, so this is a maintenance
  constraint rather than a security one. Revisit if pysparkplug adds paho 2
  support.
- **Chart version**: `4.1.10`, appVersion: `4.1.10`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.1.10`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.1.10.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.1.10` tag

## [4.1.9] - 2026-07-20: App Store Contract, Air-Gapped Icons, Working Writes, 15/15 Protocols

Audited the chart against the EmberNET App Store contract, the version generated
from the dashboard Go source rather than from documentation. Four gaps. Then went
looking at the app itself and found the write path had never worked, GraphQL had
never been able to start, and every icon we ship pointed at the public internet.

### Fixed: App Store contract

- **deployment.yaml, service-*.yaml:** `.Values.tenantLabels` was never consumed
  anywhere in the chart. The dashboard injects it at deploy
  (`store.go:1304-1315`) and we threw it away, so nothing carried
  `embernet.ai/tenant`. Result: Services filtered out of every tenant-scoped view
  (`services.go:226`), POD SHELL returning 403 (`shell.go:602-615`). Visible to
  SuperAdmin, invisible to the customer. Now on the pod template and all three
  Services, and declared in `values.yaml`
- **deployment.yaml:** `embernet.ai/app-icon` was Service-only. Contract §9.5,
  it is read from pod annotations too (`client.go:307-309`), and Service-only
  leaves node cards showing a generic glyph
- **deployment.yaml:** `replicas` was set unconditionally while `hpa.yaml` manages
  the same Deployment, so Helm reverted the HPA on every upgrade. Omitted now when
  `autoscaling.enabled`
- **networkpolicy.yaml:** allowed 5000 and 4840 but not 8000, so turning on
  `networkPolicy` silently killed Prometheus scraping

### Fixed: icons

- **_helpers.tpl, service-webui.yaml:** `embernet.ai/app-icon` pointed at
  `avatars.githubusercontent.com`. Air-gapped clusters cannot reach it. Now an
  embedded data URI via the new `emberburn.appIcon` helper, no network, no origin
  assumptions. A pod-relative path was tried and rejected: it resolves against the
  dashboard's origin, not ours
- **Chart.yaml:** `icon:` pointed at the same avatar. Embedded data URI now
- **base.html:** the header logo reassigned `logo.src` in JavaScript on load and
  theme toggle. The proxy rewriter matches `src="/` in markup, not
  `logo.src = "/` in a script, so the JS overwrote the rewritten path with a raw
  absolute one. Both assignments were dead code, same image in both themes
- **style.css:** dropped the Google Fonts `@import`. Same air-gap problem, which
  is why type has been rendering in fallback fonts
- **values.yaml:** `embernet.appIcon` defaulted to `fireball.png`, the corporate
  shield, not the EmberBurn logo. Wrong brand even when it did load
- **scripts/build-chart-icon.py:** new. Regenerates both embedded icons from
  `static/images/emberburn-chart-icon.png`. Idempotent

### Fixed: the write path never worked

- **opcua_server.py:** `write_callback` was only wired to
  `DataTransformationPublisher` by class-name match, so `RESTAPIPublisher`'s
  stayed `None` and every create, write and bulk-create returned 501. Any
  publisher exposing `set_write_callback` gets it now
- **opcua_server.py:** `write_tag()` had no `return` statement. Callers branch on
  the result, so even wired up, every success would have reported as a failure
- **publishers.py, opcua_server.py:** `DELETE /api/tags/<name>` cleared only the
  publisher cache, which `publish()` repopulated on the next cycle, the tag came
  back in under two seconds while the API returned success. Added
  `OPCUAServer.delete_tag()` and a delete callback

### Fixed: GraphQL

- **publishers.py:** `flask_graphql` pins `graphql-core<3` while `graphene` 3.x
  needs `graphql-core>=3.1`. They cannot be installed together, which is why
  GraphQL has never started in a shipped image. Ported onto graphene 3 with a
  plain Flask view over `schema.execute()`
- **publishers.py:** resolvers read `self.tags_data`, but graphene passes the root
  value (`None` at top level) as the first resolver arg, every query would have
  raised `AttributeError`
- **publishers.py:** `tag_metadata` was snapshotted at `__init__`, before
  `opcua_server` attaches it, so it stayed empty forever
- **opcua_server.py:** `_setup_tag_metadata()` tested only for `tag_cache` while
  its own comment claimed it covered GraphQL, which uses `tags_data`
- **publishers.py, config_graphql.json:** GraphiQL defaults off. CDN assets. The
  API has no external dependency

### Added: security

- **publishers.py:** mutating `/api/*` calls require an `X-EmberBurn-Token` header.
  Reads stay open for the dashboard. The pod injects the token into its own HTML,
  so the iframe works with no login prompt and no usernames anywhere.
  `security.uiWrites: false` drops the UI to read-only for internet-facing
  deployments while automation holding the token still writes
- **publishers.py:** CORS was open to every origin. Same-origin by default via
  `security.corsOrigins`
- **opcua_server.py:** OPC UA signing, encryption and username auth via
  `security.opcua.*`. Off by default, enabling it breaks every anonymous SCADA
  client until each is reconfigured. Fails loudly at startup if enabled without
  certificates or users rather than quietly serving plaintext
- **secret.yaml:** new, with `security.existingSecret` so credentials can live in
  sealed-secrets, external-secrets or vault instead of the chart

### Fixed: release safety

- **release.yml:** the chart publishes on push-to-main, the image only builds on a
  `v*` tag. Out of order, that ships a chart pointing at an image that does not
  exist, which is what 4.0.9 was. The workflow now refuses to package unless
  `appVersion` matches the values image tag and
  `ghcr.io/embernet-ai/emberburn:<version>` is already published. Order: push the
  tag, wait for the build, merge the chart bump

### Fixed: everything else

- **publishers.py:** the `'REST API'` name-map key could never match.
  `RESTAPIPublisher` stems to `RESTAPI`. UI showed "RESTAPI", icon fell back to a
  generic glyph, toggle always returned `success: false`. The 13-entry map was
  duplicated across two methods, which is how one drifted. One constant now
- **publishers.py:** publisher status was snapshotted once during `start_all()`,
  so the UI re-polled every 2s and re-rendered stale data, toggles never appeared
  to do anything. Live callback now
- **publishers.py:** the Prometheus tag gauge was hardcoded to `1` with a
  `# Placeholder` comment; counts distinct published tags now. The
  `publish_duration` histogram was created and never observed
- **api.js:** `importTags()` posted to `/api/tags/import`, which has never existed
  server-side. Import parses client-side and goes through `/api/tags/bulk`
- **api.js, tags.js, tag_generator.js:** absolute `/api/...` paths broke behind the
  dashboard's query-parameter proxy, and the relative-path workaround was wrong
  too, it resolves against the dashboard's own path. Both go through a
  proxy-aware base resolver now
- **config.html:** the four "Feature coming soon!" buttons are gone. Export Config
  and View Logs are real, backed by new `/api/config` (credentials redacted) and
  `/api/logs` (in-memory ring buffer, the app only logs to stdout). Restart and
  Import were deleted rather than faked; config is Helm-managed
- **style.css, tag_generator.html:** modal CSS was inline in one template, so every
  other page using `.modal-overlay` rendered unstyled
- **publishers.py:** three bare `except:` clauses swallowing everything including
  `KeyboardInterrupt`, unused `send_file` and `CollectorRegistry` imports, and an
  API index reporting a hardcoded `localhost:5002` GraphQL URL
- **requirements.txt:** added `websocket-server` and `twilio`. Both missing from
  the shipped image, so the WebSocket publisher and alarm SMS could never start
- **version.py:** new, single source of truth. `setup.py` carried its own string
  and had drifted to 4.0.7 while the chart was on 4.1.3
- **configmap.yaml:** deleted. Nothing mounted it, and it was the only template
  missing `namespace`
- **.helmignore:** the packaged chart was shipping 19 non-chart files to every
  user, including three stale UTF-16 PowerShell error dumps from a machine that no
  longer exists

### Fixed: Sparkplug B, which had never worked

- **publishers.py:** `SparkplugBPublisher` imported `sparkplug_b`, no such
  distribution has ever existed on PyPI, and it was not vendored here, so the
  import guard caught the `ImportError` and silently disabled the publisher for
  the life of the project
- **publishers.py:** where it did build payloads, it published **JSON** to
  `spBv1.0/` topics. Sparkplug B is protobuf. The wire format was never
  spec-compliant, so no real consumer could have decoded it even if the import had
  resolved
- Rewritten onto `pysparkplug`, which owns protobuf encoding, `bdSeq`, sequence
  numbering and the NBIRTH/DBIRTH/NDEATH lifecycle. The hand-rolled versions of all
  of those are deleted rather than ported
- Ints now map to `INT64` rather than the old `Int32`, which would silently wrap an
  OPC UA counter past 2.1 billion
- Tags created after startup, the Tag Generator can do this, trigger a device
  rebirth so the new metric is declared in a DBIRTH before its first DDATA, as the
  spec requires
- **requirements.txt:** `paho-mqtt` gained an upper bound. `pysparkplug` requires
  `paho-mqtt<2` and paho 2.x changed the callback API; unbounded, a fresh install
  resolves 2.x and Sparkplug silently stops connecting. Same class of bug as the
  flask-graphql conflict
- **test_sparkplug.py:** new. Stands up an in-process MQTT broker, sniffs the wire,
  and asserts NBIRTH/DBIRTH/DDATA/NDEATH all arrive, that payloads decode as
  Sparkplug protobuf and **are not JSON**, and that values round-trip with correct
  datatypes. Import-level checks would not have caught either original bug

### Fixed: dependency security audit

- **requirements.txt:** audited with `pip-audit`. Pinned `click>=8.3.3`
  (PYSEC-2026-2132) and `cryptography>=48.0.1` (GHSA-537c-gmf6-5ccf), neither is
  imported directly, but without a floor a rebuild could resolve a vulnerable
  version
- **KNOWN UNFIXED:** CVE-2022-25304 / PYSEC-2026-888 in `opcua`, unauthenticated
  DoS via unlimited unterminated chunks. It affects **all** versions of `opcua` and
  **all** versions of its successor `asyncua`, so no upgrade resolves it. Mitigated
  by the chart's NetworkPolicy restricting 4840 to the cluster and by pod memory
  limits bounding the blast radius to a restart. Documented in `requirements.txt`
  and the README rather than left for someone to discover

### Notes

- One instance per node, unchanged. EmberBurn is absent from
  `multiInstanceChart()` (`store.go:158-176`) and that is intended
- Two documents in this repo contradict the source-derived contract and directly
  caused bugs fixed here: `documentation/HELM_CHART_REQUIREMENTS (1).md` claims the
  icon resolves from pod *labels*, and `.agent/APP_STORE_DEPLOYMENT_FLOW.md` was
  cited by 4.1.8 as requiring a full icon URL, which is what put the GitHub avatar
  back. Both need reconciling or retiring
- **Chart version**: `4.1.9`, appVersion: `4.1.9`
- Image tag: `ghcr.io/embernet-ai/emberburn:4.1.9`
- Helm chart: `https://embernet-ai.github.io/Emberburn/emberburn-4.1.9.tgz`
- Multi-arch build (amd64/arm64) via GitHub Actions on `v4.1.9` tag

## [4.1.8] - 2026-04-27: App Store Deployment Flow Alignment

Align the chart end-to-end with `APP_STORE_DEPLOYMENT_FLOW.md`. The chart was
already mostly conformant (Service named `{{ .Release.Name }}`, the Big Four
`embernet.ai/*` labels on pod template + Service, FQDN proxy pattern, no
subdomain). This release closes the remaining gaps.

### Fixed
- **values.yaml:** `embernet.appIcon` default was a bare filename
  (`fireball.png`), which produced an invalid `embernet.ai/app-icon` annotation
, the doc requires a full URL. Changed default to `""` so the
  `service-webui.yaml` URL fallback (the GitHub avatar) is rendered.
- **values.yaml:** `network.hostNetwork` default reverted to `false` per
  `AUDIT_HELM_CHARTS.md` §5 (Multi-Instance Compatibility). `hostNetwork: true`
  turns every containerPort into a host port and collides on the second
  instance on the same node, breaking App Store multi-instance deployment.
- **NOTES.txt §10:** Was reading `embernet.guiType` while `_helpers.tpl`
  `storeLabels` reads `gui.type`/`gui.port`. Realigned NOTES.txt to read the
  same values that drive the discovery labels.

### Changed
- **NOTES.txt §1:** Lead with the App Store proxy path
  (`/api/proxy?target=http://{release}.{ns}.svc.cluster.local:{port}`) and
  demote the ingress/NodePort/port-forward variants to "Direct access (advanced)".
  Matches the doc's stance: App Store apps need no URL, ingress, or DNS record.
- **NOTES.txt §10:** Now prints the full FQDN proxy target so operators can
  verify the URL the dashboard's iframe will load.
- **values.yaml:** Added comment clarifying that `embernet.guiType` is kept for
  backward compat but `gui.type`/`gui.port` are the canonical inputs to the
  store-discovery labels.

## [4.1.7] - 2026-04-24: App Store Deployment Alignment

### Changed
- **_helpers.tpl:** Standardized `app.kubernetes.io/name` to use chart name identity.
- **_helpers.tpl:** Updated `embernet.ai/app-name` to use "EmberBurn" branding and made it configurable via `.Values.embernet.appName`.
- **service-webui.yaml:** Made `embernet.ai/app-icon` annotation dynamic via `.Values.embernet.appIcon`.

## [4.1.5] - 2026-04-24: Dashboard Routing Fix

### Fixed
- **service-webui.yaml:** Updated `flux.embernet.ai/service-name` annotation to default to `{{ .Release.Name }}` instead of `{{ .Chart.Name }}`. This resolves the 404 "Service Not Found" error in EmberNET Dashboard V4.0.7 by ensuring the proxy URL targets the actual Kubernetes service name.

---

## [4.1.2] - 2026-04-21: Documentation & Template Alignment

### Fixed
- **NOTES.txt:** Updated all service name references from `{{ fullname }}` to `{{ .Release.Name }}` to match the actual service templates (service-webui, service-opcua, service-prometheus)
- **RELEASE_CHECKLIST.md:** Corrected stale `hostNetwork: true` guidance → `hostNetwork: false` (dashboard proxy requires ClusterIP networking)
- **RELEASE_CHECKLIST.md:** Updated service naming description to reference `{{ .Release.Name }}` directly instead of fullname helper

---

## [4.1.0] - 2026-04-17: Dashboard Alignment & Multi-Instance Support

### ⚠️ BREAKING: Selector Label Change
- **`app` label changed:** `{{ fullname }}` → `{{ .Chart.Name }}` in `_helpers.tpl`
  - All instances now share `app: emberburn` for grouping
  - `app.kubernetes.io/instance` distinguishes individual releases
  - **Existing deployments must be deleted and reinstalled** (`helm uninstall` + `helm install`). Kubernetes does not allow updating immutable `matchLabels` selectors in-place

### Fixed
- **Service names:** All services now use `{{ .Release.Name }}` as the base instead of `{{ fullname }}`
  - WebUI service: `<release-name>` (was `<release-name>-emberburn`)
  - OPC UA service: `<release-name>-opcua` (was `<release-name>-emberburn-opcua`)
  - Prometheus service: `<release-name>-metrics` (was `<release-name>-emberburn-metrics`)
  - **This fixes dashboard FQDN proxy routing**: the "OPEN" button now resolves correctly
- **Ingress backend:** Updated to reference new webui service name
- **Deployment strategy:** Added `strategy.type: Recreate` to prevent scheduling deadlock when using `hostNetwork: true` with a RWO PersistentVolumeClaim

### Multi-Instance Deployment
Multiple Emberburn instances can now be deployed simultaneously:
```bash
helm install emberburn-plant-a helm/opcua-server -n plant-a --create-namespace
helm install emberburn-plant-b helm/opcua-server -n plant-b --create-namespace
```
Each instance gets unique services, PVCs, and ConfigMaps while sharing the `app: emberburn` identity label.

---

## [Unreleased]

### Added
- **Multi-Architecture Support** - Native ARM64/aarch64 Docker images
  - Automatic multi-arch builds via GitHub Actions (AMD64 + ARM64)
  - Support for Raspberry Pi 4/5 deployment
  - AWS Graviton instance support
  - Apple Silicon (M1/M2/M3) compatibility
  - NVIDIA Jetson support
  - ARM-based server support (Ampere Altra, etc.)
- Build scripts for multi-architecture Docker builds
  - `scripts/build-multi-arch.sh` (Linux/macOS)
  - `scripts/build-multi-arch.ps1` (Windows PowerShell)
- Comprehensive ARM64 deployment documentation
  - [docs/ARM64_DEPLOYMENT.md](docs/ARM64_DEPLOYMENT.md)
  - [docs/MULTI_ARCH_QUICK_REFERENCE.md](docs/MULTI_ARCH_QUICK_REFERENCE.md)
- Enhanced GitHub Actions CI/CD pipeline
  - QEMU setup for cross-platform builds
  - Build caching for faster builds
  - SBOM (Software Bill of Materials) generation
  - Build attestation and provenance
  - Enhanced metadata tagging (semver, branch, SHA)

### Changed
- Enhanced `.dockerignore` for smaller, optimized Docker images (~40% size reduction)
- Updated GitHub Actions workflow to build for multiple architectures
- Updated deployment documentation with ARM64 examples
- Improved build process with better caching

### Performance
- ARM64 images are ~3% smaller than AMD64 images
- AWS Graviton instances show ~10% better performance than equivalent x86 instances
- 20-40% cost savings when using AWS Graviton vs traditional x86 instances

### Documentation
- Updated README with multi-architecture feature announcement
- Updated KUBERNETES_DEPLOYMENT with ARM64 deployment instructions
- Updated DOCKER-BUILD-GUIDE with multi-arch build examples
- Added ARM64_IMPLEMENTATION_SUMMARY with complete technical details

## [1.0.0] - 2026-01-XX

### Added
- Initial release of EmberBurn Industrial IoT Gateway
- OPC UA Server with customizable tags
- Multi-protocol support (15 protocols)
  - MQTT, Sparkplug B, REST API, WebSocket
  - Kafka, AMQP, Modbus TCP, GraphQL
  - InfluxDB, Prometheus, SQLite
- Web-based configuration UI (Python Flask)
- Data transformation engine
- Alarm and notification system
- Kubernetes/Helm deployment support
- Docker containerization
- Comprehensive documentation

### Features
- Multiple simulation modes (random, sine, increment, static)
- Multi-protocol data publishing
- Tag discovery API
- Historical data persistence
- Metrics and monitoring
- RBAC and multi-tenancy support

---

## Version Numbering

- **Major** version: Breaking changes or major new features
- **Minor** version: New features, backwards compatible
- **Patch** version: Bug fixes, documentation updates

## Links

- [GitHub Repository](https://github.com/fireball-industries/Small-Application)
- [Documentation](https://fireballz.ai/emberburn)
- [Docker Images](https://ghcr.io/fireball-industries/emberburn)
