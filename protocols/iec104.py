"""IEC 60870-5-104 simulator: EmberBurn as a controlled station (RTU), and as a
controlling station (master). Config keys: publishers.iec104 and
publishers.iec104_master.

No library is used. The Python libraries for this protocol are GPLv3 (c104,
lib60870 bindings), which EmberBurn (MIT) cannot link, so the wire format is
written here against:

  * IEC 60870-5-104:2006 (+A1:2016) "Network access for IEC 60870-5-101 using
    standard transport profiles": APCI and the U, S and I frame formats (clause 5),
    sequence numbers and the k, w, t1, t2, t3 parameters (5.1 to 5.4), start and
    stop of data transfer (5.3).
  * IEC 60870-5-101:2003 clause 7 for the ASDU: data unit identifier (7.2.1),
    type identifications and information elements (7.2.6), cause of transmission
    (7.2.3), station interrogation (7.4.5), counter interrogation (7.4.7), commands
    (7.3), CP56Time2a (7.2.6.18).

Controlled station behaviour: STARTDT, STOPDT and TESTFR; station interrogation
(C_IC_NA_1, QOI 20) answered with every point (COT 20) then activation
termination; counter interrogation (C_CI_NA_1) with the counters (COT 37);
spontaneous reports (COT 3) with CP56Time2a time tags on change; optional cyclic
reports (COT 1); clock synchronisation, test and reset process commands answered
with activation confirmation; single and setpoint commands, with select before
execute, that write the tag. Unknown type, cause, common address or IOA are
answered with the negative confirmations (COT 44 to 47). Flow control follows
k=12 and w=8, and an idle link is probed with TESTFR after t3 (20 s).

Point types: a bool tag is M_SP_NA_1 (1), a float tag M_ME_NC_1 (13) short float,
an int tag M_ME_NB_1 (11) scaled value, a tag mapped as `counter` M_IT_NA_1 (15).
A tag mapped as `command` is a controllable point: a bool is C_SC_NA_1 (45), a
float C_SE_NC_1 (50), an int C_SE_NB_1 (49).

Not simulated: double-point and step position information, bitstrings, file
transfer, parameter commands, TLS (IEC 62351-3), and the t1 timeout on a silent
peer.
"""
import logging
import queue
import select
import socket
import socketserver
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from protocols.base import SimProtocolPublisher

START = 0x68
MAX_APDU = 253
K, W = 12, 8
T3 = 20.0

# U frame control octet 1
STARTDT_ACT, STARTDT_CON = 0x07, 0x0B
STOPDT_ACT, STOPDT_CON = 0x13, 0x23
TESTFR_ACT, TESTFR_CON = 0x43, 0x83

# type identifications
M_SP_NA_1, M_ME_NB_1, M_ME_NC_1, M_IT_NA_1 = 1, 11, 13, 15
M_SP_TB_1, M_ME_TE_1, M_ME_TF_1, M_IT_TB_1 = 30, 35, 36, 37
C_SC_NA_1, C_SE_NB_1, C_SE_NC_1 = 45, 49, 50
C_IC_NA_1, C_CI_NA_1, C_CS_NA_1, C_TS_NA_1, C_RP_NA_1 = 100, 101, 103, 104, 105
TIMED = {M_SP_NA_1: M_SP_TB_1, M_ME_NB_1: M_ME_TE_1, M_ME_NC_1: M_ME_TF_1, M_IT_NA_1: M_IT_TB_1}

# causes of transmission
COT_CYCLIC, COT_BACKGROUND, COT_SPONT, COT_INIT, COT_REQ = 1, 2, 3, 4, 5
COT_ACT, COT_ACTCON, COT_DEACT, COT_DEACTCON, COT_ACTTERM = 6, 7, 8, 9, 10
COT_INROGEN, COT_REQCOGEN = 20, 37
COT_UNKNOWN_TYPE, COT_UNKNOWN_CAUSE, COT_UNKNOWN_CA, COT_UNKNOWN_IOA = 44, 45, 46, 47

# element sizes (bytes after the 3 byte IOA), without time tag
ELEMENT_SIZE = {M_SP_NA_1: 1, M_ME_NB_1: 3, M_ME_NC_1: 5, M_IT_NA_1: 5}


def cp56(ts: Optional[float] = None) -> bytes:
    """CP56Time2a: ms (2), minute+IV (1), hour+SU (1), day+weekday (1), month (1), year (1)."""
    t = time.gmtime(ts if ts is not None else time.time())
    ms = t.tm_sec * 1000 + int((ts if ts is not None else time.time()) % 1 * 1000)
    wday = t.tm_wday + 1  # IEC: 1 = Monday
    return struct.pack("<HBBBBB", ms, t.tm_min, t.tm_hour, (wday << 5) | t.tm_mday, t.tm_mon, t.tm_year - 2000)


def u_frame(code: int) -> bytes:
    return bytes([START, 4, code, 0, 0, 0])


def s_frame(recv: int) -> bytes:
    return bytes([START, 4, 0x01, 0, (recv << 1) & 0xFF, (recv << 1) >> 8])


def i_frame(send: int, recv: int, asdu: bytes) -> bytes:
    return bytes([START, 4 + len(asdu), (send << 1) & 0xFF, (send << 1) >> 8,
                  (recv << 1) & 0xFF, (recv << 1) >> 8]) + asdu


def asdu(type_id: int, items: List[Tuple[int, bytes]], cot: int, ca: int, orig: int = 0,
         negative: bool = False, test: bool = False) -> bytes:
    """Data unit identifier plus information objects, one IOA each (SQ = 0)."""
    vsq = len(items) & 0x7F
    cot_b = (cot & 0x3F) | (0x40 if negative else 0) | (0x80 if test else 0)
    out = bytes([type_id, vsq, cot_b, orig]) + struct.pack("<H", ca)
    for ioa, element in items:
        out += struct.pack("<I", ioa)[:3] + element
    return out


def parse_asdu(data: bytes) -> Dict[str, Any]:
    """Data unit identifier and the raw object bytes. Objects are decoded by the caller
    because their size depends on the type."""
    if len(data) < 6:
        raise ValueError("short ASDU")
    type_id, vsq, cot_b, orig = data[0], data[1], data[2], data[3]
    (ca,) = struct.unpack_from("<H", data, 4)
    return {"type": type_id, "sq": bool(vsq & 0x80), "n": vsq & 0x7F, "cot": cot_b & 0x3F,
            "negative": bool(cot_b & 0x40), "test": bool(cot_b & 0x80), "orig": orig, "ca": ca, "body": data[6:]}


def parse_frames(buf: bytearray) -> List[bytes]:
    """Pull complete APDUs (start byte, length, control octets and ASDU) out of buf."""
    frames = []
    while True:
        while buf and buf[0] != START:
            del buf[0]  # resynchronise on the start byte
        if len(buf) < 2:
            break
        n = buf[1]
        if n < 4:
            del buf[0]
            continue
        if len(buf) < 2 + n:
            break
        frames.append(bytes(buf[2:2 + n]))
        del buf[:2 + n]
    return frames


# ── points ─────────────────────────────────────────────────────────────────
class Point:
    def __init__(self, source: str, ioa: int, type_id: int, value: Any, deadband: float = 0.0, scale: float = 1.0):
        self.source, self.ioa, self.type_id = source, ioa, type_id
        self.value = value
        self.deadband, self.scale = deadband, scale
        self.reported = value

    def element(self) -> bytes:
        v = self.value
        if self.type_id == M_SP_NA_1:
            return bytes([1 if v else 0])
        if self.type_id == M_ME_NC_1:
            return struct.pack("<fB", float(v), 0)
        if self.type_id == M_ME_NB_1:
            return struct.pack("<hB", max(-32768, min(32767, round(float(v) * self.scale))), 0)
        return struct.pack("<iB", max(-2**31, min(2**31 - 1, int(v))), 0)  # BCR: counter reading + SQ, CY, CA, IV octet

    def changed(self) -> bool:
        if self.type_id == M_ME_NC_1 or self.type_id == M_ME_NB_1:
            return abs(float(self.value) - float(self.reported)) > self.deadband
        return self.value != self.reported


class Command:
    def __init__(self, source: str, ioa: int, type_id: int):
        self.source, self.ioa, self.type_id = source, ioa, type_id


class Station:
    """The controlled station's information model, socket free."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.ca = int(cfg.get("common_address", 1))
        self.overrides: Dict[str, Any] = cfg.get("tag_mapping", {}) or {}
        self.points: Dict[str, Point] = {}
        self.commands: Dict[int, Command] = {}
        self.lock = threading.RLock()
        self._next = {M_SP_NA_1: 1, M_ME_NB_1: 2001, M_ME_NC_1: 3001, M_IT_NA_1: 4001, "cmd": 5001}
        self.default_deadband = float(cfg.get("deadband", 0.5))
        self.default_scale = float(cfg.get("scale", 1.0))

    def add(self, tag: str, value: Any):
        ov = self.overrides.get(tag, {}) or {}
        kind = str(ov.get("type", "")).lower()
        with self.lock:
            if kind == "command":
                tid = C_SC_NA_1 if isinstance(value, bool) else (C_SE_NC_1 if isinstance(value, float) else C_SE_NB_1)
                ioa = int(ov.get("ioa", self._next["cmd"]))
                self._next["cmd"] = max(self._next["cmd"], ioa) + 1
                self.commands[ioa] = Command(tag, ioa, tid)
                # a command point is also readable: report its value as a measurement
                kind = ""
            if kind == "counter":
                tid = M_IT_NA_1
            elif isinstance(value, bool):
                tid = M_SP_NA_1
            elif isinstance(value, float):
                tid = M_ME_NC_1
            elif isinstance(value, int):
                tid = M_ME_NB_1
            else:
                return None  # strings have no IEC 104 information element
            ioa = int(ov.get("ioa", self._next[tid]))
            self._next[tid] = max(self._next[tid], ioa) + 1
            p = Point(tag, ioa, tid, value, float(ov.get("deadband", self.default_deadband if tid in (M_ME_NC_1, M_ME_NB_1) else 0.0)),
                      float(ov.get("scale", self.default_scale)))
            self.points[tag] = p
            return p

    def sorted_points(self, types) -> List[Point]:
        with self.lock:
            return sorted((p for p in self.points.values() if p.type_id in types), key=lambda p: p.ioa)

    def chunks(self, pts: List[Point], type_id: int, cot: int, timed: bool = False) -> List[bytes]:
        """ASDUs for pts, as many objects per ASDU as fit in one APDU."""
        tid = TIMED[type_id] if timed else type_id
        size = 3 + ELEMENT_SIZE[type_id] + (7 if timed else 0)
        per = max(1, min(127, (MAX_APDU - 4 - 6) // size))
        out = []
        for i in range(0, len(pts), per):
            items = []
            for p in pts[i:i + per]:
                el = p.element() + (cp56() if timed else b"")
                items.append((p.ioa, el))
            out.append(asdu(tid, items, cot, self.ca))
        return out

    def interrogation(self, cot_data: int, types_order) -> List[bytes]:
        out: List[bytes] = []
        for t in types_order:
            pts = self.sorted_points((t,))
            if pts:
                out += self.chunks(pts, t, cot_data)
        return out


# ── controlled station: connections ─────────────────────────────────────────
class Link:
    """One TCP connection: APCI state, window, timers."""

    def __init__(self, sock: socket.socket, station: Station, write_cb, logger):
        self.sock, self.station, self.write_cb, self.logger = sock, station, write_cb, logger
        self.send_seq = 0      # V(S)
        self.recv_seq = 0      # V(R)
        self.ack_seq = 0       # N(R) last received from the peer: our I frames acknowledged up to here
        self.unacked_rx = 0
        self.started = False
        self.out: "queue.Queue[bytes]" = queue.Queue()
        self.last_rx = time.monotonic()
        self.last_tx = time.monotonic()
        self.alive = True
        self.selected: Dict[int, float] = {}

    def enqueue(self, a: bytes):
        self.out.put(a)

    def _send(self, b: bytes):
        self.sock.sendall(b)
        self.last_tx = time.monotonic()

    def _in_window(self) -> bool:
        return ((self.send_seq - self.ack_seq) & 0x7FFF) < K

    def _flush(self):
        while self.started and self._in_window():
            try:
                a = self.out.get_nowait()
            except queue.Empty:
                break
            self._send(i_frame(self.send_seq, self.recv_seq, a))
            self.send_seq = (self.send_seq + 1) & 0x7FFF
            self.unacked_rx = 0

    def run(self):
        buf = bytearray()
        self.sock.setblocking(False)
        while self.alive:
            r, _, _ = select.select([self.sock], [], [], 0.1)
            if r:
                try:
                    data = self.sock.recv(4096)
                except (BlockingIOError, InterruptedError):
                    data = None
                except OSError:
                    break
                if data == b"":
                    break
                if data:
                    self.last_rx = time.monotonic()
                    buf += data
                    for frame in parse_frames(buf):
                        self._handle(frame)
            self._flush()
            now = time.monotonic()
            if self.unacked_rx and now - self.last_tx > 10.0:  # t2: acknowledge within 10 s
                self._send(s_frame(self.recv_seq))
                self.unacked_rx = 0
            if now - max(self.last_rx, self.last_tx) > T3:     # t3: probe an idle link
                self._send(u_frame(TESTFR_ACT))
                self.last_tx = now

    def _handle(self, frame: bytes):
        c1 = frame[0]
        if c1 & 1 == 0:  # I frame
            send = ((frame[1] << 8 | c1) >> 1) & 0x7FFF
            ack = ((frame[3] << 8 | frame[2]) >> 1) & 0x7FFF
            self.ack_seq = ack
            if send != self.recv_seq:
                self.logger.warning(f"IEC 104 sequence error: got {send}, expected {self.recv_seq}; closing")
                self.alive = False
                return
            self.recv_seq = (self.recv_seq + 1) & 0x7FFF
            self.unacked_rx += 1
            if self.unacked_rx >= W:
                self._send(s_frame(self.recv_seq))
                self.unacked_rx = 0
            self._asdu(frame[4:])
        elif c1 & 3 == 1:  # S frame
            self.ack_seq = ((frame[3] << 8 | frame[2]) >> 1) & 0x7FFF
        else:  # U frame
            if c1 == STARTDT_ACT:
                self._send(u_frame(STARTDT_CON))
                self.started = True
            elif c1 == STOPDT_ACT:
                self._send(u_frame(STOPDT_CON))
                self.started = False
            elif c1 == TESTFR_ACT:
                self._send(u_frame(TESTFR_CON))

    def _reply(self, req: Dict[str, Any], cot: int, negative: bool = False, body: Optional[bytes] = None):
        b = req["body"] if body is None else body
        data = bytes([req["type"], req["n"] | (0x80 if req["sq"] else 0), (cot & 0x3F) | (0x40 if negative else 0), req["orig"]]) \
            + struct.pack("<H", req["ca"]) + b
        self.enqueue(data)

    def _asdu(self, data: bytes):
        try:
            req = parse_asdu(data)
        except ValueError:
            return
        st = self.station
        t, cot = req["type"], req["cot"]
        known = (C_SC_NA_1, C_SE_NB_1, C_SE_NC_1, C_IC_NA_1, C_CI_NA_1, C_CS_NA_1, C_TS_NA_1, C_RP_NA_1)
        if t not in known:
            return self._reply(req, COT_UNKNOWN_TYPE, True)
        if req["ca"] not in (st.ca, 0xFFFF):
            return self._reply(req, COT_UNKNOWN_CA, True)
        if cot not in (COT_ACT, COT_DEACT):
            return self._reply(req, COT_UNKNOWN_CAUSE, True)
        if t == C_IC_NA_1:
            qoi = req["body"][3] if len(req["body"]) >= 4 else 20
            if cot == COT_DEACT:
                return self._reply(req, COT_DEACTCON)
            self._reply(req, COT_ACTCON)
            if qoi == 20:
                for a in st.interrogation(COT_INROGEN, (M_SP_NA_1, M_ME_NB_1, M_ME_NC_1)):
                    self.enqueue(a)
            self._reply(req, COT_ACTTERM)
        elif t == C_CI_NA_1:
            self._reply(req, COT_ACTCON)
            for a in st.interrogation(COT_REQCOGEN, (M_IT_NA_1,)):
                self.enqueue(a)
            self._reply(req, COT_ACTTERM)
        elif t in (C_CS_NA_1, C_TS_NA_1, C_RP_NA_1):
            self._reply(req, COT_ACTCON)
        else:
            self._command(req)

    def _command(self, req: Dict[str, Any]):
        t, body = req["type"], req["body"]
        if len(body) < 3:
            return self._reply(req, COT_UNKNOWN_IOA, True)
        ioa = body[0] | body[1] << 8 | body[2] << 16
        cmd = self.station.commands.get(ioa)
        if cmd is None or cmd.type_id != t:
            return self._reply(req, COT_UNKNOWN_IOA, True)
        try:
            if t == C_SC_NA_1:
                value, select = bool(body[3] & 1), bool(body[3] & 0x80)
            elif t == C_SE_NC_1:
                value, select = struct.unpack_from("<f", body, 3)[0], bool(body[7] & 0x80)
            else:
                value, select = struct.unpack_from("<h", body, 3)[0], bool(body[5] & 0x80)
        except (struct.error, IndexError):
            return self._reply(req, COT_UNKNOWN_IOA, True)
        if req["cot"] == COT_DEACT:
            self.selected.pop(ioa, None)
            return self._reply(req, COT_DEACTCON)
        if select:
            self.selected[ioa] = time.monotonic()
            return self._reply(req, COT_ACTCON)
        # execute: a select-before-operate station refuses an execute with no select
        if self.station.cfg.get("select_before_operate", False) and time.monotonic() - self.selected.pop(ioa, -1e9) > 30.0:
            return self._reply(req, COT_ACTCON, True)
        ok = self.write_cb(cmd.source, value)
        self._reply(req, COT_ACTCON, not ok)
        if ok:
            self._reply(req, COT_ACTTERM)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        pub: "IEC104Publisher" = self.server.pub
        link = Link(self.request, pub.station, pub.client_write, pub.logger)
        with pub.links_lock:
            pub.links.append(link)
        try:
            link.run()
        except OSError:
            pass
        finally:
            link.alive = False
            with pub.links_lock:
                if link in pub.links:
                    pub.links.remove(link)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class IEC104Publisher(SimProtocolPublisher):
    """IEC 60870-5-104 controlled station. Config key: publishers.iec104."""

    config_key = "iec104"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.station = Station(config)
        self.links: List[Link] = []
        self.links_lock = threading.Lock()
        self._srv: Optional[_Server] = None
        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()

    def start(self):
        if not self.enabled:
            self.logger.info("IEC 104 publisher is disabled")
            return
        host, port = str(self.config.get("host", "0.0.0.0")), int(self.config.get("port", 2404))
        try:
            self._srv = _Server((host, port), _Handler)
        except OSError as exc:
            self.logger.error(f"IEC 104 could not bind {host}:{port}: {exc}")
            return
        self._srv.pub = self
        self._stop.clear()
        t = threading.Thread(target=self._srv.serve_forever, daemon=True, name="iec104")
        t.start()
        self._threads = [t]
        cyc = float(self.config.get("cyclic_seconds", 0))
        if cyc > 0:
            c = threading.Thread(target=self._cyclic, args=(cyc,), daemon=True, name="iec104-cyclic")
            c.start()
            self._threads.append(c)
        self.running = True
        self.logger.info(f"IEC 60870-5-104 controlled station (CA {self.station.ca}) on TCP {host}:{port}")

    def stop(self):
        self.running = False
        self._stop.set()
        if self._srv is not None:
            try:
                self._srv.shutdown()
                self._srv.server_close()
            except Exception:
                pass
            self._srv = None
        with self.links_lock:
            for l in self.links:
                l.alive = False
        self.logger.info("IEC 104 publisher stopped")

    def on_value(self, tag, value):
        st = self.station
        p = st.points.get(tag)
        if p is None:
            p = st.add(tag, value)
            if p is None:
                return
        with st.lock:
            p.value = value
            if not p.changed():
                return
            p.reported = value
            asdus = st.chunks([p], p.type_id, COT_SPONT, timed=True)
        with self.links_lock:
            links = list(self.links)
        for l in links:
            if l.started:
                for a in asdus:
                    l.enqueue(a)

    def _cyclic(self, period: float):
        while not self._stop.wait(period):
            asdus = []
            for t in (M_ME_NB_1, M_ME_NC_1):
                pts = self.station.sorted_points((t,))
                if pts:
                    asdus += self.station.chunks(pts, t, COT_CYCLIC)
            with self.links_lock:
                links = list(self.links)
            for l in links:
                if l.started:
                    for a in asdus:
                        l.enqueue(a)


# ── controlling station ─────────────────────────────────────────────────────
OBJ_SIZE = {M_SP_NA_1: 1, M_ME_NB_1: 3, M_ME_NC_1: 5, M_IT_NA_1: 5,
            M_SP_TB_1: 8, M_ME_TE_1: 10, M_ME_TF_1: 12, M_IT_TB_1: 12}


def decode_objects(a: Dict[str, Any]) -> Dict[int, Any]:
    """Information objects of a monitor direction ASDU as {ioa: value}."""
    t = a["type"]
    size = OBJ_SIZE.get(t)
    out: Dict[int, Any] = {}
    if size is None:
        return out
    body, n = a["body"], a["n"]
    pos = 0
    ioa = 0
    for i in range(n):
        if not a["sq"] or i == 0:
            if pos + 3 > len(body):
                break
            ioa = body[pos] | body[pos + 1] << 8 | body[pos + 2] << 16
            pos += 3
        else:
            ioa += 1
        if pos + size > len(body):
            break
        el = body[pos:pos + size]
        pos += size
        base = {M_SP_TB_1: M_SP_NA_1, M_ME_TE_1: M_ME_NB_1, M_ME_TF_1: M_ME_NC_1, M_IT_TB_1: M_IT_NA_1}.get(t, t)
        if base == M_SP_NA_1:
            out[ioa] = bool(el[0] & 1)
        elif base == M_ME_NB_1:
            out[ioa] = struct.unpack_from("<h", el, 0)[0]
        elif base == M_ME_NC_1:
            out[ioa] = struct.unpack_from("<f", el, 0)[0]
        else:
            out[ioa] = struct.unpack_from("<i", el, 0)[0]
    return out


class IEC104MasterPublisher(SimProtocolPublisher):
    """IEC 60870-5-104 controlling station. Config key: publishers.iec104_master.

    Connects to a controlled station, STARTDT, then a station interrogation and a
    counter interrogation at start and every `interval` seconds, acknowledging
    what it receives (S frame every w=8 I frames) and answering TESTFR. Values read
    are kept in `polled` as {ioa: value}. With `tag_map` ({EmberBurn tag: IOA}) it
    also sends the tag's value as a single command (bool) or short float setpoint
    (float) each interval, as direct execute.
    """

    config_key = "iec104_master"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.polled: Dict[int, Any] = {}
        self.cycles = 0

    def start(self):
        if not self.enabled:
            return
        if not self.config.get("host"):
            self.logger.error("IEC 104 master needs publishers.iec104_master.host")
            self.enabled = False
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="iec104-master")
        self._thread.start()

    def stop(self):
        self.running = False
        self._stop.set()

    def _run(self):
        delay = 2.0
        while not self._stop.is_set():
            try:
                self._session()
            except Exception as exc:
                self.unavailable_reason = f"cannot reach {self.config['host']}: {exc}"
                self.logger.warning(f"IEC 104 master {self.unavailable_reason}")
                self._stop.wait(delay)
                delay = min(delay * 2, 60.0)

    def _session(self):
        host, port = str(self.config["host"]), int(self.config.get("port", 2404))
        ca = int(self.config.get("common_address", 1))
        interval = float(self.config.get("interval", 10.0))
        tag_map: Dict[str, int] = self.config.get("tag_map", {}) or {}
        sock = socket.create_connection((host, port), timeout=10)
        sock.settimeout(0.2)
        send_seq = recv_seq = unacked = 0
        buf = bytearray()
        try:
            sock.sendall(u_frame(STARTDT_ACT))
            self.unavailable_reason = None
            self.logger.info(f"IEC 104 master connected to {host}:{port}")
            next_poll = 0.0
            while not self._stop.is_set():
                if time.monotonic() >= next_poll:
                    next_poll = time.monotonic() + interval
                    reqs = [asdu(C_IC_NA_1, [(0, bytes([20]))], COT_ACT, ca, 0),
                            asdu(C_CI_NA_1, [(0, bytes([5]))], COT_ACT, ca, 0)]
                    for tag, ioa in tag_map.items():
                        with self.lock:
                            v = self.values.get(tag)
                        if isinstance(v, bool):
                            reqs.append(asdu(C_SC_NA_1, [(ioa, bytes([1 if v else 0]))], COT_ACT, ca, 0))
                        elif isinstance(v, (int, float)):
                            reqs.append(asdu(C_SE_NC_1, [(ioa, struct.pack("<fB", float(v), 0))], COT_ACT, ca, 0))
                    for r in reqs:
                        sock.sendall(i_frame(send_seq, recv_seq, r))
                        send_seq = (send_seq + 1) & 0x7FFF
                    self.cycles += 1
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    raise ConnectionError("closed by the controlled station")
                buf += data
                for frame in parse_frames(buf):
                    c1 = frame[0]
                    if c1 & 1 == 0:
                        recv_seq = (recv_seq + 1) & 0x7FFF
                        unacked += 1
                        try:
                            self.polled.update(decode_objects(parse_asdu(frame[4:])))
                        except ValueError:
                            pass
                        if unacked >= W:
                            sock.sendall(s_frame(recv_seq))
                            unacked = 0
                    elif c1 == TESTFR_ACT:
                        sock.sendall(u_frame(TESTFR_CON))
        finally:
            try:
                sock.sendall(u_frame(STOPDT_ACT))
            except OSError:
                pass
            sock.close()
