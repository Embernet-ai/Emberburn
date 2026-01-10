#!/usr/bin/env python3
"""
Data Publishers for OPC UA Server
Supports publishing tag data to multiple protocols: MQTT, REST API, WebSockets, etc.

Author: Your Friendly Neighborhood Engineer
License: MIT
"""

import json
import logging
import os
import threading
import time
import requests  # For HTTP requests (Slack webhooks, etc.)
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

try:
    from sparkplug_b import *
    SPARKPLUG_AVAILABLE = True
except ImportError:
    SPARKPLUG_AVAILABLE = False

try:
    from kafka import KafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

try:
    import pika
    AMQP_AVAILABLE = True
except ImportError:
    AMQP_AVAILABLE = False

try:
    from websocket_server import WebsocketServer
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

try:
    from pymodbus.server import StartTcpServer
    from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
    from pymodbus.device import ModbusDeviceIdentification
    import struct
    MODBUS_AVAILABLE = True
except ImportError:
    MODBUS_AVAILABLE = False

try:
    from opcua import Client as OPCUAClient
    from opcua import ua
    OPCUA_CLIENT_AVAILABLE = True
except ImportError:
    OPCUA_CLIENT_AVAILABLE = False

try:
    import graphene
    from flask_graphql import GraphQLView
    GRAPHQL_AVAILABLE = True
except ImportError:
    GRAPHQL_AVAILABLE = False

try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS
    INFLUXDB_AVAILABLE = True
except ImportError:
    INFLUXDB_AVAILABLE = False

# Email and notification libraries (mostly built-in)
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from collections import deque

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

try:
    from prometheus_client import Counter, Gauge, Histogram, Info, generate_latest, REGISTRY, CollectorRegistry
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

import sqlite3
import threading
import re
import math
from typing import Callable


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
        self.app = Flask(__name__, 
                        template_folder='templates',
                        static_folder='static')
        CORS(self.app)
        self.server_thread = None
        self.tag_cache = {}
        self.write_callback = None
        
        # Register Web UI Blueprint
        try:
            from web_app import web_ui
            self.app.register_blueprint(web_ui)
            self.logger.info("EmberBurn Web UI registered")
        except ImportError as e:
            self.logger.warning(f"Web UI Blueprint not available: {e}")
        
        # Setup API routes
        self.setup_routes()
    
    def setup_routes(self):
        """Setup Flask API routes."""
        
        @self.app.route('/', methods=['GET'])
        def index_redirect():
            """Redirect root to dashboard (handled by Blueprint)."""
            # If web_ui blueprint is registered, Flask will handle the route
            # Otherwise, return API info
            return jsonify({
                "message": "EmberBurn OPC UA Gateway API",
                "version": "1.0",
                "endpoints": {
                    "ui": "/",
                    "tags": "/api/tags",
                    "publishers": "/api/publishers",
                    "alarms": "/api/alarms/active",
                    "graphql": "http://localhost:5002/graphql"
                }
            })
        
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
        
        @self.app.route('/api/tags/discovery', methods=['GET'])
        def discover_tags():
            """Discover all available tags with metadata."""
            try:
                # Get query parameters for filtering
                filter_type = request.args.get('type')  # Filter by data type
                search = request.args.get('search', '').lower()  # Search term
                category = request.args.get('category')  # Filter by category
                
                tags = []
                for tag_name, tag_data in self.tag_cache.items():
                    # Get metadata from tag_metadata if available
                    metadata = getattr(self, 'tag_metadata', {}).get(tag_name, {})
                    
                    # Build tag info
                    tag_info = {
                        'name': tag_name,
                        'value': tag_data.get('value'),
                        'timestamp': tag_data.get('timestamp'),
                        'type': metadata.get('type', 'unknown'),
                        'description': metadata.get('description', ''),
                        'units': metadata.get('units', ''),
                        'min': metadata.get('min'),
                        'max': metadata.get('max'),
                        'category': metadata.get('category', 'general'),
                        'quality': metadata.get('quality', 'good'),
                        'writable': metadata.get('writable', False),
                        'simulation_type': metadata.get('simulation_type')
                    }
                    
                    # Apply filters
                    if filter_type and tag_info['type'] != filter_type:
                        continue
                    if search and search not in tag_name.lower() and search not in tag_info.get('description', '').lower():
                        continue
                    if category and tag_info['category'] != category:
                        continue
                    
                    tags.append(tag_info)
                
                return jsonify({
                    'tags': tags,
                    'count': len(tags),
                    'total_tags': len(self.tag_cache)
                })
            except Exception as e:
                self.logger.error(f"Error in tag discovery: {e}")
                return jsonify({"error": str(e)}), 500
        
        @self.app.route('/api/tags/<tag_name>/metadata', methods=['GET'])
        def get_tag_metadata(tag_name):
            """Get detailed metadata for a specific tag."""
            if tag_name not in self.tag_cache:
                return jsonify({"error": "Tag not found"}), 404
            
            metadata = getattr(self, 'tag_metadata', {}).get(tag_name, {})
            tag_data = self.tag_cache[tag_name]
            
            return jsonify({
                'name': tag_name,
                'current_value': tag_data.get('value'),
                'timestamp': tag_data.get('timestamp'),
                'metadata': metadata
            })
        
        @self.app.route('/api/tags/categories', methods=['GET'])
        def get_tag_categories():
            """Get all tag categories."""
            categories = set()
            metadata_dict = getattr(self, 'tag_metadata', {})
            
            for tag_name in self.tag_cache.keys():
                metadata = metadata_dict.get(tag_name, {})
                category = metadata.get('category', 'general')
                categories.add(category)
            
            return jsonify({
                'categories': sorted(list(categories)),
                'count': len(categories)
            })
        
        @self.app.route('/api/tags/types', methods=['GET'])
        def get_tag_types():
            """Get all data types used by tags."""
            types = set()
            metadata_dict = getattr(self, 'tag_metadata', {})
            
            for tag_name in self.tag_cache.keys():
                metadata = metadata_dict.get(tag_name, {})
                tag_type = metadata.get('type', 'unknown')
                types.add(tag_type)
            
            return jsonify({
                'types': sorted(list(types)),
                'count': len(types)
            })
        
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
        
        @self.app.route('/api/publishers', methods=['GET'])
        def get_publishers():
            """Get all publisher statuses."""
            # This will be populated by the PublisherManager
            return jsonify({
                "publishers": getattr(self, '_publisher_statuses', [])
            })
        
        @self.app.route('/api/publishers/<publisher_name>/toggle', methods=['POST'])
        def toggle_publisher(publisher_name):
            """Toggle a publisher on/off."""
            # This will be handled by the PublisherManager
            callback = getattr(self, '_toggle_callback', None)
            if callback:
                success = callback(publisher_name)
                return jsonify({"success": success, "publisher": publisher_name})
            return jsonify({"error": "Toggle not supported"}), 501
        
        @self.app.route('/api/alarms/active', methods=['GET'])
        def get_active_alarms():
            """Get active alarms."""
            callback = getattr(self, '_alarms_callback', None)
            if callback:
                alarms = callback()
                return jsonify({"alarms": alarms})
            return jsonify({"alarms": []})
        
        @self.app.route('/metrics', methods=['GET'])
        def prometheus_metrics():
            """Prometheus metrics endpoint."""
            try:
                if PROMETHEUS_AVAILABLE:
                    metrics = generate_latest(REGISTRY)
                    return metrics, 200, {'Content-Type': 'text/plain; charset=utf-8'}
                else:
                    return jsonify({"error": "Prometheus client not installed"}), 501
            except Exception as e:
                self.logger.error(f"Error generating metrics: {e}")
                return jsonify({"error": str(e)}), 500
    
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


class SparkplugBPublisher(DataPublisher):
    """Sparkplug B Publisher for Ignition Edge and SCADA systems."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        if not SPARKPLUG_AVAILABLE:
            self.logger.warning("Sparkplug B library not available. Install with: pip install sparkplug-b")
            self.enabled = False
            return
            
        self.client = None
        self.connected = False
        self.sequence_number = 0
        self.bdSeq = 0
        
    def get_next_sequence(self):
        """Get next sequence number (0-255)."""
        seq = self.sequence_number
        self.sequence_number = (self.sequence_number + 1) % 256
        return seq
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback for when the client receives a CONNACK response."""
        if rc == 0:
            self.connected = True
            self.logger.info("Connected to Sparkplug B broker successfully")
            
            # Send NBIRTH (Node Birth) message
            self.send_node_birth()
            # Send DBIRTH (Device Birth) message
            self.send_device_birth()
        else:
            self.logger.error(f"Failed to connect to Sparkplug B broker, return code {rc}")
            self.connected = False
    
    def on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects."""
        self.connected = False
        if rc != 0:
            self.logger.warning(f"Unexpected Sparkplug B disconnection (rc={rc})")
    
    def send_node_birth(self):
        """Send Node Birth Certificate."""
        if not self.connected:
            return
            
        try:
            group_id = self.config.get("group_id", "Sparkplug B Devices")
            edge_node_id = self.config.get("edge_node_id", "OPC_UA_Gateway")
            
            topic = f"spBv1.0/{group_id}/NBIRTH/{edge_node_id}"
            
            # Create minimal NBIRTH payload
            payload = {
                "timestamp": int(time.time() * 1000),
                "metrics": [
                    {
                        "name": "Node Control/Rebirth",
                        "timestamp": int(time.time() * 1000),
                        "dataType": "Boolean",
                        "value": False
                    }
                ],
                "seq": self.get_next_sequence()
            }
            
            self.client.publish(topic, json.dumps(payload), qos=0, retain=False)
            self.logger.info(f"Sent NBIRTH to {topic}")
            
        except Exception as e:
            self.logger.error(f"Error sending NBIRTH: {e}")
    
    def send_device_birth(self):
        """Send Device Birth Certificate with all metrics."""
        if not self.connected:
            return
            
        try:
            group_id = self.config.get("group_id", "Sparkplug B Devices")
            edge_node_id = self.config.get("edge_node_id", "OPC_UA_Gateway")
            device_id = self.config.get("device_id", "EdgeDevice")
            
            topic = f"spBv1.0/{group_id}/DBIRTH/{edge_node_id}/{device_id}"
            
            # Create DBIRTH payload with metrics
            payload = {
                "timestamp": int(time.time() * 1000),
                "metrics": [],
                "seq": self.get_next_sequence()
            }
            
            self.client.publish(topic, json.dumps(payload), qos=0, retain=False)
            self.logger.info(f"Sent DBIRTH to {topic}")
            
        except Exception as e:
            self.logger.error(f"Error sending DBIRTH: {e}")
    
    def start(self):
        """Start the Sparkplug B publisher."""
        if not self.enabled or not SPARKPLUG_AVAILABLE:
            if not SPARKPLUG_AVAILABLE:
                self.logger.warning("Sparkplug B publisher is disabled (library not available)")
            else:
                self.logger.info("Sparkplug B publisher is disabled")
            return
        
        try:
            broker = self.config.get("broker", "localhost")
            port = self.config.get("port", 1883)
            group_id = self.config.get("group_id", "Sparkplug B Devices")
            edge_node_id = self.config.get("edge_node_id", "OPC_UA_Gateway")
            
            client_id = f"{group_id}_{edge_node_id}"
            
            self.client = mqtt.Client(client_id=client_id)
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            
            # Set username/password if provided
            username = self.config.get("username")
            password = self.config.get("password")
            if username and password:
                self.client.username_pw_set(username, password)
            
            # Configure NDEATH (Node Death) certificate as LWT
            ndeath_topic = f"spBv1.0/{group_id}/NDEATH/{edge_node_id}"
            ndeath_payload = {
                "timestamp": int(time.time() * 1000),
                "bdSeq": self.bdSeq
            }
            self.client.will_set(ndeath_topic, json.dumps(ndeath_payload), qos=0, retain=False)
            
            self.logger.info(f"Connecting to Sparkplug B broker at {broker}:{port}")
            self.client.connect(broker, port, keepalive=60)
            self.client.loop_start()
            self.running = True
            
        except Exception as e:
            self.logger.error(f"Failed to start Sparkplug B publisher: {e}")
            self.running = False
    
    def stop(self):
        """Stop the Sparkplug B publisher."""
        if self.client and self.running:
            # Send NDEATH before disconnecting
            try:
                group_id = self.config.get("group_id", "Sparkplug B Devices")
                edge_node_id = self.config.get("edge_node_id", "OPC_UA_Gateway")
                
                topic = f"spBv1.0/{group_id}/NDEATH/{edge_node_id}"
                payload = {
                    "timestamp": int(time.time() * 1000),
                    "bdSeq": self.bdSeq
                }
                self.client.publish(topic, json.dumps(payload), qos=0, retain=False)
            except:
                pass
                
            self.client.loop_stop()
            self.client.disconnect()
            self.running = False
            self.logger.info("Sparkplug B publisher stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Publish tag value using Sparkplug B DDATA message.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled or not self.connected or not SPARKPLUG_AVAILABLE:
            return
        
        try:
            group_id = self.config.get("group_id", "Sparkplug B Devices")
            edge_node_id = self.config.get("edge_node_id", "OPC_UA_Gateway")
            device_id = self.config.get("device_id", "EdgeDevice")
            
            topic = f"spBv1.0/{group_id}/DDATA/{edge_node_id}/{device_id}"
            
            # Determine Sparkplug data type
            if isinstance(value, bool):
                datatype = "Boolean"
            elif isinstance(value, int):
                datatype = "Int32"
            elif isinstance(value, float):
                datatype = "Float"
            elif isinstance(value, str):
                datatype = "String"
            else:
                datatype = "String"
                value = str(value)
            
            # Create DDATA payload
            payload = {
                "timestamp": int((timestamp or time.time()) * 1000),
                "metrics": [
                    {
                        "name": tag_name,
                        "timestamp": int((timestamp or time.time()) * 1000),
                        "dataType": datatype,
                        "value": value
                    }
                ],
                "seq": self.get_next_sequence()
            }
            
            self.client.publish(topic, json.dumps(payload), qos=0, retain=False)
            self.logger.debug(f"Published Sparkplug B DDATA: {tag_name} = {value}")
            
        except Exception as e:
            self.logger.error(f"Error publishing to Sparkplug B: {e}")


class KafkaPublisher(DataPublisher):
    """Apache Kafka Publisher for enterprise streaming."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        if not KAFKA_AVAILABLE:
            self.logger.warning("Kafka library not available. Install with: pip install kafka-python")
            self.enabled = False
            return
            
        self.producer = None
        
    def start(self):
        """Start the Kafka publisher."""
        if not self.enabled or not KAFKA_AVAILABLE:
            if not KAFKA_AVAILABLE:
                self.logger.warning("Kafka publisher is disabled (library not available)")
            else:
                self.logger.info("Kafka publisher is disabled")
            return
        
        try:
            bootstrap_servers = self.config.get("bootstrap_servers", ["localhost:9092"])
            
            # Convert string to list if needed
            if isinstance(bootstrap_servers, str):
                bootstrap_servers = [bootstrap_servers]
            
            self.producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                compression_type=self.config.get("compression", "gzip")
            )
            
            self.running = True
            self.logger.info(f"Kafka publisher started with brokers: {bootstrap_servers}")
            
        except Exception as e:
            self.logger.error(f"Failed to start Kafka publisher: {e}")
            self.running = False
    
    def stop(self):
        """Stop the Kafka publisher."""
        if self.producer and self.running:
            self.producer.flush()
            self.producer.close()
            self.running = False
            self.logger.info("Kafka publisher stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Publish tag value to Kafka topic.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled or not self.running or not KAFKA_AVAILABLE:
            return
        
        try:
            topic = self.config.get("topic", "industrial-data")
            
            # Create message payload
            message = {
                "tag": tag_name,
                "value": value,
                "timestamp": timestamp or time.time()
            }
            
            # Include tag name as key for partitioning
            key = tag_name.encode('utf-8')
            
            self.producer.send(topic, value=message, key=key)
            self.logger.debug(f"Published to Kafka: {tag_name} = {value}")
            
        except Exception as e:
            self.logger.error(f"Error publishing to Kafka: {e}")


class AMQPPublisher(DataPublisher):
    """AMQP Publisher for RabbitMQ and other AMQP brokers."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        if not AMQP_AVAILABLE:
            self.logger.warning("AMQP library not available. Install with: pip install pika")
            self.enabled = False
            return
            
        self.connection = None
        self.channel = None
        
    def start(self):
        """Start the AMQP publisher."""
        if not self.enabled or not AMQP_AVAILABLE:
            if not AMQP_AVAILABLE:
                self.logger.warning("AMQP publisher is disabled (library not available)")
            else:
                self.logger.info("AMQP publisher is disabled")
            return
        
        try:
            host = self.config.get("host", "localhost")
            port = self.config.get("port", 5672)
            username = self.config.get("username", "guest")
            password = self.config.get("password", "guest")
            vhost = self.config.get("virtual_host", "/")
            
            credentials = pika.PlainCredentials(username, password)
            parameters = pika.ConnectionParameters(
                host=host,
                port=port,
                virtual_host=vhost,
                credentials=credentials
            )
            
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            
            # Declare exchange
            exchange = self.config.get("exchange", "industrial.data")
            exchange_type = self.config.get("exchange_type", "topic")
            self.channel.exchange_declare(
                exchange=exchange,
                exchange_type=exchange_type,
                durable=True
            )
            
            self.running = True
            self.logger.info(f"AMQP publisher started on {host}:{port}")
            
        except Exception as e:
            self.logger.error(f"Failed to start AMQP publisher: {e}")
            self.running = False
    
    def stop(self):
        """Stop the AMQP publisher."""
        if self.connection and self.running:
            try:
                self.channel.close()
                self.connection.close()
            except:
                pass
            self.running = False
            self.logger.info("AMQP publisher stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Publish tag value to AMQP exchange.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled or not self.running or not AMQP_AVAILABLE:
            return
        
        try:
            exchange = self.config.get("exchange", "industrial.data")
            routing_key = self.config.get("routing_key_prefix", "opcua") + "." + tag_name
            
            # Create message payload
            message = {
                "tag": tag_name,
                "value": value,
                "timestamp": timestamp or time.time()
            }
            
            self.channel.basic_publish(
                exchange=exchange,
                routing_key=routing_key,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # Make message persistent
                    content_type='application/json'
                )
            )
            
            self.logger.debug(f"Published to AMQP: {routing_key} = {value}")
            
        except Exception as e:
            self.logger.error(f"Error publishing to AMQP: {e}")


class WebSocketPublisher(DataPublisher):
    """WebSocket Publisher for real-time browser updates."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        if not WEBSOCKET_AVAILABLE:
            self.logger.warning("WebSocket library not available. Install with: pip install websocket-server")
            self.enabled = False
            return
            
        self.server = None
        self.server_thread = None
        self.clients = []
        
    def new_client(self, client, server):
        """Called when a new client connects."""
        self.clients.append(client)
        self.logger.info(f"New WebSocket client connected: {client['id']}")
    
    def client_left(self, client, server):
        """Called when a client disconnects."""
        if client in self.clients:
            self.clients.remove(client)
        self.logger.info(f"WebSocket client disconnected: {client['id']}")
    
    def start(self):
        """Start the WebSocket server."""
        if not self.enabled or not WEBSOCKET_AVAILABLE:
            if not WEBSOCKET_AVAILABLE:
                self.logger.warning("WebSocket publisher is disabled (library not available)")
            else:
                self.logger.info("WebSocket publisher is disabled")
            return
        
        try:
            host = self.config.get("host", "0.0.0.0")
            port = self.config.get("port", 9001)
            
            self.server = WebsocketServer(host=host, port=port)
            self.server.set_fn_new_client(self.new_client)
            self.server.set_fn_client_left(self.client_left)
            
            def run_server():
                self.server.run_forever()
            
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            self.running = True
            
            self.logger.info(f"WebSocket server started on ws://{host}:{port}")
            
        except Exception as e:
            self.logger.error(f"Failed to start WebSocket publisher: {e}")
            self.running = False
    
    def stop(self):
        """Stop the WebSocket server."""
        if self.server and self.running:
            self.server.shutdown()
            self.running = False
            self.logger.info("WebSocket publisher stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Broadcast tag value to all connected WebSocket clients.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled or not self.running or not WEBSOCKET_AVAILABLE:
            return
        
        try:
            if not self.clients:
                return
            
            # Create message payload
            message = {
                "tag": tag_name,
                "value": value,
                "timestamp": timestamp or time.time()
            }
            
            message_json = json.dumps(message)
            
            # Broadcast to all connected clients
            for client in self.clients[:]:  # Use copy to avoid modification during iteration
                try:
                    self.server.send_message(client, message_json)
                except:
                    # Remove disconnected clients
                    if client in self.clients:
                        self.clients.remove(client)
            
            self.logger.debug(f"Broadcast to {len(self.clients)} WebSocket clients: {tag_name} = {value}")
            
        except Exception as e:
            self.logger.error(f"Error publishing to WebSocket: {e}")


class ModbusTCPPublisher(DataPublisher):
    """MODBUS TCP Server Publisher for legacy industrial systems."""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        if not MODBUS_AVAILABLE:
            self.logger.warning("MODBUS library not available. Install with: pip install pymodbus")
            self.enabled = False
            return
            
        self.server_thread = None
        self.context = None
        self.tag_register_map = {}  # Maps tag names to register addresses
        self.register_tag_map = {}  # Maps register addresses to tag info
        self.next_register = 0
        
    def allocate_registers(self, tag_name: str, tag_type: str) -> int:
        """
        Allocate MODBUS registers for a tag.
        
        Args:
            tag_name: Name of the tag
            tag_type: Type of tag (int, float, bool, string)
            
        Returns:
            Starting register address
        """
        if tag_name in self.tag_register_map:
            return self.tag_register_map[tag_name]["start_register"]
        
        # Determine number of registers needed
        if tag_type == "float":
            num_registers = 2  # 32-bit float = 2 registers
        elif tag_type == "int":
            num_registers = 1  # 16-bit int = 1 register
        elif tag_type == "bool":
            num_registers = 1  # Boolean = 1 register (0 or 1)
        elif tag_type == "string":
            num_registers = 32  # Reserve 32 registers (64 bytes) for strings
        else:
            num_registers = 1
        
        start_register = self.next_register
        self.tag_register_map[tag_name] = {
            "start_register": start_register,
            "num_registers": num_registers,
            "type": tag_type
        }
        
        # Create reverse mapping for reading
        for i in range(num_registers):
            self.register_tag_map[start_register + i] = {
                "tag_name": tag_name,
                "offset": i,
                "type": tag_type
            }
        
        self.next_register += num_registers
        self.logger.debug(f"Allocated registers {start_register}-{start_register + num_registers - 1} for {tag_name} ({tag_type})")
        
        return start_register
    
    def start(self):
        """Start the MODBUS TCP server."""
        if not self.enabled or not MODBUS_AVAILABLE:
            if not MODBUS_AVAILABLE:
                self.logger.warning("MODBUS TCP publisher is disabled (library not available)")
            else:
                self.logger.info("MODBUS TCP publisher is disabled")
            return
        
        try:
            host = self.config.get("host", "0.0.0.0")
            port = self.config.get("port", 502)
            
            # Initialize register mapping from config
            register_mapping = self.config.get("register_mapping", {})
            for tag_name, mapping in register_mapping.items():
                tag_type = mapping.get("type", "float")
                if "register" in mapping:
                    # Use explicit register assignment
                    start_reg = mapping["register"]
                    num_regs = 2 if tag_type == "float" else 1
                    self.tag_register_map[tag_name] = {
                        "start_register": start_reg,
                        "num_registers": num_regs,
                        "type": tag_type
                    }
                    self.next_register = max(self.next_register, start_reg + num_regs)
            
            # Create MODBUS datastore (65536 registers, initialized to 0)
            store = ModbusSlaveContext(
                di=ModbusSequentialDataBlock(0, [0] * 65536),  # Discrete Inputs
                co=ModbusSequentialDataBlock(0, [0] * 65536),  # Coils
                hr=ModbusSequentialDataBlock(0, [0] * 65536),  # Holding Registers
                ir=ModbusSequentialDataBlock(0, [0] * 65536)   # Input Registers
            )
            
            self.context = ModbusServerContext(slaves=store, single=True)
            
            # Setup device identification
            identity = ModbusDeviceIdentification()
            identity.VendorName = 'OPC UA Gateway'
            identity.ProductCode = 'OPCUA-MB'
            identity.VendorUrl = 'https://github.com/yourrepo'
            identity.ProductName = 'OPC UA to MODBUS Bridge'
            identity.ModelName = 'MODBUS TCP Server'
            identity.MajorMinorRevision = '1.0.0'
            
            # Start server in separate thread
            def run_server():
                StartTcpServer(
                    context=self.context,
                    identity=identity,
                    address=(host, port),
                    allow_reuse_address=True
                )
            
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            self.running = True
            
            self.logger.info(f"MODBUS TCP server started on {host}:{port}")
            self.logger.info(f"Allocated {self.next_register} MODBUS registers")
            
        except Exception as e:
            self.logger.error(f"Failed to start MODBUS TCP publisher: {e}")
            self.running = False
    
    def stop(self):
        """Stop the MODBUS TCP server."""
        if self.running:
            # pymodbus server doesn't have clean shutdown in thread mode
            # Server will stop when daemon thread terminates
            self.running = False
            self.logger.info("MODBUS TCP publisher stopped")
    
    def value_to_registers(self, value: Any, tag_type: str) -> list:
        """
        Convert a value to MODBUS register values.
        
        Args:
            value: The value to convert
            tag_type: Type of the value
            
        Returns:
            List of register values (16-bit integers)
        """
        if tag_type == "float":
            # Convert float to 2 registers (32-bit IEEE 754)
            packed = struct.pack('>f', float(value))
            reg1, reg2 = struct.unpack('>HH', packed)
            return [reg1, reg2]
        
        elif tag_type == "int":
            # Convert int to 1 register (signed 16-bit)
            # Handle values outside 16-bit range
            int_value = int(value)
            if int_value > 32767:
                int_value = 32767
            elif int_value < -32768:
                int_value = -32768
            # Convert to unsigned for register storage
            reg_value = int_value & 0xFFFF
            return [reg_value]
        
        elif tag_type == "bool":
            # Convert bool to 1 register (0 or 1)
            return [1 if value else 0]
        
        elif tag_type == "string":
            # Convert string to registers (2 chars per register)
            str_value = str(value)[:64]  # Limit to 64 chars
            registers = []
            for i in range(0, len(str_value), 2):
                char1 = ord(str_value[i]) if i < len(str_value) else 0
                char2 = ord(str_value[i + 1]) if i + 1 < len(str_value) else 0
                registers.append((char1 << 8) | char2)
            # Pad to 32 registers
            while len(registers) < 32:
                registers.append(0)
            return registers
        
        return [0]
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Update MODBUS registers with tag value.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp (not used in MODBUS)
        """
        if not self.enabled or not self.running or not MODBUS_AVAILABLE:
            return
        
        try:
            # Get or allocate registers for this tag
            if tag_name not in self.tag_register_map:
                # Auto-allocate if not in mapping
                tag_type = "float"  # Default to float
                if isinstance(value, bool):
                    tag_type = "bool"
                elif isinstance(value, int):
                    tag_type = "int"
                elif isinstance(value, str):
                    tag_type = "string"
                
                self.allocate_registers(tag_name, tag_type)
            
            tag_info = self.tag_register_map[tag_name]
            start_register = tag_info["start_register"]
            tag_type = tag_info["type"]
            
            # Convert value to register values
            register_values = self.value_to_registers(value, tag_type)
            
            # Update holding registers in the datastore
            slave_context = self.context[0]
            for i, reg_value in enumerate(register_values):
                slave_context.setValues(3, start_register + i, [reg_value])  # Function code 3 = holding registers
            
            self.logger.debug(f"Updated MODBUS registers {start_register}-{start_register + len(register_values) - 1}: {tag_name} = {value}")
            
        except Exception as e:
            self.logger.error(f"Error publishing to MODBUS: {e}")
    
    def get_register_map(self) -> Dict[str, Any]:
        """
        Get the current register mapping for documentation.
        
        Returns:
            Dictionary mapping tag names to register info
        """
        return self.tag_register_map.copy()


class AlarmsPublisher(DataPublisher):
    """
    Alarms & Notifications Publisher - Because sometimes things go wrong
    
    Monitors tag values against configurable thresholds and sends alerts via:
    - Email (SMTP)
    - Slack (Webhooks)
    - SMS (Twilio)
    - Logging (always enabled)
    
    Features:
    - Threshold-based alerting (>, <, ==, !=)
    - Priority levels (INFO, WARNING, CRITICAL)
    - Debouncing (avoid spam)
    - Alarm history
    - Multiple notification channels
    - Auto-clear when values return to normal
    
    Because at 3 AM, you want to know if the reactor temperature is getting spicy.
    """
    
    PRIORITY_INFO = "INFO"
    PRIORITY_WARNING = "WARNING"
    PRIORITY_CRITICAL = "CRITICAL"
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize the alarms publisher.
        
        Config structure:
        {
            "enabled": true,
            "rules": [
                {
                    "name": "High Temperature",
                    "tag": "Temperature",
                    "condition": ">",
                    "threshold": 25.0,
                    "priority": "CRITICAL",
                    "debounce_seconds": 60,
                    "message": "Temperature is too high!"
                }
            ],
            "notifications": {
                "email": {...},
                "slack": {...},
                "sms": {...}
            },
            "history_size": 1000
        }
        """
        super().__init__(config, logger)
        
        self.rules = config.get("rules", [])
        self.notifications_config = config.get("notifications", {})
        self.history_size = config.get("history_size", 1000)
        
        # Active alarms tracking
        self.active_alarms = {}  # tag_name -> alarm_info
        self.alarm_history = deque(maxlen=self.history_size)
        
        # Last notification time per rule (for debouncing)
        self.last_notification = {}  # rule_name -> timestamp
        
        # Parse rules
        self.parsed_rules = []
        for rule in self.rules:
            self.parsed_rules.append({
                "name": rule.get("name", "Unnamed Rule"),
                "tag": rule.get("tag"),
                "condition": rule.get("condition", ">"),
                "threshold": rule.get("threshold"),
                "priority": rule.get("priority", self.PRIORITY_WARNING),
                "debounce_seconds": rule.get("debounce_seconds", 60),
                "message": rule.get("message", "Alarm triggered"),
                "auto_clear": rule.get("auto_clear", True),
                "channels": rule.get("channels", ["log"])  # log, email, slack, sms
            })
        
        self.logger.info(f"Alarms publisher initialized with {len(self.parsed_rules)} rules")
    
    def start(self):
        """Start the alarms publisher."""
        if not self.enabled:
            self.logger.info("Alarms publisher is disabled")
            return
        
        self.running = True
        self.logger.info(f"Alarms publisher started - monitoring {len(self.parsed_rules)} rules")
    
    def stop(self):
        """Stop the alarms publisher."""
        self.running = False
        self.logger.info("Alarms publisher stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Check tag value against alarm rules.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled or not self.running:
            return
        
        # Check each rule that applies to this tag
        for rule in self.parsed_rules:
            if rule["tag"] != tag_name:
                continue
            
            # Evaluate condition
            triggered = self._evaluate_condition(value, rule["condition"], rule["threshold"])
            
            rule_key = f"{rule['name']}_{tag_name}"
            
            if triggered:
                # Alarm condition met
                if rule_key not in self.active_alarms:
                    # New alarm
                    self._trigger_alarm(rule, tag_name, value, timestamp)
                else:
                    # Alarm already active, just update value
                    self.active_alarms[rule_key]["last_value"] = value
                    self.active_alarms[rule_key]["last_update"] = timestamp or time.time()
            else:
                # Alarm condition not met
                if rule_key in self.active_alarms and rule["auto_clear"]:
                    # Clear alarm
                    self._clear_alarm(rule, tag_name, value, timestamp)
    
    def _evaluate_condition(self, value: Any, condition: str, threshold: Any) -> bool:
        """Evaluate if value meets alarm condition."""
        try:
            if condition == ">":
                return float(value) > float(threshold)
            elif condition == ">=":
                return float(value) >= float(threshold)
            elif condition == "<":
                return float(value) < float(threshold)
            elif condition == "<=":
                return float(value) <= float(threshold)
            elif condition == "==":
                return value == threshold
            elif condition == "!=":
                return value != threshold
            else:
                self.logger.warning(f"Unknown condition: {condition}")
                return False
        except (ValueError, TypeError) as e:
            self.logger.error(f"Error evaluating condition: {e}")
            return False
    
    def _trigger_alarm(self, rule: Dict, tag_name: str, value: Any, timestamp: Optional[float]):
        """Trigger a new alarm."""
        rule_key = f"{rule['name']}_{tag_name}"
        now = timestamp or time.time()
        
        # Check debounce
        if rule_key in self.last_notification:
            time_since_last = now - self.last_notification[rule_key]
            if time_since_last < rule["debounce_seconds"]:
                self.logger.debug(f"Alarm {rule_key} debounced ({time_since_last:.1f}s < {rule['debounce_seconds']}s)")
                return
        
        # Create alarm record
        alarm = {
            "rule_name": rule["name"],
            "tag": tag_name,
            "priority": rule["priority"],
            "message": rule["message"],
            "condition": f"{rule['condition']} {rule['threshold']}",
            "triggered_value": value,
            "last_value": value,
            "triggered_at": now,
            "last_update": now,
            "cleared_at": None,
            "status": "ACTIVE"
        }
        
        self.active_alarms[rule_key] = alarm
        self.alarm_history.append(alarm.copy())
        
        # Send notifications
        self._send_notifications(alarm, rule["channels"])
        
        self.last_notification[rule_key] = now
        
        # Log
        priority_emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}
        emoji = priority_emoji.get(rule["priority"], "⚠️")
        self.logger.warning(
            f"{emoji} ALARM TRIGGERED: {rule['name']} - {tag_name}={value} {rule['condition']} {rule['threshold']} - {rule['message']}"
        )
    
    def _clear_alarm(self, rule: Dict, tag_name: str, value: Any, timestamp: Optional[float]):
        """Clear an active alarm."""
        rule_key = f"{rule['name']}_{tag_name}"
        now = timestamp or time.time()
        
        alarm = self.active_alarms[rule_key]
        alarm["status"] = "CLEARED"
        alarm["cleared_at"] = now
        alarm["cleared_value"] = value
        
        # Update history
        self.alarm_history.append(alarm.copy())
        
        # Remove from active
        del self.active_alarms[rule_key]
        
        # Log
        self.logger.info(
            f"✅ ALARM CLEARED: {rule['name']} - {tag_name}={value} (was {alarm['triggered_value']})"
        )
        
        # Optionally send clear notification
        if "clear" in rule.get("channels", []):
            clear_alarm = alarm.copy()
            clear_alarm["message"] = f"CLEARED: {rule['message']}"
            self._send_notifications(clear_alarm, rule["channels"])
    
    def _send_notifications(self, alarm: Dict, channels: list):
        """Send alarm notifications to configured channels."""
        for channel in channels:
            if channel == "log":
                # Already logged
                pass
            elif channel == "email":
                self._send_email(alarm)
            elif channel == "slack":
                self._send_slack(alarm)
            elif channel == "sms":
                self._send_sms(alarm)
    
    def _send_email(self, alarm: Dict):
        """Send email notification."""
        email_config = self.notifications_config.get("email", {})
        if not email_config.get("enabled", False):
            return
        
        try:
            smtp_server = email_config.get("smtp_server", "localhost")
            smtp_port = email_config.get("smtp_port", 587)
            username = email_config.get("username", "")
            password = email_config.get("password", "")
            from_addr = email_config.get("from", "opcua@fireball.local")
            to_addrs = email_config.get("to", [])
            
            if not to_addrs:
                return
            
            # Create message
            msg = MIMEMultipart()
            msg["From"] = from_addr
            msg["To"] = ", ".join(to_addrs)
            msg["Subject"] = f"[{alarm['priority']}] {alarm['rule_name']} - {alarm['tag']}"
            
            body = f"""
            Alarm: {alarm['rule_name']}
            Priority: {alarm['priority']}
            Tag: {alarm['tag']}
            Value: {alarm['triggered_value']}
            Condition: {alarm['condition']}
            Message: {alarm['message']}
            Time: {datetime.fromtimestamp(alarm['triggered_at']).strftime('%Y-%m-%d %H:%M:%S')}
            Status: {alarm['status']}
            """
            
            msg.attach(MIMEText(body, "plain"))
            
            # Send
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if username and password:
                    server.starttls()
                    server.login(username, password)
                server.send_message(msg)
            
            self.logger.info(f"Email notification sent for alarm: {alarm['rule_name']}")
            
        except Exception as e:
            self.logger.error(f"Error sending email notification: {e}")
    
    def _send_slack(self, alarm: Dict):
        """Send Slack notification via webhook."""
        slack_config = self.notifications_config.get("slack", {})
        if not slack_config.get("enabled", False):
            return
        
        try:
            webhook_url = slack_config.get("webhook_url")
            if not webhook_url:
                return
            
            # Priority colors
            color_map = {
                "INFO": "#36a64f",
                "WARNING": "#ff9900",
                "CRITICAL": "#ff0000"
            }
            
            # Create Slack message
            payload = {
                "attachments": [
                    {
                        "color": color_map.get(alarm["priority"], "#808080"),
                        "title": f"[{alarm['priority']}] {alarm['rule_name']}",
                        "text": alarm["message"],
                        "fields": [
                            {"title": "Tag", "value": alarm["tag"], "short": True},
                            {"title": "Value", "value": str(alarm["triggered_value"]), "short": True},
                            {"title": "Condition", "value": alarm["condition"], "short": True},
                            {"title": "Status", "value": alarm["status"], "short": True}
                        ],
                        "footer": "OPC UA Alarm System",
                        "ts": int(alarm["triggered_at"])
                    }
                ]
            }
            
            response = requests.post(webhook_url, json=payload, timeout=5)
            response.raise_for_status()
            
            self.logger.info(f"Slack notification sent for alarm: {alarm['rule_name']}")
            
        except Exception as e:
            self.logger.error(f"Error sending Slack notification: {e}")
    
    def _send_sms(self, alarm: Dict):
        """Send SMS notification via Twilio."""
        if not TWILIO_AVAILABLE:
            self.logger.warning("Twilio library not available for SMS notifications")
            return
        
        sms_config = self.notifications_config.get("sms", {})
        if not sms_config.get("enabled", False):
            return
        
        try:
            account_sid = sms_config.get("account_sid")
            auth_token = sms_config.get("auth_token")
            from_number = sms_config.get("from_number")
            to_numbers = sms_config.get("to_numbers", [])
            
            if not all([account_sid, auth_token, from_number, to_numbers]):
                return
            
            client = TwilioClient(account_sid, auth_token)
            
            message_body = f"[{alarm['priority']}] {alarm['rule_name']}: {alarm['tag']}={alarm['triggered_value']} {alarm['condition']}. {alarm['message']}"
            
            for to_number in to_numbers:
                client.messages.create(
                    body=message_body,
                    from_=from_number,
                    to=to_number
                )
            
            self.logger.info(f"SMS notification sent for alarm: {alarm['rule_name']}")
            
        except Exception as e:
            self.logger.error(f"Error sending SMS notification: {e}")
    
    def get_active_alarms(self) -> list:
        """Get list of currently active alarms."""
        return list(self.active_alarms.values())
    
    def get_alarm_history(self, limit: int = 100) -> list:
        """Get alarm history."""
        history_list = list(self.alarm_history)
        return history_list[-limit:] if limit else history_list
    
    def acknowledge_alarm(self, rule_name: str, tag_name: str, user: str = "system"):
        """Acknowledge an active alarm (doesn't clear it, just marks as acknowledged)."""
        rule_key = f"{rule_name}_{tag_name}"
        if rule_key in self.active_alarms:
            self.active_alarms[rule_key]["acknowledged"] = True
            self.active_alarms[rule_key]["acknowledged_by"] = user
            self.active_alarms[rule_key]["acknowledged_at"] = time.time()
            self.logger.info(f"Alarm acknowledged by {user}: {rule_name} - {tag_name}")
            return True
        return False


class InfluxDBPublisher(DataPublisher):
    """
    InfluxDB Publisher - Time-series database storage
    
    Writes tag data to InfluxDB for:
    - Historical data storage
    - Trend analysis
    - Grafana dashboards
    - Long-term data retention
    - Analytics and reporting
    
    Because sometimes you need to know what happened last Tuesday at 3:47 PM.
    And because "if it's not in the database, it didn't happen."
    """
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize the InfluxDB publisher.
        
        Config structure:
        {
            "enabled": true,
            "url": "http://localhost:8086",
            "token": "your-influx-token",
            "org": "fireball-industries",
            "bucket": "industrial-data",
            "measurement": "opcua_tags",
            "batch_size": 100,
            "flush_interval": 1000  // milliseconds
        }
        """
        super().__init__(config, logger)
        
        if not INFLUXDB_AVAILABLE:
            self.logger.warning("InfluxDB client library not available. Install with: pip install influxdb-client")
            self.enabled = False
            return
        
        self.url = config.get("url", "http://localhost:8086")
        self.token = config.get("token", "")
        self.org = config.get("org", "fireball-industries")
        self.bucket = config.get("bucket", "industrial-data")
        self.measurement = config.get("measurement", "opcua_tags")
        self.batch_size = config.get("batch_size", 100)
        self.flush_interval = config.get("flush_interval", 1000)
        
        self.client = None
        self.write_api = None
        
        # Additional tags to add to each point
        self.global_tags = config.get("tags", {})
        
    def start(self):
        """Start the InfluxDB publisher."""
        if not self.enabled or not INFLUXDB_AVAILABLE:
            if not INFLUXDB_AVAILABLE:
                self.logger.warning("InfluxDB publisher is disabled (library not available)")
            else:
                self.logger.info("InfluxDB publisher is disabled")
            return
        
        try:
            # Create InfluxDB client
            self.client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org
            )
            
            # Create write API with batching
            self.write_api = self.client.write_api(
                write_options=SYNCHRONOUS
            )
            
            # Test connection by pinging
            health = self.client.health()
            if health.status == "pass":
                self.logger.info(f"InfluxDB publisher started: {self.url} -> {self.bucket}")
                self.running = True
            else:
                self.logger.error(f"InfluxDB health check failed: {health.message}")
                self.enabled = False
                
        except Exception as e:
            self.logger.error(f"Failed to start InfluxDB publisher: {e}")
            self.enabled = False
    
    def stop(self):
        """Stop the InfluxDB publisher."""
        if self.write_api:
            try:
                self.write_api.close()
                self.logger.debug("InfluxDB write API closed")
            except Exception as e:
                self.logger.error(f"Error closing InfluxDB write API: {e}")
        
        if self.client:
            try:
                self.client.close()
                self.logger.info("InfluxDB publisher stopped")
            except Exception as e:
                self.logger.error(f"Error closing InfluxDB client: {e}")
        
        self.running = False
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Write tag value to InfluxDB.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp (uses current time if not provided)
        """
        if not self.enabled or not self.running or not INFLUXDB_AVAILABLE:
            return
        
        try:
            # Create point
            point = Point(self.measurement)
            
            # Add tag name as a tag (for efficient querying)
            point.tag("tag", tag_name)
            
            # Add global tags
            for tag_key, tag_value in self.global_tags.items():
                point.tag(tag_key, tag_value)
            
            # Add value as field (type-specific)
            if isinstance(value, bool):
                point.field("value_bool", value)
                point.field("value", 1 if value else 0)  # Numeric representation
            elif isinstance(value, int):
                point.field("value_int", value)
                point.field("value", float(value))
            elif isinstance(value, float):
                point.field("value_float", value)
                point.field("value", value)
            elif isinstance(value, str):
                point.field("value_string", value)
                # Try to parse as number for graphing
                try:
                    point.field("value", float(value))
                except (ValueError, TypeError):
                    pass
            else:
                point.field("value_string", str(value))
            
            # Set timestamp
            if timestamp:
                # Convert to nanoseconds (InfluxDB native precision)
                point.time(int(timestamp * 1e9), WritePrecision.NS)
            
            # Write to InfluxDB
            self.write_api.write(bucket=self.bucket, org=self.org, record=point)
            
            self.logger.debug(f"Wrote to InfluxDB: {tag_name} = {value}")
            
        except Exception as e:
            self.logger.error(f"Error writing to InfluxDB: {e}")


class GraphQLPublisher(DataPublisher):
    """
    GraphQL API Publisher - Modern query interface
    
    Provides a GraphQL endpoint for querying tag data with advanced features:
    - Flexible queries (get specific fields you need)
    - Real-time subscriptions (future)
    - Typed schema with introspection
    - Query batching
    - Filtering and pagination
    
    GraphQL is like REST API but you're in control of exactly what data you get back.
    No more over-fetching, no more under-fetching. Just vibes.
    """
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize the GraphQL publisher.
        
        Config structure:
        {
            "enabled": true,
            "host": "0.0.0.0",
            "port": 5002,
            "graphiql": true,  // Enable GraphiQL web interface
            "cors_enabled": true
        }
        """
        super().__init__(config, logger)
        
        if not GRAPHQL_AVAILABLE:
            self.logger.warning("GraphQL libraries not available. Install with: pip install graphene flask-graphql")
            self.enabled = False
            return
        
        self.app = Flask(__name__)
        if config.get("cors_enabled", True):
            CORS(self.app)
        
        self.tags_data = {}  # In-memory tag storage
        self.server_thread = None
        
        # Build GraphQL schema
        self._setup_schema()
        
        # Add GraphQL endpoint
        host = config.get("host", "0.0.0.0")
        port = config.get("port", 5002)
        graphiql = config.get("graphiql", True)
        
        self.app.add_url_rule(
            '/graphql',
            view_func=GraphQLView.as_view(
                'graphql',
                schema=self.schema,
                graphiql=graphiql  # Enable GraphiQL IDE
            )
        )
        
        self.logger.info(f"GraphQL publisher initialized on http://{host}:{port}/graphql")
        if graphiql:
            self.logger.info(f"GraphiQL IDE available at http://{host}:{port}/graphql")
    
    def _setup_schema(self):
        """Setup GraphQL schema with types and queries."""
        
        # Define Tag type
        class TagType(graphene.ObjectType):
            name = graphene.String(description="Tag name")
            value = graphene.Field(
                graphene.String,
                description="Tag value (can be string, float, int, or bool)"
            )
            type = graphene.String(description="Data type of the tag")
            timestamp = graphene.Float(description="Last update timestamp")
            description = graphene.String(description="Tag description")
            units = graphene.String(description="Engineering units")
            min_value = graphene.Float(description="Minimum value")
            max_value = graphene.Float(description="Maximum value")
            category = graphene.String(description="Tag category")
            quality = graphene.String(description="Tag quality (good, bad, uncertain)")
            writable = graphene.Boolean(description="Whether tag is writable")
            simulation_type = graphene.String(description="Simulation type if simulated")
            
            def resolve_value(self, info):
                # Return value as string for generic handling
                return str(self.value) if self.value is not None else None
        
        # Define Statistics type
        class TagStatsType(graphene.ObjectType):
            count = graphene.Int(description="Total number of tags")
            tags = graphene.List(graphene.String, description="List of tag names")
        
        # Define Query type
        class Query(graphene.ObjectType):
            # Get single tag
            tag = graphene.Field(
                TagType,
                name=graphene.String(required=True, description="Tag name to query"),
                description="Query a single tag by name"
            )
            
            # Get all tags
            tags = graphene.List(
                TagType,
                filter=graphene.String(description="Filter tags by name pattern"),
                description="Query all tags, optionally filtered"
            )
            
            # Get tag statistics
            stats = graphene.Field(
                TagStatsType,
                description="Get statistics about available tags"
            )
            
            def resolve_tag(self, info, name):
                """Resolve single tag query."""
                if name in self.tags_data:
                    tag_data = self.tags_data[name]
                    metadata = self.tag_metadata.get(name, {})
                    return TagType(
                        name=name,
                        value=tag_data.get('value'),
                        type=metadata.get('type', 'unknown'),
                        timestamp=tag_data.get('timestamp'),
                        description=metadata.get('description', ''),
                        units=metadata.get('units', ''),
                        min_value=metadata.get('min'),
                        max_value=metadata.get('max'),
                        category=metadata.get('category', 'general'),
                        quality=metadata.get('quality', 'good'),
                        writable=metadata.get('writable', False),
                        simulation_type=metadata.get('simulation_type')
                    )
                return None
            
            def resolve_tags(self, info, filter=None):
                """Resolve all tags query with optional filtering."""
                tags = []
                for name, tag_data in self.tags_data.items():
                    # Apply filter if provided
                    if filter and filter.lower() not in name.lower():
                        continue
                    
                    metadata = self.tag_metadata.get(name, {})
                    tags.append(TagType(
                        name=name,
                        value=tag_data.get('value'),
                        type=metadata.get('type', 'unknown'),
                        timestamp=tag_data.get('timestamp'),
                        description=metadata.get('description', ''),
                        units=metadata.get('units', ''),
                        min_value=metadata.get('min'),
                        max_value=metadata.get('max'),
                        category=metadata.get('category', 'general'),
                        quality=metadata.get('quality', 'good'),
                        writable=metadata.get('writable', False),
                        simulation_type=metadata.get('simulation_type')
                    ))
                return tags
            
            def resolve_stats(self, info):
                """Resolve stats query."""
                return TagStatsType(
                    count=len(self.tags_data),
                    tags=list(self.tags_data.keys())
                )
        
        # Bind tags_data and metadata to Query class for resolvers
        Query.tags_data = self.tags_data
        Query.tag_metadata = getattr(self, 'tag_metadata', {})
        
        # Create schema
        self.schema = graphene.Schema(query=Query)
    
    def start(self):
        """Start the GraphQL API server."""
        if not self.enabled or not GRAPHQL_AVAILABLE:
            if not GRAPHQL_AVAILABLE:
                self.logger.warning("GraphQL publisher is disabled (libraries not available)")
            else:
                self.logger.info("GraphQL publisher is disabled")
            return
        
        try:
            host = self.config.get("host", "0.0.0.0")
            port = self.config.get("port", 5002)
            
            def run_server():
                self.app.run(host=host, port=port, debug=False, use_reloader=False)
            
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            
            self.logger.info(f"GraphQL API server started on http://{host}:{port}/graphql")
            
        except Exception as e:
            self.logger.error(f"Failed to start GraphQL publisher: {e}")
    
    def stop(self):
        """Stop the GraphQL API server."""
        # Flask doesn't have a graceful shutdown in this mode
        # The daemon thread will stop when the main process stops
        self.logger.info("GraphQL publisher stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Update tag value in GraphQL data store.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled or not GRAPHQL_AVAILABLE:
            return
        
        # Determine type
        value_type = type(value).__name__
        
        # Store tag data
        self.tags_data[tag_name] = {
            "value": value,
            "type": value_type,
            "timestamp": timestamp or time.time()
        }


class OPCUAClientPublisher(DataPublisher):
    """
    OPC UA Client Publisher - Push data to other OPC UA servers
    
    This publisher acts as an OPC UA client and writes tag values to
    nodes on remote OPC UA servers. Useful for pushing data to:
    - Ignition's OPC UA server
    - KEPServerEX
    - Other OPC UA servers in the network
    - Historian systems with OPC UA interfaces
    
    Features:
    - Auto-connect and reconnect on disconnection
    - Node browsing and creation
    - Multiple server support
    - Username/password authentication
    - Certificate-based security (if configured)
    - Automatic namespace handling
    """
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize the OPC UA Client publisher.
        
        Config structure:
        {
            "enabled": true,
            "servers": [
                {
                    "url": "opc.tcp://remote-server:4840",
                    "name": "Ignition Server",
                    "username": "admin",  # Optional
                    "password": "password",  # Optional
                    "namespace": 2,  # Namespace index for creating nodes
                    "base_node": "ns=2;s=Gateway/",  # Base node path
                    "auto_create_nodes": true,  # Create nodes if they don't exist
                    "node_mapping": {  # Optional: map tag names to specific node IDs
                        "Temperature": "ns=2;s=Gateway/Temperature",
                        "Pressure": "ns=2;s=Gateway/Pressure"
                    }
                }
            ],
            "reconnect_interval": 5  # Seconds between reconnection attempts
        }
        """
        super().__init__(config, logger)
        
        if not OPCUA_CLIENT_AVAILABLE:
            self.logger.warning("OPC UA Client library not available. Install with: pip install opcua")
            self.enabled = False
            return
        
        self.servers_config = config.get("servers", [])
        self.reconnect_interval = config.get("reconnect_interval", 5)
        
        # Track client connections
        self.clients = {}  # server_name -> {"client": OPCUAClient, "connected": bool, "nodes": {}}
        self.running = False
        self.reconnect_thread = None
        
        self.logger.info(f"OPC UA Client publisher initialized with {len(self.servers_config)} server(s)")
    
    def start(self):
        """Start the OPC UA client publisher."""
        if not self.enabled:
            return
        
        self.running = True
        
        # Connect to all configured servers
        for server_config in self.servers_config:
            self._connect_to_server(server_config)
        
        # Start reconnection thread
        self.reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
        self.reconnect_thread.start()
        
        self.logger.info("OPC UA Client publisher started")
    
    def stop(self):
        """Stop the OPC UA client publisher."""
        if not self.enabled:
            return
        
        self.running = False
        
        # Disconnect all clients
        for server_name, client_info in self.clients.items():
            try:
                if client_info["connected"]:
                    client_info["client"].disconnect()
                    self.logger.info(f"Disconnected from OPC UA server: {server_name}")
            except Exception as e:
                self.logger.error(f"Error disconnecting from {server_name}: {e}")
        
        self.clients.clear()
        self.logger.info("OPC UA Client publisher stopped")
    
    def _connect_to_server(self, server_config: Dict[str, Any]):
        """
        Connect to a single OPC UA server.
        
        Args:
            server_config: Server configuration dictionary
        """
        server_name = server_config.get("name", server_config["url"])
        url = server_config["url"]
        
        try:
            client = OPCUAClient(url)
            
            # Set authentication if provided
            if server_config.get("username") and server_config.get("password"):
                client.set_user(server_config["username"])
                client.set_password(server_config["password"])
            
            # Connect
            client.connect()
            
            # Store client info
            self.clients[server_name] = {
                "client": client,
                "connected": True,
                "config": server_config,
                "nodes": {},  # tag_name -> node object cache
                "root": client.get_root_node(),
                "objects": client.get_objects_node()
            }
            
            self.logger.info(f"Connected to OPC UA server: {server_name} ({url})")
            
        except Exception as e:
            self.logger.error(f"Failed to connect to {server_name}: {e}")
            self.clients[server_name] = {
                "client": None,
                "connected": False,
                "config": server_config,
                "nodes": {}
            }
    
    def _reconnect_loop(self):
        """Background thread to reconnect to disconnected servers."""
        while self.running:
            time.sleep(self.reconnect_interval)
            
            for server_name, client_info in list(self.clients.items()):
                if not client_info["connected"]:
                    self.logger.info(f"Attempting to reconnect to {server_name}...")
                    self._connect_to_server(client_info["config"])
    
    def _get_or_create_node(self, client_info: Dict[str, Any], tag_name: str):
        """
        Get or create an OPC UA node for a tag.
        
        Args:
            client_info: Client information dictionary
            tag_name: Tag name
            
        Returns:
            Node object or None
        """
        # Check cache first
        if tag_name in client_info["nodes"]:
            return client_info["nodes"][tag_name]
        
        config = client_info["config"]
        client = client_info["client"]
        
        # Check for explicit node mapping
        node_mapping = config.get("node_mapping", {})
        if tag_name in node_mapping:
            node_id = node_mapping[tag_name]
            try:
                node = client.get_node(node_id)
                client_info["nodes"][tag_name] = node
                return node
            except Exception as e:
                self.logger.error(f"Failed to get mapped node {node_id}: {e}")
                return None
        
        # Build node path from base_node + tag_name
        base_node = config.get("base_node", "")
        if base_node:
            node_id = f"{base_node}{tag_name}"
        else:
            namespace = config.get("namespace", 2)
            node_id = f"ns={namespace};s={tag_name}"
        
        try:
            # Try to get existing node
            node = client.get_node(node_id)
            # Verify it exists by reading a value (will throw if doesn't exist)
            _ = node.get_browse_name()
            client_info["nodes"][tag_name] = node
            return node
        except Exception:
            # Node doesn't exist
            if config.get("auto_create_nodes", False):
                try:
                    # Create a new variable node
                    objects = client_info["objects"]
                    namespace = config.get("namespace", 2)
                    
                    # Create the variable
                    node = objects.add_variable(namespace, tag_name, 0.0)
                    node.set_writable()
                    
                    client_info["nodes"][tag_name] = node
                    self.logger.info(f"Created new node: {node_id}")
                    return node
                except Exception as e:
                    self.logger.error(f"Failed to create node {node_id}: {e}")
                    return None
            else:
                self.logger.warning(f"Node {node_id} not found and auto_create_nodes is disabled")
                return None
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Publish tag value to all connected OPC UA servers.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp (currently not used)
        """
        if not self.enabled:
            return
        
        for server_name, client_info in self.clients.items():
            if not client_info["connected"]:
                continue
            
            try:
                # Get or create the node
                node = self._get_or_create_node(client_info, tag_name)
                if not node:
                    continue
                
                # Convert Python types to OPC UA DataValue
                if isinstance(value, bool):
                    ua_value = ua.DataValue(ua.Variant(value, ua.VariantType.Boolean))
                elif isinstance(value, int):
                    ua_value = ua.DataValue(ua.Variant(value, ua.VariantType.Int32))
                elif isinstance(value, float):
                    ua_value = ua.DataValue(ua.Variant(value, ua.VariantType.Double))
                elif isinstance(value, str):
                    ua_value = ua.DataValue(ua.Variant(value, ua.VariantType.String))
                else:
                    ua_value = ua.DataValue(ua.Variant(str(value), ua.VariantType.String))
                
                # Write the value
                node.set_value(ua_value)
                self.logger.debug(f"Wrote {tag_name}={value} to {server_name}")
                
            except Exception as e:
                self.logger.error(f"Error writing {tag_name} to {server_name}: {e}")
                # Mark as disconnected on error
                client_info["connected"] = False


class PrometheusPublisher(DataPublisher):
    """
    Prometheus Metrics Publisher - Operational monitoring
    
    Exposes operational metrics for:
    - Tag update counts
    - Publisher health status
    - Message throughput
    - Error rates
    - System uptime
    
    Because if you're not monitoring it, it's not in production.
    And because "trust but verify" applies to industrial systems too.
    """
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize the Prometheus publisher.
        
        Config structure:
        {
            "enabled": true,
            "port": 9090,
            "include_publisher_metrics": true,
            "include_tag_metrics": true
        }
        """
        super().__init__(config, logger)
        
        if not PROMETHEUS_AVAILABLE:
            self.logger.warning("Prometheus client library not available. Install with: pip install prometheus-client")
            self.enabled = False
            return
        
        self.port = config.get("port", 9090)
        self.include_publisher_metrics = config.get("include_publisher_metrics", True)
        self.include_tag_metrics = config.get("include_tag_metrics", True)
        
        # Create metrics
        self._create_metrics()
        
        # Track start time for uptime
        self.start_time = time.time()
        
    def _create_metrics(self):
        """Create Prometheus metrics."""
        # System metrics
        self.system_info = Info('emberburn_system', 'EmberBurn system information')
        self.system_uptime = Gauge('emberburn_uptime_seconds', 'System uptime in seconds')
        
        # Tag metrics
        self.tags_total = Gauge('emberburn_tags_total', 'Total number of tags')
        self.tag_updates_total = Counter('emberburn_tag_updates_total', 'Total tag updates', ['tag_name'])
        self.tag_update_errors = Counter('emberburn_tag_update_errors_total', 'Tag update errors', ['tag_name'])
        self.tag_value = Gauge('emberburn_tag_value', 'Current tag value (numeric only)', ['tag_name'])
        
        # Publisher metrics
        self.publishers_total = Gauge('emberburn_publishers_total', 'Total number of publishers')
        self.publishers_enabled = Gauge('emberburn_publishers_enabled', 'Number of enabled publishers')
        self.publisher_health = Gauge('emberburn_publisher_health', 'Publisher health status (1=healthy, 0=unhealthy)', ['publisher_name'])
        self.publisher_messages_sent = Counter('emberburn_publisher_messages_total', 'Messages sent by publisher', ['publisher_name'])
        self.publisher_errors = Counter('emberburn_publisher_errors_total', 'Publisher errors', ['publisher_name'])
        
        # Performance metrics
        self.publish_duration = Histogram('emberburn_publish_duration_seconds', 'Time spent publishing', ['publisher_name'])
        
        # Alarm metrics
        self.alarms_active = Gauge('emberburn_alarms_active', 'Number of active alarms')
        self.alarms_critical = Gauge('emberburn_alarms_critical', 'Number of critical alarms')
        self.alarms_warning = Gauge('emberburn_alarms_warning', 'Number of warning alarms')
        self.alarms_triggered = Counter('emberburn_alarms_triggered_total', 'Total alarms triggered', ['alarm_name', 'priority'])
        
        # Set system info
        self.system_info.info({
            'version': '1.0',
            'platform': 'emberburn',
            'protocols': '13'  # 12 protocols + Prometheus
        })
        
    def start(self):
        """Start the Prometheus publisher."""
        if not self.enabled:
            self.logger.info("Prometheus publisher is disabled")
            return
        
        try:
            # Metrics are exposed via the /metrics endpoint in REST API
            # No separate server needed
            self.logger.info(f"Prometheus metrics available at /metrics endpoint")
            
        except Exception as e:
            self.logger.error(f"Failed to start Prometheus publisher: {e}")
            self.enabled = False
    
    def stop(self):
        """Stop the Prometheus publisher."""
        self.logger.info("Prometheus publisher stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Update tag metrics.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled:
            return
        
        try:
            # Increment tag update counter
            self.tag_updates_total.labels(tag_name=tag_name).inc()
            
            # Update tag value gauge (if numeric)
            if isinstance(value, (int, float)):
                self.tag_value.labels(tag_name=tag_name).set(value)
        
        except Exception as e:
            self.logger.error(f"Error updating tag metrics: {e}")
            self.tag_update_errors.labels(tag_name=tag_name).inc()
    
    def update_system_metrics(self, tags_count: int):
        """Update system-level metrics."""
        if not self.enabled:
            return
        
        try:
            self.tags_total.set(tags_count)
            self.system_uptime.set(time.time() - self.start_time)
        except Exception as e:
            self.logger.error(f"Error updating system metrics: {e}")
    
    def update_publisher_metrics(self, publishers: list):
        """Update publisher health metrics."""
        if not self.enabled:
            return
        
        try:
            self.publishers_total.set(len(publishers))
            enabled_count = sum(1 for p in publishers if p.get('enabled', False))
            self.publishers_enabled.set(enabled_count)
            
            # Update individual publisher health
            for pub in publishers:
                name = pub.get('name', 'unknown')
                health = 1 if pub.get('enabled', False) else 0
                self.publisher_health.labels(publisher_name=name).set(health)
        
        except Exception as e:
            self.logger.error(f"Error updating publisher metrics: {e}")
    
    def update_alarm_metrics(self, alarms: list):
        """Update alarm metrics."""
        if not self.enabled:
            return
        
        try:
            self.alarms_active.set(len(alarms))
            
            critical_count = sum(1 for a in alarms if a.get('priority') == 'CRITICAL')
            warning_count = sum(1 for a in alarms if a.get('priority') == 'WARNING')
            
            self.alarms_critical.set(critical_count)
            self.alarms_warning.set(warning_count)
        
        except Exception as e:
            self.logger.error(f"Error updating alarm metrics: {e}")
    
    def record_publisher_message(self, publisher_name: str):
        """Record a message sent by a publisher."""
        if not self.enabled:
            return
        
        try:
            self.publisher_messages_sent.labels(publisher_name=publisher_name).inc()
        except Exception as e:
            self.logger.error(f"Error recording publisher message: {e}")
    
    def record_publisher_error(self, publisher_name: str):
        """Record a publisher error."""
        if not self.enabled:
            return
        
        try:
            self.publisher_errors.labels(publisher_name=publisher_name).inc()
        except Exception as e:
            self.logger.error(f"Error recording publisher error: {e}")
    
    def record_alarm_triggered(self, alarm_name: str, priority: str):
        """Record an alarm being triggered."""
        if not self.enabled:
            return
        
        try:
            self.alarms_triggered.labels(alarm_name=alarm_name, priority=priority).inc()
        except Exception as e:
            self.logger.error(f"Error recording alarm trigger: {e}")


class SQLitePersistencePublisher(DataPublisher):
    """
    SQLite Persistence Publisher - Local data storage with historical tag values and audit logging.
    
    Features:
    - Historical tag value storage with timestamps
    - Audit logging for system events
    - Configurable retention policies
    - Automatic database cleanup
    - Thread-safe operations
    - Query API for historical data
    """
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """Initialize SQLite persistence publisher."""
        super().__init__(config, logger)
        self.db_path = self.config.get("db_path", "emberburn_data.db")
        self.retention_days = self.config.get("retention_days", 30)
        self.batch_size = self.config.get("batch_size", 100)
        self.enable_tag_history = self.config.get("enable_tag_history", True)
        self.enable_audit_log = self.config.get("enable_audit_log", True)
        self.auto_vacuum = self.config.get("auto_vacuum", True)
        
        self.connection = None
        self.db_lock = threading.Lock()
        self.write_buffer = []
        self.audit_buffer = []
        
    def start(self):
        """Start the SQLite publisher and initialize database."""
        try:
            self._init_database()
            self.enabled = True
            self.logger.info(f"SQLite persistence started (database: {self.db_path})")
            self._log_audit_event("system", "SQLitePersistence", "Publisher started", "info")
        except Exception as e:
            self.logger.error(f"Failed to start SQLite persistence: {e}")
            self.enabled = False
    
    def stop(self):
        """Stop the SQLite publisher and flush buffers."""
        try:
            self._flush_buffers()
            self._log_audit_event("system", "SQLitePersistence", "Publisher stopped", "info")
            
            if self.connection:
                self.connection.close()
                self.connection = None
            
            self.enabled = False
            self.logger.info("SQLite persistence stopped")
        except Exception as e:
            self.logger.error(f"Error stopping SQLite persistence: {e}")
    
    def publish(self, tag_name: str, value: Any, data_type: str):
        """
        Publish tag value to SQLite database.
        
        Args:
            tag_name: Name of the tag
            value: Tag value
            data_type: Data type of the tag
        """
        if not self.enabled or not self.enable_tag_history:
            return
        
        try:
            # Convert value to string for storage
            value_str = str(value)
            timestamp = datetime.now().isoformat()
            
            # Add to write buffer
            self.write_buffer.append((tag_name, value_str, data_type, timestamp))
            
            # Flush if batch size reached
            if len(self.write_buffer) >= self.batch_size:
                self._flush_tag_history()
            
        except Exception as e:
            self.logger.error(f"Error publishing to SQLite: {e}")
    
    def _init_database(self):
        """Initialize SQLite database and create tables."""
        with self.db_lock:
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = self.connection.cursor()
            
            # Tag history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tag_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tag_name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes for performance
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_tag_history_tag_name 
                ON tag_history(tag_name)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_tag_history_timestamp 
                ON tag_history(timestamp DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_tag_history_created_at 
                ON tag_history(created_at DESC)
            ''')
            
            # Audit log table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_source TEXT NOT NULL,
                    event_details TEXT,
                    severity TEXT DEFAULT 'info',
                    user TEXT,
                    timestamp TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_log_event_type 
                ON audit_log(event_type)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp 
                ON audit_log(timestamp DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_log_severity 
                ON audit_log(severity)
            ''')
            
            # System events table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    severity TEXT DEFAULT 'info',
                    details TEXT,
                    timestamp TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_system_events_timestamp 
                ON system_events(timestamp DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_system_events_severity 
                ON system_events(severity)
            ''')
            
            # Publisher statistics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS publisher_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publisher_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    messages_sent INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    last_message TEXT,
                    timestamp TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_publisher_stats_publisher 
                ON publisher_stats(publisher_name, timestamp DESC)
            ''')
            
            self.connection.commit()
            
            # Auto-vacuum if enabled
            if self.auto_vacuum:
                cursor.execute("PRAGMA auto_vacuum = FULL")
                cursor.execute("VACUUM")
            
            self.logger.info(f"SQLite database initialized at {self.db_path}")
    
    def _flush_tag_history(self):
        """Flush tag history buffer to database."""
        if not self.write_buffer:
            return
        
        try:
            with self.db_lock:
                cursor = self.connection.cursor()
                cursor.executemany(
                    'INSERT INTO tag_history (tag_name, value, data_type, timestamp) VALUES (?, ?, ?, ?)',
                    self.write_buffer
                )
                self.connection.commit()
                self.logger.debug(f"Flushed {len(self.write_buffer)} tag history records")
                self.write_buffer.clear()
        except Exception as e:
            self.logger.error(f"Error flushing tag history: {e}")
    
    def _flush_audit_log(self):
        """Flush audit log buffer to database."""
        if not self.audit_buffer:
            return
        
        try:
            with self.db_lock:
                cursor = self.connection.cursor()
                cursor.executemany(
                    'INSERT INTO audit_log (event_type, event_source, event_details, severity, user, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
                    self.audit_buffer
                )
                self.connection.commit()
                self.logger.debug(f"Flushed {len(self.audit_buffer)} audit log records")
                self.audit_buffer.clear()
        except Exception as e:
            self.logger.error(f"Error flushing audit log: {e}")
    
    def _flush_buffers(self):
        """Flush all buffers to database."""
        self._flush_tag_history()
        self._flush_audit_log()
    
    def _log_audit_event(self, event_type: str, event_source: str, event_details: str, 
                        severity: str = "info", user: str = None):
        """
        Log an audit event.
        
        Args:
            event_type: Type of event (system, tag, publisher, alarm, user)
            event_source: Source of the event
            event_details: Details of the event
            severity: Severity level (info, warning, error, critical)
            user: User who triggered the event (optional)
        """
        if not self.enabled or not self.enable_audit_log:
            return
        
        try:
            timestamp = datetime.now().isoformat()
            self.audit_buffer.append((event_type, event_source, event_details, severity, user, timestamp))
            
            # Flush if batch size reached
            if len(self.audit_buffer) >= self.batch_size:
                self._flush_audit_log()
        except Exception as e:
            self.logger.error(f"Error logging audit event: {e}")
    
    def log_system_event(self, event_type: str, message: str, severity: str = "info", details: str = None):
        """
        Log a system event.
        
        Args:
            event_type: Type of event (startup, shutdown, error, etc.)
            message: Event message
            severity: Severity level
            details: Additional details (optional)
        """
        if not self.enabled:
            return
        
        try:
            timestamp = datetime.now().isoformat()
            with self.db_lock:
                cursor = self.connection.cursor()
                cursor.execute(
                    'INSERT INTO system_events (event_type, message, severity, details, timestamp) VALUES (?, ?, ?, ?, ?)',
                    (event_type, message, severity, details, timestamp)
                )
                self.connection.commit()
        except Exception as e:
            self.logger.error(f"Error logging system event: {e}")
    
    def log_publisher_stats(self, publisher_name: str, status: str, messages_sent: int = 0, 
                           errors: int = 0, last_message: str = None):
        """
        Log publisher statistics.
        
        Args:
            publisher_name: Name of the publisher
            status: Current status
            messages_sent: Number of messages sent
            errors: Number of errors
            last_message: Last message sent
        """
        if not self.enabled:
            return
        
        try:
            timestamp = datetime.now().isoformat()
            with self.db_lock:
                cursor = self.connection.cursor()
                cursor.execute(
                    'INSERT INTO publisher_stats (publisher_name, status, messages_sent, errors, last_message, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
                    (publisher_name, status, messages_sent, errors, last_message, timestamp)
                )
                self.connection.commit()
        except Exception as e:
            self.logger.error(f"Error logging publisher stats: {e}")
    
    def cleanup_old_data(self):
        """Clean up data older than retention period."""
        if not self.enabled:
            return
        
        try:
            cutoff_date = (datetime.now() - timedelta(days=self.retention_days)).isoformat()
            
            with self.db_lock:
                cursor = self.connection.cursor()
                
                # Clean up tag history
                cursor.execute('DELETE FROM tag_history WHERE timestamp < ?', (cutoff_date,))
                tag_deleted = cursor.rowcount
                
                # Clean up audit log
                cursor.execute('DELETE FROM audit_log WHERE timestamp < ?', (cutoff_date,))
                audit_deleted = cursor.rowcount
                
                # Clean up system events
                cursor.execute('DELETE FROM system_events WHERE timestamp < ?', (cutoff_date,))
                events_deleted = cursor.rowcount
                
                # Clean up publisher stats
                cursor.execute('DELETE FROM publisher_stats WHERE timestamp < ?', (cutoff_date,))
                stats_deleted = cursor.rowcount
                
                self.connection.commit()
                
                if self.auto_vacuum:
                    cursor.execute("VACUUM")
                
                self.logger.info(
                    f"Cleaned up old data: {tag_deleted} tag records, {audit_deleted} audit records, "
                    f"{events_deleted} system events, {stats_deleted} publisher stats"
                )
                
                self._log_audit_event("system", "SQLitePersistence", 
                                     f"Cleaned up {tag_deleted + audit_deleted + events_deleted + stats_deleted} old records",
                                     "info")
        except Exception as e:
            self.logger.error(f"Error cleaning up old data: {e}")
    
    def get_tag_history(self, tag_name: str, start_time: str = None, end_time: str = None, 
                       limit: int = 1000) -> List[Tuple]:
        """
        Get historical tag values.
        
        Args:
            tag_name: Name of the tag
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            limit: Maximum number of records to return
            
        Returns:
            List of tuples (tag_name, value, data_type, timestamp)
        """
        if not self.enabled:
            return []
        
        try:
            with self.db_lock:
                cursor = self.connection.cursor()
                
                query = 'SELECT tag_name, value, data_type, timestamp FROM tag_history WHERE tag_name = ?'
                params = [tag_name]
                
                if start_time:
                    query += ' AND timestamp >= ?'
                    params.append(start_time)
                
                if end_time:
                    query += ' AND timestamp <= ?'
                    params.append(end_time)
                
                query += ' ORDER BY timestamp DESC LIMIT ?'
                params.append(limit)
                
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Error getting tag history: {e}")
            return []
    
    def get_audit_log(self, event_type: str = None, severity: str = None, 
                     start_time: str = None, end_time: str = None, limit: int = 1000) -> List[Tuple]:
        """
        Get audit log entries.
        
        Args:
            event_type: Filter by event type
            severity: Filter by severity
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            limit: Maximum number of records to return
            
        Returns:
            List of tuples (event_type, event_source, event_details, severity, user, timestamp)
        """
        if not self.enabled:
            return []
        
        try:
            with self.db_lock:
                cursor = self.connection.cursor()
                
                query = 'SELECT event_type, event_source, event_details, severity, user, timestamp FROM audit_log WHERE 1=1'
                params = []
                
                if event_type:
                    query += ' AND event_type = ?'
                    params.append(event_type)
                
                if severity:
                    query += ' AND severity = ?'
                    params.append(severity)
                
                if start_time:
                    query += ' AND timestamp >= ?'
                    params.append(start_time)
                
                if end_time:
                    query += ' AND timestamp <= ?'
                    params.append(end_time)
                
                query += ' ORDER BY timestamp DESC LIMIT ?'
                params.append(limit)
                
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Error getting audit log: {e}")
            return []
    
    def get_database_stats(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Dictionary with database statistics
        """
        if not self.enabled:
            return {}
        
        try:
            with self.db_lock:
                cursor = self.connection.cursor()
                
                stats = {}
                
                # Tag history count
                cursor.execute('SELECT COUNT(*) FROM tag_history')
                stats['tag_history_count'] = cursor.fetchone()[0]
                
                # Audit log count
                cursor.execute('SELECT COUNT(*) FROM audit_log')
                stats['audit_log_count'] = cursor.fetchone()[0]
                
                # System events count
                cursor.execute('SELECT COUNT(*) FROM system_events')
                stats['system_events_count'] = cursor.fetchone()[0]
                
                # Publisher stats count
                cursor.execute('SELECT COUNT(*) FROM publisher_stats')
                stats['publisher_stats_count'] = cursor.fetchone()[0]
                
                # Database file size
                cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
                stats['database_size_bytes'] = cursor.fetchone()[0]
                stats['database_size_mb'] = round(stats['database_size_bytes'] / 1024 / 1024, 2)
                
                # Oldest record
                cursor.execute('SELECT MIN(timestamp) FROM tag_history')
                oldest = cursor.fetchone()[0]
                stats['oldest_record'] = oldest if oldest else None
                
                # Newest record
                cursor.execute('SELECT MAX(timestamp) FROM tag_history')
                newest = cursor.fetchone()[0]
                stats['newest_record'] = newest if newest else None
                
                return stats
        except Exception as e:
            self.logger.error(f"Error getting database stats: {e}")
            return {}


class DataTransformationPublisher(DataPublisher):
    """
    Data Transformation Publisher - Apply transformations, unit conversions, and computed tags.
    
    Features:
    - Unit conversions (temperature, pressure, flow, etc.)
    - Scaling and offset calculations
    - Expression-based computed tags
    - Tag aliasing
    - Safe expression evaluation
    """
    
    # Unit conversion definitions
    UNIT_CONVERSIONS = {
        # Temperature
        'celsius_to_fahrenheit': lambda c: c * 9/5 + 32,
        'fahrenheit_to_celsius': lambda f: (f - 32) * 5/9,
        'celsius_to_kelvin': lambda c: c + 273.15,
        'kelvin_to_celsius': lambda k: k - 273.15,
        'fahrenheit_to_kelvin': lambda f: (f - 32) * 5/9 + 273.15,
        'kelvin_to_fahrenheit': lambda k: (k - 273.15) * 9/5 + 32,
        
        # Pressure
        'kpa_to_psi': lambda kpa: kpa * 0.145038,
        'psi_to_kpa': lambda psi: psi / 0.145038,
        'bar_to_psi': lambda bar: bar * 14.5038,
        'psi_to_bar': lambda psi: psi / 14.5038,
        'kpa_to_bar': lambda kpa: kpa / 100,
        'bar_to_kpa': lambda bar: bar * 100,
        
        # Flow
        'lpm_to_gpm': lambda lpm: lpm * 0.264172,  # L/min to gal/min
        'gpm_to_lpm': lambda gpm: gpm / 0.264172,
        'lps_to_gps': lambda lps: lps * 0.264172,  # L/s to gal/s
        'gps_to_lps': lambda gps: gps / 0.264172,
        
        # Length
        'mm_to_inch': lambda mm: mm / 25.4,
        'inch_to_mm': lambda inch: inch * 25.4,
        'cm_to_inch': lambda cm: cm / 2.54,
        'inch_to_cm': lambda inch: inch * 2.54,
        'm_to_ft': lambda m: m * 3.28084,
        'ft_to_m': lambda ft: ft / 3.28084,
        
        # Mass
        'kg_to_lb': lambda kg: kg * 2.20462,
        'lb_to_kg': lambda lb: lb / 2.20462,
        'g_to_oz': lambda g: g * 0.035274,
        'oz_to_g': lambda oz: oz / 0.035274,
        
        # Volume
        'l_to_gal': lambda l: l * 0.264172,
        'gal_to_l': lambda gal: gal / 0.264172,
        'ml_to_floz': lambda ml: ml * 0.033814,
        'floz_to_ml': lambda floz: floz / 0.033814,
        
        # Speed
        'mps_to_fps': lambda mps: mps * 3.28084,  # m/s to ft/s
        'fps_to_mps': lambda fps: fps / 3.28084,
        'kph_to_mph': lambda kph: kph * 0.621371,
        'mph_to_kph': lambda mph: mph / 0.621371,
    }
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """Initialize data transformation publisher."""
        super().__init__(config, logger)
        
        self.transformations = self.config.get("transformations", [])
        self.computed_tags = self.config.get("computed_tags", [])
        self.enable_conversions = self.config.get("enable_conversions", True)
        self.enable_computed = self.config.get("enable_computed", True)
        
        self.source_tags = {}  # Store source tag values
        self.transformed_cache = {}  # Cache transformed values
        self.write_callback = None  # Callback to write transformed tags back
        
        # Safe math functions for expressions
        self.safe_functions = {
            'abs': abs,
            'round': round,
            'min': min,
            'max': max,
            'sum': sum,
            'pow': pow,
            'sqrt': math.sqrt,
            'sin': math.sin,
            'cos': math.cos,
            'tan': math.tan,
            'log': math.log,
            'log10': math.log10,
            'exp': math.exp,
            'floor': math.floor,
            'ceil': math.ceil,
        }
        
    def start(self):
        """Start the transformation publisher."""
        try:
            self.enabled = True
            self.logger.info(f"Data transformation started ({len(self.transformations)} transformations, "
                           f"{len(self.computed_tags)} computed tags)")
        except Exception as e:
            self.logger.error(f"Failed to start data transformation: {e}")
            self.enabled = False
    
    def stop(self):
        """Stop the transformation publisher."""
        self.enabled = False
        self.logger.info("Data transformation stopped")
    
    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """
        Store source tag value and trigger transformations.
        
        Args:
            tag_name: Name of the source tag
            value: Tag value
            timestamp: Optional timestamp
        """
        if not self.enabled:
            return
        
        try:
            # Store source value
            self.source_tags[tag_name] = {
                'value': value,
                'timestamp': timestamp or time.time()
            }
            
            # Apply transformations for this source tag
            if self.enable_conversions:
                self._apply_transformations(tag_name, value, timestamp)
            
            # Update computed tags that depend on this source
            if self.enable_computed:
                self._update_computed_tags(tag_name)
            
        except Exception as e:
            self.logger.error(f"Error in transformation publish: {e}")
    
    def _apply_transformations(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """Apply configured transformations to a tag."""
        for transform in self.transformations:
            try:
                # Check if this transformation applies to this tag
                if transform.get('source_tag') != tag_name:
                    continue
                
                transform_type = transform.get('type')
                target_tag = transform.get('target_tag')
                
                if transform_type == 'unit_conversion':
                    # Apply unit conversion
                    conversion = transform.get('conversion')
                    if conversion in self.UNIT_CONVERSIONS:
                        converted_value = self.UNIT_CONVERSIONS[conversion](value)
                        self._write_transformed_tag(target_tag, converted_value, timestamp)
                    else:
                        self.logger.warning(f"Unknown conversion: {conversion}")
                
                elif transform_type == 'scale_offset':
                    # Apply scaling and offset: output = (input * scale) + offset
                    scale = transform.get('scale', 1.0)
                    offset = transform.get('offset', 0.0)
                    transformed_value = (value * scale) + offset
                    self._write_transformed_tag(target_tag, transformed_value, timestamp)
                
                elif transform_type == 'alias':
                    # Simple alias/copy
                    self._write_transformed_tag(target_tag, value, timestamp)
                
                elif transform_type == 'custom':
                    # Custom transformation function
                    expression = transform.get('expression')
                    if expression:
                        result = self._evaluate_expression(expression, {'value': value})
                        self._write_transformed_tag(target_tag, result, timestamp)
                
            except Exception as e:
                self.logger.error(f"Error applying transformation {transform.get('target_tag')}: {e}")
    
    def _update_computed_tags(self, changed_tag: str):
        """Update computed tags that depend on the changed source tag."""
        for computed in self.computed_tags:
            try:
                # Check if this computed tag depends on the changed tag
                dependencies = computed.get('dependencies', [])
                if changed_tag not in dependencies:
                    continue
                
                # Check if all dependencies are available
                if not all(dep in self.source_tags for dep in dependencies):
                    continue
                
                # Build context with all source values
                context = {
                    dep: self.source_tags[dep]['value']
                    for dep in dependencies
                }
                
                # Evaluate expression
                expression = computed.get('expression')
                target_tag = computed.get('target_tag')
                
                if expression and target_tag:
                    result = self._evaluate_expression(expression, context)
                    timestamp = max(self.source_tags[dep]['timestamp'] for dep in dependencies)
                    self._write_transformed_tag(target_tag, result, timestamp)
                
            except Exception as e:
                self.logger.error(f"Error updating computed tag {computed.get('target_tag')}: {e}")
    
    def _evaluate_expression(self, expression: str, context: Dict[str, Any]) -> Any:
        """
        Safely evaluate a mathematical expression.
        
        Args:
            expression: Expression to evaluate
            context: Variables available in the expression
            
        Returns:
            Evaluated result
        """
        try:
            # Create safe evaluation context
            safe_dict = {
                '__builtins__': {},
                **self.safe_functions,
                **context
            }
            
            # Evaluate expression
            result = eval(expression, safe_dict)
            return result
            
        except Exception as e:
            self.logger.error(f"Error evaluating expression '{expression}': {e}")
            raise
    
    def _write_transformed_tag(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        """Write a transformed tag value."""
        # Cache the value
        self.transformed_cache[tag_name] = {
            'value': value,
            'timestamp': timestamp or time.time()
        }
        
        # Call write callback if set (to write back to OPC UA server)
        if self.write_callback:
            try:
                self.write_callback(tag_name, value)
            except Exception as e:
                self.logger.error(f"Error writing transformed tag {tag_name}: {e}")
    
    def set_write_callback(self, callback: Callable):
        """Set callback function for writing transformed tags."""
        self.write_callback = callback
    
    def get_transformed_tags(self) -> Dict[str, Any]:
        """Get all transformed tag values."""
        return self.transformed_cache
    
    def add_transformation(self, transformation: Dict[str, Any]):
        """Add a transformation at runtime."""
        self.transformations.append(transformation)
        self.logger.info(f"Added transformation: {transformation.get('target_tag')}")
    
    def add_computed_tag(self, computed_tag: Dict[str, Any]):
        """Add a computed tag at runtime."""
        self.computed_tags.append(computed_tag)
        self.logger.info(f"Added computed tag: {computed_tag.get('target_tag')}")
    
    def get_available_conversions(self) -> List[str]:
        """Get list of available unit conversions."""
        return sorted(list(self.UNIT_CONVERSIONS.keys()))


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
        
        # Sparkplug B Publisher (for Ignition)
        sparkplug_config = publishers_config.get("sparkplug_b", {})
        if sparkplug_config.get("enabled", False):
            sparkplug_pub = SparkplugBPublisher(sparkplug_config, self.logger)
            self.publishers.append(sparkplug_pub)
            self.logger.info("Sparkplug B publisher initialized")
        
        # Kafka Publisher
        kafka_config = publishers_config.get("kafka", {})
        if kafka_config.get("enabled", False):
            kafka_pub = KafkaPublisher(kafka_config, self.logger)
            self.publishers.append(kafka_pub)
            self.logger.info("Kafka publisher initialized")
        
        # AMQP Publisher (RabbitMQ)
        amqp_config = publishers_config.get("amqp", {})
        if amqp_config.get("enabled", False):
            amqp_pub = AMQPPublisher(amqp_config, self.logger)
            self.publishers.append(amqp_pub)
            self.logger.info("AMQP publisher initialized")
        
        # WebSocket Publisher
        websocket_config = publishers_config.get("websocket", {})
        if websocket_config.get("enabled", False):
            websocket_pub = WebSocketPublisher(websocket_config, self.logger)
            self.publishers.append(websocket_pub)
            self.logger.info("WebSocket publisher initialized")
        
        # MODBUS TCP Publisher
        modbus_config = publishers_config.get("modbus_tcp", {})
        if modbus_config.get("enabled", False):
            modbus_pub = ModbusTCPPublisher(modbus_config, self.logger)
            self.publishers.append(modbus_pub)
            self.logger.info("MODBUS TCP publisher initialized")
        
        # GraphQL API Publisher
        graphql_config = publishers_config.get("graphql", {})
        if graphql_config.get("enabled", False):
            graphql_pub = GraphQLPublisher(graphql_config, self.logger)
            self.publishers.append(graphql_pub)
            self.logger.info("GraphQL API publisher initialized")
        
        # InfluxDB Publisher
        influxdb_config = publishers_config.get("influxdb", {})
        if influxdb_config.get("enabled", False):
            influxdb_pub = InfluxDBPublisher(influxdb_config, self.logger)
            self.publishers.append(influxdb_pub)
            self.logger.info("InfluxDB publisher initialized")
        
        # Alarms Publisher
        alarms_config = publishers_config.get("alarms", {})
        if alarms_config.get("enabled", False):
            alarms_pub = AlarmsPublisher(alarms_config, self.logger)
            self.publishers.append(alarms_pub)
            self.logger.info("Alarms publisher initialized")
        
        # OPC UA Client Publisher
        opcua_client_config = publishers_config.get("opcua_client", {})
        if opcua_client_config.get("enabled", False):
            opcua_client_pub = OPCUAClientPublisher(opcua_client_config, self.logger)
            self.publishers.append(opcua_client_pub)
            self.logger.info("OPC UA Client publisher initialized")
        
        # REST API Publisher
        rest_config = publishers_config.get("rest_api", {})
        if rest_config.get("enabled", False):
            rest_pub = RESTAPIPublisher(rest_config, self.logger)
            self.publishers.append(rest_pub)
            self.logger.info("REST API publisher initialized")
        
        # Prometheus Publisher
        prometheus_config = publishers_config.get("prometheus", {})
        if prometheus_config.get("enabled", False):
            prometheus_pub = PrometheusPublisher(prometheus_config, self.logger)
            self.publishers.append(prometheus_pub)
            self.logger.info("Prometheus publisher initialized")
        
        # SQLite Persistence Publisher
        sqlite_config = publishers_config.get("sqlite_persistence", {})
        if sqlite_config.get("enabled", False):
            sqlite_pub = SQLitePersistencePublisher(sqlite_config, self.logger)
            self.publishers.append(sqlite_pub)
            self.logger.info("SQLite Persistence publisher initialized")
        
        # Data Transformation Publisher
        transformation_config = publishers_config.get("data_transformation", {})
        if transformation_config.get("enabled", False):
            transformation_pub = DataTransformationPublisher(transformation_config, self.logger)
            self.publishers.append(transformation_pub)
            self.logger.info("Data Transformation publisher initialized")
        
        return self.publishers
    
    def start_all(self):
        """Start all publishers."""
        for publisher in self.publishers:
            try:
                publisher.start()
            except Exception as e:
                self.logger.error(f"Error starting publisher {publisher.__class__.__name__}: {e}")
        
        # Setup API callbacks for REST API publisher
        for publisher in self.publishers:
            if isinstance(publisher, RESTAPIPublisher):
                # Set publisher statuses callback
                publisher._publisher_statuses = self.get_publisher_statuses()
                
                # Set toggle callback
                def toggle_callback(name):
                    return self.toggle_publisher(name)
                publisher._toggle_callback = toggle_callback
                
                # Set alarms callback
                def alarms_callback():
                    return self.get_active_alarms()
                publisher._alarms_callback = alarms_callback
                
                break
        
        # Update Prometheus with initial publisher states
        prometheus_pub = self._get_prometheus_publisher()
        if prometheus_pub:
            statuses = self.get_publisher_statuses()
            prometheus_pub.update_publisher_metrics(statuses)
    
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
                
                # Update Prometheus metrics for successful publish
                if isinstance(publisher, PrometheusPublisher):
                    continue  # Don't record metrics publisher itself
                    
                prometheus_pub = self._get_prometheus_publisher()
                if prometheus_pub:
                    publisher_name = publisher.__class__.__name__.replace('Publisher', '')
                    prometheus_pub.record_publisher_message(publisher_name)
                    
            except Exception as e:
                self.logger.error(f"Error publishing to {publisher.__class__.__name__}: {e}")
                
                # Record error in Prometheus
                prometheus_pub = self._get_prometheus_publisher()
                if prometheus_pub:
                    publisher_name = publisher.__class__.__name__.replace('Publisher', '')
                    prometheus_pub.record_publisher_error(publisher_name)
        
        # Update system metrics
        prometheus_pub = self._get_prometheus_publisher()
        if prometheus_pub:
            # Count unique tags (would need to track this properly in real implementation)
            prometheus_pub.update_system_metrics(tags_count=1)  # Placeholder
    
    def _get_prometheus_publisher(self):
        """Get the Prometheus publisher instance."""
        for publisher in self.publishers:
            if isinstance(publisher, PrometheusPublisher):
                return publisher
        return None
    
    def get_publisher_statuses(self):
        """Get status of all publishers."""
        statuses = []
        for publisher in self.publishers:
            # Determine publisher name
            class_name = publisher.__class__.__name__.replace('Publisher', '')
            
            # Map class names to friendly names
            name_map = {
                'MQTT': 'MQTT',
                'REST API': 'REST API',
                'SparkplugB': 'Sparkplug B',
                'Kafka': 'Kafka',
                'AMQP': 'AMQP',
                'WebSocket': 'WebSocket',
                'ModbusTCP': 'MODBUS TCP',
                'GraphQL': 'GraphQL',
                'InfluxDB': 'InfluxDB',
                'Alarms': 'Alarms',
                'OPCUAClient': 'OPC UA Client',
                'Prometheus': 'Prometheus',
                'SQLitePersistence': 'SQLite Persistence'
            }
            
            friendly_name = name_map.get(class_name, class_name)
            
            statuses.append({
                'name': friendly_name,
                'enabled': publisher.enabled,
                'class': publisher.__class__.__name__
            })
        
        return statuses
    
    def toggle_publisher(self, publisher_name: str):
        """Toggle a publisher on/off."""
        for publisher in self.publishers:
            class_name = publisher.__class__.__name__.replace('Publisher', '')
            name_map = {
                'MQTT': 'MQTT',
                'REST API': 'REST API',
                'SparkplugB': 'Sparkplug B',
                'Kafka': 'Kafka',
                'AMQP': 'AMQP',
                'WebSocket': 'WebSocket',
                'ModbusTCP': 'MODBUS TCP',
                'GraphQL': 'GraphQL',
                'InfluxDB': 'InfluxDB',
                'Alarms': 'Alarms',
                'OPCUAClient': 'OPC UA Client',
                'Prometheus': 'Prometheus',
                'SQLitePersistence': 'SQLite Persistence'
            }
            
            friendly_name = name_map.get(class_name, class_name)
            
            if friendly_name == publisher_name:
                publisher.enabled = not publisher.enabled
                if publisher.enabled:
                    try:
                        publisher.start()
                        self.logger.info(f"Publisher {publisher_name} enabled and started")
                    except Exception as e:
                        self.logger.error(f"Error starting publisher {publisher_name}: {e}")
                        publisher.enabled = False
                        return False
                else:
                    try:
                        publisher.stop()
                        self.logger.info(f"Publisher {publisher_name} disabled")
                    except Exception as e:
                        self.logger.error(f"Error stopping publisher {publisher_name}: {e}")
                
                return True
        
        return False
    
    def get_active_alarms(self):
        """Get active alarms from the Alarms publisher."""
        for publisher in self.publishers:
            if isinstance(publisher, AlarmsPublisher):
                return publisher.get_active_alarms()
        return []