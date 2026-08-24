# Changelog

All notable changes to EmberBurn Industrial IoT Gateway will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.4.22] - 2026-08-24: The Metrics Service Pointed At A Port Nothing Binds

### Fixed

- **Every scrape of `<release>-metrics:8000` was refused, and had been since the
  Service was introduced.** `PrometheusPublisher.start()` binds no listener. It
  registers metrics against the default registry and the Flask app in
  `RESTAPIPublisher` serves them at `/metrics` on the web UI port. The publisher
  says as much in its own body, "No separate server needed". The Service was
  still forwarding to `targetPort: 8000`, so the metrics existed and nothing
  could reach them.

  Nothing failed loudly, which is why it survived. The publisher reported
  `enabled`, the Service object existed, `/metrics` answered `200` on `5000` the
  whole time, and the dashboard rendered an endpoint off the
  `service-type: prometheus` label that could never answer. Found on
  `fragua-edge-01`, which had therefore been unmonitored for its entire life.

  `service.prometheus.targetPort` is `5000` now. `port` stays `8000`, so any
  existing scrape config or dashboard entry pointed at `<release>-metrics:8000`
  keeps resolving and only the far end moves.

- **Dropped the `prometheus` containerPort.** It advertised a listener that never
  existed. It cannot simply be repointed at the web UI port either, because two
  containerPorts with the same number and protocol are rejected by the API
  server. The metrics Service reaches the app by port number instead, and
  `webui` stays first in the list, which the dashboard depends on for its Launch
  UI proxy.

  `emberburn.ports.prometheus` stays in the port map, moved down to the RESERVED
  group beside `modbus` and `websocket`, because it still names the Service port.

## [4.4.21] - 2026-08-19: The Web UI Renders Again When The Dashboard Embeds It

### Fixed

- **Iframed through the dashboard, the web UI painted as unstyled HTML.** Our
  `<link rel="stylesheet" href="/static/web/css/style.css">` and
  `<script src="/static/...">` are root-absolute. On the dashboard's path-proxy
  route we are served under `dashboard.embernet.ai`, so those resolve against the
  dashboard, 404, and the page renders with no CSS at all. The browser fetches
  them before any JavaScript runs, so `static/js/api.js` being mode-aware cannot
  rescue the first paint.

  4.1.9 shipped an `after_request` hook that rewrote them, gated on
  `X-Forwarded-For`. 4.1.19 deleted it, because that gate cannot tell the
  dashboard's two routes apart - Go's reverse proxy sets `X-Forwarded-For` on
  **both**. On the appgui subdomain we are already at our own root, so rewriting
  there pointed every asset at the dashboard and the iframe rendered nothing.
  Deleting it fixed the subdomain and silently broke the proxy route. **The gate
  was the bug**; the rewriting is still required on one of the two routes.

  The hook is back, gated on `X-Embernet-Proxy-Prefix` - set by the dashboard
  (v4.9.6) **only** on the routes that serve us under its origin, and carrying
  the exact prefix our URLs must take. Absent means we are at our own root and
  nothing is touched, so 4.1.19's fix is preserved.

### Changed

- The prefix is no longer guessed from `request.host`. The old version hardcoded
  `/api/proxy?target=http://{host}`, a cross-repo pin that is also wrong for
  `/api/appview` - the route Ignition Edge GUIs use - where the path travels in a
  query parameter and must be percent-encoded. A prefix ending in `path=` selects
  that encoding.
- Rewriting is a regex over `href`/`src`/`fetch(` rather than string replacement,
  so only root-absolute URLs are touched and an external `https://` href is left
  alone. Streamed responses (`direct_passthrough`) are skipped.

---

## [4.4.20] - 2026-08-17: One Number To Deploy

Consolidation release. **Deploy this one.** No code change from 4.1.21 — the
version exists so there is a single answer to "what should be running," instead
of a 4.1.x tail where some versions are fine, one is actively misleading, and
one was never packaged at all.

### Why the jump

The dead-broker work shipped across three releases in two days, and the middle
one is a trap:

| Version | State | Notes |
|---|---|---|
| 4.1.19 | Superseded | Floods the log on a dead broker. This is what was in the field. |
| 4.1.20 | **Do not deploy** | Fixes the flood, but reports a dead broker as healthy to Prometheus. |
| 4.1.21 | Good | Fixes 4.1.20. Functionally identical to this release. |
| 4.4.20 | **Deploy this** | Same code as 4.1.21, one number. |

4.1.16 also has an image and a tag but was never packaged into the chart index,
so it is not installable from the catalog. That gap stays historical rather than
being back-filled — this release supersedes it.

### What you get, relative to 4.1.19

- **A dead broker no longer floods the log.** 63,720 publish errors in 30
  minutes became 2 lines: one when the link drops, one when it returns. See
  4.1.20 for the mechanism — `SparkplugBPublisher.connected` was set once and
  never contradicted, and pysparkplug's own `_connected` records intent rather
  than the socket, so neither could be trusted for liveness
- **It reconnects on its own.** There was previously no path from a running
  publisher back to `start()`, so a broker blip meant a dead gateway until
  someone restarted the pod — and it looked healthy throughout. Retries are
  paced 1s doubling to 60s with jitter
- **A paused publisher reads as unhealthy, not healthy.** The correction from
  4.1.21: dropping a value and delivering one are now distinguishable to
  `publish_to_all()`, so `emberburn_publisher_errors_total` still answers the
  question it exists to answer
- **Nothing retries flat out any more.** `OPCUAClientPublisher` had the same
  defect on a five-second loop and got the same backoff

### Verification

122 checks across four suites: `test_backoff.py` 29, `test_sparkplug.py` 15,
`test_chunk_limits.py` 12, `test_simulation.py` 66.

No chart behaviour changed anywhere in this arc. `reconnect_initial_seconds`
and `reconnect_max_seconds` are optional with sane defaults, so nothing new is
rendered into the ConfigMap.

## [4.1.21] - 2026-08-17: A Paused Publisher Is Not A Healthy One

### Fixed

- **4.1.20 quieted the logs and blinded the metrics in the same change.** The
  flood fix works by having `publish()` return early while the broker is down
  instead of throwing per tag. But `publish_to_all()` decides what happened by
  whether `publish()` raised — and a paused publish returns, exactly like a
  successful one. So every dropped tag was counted as a **delivered message**:
  a dead broker read as roughly 45 healthy messages a second on the dashboard,
  which is precisely the question `emberburn_publisher_errors_total` exists to
  answer. The first drop also fired the throttle's `clear()` and logged a
  **"recovered"** line, immediately after the line saying the link had dropped.

  4.1.20's changelog claimed "Prometheus still counts every error, so the
  metrics are unchanged." That was true of the exception path and false of the
  path the fix actually introduced. Correcting it here rather than quietly.

- Publishers now carry `unavailable_reason` on the base class: `None` while
  delivering, a string while enabled but unable to. `publish_to_all()` reads it
  to tell a drop apart from a delivery, records the drop as an error, and
  leaves the error run open so no false recovery is logged. Suppression stays
  log-only, which is what was meant the first time.

- **`OPCUAClientPublisher` had the same hole.** Its `publish()` skips servers
  that are down and returns normally, so with every configured server
  unreachable it dropped every value while looking like a clean publish. It now
  reports `unavailable_reason` when no server is reachable.

The regression test asserts on the counters, not the log lines — the metric was
the thing that broke, and a log-only test is what let this ship.

## [4.1.20] - 2026-08-16: A Dead Broker Stops Being A Log Flood

### Fixed

- **63,720 publish errors in 30 minutes — about 35 a second — against a broker
  that had gone away.** `SparkplugBPublisher.connected` was set `True` by
  `start()` and cleared only by `stop()`. Nothing ever contradicted it, so when
  AnvilMQ went away the guard at the top of `publish()` still passed, every
  publish fell through to `update_device()`, and every one of them threw and
  logged its own line: one per tag, per scan, for as long as the broker stayed
  dead. Ninety tags on a two-second scan is exactly the observed rate.

  The flag could not be fixed by clearing it in the right place, because there
  was no right place — `pysparkplug` sets `EdgeNode._connected` in its
  on_connect callback and clears it only when *we* call `disconnect()`, so it
  reports intent, not the socket. Liveness now comes from paho's
  `is_connected()`, which tracks the connection itself. If those internals ever
  move, it falls back to pysparkplug's flag: the safe failure here is to keep
  publishing, not to refuse to.

- **Nothing ever reconnected.** There was no path back to `start()` from a
  running publisher, so a broker blip meant a dead gateway until someone
  restarted the pod — and the pod looked healthy the whole time. A monitor
  thread now watches the link, pauses publishing when it drops, and reconnects
  on an exponential backoff (1s, doubling, capped at 60s, with jitter so a fleet
  that lost the same broker does not all pile back on at the same instant). A
  broker that is not up yet at boot is treated the same as one that dies later;
  neither needs a restart now.

  Recovery re-issues the DBIRTH, and the birth set is the union of tag metadata
  and every tag declared at runtime. Seeding from metadata alone would have
  silently dropped Tag-Generator tags from the metric set the first time the
  broker blinked, and a DDATA naming a metric the newest DBIRTH left out is not
  legal Sparkplug.

- **The same amplifier existed for every publisher.** `publish_to_all()` logged
  one line per exception, per tag, per scan, so any publisher developing this
  disease produced the same flood. Errors now collapse to one line per state
  change: first failure, a periodic count while it persists so a long outage
  stays visible, and one line when it clears. A *changed* message logs
  immediately — "connection refused" becoming "authentication failed" is new
  information. Suppression is log-only; Prometheus still counts every single
  error, so the metrics are unchanged.

- **`OPCUAClientPublisher` retried on a flat five-second interval forever**,
  logging an info line and an error line every pass. Same defect, same fix —
  per-server backoff, `reconnect_interval` kept as the first wait so a
  configured value still means what it did, with a ceiling added.

While the broker is down, publishing costs nothing: 1,800 calls to a dead
broker return in under a millisecond total and produce zero log lines, against
1,800 lines before. Verified in `test_backoff.py`, which runs a real in-process
broker and kills it — the bug was a false belief about a socket, so mocking the
socket would have mocked away the thing under test.

No chart changes. The two new knobs (`reconnect_initial_seconds`,
`reconnect_max_seconds`) are optional and default sane, so nothing needs to be
rendered into the ConfigMap for this to work.

## [4.1.19] - 2026-08-13: Unpin The Web UI From The Dashboard's Path Proxy

### Fixed

- **Launch UI opened an empty iframe.** An `after_request` hook rewrote every
  absolute `href`/`src`/`fetch()` in our HTML to
  `/api/proxy?target=http://<our host>/…`, gated on `X-Forwarded-For`.

  That gate cannot tell the dashboard's two routes apart, and `X-Forwarded-For`
  is set on **both**. The primary route serves an app at the **root of its own
  hostname** (`<svc>--<tenant>--<ns>--<port>.apps.embernet.ai`), where absolute
  paths already resolve. Rewriting them there pointed every asset and every API
  call at the *dashboard's* origin, for an app not served there — so the frame
  loaded and rendered nothing.

  The hook is removed. Serving at our own root needs no rewriting, and
  `static/js/api.js` was already mode-aware: it rebuilds the prefix from
  `?target=` when present and uses same-origin paths when not, so the fallback
  route still works.

  The dashboard's own `documentation/internal/App_Store_GUI_Shell_Alignment.md`
  names this hook as "direction B", calls it the worse of the two failure modes
  because it pins an app to the fallback permanently, and lists unpinning
  EmberBurn as an open decision. This closes it.

## [4.1.18] - 2026-08-13: Chart Fix — `args` Without `command` Never Starts

### Fixed

- **The pod crash-looped on `exec: "-c": executable file not found`.** 4.1.15
  added `args` to point the app at the mounted config, but the image declares
  `CMD` with **no `ENTRYPOINT`**. Kubernetes `args` overrides `CMD` and leaves
  `ENTRYPOINT` as the program — with no ENTRYPOINT, args become the entire
  command line and the kubelet tries to exec `-c`. The template now sets
  `command: ["python", "opcua_server.py"]` alongside `args`.

Chart-only release; the 4.1.17 image is unchanged.

## [4.1.17] - 2026-08-13: Stable OPC UA Node IDs

### Fixed

- **A tag's NodeId depended on the order tags were created in.**
  `add_variable(idx, name, value)` asks the server to assign the next free
  *numeric* identifier, so tags came out as `ns=2;i=1`, `ns=2;i=2` … in
  creation order. An OPC client that bound to `ns=2;i=7` keeps that binding,
  and the next start — a reordered tag store, one tag added, one removed —
  silently pointed it at a different tag. Nothing errors; the screen just shows
  the wrong number, in the right units, for a tag that looks plausible.
- NodeIds are now strings derived from the tag name
  (`ns=2;s=PLC_PRG/Baja_Temp`), which is stable across restarts, readable in a
  client's browse tree, and the thing you actually want to write down as an OPC
  item path.

**Upgrade note:** any OPC client bound to the old numeric ids must be
re-pointed. Browse paths are unchanged, so a client that browses rather than
hardcodes ids is unaffected.

## [4.1.16] - 2026-08-13: Computed Tags Are Tags, Plus Energy And Clocks

### Changed

- **Computed tags are authored through the tag API like everything else.** They
  were the last thing still requiring chart values: `config.publishers.
  data_transformation.computed_tags`. But a computed tag has a name, a type and
  a value on the wire — it is a tag. Declare `simulation_type: computed` with an
  `expression` and `dependencies` in the tag definition and it is created,
  persisted and deleted through the same API as the rest. The server collects
  them and replaces the transformation publisher's set wholesale, so deleting
  one actually stops it being computed instead of leaving it running forever

### Added

- **`accumulate`** — integrates another tag over time, for energy counters.
  kWh is the integral of kW, not a counter that ticks: `increment` climbs at a
  fixed rate regardless of load, so a site drawing 20 kW and one drawing 140 kW
  would total identically and the counter would visibly disagree with the power
  reading next to it on the same screen. The running total is kept at full
  precision in state rather than read back from the published value — rounding
  a per-scan increment for display and then accumulating from it lost exactly
  10% over one simulated hour
- **`clock`** — exposes hour/minute/second of local time. HMIs commonly show
  the plant clock from tags rather than the client's, and simulating those with
  `random` puts a number that is not a time on the screen

## [4.1.15] - 2026-08-13: Tags Belong In The App, Not In The Chart

### Changed — tag sets are no longer a chart concern

`config.tags` now defaults to **empty**, and a site's tag list does not belong
in it. Tags are created in the running application — the web UI, or
`POST /api/tags/create` and `/api/tags/bulk` — and EmberBurn persists them to
its data volume, so they survive restarts, upgrades and rescheduling.

Two things had to be fixed before that was actually true:

- **A tag created through the API never simulated.** `create_tag` routed through
  `write_callback` → `write_tag`, which registers a tag as
  `{"simulate": False}` and discards everything else. `simulation_type`, `min`,
  `max` and every model-specific key were kept only in the REST publisher's own
  metadata dict, which nothing reads when updating values. So a tag made in the
  UI sat there at its initial value forever, and the only way to get a
  simulating tag was to bake it into the chart. Added
  `OPCUAServer.define_tag(name, definition)` and a `define_callback`, which
  registers the type, the full simulation config and the metadata
- **Nothing survived a restart.** Runtime-authored definitions are now written
  to `EMBERBURN_TAG_STORE` (default `/app/data/tags.json`, i.e. the persistent
  volume) and layered over the config file at startup. Written via a temp file
  and atomic replace, so a restart mid-import cannot leave a store that fails
  to parse. A corrupt store is logged and skipped rather than taking startup
  down with it. Deletes persist too, or the tag returns on the next restart
- `/api/tags/bulk` writes the store once for the whole import instead of once
  per tag, and passes model-specific keys through verbatim — an allow-list
  would silently drop the keys of any model it had not been taught

**Note for anyone automating this:** EmberBurn refuses anonymous writes. With no
`EMBERBURN_API_KEY` configured it generates an ephemeral per-pod token that the
web UI receives and no external caller can know, so a seeding script needs a
configured key (`security.apiKey` / `security.existingSecret`).

### Fixed — the chart's config was never read

- **The chart's tags and publishers did nothing at all.** The chart mounted
  `tags.json` and `publishers.json` as two ConfigMaps, but `opcua_server.py`
  takes a single `-c` file and reads `tags` and `publishers` as sections of it.
  No template emitted `command:`/`args:`, so the image `CMD` won and the pod ran
  `config/config_web_ui.json` from inside the image — ten demo tags, every
  publisher off. Verified on the live Fragua deployment: both files were mounted
  under `/app/config/` and neither was ever opened. Every value anyone set in
  `config.tags` or `config.publishers` since the chart existed was ignored,
  silently, while the pod reported healthy
- Chart now renders ONE ConfigMap containing `{"tags": …, "publishers": …}` and
  passes `-c /app/config/emberburn.json`
- **`config.publishers.sparkplug` → `config.publishers.sparkplug_b`.**
  `publishers.py` reads `sparkplug_b`, as does every config file in the image.
  The chart wrote a key nothing looked at, so `enabled: true` was a no-op even
  once the file was loadable. `questions.yaml` and `NOTES.txt` updated to match
- **Tags with `simulate: false` were never published.** The update loop skipped
  them before reaching the publish call, so setpoints, mode strings and anything
  written by the transformation publisher were declared in the Sparkplug DBIRTH
  and then never sent again. Values are now published every scan whether or not
  the tag is simulated
- **`timestamp or time.time()` treated a legitimate `0.0` as absent** in the
  alarms and transformation publishers. Harmless where a timestamp is only
  recorded, wrong where one is subtracted — it corrupted alarm on-delays and
  rolling windows

### Added

- **Five behavioural simulation types.** `random`/`sine`/`increment` are
  independent and stateless, which makes `bool` + `random` a coin flip every
  scan and leaves no tag related to any other. Sites do not behave that way:
  - `duty_cycle` — runs on/off for configured durations, with jitter
  - `event` — rare pulse of random duration with exponentially distributed
    gaps, and an `overrun_probability` that occasionally stretches one past its
    normal length so duration alarms have something to catch
  - `walk` — bounded random walk with optional drift and `reset_on_max`, for
    things that creep toward a limit and then get serviced
  - `thermostat` — pulled toward `setpoint - band` while a driver boolean is
    on, drifting toward `ambient` when it is off
  - `follows` — mirrors another tag after a lag, with `mismatch_probability`
    for a feedback that sticks, which is what command/feedback alarms exist for
- **`hysteresis`** — two-position control of a device from a process tag, with
  a differential and short-cycle protection. Prefer it over `duty_cycle`
  wherever the plant has a controller: a duty cycle is open-loop, so its
  process settles wherever the rates happen to balance rather than at setpoint,
  and wanders whenever anything perturbs it. Simulations now evaluate in rank
  order (independent → `hysteresis` → `thermostat`/`follows`) so a control loop
  resolves in the physically correct direction
- **`delay_seconds` on alarm rules** — an on-delay, distinct from
  `debounce_seconds`, which only rate-limits notifications for an alarm already
  raised. Process alarms are specified as delays ("High-High -12, 10 min
  delay"); without one, a room past its limit for a single scan is an alarm
- **Computed tags accept aliased dependencies** — `dependencies` may be a
  `{variable: tag_name}` mapping. Required for UNS-style names, since
  `Power/Meter_01/CurrentA` is three divisions to `eval()`, not a variable
- **`window_seconds` on a computed tag** — rolling time-window average, so a
  "rolling 15-minute demand" point is one, rather than instantaneous power under
  a misleading name
- `test_simulation.py` — 36 checks over the models, the alarm on-delay and the
  computed-tag changes

### Note

- Alarm rules match on **tag name**. The `"tag": "ns=2;i=2"` OPC node ids in the
  bundled example configs match nothing and have never fired

## [4.1.14] - 2026-08-10: Revert The groupId Derivation

### Reverted

- **`config.publishers.sparkplug.group_id` is a plain value again.** 4.1.13
  derived it from `tenantLabels."embernet.ai/tenant"` and failed the render when
  that label was absent or disagreed. It was wrong about how this cluster
  deploys: App Store installs here carry **no tenantLabels at all**. The live
  `ignition-edge-fragua-edge-01`, `ignition-edge-fragua-edge-02` and
  `codesys-pod` HelmChart CRDs have none, because the dashboard only injects
  them when a deploy carries tenant context and these did not. So the
  derivation made the chart fail to render on precisely the path that installs
  it, which is the opposite of a safety feature
- Set `group_id` per deploy in the CRD's `valuesContent`, the way every other
  per-deploy setting is set here. The live ignition-edge CRDs carry
  `persistence.storageClass` and `gateway.heap.max` exactly that way

### Kept

- The default stays empty rather than returning to `"Fireball"`. A non-empty
  default is a wrong answer pre-filled for every tenant that is not Fireball,
  and it fails quietly: the broker refuses the publish and returns failure
  rather than raising, so the gateway looks healthy and sends nothing
- Credentials from a Secret via `existingSecret` / `usernameKey` /
  `passwordKey`, unchanged from 4.1.13

### Known issue, not fixed here

- `tenantLabels` are rendered as Kubernetes labels, and the dashboard injects
  `embernet.ai/deployed-by` with the caller's **email**
  (`store.go:757`, `:851`; the field is documented as "Email of user initiating
  deployment" and is not passed through `sanitizeLabelValue`). `@` is not legal
  in a label value, so any deploy that does carry tenant context fails on all
  three Services and the Deployment. Reproduced by hand. Left alone because it
  is a dashboard/contract question, not this chart's to decide

## [4.1.13] - 2026-08-09: Sparkplug Credentials, Actually Shipped

AnvilMQ enforces per-user ACLs (`userManagement.enabled` has been the anvilmq
chart default since 2.0.11), so every MQTT publisher needs a credential and a
topic namespace that matches it. Both halves of that existed in the tree and
neither was in anything deployable.

### Fixed: the release that never happened

- **Published chart 4.1.12 contained no `EMBERBURN_SPARKPLUG_*` env block.** The
  two Sparkplug-credential commits landed *after* the 4.1.12 chart was published,
  and `release.yml` skips a version already indexed, so nothing republished. A
  deploy setting `config.publishers.sparkplug.existingSecret` rendered no
  environment variables at all
- **No image read them either.** `docker-publish.yml` only builds on a `v*` tag
  and the `publishers.py` change is in no released tag, so even a correct chart
  would have run against an image that ignores the variables
- Net effect: EmberBurn would have come up healthy, reported nothing wrong, and
  published nothing. Chart `version`, `appVersion`,
  `catalog.cattle.io/upstream-version` and the values image tag all move to
  4.1.13 together so the CI gate comparing them passes

### Changed: groupId is derived, not typed

- `config.publishers.sparkplug.group_id` now defaults to **empty** and resolves
  from `tenantLabels."embernet.ai/tenant"`, which the dashboard already injects
  at deploy time. groupId **is** the tenant slug. AnvilMQ scopes a credential to
  `spBv1.0/<tenant>/#`, so a groupId that is not that slug publishes outside the
  grant and the broker refuses every message, returning failure rather than
  raising, which is how it stays invisible
- The old default was `"Fireball"`: a wrong answer pre-filled for every tenant
  that is not Fireball, waiting to be deployed unchanged. The label deciding who
  can see the app now also decides the topic namespace, so the two cannot drift
- An explicit `group_id` still wins, so deliberate overrides remain possible. If
  it disagrees with the tenant label the render **fails** rather than guessing;
  with neither set and Sparkplug enabled it also fails, rather than inventing a
  namespace

### Security

- Broker credentials come from a Secret via `existingSecret` / `usernameKey` /
  `passwordKey`, mirroring the Ignition-Edge-Pod convention. The rendered
  publishers ConfigMap carries only non-secret settings. Verified that the
  password renders empty there while the env var resolves from the Secret

## [4.1.12] - 2026-07-21: Edge-Sized Storage

### Fixed

- **PVC default dropped to 2Gi.** Longhorn on the Fragua edges runs
  `default-replica-count=3` at `storage-over-provisioning-percentage=100` with
  most of each node's disk already scheduled, so the previous request sat Pending
  on `insufficient storage; precheck new replica failed` and the pod never
  started. The SQLite persistence file is small; the request had been sized for a
  historian EmberBurn does not run

### Documentation

- OPC UA hardening notes describe what the chunk guard protects and why, without
  publishing a usable recipe for the attack it blocks

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
