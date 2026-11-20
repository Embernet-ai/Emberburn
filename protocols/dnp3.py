"""DNP3 simulator: EmberBurn as a DNP3 outstation, and as a DNP3 master.

Server role (publishers.dnp3): the tags become points of one outstation on TCP
20000, readable by an integrity or class poll, with change events in classes 1, 2
and 3, and controllable through select-before-operate and direct operate. A float
or int tag is an Analog Input (group 30), a bool a Binary Input (group 1), and a
tag mapped as a counter is a Counter (group 20). A tag mapped as an output is a
Binary Output (group 10, controlled by CROB group 12) or an Analog Output
(group 40, controlled by group 41), and a control from the master writes the tag.

Client role (publishers.dnp3_master): EmberBurn polls a remote outstation (an
integrity poll at start, then an integrity poll and class 1, 2, 3 event polls every
interval), which gives an analyzer or intrusion detection sensor the master side
of a DNP3 conversation.

The protocol stack is dnp3py (https://github.com/craigpnnl/dnp3py, MIT, a pure
Python IEEE 1815-2012 implementation, Level 2 object model). It owns the data link,
transport and application layers, the CRCs, fragmentation, IIN bits and the
event buffers. This module maps tags to points and controls back to tags. dnp3py
is asyncio, so each role runs its own event loop in a thread.

Analog values: dnp3py serves analog inputs and outputs as 32-bit integers (g30v1,
g40v2), as most RTUs do, so a float tag is sent as round(value x scale) with scale
100 by default (two decimals; the master divides it back out) and an int tag with
scale 1. Set `scale` per tag in tag_mapping, or `analog_scale` for all float tags.
The deadband (default 0.5, in engineering units) decides when a change becomes a
class event.

Not simulated: secure authentication (SAv5), file transfer, double-bit inputs,
frozen counters beyond what dnp3py does by default, and serial or UDP transport.
"""
import asyncio
import logging
import threading
from typing import Any, Dict, Optional, Tuple

from protocols.base import SimProtocolPublisher

OUTPUT_KINDS = ("binary_output", "analog_output")
KINDS = ("binary_input", "analog_input", "counter") + OUTPUT_KINDS


class DNP3Publisher(SimProtocolPublisher):
    """DNP3 outstation. Config key: publishers.dnp3."""

    config_key = "dnp3"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._runner = None
        self.db = None
        self.points: Dict[str, Tuple[str, int]] = {}     # tag -> (kind, index)
        self.scales: Dict[str, float] = {}               # tag -> analog scale
        self.by_point: Dict[Tuple[str, int], str] = {}   # (kind, index) -> tag
        self._next = {k: 0 for k in KINDS}
        self.overrides: Dict[str, Any] = config.get("tag_mapping", {}) or {}

    # lifecycle -------------------------------------------------------------
    def start(self):
        if not self.enabled:
            self.logger.info("DNP3 publisher is disabled")
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="dnp3")
        self._thread.start()
        if not self._ready.wait(20) or self._runner is None:
            self.logger.error("DNP3 outstation did not start")
            self.running = False
            return
        self.running = True

    def stop(self):
        self.running = False
        loop, runner = self._loop, self._runner
        if loop is not None and runner is not None and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(runner.stop(), loop)
            try:
                fut.result(5)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=8)
        self._runner = None
        self.logger.info("DNP3 publisher stopped")

    def _run(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except Exception as exc:
            self.logger.error(f"DNP3 outstation stopped: {exc}")
        finally:
            self._ready.set()
            loop.close()

    async def _serve(self):
        from dnp3.database import Database
        from dnp3.outstation import Outstation, OutstationConfig, OutstationTcpRunner

        self.db = Database()
        handler = _Handler(self)
        outstation = Outstation(
            config=OutstationConfig(
                address=int(self.config.get("address", 10)),
                master_address=int(self.config.get("master_address", 0)),
                time_sync_required=bool(self.config.get("time_sync_required", False)),
            ),
            database=self.db,
            handler=handler,
        )
        host = str(self.config.get("host", "0.0.0.0"))
        port = int(self.config.get("port", 20000))
        self._runner = OutstationTcpRunner(outstation=outstation, host=host, port=port)
        task = asyncio.ensure_future(self._runner.run())
        for _ in range(100):
            if self._runner.is_running:
                break
            if task.done():
                task.result()
            await asyncio.sleep(0.05)
        self.logger.info(f"DNP3 outstation {outstation.config.address} on TCP {host}:{port}")
        self._ready.set()
        await task

    # tags to points --------------------------------------------------------
    def on_value(self, tag_name, value):
        if self._loop is None or not self.running:
            return
        self._loop.call_soon_threadsafe(self._apply, tag_name, value)

    def _kind(self, tag: str, value: Any) -> str:
        want = str((self.overrides.get(tag, {}) or {}).get("type", "")).lower()
        if want in KINDS:
            return want
        return "binary_input" if isinstance(value, bool) else "analog_input"

    def _add_point(self, tag: str, value: Any) -> Tuple[str, int]:
        from dnp3.database import (AnalogInputConfig, AnalogOutputConfig, BinaryInputConfig,
                                   BinaryOutputConfig, CounterConfig, EventClass)
        ov = self.overrides.get(tag, {}) or {}
        kind = self._kind(tag, value)
        index = int(ov.get("index", self._next[kind]))
        self._next[kind] = max(self._next[kind], index) + 1
        cls = {1: EventClass.CLASS_1, 2: EventClass.CLASS_2, 3: EventClass.CLASS_3}.get(int(ov.get("class", 1)), EventClass.CLASS_1)
        scale = float(ov.get("scale", 1 if isinstance(value, int) and not isinstance(value, bool) else self.config.get("analog_scale", 100)))
        if kind == "binary_input":
            self.db.add_binary_input(index, BinaryInputConfig(event_class=cls), value=bool(value))
        elif kind == "binary_output":
            self.db.add_binary_output(index, BinaryOutputConfig(event_class=cls), value=bool(value))
        elif kind == "counter":
            self.db.add_counter(index, CounterConfig(event_class=cls, deadband=int(ov.get("deadband", 0))), value=int(value))
        elif kind == "analog_output":
            self.db.add_analog_output(index, AnalogOutputConfig(), value=round(float(value) * scale))
        else:
            self.db.add_analog_input(index, AnalogInputConfig(event_class=cls, deadband=float(ov.get("deadband", self.config.get("analog_deadband", 0.5))) * scale), value=round(float(value) * scale))
        self.scales[tag] = scale
        self.points[tag] = (kind, index)
        self.by_point[(kind, index)] = tag
        return kind, index

    def _apply(self, tag: str, value: Any):
        try:
            if tag not in self.points:
                self._add_point(tag, value)
                return
            kind, index = self.points[tag]
            if kind == "binary_input":
                self.db.update_binary_input(index, bool(value))
            elif kind == "binary_output":
                self.db.update_binary_output(index, bool(value))
            elif kind == "counter":
                self.db.update_counter(index, int(value))
            elif kind == "analog_output":
                self.db.update_analog_output(index, round(float(value) * self.scales[tag]))
            else:
                self.db.update_analog_input(index, round(float(value) * self.scales[tag]))
        except Exception as exc:
            self.logger.error(f"DNP3 could not update {tag}: {exc}")

    # controls from the master ---------------------------------------------
    def control(self, kind: str, index: int, value: Any) -> bool:
        tag = self.by_point.get((kind, index))
        if tag is None:
            return False
        if kind == "analog_output":
            value = float(value) / self.scales[tag]   # the master sends scaled counts
        ok = self.client_write(tag, value)
        if ok:
            if kind == "binary_output":
                self.db.update_binary_output(index, bool(value))
            else:
                self.db.update_analog_output(index, round(float(value) * self.scales[tag]))
        return ok


def _handler_base():
    from dnp3.outstation import DefaultCommandHandler
    return DefaultCommandHandler


def _Handler(pub: DNP3Publisher):
    from dnp3.outstation import CommandResult

    base = _handler_base()

    class Handler(base):
        """Controls land in the tag store; anything not mapped is refused."""

        @staticmethod
        def _value(code) -> Optional[bool]:
            # control code octet: bits 7-6 trip/close, bits 3-0 operation type
            op, tcc = int(code.op_type), int(code.tcc)
            if op == 3:
                return True      # latch on
            if op == 4:
                return False     # latch off
            if op in (0, 1):     # pulse on, or no op with trip/close: close true, trip false
                if tcc == 1:
                    return True
                if tcc == 2:
                    return False
            return None

        def select_binary_output(self, index, code, count, on_time, off_time):
            ok = ("binary_output", index) in pub.by_point and self._value(code) is not None
            return CommandResult.success() if ok else CommandResult.not_supported()

        def operate_binary_output(self, index, code, count, on_time, off_time, select_sequence):
            return self.direct_operate_binary_output(index, code, count, on_time, off_time)

        def direct_operate_binary_output(self, index, code, count, on_time, off_time):
            v = self._value(code)
            if v is None or not pub.control("binary_output", index, v):
                return CommandResult.not_supported()
            return CommandResult.success()

        def select_analog_output(self, index, value):
            return CommandResult.success() if ("analog_output", index) in pub.by_point else CommandResult.not_supported()

        def operate_analog_output(self, index, value, select_sequence):
            return self.direct_operate_analog_output(index, value)

        def direct_operate_analog_output(self, index, value):
            if not pub.control("analog_output", index, value):
                return CommandResult.not_supported()
            return CommandResult.success()

    return Handler()
