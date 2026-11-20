"""S7comm simulator: EmberBurn as a Siemens S7 CPU.

Tags live in data blocks, served over ISO on TCP (COTP, port 102) as S7comm, so
a Step 7 style client, a SCADA driver, or a protocol analyzer reads them as DB
variables. Config key: publishers.s7comm.

The protocol server is python-snap7 (https://github.com/gijzelaerr/python-snap7,
MIT; 3.x is a pure Python implementation of the S7 server), which owns the COTP
and S7comm framing, the SZL and CPU information answers and the read and write
functions. This module maps tags onto data block bytes and back:

  REAL and DINT are big endian 4 byte values, INT is 2 bytes, BOOL is one bit of
  a byte, LREAL is 8 bytes, STRING is the S7 string (max length byte, length
  byte, characters).

A client write to a data block lands in the tag store through the write callback.
The CPU identity answered to a client is python-snap7's built in S7-300 identity.
"""
import logging
import struct
from typing import Any, Dict, Optional, Tuple

from protocols.base import SimProtocolPublisher

SIZES = {"BOOL": 1, "INT": 2, "DINT": 4, "REAL": 4, "LREAL": 8}


def infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "DINT"
    if isinstance(value, float):
        return "REAL"
    return "STRING"


class Slot:
    """Where one tag lives: data block, byte offset, bit (BOOL only), type."""

    def __init__(self, source: str, db: int, offset: int, typ: str, bit: int = 0, strlen: int = 0):
        self.source, self.db, self.offset, self.type, self.bit, self.strlen = source, db, offset, typ, bit, strlen

    @property
    def size(self) -> int:
        return self.strlen + 2 if self.type == "STRING" else SIZES[self.type]

    def encode(self, area: bytearray, value: Any):
        o = self.offset
        if self.type == "BOOL":
            if value:
                area[o] |= 1 << self.bit
            else:
                area[o] &= ~(1 << self.bit) & 0xFF
        elif self.type == "REAL":
            area[o:o + 4] = struct.pack(">f", float(value))
        elif self.type == "LREAL":
            area[o:o + 8] = struct.pack(">d", float(value))
        elif self.type == "DINT":
            area[o:o + 4] = struct.pack(">i", max(-2**31, min(2**31 - 1, int(value))))
        elif self.type == "INT":
            area[o:o + 2] = struct.pack(">h", max(-2**15, min(2**15 - 1, int(value))))
        else:
            raw = str(value).encode("latin-1", "replace")[:self.strlen]
            area[o] = self.strlen
            area[o + 1] = len(raw)
            area[o + 2:o + 2 + self.strlen] = raw.ljust(self.strlen, b"\x00")

    def decode(self, area: bytearray) -> Any:
        o = self.offset
        if self.type == "BOOL":
            return bool(area[o] >> self.bit & 1)
        if self.type == "REAL":
            return struct.unpack(">f", bytes(area[o:o + 4]))[0]
        if self.type == "LREAL":
            return struct.unpack(">d", bytes(area[o:o + 8]))[0]
        if self.type == "DINT":
            return struct.unpack(">i", bytes(area[o:o + 4]))[0]
        if self.type == "INT":
            return struct.unpack(">h", bytes(area[o:o + 2]))[0]
        n = min(area[o + 1], self.strlen)
        return bytes(area[o + 2:o + 2 + n]).decode("latin-1")


class S7CommPublisher(SimProtocolPublisher):
    """S7comm server. Config key: publishers.s7comm."""

    config_key = "s7comm"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.default_db = int(config.get("db", 1))
        self.db_size = int(config.get("db_size", 1024))
        self.string_length = int(config.get("string_length", 32))
        self.overrides: Dict[str, Any] = config.get("tag_mapping", {}) or {}
        self.areas: Dict[int, bytearray] = {}
        self.slots: Dict[str, Slot] = {}
        self._cursor: Dict[int, Tuple[int, int]] = {}  # db -> (next free byte, next free bit or -1)
        self._server = None

    # layout ----------------------------------------------------------------
    def _alloc(self, db: int, size: int, align: int) -> int:
        nxt, _ = self._cursor.get(db, (0, -1))
        off = (nxt + align - 1) // align * align
        self._cursor[db] = (off + size, -1)
        return off

    def _place(self, source: str, value: Any) -> Optional[Slot]:
        ov = self.overrides.get(source, {}) or {}
        typ = str(ov.get("type", infer_type(value))).upper()
        if typ not in SIZES and typ != "STRING":
            typ = infer_type(value)
        db = int(ov.get("db", self.default_db))
        strlen = int(ov.get("length", self.string_length)) if typ == "STRING" else 0
        if db not in self.areas:
            self.logger.warning(f"S7comm: {source} wants DB{db}, which is not registered; list it in publishers.s7comm.dbs")
            return None
        if "offset" in ov:
            off, bit = int(ov["offset"]), int(ov.get("bit", 0))
        elif typ == "BOOL":
            nxt, bit_next = self._cursor.get(db, (0, -1))
            if bit_next < 0 or bit_next > 7:
                off, bit = self._alloc(db, 1, 1), 0
            else:
                off, bit = nxt - 1, bit_next
            self._cursor[db] = (off + 1, bit + 1)
        else:
            size = strlen + 2 if typ == "STRING" else SIZES[typ]
            off, bit = self._alloc(db, size, 2), 0
        slot = Slot(source, db, off, typ, bit, strlen)
        if off + slot.size > len(self.areas[db]):
            self.logger.warning(f"S7comm: DB{db} ({len(self.areas[db])} bytes) is full; {source} is not served. Raise db_size.")
            return None
        return slot

    def on_value(self, tag_name, value):
        with self.lock:
            slot = self.slots.get(tag_name)
            if slot is None:
                slot = self._place(tag_name, value)
                if slot is None:
                    return
                self.slots[tag_name] = slot
            slot.encode(self.areas[slot.db], value)

    # server ----------------------------------------------------------------
    def start(self):
        if not self.enabled:
            self.logger.info("S7comm publisher is disabled")
            return
        from snap7.server import Server
        from snap7.type import SrvArea
        port = int(self.config.get("port", 102))
        for db in [self.default_db] + [int(d) for d in self.config.get("dbs", [])]:
            self.areas.setdefault(db, bytearray(self.db_size))
        self._server = Server()
        for db, area in self.areas.items():
            self._server.register_area(SrvArea.DB, db, area)
        self._server.set_events_callback(self._event)
        try:
            self._server.start(tcp_port=port)
        except Exception as exc:
            self.logger.error(f"S7comm could not start on port {port}: {exc}")
            self._server = None
            return
        self.running = True
        self.logger.info(f"S7comm server on TCP {port}, data blocks {sorted(self.areas)} of {self.db_size} bytes")

    def stop(self):
        self.running = False
        if self._server is not None:
            try:
                self._server.stop()
            except Exception:
                pass
            self._server = None
        self.logger.info("S7comm publisher stopped")

    def _event(self, event):
        """A client wrote a data block: carry changed values into the tag store."""
        try:
            text = self._server.event_text(event)
        except Exception:
            return
        if "Write" not in text:
            return
        with self.lock:
            slots = list(self.slots.values())
        for slot in slots:
            try:
                new = slot.decode(self.areas[slot.db])
            except Exception:
                continue
            old = self.values.get(slot.source)
            same = new == old or (isinstance(old, float) and isinstance(new, float)
                                  and abs(new - old) < 1e-5 * max(1.0, abs(old)))
            if not same:
                self.client_write(slot.source, new)
