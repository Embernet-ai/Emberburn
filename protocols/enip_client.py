"""EtherNet/IP client: EmberBurn as the scanner.

Writes EmberBurn tag values into the tags of a Logix style controller and reads
a list of tags back on a poll, so a real or simulated EtherNet/IP device, and an
analyzer or intrusion detection sensor between them, sees SCADA style client
traffic. Config key: publishers.ethernet_ip_client.

Uses pycomm3 (MIT, https://github.com/ottowayi/pycomm3), which does the CIP
client side: the session, Forward Open, tag list upload and the typed reads and
writes. Nothing from it is copied into this repository.
"""
import logging
import threading
import time
from typing import Any, Dict, Optional

from protocols.base import SimProtocolPublisher


class EtherNetIPClientPublisher(SimProtocolPublisher):
    """Pushes tags to, and polls tags from, a remote EtherNet/IP controller."""

    config_key = "ethernet_ip_client"

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.polled: Dict[str, Any] = {}      # remote tag -> last value read
        self.writes = 0
        self.reads = 0

    def start(self):
        if not self.enabled:
            self.logger.info("EtherNet/IP client publisher is disabled")
            return
        if not self.config.get("host"):
            self.logger.error("EtherNet/IP client needs publishers.ethernet_ip_client.host")
            self.enabled = False
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="enip-client")
        self._thread.start()
        self.logger.info(f"EtherNet/IP client started toward {self.config['host']}")

    def stop(self):
        self.running = False
        self._stop.set()
        self.logger.info("EtherNet/IP client publisher stopped")

    def _run(self):
        from pycomm3 import LogixDriver  # imported here so the server role never needs it

        host = str(self.config["host"])
        slot = self.config.get("slot")
        path = f"{host}/{int(slot)}" if slot is not None else host
        tag_map: Dict[str, str] = self.config.get("tag_map", {}) or {}
        poll_tags = list(self.config.get("poll_tags", []) or [])
        interval = float(self.config.get("interval", 2.0))
        delay = 2.0
        while not self._stop.is_set():
            try:
                with LogixDriver(path, init_tags=True, init_program_tags=False) as plc:
                    self.unavailable_reason = None
                    delay = 2.0
                    self.logger.info(f"EtherNet/IP client connected to {path}")
                    while not self._stop.is_set():
                        self._cycle(plc, tag_map, poll_tags)
                        self._stop.wait(interval)
            except Exception as exc:
                self.unavailable_reason = f"cannot reach {path}: {exc}"
                self.logger.warning(f"EtherNet/IP client {self.unavailable_reason}")
                self._stop.wait(delay)
                delay = min(delay * 2, 60.0)

    def _cycle(self, plc, tag_map, poll_tags):
        with self.lock:
            out = [(remote, self.values[local]) for local, remote in tag_map.items() if local in self.values]
        if out:
            for result in plc.write(*out) if len(out) > 1 else [plc.write(out[0])]:
                if result.error:
                    self.logger.warning(f"EtherNet/IP write {result.tag} failed: {result.error}")
                else:
                    self.writes += 1
        if poll_tags:
            results = plc.read(*poll_tags)
            for result in results if isinstance(results, list) else [results]:
                if result.error:
                    self.logger.warning(f"EtherNet/IP read {result.tag} failed: {result.error}")
                else:
                    self.polled[result.tag] = result.value
                    self.reads += 1
