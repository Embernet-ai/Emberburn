"""IEC 61850-8-1 GOOSE: EmberBurn publishes tags as a GOOSE control block, and can
subscribe to one. Config keys: publishers.goose (publisher) and
publishers.goose_subscriber.

GOOSE is a layer 2 multicast protocol (Ethernet type 0x88B8, destination
01:0C:CD:01:xx:xx), so it needs a raw socket: the NET_RAW capability, and it only
reaches the Ethernet segment of the interface (see protocols/rawnet.py).

No library is used. The wire format is written against IEC 61850-8-1:2011 clause 18
(GOOSE: the Ethernet frame, APPID, the goosePdu ASN.1 of annex A, the state number
and sequence number rules and retransmission, 18.1.2) and ITU-T X.690 (BER).
Retransmission follows the standard's scheme: on a change stNum increases and sNum
restarts at 0, the frame is sent at once and repeated at min_time_ms, then at
doubling intervals up to max_time_ms, which is also the heartbeat; timeAllowedtoLive
is twice max_time_ms.

Data set entries are the configured `tags`, in order: a bool is BOOLEAN, an int
INTEGER, a float FLOAT (32 bit), a string VISIBLE-STRING.

Not simulated: Sampled Values, R-GOOSE (routable), security (IEC 62351-6), and VLAN
priority handling beyond the tag.
"""
import logging
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from protocols.base import SimProtocolPublisher
from protocols.rawnet import RawInterface, mac_bytes, mac_str, payload_offset

ETHERTYPE_GOOSE = 0x88B8


# ── BER ────────────────────────────────────────────────────────────────────
def ber_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + ber_len(len(value)) + value


def ber_int(v: int, signed: bool = True) -> bytes:
    if signed:
        n = max(1, (v.bit_length() + 8) // 8)
        return v.to_bytes(n, "big", signed=True)
    n = max(1, (v.bit_length() + 7) // 8)
    b = v.to_bytes(n, "big")
    return b"\x00" + b if b[0] & 0x80 else b


def utc_time(ts: float) -> bytes:
    """UtcTime: 4 byte seconds, 3 byte fraction of a second, 1 byte quality
    (leap second not known 0, clock failure 0, not synchronised 0, accuracy 10 bits = 0b01010)."""
    sec = int(ts)
    frac = int((ts - sec) * (1 << 24))
    return struct.pack(">I", sec) + frac.to_bytes(3, "big") + bytes([0x0A])


def data_item(v: Any) -> bytes:
    if isinstance(v, bool):
        return tlv(0x83, b"\xff" if v else b"\x00")
    if isinstance(v, int):
        return tlv(0x85, ber_int(v))
    if isinstance(v, float):
        return tlv(0x87, b"\x08" + struct.pack(">f", v))  # exponent width 8, then IEEE 754 single
    return tlv(0x8A, str(v).encode("latin-1", "replace"))


def build_pdu(gocb_ref: str, ttl_ms: int, dat_set: str, go_id: str, ts: float, st_num: int, sq_num: int,
              test: bool, conf_rev: int, nds_com: bool, values: List[Any]) -> bytes:
    body = (tlv(0x80, gocb_ref.encode()) + tlv(0x81, ber_int(ttl_ms)) + tlv(0x82, dat_set.encode())
            + tlv(0x83, go_id.encode()) + tlv(0x84, utc_time(ts)) + tlv(0x85, ber_int(st_num, False))
            + tlv(0x86, ber_int(sq_num, False)) + tlv(0x87, b"\xff" if test else b"\x00")
            + tlv(0x88, ber_int(conf_rev, False)) + tlv(0x89, b"\xff" if nds_com else b"\x00")
            + tlv(0x8A, ber_int(len(values), False)) + tlv(0xAB, b"".join(data_item(v) for v in values)))
    return tlv(0x61, body)


def build_frame(dst: bytes, src: bytes, appid: int, pdu: bytes, vlan: Optional[Tuple[int, int]] = (4, 0)) -> bytes:
    """Ethernet frame: optional 802.1Q tag (priority, VID), 0x88B8, APPID, Length, Reserved1/2, PDU."""
    hdr = dst + src
    if vlan is not None:
        hdr += struct.pack(">HH", 0x8100, (vlan[0] << 13) | vlan[1])
    hdr += struct.pack(">H", ETHERTYPE_GOOSE)
    return hdr + struct.pack(">HHHH", appid, 8 + len(pdu), 0, 0) + pdu


# ── decode (for the subscriber, and checked against the encoder in the tests) ──
def read_tlv(b: bytes, pos: int) -> Tuple[int, bytes, int]:
    tag = b[pos]
    ln = b[pos + 1]
    pos += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(b[pos:pos + n], "big")
        pos += n
    return tag, b[pos:pos + ln], pos + ln


def decode_frame(frame: bytes) -> Dict[str, Any]:
    off = payload_offset(frame)
    appid, length = struct.unpack_from(">HH", frame, off)
    pdu = frame[off + 8:off + length]
    tag, body, _ = read_tlv(pdu, 0)
    if tag != 0x61:
        raise ValueError("not a goosePdu")
    out: Dict[str, Any] = {"appid": appid, "dst": mac_str(frame[0:6]), "src": mac_str(frame[6:12]), "values": []}
    pos = 0
    names = {0x80: "gocbRef", 0x81: "ttl", 0x82: "datSet", 0x83: "goID", 0x84: "t", 0x85: "stNum", 0x86: "sqNum",
             0x87: "test", 0x88: "confRev", 0x89: "ndsCom", 0x8A: "numEntries"}
    while pos < len(body):
        tag, val, pos = read_tlv(body, pos)
        if tag == 0xAB:
            p = 0
            while p < len(val):
                t, v, p = read_tlv(val, p)
                if t == 0x83:
                    out["values"].append(v != b"\x00")
                elif t in (0x85, 0x86):
                    out["values"].append(int.from_bytes(v, "big", signed=(t == 0x85)))
                elif t == 0x87:
                    out["values"].append(struct.unpack(">f", v[1:5])[0])
                elif t == 0x8A:
                    out["values"].append(v.decode("latin-1"))
                else:
                    out["values"].append(v)
            continue
        name = names.get(tag)
        if name in ("gocbRef", "datSet", "goID"):
            out[name] = val.decode()
        elif name in ("ttl",):
            out[name] = int.from_bytes(val, "big", signed=True)
        elif name in ("stNum", "sqNum", "confRev", "numEntries"):
            out[name] = int.from_bytes(val, "big")
        elif name in ("test", "ndsCom"):
            out[name] = val != b"\x00"
        elif name == "t":
            out[name] = int.from_bytes(val[:4], "big") + int.from_bytes(val[4:7], "big") / (1 << 24)
    return out


class GoosePublisher(SimProtocolPublisher):
    """GOOSE publisher. Config key: publishers.goose."""

    config_key = "goose"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.tags: List[str] = [str(t) for t in (config.get("tags") or [])]
        self.iface: Optional[RawInterface] = None
        self.st_num = 1
        self.sq_num = 0
        self.snapshot: List[Any] = []
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._changed = threading.Event()

    def start(self):
        if not self.enabled:
            return
        try:
            self.iface = RawInterface(self.config.get("interface"))
        except OSError as exc:
            self.logger.error(f"GOOSE needs a raw socket (NET_RAW) on an interface: {exc}")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="goose")
        self._thread.start()
        self.running = True
        self.logger.info(f"GOOSE publisher on {self.iface.name}, dataset of {len(self.tags)} tags")

    def stop(self):
        self.running = False
        self._stop.set()
        self._changed.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self.iface is not None:
            self.iface.close()
        self.logger.info("GOOSE publisher stopped")

    def on_value(self, tag, value):
        if tag in self.tags:
            self._changed.set()

    def _values(self) -> List[Any]:
        with self.lock:
            return [self.values.get(t, False) for t in self.tags]

    def _frame(self, values: List[Any]) -> bytes:
        c = self.config
        max_ms = int(c.get("max_time_ms", 1000))
        vlan = (int(c.get("vlan_priority", 4)), int(c.get("vlan_id", 0))) if c.get("vlan", True) else None
        pdu = build_pdu(str(c.get("gocb_ref", "EmberBurnIED/LLN0$GO$gcb01")), 2 * max_ms,
                        str(c.get("dat_set", "EmberBurnIED/LLN0$DataSet1")), str(c.get("go_id", "EmberBurnGOOSE1")),
                        time.time(), self.st_num, self.sq_num, bool(c.get("test", False)),
                        int(c.get("conf_rev", 1)), bool(c.get("nds_com", False)), values)
        return build_frame(mac_bytes(str(c.get("dest_mac", "01:0C:CD:01:00:01"))), self.iface.mac,
                           int(c.get("appid", 0x0001)), pdu, vlan)

    def _run(self):
        min_s = int(self.config.get("min_time_ms", 8)) / 1000.0
        max_s = int(self.config.get("max_time_ms", 1000)) / 1000.0
        # wait for the first values, then the first frame is stNum 1, sqNum 0
        while not self._stop.is_set() and not any(t in self.values for t in self.tags):
            self._stop.wait(0.2)
        last = self._values()
        interval = min_s
        self._changed.clear()
        while not self._stop.is_set():
            try:
                self.iface.send(self._frame(last))
            except OSError as exc:
                self.logger.warning(f"GOOSE send failed: {exc}")
            self.sq_num = (self.sq_num + 1) & 0xFFFFFFFF
            if self._changed.wait(interval):
                self._changed.clear()
                cur = self._values()
                if cur != last:
                    last = cur
                    self.st_num = (self.st_num + 1) & 0xFFFFFFFF or 1  # stNum 0 is not used
                    self.sq_num = 0
                    interval = min_s
                    continue
            interval = min(interval * 2, max_s)


class GooseSubscriberPublisher(SimProtocolPublisher):
    """GOOSE subscriber. Config key: publishers.goose_subscriber.

    Listens on `dest_mac` for GOOSE with the configured `gocb_ref` (any if unset) and
    writes dataset entry i into tag `tags[i]` of the gateway. `received` keeps the last
    decoded message."""

    config_key = "goose_subscriber"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.tags: List[str] = [str(t) for t in (config.get("tags") or [])]
        self.iface: Optional[RawInterface] = None
        self.received: Optional[Dict[str, Any]] = None
        self.last_st = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self):
        if not self.enabled:
            return
        try:
            self.iface = RawInterface(self.config.get("interface"), [ETHERTYPE_GOOSE])
            self.iface.join(str(self.config.get("dest_mac", "01:0C:CD:01:00:01")))
        except OSError as exc:
            self.logger.error(f"GOOSE subscriber needs a raw socket (NET_RAW): {exc}")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="goose-sub")
        self._thread.start()
        self.running = True

    def stop(self):
        self.running = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self.iface is not None:
            self.iface.close()

    def _run(self):
        want = self.config.get("gocb_ref")
        while not self._stop.is_set():
            frame = self.iface.recv()
            if frame is None:
                continue
            try:
                m = decode_frame(frame)
            except Exception:
                continue
            if want and m.get("gocbRef") != want:
                continue
            self.received = m
            if m["stNum"] != self.last_st:  # a new state: apply it
                self.last_st = m["stNum"]
                for tag, v in zip(self.tags, m["values"]):
                    with self.lock:
                        self.values[tag] = v
                    if self._write_callback:
                        self._write_callback(tag, v)
