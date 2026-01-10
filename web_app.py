"""
EmberBurn Web Application
Flask-based web UI for OPC UA Industrial Gateway

Author: Patrick Ryan, CTO - Fireball Industries
License: MIT
"""

from flask import Blueprint, render_template, jsonify, request
import logging

# Create Blueprint for web UI
web_ui = Blueprint('web_ui', __name__,
                   template_folder='templates',
                   static_folder='static',
                   static_url_path='/static/web')

logger = logging.getLogger("EmberBurnUI")


@web_ui.route('/')
def index():
    """Serve the main dashboard."""
    return render_template('index.html')


@web_ui.route('/dashboard')
def dashboard():
    """Dashboard view."""
    return render_template('dashboard.html')


@web_ui.route('/tags')
def tags():
    """Tag monitor view."""
    return render_template('tags.html')


@web_ui.route('/publishers')
def publishers():
    """Publishers management view."""
    return render_template('publishers.html')


@web_ui.route('/alarms')
def alarms():
    """Alarms view."""
    return render_template('alarms.html')


@web_ui.route('/config')
def config():
    """Configuration view."""
    return render_template('config.html')


# Health check for the UI blueprint
@web_ui.route('/health')
def health():
    """UI health check."""
    return jsonify({"status": "healthy", "service": "emberburn-ui"})
