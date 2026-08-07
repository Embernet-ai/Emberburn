# EmberBurn: dashboard app tile icon

**Status: resolved in the chart as of 4.1.9. No catalog registration required.**

This directory previously held a store-catalog registration spec. That was based
on `documentation/HELM_CHART_REQUIREMENTS (1).md`, which states the dashboard
resolves the icon from `pod.Labels["embernet.ai/app-icon"]`. **That document is
wrong**, and the EmberNET App Store Chart Contract (generated 2026-07-19 against
dashboard v4.1.34, derived from the Go source) says so explicitly in its §9.

The correct contract:

- `embernet.ai/app-icon` is an **annotation**, never a label: label values
  cannot contain `/` or `:` (contract §3).
- It is read from **both pod and Service annotations** (`client.go:307-309`).
  Setting it only on the Service leaves node cards showing a generic glyph
  (contract §9.5).

## What the chart now does

`emberburn.appIcon` in `_helpers.tpl` emits the EmberBurn logo as an embedded
`data:image/png;base64` URI (128x128, ~8.7KB), applied as an annotation to both
the pod template and the web UI Service.

A data URI was chosen over the alternatives because:

- **An external URL** (`avatars.githubusercontent.com`, the previous default)
  cannot resolve in an air-gapped Embernet cluster, this was the original bug.
- **A pod-relative path** (`/static/web/images/...`) resolves against whichever
  origin the dashboard renders the tile from, not against the pod.
- **A data URI** is origin-independent and needs no network at all.

Override with `embernet.appIcon` if your cluster can reach a real URL.

Regenerate the embedded icon after changing the source artwork:

```bash
python scripts/build-chart-icon.py
```

Source of truth: `static/images/emberburn-chart-icon.png`.

## Assets

Square-padded renders remain here in case the store catalog wants its own copy
for the app browse/detail views, which are separate from the running-app tile:

| File | Size |
|------|------|
| `emberburn-512.png` | 512x512 |
| `emberburn-256.png` | 256x256 |
| `emberburn-128.png` | 128x128 |
| `emberburn-64.png` | 64x64 |
| `emberburn-128.datauri.txt` | inline `data:` URI |

Note `static/images/fireball.png` is the **Fireball Industries** corporate
shield, not the EmberBurn product logo. The chart's `embernet.appIcon` default
used to point at it. Do not use it for EmberBurn.

## Docs needing reconciliation

Two in-repo documents contradict the source-derived contract and should be
corrected or retired:

1. `documentation/HELM_CHART_REQUIREMENTS (1).md`: says the icon comes from pod
   *labels* via store-catalog cross-reference. Contract §9.5 says otherwise.
2. `.agent/APP_STORE_DEPLOYMENT_FLOW.md`: cited by chart v4.1.8 (`507192f`) as
   requiring a full icon URL, which is what reintroduced the external GitHub
   avatar. Contract §9 lists seven ways this document is out of date.
