"""Shared plumbing for the simulated OT protocol publishers."""
import logging
import re
import threading
from typing import Any, Callable, Dict, Optional

from publishers import DataPublisher


class SimProtocolPublisher(DataPublisher):
    """A DataPublisher that serves the gateway's tags over an OT protocol.

    The main loop calls publish() once per tag per scan. This base keeps the
    latest value of every tag, tells the subclass when a tag appears or changes,
    and carries writes from a protocol client back to the tag store through the
    same write callback the REST API uses.
    """

    # Config key under "publishers", set by each subclass.
    config_key = ""

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.values: Dict[str, Any] = {}
        self.lock = threading.RLock()
        self._write_callback: Optional[Callable[[str, Any], bool]] = None

    # DataPublisher callbacks the server wires up for any publisher that has them.
    def set_write_callback(self, callback: Callable[[str, Any], bool]):
        self._write_callback = callback

    def publish(self, tag_name: str, value: Any, timestamp: Optional[float] = None):
        if not self.enabled or not self.running:
            return
        with self.lock:
            is_new = tag_name not in self.values
            self.values[tag_name] = value
        if is_new:
            self.on_new_tag(tag_name, value)
        self.on_value(tag_name, value)

    def on_new_tag(self, tag_name: str, value: Any):
        """A tag was seen for the first time."""

    def on_value(self, tag_name: str, value: Any):
        """A scan delivered a value for a tag."""

    def client_write(self, tag_name: str, value: Any) -> bool:
        """A protocol client wrote a value. Returns True if the tag store took it."""
        with self.lock:
            if tag_name not in self.values:
                return False
            self.values[tag_name] = value
        if self._write_callback is None:
            return True
        try:
            return bool(self._write_callback(tag_name, value))
        except Exception as exc:  # a failed write must not kill the server thread
            self.logger.error(f"write of {tag_name} from {self.config_key} failed: {exc}")
            return False


_UNSAFE = re.compile(r"[^A-Za-z0-9_]")


def symbol_name(tag_name: str) -> str:
    """A tag name as an IEC 61131 style identifier: letters, digits and underscores,
    starting with a letter or underscore. 'Plant/Line1/Temp C' becomes
    'Plant_Line1_Temp_C'."""
    name = _UNSAFE.sub("_", tag_name)
    if not name or name[0].isdigit():
        name = "T_" + name
    return name[:40]
