"""BACnet/IP simulator: EmberBurn as a BACnet device.

Every tag is an object in one BACnet device on UDP 47808: a float or int tag is
an Analog Value, a bool a Binary Value, a string a Character String Value. Who-Is,
I-Am, ReadProperty, ReadPropertyMultiple, WriteProperty and the object list work
as they do on a real device. Config key: publishers.bacnet.

The protocol stack is bacpypes3 (https://github.com/JoelBender/bacpypes3, MIT per
its package metadata), which owns the BVLL, NPDU and APDU framing and the object
model. This module creates the objects, keeps their present values current, and
carries a client WriteProperty back into the tag store. bacpypes3 is asyncio, so
the stack runs on its own event loop in a thread.

Not simulated: COV subscriptions, alarms and events, schedules, trend logs,
segmentation beyond what bacpypes3 does by default, BACnet/SC, and routing between
networks.
"""
import asyncio
import logging
import socket
import threading
import time
from typing import Any, Dict, Optional

from protocols.base import SimProtocolPublisher


def primary_ip() -> str:
    """The address this pod or host reaches the network with (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("203.0.113.1", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class BACnetPublisher(SimProtocolPublisher):
    """BACnet/IP device. Config key: publishers.bacnet."""

    config_key = "bacnet"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop_evt = threading.Event()
        self.app = None
        self.objects: Dict[str, Any] = {}      # tag -> bacpypes3 object
        self.kinds: Dict[str, str] = {}        # tag -> AV BV CSV
        self.last: Dict[str, Any] = {}         # tag -> last value we wrote into the object
        self._next_instance = {"AV": 1, "BV": 1, "CSV": 1}
        self.overrides: Dict[str, Any] = config.get("tag_mapping", {}) or {}

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self):
        if not self.enabled:
            self.logger.info("BACnet publisher is disabled")
            return
        self._ready.clear()
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="bacnet")
        self._thread.start()
        if not self._ready.wait(20) or self.app is None:
            self.logger.error("BACnet did not start")
            self.running = False
            return
        self.running = True

    def stop(self):
        self.running = False
        self._stop_evt.set()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.logger.info("BACnet publisher stopped")

    def _run(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except Exception as exc:
            self.logger.error(f"BACnet stopped: {exc}")
        finally:
            try:
                if self.app is not None:
                    self.app.close()
            except Exception:
                pass
            loop.close()
            self._ready.set()

    async def _serve(self):
        from bacpypes3.argparse import SimpleArgumentParser
        from bacpypes3.app import Application

        host = str(self.config.get("host", "0.0.0.0"))
        if host in ("0.0.0.0", ""):
            host = primary_ip()
        port = int(self.config.get("port", 47808))
        prefix = int(self.config.get("prefix", 24))
        argv = [
            "--name", str(self.config.get("device_name", "EmberBurn")),
            "--instance", str(int(self.config.get("device_instance", 1234))),
            "--address", f"{host}/{prefix}:{port}",
        ]
        if self.config.get("vendor_id") is not None:
            argv += ["--vendoridentifier", str(int(self.config["vendor_id"]))]
        args = SimpleArgumentParser().parse_args(argv)
        self.app = Application.from_args(args)
        self.logger.info(f"BACnet/IP device {args.instance} on {host}/{prefix}:{port}")
        self._ready.set()
        while not self._stop_evt.is_set():
            self._poll_writes()
            await asyncio.sleep(0.5)

    # ── tags to objects ───────────────────────────────────────────────────
    def on_value(self, tag_name, value):
        if self._loop is None or not self.running:
            return
        self._loop.call_soon_threadsafe(self._apply, tag_name, value)

    def _kind(self, tag_name: str, value: Any) -> str:
        ov = self.overrides.get(tag_name, {}) or {}
        want = str(ov.get("type", "")).upper()
        if want in ("AV", "BV", "CSV"):
            return want
        if isinstance(value, bool):
            return "BV"
        if isinstance(value, (int, float)):
            return "AV"
        return "CSV"

    def _apply(self, tag_name: str, value: Any):
        try:
            obj = self.objects.get(tag_name)
            if obj is None:
                obj = self._create(tag_name, value)
                if obj is None:
                    return
            kind = self.kinds[tag_name]
            new = self._to_bacnet(kind, value)
            if obj.presentValue != new:
                obj.presentValue = new
            self.last[tag_name] = self._from_object(kind, obj)
        except Exception as exc:
            self.logger.error(f"BACnet could not update {tag_name}: {exc}")

    @staticmethod
    def _to_bacnet(kind: str, value: Any):
        if kind == "AV":
            return float(value)
        if kind == "BV":
            return "active" if value else "inactive"
        return str(value)

    @staticmethod
    def _from_object(kind: str, obj):
        v = obj.presentValue
        if kind == "AV":
            return float(v)
        if kind == "BV":
            return str(v) == "active"
        return str(v)

    def _create(self, tag_name: str, value: Any):
        from bacpypes3.local.analog import AnalogValueObject
        from bacpypes3.local.binary import BinaryValueObject
        from bacpypes3.object import CharacterStringValueObject

        ov = self.overrides.get(tag_name, {}) or {}
        kind = self._kind(tag_name, value)
        inst = int(ov.get("instance", self._next_instance[kind]))
        self._next_instance[kind] = max(self._next_instance[kind], inst) + 1
        name = str(ov.get("name", tag_name))
        desc = str(ov.get("description", "") or (self.tag_metadata.get(tag_name, {}) or {}).get("description", "") or tag_name)
        if kind == "AV":
            kw = dict(objectIdentifier=("analogValue", inst), objectName=name, presentValue=float(value),
                      statusFlags=[0, 0, 0, 0], description=desc)
            if ov.get("units"):
                kw["units"] = ov["units"]
            obj = AnalogValueObject(**kw)
        elif kind == "BV":
            obj = BinaryValueObject(objectIdentifier=("binaryValue", inst), objectName=name,
                                    presentValue="active" if value else "inactive",
                                    statusFlags=[0, 0, 0, 0], description=desc)
        else:
            obj = CharacterStringValueObject(objectIdentifier=("characterstringValue", inst), objectName=name,
                                             presentValue=str(value), statusFlags=[0, 0, 0, 0], description=desc)
        self.app.add_object(obj)
        self.objects[tag_name] = obj
        self.kinds[tag_name] = kind
        return obj

    def _poll_writes(self):
        """A client WriteProperty changes an object directly; carry the change back."""
        for tag, obj in list(self.objects.items()):
            try:
                cur = self._from_object(self.kinds[tag], obj)
            except Exception:
                continue
            old = self.last.get(tag)
            if old is None or cur == old:
                continue
            if isinstance(cur, float) and isinstance(old, float) and abs(cur - old) < 1e-6 * max(1.0, abs(old)):
                continue
            self.last[tag] = cur
            self.client_write(tag, cur)
