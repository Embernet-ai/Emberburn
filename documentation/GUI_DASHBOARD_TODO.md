# EmberBurn GUI Dashboard - Issue Resolution TODO

**Created:** March 4, 2026  
**Status:** Ready for Phased Execution  
**Priority:** Critical

---

## Summary

Review of `App_Integration_Guide.md` and the EmberBurn codebase revealed **1 critical issue** preventing the `/dashboard` route from functioning correctly.

---

## Phase 1: Critical Fix (Immediate)

### Issue 1.1: Missing `dashboard.html` Template: BROKEN ROUTE

**File:** `web_app.py` (Lines 27-29)  
**Severity:** 🔴 Critical  
**Impact:** Navigating to `/dashboard` returns HTTP 500 error

**Current Code (Broken):**
```python
@web_ui.route('/dashboard')
def dashboard():
    """Dashboard view."""
    return render_template('dashboard.html')  # ❌ Template does not exist
```

**Root Cause:**  
The route references `dashboard.html`, but only these templates exist:
- `index.html` ← This IS the actual dashboard
- `tags.html`
- `publishers.html`
- `alarms.html`
- `config.html`
- `tag_generator.html`
- `base.html`

**Fix Option A (Recommended): Redirect to Index:**
```python
from flask import redirect, url_for

@web_ui.route('/dashboard')
def dashboard():
    """Dashboard view - redirect to main index."""
    return redirect(url_for('web_ui.index'))
```

**Fix Option B: Remove Redundant Route:**
Simply delete lines 27-29 from `web_app.py`. The main dashboard is already served at `/`.

**Verification Steps:**
1. Start the server: `python opcua_server.py -c config/config_web_ui.json`
2. Navigate to `http://localhost:5000/`: Should show dashboard ✓
3. Navigate to `http://localhost:5000/dashboard`: Currently returns 500 error
4. After fix, `/dashboard` should redirect to `/` or show dashboard

---

## Phase 2: Verification Checklist

After applying Phase 1 fix, verify all GUI routes work:

| Route | Template | Status |
|-------|----------|--------|
| `/` | `index.html` | ✅ Working |
| `/dashboard` | N/A (redirect) | ❌ Needs fix |
| `/tags` | `tags.html` | ✅ Working |
| `/tag-generator` | `tag_generator.html` | ✅ Working |
| `/publishers` | `publishers.html` | ✅ Working |
| `/alarms` | `alarms.html` | ✅ Working |
| `/config` | `config.html` | ✅ Working |
| `/health` | JSON response | ✅ Working |

---

## Phase 3: Integration Verification

Verify the app works with the Embernet Dashboard ecosystem as documented in `App_Integration_Guide.md`:

### 3.1 Required Helm Labels (Verified in `helm/opcua-server/`)

- [ ] `embernet.ai/store-app: "true"`: Required for dashboard visibility
- [ ] `embernet.ai/gui-type: "web"`: EmberBurn has web UI
- [ ] `embernet.ai/gui-port: "5000"`: Flask runs on port 5000
- [ ] `embernet.ai/app-name: "Emberburn"`: Display name
- [ ] `app: emberburn`: Service selector

### 3.2 iframe Compatibility

EmberBurn uses Flask with no restrictive headers by default, so iframe embedding works out of the box.

### 3.3 API Endpoints (All Verified Working)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/tags` | GET | Get all tag values |
| `/api/tags/<name>` | GET/POST/PUT/DELETE | CRUD operations |
| `/api/publishers` | GET | Get publisher statuses |
| `/api/alarms/active` | GET | Get active alarms |
| `/api/health` | GET | Health check |
| `/metrics` | GET | Prometheus metrics |

---

## Execution Commands

```bash
# Phase 1: Apply fix to web_app.py
# Edit web_app.py and change the /dashboard route

# Phase 2: Test locally
cd c:\Users\admin\Documents\GitHub\Emberburn
python opcua_server.py -c config/config_web_ui.json

# Open browser and verify:
# http://localhost:5000/           (dashboard)
# http://localhost:5000/dashboard  (should redirect or show dashboard)
# http://localhost:5000/tags       (tag monitor)
# http://localhost:5000/publishers (publishers)

# Phase 3: Build and deploy Docker image
docker build -t emberburn:latest .
docker run -p 5000:5000 emberburn:latest
```

---

## Files Modified

| File | Change | Phase |
|------|--------|-------|
| `web_app.py` | Fix `/dashboard` route | Phase 1 |

---

## Completion Criteria

- [ ] `/dashboard` route no longer returns 500 error
- [ ] All 7 GUI routes render correctly
- [ ] API endpoints respond as expected
- [ ] Docker container starts and serves dashboard
- [ ] Integration with Embernet Dashboard verified (requires K8s environment)

---

## Notes

The `App_Integration_Guide.md` documentation is accurate for Kubernetes/Helm integration. The only code issue found was the missing `dashboard.html` template, which is a simple fix.

**Estimated Time to Complete:** 5 minutes for Phase 1, 15 minutes for full verification.
