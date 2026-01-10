#!/usr/bin/env python3
"""
Data Publishers for OPC UA Server
Supports publishing tag data to multiple protocols: MQTT, REST API, WebSockets, etc.

Author: Your Friendly Neighborhood Engineer
License: MIT
"""

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request
from flask_cors import CORS


class DataPublisher(ABC):
    """Base class for all data publishers."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize the data publisher.
        
        Args:
            config: Publisher-specific configuration
            logger: Logger instance
        """
        self.config = config
        self.enabled = config.get("enabled", False)
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self.running = False
        
    @abstractmethod
    def start(self):
        """Start the publisher."""
        pass
    
    @abstractmethod
    def stop(self):
        """Stop the publisher."""
        pass
    
    @abstractmethod
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Publish a tag value.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        pass


class MQTTPublisher(DataPublisher):
    """MQTT Publisher for tag data."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.client = None
        self.connected = False
        
    def on_connect(self, client, userdata, flags, rc):
        """Callback for when the client receives a CONNACK response."""
        if rc == 0:
            self.connected = True
            self.logger.info("Connected to MQTT broker successfully")
            
            # Subscribe to command topics if configured
            command_topic = self.config.get("command_topic")
            if command_topic:
                client.subscribe(f"{command_topic}/#")
                self.logger.info(f"Subscribed to command topic: {command_topic}/#")
        else:
            self.logger.error(f"Failed to connect to MQTT broker, return code {rc}")
            self.connected = False
    
    def on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects."""
        self.connected = False
        if rc != 0:
            self.logger.warning(f"Unexpected MQTT disconnection (rc={rc}). Attempting to reconnect...")
    
    def on_message(self, client, userdata, msg):
        """Callback for when a PUBLISH message is received."""
        try:
            topic = msg.topic
            payload = msg.payload.decode()
            self.logger.info(f"Received MQTT message on {topic}: {payload}")
            
            # Parse the command (could be used for write-back to OPC UA)
            # Format: command_topic/tag_name -> value
            if hasattr(self, 'command_callback'):
                tag_name = topic.split('/')[-1]
                self.command_callback(tag_name, payload)
                
        except Exception as e:
            self.logger.error(f"Error processing MQTT message: {e}")
    
    def start(self):
        """Start the MQTT publisher."""
        if not self.enabled:
            self.logger.info("MQTT publisher is disabled")
            return
        
        try:
            broker = self.config.get("broker", "localhost")
            port = self.config.get("port", 1883)
            client_id = self.config.get("client_id", "opcua_server")
            
            self.client = mqtt.Client(client_id=client_id)
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_message = self.on_message
            
            # Set username/password if provided
            username = self.config.get("username")
            password = self.config.get("password")
            if username and password:
                self.client.username_pw_set(username, password)
            
            # Configure TLS if specified
            use_tls = self.config.get("use_tls", False)
            if use_tls:
                ca_certs = self.config.get("ca_certs")
                self.client.tls_set(ca_certs=ca_certs)
            
            self.logger.info(f"Connecting to MQTT broker at {broker}:{port}")
            self.client.connect(broker, port, keepalive=60)
            self.client.loop_start()
            self.running = True
            
        except Exception as e:
            self.logger.error(f"Failed to start MQTT publisher: {e}")
            self.running = False
    
    def stop(self):
        """Stop the MQTT publisher."""
        if self.client and self.running:
            self.client.loop_stop()
            self.client.disconnect()
            self.running = False
            self.logger.info("MQTT publisher stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Publish tag value to MQTT.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled or not self.connected:
            return
        
        try:
            topic_prefix = self.config.get("topic_prefix", "opcua")
            topic = f"{topic_prefix}/{tag_name}"
            
            # Create payload
            payload_format = self.config.get("payload_format", "json")
            
            if payload_format == "json":
                payload_data = {
                    "tag": tag_name,
                    "value": value,
                    "timestamp": timestamp or time.time()
                }
                payload = json.dumps(payload_data)
            else:
                # Simple string format
                payload = str(value)
            
            qos = self.config.get("qos", 0)
            retain = self.config.get("retain", False)
            
            self.client.publish(topic, payload, qos=qos, retain=retain)
            self.logger.debug(f"Published to MQTT: {topic} = {payload}")
            
        except Exception as e:
            self.logger.error(f"Error publishing to MQTT: {e}")
    
    def set_command_callback(self, callback):
        """Set callback function for handling incoming commands."""
        self.command_callback = callback


class RESTAPIPublisher(DataPublisher):
    """REST API Publisher for tag data."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.app = Flask(__name__)
        CORS(self.app)
        self.server_thread = None
        self.tag_cache = {}
        self.write_callback = None
        
        # Setup routes
        self.setup_routes()
    
    def setup_routes(self):
        """Setup Flask routes."""
        
        @self.app.route('/api/tags', methods=['GET'])
        def get_all_tags():
            """Get all tag values."""
            return jsonify({
                "tags": self.tag_cache,
                "count": len(self.tag_cache)
            })
        
        @self.app.route('/api/tags/<tag_name>', methods=['GET'])
        def get_tag(tag_name):
            """Get a specific tag value."""
            if tag_name in self.tag_cache:
                return jsonify(self.tag_cache[tag_name])
            return jsonify({"error": "Tag not found"}), 404
        
        @self.app.route('/api/tags/<tag_name>', methods=['POST', 'PUT'])
        def write_tag(tag_name):
            """Write a value to a tag."""
            try:
                data = request.get_json()
                value = data.get('value')
                
                if value is None:
                    return jsonify({"error": "No value provided"}), 400
                
                # Call write callback if set
                if self.write_callback:
                    success = self.write_callback(tag_name, value)
                    if success:
                        return jsonify({"success": True, "tag": tag_name, "value": value})
                    else:
                        return jsonify({"error": "Failed to write tag"}), 500
                        
                return jsonify({"error": "Write not supported"}), 501
                
            except Exception as e:
                self.logger.error(f"Error writing tag via API: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/health', methods=['GET'])
        def health_check():
            """Health check endpoint."""
            return jsonify({
                "status": "healthy",
                "tags_count": len(self.tag_cache)
            })
    
    def start(self):
        """Start the REST API server."""
        if not self.enabled:
            self.logger.info("REST API publisher is disabled")
            return
        
        try:
            host = self.config.get("host", "0.0.0.0")
            port = self.config.get("port", 5000)
            
            def run_server():
                self.app.run(host=host, port=port, debug=False, use_reloader=False)
            
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            self.running = True
            
            self.logger.info(f"REST API started on http://{host}:{port}")
            
        except Exception as e:
            self.logger.error(f"Failed to start REST API: {e}")
            self.running = False
    
    def stop(self):
        """Stop the REST API server."""
        # Flask doesn't have a clean shutdown in this mode
        # In production, use a proper WSGI server
        self.running = False
        self.logger.info("REST API publisher stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Update tag cache for REST API.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled:
            return
        
        self.tag_cache[tag_name] = {
            "value": value,
            "timestamp": timestamp or time.time()
        }
    
    def set_write_callback(self, callback):
        """Set callback function for handling write requests."""
        self.write_callback = callback


class PublisherManager:
    """Manages multiple data publishers."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize the publisher manager.
        
        Args:
            config: Configuration dictionary with publisher settings
            logger: Logger instance
        """
        self.config = config
        self.logger = logger or logging.getLogger("PublisherManager")
        self.publishers = []
        
    def initialize_publishers(self):
        """Initialize all configured publishers."""
        publishers_config = self.config.get("publishers", {})
        
        # MQTT Publisher
        mqtt_config = publishers_config.get("mqtt", {})
        if mqtt_config.get("enabled", False):
            mqtt_pub = MQTTPublisher(mqtt_config, self.logger)
            self.publishers.append(mqtt_pub)
            self.logger.info("MQTT publisher initialized")
        
        # REST API Publisher
        rest_config = publishers_config.get("rest_api", {})
        if rest_config.get("enabled", False):
            rest_pub = RESTAPIPublisher(rest_config, self.logger)
            self.publishers.append(rest_pub)
            self.logger.info("REST API publisher initialized")
        
        return self.publishers
    
    def start_all(self):
        """Start all publishers."""
        for publisher in self.publishers:
            try:
                publisher.start()
            except Exception as e:
                self.logger.error(f"Error starting publisher {publisher.__class__.__name__}: {e}")
    
    def stop_all(self):
        """Stop all publishers."""
        for publisher in self.publishers:
            try:
                publisher.stop()
            except Exception as e:
                self.logger.error(f"Error stopping publisher {publisher.__class__.__name__}: {e}")
    
    def publish_to_all(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Publish tag value to all enabled publishers.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        for publisher in self.publishers:
            try:
                publisher.publish(tag_name, value, timestamp)
            except Exception as e:
                self.logger.error(f"Error publishing to {publisher.__class__.__name__}: {e}")
