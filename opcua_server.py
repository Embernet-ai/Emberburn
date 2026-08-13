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

logger = logging.getLogger("OPCUAServer")

# Defaults are generous for a tag gateway — a browse response is a handful of
# chunks — while still bounding memory well under any sane pod limit.
DEFAULT_MAX_CHUNKS = 512
DEFAULT_MAX_MESSAGE_BYTES = 16 * 1024 * 1024

# Evaluation rank. Simulations that read another tag must run after whatever
# they read, so a compressor that started this scan cools the room this scan.
#
# Refrigeration is a loop, not a chain: the thermostat switches on what the room
# is doing, and the room does what the thermostat switched. Ranking `hysteresis`
# between the independent types and `thermostat` breaks the cycle in the
# physically correct place — the controller reads the temperature the room
# reached last scan, exactly like a real one sampling its probe.
SIM_RANK = {"hysteresis": 1, "thermostat": 2, "follows": 2, "accumulate": 2}
DEFAULT_SIM_RANK = 0

# Distinguishes "no value recorded yet" from a legitimately recorded False.
_NO_VALUE = object()


def apply_chunk_limits(max_chunks: int = DEFAULT_MAX_CHUNKS,
                       max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES) -> bool:
    """
    Bound OPC UA message reassembly to mitigate CVE-2022-25304.

    python-opcua accumulates incoming chunks in SecureConnection._incoming_parts,
    a plain list that is only cleared when a Final or Abort chunk arrives. A
    client can therefore open a session and stream unlimited Intermediate chunks
    without ever terminating the message, and the server grows until it dies.

    The CVE affects every released version of `opcua` and of its successor
    `asyncua`, so there is no upgrade that fixes it. Since the library is pure
    Python and we own the process, cap it here instead: refuse a message once it
    exceeds either limit and raise UaError, which python-opcua already handles by
    tearing down the offending channel. One abusive client loses its connection;
    the server keeps serving everyone else.

    Returns True if the guard was installed. Returns False — loudly — if the
    library internals have moved, so a silent lapse in the mitigation is visible
    rather than assumed.
    """
    try:
        from opcua import ua
        from opcua.common.connection import SecureConnection
    except Exception as e:
        logger.error(f"Cannot apply OPC UA chunk limits, import failed: {e}")
        return False

    if getattr(SecureConnection, "_emberburn_chunk_guard", False):
        return True

    original_receive = getattr(SecureConnection, "_receive", None)
    if original_receive is None:
        logger.error(
            "Cannot apply OPC UA chunk limits: SecureConnection._receive is gone. "
            "CVE-2022-25304 is UNMITIGATED — keep port 4840 off untrusted networks."
        )
        return False

    def guarded_receive(self, msg):
        # Byte total is tracked incrementally; summing the list on every chunk
        # would make reassembly quadratic.
        pending = len(self._incoming_parts)
        accumulated = getattr(self, "_emberburn_pending_bytes", 0)
        accumulated += len(getattr(msg, "Body", b"") or b"")

        if pending >= max_chunks or accumulated > max_message_bytes:
            self._incoming_parts = []
            self._emberburn_pending_bytes = 0
            raise ua.UaError(
                f"Message exceeds limits ({pending + 1} chunks, {accumulated} bytes; "
                f"max {max_chunks} chunks, {max_message_bytes} bytes) — "
                "closing channel (CVE-2022-25304 guard)"
            )

        result = original_receive(self, msg)

        # _receive clears _incoming_parts once a message completes or aborts.
        self._emberburn_pending_bytes = accumulated if self._incoming_parts else 0
        return result

    SecureConnection._receive = guarded_receive
    SecureConnection._emberburn_chunk_guard = True
    logger.info(
        f"OPC UA chunk limits applied: max {max_chunks} chunks, "
        f"{max_message_bytes} bytes per message (CVE-2022-25304 mitigation)"
    )
    return True


class OPCUAServer: 
    """
    OPC UA Server with configurable tags and simulation capabilities.

    Supports multiple data types (float, int, string, bool) and simulation modes
    for industrial automation testing:

      random      independent value in [min, max] every scan
      increment   counter, optionally rolling over at max
      sine        smooth wave from amplitude/offset/period
      duty_cycle  boolean that runs on/off for configured durations
      hysteresis  boolean under two-position control of another tag
      event       boolean that pulses rarely, for a random duration
      walk        bounded random walk with optional drift
      thermostat  temperature pulled down by a driver boolean, drifting up
                  toward ambient when that driver is off
      follows     mirrors another tag after a lag, with optional disagreement
      accumulate  integrates another tag over time, for energy counters
      clock       hour / minute / second of local time
      computed    value from an expression over other tags

    The behavioural ones exist because plant data has cause and effect. `bool` +
    `random` is a coin flip every scan, which reads as noise to anyone who has
    seen a real compressor, and no correlation between tags means no story to
    tell about a site.

    Tags are created in the running program — through the web UI or the REST
    API — and persisted to the data volume, NOT declared in a config file that
    has to be edited and redeployed. See define_tag and the runtime tag store.
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
        # Set once the address space exists; runtime-authored tags are attached
        # to the same folder and namespace as the configured ones.
        self.device_node = None
        self.namespace_index = 0
        
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
    
    def configure_security(self):
        """
        Apply the OPC UA security policy and user authentication.

        Off by default and deliberately so: turning encryption or user auth on
        makes every existing anonymous client fail to connect until it is
        reconfigured with credentials and a trusted certificate. Operators opt
        in per deployment via the Helm chart once their SCADA clients are ready.

        Note this is entirely independent of the web UI on port 5000 — it does
        not affect the Embernet Dashboard iframe, which speaks HTTP, not OPC UA.

        Environment:
            OPC_SECURITY_ENABLED  "true" to require signing and encryption
            OPC_ALLOW_ANONYMOUS   "false" to reject anonymous sessions
            OPC_USERS             "user1:pass1,user2:pass2"
            OPC_CERT_FILE         server certificate (required when enabled)
            OPC_KEY_FILE          server private key (required when enabled)
        """
        security_enabled = os.getenv('OPC_SECURITY_ENABLED', 'false').lower() == 'true'
        allow_anonymous = os.getenv('OPC_ALLOW_ANONYMOUS', 'true').lower() == 'true'

        if not security_enabled and allow_anonymous:
            self.logger.warning(
                "OPC UA endpoint is anonymous and unencrypted. Keep port 4840 on "
                "a trusted network, or set OPC_SECURITY_ENABLED=true."
            )
            return

        if security_enabled:
            cert_file = os.getenv('OPC_CERT_FILE', '')
            key_file = os.getenv('OPC_KEY_FILE', '')

            if not cert_file or not key_file:
                # Failing loudly beats silently serving plaintext when the
                # operator believes they enabled encryption.
                raise RuntimeError(
                    "OPC_SECURITY_ENABLED=true requires OPC_CERT_FILE and "
                    "OPC_KEY_FILE to be set"
                )

            try:
                from opcua import ua
                self.server.load_certificate(cert_file)
                self.server.load_private_key(key_file)
                self.server.set_security_policy([
                    ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                    ua.SecurityPolicyType.Basic256Sha256_Sign,
                ])
                self.logger.info("OPC UA security policy: Basic256Sha256 (sign/encrypt)")
            except Exception as e:
                raise RuntimeError(f"Failed to configure OPC UA security: {e}") from e

        if not allow_anonymous:
            users = self._parse_users(os.getenv('OPC_USERS', ''))
            if not users:
                raise RuntimeError(
                    "OPC_ALLOW_ANONYMOUS=false requires OPC_USERS "
                    "(format: user1:pass1,user2:pass2)"
                )

            def user_manager(isession, username, password):
                expected = users.get(username)
                # compare_digest keeps this constant-time against guessing.
                import hmac
                return expected is not None and hmac.compare_digest(expected, password or '')

            try:
                self.server.user_manager.set_user_manager(user_manager)
                self.logger.info(
                    f"OPC UA user authentication enabled for {len(users)} user(s)"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to configure OPC UA user manager: {e}") from e

    @staticmethod
    def _parse_users(raw: str) -> dict:
        """Parse an OPC_USERS string of the form 'user1:pass1,user2:pass2'."""
        users = {}
        for entry in raw.split(','):
            entry = entry.strip()
            if not entry or ':' not in entry:
                continue
            username, password = entry.split(':', 1)
            if username:
                users[username] = password
        return users

    def create_server(self):
        """
        Initialize and configure the OPC UA server.

        Returns:
            int:  Namespace index
        """
        # Must run before any client can connect.
        apply_chunk_limits(
            max_chunks=int(os.getenv('OPC_MAX_CHUNKS', DEFAULT_MAX_CHUNKS)),
            max_message_bytes=int(
                os.getenv('OPC_MAX_MESSAGE_BYTES', DEFAULT_MAX_MESSAGE_BYTES)
            ),
        )

        self.server = Server()

        # Server endpoint configuration
        endpoint = os.getenv('OPC_ENDPOINT', 'opc.tcp://0.0.0.0:4840/freeopcua/server/')
        self.server.set_endpoint(endpoint)
        
        server_name = os.getenv('OPC_SERVER_NAME', 'Python OPC UA Server')
        self.server.set_server_name(server_name)

        self.configure_security()

        # Setup namespace
        uri = os.getenv('OPC_NAMESPACE', 'http://opcua.edge.server')
        idx = self.server.register_namespace(uri)
        
        # Get Objects node
        objects = self.server.get_objects_node()
        
        # Create device object/folder
        device_name = os.getenv('OPC_DEVICE_NAME', 'EdgeDevice')
        myobj = objects.add_object(idx, device_name)
        
        # Remember where new tags are attached so tags created at runtime land
        # in the same folder and namespace as the configured ones.
        self.device_node = myobj
        self.namespace_index = idx

        # Load tag configuration. Tags authored at runtime are layered on top,
        # so a tag created through the API or the web UI outlives the pod.
        tag_config = dict(self.load_tag_config())
        tag_config.update(self.load_runtime_tags())

        # Create tags based on config
        for tag_name, tag_info in tag_config.items():
            try:
                initial_value = tag_info.get("initial_value", 0)
                tag_type = tag_info.get("type", "float")
                description = tag_info.get("description", "")

                # Convert initial value to appropriate type
                initial_value = self.convert_initial_value(initial_value, tag_type)

                # Create OPC UA variable
                var = myobj.add_variable(self.node_id_for(tag_name), tag_name, initial_value)
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
    
    # ------------------------------------------------------------------
    # Runtime tag authoring
    #
    # Tags are meant to be created in the running program — through the web UI
    # or the REST API — not baked into a config file that someone has to edit
    # and redeploy. Two things have to be true for that to work: a tag created
    # at runtime must carry its full simulation config (not just a value), and
    # it must still be there after the pod restarts.
    # ------------------------------------------------------------------

    def node_id_for(self, tag_name):
        """
        Build a stable OPC UA NodeId for a tag.

        `add_variable(idx, name, value)` asks the server to assign the next free
        NUMERIC identifier, so a tag's NodeId depends on the order tags happen
        to be created in. An OPC client that bound to `ns=2;i=7` keeps that
        binding, and the next start — a reordered tag store, one tag added, one
        removed — silently points it at a different tag. Nothing errors; the
        screen just shows the wrong number.

        A string NodeId derived from the tag name is stable across restarts and
        readable in a client's browse tree, which is also what makes an OPC item
        path worth writing down: `ns=2;s=PLC_PRG/Baja_Temp`.
        """
        from opcua import ua
        return ua.NodeId(tag_name, self.namespace_index)

    def runtime_tag_store_path(self):
        """
        Where runtime-authored tag definitions are kept.

        Defaults to the persistent data volume. Anywhere else and tags created
        in the UI vanish on the next restart, which is the whole failure this
        store exists to prevent.
        """
        return Path(os.getenv("EMBERBURN_TAG_STORE", "/app/data/tags.json"))

    def load_runtime_tags(self):
        """
        Load tag definitions authored at runtime.

        A missing store is the normal first-boot case, not an error. A corrupt
        one is reported and skipped rather than taking the server down with it —
        losing the tags someone added is bad, refusing to start at all is worse.
        """
        path = self.runtime_tag_store_path()
        try:
            if not path.exists():
                return {}
            with open(path, "r") as f:
                tags = json.load(f)
            if not isinstance(tags, dict):
                self.logger.error(f"Runtime tag store {path} is not an object, ignoring")
                return {}
            self.logger.info(f"Loaded {len(tags)} runtime tag(s) from {path}")
            return tags
        except json.JSONDecodeError as e:
            self.logger.error(f"Runtime tag store {path} is not valid JSON, ignoring: {e}")
            return {}
        except Exception as e:
            self.logger.error(f"Error reading runtime tag store {path}: {e}")
            return {}

    def save_runtime_tags(self) -> bool:
        """
        Persist every runtime-authored tag definition.

        Written to a temporary file and moved into place, so a restart in the
        middle of a bulk import cannot leave a half-written store that fails to
        parse on the way back up.
        """
        path = self.runtime_tag_store_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            definitions = {
                name: data["config"]
                for name, data in self.tags.items()
                if data.get("runtime")
            }
            temp_path = path.with_suffix(path.suffix + ".tmp")
            with open(temp_path, "w") as f:
                json.dump(definitions, f, indent=2)
            temp_path.replace(path)
            self.logger.debug(f"Persisted {len(definitions)} runtime tag(s) to {path}")
            return True
        except Exception as e:
            self.logger.error(f"Error writing runtime tag store {path}: {e}")
            return False

    def sync_computed_tags(self):
        """
        Hand every `computed` tag to the transformation publisher.

        A tag whose `simulation_type` is `computed` carries an `expression` and
        its `dependencies` in its own definition, so it is created, persisted
        and deleted through the same tag API as everything else instead of
        living in chart values. This collects them into the shape the
        transformation publisher wants and replaces its set wholesale, which
        keeps deletes working — an incremental add would leave a removed tag
        being computed forever.
        """
        if not self.publisher_manager:
            return

        computed = []
        for name, data in self.tags.items():
            config = data.get("config", {})
            if config.get("simulation_type") != "computed":
                continue
            if not config.get("expression"):
                self.logger.warning(f"Computed tag {name} has no expression, skipping")
                continue
            entry = {
                "target_tag": name,
                "expression": config["expression"],
                "dependencies": config.get("dependencies", {}),
                "description": config.get("description", ""),
            }
            if config.get("window_seconds"):
                entry["window_seconds"] = config["window_seconds"]
            computed.append(entry)

        for publisher in self.publisher_manager.publishers:
            if hasattr(publisher, "set_computed_tags"):
                publisher.set_computed_tags(computed)

    def define_tag(self, tag_name: str, definition: dict, persist: bool = True) -> bool:
        """
        Create or redefine a tag from a full definition.

        This is what the REST API and the web UI call. `write_tag` only carries
        a value, so a tag created through it was registered with
        `{"simulate": False}` and never simulated no matter what the caller
        asked for — which is exactly why tag sets ended up hardcoded into the
        chart instead of being authored in the app.

        Args:
            tag_name: Name of the tag. May contain `/` to express a UNS path.
            definition: Tag config — `type`, `initial_value`, `simulate`,
                `simulation_type` and whatever keys that model takes.
            persist: Write the runtime store afterwards. Bulk callers pass
                False and save once at the end.

        Returns:
            True if the tag is now defined.
        """
        try:
            tag_type = definition.get("type", "float")
            initial_value = self.convert_initial_value(
                definition.get("initial_value", 0), tag_type
            )

            existing = self.tags.get(tag_name)
            if existing is not None:
                # Redefining: keep the live node, swap the definition. Deleting
                # and re-adding the variable would break any client subscription
                # to it.
                existing["config"] = definition
                existing["type"] = tag_type
                existing["runtime"] = True
                existing.pop("sim", None)          # stale phase timers
                if definition.get("reset_value", False):
                    existing["variable"].set_value(initial_value)
            else:
                if self.device_node is None:
                    self.logger.error(
                        f"Cannot define tag {tag_name}: OPC UA server not started"
                    )
                    return False
                var = self.device_node.add_variable(
                    self.node_id_for(tag_name), tag_name, initial_value
                )
                var.set_writable()
                self.tags[tag_name] = {
                    "variable": var,
                    "config": definition,
                    "type": tag_type,
                    "runtime": True,
                }

            self.tag_metadata[tag_name] = {
                "type": tag_type,
                "description": definition.get("description", ""),
                "units": definition.get("units", ""),
                "min": definition.get("min"),
                "max": definition.get("max"),
                "category": definition.get("category", "general"),
                "quality": definition.get("quality", "good"),
                "writable": definition.get("writable", True),
                "simulation_type": definition.get("simulation_type"),
            }
            self._setup_tag_metadata()
            self.sync_computed_tags()

            if persist:
                self.save_runtime_tags()

            self.logger.info(
                f"Defined tag {tag_name} ({tag_type}, "
                f"{definition.get('simulation_type') if definition.get('simulate') else 'static'})"
            )
            return True
        except Exception as e:
            self.logger.error(f"Error defining tag {tag_name}: {e}")
            return False

    def write_tag(self, tag_name: str, value) -> bool:
        """
        Write a value to a tag, creating it if it does not exist yet.

        Used by the transformation publisher and by the REST API write/create
        endpoints.

        Args:
            tag_name: Name of the tag to write
            value: Value to write

        Returns:
            True if the value was written (or the tag was created), False if the
            write failed. Callers branch on this, so it must never return None.
        """
        try:
            if tag_name in self.tags:
                var = self.tags[tag_name]["variable"]
                var.set_value(value)
                self.logger.debug(f"Wrote transformed tag {tag_name} = {value}")
                return True
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
                    
                    var = myobj.add_variable(self.node_id_for(tag_name), tag_name, value)
                    var.set_writable()
                    
                    self.tags[tag_name] = {
                        "variable": var,
                        "config": {"simulate": False},
                        "type": tag_type
                    }
                    
                    self.logger.info(f"Created new transformed tag: {tag_name} = {value}")
                    return True

                self.logger.error(
                    f"Cannot write tag {tag_name}: OPC UA server not started"
                )
                return False
        except Exception as e:
            self.logger.error(f"Error writing tag {tag_name}: {e}")
            return False

    def delete_tag(self, tag_name: str) -> bool:
        """
        Remove a tag from the OPC UA address space.

        The REST DELETE endpoint used to clear only the publisher's tag_cache,
        which the next update cycle repopulated from self.tags — so the tag
        reappeared within one UPDATE_INTERVAL while the API reported success.
        Deleting here is what actually makes it stick.

        Args:
            tag_name: Name of the tag to delete

        Returns:
            True if the tag was removed, False if it did not exist or the
            removal failed.
        """
        if tag_name not in self.tags:
            self.logger.warning(f"Cannot delete unknown tag: {tag_name}")
            return False

        try:
            variable = self.tags[tag_name].get("variable")
            if variable is not None:
                variable.delete()
        except Exception as e:
            # Address-space removal failed, but we still drop our reference so
            # the tag stops being published and simulated.
            self.logger.error(f"Error removing OPC UA node for {tag_name}: {e}")

        was_runtime = self.tags[tag_name].get("runtime", False)
        del self.tags[tag_name]
        self.tag_metadata.pop(tag_name, None)
        # Persist the removal, or the tag comes back on the next restart and
        # the delete looks like it silently failed.
        if was_runtime:
            self.save_runtime_tags()
        self.logger.info(f"Deleted tag: {tag_name}")
        return True

    def simulation_order(self):
        """
        Return (tag_name, tag_data) pairs ordered so drivers update before the
        tags that read them.

        `sorted` is stable, so tags keep their configured order within each
        rank. Recomputed per scan rather than cached because the REST API and
        the transformation publisher can both create tags at runtime.
        """
        return sorted(
            self.tags.items(),
            key=lambda item: SIM_RANK.get(
                item[1]["config"].get("simulation_type"), DEFAULT_SIM_RANK
            )
        )

    def update_tags(self):
        """Update tag values based on simulation configuration."""
        timestamp = time.time()

        for tag_name, tag_data in self.simulation_order():
            try:
                var = tag_data["variable"]
                config = tag_data["config"]
                tag_type = tag_data["type"]

                sim_type = config.get("simulation_type", "random")
                current_value = var.get_value()

                # A tag that isn't simulated still has a value worth sending —
                # setpoints, mode strings, and tags written by the
                # transformation publisher are all `simulate: false`. Skipping
                # the publish for them meant they were declared in the DBIRTH
                # and then never updated again.
                if not config.get("simulate", False):
                    sim_type = None

                if sim_type == "random":
                    new_value = self.generate_random_value(config, tag_type)
                elif sim_type == "increment":
                    new_value = self.generate_increment_value(current_value, config, tag_type)
                elif sim_type == "sine":
                    new_value = self.generate_sine_value(config, tag_type)
                elif sim_type == "duty_cycle":
                    new_value = self.generate_duty_cycle_value(tag_name, tag_data, timestamp)
                elif sim_type == "hysteresis":
                    new_value = self.generate_hysteresis_value(tag_name, tag_data, current_value, timestamp)
                elif sim_type == "event":
                    new_value = self.generate_event_value(tag_name, tag_data, timestamp)
                elif sim_type == "walk":
                    new_value = self.generate_walk_value(tag_name, tag_data, current_value, timestamp)
                elif sim_type == "thermostat":
                    new_value = self.generate_thermostat_value(tag_name, tag_data, current_value, timestamp)
                elif sim_type == "follows":
                    new_value = self.generate_follows_value(tag_name, tag_data, current_value, timestamp)
                elif sim_type == "accumulate":
                    new_value = self.generate_accumulate_value(tag_name, tag_data, current_value, timestamp)
                elif sim_type == "clock":
                    new_value = self.generate_clock_value(tag_name, tag_data)
                else:
                    new_value = None

                if new_value is not None and new_value != current_value:
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

    # ------------------------------------------------------------------
    # Behavioral simulation
    #
    # These four carry state between scans (phase timers, walk position) and
    # two of them read other tags, which is why they take `tag_data` and the
    # scan timestamp rather than just `config`. State is kept on the tag entry
    # so deleting a tag disposes of its simulation state with it.
    # ------------------------------------------------------------------

    def sim_state(self, tag_data):
        """Return the mutable per-tag simulation state, creating it on first use."""
        return tag_data.setdefault("sim", {})

    @staticmethod
    def jittered(seconds, jitter_fraction):
        """Scatter a duration by ±jitter_fraction so cycles don't fall into lockstep."""
        if jitter_fraction <= 0:
            return seconds
        low = max(0.0, 1.0 - jitter_fraction)
        return max(1.0, seconds * random.uniform(low, 1.0 + jitter_fraction))

    def referenced_value(self, tag_name, default=None):
        """
        Read another tag's current value, for simulations that depend on one.

        An unknown reference is warned about once and then treated as the
        default — a typo in one tag's `driver_tag` should not flood the log at
        the scan rate, nor stop the rest of the site from simulating.
        """
        if not tag_name:
            return default

        entry = self.tags.get(tag_name)
        if entry is None:
            if not hasattr(self, "_warned_refs"):
                self._warned_refs = set()
            if tag_name not in self._warned_refs:
                self._warned_refs.add(tag_name)
                self.logger.warning(f"Simulation references unknown tag: {tag_name}")
            return default

        try:
            return entry["variable"].get_value()
        except Exception as e:
            self.logger.error(f"Error reading referenced tag {tag_name}: {e}")
            return default

    def referenced_number(self, tag_name, default):
        """Read another tag's value as a float, falling back to `default`."""
        value = self.referenced_value(tag_name, None)
        if value is None:
            return float(default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def generate_duty_cycle_value(self, tag_name, tag_data, now):
        """
        Generate a boolean that runs on for `on_seconds` then off for
        `off_seconds`, each scattered by `jitter_pct`.

        This is what a compressor, a supply fan or a lighting contactor
        actually does.

        Config: on_seconds, off_seconds, jitter_pct, initial_value

        Returns:
            bool: current state of the cycle
        """
        config = tag_data["config"]
        state = self.sim_state(tag_data)

        on_seconds = float(config.get("on_seconds", 600))
        off_seconds = float(config.get("off_seconds", 600))
        jitter = max(0.0, float(config.get("jitter_pct", 15))) / 100.0

        if "next_switch" not in state:
            state["phase"] = bool(config.get("initial_value", False))
            # Start somewhere inside the first phase rather than at its edge, so
            # several assets on the same config don't switch in unison forever.
            duration = self.jittered(on_seconds if state["phase"] else off_seconds, jitter)
            state["next_switch"] = now + random.uniform(0.0, duration)

        if now >= state["next_switch"]:
            state["phase"] = not state["phase"]
            state["next_switch"] = now + self.jittered(
                on_seconds if state["phase"] else off_seconds, jitter
            )

        return state["phase"]

    def generate_hysteresis_value(self, tag_name, tag_data, current_value, now):
        """
        Generate a boolean from two-position control of another tag.

        Cooling (the default): switch on once `process_tag` rises above
        setpoint + differential, off once it falls below setpoint - differential.
        Set `invert: true` for heating.

        Use this rather than `duty_cycle` wherever the plant has a controller.
        A duty cycle is open-loop — it runs to a clock regardless of the
        process — so its temperature settles wherever the cooling and warming
        rates happen to balance, which is not the setpoint and drifts as soon as
        anything else (a defrost, a door) perturbs it. Closing the loop is what
        makes a cold room sit at the number on its setpoint tag.

        `min_on_seconds` / `min_off_seconds` are short-cycle protection, which
        real compressors have and which also stops the output chattering when
        the process sits on a threshold.

        Config: process_tag, setpoint, setpoint_tag, differential, invert,
                min_on_seconds, min_off_seconds

        Returns:
            bool: commanded state of the device
        """
        config = tag_data["config"]
        state = self.sim_state(tag_data)

        setpoint = self.referenced_number(config.get("setpoint_tag"), config.get("setpoint", 0.0))
        differential = float(config.get("differential", 1.0))
        invert = bool(config.get("invert", False))
        min_on = float(config.get("min_on_seconds", 0))
        min_off = float(config.get("min_off_seconds", 0))

        running = bool(current_value)
        process = self.referenced_value(config.get("process_tag"), None)
        if process is None:
            return running
        try:
            process = float(process)
        except (TypeError, ValueError):
            return running

        held_since = state.get("since", now)
        state.setdefault("since", now)

        above = process > setpoint + differential
        below = process < setpoint - differential
        # Heating inverts which side of the band calls for the device.
        call_for_on, call_for_off = (below, above) if invert else (above, below)

        if running and call_for_off:
            if now - held_since >= min_on:
                state["since"] = now
                return False
        elif not running and call_for_on:
            if now - held_since >= min_off:
                state["since"] = now
                return True

        return running

    def generate_event_value(self, tag_name, tag_data, now):
        """
        Generate a boolean that is normally false and pulses true occasionally
        — a door opening, a defrost cycle, a fault, a generator exercise run.

        Intervals are exponentially distributed around `mtbe_seconds`, which is
        what makes the gaps look unplanned instead of metronomic.

        `overrun_probability` occasionally stretches an event past its normal
        duration. That is deliberate: it is what eventually trips the
        "open longer than 5 min" and "cycle longer than 45 min" alarms, so a
        demo has something to show instead of staying green forever.

        Config: mtbe_seconds, duration_min, duration_max, overrun_probability,
                overrun_multiplier

        Returns:
            bool: True while the event is active
        """
        config = tag_data["config"]
        state = self.sim_state(tag_data)

        mtbe = float(config.get("mtbe_seconds", 2700))
        duration_min = float(config.get("duration_min", 30))
        duration_max = max(duration_min, float(config.get("duration_max", 90)))
        overrun_probability = float(config.get("overrun_probability", 0.0))
        overrun_multiplier = float(config.get("overrun_multiplier", 4.0))

        def next_gap():
            if mtbe <= 0:
                return float("inf")
            return random.expovariate(1.0 / mtbe)

        if "next_start" not in state:
            state["active"] = False
            state["next_start"] = now + next_gap()

        if state["active"]:
            if now >= state.get("until", now):
                state["active"] = False
                state["next_start"] = now + next_gap()
        elif now >= state["next_start"]:
            duration = random.uniform(duration_min, duration_max)
            if overrun_probability > 0 and random.random() < overrun_probability:
                duration *= overrun_multiplier
            state["active"] = True
            state["until"] = now + duration

        return state["active"]

    def generate_walk_value(self, tag_name, tag_data, current_value, now):
        """
        Generate a bounded random walk, optionally with a steady drift.

        Drift is the interesting part: a filter differential pressure that
        creeps upward until it reaches its High setpoint and is then "changed"
        (`reset_on_max`) tells a maintenance story that a random value in a
        band cannot.

        Config: step, drift_per_hour, min, max, reset_on_max, initial_value

        Returns:
            Value of the tag's declared type, clamped to [min, max]
        """
        config = tag_data["config"]
        state = self.sim_state(tag_data)

        step = float(config.get("step", 1.0))
        drift_per_hour = float(config.get("drift_per_hour", 0.0))
        min_val = float(config.get("min", 0.0))
        max_val = float(config.get("max", 100.0))

        elapsed = max(0.0, now - state.get("last_update", now))
        state["last_update"] = now

        try:
            value = float(current_value)
        except (TypeError, ValueError):
            value = float(config.get("initial_value", min_val))

        value += random.uniform(-step, step) + drift_per_hour * (elapsed / 3600.0)

        if value >= max_val:
            if config.get("reset_on_max", False):
                value = float(config.get("initial_value", min_val))
            else:
                value = max_val
        elif value < min_val:
            value = min_val

        if tag_data["type"] == "int":
            return int(round(value))
        return round(value, 2)

    def generate_thermostat_value(self, tag_name, tag_data, current_value, now):
        """
        Generate a temperature that responds to a driver boolean.

        While `driver_tag` is true the value is pulled toward `setpoint - band`
        at `pull_rate` degrees per minute; while it is false the value drifts
        back toward `ambient` at `rise_rate`. Pair it with a `duty_cycle`
        compressor and the room sawtooths around its setpoint the way a real
        one does — and the temperature and the compressor status agree with
        each other, which is the whole point.

        `setpoint_tag` lets the setpoint be another tag, so changing the
        setpoint in the UI moves the process.

        Config: setpoint, setpoint_tag, driver_tag, band, pull_rate, rise_rate,
                ambient, noise

        Returns:
            float: the new temperature
        """
        config = tag_data["config"]
        state = self.sim_state(tag_data)

        setpoint = self.referenced_number(config.get("setpoint_tag"), config.get("setpoint", 0.0))
        band = float(config.get("band", 1.0))
        ambient = float(config.get("ambient", setpoint + 20.0))
        pull_rate = float(config.get("pull_rate", 1.0))
        rise_rate = float(config.get("rise_rate", 0.3))
        noise = float(config.get("noise", 0.05))
        driver_on = bool(self.referenced_value(config.get("driver_tag"), False))

        elapsed = max(0.0, now - state.get("last_update", now))
        state["last_update"] = now
        minutes = elapsed / 60.0

        try:
            value = float(current_value)
        except (TypeError, ValueError):
            value = float(config.get("initial_value", setpoint))

        target = (setpoint - band) if driver_on else ambient
        delta = (pull_rate if driver_on else rise_rate) * minutes

        if value < target:
            value = min(target, value + delta)
        else:
            value = max(target, value - delta)

        if noise:
            value += random.uniform(-noise, noise)

        return round(value, 2)

    def generate_follows_value(self, tag_name, tag_data, current_value, now):
        """
        Mirror another tag's value after `lag_seconds`.

        Models a feedback/status point trailing its command. With
        `mismatch_probability` set, the feedback occasionally refuses to follow
        for `mismatch_seconds` — a stuck contactor — which is precisely the
        condition a command/feedback mismatch alarm exists to catch.

        Config: source_tag, lag_seconds, mismatch_probability, mismatch_seconds

        Returns:
            The source's value once the lag has elapsed, otherwise the value
            the tag already holds.
        """
        config = tag_data["config"]
        state = self.sim_state(tag_data)

        lag_seconds = float(config.get("lag_seconds", 0.0))
        mismatch_probability = float(config.get("mismatch_probability", 0.0))
        mismatch_seconds = float(config.get("mismatch_seconds", 30.0))

        source_value = self.referenced_value(config.get("source_tag"), current_value)
        source_changed = "last_source" in state and source_value != state["last_source"]

        # `last_source` is deliberately NOT advanced while suppressed. Leaving it
        # stale is what makes the change still look pending when the window
        # expires, so the tag resynchronises instead of staying wrong forever.
        if state.get("mismatch_until", 0.0) > now:
            return current_value

        # One roll per distinct change: `mismatch_for` records which source value
        # was already refused, otherwise a high probability re-rolls the instant
        # the window closes and the tag never catches up at all.
        if (source_changed and mismatch_probability > 0
                and state.get("mismatch_for", _NO_VALUE) != source_value
                and random.random() < mismatch_probability):
            state["mismatch_until"] = now + mismatch_seconds
            state["mismatch_for"] = source_value
            return current_value

        if "last_source" not in state or source_changed:
            state["last_source"] = source_value
            state["pending"] = source_value
            state["apply_at"] = now + lag_seconds

        if "pending" in state and now >= state.get("apply_at", now):
            state.pop("apply_at", None)
            return state.pop("pending")

        return current_value

    def generate_accumulate_value(self, tag_name, tag_data, current_value, now):
        """
        Integrate another tag over time — the running total behind an energy
        counter.

        kWh is the integral of kW, not a counter that ticks. `increment` climbs
        at a fixed rate regardless of load, so a site drawing 20 kW and one
        drawing 140 kW would bill identically, and the totaliser would disagree
        with the power reading right next to it on the same screen.

        Config: source_tag, scale (multiplier on source-units-per-hour), max,
                reset_on_max

        Returns:
            float: the accumulated total
        """
        config = tag_data["config"]
        state = self.sim_state(tag_data)

        scale = float(config.get("scale", 1.0))
        elapsed = max(0.0, now - state.get("last_update", now))
        state["last_update"] = now

        # The running total is kept at full precision in state, NOT read back
        # from the published value. Each scan adds a small amount — at a 2s
        # scan, 60 kW is 0.0333 kWh — and re-reading a value rounded for
        # display discards the remainder every single time. That bias is not
        # small: it lost exactly 10% over one simulated hour.
        total = state.get("total")
        if total is None:
            try:
                total = float(current_value)
            except (TypeError, ValueError):
                total = float(config.get("initial_value", 0.0))

        rate = self.referenced_number(config.get("source_tag"), 0.0)
        total += rate * scale * (elapsed / 3600.0)

        max_val = config.get("max")
        if max_val is not None and total >= float(max_val):
            total = float(config.get("initial_value", 0.0)) if config.get("reset_on_max", False) else float(max_val)

        state["total"] = total

        if tag_data["type"] == "int":
            return int(total)
        return round(total, 2)

    def generate_clock_value(self, tag_name, tag_data):
        """
        Expose a component of the current local time.

        HMIs commonly show the plant clock from tags rather than the client's
        own clock, so the displayed time is the controller's. Simulating those
        with `random` puts a number that is not a time on the screen, which is
        the first thing anyone notices.

        Config: part — hour | minute | second (default: second)

        Returns:
            int: the requested component of local time
        """
        part = str(tag_data["config"].get("part", "second")).lower()
        local = time.localtime()
        if part == "hour":
            return local.tm_hour
        if part == "minute":
            return local.tm_min
        return local.tm_sec

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
                self._setup_write_callbacks()
                
                self.publisher_manager.start_all()

                # Computed tags restored from the runtime store were registered
                # before any publisher existed, so hand them over now that one
                # does — otherwise they stay at their initial value until
                # someone happens to redefine a tag.
                self.sync_computed_tags()
            
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
    
    def _setup_tag_metadata(self):
        """Setup tag metadata for publishers that need it."""
        if not self.publisher_manager:
            return
        
        # Every publisher gets metadata. DataPublisher declares tag_metadata, so
        # there is nothing to probe for. This used to test for 'tag_cache' or
        # 'tags_data' and silently skipped any publisher naming its store
        # something else — GraphQL and Sparkplug B were both missed that way.
        for publisher in self.publisher_manager.publishers:
            publisher.tag_metadata = self.tag_metadata
            self.logger.debug(f"Passed tag metadata to {publisher.__class__.__name__}")
    
    def _setup_write_callbacks(self):
        """
        Give every publisher that accepts a write callback a way back into the
        OPC UA address space.

        This used to match only DataTransformationPublisher by class name, which
        left RESTAPIPublisher.write_callback as None — so every write, create and
        bulk-create from the web UI returned 501 "Write not supported". Any
        publisher exposing set_write_callback needs the wiring, not just one.
        """
        if not self.publisher_manager:
            return

        for publisher in self.publisher_manager.publishers:
            if not hasattr(publisher, 'set_write_callback'):
                continue
            publisher.set_write_callback(self.write_tag)
            self.logger.info(
                f"Write callback configured for {publisher.__class__.__name__}"
            )

            if hasattr(publisher, 'set_delete_callback'):
                publisher.set_delete_callback(self.delete_tag)

            # Full tag definitions, not just values. Without this the REST API
            # can only set a value, so a tag created in the web UI is inert —
            # no type, no simulation, no persistence.
            if hasattr(publisher, 'set_define_callback'):
                publisher.set_define_callback(self.define_tag)

            if hasattr(publisher, 'set_persist_callback'):
                publisher.set_persist_callback(self.save_runtime_tags)


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