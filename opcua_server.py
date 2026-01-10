#!/usr/bin/env python3
"""
OPC UA Server for Ignition Edge
A configurable OPC UA server that simulates industrial tags with various data types. 

Author: Your Friendly Neighborhood Engineer
License: MIT
"""

from opcua import Server
import json
import time
import random
import os
import signal
import sys
import logging
from datetime import datetime
from pathlib import Path
from publishers import PublisherManager


class OPCUAServer: 
    """
    OPC UA Server with configurable tags and simulation capabilities. 
    
    Supports multiple data types (float, int, string, bool) and simulation modes
    (random, increment, static) for industrial automation testing.
    """
    
    def __init__(self, config_file="tags_config.json", log_level="INFO"):
        """
        Initialize the OPC UA Server.
        
        Args:
            config_file (str): Path to the tags configuration JSON file
            log_level (str): Logging level (DEBUG, INFO, WARNING, ERROR)
        """
        self.server = None
        self.config_file = config_file
        self.running = True
        self.tags = {}
        self.tag_metadata = {}  # Store tag metadata
        self.update_interval = float(os.getenv('UPDATE_INTERVAL', '2'))
        self.publisher_manager = None
        self.full_config = None
        
        # Setup logging
        self.setup_logging(log_level)
        
    def setup_logging(self, log_level):
        """Configure logging with timestamp and level."""
        numeric_level = getattr(logging, log_level.upper(), None)
        if not isinstance(numeric_level, int):
            numeric_level = logging.INFO
            
        logging.basicConfig(
            level=numeric_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger = logging.getLogger('OPCUAServer')
        
    def signal_handler(self, sig, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info("Shutdown signal received...")
        self.running = False
        
    def load_tag_config(self):
        """
        Load tag configuration from JSON file. 
        
        Returns:
            dict: Tag configuration dictionary
        """
        try:
            config_path = Path(self.config_file)
            if not config_path.exists():
                self.logger.warning(f"Config file {self.config_file} not found, using defaults")
                return self.get_default_config()
                
            with open(config_path, 'r') as f:
                config = json.load(f)
                self.logger.info(f"Loaded configuration from {self.config_file}")
                # Store full config for publishers
                self.full_config = config
                # Return just the tags section if it exists, otherwise use entire config as tags
                return config.get('tags', config)
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in config file: {e}")
            self.logger.info("Using default configuration")
            return self.get_default_config()
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            return self.get_default_config()
    
    def get_default_config(self):
        """
        Return default tag configuration.
        
        Returns:
            dict: Default tag configuration
        """
        return {
            "Temperature": {
                "type": "float",
                "initial_value": 20.0,
                "simulate": True,
                "simulation_type": "random",
                "min": 15.0,
                "max": 25.0,
                "description": "Ambient temperature sensor"
            },
            "Pressure": {
                "type": "float",
                "initial_value": 101.3,
                "simulate": True,
                "simulation_type": "random",
                "min": 99.0,
                "max": 103.0,
                "description": "System pressure in kPa"
            },
            "Counter": {
                "type": "int",
                "initial_value": 0,
                "simulate": True,
                "simulation_type": "increment",
                "increment": 1,
                "description": "Production counter"
            },
            "Status": {
                "type": "string",
                "initial_value": "Running",
                "simulate": False,
                "description": "System status message"
            },
            "IsRunning": {
                "type": "bool",
                "initial_value": True,
                "simulate": False,
                "description": "System running flag"
            }
        }
    
    def convert_initial_value(self, value, tag_type):
        """
        Convert initial value to the appropriate type.
        
        Args:
            value:  The value to convert
            tag_type (str): Target type (int, float, string, bool)
            
        Returns:
            Converted value
        """
        try:
            if tag_type == "int":
                return int(value)
            elif tag_type == "float":
                return float(value)
            elif tag_type == "string":
                return str(value)
            elif tag_type == "bool":
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes', 'on')
                return bool(value)
            else:
                self.logger.warning(f"Unknown type {tag_type}, defaulting to float")
                return float(value)
        except (ValueError, TypeError) as e:
            self.logger.error(f"Error converting value {value} to {tag_type}: {e}")
            return value
    
    def create_server(self):
        """
        Initialize and configure the OPC UA server.
        
        Returns:
            int:  Namespace index
        """
        self.server = Server()
        
        # Server endpoint configuration
        endpoint = os.getenv('OPC_ENDPOINT', 'opc.tcp://0.0.0.0:4840/freeopcua/server/')
        self.server.set_endpoint(endpoint)
        
        server_name = os.getenv('OPC_SERVER_NAME', 'Python OPC UA Server')
        self.server.set_server_name(server_name)
        
        # Setup namespace
        uri = os.getenv('OPC_NAMESPACE', 'http://opcua.edge.server')
        idx = self.server.register_namespace(uri)
        
        # Get Objects node
        objects = self.server.get_objects_node()
        
        # Create device object/folder
        device_name = os.getenv('OPC_DEVICE_NAME', 'EdgeDevice')
        myobj = objects.add_object(idx, device_name)
        
        # Load tag configuration
        tag_config = self.load_tag_config()
        
        # Create tags based on config
        for tag_name, tag_info in tag_config.items():
            try:
                initial_value = tag_info.get("initial_value", 0)
                tag_type = tag_info.get("type", "float")
                description = tag_info.get("description", "")
                
                # Convert initial value to appropriate type
                initial_value = self.convert_initial_value(initial_value, tag_type)
                
                # Create OPC UA variable
                var = myobj.add_variable(idx, tag_name, initial_value)
                var.set_writable()
                
                # Store tag information
                self.tags[tag_name] = {
                    "variable": var,
                    "config": tag_info,
                    "type": tag_type
                }
                
                # Store tag metadata for publishers
                self.tag_metadata[tag_name] = {
                    "type": tag_type,
                    "description": tag_info.get("description", ""),
                    "units": tag_info.get("units", ""),
                    "min": tag_info.get("min"),
                    "max": tag_info.get("max"),
                    "category": tag_info.get("category", "general"),
                    "quality": tag_info.get("quality", "good"),
                    "writable": tag_info.get("writable", False),
                    "simulation_type": tag_info.get("simulation_type")
                }
                
                self.logger.debug(f"Created tag: {tag_name} ({tag_type}) = {initial_value}")
                
            except Exception as e:
                self.logger.error(f"Error creating tag {tag_name}: {e}")
        
        self.logger.info(f"OPC UA Server configured with {len(self.tags)} tags")
        return idx
    
    def write_tag(self, tag_name: str, value):
        """
        Write a value to a tag (used by transformation publisher).
        
        Args:
            tag_name: Name of the tag to write
            value: Value to write
        """
        try:
            if tag_name in self.tags:
                var = self.tags[tag_name]["variable"]
                var.set_value(value)
                self.logger.debug(f"Wrote transformed tag {tag_name} = {value}")
            else:
                # Create new tag for transformed/computed values
                if self.server:
                    objects = self.server.get_objects_node()
                    idx = self.server.get_namespace_index("http://ignition-edge.example")
                    myobj = objects.get_child([f"{idx}:IgnitionEdge"])
                    
                    # Determine type from value
                    if isinstance(value, bool):
                        tag_type = "bool"
                    elif isinstance(value, int):
                        tag_type = "int"
                    elif isinstance(value, float):
                        tag_type = "float"
                    else:
                        tag_type = "string"
                    
                    var = myobj.add_variable(idx, tag_name, value)
                    var.set_writable()
                    
                    self.tags[tag_name] = {
                        "variable": var,
                        "config": {"simulate": False},
                        "type": tag_type
                    }
                    
                    self.logger.info(f"Created new transformed tag: {tag_name} = {value}")
        except Exception as e:
            self.logger.error(f"Error writing tag {tag_name}: {e}")
    
    def update_tags(self):
        """Update tag values based on simulation configuration."""
        timestamp = time.time()
        
        for tag_name, tag_data in self.tags.items():
            try:
                var = tag_data["variable"]
                config = tag_data["config"]
                tag_type = tag_data["type"]
                
                # Only update if simulation is enabled
                if not config.get("simulate", False):
                    continue
                
                sim_type = config.get("simulation_type", "random")
                current_value = var.get_value()
                
                if sim_type == "random":
                    new_value = self.generate_random_value(config, tag_type)
                    var.set_value(new_value)
                    self.logger.debug(f"{tag_name}: {current_value} -> {new_value}")
                    
                elif sim_type == "increment":
                    new_value = self.generate_increment_value(current_value, config, tag_type)
                    var.set_value(new_value)
                    self.logger.debug(f"{tag_name}: {current_value} -> {new_value}")
                    
                elif sim_type == "sine":
                    new_value = self.generate_sine_value(config, tag_type)
                    var.set_value(new_value)
                    self.logger.debug(f"{tag_name}: {current_value} -> {new_value}")
                
                # Publish to all configured publishers (MQTT, REST API, etc.)
                if self.publisher_manager:
                    self.publisher_manager.publish_to_all(tag_name, var.get_value(), timestamp)
                    
            except Exception as e:
                self.logger.error(f"Error updating tag {tag_name}: {e}")
    
    def generate_random_value(self, config, tag_type):
        """
        Generate a random value within configured range.
        
        Args:
            config (dict): Tag configuration
            tag_type (str): Data type
            
        Returns: 
            Random value of appropriate type
        """
        min_val = config.get("min", 0)
        max_val = config.get("max", 100)
        
        if tag_type == "int":
            return random.randint(int(min_val), int(max_val))
        elif tag_type == "float":
            return round(random.uniform(min_val, max_val), 2)
        elif tag_type == "bool":
            return random.choice([True, False])
        else:
            return random.uniform(min_val, max_val)
    
    def generate_increment_value(self, current_value, config, tag_type):
        """
        Generate an incremented value.
        
        Args:
            current_value: Current tag value
            config (dict): Tag configuration
            tag_type (str): Data type
            
        Returns:
            Incremented value
        """
        increment = config.get("increment", 1)
        max_val = config.get("max", None)
        reset_on_max = config.get("reset_on_max", False)
        
        new_value = current_value + increment
        
        # Handle rollover if max is set
        if max_val is not None and new_value >= max_val:
            if reset_on_max:
                new_value = config.get("min", 0)
        
        if tag_type == "int":
            return int(new_value)
        else:
            return float(new_value)
    
    def generate_sine_value(self, config, tag_type):
        """
        Generate a sine wave value.
        
        Args:
            config (dict): Tag configuration
            tag_type (str): Data type
            
        Returns:
            Sine wave value
        """
        import math
        
        amplitude = config.get("amplitude", 10)
        offset = config.get("offset", 0)
        period = config.get("period", 60)  # seconds
        
        # Use current time for sine calculation
        t = time.time()
        value = offset + amplitude * math.sin(2 * math.pi * t / period)
        
        if tag_type == "int":
            return int(value)
        else:
            return round(value, 2)
    
    def print_server_info(self):
        """Print server startup information."""
        print("\n" + "="*60)
        print("  OPC UA Server Started")
        print("="*60)
        print(f"  Endpoint: {self.server.endpoint}")
        print(f"  Update Interval: {self.update_interval}s")
        print(f"  Tags Configured: {len(self.tags)}")
        print("-"*60)
        print("  Available Tags:")
        for tag_name, tag_data in self.tags.items():
            tag_type = tag_data["type"]
            simulate = tag_data["config"].get("simulate", False)
            sim_type = tag_data["config"].get("simulation_type", "static") if simulate else "static"
            print(f"    • {tag_name:20s} ({tag_type:6s}) - {sim_type}")
        print("="*60)
        print("  Press Ctrl+C to stop")
        print("="*60 + "\n")
    
    def run(self):
        """Start and run the OPC UA server."""
        # Register signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        try:
            # Create and start server
            self.create_server()
            self.server.start()
            
            self.logger.info(f"OPC UA Server started at {self.server.endpoint}")
            
            # Initialize and start data publishers
            if self.full_config:
                self.publisher_manager = PublisherManager(self.full_config, self.logger)
                self.publisher_manager.initialize_publishers()
                
                # Pass tag metadata to publishers that need it
                self._setup_tag_metadata()
                
                # Setup write callback for transformation publisher
                self._setup_transformation_callback()
                
                self.publisher_manager.start_all()
            
            self.print_server_info()
            
            # Main loop
            while self.running:
                self.update_tags()
                time.sleep(self.update_interval)
                
        except Exception as e:
            self.logger.error(f"Server error: {e}", exc_info=True)
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Gracefully shutdown the server."""
        self.logger.info("Shutting down server...")
    
    def _setup_tag_metadata(self):
        """Setup tag metadata for publishers that need it."""
        if not self.publisher_manager:
            return
        
        # Pass metadata to REST API publisher
        for publisher in self.publisher_manager.publishers:
            if hasattr(publisher, 'tag_cache'):
                # This is likely the REST API or GraphQL publisher
                publisher.tag_metadata = self.tag_metadata
                self.logger.debug(f"Passed tag metadata to {publisher.__class__.__name__}")
    
    def _setup_transformation_callback(self):
        """Setup write callback for transformation publisher."""
        if not self.publisher_manager:
            return
        
        # Find transformation publisher and set write callback
        for publisher in self.publisher_manager.publishers:
            if publisher.__class__.__name__ == 'DataTransformationPublisher':
                publisher.set_write_callback(self.write_tag)
                self.logger.info("Transformation publisher write callback configured")
                break
        
        # Stop publishers first
        if self.publisher_manager:
            try:
                self.publisher_manager.stop_all()
                self.logger.info("Publishers stopped successfully")
            except Exception as e:
                self.logger.error(f"Error stopping publishers: {e}")
        
        # Stop OPC UA server
        if self.server:
            try:
                self.server.stop()
                self.logger.info("Server stopped successfully")
            except Exception as e:
                self.logger.error(f"Error during shutdown: {e}")
        print("\nServer stopped. Goodbye!\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='OPC UA Server for Ignition Edge')
    parser.add_argument(
        '-c', '--config',
        default='tags_config.json',
        help='Path to tags configuration file (default: tags_config.json)'
    )
    parser.add_argument(
        '-l', '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )
    parser.add_argument(
        '-i', '--interval',
        type=float,
        help='Update interval in seconds (overrides UPDATE_INTERVAL env var)'
    )
    
    args = parser.parse_args()
    
    # Override update interval if specified
    if args.interval:
        os.environ['UPDATE_INTERVAL'] = str(args.interval)
    
    # Create and run server
    server = OPCUAServer(config_file=args.config, log_level=args.log_level)
    server.run()


if __name__ == "__main__":
    main()