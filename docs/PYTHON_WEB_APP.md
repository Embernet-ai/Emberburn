# 🔥 EmberBurn Web UI - Python Flask Application

**Proper Python Web Application for Industrial IoT Gateway**

By Patrick Ryan, CTO - Fireball Industries

---

## What Changed?

We converted the single-file HTML/React approach to a **proper Python Flask web application** with:

✅ **Flask Blueprint Architecture** - Modular, scalable structure  
✅ **Jinja2 Templates** - Server-side rendering  
✅ **Separated Static Assets** - CSS and JavaScript properly organized  
✅ **Vanilla JavaScript** - No React, no build step, pure JS  
✅ **Python-Native** - Everything served through Flask  

---

## Project Structure

```
Small-Application/
├── web_app.py                 # Flask Blueprint for Web UI
├── templates/                 # Jinja2 templates
│   ├── base.html             # Base template with sidebar/nav
│   ├── index.html            # Dashboard view
│   ├── tags.html             # Tag monitor view
│   ├── publishers.html       # Publishers management
│   ├── alarms.html           # Alarms monitoring
│   └── config.html           # Configuration view
├── static/                    # Static assets
│   ├── css/
│   │   └── style.css         # Fire-themed styles
│   └── js/
│       ├── api.js            # API client
│       ├── app.js            # Core application logic
│       ├── dashboard.js      # Dashboard view logic
│       ├── tags.js           # Tags view logic
│       ├── publishers.js     # Publishers view logic
│       └── alarms.js         # Alarms view logic
├── publishers.py             # Updated to register Blueprint
└── opcua_server.py           # Main server (unchanged)
```

---

## How It Works

### Flask Blueprint Pattern

The **web_app.py** creates a Flask Blueprint:

```python
web_ui = Blueprint('web_ui', __name__,
                   template_folder='templates',
                   static_folder='static')
```

Routes are defined in the blueprint:
- `GET /` - Dashboard (index.html)
- `GET /tags` - Tag monitor
- `GET /publishers` - Publishers management
- `GET /alarms` - Alarms monitoring
- `GET /config` - Configuration view

### Template Inheritance

All pages extend **base.html** which provides:
- Sidebar with navigation
- ASCII art branding (Fireball Industries + EmberBurn)
- Common layout and structure
- JavaScript/CSS includes

Example:
```html
{% extends "base.html" %}
{% block content %}
  <!-- Page-specific content -->
{% endblock %}
```

### API Integration

**Static JavaScript files** handle API communication:

1. **api.js** - API client class
   ```javascript
   const api = new EmberBurnAPI();
   await api.getTags();
   await api.togglePublisher(name);
   ```

2. **Page-specific JS** - View logic
   - dashboard.js - Updates dashboard metrics
   - tags.js - Renders tag table
   - publishers.js - Manages protocol cards
   - alarms.js - Displays active alarms

3. **Auto-updating** - 2-second intervals
   ```javascript
   const updater = new AutoUpdater(updateFunction, 2000);
   updater.start();
   ```

---

## Running the Application

### 1. Start the Server

```bash
python opcua_server.py -c config/config_web_ui.json
```

The REST API publisher automatically:
1. Creates Flask app
2. Registers the **web_ui** Blueprint
3. Serves templates from `/templates`
4. Serves static files from `/static`
5. Starts on port 5000

### 2. Open Your Browser

```
http://localhost:5000/
```

You'll see:
- 🔥 **Dashboard** with live metrics and tag table
- 🏷️ **Tag Monitor** with all tags
- 📡 **Publishers** with enable/disable controls
- 🚨 **Alarms** with active alarm monitoring
- ⚙️ **Config** with system information

---

## Key Features

### Server-Side Rendering

**Jinja2 templates** render on the server:
- Faster initial load
- SEO-friendly (if that matters for industrial UIs)
- Python-native templating
- Easy to extend

### Modular JavaScript

**Separated concerns:**
- `api.js` - API communication
- `app.js` - Utilities and auto-updater
- `dashboard.js`, `tags.js`, etc. - View-specific logic

**No build step required!**
- No webpack
- No npm
- No Node.js
- Just Python and vanilla JS

### URL-Based Navigation

**Proper URLs:**
- `/` - Dashboard
- `/tags` - Tag monitor
- `/publishers` - Publishers
- `/alarms` - Alarms
- `/config` - Configuration

**Benefits:**
- Bookmarkable pages
- Browser back/forward works
- Can link directly to specific views

---

## Customization

### Adding New Pages

**1. Create template:**
```html
<!-- templates/mypage.html -->
{% extends "base.html" %}
{% block content %}
  <h1>My Page</h1>
{% endblock %}
```

**2. Add route in web_app.py:**
```python
@web_ui.route('/mypage')
def mypage():
    return render_template('mypage.html')
```

**3. Add navigation in base.html:**
```html
<li><a href="{{ url_for('web_ui.mypage') }}" class="nav-item">
    <span>🎯</span> My Page
</a></li>
```

### Customizing Styles

Edit **static/css/style.css**:

```css
:root {
    --flame-orange: #your-color;  /* Change primary color */
}
```

All styles use CSS variables for easy theming.

### Adding JavaScript Features

Create new JS file in **static/js/** and include in template:

```html
{% block extra_js %}
<script src="{{ url_for('web_ui.static', filename='js/myfeature.js') }}"></script>
{% endblock %}
```

---

## Advantages Over Single HTML File

### ✅ Python-Native
- No CDN dependencies
- Works offline
- Proper Flask integration
- Server-side rendering

### ✅ Maintainable
- Separated files (HTML, CSS, JS)
- Modular structure
- Easy to find and edit code
- Version control friendly

### ✅ Scalable
- Add new pages easily
- Extend with Flask plugins
- Database integration ready
- Authentication ready

### ✅ Professional
- Proper file structure
- Industry-standard patterns
- Production-ready architecture
- Team-friendly codebase

---

## Migration from Old UI

**Old:** Single `web/index.html` with embedded React

**New:** Proper Flask application with templates

**Breaking Changes:**
- None! Old API endpoints still work
- URL structure same (except navigation)
- Same fire theme and branding

**What to Delete:**
- `web/index.html` (optional, not used anymore)

**What to Keep:**
- Everything else
- configs still work
- API still works

---

## Development Tips

### Hot Reload

Flask development mode:
```bash
export FLASK_ENV=development  # Linux/Mac
$env:FLASK_ENV="development"   # PowerShell
python opcua_server.py -c config/config_web_ui.json
```

Changes to templates auto-reload!

### Debugging

Enable debug mode in publishers.py:
```python
self.app.run(host=host, port=port, debug=True)
```

**Warning:** Never use debug=True in production!

### Testing

Test API endpoints:
```bash
# Get tags
curl http://localhost:5000/api/tags

# Get publishers
curl http://localhost:5000/api/publishers

# Toggle MQTT
curl -X POST http://localhost:5000/api/publishers/MQTT/toggle
```

Test UI pages:
```bash
curl http://localhost:5000/
curl http://localhost:5000/tags
curl http://localhost:5000/publishers
```

---

## Production Deployment

### Option 1: Gunicorn (Recommended)

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 'publishers:create_app()'
```

**Note:** You'll need to refactor to create a Flask app factory.

### Option 2: uWSGI

```bash
pip install uwsgi
uwsgi --http :5000 --wsgi-file publishers.py --callable app
```

### Option 3: Docker

```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "opcua_server.py", "-c", "config/config_web_ui.json"]
```

### Option 4: K3s/Kubernetes

See deployment guide (coming soon).

---

## Security Notes

### Current State: 🔓 UNSECURED

Same as before:
- No authentication
- No HTTPS enforcement
- Open API access

### Recommendations

**For Production:**

1. **Add Authentication:**
   ```python
   from flask_httpauth import HTTPBasicAuth
   auth = HTTPBasicAuth()
   
   @auth.verify_password
   def verify_password(username, password):
       # Your auth logic
   
   @web_ui.route('/dashboard')
   @auth.login_required
   def dashboard():
       return render_template('dashboard.html')
   ```

2. **Enable HTTPS:**
   - Use nginx reverse proxy with SSL
   - Or use Flask-Talisman

3. **CSRF Protection:**
   ```python
   from flask_wtf.csrf import CSRFProtect
   csrf = CSRFProtect(app)
   ```

4. **Rate Limiting:**
   ```python
   from flask_limiter import Limiter
   limiter = Limiter(app)
   ```

---

## Troubleshooting

### "Template not found"

**Check:**
- `templates/` folder exists
- Blueprint registered correctly
- Template name matches route

**Fix:**
```python
# In web_app.py
web_ui = Blueprint('web_ui', __name__,
                   template_folder='templates')  # ← Check this
```

### "Static files not loading"

**Check:**
- `static/` folder exists
- File paths correct in templates
- Blueprint static_folder set

**Fix:**
```html
<!-- Correct -->
<link rel="stylesheet" href="{{ url_for('web_ui.static', filename='css/style.css') }}">

<!-- Wrong -->
<link rel="stylesheet" href="/static/css/style.css">
```

### "API calls failing"

**Check:**
- REST API publisher enabled
- Port 5000 not blocked
- CORS configured (it is)

**Test:**
```bash
curl http://localhost:5000/api/tags
```

### "Styles not applying"

**Check:**
- CSS file exists at `static/css/style.css`
- Template includes CSS correctly
- Browser cache (hard refresh: Ctrl+Shift+R)

---

## FAQ

**Q: Do I need Node.js now?**
A: **No!** Pure Python and vanilla JavaScript. No build tools.

**Q: Can I still use the old web/index.html?**
A: It won't work anymore. Use the new Flask templates.

**Q: Is this faster than the React version?**
A: **Yes!** Server-side rendering + vanilla JS = faster initial load.

**Q: Can I add React/Vue later?**
A: Sure! Use Flask as API backend, React as separate frontend. But you don't need it.

**Q: What about mobile?**
A: CSS is not responsive yet. Add media queries or use Bootstrap.

**Q: Can I customize the sidebar?**
A: Yes! Edit `templates/base.html`.

**Q: How do I add database support?**
A: Use Flask-SQLAlchemy. Works perfectly with Blueprints.

---

## Next Steps

### Immediate

1. **Test all views** - Dashboard, Tags, Publishers, Alarms
2. **Customize branding** - Edit ASCII art, colors
3. **Add features** - Tag writing, config editor, logs

### Short-Term

- Mobile responsive design
- Historical charts (InfluxDB data)
- Alarm acknowledgment
- Configuration editor

### Long-Term

- User authentication
- Multi-user support
- Role-based access
- WebSocket real-time updates

---

## Summary

**What We Built:**

🔥 **Proper Python Flask web application**
- Blueprint architecture
- Jinja2 templates
- Separated static assets
- Vanilla JavaScript (no React)
- Professional structure

**Why It's Better:**

✅ Python-native (no CDN dependencies)
✅ Maintainable (separated files)
✅ Scalable (easy to extend)
✅ Production-ready (proper patterns)
✅ No build step (works immediately)

**How to Use:**

```bash
python opcua_server.py -c config/config_web_ui.json
# Open http://localhost:5000/
```

---

*Built with 🔥 by Patrick Ryan, CTO - Fireball Industries*

*"Now it's a REAL Python web app!"*
