# Emberburn UI Redesign: OPC UA / IEC 62541 Industrial Protocol Tag Generator

> **Specification for updating the Emberburn web interface to match the Embernet Industrial Dashboard design language, and adding an OPC UA tag generator/creator UI.**
>
> **Source Repository:** `Small-Application/` (GitHub: embernet-ai/Emberburn)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Current Codebase Inventory](#2-current-codebase-inventory)
3. [Design Language: Match the Dashboard](#3-design-language-match-the-dashboard)
4. [Dark Mode Implementation](#4-dark-mode-implementation)
5. [Header & Navigation Migration](#5-header--navigation-migration)
6. [OPC UA Tag Generator: Feature Spec](#6-opc-ua-tag-generator-feature-spec)
7. [Tag Generator UI Layout](#7-tag-generator-ui-layout)
8. [OPC UA Server Integration (Existing)](#8-opc-ua-server-integration-existing)
9. [Tag Data Model](#9-tag-data-model)
10. [API Endpoints](#10-api-endpoints)
11. [Helm Chart Compliance & Namespace Fix](#11-helm-chart-compliance--namespace-fix)
12. [Implementation Phases](#12-implementation-phases)

---

## 1. Overview

**Emberburn** is an Embernet industrial application deployed via Helm chart. This document specifies:

1. **UI redesign**: Restyle Emberburn's existing Python Flask web interface to match the Embernet Industrial Dashboard (dark mode default, same color palette, header-based nav instead of sidebar, Embernet/Fireball branding)
2. **OPC UA Tag Generator**: Extend the existing tag *monitor* into a tag *generator/creator* UI for creating, browsing, and managing OPC UA / IEC 62541 (commonly referenced as "APCUA/15") industrial protocol tags via the already-running `opcua` Python server

The goal is visual and functional consistency across the entire Embernet platform. When a user clicks "Launch UI" on Emberburn from the Industrial Dashboard, the app should feel like a native extension of the dashboard, not a separate product.

---

## 2. Current Codebase Inventory

### Application Stack

| Component | Technology | File |
|-----------|-----------|------|
| Web Server | Python Flask Blueprint | `web_app.py` |
| OPC UA Server | Python `opcua` library | `opcua_server.py` |
| Tag Config | JSON file | `tags_config.json` |
| Templates | Jinja2 | `templates/*.html` |
| Styles | Single CSS | `static/css/style.css` (489 lines) |
| JavaScript | Vanilla JS, 6 modules | `static/js/*.js` |
| Helm Chart | v1.0.6 / appVersion 1.0.3 | `helm/opcua-server/` |

### Existing Routes (`web_app.py`)

| Route | Template | Purpose |
|-------|----------|---------|
| `/` | `index.html` | Dashboard, stat cards (Active Tags, Publishers, Alarms) + live tag table |
| `/dashboard` | `dashboard.html` | Alternate dashboard view |
| `/tags` | `tags.html` | Tag Discovery & Monitor, search, category filter, tag table with details modal |
| `/publishers` | `publishers.html` | Publisher management grid (MQTT, InfluxDB, Modbus, etc.) |
| `/alarms` | `alarms.html` | Active alarm monitoring |
| `/config` | `config.html` | Server info + quick actions (Restart, Export, Import, Logs) |

### Existing JavaScript Modules (`static/js/`)

| File | Purpose |
|------|---------|
| `api.js` | `EmberBurnAPI` class, wraps `/api/tags`, `/api/publishers`, `/api/alarms/active`, `/api/health` |
| `dashboard.js` | Dashboard auto-updater, fetches tags/publishers/alarms every 2s |
| `tags.js` | Tag discovery via `/api/tags/discovery`, search, category filter, details modal |
| `publishers.js` | Publisher grid rendering and toggle |
| `alarms.js` | Alarm list rendering |
| `app.js` | Global utilities (escapeHTML, formatTimestamp, AutoUpdater class) |

### Existing CSS Theme (`static/css/style.css`)

```css
/* CURRENT fire theme — will be replaced */
:root {
    --flame-orange: #ff6b35;   /* → becomes --ember-red: #E31837 */
    --flame-red: #ff3b3b;
    --fire-yellow: #ffb347;
    --ember-dark: #1a1a1a;     /* → becomes --portal-bg: #121212 */
    --ember-gray: #2d2d2d;     /* → becomes --card-bg: #1E1E1E */
    --smoke-gray: #555;
    --ash-light: #e0e0e0;
    --success-green: #00ff88;
    --error-red: #ff4444;
    --warning-yellow: #ffaa00;
    --card-bg: #2d2d2d;
}
```

### Existing Layout (`templates/base.html`)

The current layout uses a **fixed sidebar** with ASCII art logos:

```
┌──────────────────────────────────────────────────┐
│ ┌─────────┐ ┌──────────────────────────────────┐ │
│ │ SIDEBAR  │ │  MAIN CONTENT                   │ │
│ │          │ │                                  │ │
│ │ ASCII    │ │  {% block content %}             │ │
│ │ EMBERBURN│ │                                  │ │
│ │ LOGO     │ │                                  │ │
│ │          │ │                                  │ │
│ │ 🏠 Home  │ │                                  │ │
│ │ 📊 Tags  │ │                                  │ │
│ │ 📡 Pubs  │ │                                  │ │
│ │ 🚨 Alarm │ │                                  │ │
│ │ ⚙️ Config│ │                                  │ │
│ │          │ │                                  │ │
│ │ FIREBALL │ │                                  │ │
│ │ ASCII    │ │                                  │ │
│ └─────────┘ └──────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

**This must change to a header-based layout matching the Industrial Dashboard.**

### Existing Tag Configuration (`tags_config.json`)

10 tags pre-configured with simulation:
- `Temperature` (float, random 15-25)
- `Pressure` (float, random 99-103)
- `Flow` (float, random 40-60)
- `FlowRate` (float, sine wave)
- `Counter` (int, increment with rollover at 1000)
- `TotalCount` (int, increment no rollover)
- `Status` (string, static "Running")
- `AlarmMessage` (string, static "No Alarms")
- `IsRunning` (bool, static true)
- `AlarmActive` (bool, random)

### Existing OPC UA Server (`opcua_server.py`)

The OPC UA server **already exists and works**. Key capabilities:
- Creates tags dynamically from `tags_config.json`
- Supports types: `int`, `float`, `string`, `bool`
- Simulation modes: `random`, `increment`, `sine`, `static`
- Tag metadata: type, description, units, min/max, category, quality, writable
- `write_tag()` method for runtime tag creation + value writes
- Publisher integration (MQTT, REST, GraphQL, Prometheus, etc.)
- Runs on `opc.tcp://0.0.0.0:4840/freeopcua/server/`

**What we are adding:** A web UI to create/edit/delete tags at runtime via the existing `write_tag()` and server APIs, not a new OPC UA server.

---

## 3. Design Language: Match the Dashboard

### Color Palette Migration

The core change is remapping the fire/orange theme to the Embernet red design system. **Edit `static/css/style.css`:**

```css
/* REPLACE the existing :root block */
:root {
    /* ── OLD → NEW mapping ── */
    /* --flame-orange: #ff6b35  → --ember-red: #E31837     (primary accent)  */
    /* --flame-red:    #ff3b3b  → --ember-red-hover: #c21530 (hover state)  */
    /* --fire-yellow:  #ffb347  → stays for value highlights                 */
    /* --ember-dark:   #1a1a1a  → --portal-bg: #121212     (page bg)        */
    /* --ember-gray:   #2d2d2d  → --card-bg: #1E1E1E       (card bg)        */
    /* --smoke-gray:   #555     → --border-color: #333333  (borders)        */
    /* --ash-light:    #e0e0e0  → --text-main: #E0E0E0     (primary text)   */

    /* Primary */
    --ember-red: #E31837;
    --ember-red-hover: #c21530;

    /* Dark Mode (Default) */
    --portal-bg: #121212;
    --card-bg: #1E1E1E;
    --text-main: #E0E0E0;
    --text-sub: #aaaaaa;
    --border-color: #333333;
    --shadow: 0 4px 8px rgba(0, 0, 0, 0.5);

    /* Keep for value highlights */
    --fire-yellow: #ffb347;

    /* Light Mode */
    --portal-bg-light: #f4f6f8;
    --card-bg-light: #ffffff;
    --text-main-light: #333333;
    --text-sub-light: #666666;
    --border-color-light: #e0e0e0;

    /* Status Colors — keep existing names for JS compatibility */
    --success-green: #28a745;
    --warning-yellow: #ff9800;
    --error-red: #dc3545;
    --info: #17a2b8;
}
```

### CSS Find-and-Replace Checklist

After replacing `:root`, do a global find-and-replace across `static/css/style.css`:

| Find | Replace With | Notes |
|------|-------------|-------|
| `var(--flame-orange)` | `var(--ember-red)` | All accent colors, borders, focus rings, scrollbar |
| `var(--flame-red)` | `var(--ember-red-hover)` | Scrollbar hover, hover states |
| `var(--ember-dark)` | `var(--portal-bg)` | Page background, form inputs |
| `var(--ember-gray)` | `var(--card-bg)` | Cards, publisher cards, sidebar (then remove sidebar) |
| `var(--smoke-gray)` | `var(--border-color)` | Borders, table rows, loading text |
| `var(--ash-light)` | `var(--text-main)` | All primary text |
| `rgba(255, 107, 53, 0.3)` | `rgba(227, 24, 55, 0.3)` | Box shadows (publisher hover, focus glow) |

### Typography

```css
/* ADD — the dashboard uses Inter */
body {
    font-family: 'Inter', 'Segoe UI', Roboto, sans-serif;
}
```

### Card Style

The existing `.card` in `style.css` is close, update border-radius and hover behavior:

```css
.card {
    background: var(--card-bg);
    border-radius: 8px;        /* was 12px */
    border: 1px solid var(--border-color);
    box-shadow: var(--shadow);
    padding: 20px;
    margin-bottom: 20px;
    transition: border-color 0.2s;
}

.card:hover {
    border-color: var(--ember-red);   /* was --flame-orange */
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 15px;
    font-weight: 600;
    font-size: 1.1em;
    color: var(--text-main);
}
```

### Buttons

```css
.btn-primary {
    background: var(--ember-red);
    color: white;
    border: none;
    padding: 8px 20px;
    border-radius: 4px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s;
}

.btn-primary:hover {
    background: #c21530;
}

.btn-secondary {
    background: transparent;
    color: var(--text-main);
    border: 1px solid var(--border-color);
    padding: 8px 20px;
    border-radius: 4px;
    cursor: pointer;
}

.btn-secondary:hover {
    border-color: var(--ember-red);
    color: var(--ember-red);
}
```

---

## 4. Dark Mode Implementation

**Dark mode is the default.** Match the dashboard's approach exactly:

```javascript
// On page load — default to dark if no preference stored
(function () {
    const stored = localStorage.getItem('theme');
    let isDark = true; // Default

    if (stored === 'light') {
        isDark = false;
    } else if (stored === 'dark') {
        isDark = true;
    } else {
        // No preference — default to dark
        isDark = true;
        localStorage.setItem('theme', 'dark');
    }

    if (isDark) {
        document.body.classList.add('dark-mode');
    }
})();

// Toggle function
function toggleTheme() {
    const isDark = document.body.classList.toggle('dark-mode');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');

    // Swap logo
    const logo = document.getElementById('header-logo');
    if (logo) {
        logo.src = isDark
            ? '/static/images/embernet-white.png'
            : '/static/images/embernet.png';
    }
}
```

The `dark-mode` class overrides CSS variables:

```css
body.dark-mode {
    --portal-bg: #121212;
    --card-bg: #1E1E1E;
    --text-main: #E0E0E0;
    --text-sub: #aaaaaa;
    --border-color: #333333;
    --shadow: 0 4px 8px rgba(0, 0, 0, 0.5);
}
```

---

## 5. Header & Navigation Migration

### What Changes

The current `templates/base.html` uses a **240px fixed left sidebar** with ASCII art logos for "EMBERBURN" and "Fireball Industries", plus emoji nav links (`🏠 Dashboard`, `📊 Tags`, `📡 Publishers`, `🚨 Alarms`, `⚙️ Config`).

**This must be replaced with a horizontal header + full-width content layout**, matching the Industrial Dashboard.

### Remove from `base.html`

Delete the entire `<div class="sidebar">...</div>` block (approximately lines 14-80), which includes:
- ASCII art pre-formatted logos
- Nav links (`<a href="/" ...>🏠 Dashboard</a>`, etc.)
- Sidebar footer with "Fireball Industries" ASCII art
- The `.main-content { margin-left: 240px; }` wrapper

### Remove from `style.css`

Delete these rule blocks:
- `.sidebar` (fixed left, width 240px, background ember-dark)
- `.sidebar .logo` (padding, text-align, border-bottom)
- `.sidebar .logo pre` (ASCII art monospace styling)
- `.sidebar nav a` (sidebar link styling)
- `.sidebar nav a:hover`, `.sidebar nav a.active`
- `.sidebar .sidebar-footer`
- `.main-content` margin-left rule

### Add to `base.html`: New Header

Replace the sidebar with this header block before `{% block content %}`:

```html
<!-- NEW: Header matching Industrial Dashboard -->
<div class="header">
    <div class="header-left">
        <div class="logo-container">
            <img id="header-logo" src="{{ url_for('web_ui.static', filename='images/embernet-white.png') }}"
                 alt="Embernet" class="logo-image" />
        </div>
        <span class="app-title">Emberburn</span>
    </div>
    <div class="header-right">
        <nav class="nav-bar">
            <a href="/" class="nav-link {% if request.path == '/' %}active{% endif %}">Dashboard</a>
            <a href="/tags" class="nav-link {% if request.path == '/tags' %}active{% endif %}">Tags</a>
            <a href="/tag-generator" class="nav-link {% if request.path == '/tag-generator' %}active{% endif %}">Tag Generator</a>
            <a href="/publishers" class="nav-link {% if request.path == '/publishers' %}active{% endif %}">Publishers</a>
            <a href="/alarms" class="nav-link {% if request.path == '/alarms' %}active{% endif %}">Alarms</a>
            <a href="/config" class="nav-link {% if request.path == '/config' %}active{% endif %}">Config</a>
        </nav>
        <button class="theme-toggle" onclick="toggleTheme()">
            <span id="theme-toggle-icon">☀️</span>
        </button>
        <div class="company-logo-container">
            <img src="{{ url_for('web_ui.static', filename='images/fireball.png') }}"
                 alt="Fireball" class="company-logo-image" />
        </div>
    </div>
</div>
```

> **Note:** URLs use Flask's `url_for('web_ui.static', ...)` because `web_app.py` registers the Blueprint with `static_url_path='/static/web'`. Image files must be placed in `static/images/`.

### Add to `style.css`: Header Styles

```css
/* ── Header (replaces sidebar) ── */
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 30px;
    padding-bottom: 20px;
    border-bottom: 2px solid var(--border-color);
}

.header-left {
    display: flex;
    align-items: center;
    gap: 15px;
}

.logo-image {
    height: 50px;
    width: auto;
    max-width: 200px;
    object-fit: contain;
}

.app-title {
    font-size: 1.4em;
    font-weight: 700;
    color: var(--ember-red);
    letter-spacing: 1px;
    text-transform: uppercase;
}

.header-right {
    display: flex;
    align-items: center;
    gap: 15px;
}

.nav-bar {
    display: flex;
    gap: 8px;
}

.nav-link {
    color: var(--text-sub);
    text-decoration: none;
    font-weight: 600;
    padding: 5px 12px;
    border-radius: 4px;
    transition: all 0.2s;
    font-size: 0.9em;
}

.nav-link:hover,
.nav-link.active {
    color: white;
    background: var(--ember-red);
}

.theme-toggle {
    background: transparent;
    border: 1px solid var(--border-color);
    padding: 5px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1.2em;
}

.company-logo-image {
    height: 35px;
    width: auto;
    object-fit: contain;
}

/* ── Main content now full-width ── */
.main-content {
    margin-left: 0;    /* was 240px for sidebar */
    padding: 20px 30px;
}
```

### Footer

Add to `base.html` after `{% block content %}`:

```html
<div class="status-footer">
    <span>EmberNET Emberburn v1.0</span>
    <span>OPC UA: <span id="opcua-status" class="status-dot dot-green"></span> Running</span>
    <button onclick="toggleTheme()"><span id="footer-theme-icon">☀️</span></button>
</div>
```

### Static Assets Required

Create directory `static/images/` and copy these from the Industrial Dashboard's `web/static/images/`:

| File | Purpose |
|------|---------|
| `embernet-white.png` | Header logo (dark mode, default) |
| `embernet.png` | Header logo (light mode) |
| `fireball.png` | Company logo (header right) |
| `favicon-32x32.png` | Browser tab icon |

---

## 6. OPC UA Tag Generator: Feature Spec

### What Is This?

An **OPC UA Tag Generator** is a visual tool for creating and managing OPC UA (IEC 62541) address space nodes, the "tags" that PLC systems, SCADA software, and industrial equipment read/write via the OPC UA protocol.

### Key Capabilities

| Feature | Description |
|---------|-------------|
| **Create Tags** | Define new OPC UA nodes with name, data type, initial value, and access level |
| **Browse Tags** | Tree-view of the OPC UA address space, expandable folders/objects |
| **Edit Tags** | Modify tag properties (value, data type, engineering units, description) |
| **Delete Tags** | Remove tags from the address space |
| **Bulk Import** | CSV/JSON upload for mass tag creation |
| **Bulk Export** | Export current tag configuration as CSV/JSON/XML |
| **Tag Templates** | Pre-built tag sets for common industrial protocols (Modbus map, S7 variables, Allen-Bradley tags) |
| **Live Values** | Real-time display of current tag values with polling |
| **Write Values** | Manual write to tags for testing/simulation |
| **Tag Groups** | Organize tags into folders (OPC UA Objects) |
| **Alarm Configuration** | Set high/low limits, deadband, alarm severity per tag |

### Supported OPC UA Data Types

| OPC UA Type | Description | Example |
|---|---|---|
| `Boolean` | True/False | Motor Running: `true` |
| `Int16` | Signed 16-bit integer | Temperature Raw: `2841` |
| `Int32` | Signed 32-bit integer | Encoder Count: `1048576` |
| `UInt16` | Unsigned 16-bit integer | Analog Input: `32768` |
| `UInt32` | Unsigned 32-bit integer | Total Parts: `1500000` |
| `Float` | 32-bit IEEE 754 | Temperature °C: `23.5` |
| `Double` | 64-bit IEEE 754 | Latitude: `40.7128` |
| `String` | UTF-8 text | Recipe Name: `"BatchA"` |
| `DateTime` | ISO 8601 timestamp | Last Cycle: `2026-02-10T11:30:00Z` |
| `ByteString` | Raw bytes | Firmware Blob |

---

## 7. Tag Generator UI Layout

### Main View: Tag Dashboard

```
┌──────────────────────────────────────────────────────────────────────┐
│ [Emberburn Logo]                     [Dashboard][Tags][Browse]  🔥 │
│─────────────────────────────────────────────────────────────────────│
│                                                                      │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐       │
│  │  📊 Total Tags   │ │  🟢 Server Up    │ │  📡 Connected    │       │
│  │     1,247        │ │    12h 34m       │ │    3 clients     │       │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘       │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Quick Actions                                                   │ │
│  │  [+ New Tag]  [📁 Import CSV]  [📤 Export]  [📋 Template]       │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Recent Tags                                          [View All] │ │
│  │ ┌──────────────┬──────────┬──────────┬──────────┬────────────┐  │ │
│  │ │ Name         │ Type     │ Value    │ Quality  │ Actions    │  │ │
│  │ ├──────────────┼──────────┼──────────┼──────────┼────────────┤  │ │
│  │ │ Motor1.Speed │ Float    │ 1750.2   │ 🟢 Good  │ ✏️ 🗑️ 📝   │  │ │
│  │ │ Tank.Level   │ Double   │ 67.42    │ 🟢 Good  │ ✏️ 🗑️ 📝   │  │ │
│  │ │ Valve.Open   │ Boolean  │ true     │ 🟢 Good  │ ✏️ 🗑️ 📝   │  │ │
│  │ │ PLC.Heartbeat│ UInt32   │ 44291    │ 🟡 Stale │ ✏️ 🗑️ 📝   │  │ │
│  │ └──────────────┴──────────┴──────────┴──────────┴────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────┐ ┌────────────────────────────┐ │
│  │  📦 Tag Groups                    │ │  🔔 Active Alarms          │ │
│  │  ▸ Production/                   │ │  ⚠️ Tank.Level > 90%       │ │
│  │    ▸ Line1/                      │ │  🔴 Motor1.Temp > 85°C     │ │
│  │    ▸ Line2/                      │ │  ⚠️ PLC.Heartbeat stale    │ │
│  │  ▸ Utilities/                    │ │                             │ │
│  │  ▸ Quality/                      │ │                             │ │
│  └──────────────────────────────────┘ └────────────────────────────┘ │
│                                                                      │
│ [Emberburn v1.0.0]  [OPC UA: 🟢 Running]         [☀️/🌙] │
└──────────────────────────────────────────────────────────────────────┘
```

### Create Tag Modal

```
┌──────────────────────────────────────────────────────┐
│  Create New Tag                                   ✕  │
│──────────────────────────────────────────────────────│
│                                                      │
│  Tag Name:     [Production.Line1.Motor1.Speed    ]   │
│  Display Name: [Motor 1 Speed                    ]   │
│  Description:  [Main drive motor speed in RPM    ]   │
│                                                      │
│  Data Type:    [Float           ▾]                   │
│  Initial Value:[0.0                              ]   │
│  Engineering Units: [RPM                         ]   │
│                                                      │
│  Access Level: [● Read/Write  ○ Read Only]           │
│                                                      │
│  ── Alarm Configuration (optional) ──                │
│  ☐ Enable Alarms                                     │
│  High Limit:   [1800       ]  Severity: [High  ▾]   │
│  Low Limit:    [100        ]  Severity: [Low   ▾]   │
│  Deadband:     [5          ]                         │
│                                                      │
│  Parent Group: [Production/Line1  ▾]                 │
│                                                      │
│  [Cancel]                      [Create Tag] (red)    │
└──────────────────────────────────────────────────────┘
```

### Browse Tags View (Tree)

```
┌─────────────────────────────────────────────────────────────────────┐
│  OPC UA Address Space Browser                          [Refresh]    │
│─────────────────────────────────────────────────────────────────────│
│  ┌─────────────────────────┐ ┌─────────────────────────────────────│
│  │ Address Space Tree      │ │ Tag Details                         │
│  │                         │ │                                     │
│  │ ▾ 📂 Root               │ │ Node ID:  ns=2;s=Production.       │
│  │   ▾ 📂 Objects          │ │                  Line1.Motor1.Speed│
│  │     ▾ 📂 Production     │ │ Browse Name: Motor1.Speed          │
│  │       ▾ 📂 Line1        │ │ Display Name: Motor 1 Speed        │
│  │         ▸ 📂 Motor1     │ │ Data Type: Float                   │
│  │           📊 Speed ←    │ │ Value: 1750.2                      │
│  │           📊 Current    │ │ Quality: Good                      │
│  │           📊 Temp       │ │ Timestamp: 2026-02-10T11:30:00Z    │
│  │           🔘 Running    │ │ Access: Read/Write                  │
│  │         ▸ 📂 Motor2     │ │ Eng. Units: RPM                    │
│  │       ▾ 📂 Line2        │ │ Description: Main drive motor      │
│  │         ▸ 📂 Conveyor   │ │              speed in RPM           │
│  │     ▸ 📂 Utilities      │ │                                     │
│  │     ▸ 📂 Quality        │ │ [✏️ Edit] [📝 Write Value] [🗑️ Del]│
│  │                         │ │                                     │
│  └─────────────────────────┘ └─────────────────────────────────────│
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. OPC UA Server Integration (Existing)

### Architecture: Already Built

Emberburn **already has** a fully functional OPC UA server in `opcua_server.py`. No new server implementation is needed.

```
┌────────────────────────────────────────────────────────┐
│                  Emberburn Container                    │
│                                                        │
│  ┌──────────────┐     ┌───────────────────────────┐   │
│  │  Flask Web UI │     │  OPC UA Server (EXISTING)  │   │
│  │  (HTTP :5000) │────▶│  (opc.tcp://:4840)         │   │
│  │              │ API │                             │   │
│  │  EXISTING:   │     │  - 10 tags from JSON config │   │
│  │  - /tags     │     │  - random/increment/sine    │   │
│  │  - /publishers│    │  - Publisher integration     │   │
│  │  - /alarms   │     │  - Writable tags             │   │
│  │  - /config   │     │                             │   │
│  │              │     │  NEW (Tag Generator adds):   │   │
│  │  NEW:        │     │  - Dynamic tag creation      │   │
│  │  - /tag-gen  │     │  - Runtime config save       │   │
│  └──────────────┘     └───────────────────────────┘   │
│                                                        │
│  Ports exposed (per values.yaml):                     │
│    5000 → Web UI + REST API (proxied by dashboard)     │
│    4840 → OPC UA (direct access for SCADA/PLC)         │
│    8000 → Prometheus metrics                           │
│    5020 → Modbus TCP (optional)                        │
│    9001 → WebSocket (optional)                         │
└────────────────────────────────────────────────────────┘
```

### Existing Server Capabilities (`opcua_server.py`)

| Method | Line | Purpose |
|--------|------|---------|
| `load_tag_config()` | ~60 | Loads `tags_config.json` (or env-specified file) |
| `get_default_tags()` | ~95 | Fallback 5-tag config if JSON not found |
| `create_server()` | ~175 | Builds OPC UA address space from tag config |
| `write_tag(name, value)` | ~250 | Write value to existing tag OR create new tag at runtime |
| `update_tags()` | ~295 | Simulation loop, random/increment/sine per tag config |
| `generate_random_value()` | ~335 | Random value within min/max range |
| `generate_increment_value()` | ~355 | Counter with optional rollover |
| `generate_sine_value()` | ~385 | Sine wave generator |

### Key Insight: `write_tag()` Already Supports Dynamic Creation

The existing `write_tag()` method (line ~250) already handles creating new tags at runtime:

```python
def write_tag(self, tag_name: str, value):
    if tag_name in self.tags:
        var = self.tags[tag_name]["variable"]
        var.set_value(value)
    else:
        # Create new tag for transformed/computed values
        var = myobj.add_variable(idx, tag_name, value)
        var.set_writable()
        self.tags[tag_name] = {...}
```

**The Tag Generator UI simply needs REST endpoints that call this method.**

---

## 9. Tag Data Model

### Tag Object

```json
{
    "nodeId": "ns=2;s=Production.Line1.Motor1.Speed",
    "browseName": "Motor1.Speed",
    "displayName": "Motor 1 Speed",
    "description": "Main drive motor speed in RPM",
    "dataType": "Float",
    "value": 1750.2,
    "quality": "Good",
    "timestamp": "2026-02-10T11:30:00.000Z",
    "accessLevel": "ReadWrite",
    "engineeringUnits": "RPM",
    "parentGroup": "Production/Line1",
    "alarm": {
        "enabled": true,
        "highLimit": 1800,
        "lowLimit": 100,
        "highSeverity": "High",
        "lowSeverity": "Low",
        "deadband": 5,
        "state": "Normal"
    },
    "historizing": true,
    "samplingInterval": 1000
}
```

### Tag Group (OPC UA Object/Folder)

```json
{
    "nodeId": "ns=2;s=Production.Line1",
    "browseName": "Line1",
    "displayName": "Production Line 1",
    "description": "Main production line assembly area",
    "type": "Folder",
    "children": ["Motor1", "Motor2", "Conveyor", "Sensors"],
    "tagCount": 47
}
```

### Bulk Import Format (CSV)

```csv
Name,DisplayName,DataType,InitialValue,Units,Access,Group,Description
Production.Line1.Motor1.Speed,Motor 1 Speed,Float,0.0,RPM,ReadWrite,Production/Line1,Main drive motor speed
Production.Line1.Motor1.Current,Motor 1 Current,Float,0.0,A,ReadOnly,Production/Line1,Motor current draw
Production.Line1.Motor1.Running,Motor 1 Running,Boolean,false,,ReadOnly,Production/Line1,Motor on/off status
Production.Line1.Tank.Level,Tank Level,Double,0.0,%,ReadWrite,Production/Line1,Tank fill level percentage
```

---

## 10. API Endpoints

### Existing Endpoints (in `api.js` / `web_app.py`)

These already work and the Tag Generator builds on top of them:

| Method | Endpoint | Status | JS Usage |
|--------|----------|--------|----------|
| `GET` | `/api/tags` | **EXISTS** | `api.getTags()` |
| `GET` | `/api/tags/:name` | **EXISTS** | `api.getTag(name)` |
| `POST` | `/api/tags/:name` | **EXISTS** | `api.writeTag(name, value)`, writes value to tag |
| `GET` | `/api/tags/discovery` | **EXISTS** | Used by `tags.js`, returns metadata (type, units, min/max, category, quality) |
| `GET` | `/api/publishers` | **EXISTS** | `api.getPublishers()` |
| `POST` | `/api/publishers/:name/toggle` | **EXISTS** | `api.togglePublisher(name)` |
| `GET` | `/api/alarms/active` | **EXISTS** | `api.getActiveAlarms()` |
| `GET` | `/api/health` | **EXISTS** | `api.healthCheck()` |

### New Endpoints for Tag Generator

Add these to the REST API publisher (or add a new Flask Blueprint):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/tags/create` | **NEW**: Create a new OPC UA tag (calls `write_tag()`) |
| `PUT` | `/api/tags/:name` | **NEW**: Update tag properties (type, description, units, simulation) |
| `DELETE` | `/api/tags/:name` | **NEW**: Remove tag from address space |
| `POST` | `/api/tags/bulk` | **NEW**: Bulk create tags (JSON array or CSV) |
| `GET` | `/api/tags/export?format=csv` | **NEW**: Export current tag config as CSV/JSON |
| `POST` | `/api/tags/import` | **NEW**: Import tags from CSV/JSON upload |

### Tag Groups

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/groups` | List all tag groups (tree structure) |
| `POST` | `/api/groups` | Create a new group/folder |
| `PUT` | `/api/groups/:nodeId` | Rename/move a group |
| `DELETE` | `/api/groups/:nodeId` | Delete a group (and optionally its children) |

### OPC UA Server

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/opcua/status` | Server status (uptime, connected clients, tag count) |
| `POST` | `/api/opcua/restart` | Restart the OPC UA server |
| `GET` | `/api/opcua/sessions` | List active OPC UA client sessions |
| `GET` | `/api/opcua/browse?nodeId=...` | Browse address space (tree) |

### Alarms

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/alarms` | List active alarms |
| `GET` | `/api/alarms/history` | Alarm history |
| `POST` | `/api/alarms/:id/ack` | Acknowledge an alarm |

### Templates

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/templates` | List available tag templates |
| `POST` | `/api/templates/apply` | Apply a template (creates tags from preset) |

### Example Tag Templates

```json
[
    {
        "name": "3-Phase Motor",
        "description": "Standard tags for a 3-phase AC motor",
        "tags": [
            {"suffix": ".Speed", "type": "Float", "units": "RPM"},
            {"suffix": ".Current.L1", "type": "Float", "units": "A"},
            {"suffix": ".Current.L2", "type": "Float", "units": "A"},
            {"suffix": ".Current.L3", "type": "Float", "units": "A"},
            {"suffix": ".Voltage", "type": "Float", "units": "V"},
            {"suffix": ".Temperature", "type": "Float", "units": "°C"},
            {"suffix": ".Running", "type": "Boolean", "units": ""},
            {"suffix": ".Fault", "type": "Boolean", "units": ""},
            {"suffix": ".Runtime", "type": "UInt32", "units": "hours"}
        ]
    },
    {
        "name": "Tank Level System",
        "description": "Tags for a tank with level, temperature, and valve control",
        "tags": [
            {"suffix": ".Level", "type": "Double", "units": "%"},
            {"suffix": ".Temperature", "type": "Float", "units": "°C"},
            {"suffix": ".Pressure", "type": "Float", "units": "bar"},
            {"suffix": ".InletValve", "type": "Boolean", "units": ""},
            {"suffix": ".OutletValve", "type": "Boolean", "units": ""},
            {"suffix": ".HighAlarm", "type": "Boolean", "units": ""},
            {"suffix": ".LowAlarm", "type": "Boolean", "units": ""}
        ]
    },
    {
        "name": "Modbus TCP Device (40 Holding Registers)",
        "description": "Maps Modbus holding registers 40001-40040 to OPC UA tags",
        "tags": [
            {"suffix": ".HR40001", "type": "UInt16", "units": ""},
            {"suffix": ".HR40002", "type": "UInt16", "units": ""},
            "... (generated programmatically for the range)"
        ]
    }
]
```

---

## 11. Helm Chart Compliance & Namespace Fix

The Emberburn Helm chart is at `helm/opcua-server/` (Chart.yaml: `name: emberburn`, version `1.0.6`, appVersion `1.0.3`).

### CRITICAL: Namespace.yaml Causes the Ownership Error

**The file `helm/opcua-server/templates/namespace.yaml` EXISTS and is the root cause of the namespace ownership error:**

```yaml
# helm/opcua-server/templates/namespace.yaml — CURRENT (PROBLEMATIC)
{{- if .Values.namespace.create -}}
apiVersion: v1
kind: Namespace
metadata:
  name: {{ include "emberburn.namespace" . }}
  labels:
    {{- toYaml .Values.namespace.labels | nindent 4 }}
    {{- include "emberburn.labels" . | nindent 4 }}
{{- end }}
```

And in `values.yaml`:
```yaml
namespace:
  name: emberburn
  create: true    # ← THIS IS THE PROBLEM
```

**When a second Helm release tries to manage the same namespace, or if the namespace already exists from a previous failed install, Helm throws:**
```
Error: rendered manifests contain a resource that already exists.
Unable to continue with install: existing resource conflict: namespace "emberburn"
```

### Fix

**Option A: Delete the file (recommended)**
```bash
# Remove the namespace template entirely
rm helm/opcua-server/templates/namespace.yaml

# Change values.yaml
namespace:
  name: emberburn
  create: false   # ← NEVER create namespace via Helm template
```

Then install with:
```bash
helm install emberburn ./helm/opcua-server -n emberburn --create-namespace
```

### Required Labels on Pod

The existing deployment template must include these labels for the Industrial Dashboard to discover Emberburn:

```yaml
labels:
  app: {{ include "emberburn.fullname" . }}
  app.kubernetes.io/name: {{ include "emberburn.name" . }}
  app.kubernetes.io/instance: {{ .Release.Name }}
  app.kubernetes.io/managed-by: {{ .Release.Service }}
  embernet.io/store-app: "true"
  embernet.io/app-name: "Emberburn"
  embernet.io/app-icon: "🔥"
```

### Required Container Ports

Verify in `deployment.yaml` that both ports are declared:

```yaml
containers:
  - name: emberburn
    ports:
      - name: http
        containerPort: 5000      # Web UI — proxied by dashboard
        protocol: TCP
      - name: opcua
        containerPort: 4840      # OPC UA — direct access for PLCs
        protocol: TCP
      - name: prometheus
        containerPort: 8000      # Prometheus metrics
        protocol: TCP
```

### Service: Already Has Multiple Port Services

The chart already has separate service templates:
- `service-webui.yaml`: port 5000
- `service-opcua.yaml`: port 4840
- `service-prometheus.yaml`: port 8000

These are correct. The Web UI service is what the dashboard's "Launch UI" proxies to.

### NO Namespace Resource in Templates

```bash
# ❌ DELETE THIS:
helm/opcua-server/templates/namespace.yaml

# ✅ Install with --create-namespace instead:
helm install emberburn ./helm/opcua-server -n emberburn --create-namespace
```

### Dynamic Resource Names: Already Correct

The existing `_helpers.tpl` uses `{{ include "emberburn.fullname" . }}` which is correct.

---

## 12. Implementation Phases

### Phase 1: UI Reskin (Estimate: 2-3 days)

Files to edit: `static/css/style.css`, `templates/base.html`, all 6 templates

- [ ] Replace `:root` CSS variables in `style.css` (Section 3 mapping table)
- [ ] Global find-replace: `var(--flame-orange)` → `var(--ember-red)` across `style.css`
- [ ] Global find-replace: `var(--ember-dark)` → `var(--portal-bg)`, etc. (full table in Section 3)
- [ ] Remove sidebar block from `templates/base.html` (the `<div class="sidebar">` block)
- [ ] Remove sidebar CSS rules from `style.css` (`.sidebar`, `.sidebar nav a`, etc.)
- [ ] Add header HTML to `base.html` (Section 5 template)
- [ ] Add header CSS to `style.css` (Section 5 styles)
- [ ] Add footer to `base.html` with OPC UA status indicator
- [ ] Create `static/images/` directory and copy `embernet-white.png`, `embernet.png`, `fireball.png`, `favicon-32x32.png` from Industrial Dashboard
- [ ] Add `<link>` to Inter font (Google Fonts) in `base.html` `<head>`
- [ ] Implement dark mode toggle with `localStorage` (Section 4)
- [ ] Update `.main-content` to `margin-left: 0` (was 240px for sidebar)
- [ ] Verify all 6 existing pages render correctly with new layout
- [ ] Test "Launch UI" through dashboard proxy: check font loading, image paths, relative URLs

### Phase 2: Tag Generator Backend (Estimate: 2-3 days)

Files to edit: `web_app.py`, `opcua_server.py`

- [ ] Add `/tag-generator` route to `web_app.py` returning new `tag_generator.html` template
- [ ] Add `POST /api/tags/create` endpoint: accepts `{name, type, initial_value, description, units, category, simulate, simulation_type, min, max}`
- [ ] Wire `POST /api/tags/create` to call `opcua_server.write_tag()` + update `self.tag_metadata`
- [ ] Add `DELETE /api/tags/:name` endpoint: removes from `self.tags` and `self.tag_metadata`
- [ ] Add `PUT /api/tags/:name` endpoint: update metadata (description, units, simulation config)
- [ ] Add `POST /api/tags/bulk` endpoint: accepts JSON array of tag definitions
- [ ] Add `GET /api/tags/export?format=csv`: exports current `tags_config.json` + runtime tags as CSV
- [ ] Add `POST /api/tags/import`: accepts CSV/JSON file upload, creates tags
- [ ] Add persistence: write runtime tag changes back to `tags_config.json` (or a `tags_runtime.json`)
- [ ] Add tag template presets (3-Phase Motor, Tank Level, Modbus) as JSON files in `config/`

### Phase 3: Tag Generator UI (Estimate: 3-4 days)

Files to create: `templates/tag_generator.html`, `static/js/tag_generator.js`

- [ ] Create `tag_generator.html`: extends `base.html`, has stat cards + quick actions + tag table
- [ ] Create `tag_generator.js`: mirrors patterns from `dashboard.js` (AutoUpdater, parallel fetch)
- [ ] Build "Create Tag" modal: form with name, type (dropdown), initial value, units, description, category, simulation config
- [ ] Build tag table with inline edit, delete, write-value actions
- [ ] Build bulk import UI: file upload (CSV/JSON) with preview table before confirm
- [ ] Build export button: downloads CSV/JSON
- [ ] Build tag template selector: dropdown of presets, preview of tags to be created, apply button
- [ ] Add `api.createTag()`, `api.deleteTag()`, `api.updateTag()`, `api.bulkCreateTags()`, `api.exportTags()`, `api.importTags()` to `api.js`

### Phase 4: Helm Chart Fixes (Estimate: 1 day)

Files to edit: `helm/opcua-server/templates/namespace.yaml`, `helm/opcua-server/values.yaml`

- [ ] Delete `helm/opcua-server/templates/namespace.yaml`
- [ ] Set `namespace.create: false` in `values.yaml`
- [ ] Ensure `embernet.io/*` labels exist on pod template in `deployment.yaml`
- [ ] Verify container ports declaration includes `http: 5000`, `opcua: 4840`, `prometheus: 8000`
- [ ] Test `helm install emberburn ./helm/opcua-server -n emberburn --create-namespace`
- [ ] Test multi-instance install (two releases, e.g., `emberburn-dev` and `emberburn-prod`)
- [ ] Test "Launch UI" from Industrial Dashboard after fresh Helm install
- [ ] Bump chart version in `Chart.yaml` and publish to Helm repo

---

## Static Assets Required

Create `static/images/` (does not currently exist) and copy from the Industrial Dashboard (`embernet-dashboard/web/static/images/`):

| File | Purpose | Destination |
|------|---------|-------------|
| `embernet-white.png` | Header logo (dark mode, default) | `static/images/embernet-white.png` |
| `embernet.png` | Header logo (light mode) | `static/images/embernet.png` |
| `fireball.png` | Company logo (header right) | `static/images/fireball.png` |
| `favicon-32x32.png` | Browser tab icon | `static/images/favicon-32x32.png` |

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `static/css/style.css` | **EDIT** | Replace `:root` vars, remove sidebar styles, add header styles |
| `templates/base.html` | **EDIT** | Remove sidebar, add header + footer, add Inter font link |
| `templates/index.html` | **VERIFY** | Should work as-is with new `base.html` layout |
| `templates/tags.html` | **VERIFY** | Should work as-is, tag monitor remains |
| `templates/publishers.html` | **VERIFY** | Should work as-is |
| `templates/alarms.html` | **VERIFY** | Should work as-is |
| `templates/config.html` | **EDIT** | Update inline colors from `var(--flame-orange)` → `var(--ember-red)` |
| `templates/tag_generator.html` | **CREATE** | New tag generator page (extends base.html) |
| `static/js/tag_generator.js` | **CREATE** | Tag generator logic (create, edit, delete, import, export) |
| `static/js/api.js` | **EDIT** | Add `createTag()`, `deleteTag()`, `updateTag()`, `bulkCreateTags()`, `exportTags()`, `importTags()` |
| `static/images/*` | **CREATE** | Copy 4 image files from Industrial Dashboard |
| `web_app.py` | **EDIT** | Add `/tag-generator` route |
| `opcua_server.py` | **EDIT** | Add REST endpoints for tag CRUD (or add new Blueprint) |
| `helm/opcua-server/templates/namespace.yaml` | **DELETE** | Root cause of namespace ownership error |
| `helm/opcua-server/values.yaml` | **EDIT** | Set `namespace.create: false` |

---

## Summary

The Emberburn UI update achieves two goals:

1. **Visual consistency**: Emberburn's existing fire/orange-themed sidebar layout is migrated to the Embernet red/dark horizontal-header design system. The current `static/css/style.css` variables map cleanly (see Section 3 table). The sidebar in `templates/base.html` becomes a header bar. All 6 existing views continue working with updated styling.

2. **OPC UA Tag Generator**: The existing tag *monitor* (`/tags` → `tags.html` → `tags.js`) and OPC UA server (`opcua_server.py` with `write_tag()` that already creates tags dynamically) are extended with a new Tag Generator page that allows creating, editing, deleting, and bulk-importing OPC UA tags at runtime. No new OPC UA server library is needed, the Python `opcua` package and server already work.

3. **Helm Chart Fix**: The `namespace.yaml` template in `helm/opcua-server/templates/` is deleted to prevent the namespace ownership error that causes installation failures when the namespace already exists. - MAY BE COMPLETED ALREADY

The result is a unified industrial platform where the dashboard provides cluster management and app deployment, and Emberburn provides the protocol-level tag engineering that industrial systems need, with a consistent look and feel across both.
