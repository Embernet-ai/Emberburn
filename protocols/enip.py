"""EtherNet/IP and CIP simulator.

EmberBurn's tags are served as a Logix style controller: symbolic tag read and
write (Read Tag 0x4C, Write Tag 0x4D, the fragmented forms, Multiple Service
Packet), tag browse through the Symbol Object, the STRING template, the Identity
object, the Connection Manager (Unconnected Send, Forward Open, Large Forward
Open, Forward Close), connected explicit messaging, and implicit I/O on UDP 2222
from Assembly instances 100 (input, produced) and 101 (output, consumed).
ListIdentity, ListServices and ListInterfaces answer on both TCP and UDP 44818.

No library is used. The permissively licensed Python libraries for this protocol
are clients (pycomm3, MIT, which the tests use as the independent client). The
only server library, cpppo, is GPLv3 or proprietary, which EmberBurn (MIT) cannot
link. The wire format here is written against:

  * ODVA, "The CIP Networks Library, Volume 2: EtherNet/IP Adaptation of CIP",
    encapsulation (section 2), common packet format (2-6), ListIdentity (2-4.2).
  * ODVA, "The CIP Networks Library, Volume 1: Common Industrial Protocol",
    object model (chapter 4), EPATH encoding (appendix C), Connection Manager and
    Forward Open (3-5, 3-5.5.1), message router and status codes (appendix B).
  * Rockwell Automation, "Logix 5000 Controllers Data Access" (1756-PM020), for
    the tag services and the Symbol and Template objects. Those are Rockwell
    vendor objects; where the document leaves a field open, the field layout was
    confirmed against what pycomm3 (MIT) asks for and against Wireshark's CIP
    dissector output (tshark decodes every frame this module sends without a
    malformed or expert error, see test_enip.py and the release evidence).
    No code was copied from either.

Little endian everywhere except the sockaddr in ListIdentity and the Forward Open
sockaddr items, which are network byte order as the specification says.
"""
import ipaddress
import logging
import random
import socket
import socketserver
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from protocols.base import SimProtocolPublisher, symbol_name

# ── encapsulation (Vol 2 section 2-3) ──────────────────────────────────────
CMD_NOP = 0x0000
CMD_LIST_SERVICES = 0x0004
CMD_LIST_IDENTITY = 0x0063
CMD_LIST_INTERFACES = 0x0064
CMD_REGISTER_SESSION = 0x0065
CMD_UNREGISTER_SESSION = 0x0066
CMD_SEND_RR_DATA = 0x006F
CMD_SEND_UNIT_DATA = 0x0070

ENCAP_OK = 0x0000
ENCAP_UNSUPPORTED = 0x0001
ENCAP_NO_MEMORY = 0x0002
ENCAP_BAD_DATA = 0x0003
ENCAP_BAD_SESSION = 0x0064
ENCAP_BAD_LENGTH = 0x0065
ENCAP_BAD_VERSION = 0x0069

HDR = struct.Struct("<HHII8sI")  # command, length, session, status, context, options

# common packet format item types (Vol 2 2-6.1)
ITEM_NULL_ADDRESS = 0x0000
ITEM_LIST_IDENTITY = 0x000C
ITEM_CONNECTED_ADDRESS = 0x00A1
ITEM_CONNECTED_DATA = 0x00B1
ITEM_UNCONNECTED_DATA = 0x00B2
ITEM_LIST_SERVICES = 0x0100
ITEM_SOCKADDR_OT = 0x8000
ITEM_SOCKADDR_TO = 0x8001
ITEM_SEQUENCED_ADDRESS = 0x8002

# ── CIP services and status (Vol 1 appendix A and B) ───────────────────────
SVC_GET_ATTRIBUTES_ALL = 0x01
SVC_GET_ATTRIBUTE_LIST = 0x03
SVC_MULTIPLE = 0x0A
SVC_GET_ATTRIBUTE_SINGLE = 0x0E
SVC_SET_ATTRIBUTE_SINGLE = 0x10
SVC_FORWARD_CLOSE = 0x4E
SVC_UNCONNECTED_SEND = 0x52
SVC_FORWARD_OPEN = 0x54
SVC_GET_INSTANCE_ATTRIBUTE_LIST = 0x55
SVC_LARGE_FORWARD_OPEN = 0x5B
SVC_READ_TAG = 0x4C
SVC_WRITE_TAG = 0x4D
SVC_READ_TAG_FRAGMENTED = 0x52
SVC_WRITE_TAG_FRAGMENTED = 0x53

ST_OK = 0x00
ST_CONNECTION_FAILURE = 0x01
ST_PATH_SEGMENT_ERROR = 0x04
ST_PATH_DESTINATION_UNKNOWN = 0x05
ST_PARTIAL = 0x06
ST_SERVICE_NOT_SUPPORTED = 0x08
ST_ATTRIBUTE_NOT_SETTABLE = 0x0E
ST_NOT_ENOUGH_DATA = 0x13
ST_ATTRIBUTE_NOT_SUPPORTED = 0x14
ST_TOO_MUCH_DATA = 0x15
ST_OBJECT_DOES_NOT_EXIST = 0x16
ST_GENERAL_ERROR = 0xFF

# object classes
CLASS_IDENTITY = 0x01
CLASS_MESSAGE_ROUTER = 0x02
CLASS_ASSEMBLY = 0x04
CLASS_CONNECTION_MANAGER = 0x06
CLASS_PROGRAM_NAME = 0x64
CLASS_SYMBOL = 0x6B
CLASS_TEMPLATE = 0x6C

# CIP data type codes (Vol 1 appendix C-6)
T_BOOL = 0xC1
T_SINT = 0xC2
T_INT = 0xC3
T_DINT = 0xC4
T_LINT = 0xC5
T_REAL = 0xCA
T_LREAL = 0xCB
STRUCT_STRING_HANDLE = 0x0FCE  # Logix STRING (an 82 character ASCIISTRING82)
STRING_LEN = 82
STRING_SIZE = 88  # DINT LEN + 82 SINT DATA + 2 pad

ATOMIC = {
    "BOOL": (T_BOOL, "B", 1),
    "SINT": (T_SINT, "<b", 1),
    "INT": (T_INT, "<h", 2),
    "DINT": (T_DINT, "<i", 4),
    "LINT": (T_LINT, "<q", 8),
    "REAL": (T_REAL, "<f", 4),
    "LREAL": (T_LREAL, "<d", 8),
}
ATOMIC_BY_CODE = {code: name for name, (code, _, _) in ATOMIC.items()}

# Symbol Object attribute 6 "software control" bit: set for a base (non alias) tag.
BASE_TAG_BIT = 1 << 26

MAX_DATA = 480  # bytes of tag data in one response before a read goes fragmented


class CipError(Exception):
    def __init__(self, status: int, ext: bytes = b""):
        super().__init__(f"cip status 0x{status:02x}")
        self.status = status
        self.ext = ext


# ── EPATH (Vol 1 appendix C-1) ─────────────────────────────────────────────
def parse_epath(b: bytes) -> List[Tuple[str, Any]]:
    segs: List[Tuple[str, Any]] = []
    i = 0
    n = len(b)
    while i < n:
        t = b[i]
        if t in (0x20, 0x24, 0x30, 0x28, 0x2C):  # 8 bit logical: class, instance, attribute, member, connection point
            kind = {0x20: "class", 0x24: "instance", 0x30: "attribute", 0x28: "element", 0x2C: "connpoint"}[t]
            segs.append((kind, b[i + 1]))
            i += 2
        elif t in (0x21, 0x25, 0x31, 0x29, 0x2D):  # 16 bit, one pad byte
            kind = {0x21: "class", 0x25: "instance", 0x31: "attribute", 0x29: "element", 0x2D: "connpoint"}[t]
            segs.append((kind, struct.unpack_from("<H", b, i + 2)[0]))
            i += 4
        elif t in (0x22, 0x26, 0x32, 0x2A, 0x2E):  # 32 bit
            kind = {0x22: "class", 0x26: "instance", 0x32: "attribute", 0x2A: "element", 0x2E: "connpoint"}[t]
            segs.append((kind, struct.unpack_from("<I", b, i + 2)[0]))
            i += 6
        elif t == 0x91:  # ANSI extended symbol
            ln = b[i + 1]
            segs.append(("symbol", b[i + 2:i + 2 + ln].decode("ascii", "replace")))
            i += 2 + ln + (ln & 1)
        elif t & 0xE0 == 0x00:  # port segment: routing, ignored (single device)
            if t & 0x10:
                ln = b[i + 1]
                i += 2 + ln + ((2 + ln) & 1)
            else:
                i += 2
            segs.append(("port", None))
        elif t == 0x80 + 0x11 or t == 0x11:  # simple data segment
            ln = b[i + 1]
            i += 2 + ln * 2
        else:
            raise CipError(ST_PATH_SEGMENT_ERROR)
    return segs


def encode_epath(class_id: int, instance: int) -> bytes:
    return bytes([0x20, class_id, 0x24, instance])


def cip_reply(service: int, status: int = ST_OK, data: bytes = b"", ext: bytes = b"") -> bytes:
    return bytes([service | 0x80, 0, status, len(ext) // 2]) + ext + data


def shortstring(s: str) -> bytes:
    raw = s.encode("ascii", "replace")[:255]
    return bytes([len(raw)]) + raw


def cpf_encode(items: List[Tuple[int, bytes]]) -> bytes:
    out = struct.pack("<H", len(items))
    for t, d in items:
        out += struct.pack("<HH", t, len(d)) + d
    return out


def cpf_decode(b: bytes) -> List[Tuple[int, bytes]]:
    if len(b) < 2:
        raise CipError(ST_NOT_ENOUGH_DATA)
    (count,) = struct.unpack_from("<H", b, 0)
    items, i = [], 2
    for _ in range(count):
        if i + 4 > len(b):
            raise CipError(ST_NOT_ENOUGH_DATA)
        t, ln = struct.unpack_from("<HH", b, i)
        items.append((t, b[i + 4:i + 4 + ln]))
        i += 4 + ln
    return items


def sockaddr(ip: str, port: int, family: int = 2) -> bytes:
    """sockaddr_in as it travels in CIP: big endian, 16 bytes."""
    return struct.pack(">HH4s8x", family, port, socket.inet_aton(ip))


# ── tags ───────────────────────────────────────────────────────────────────
class TagDef:
    def __init__(self, source: str, name: str, cip_type: str, value: Any):
        self.source = source      # EmberBurn tag name
        self.name = name          # symbol served to the client
        self.cip_type = cip_type  # BOOL SINT INT DINT LINT REAL LREAL STRING
        self.value = value
        self.instance = 0

    @property
    def symbol_type(self) -> int:
        if self.cip_type == "STRING":
            return 0x8000 | STRUCT_STRING_HANDLE
        return ATOMIC[self.cip_type][0]

    @property
    def type_bytes(self) -> bytes:
        if self.cip_type == "STRING":
            return struct.pack("<BBH", 0xA0, 0x02, STRUCT_STRING_HANDLE)
        return struct.pack("<H", ATOMIC[self.cip_type][0])

    @property
    def size(self) -> int:
        return STRING_SIZE if self.cip_type == "STRING" else ATOMIC[self.cip_type][2]

    def encode(self) -> bytes:
        v = self.value
        if self.cip_type == "STRING":
            raw = str(v).encode("latin-1", "replace")[:STRING_LEN]
            return struct.pack("<i", len(raw)) + raw.ljust(STRING_LEN, b"\x00") + b"\x00\x00"
        if self.cip_type == "BOOL":
            return b"\xff" if v else b"\x00"
        fmt = ATOMIC[self.cip_type][1]
        if self.cip_type in ("REAL", "LREAL"):
            return struct.pack(fmt, float(v))
        bits = ATOMIC[self.cip_type][2] * 8
        iv = int(v)
        lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
        return struct.pack(fmt, max(lo, min(hi, iv)))

    def decode(self, raw: bytes) -> Any:
        if self.cip_type == "STRING":
            (ln,) = struct.unpack_from("<i", raw, 0)
            return raw[4:4 + max(0, min(ln, STRING_LEN))].decode("latin-1")
        if self.cip_type == "BOOL":
            return raw[0] != 0
        v = struct.unpack(ATOMIC[self.cip_type][1], raw[:ATOMIC[self.cip_type][2]])[0]
        return v


def infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "DINT"
    if isinstance(value, float):
        return "REAL"
    return "STRING"


class Layout:
    """Packs tag values into an assembly image, 32 bit types on 4 byte offsets."""

    def __init__(self):
        self.items: List[Tuple[TagDef, int]] = []
        self.size = 0

    def add(self, tag: TagDef):
        if tag.cip_type == "STRING":
            return
        align = min(4, tag.size)
        off = (self.size + align - 1) // align * align
        self.items.append((tag, off))
        self.size = off + tag.size

    def pack(self) -> bytes:
        buf = bytearray(self.size)
        for tag, off in self.items:
            buf[off:off + tag.size] = tag.encode()
        return bytes(buf)


# ── connections ────────────────────────────────────────────────────────────
class Connection:
    def __init__(self):
        self.ot_id = 0
        self.to_id = 0
        self.key = (0, 0, 0)
        self.klass = 3
        self.session = 0
        self.ot_rpi = 0
        self.to_rpi = 0
        self.timeout_mult = 0
        self.peer_ip = ""
        self.to_addr: Tuple[str, int] = ("", 2222)
        self.multicast = False
        self.out_cp = 0
        self.in_cp = 0
        self.to_size = 0
        self.ot_size = 0
        self.seq_to = 0
        self.enc_seq = 0
        self.last_rx = time.monotonic()
        self.alive = True


class EnipDevice:
    """The CIP object model. Socket free: bytes in, bytes out, so it is testable
    without a network and the TCP, UDP and I/O threads stay thin."""

    def __init__(self, cfg: Dict[str, Any], logger: logging.Logger, write_cb=None):
        self.cfg = cfg
        self.logger = logger
        self.write_cb = write_cb  # callable(source_tag, value) -> bool
        self.lock = threading.RLock()
        ident = cfg.get("identity", {}) or {}
        self.vendor_id = int(ident.get("vendor_id", 1))
        self.device_type = int(ident.get("device_type", 14))
        self.product_code = int(ident.get("product_code", 166))
        self.rev_major = int(ident.get("revision_major", 33))
        self.rev_minor = int(ident.get("revision_minor", 11))
        # 0x3060 reads as REMOTE RUN to a Logix aware client (low byte 0x60, high 0x30).
        self.status = int(ident.get("status", 0x3060))
        self.serial = int(ident.get("serial", 0x00EB0001))
        self.product_name = str(ident.get("product_name", "1756-L83E/B"))
        self.program_name = str(cfg.get("program_name", "EmberBurn"))
        self.tag_overrides = cfg.get("tag_mapping", {}) or {}
        self.tags: Dict[str, TagDef] = {}      # lower case symbol -> TagDef
        self.by_source: Dict[str, TagDef] = {}
        self.order: List[TagDef] = []
        self.by_instance: Dict[int, TagDef] = {}
        self.in_layout = Layout()
        self.out_layout = Layout()
        self.out_image = bytearray(int(cfg.get("assembly_output_size", 32)))
        self.next_session = 0x0000A001
        self.sessions: set = set()
        self.connections: Dict[int, Connection] = {}
        self.next_conn_id = 0x20000001
        self.public_ip = cfg.get("advertise_ip") or ""
        self.port = int(cfg.get("port", 44818))
        self.io_port = int(cfg.get("io_port", 2222))

    # ── tag registry ──────────────────────────────────────────────────────
    def set_tag(self, source: str, value: Any):
        with self.lock:
            td = self.by_source.get(source)
            if td is None:
                ov = self.tag_overrides.get(source, {}) or {}
                cip_type = str(ov.get("type", infer_type(value))).upper()
                if cip_type not in ATOMIC and cip_type != "STRING":
                    cip_type = infer_type(value)
                name = str(ov.get("name") or symbol_name(source))
                base, n = name, 2
                while name.lower() in self.tags:
                    name = f"{base}_{n}"
                    n += 1
                td = TagDef(source, name, cip_type, value)
                td.instance = len(self.order) + 1
                self.tags[name.lower()] = td
                self.by_source[source] = td
                self.order.append(td)
                self.by_instance[td.instance] = td
                self._layout_for(td)
            td.value = value

    def _layout_for(self, td: TagDef):
        """The input assembly packs tags in first-seen order, or in the order of
        assembly_input_tags when that is set, so a layout can be fixed in config
        and survives restarts. assembly_output_tags works the same way for the
        output assembly, whose bytes are written back into those tags."""
        if self.cfg.get("assembly_input_tags"):
            self.in_layout = self._listed_layout(self.cfg["assembly_input_tags"])
        else:
            self.in_layout.add(td)
        if self.cfg.get("assembly_output_tags"):
            self.out_layout = self._listed_layout(self.cfg["assembly_output_tags"])
            if self.out_layout.size > len(self.out_image):
                self.out_image.extend(bytes(self.out_layout.size - len(self.out_image)))

    def _listed_layout(self, names) -> Layout:
        lay = Layout()
        for n in names:
            td = self.by_source.get(str(n)) or self.tags.get(str(n).lower())
            if td:
                lay.add(td)
        return lay

    def input_image(self) -> bytes:
        with self.lock:
            return self.in_layout.pack()

    # ── encapsulation ─────────────────────────────────────────────────────
    def encap(self, cmd: int, session: int, status: int, ctx: bytes, data: bytes) -> bytes:
        return HDR.pack(cmd, len(data), session, status, ctx, 0) + data

    def list_identity_item(self, local_ip: str) -> bytes:
        body = struct.pack("<H", 1) + sockaddr(local_ip, self.port)
        body += struct.pack("<HHHBBHI", self.vendor_id, self.device_type, self.product_code,
                            self.rev_major, self.rev_minor, self.status, self.serial)
        body += shortstring(self.product_name) + bytes([0x03])
        return body

    def handle_encap(self, frame: bytes, state: Dict[str, Any]) -> Optional[bytes]:
        """One encapsulation frame in, the reply frame out (None for no reply).
        state is per TCP connection: local_ip, peer_ip, sessions, closed flag."""
        if len(frame) < HDR.size:
            return None
        cmd, length, session, _status, ctx, _opt = HDR.unpack_from(frame)
        data = frame[HDR.size:HDR.size + length]
        local_ip = self.public_ip or state.get("local_ip", "0.0.0.0")
        if cmd == CMD_NOP:
            return None
        if cmd == CMD_LIST_IDENTITY:
            item = self.list_identity_item(local_ip)
            return self.encap(cmd, session, ENCAP_OK, ctx, cpf_encode([(ITEM_LIST_IDENTITY, item)]))
        if cmd == CMD_LIST_SERVICES:
            item = struct.pack("<HH", 1, 0x0120) + b"Communications\x00\x00"
            return self.encap(cmd, session, ENCAP_OK, ctx, cpf_encode([(ITEM_LIST_SERVICES, item)]))
        if cmd == CMD_LIST_INTERFACES:
            return self.encap(cmd, session, ENCAP_OK, ctx, cpf_encode([]))
        if cmd == CMD_REGISTER_SESSION:
            if len(data) < 4:
                return self.encap(cmd, 0, ENCAP_BAD_LENGTH, ctx, b"")
            version = struct.unpack_from("<H", data, 0)[0]
            if version != 1:
                return self.encap(cmd, 0, ENCAP_BAD_VERSION, ctx, struct.pack("<HH", 1, 0))
            with self.lock:
                handle = self.next_session
                self.next_session += 1
                self.sessions.add(handle)
            state.setdefault("sessions", set()).add(handle)
            return self.encap(cmd, handle, ENCAP_OK, ctx, struct.pack("<HH", 1, 0))
        if cmd == CMD_UNREGISTER_SESSION:
            self.drop_session(session)
            state["closed"] = True
            return None
        if cmd in (CMD_SEND_RR_DATA, CMD_SEND_UNIT_DATA):
            if session not in self.sessions:
                return self.encap(cmd, session, ENCAP_BAD_SESSION, ctx, data)  # echo the request: analyzers expect the CPF body
            try:
                return self._send_data(cmd, session, ctx, data, state)
            except CipError:
                return self.encap(cmd, session, ENCAP_BAD_DATA, ctx, data)
        return self.encap(cmd, session, ENCAP_UNSUPPORTED, ctx, b"")

    def drop_session(self, session: int):
        with self.lock:
            self.sessions.discard(session)
            for cid, c in list(self.connections.items()):
                if c.session == session:
                    c.alive = False
                    del self.connections[cid]

    def _send_data(self, cmd, session, ctx, data, state):
        if len(data) < 6:
            raise CipError(ST_NOT_ENOUGH_DATA)
        iface, timeout = struct.unpack_from("<IH", data, 0)
        items = cpf_decode(data[6:])
        head = struct.pack("<IH", iface, timeout)
        if cmd == CMD_SEND_RR_DATA:
            payload = next((d for t, d in items if t == ITEM_UNCONNECTED_DATA), None)
            if payload is None:
                raise CipError(ST_NOT_ENOUGH_DATA)
            extra: List[Tuple[int, bytes]] = []
            resp = self.process(payload, {"state": state, "session": session, "extra": extra, "items": items})
            out = [(ITEM_NULL_ADDRESS, b""), (ITEM_UNCONNECTED_DATA, resp)] + extra
            return self.encap(cmd, session, ENCAP_OK, ctx, head + cpf_encode(out))
        addr = next((d for t, d in items if t == ITEM_CONNECTED_ADDRESS), None)
        payload = next((d for t, d in items if t == ITEM_CONNECTED_DATA), None)
        if addr is None or payload is None or len(addr) < 4 or len(payload) < 2:
            raise CipError(ST_NOT_ENOUGH_DATA)
        (cid,) = struct.unpack("<I", addr[:4])
        with self.lock:
            conn = self.connections.get(cid)
        if conn is None or conn.session != session:
            return None
        conn.last_rx = time.monotonic()
        seq = payload[:2]
        resp = self.process(payload[2:], {"state": state, "session": session, "extra": [], "items": items})
        out = [(ITEM_CONNECTED_ADDRESS, struct.pack("<I", conn.to_id)), (ITEM_CONNECTED_DATA, seq + resp)]
        return self.encap(cmd, session, ENCAP_OK, ctx, head + cpf_encode(out))

    # ── CIP ───────────────────────────────────────────────────────────────
    def process(self, req: bytes, ctx: Dict[str, Any]) -> bytes:
        if len(req) < 2:
            return cip_reply(0, ST_NOT_ENOUGH_DATA)
        service = req[0]
        try:
            plen = req[1] * 2
            if len(req) < 2 + plen:
                raise CipError(ST_NOT_ENOUGH_DATA)
            segs = parse_epath(req[2:2 + plen])
            data = req[2 + plen:]
            return self.dispatch(service, segs, data, ctx)
        except CipError as e:
            return cip_reply(service, e.status, ext=e.ext)
        except (struct.error, IndexError, ValueError):
            return cip_reply(service, ST_NOT_ENOUGH_DATA)

    @staticmethod
    def _addr(segs):
        cls = inst = attr = None
        for k, v in segs:
            if k == "class" and cls is None:
                cls = v
            elif k == "instance" and inst is None:
                inst = v
            elif k == "attribute" and attr is None:
                attr = v
        return cls, inst, attr

    def dispatch(self, service: int, segs, data: bytes, ctx) -> bytes:
        cls, inst, attr = self._addr(segs)
        if cls is None:
            if any(k == "symbol" for k, _ in segs):
                return self.tag_service(service, segs, data)
            raise CipError(ST_PATH_SEGMENT_ERROR)
        if cls == CLASS_CONNECTION_MANAGER:
            return self.connection_manager(service, inst, data, ctx)
        if cls == CLASS_MESSAGE_ROUTER:
            if service == SVC_MULTIPLE:
                return self.multiple(data, ctx)
            if service == SVC_GET_ATTRIBUTE_SINGLE and attr == 1:
                objs = [1, 2, 4, 6, 0x6B, 0x6C]
                return cip_reply(service, data=struct.pack("<H", len(objs)) + b"".join(struct.pack("<H", o) for o in objs))
            raise CipError(ST_SERVICE_NOT_SUPPORTED)
        if cls == CLASS_IDENTITY:
            return self.identity(service, inst, attr)
        if cls == CLASS_ASSEMBLY:
            return self.assembly(service, inst, attr, data)
        if cls == CLASS_PROGRAM_NAME:
            name = self.program_name.encode("ascii", "replace")
            return cip_reply(service, data=struct.pack("<H", len(name)) + name)
        if cls == CLASS_SYMBOL:
            if service == SVC_GET_INSTANCE_ATTRIBUTE_LIST:
                return self.symbol_list(inst or 0, data)
            if inst:
                return self.tag_by_instance(service, inst, data)
            raise CipError(ST_SERVICE_NOT_SUPPORTED)
        if cls == CLASS_TEMPLATE:
            return self.template(service, inst, data)
        raise CipError(ST_PATH_DESTINATION_UNKNOWN)

    # Identity (Vol 1 5-2)
    def _identity_attrs(self) -> Dict[int, bytes]:
        return {
            1: struct.pack("<H", self.vendor_id),
            2: struct.pack("<H", self.device_type),
            3: struct.pack("<H", self.product_code),
            4: bytes([self.rev_major, self.rev_minor]),
            5: struct.pack("<H", self.status),
            6: struct.pack("<I", self.serial),
            7: shortstring(self.product_name),
        }

    def identity(self, service, inst, attr):
        if inst not in (0, 1):
            raise CipError(ST_OBJECT_DOES_NOT_EXIST)
        attrs = self._identity_attrs()
        if inst == 0:
            if service == SVC_GET_ATTRIBUTE_SINGLE and attr == 1:
                return cip_reply(service, data=struct.pack("<H", 1))
            raise CipError(ST_ATTRIBUTE_NOT_SUPPORTED)
        if service == SVC_GET_ATTRIBUTES_ALL:
            return cip_reply(service, data=b"".join(attrs[i] for i in sorted(attrs)))
        if service == SVC_GET_ATTRIBUTE_SINGLE:
            if attr not in attrs:
                raise CipError(ST_ATTRIBUTE_NOT_SUPPORTED)
            return cip_reply(service, data=attrs[attr])
        raise CipError(ST_SERVICE_NOT_SUPPORTED)

    # Assembly (Vol 1 5-5)
    def assembly(self, service, inst, attr, data):
        if inst not in (100, 101):
            raise CipError(ST_OBJECT_DOES_NOT_EXIST)
        if service == SVC_GET_ATTRIBUTE_SINGLE:
            if attr != 3:
                raise CipError(ST_ATTRIBUTE_NOT_SUPPORTED)
            image = self.input_image() if inst == 100 else bytes(self.out_image)
            return cip_reply(service, data=image)
        if service == SVC_SET_ATTRIBUTE_SINGLE:
            if inst == 100 or attr != 3:
                raise CipError(ST_ATTRIBUTE_NOT_SETTABLE)
            if len(data) < len(self.out_image):
                raise CipError(ST_NOT_ENOUGH_DATA)
            if len(data) > len(self.out_image):
                raise CipError(ST_TOO_MUCH_DATA)
            self.apply_output(data)
            return cip_reply(service)
        raise CipError(ST_SERVICE_NOT_SUPPORTED)

    def apply_output(self, data: bytes):
        """Consumed data (Set_Attribute_Single or implicit O->T) lands in the output
        image and, for tags mapped with assembly_output_tags, in the tag store."""
        with self.lock:
            n = min(len(data), len(self.out_image))
            self.out_image[:n] = data[:n]
            items = list(self.out_layout.items)
        for td, off in items:
            if off + td.size <= len(data):
                v = td.decode(bytes(data[off:off + td.size]))
                td.value = v
                if self.write_cb:
                    self.write_cb(td.source, v)

    # Multiple Service Packet (Vol 1 A-4.7)
    def multiple(self, data: bytes, ctx) -> bytes:
        (count,) = struct.unpack_from("<H", data, 0)
        offs = list(struct.unpack_from(f"<{count}H", data, 2))
        replies = []
        for i, o in enumerate(offs):
            end = offs[i + 1] if i + 1 < count else len(data)
            replies.append(self.process(data[o:end], ctx))
        pos = 2 + 2 * count
        table, body = b"", b""
        for r in replies:
            table += struct.pack("<H", pos + len(body))
            body += r
        return cip_reply(SVC_MULTIPLE, ST_OK, struct.pack("<H", count) + table + body)

    # ── tags ──────────────────────────────────────────────────────────────
    def _tag_from_path(self, segs) -> TagDef:
        names = [v for k, v in segs if k == "symbol"]
        if not names:
            raise CipError(ST_PATH_SEGMENT_ERROR)
        name = names[0]
        if name.lower().startswith("program:"):
            raise CipError(ST_PATH_SEGMENT_ERROR, b"\x00\x00")
        with self.lock:
            td = self.tags.get(name.lower())
        if td is None or len(names) > 1 or any(k == "element" for k, _ in segs):
            raise CipError(ST_PATH_SEGMENT_ERROR, b"\x00\x00")
        return td

    def tag_service(self, service, segs, data) -> bytes:
        return self.tag_op(service, self._tag_from_path(segs), data)

    def tag_by_instance(self, service, inst, data) -> bytes:
        with self.lock:
            td = self.by_instance.get(inst)
        if td is None:
            raise CipError(ST_PATH_DESTINATION_UNKNOWN)
        return self.tag_op(service, td, data)

    def tag_op(self, service: int, td: TagDef, data: bytes) -> bytes:
        with self.lock:
            raw = td.encode()
        if service == SVC_READ_TAG:
            (count,) = struct.unpack_from("<H", data, 0)
            if count != 1:
                raise CipError(ST_GENERAL_ERROR, struct.pack("<H", 0x2105))
            return cip_reply(service, data=td.type_bytes + raw)
        if service == SVC_READ_TAG_FRAGMENTED:
            count, offset = struct.unpack_from("<HI", data, 0)
            if count != 1:
                raise CipError(ST_GENERAL_ERROR, struct.pack("<H", 0x2105))
            if offset > len(raw):
                raise CipError(ST_GENERAL_ERROR, struct.pack("<H", 0x2105))
            chunk = raw[offset:offset + MAX_DATA]
            status = ST_PARTIAL if offset + len(chunk) < len(raw) else ST_OK
            return cip_reply(service, status, td.type_bytes + chunk)
        if service in (SVC_WRITE_TAG, SVC_WRITE_TAG_FRAGMENTED):
            tlen = 4 if td.cip_type == "STRING" else 2
            if len(data) < tlen + 2:
                raise CipError(ST_NOT_ENOUGH_DATA)
            if data[:tlen] != td.type_bytes:
                raise CipError(ST_GENERAL_ERROR, struct.pack("<H", 0x2107))  # data type mismatch
            count = struct.unpack_from("<H", data, tlen)[0]
            body = data[tlen + 2:]
            off = 0
            if service == SVC_WRITE_TAG_FRAGMENTED:
                off = struct.unpack_from("<I", body, 0)[0]
                body = body[4:]
            if count != 1 or off != 0 or len(body) < td.size:
                raise CipError(ST_NOT_ENOUGH_DATA)
            value = td.decode(body[:td.size])
            if self.write_cb is not None and not self.write_cb(td.source, value):
                raise CipError(ST_GENERAL_ERROR, struct.pack("<H", 0x2104))  # privilege violation
            with self.lock:
                td.value = value
            return cip_reply(service)
        raise CipError(ST_SERVICE_NOT_SUPPORTED)

    # Symbol Object tag browse: Get_Instance_Attribute_List
    def symbol_list(self, start: int, data: bytes) -> bytes:
        (n,) = struct.unpack_from("<H", data, 0)
        attrs = list(struct.unpack_from(f"<{n}H", data, 2))
        with self.lock:
            tags = [t for t in self.order if t.instance >= start]
        out, status = b"", ST_OK
        for t in tags:
            rec = struct.pack("<I", t.instance)
            for a in attrs:
                if a == 1:
                    nm = t.name.encode("ascii")
                    rec += struct.pack("<H", len(nm)) + nm
                elif a == 2:
                    rec += struct.pack("<H", t.symbol_type)
                elif a == 3:
                    rec += struct.pack("<I", t.instance * 0x40)
                elif a == 5:
                    rec += struct.pack("<I", t.instance * 0x40)
                elif a == 6:
                    rec += struct.pack("<I", BASE_TAG_BIT)
                elif a == 8:
                    rec += struct.pack("<III", 0, 0, 0)
                elif a == 10:
                    rec += bytes([0x03])  # read and write
                else:
                    raise CipError(ST_ATTRIBUTE_NOT_SUPPORTED)
            if len(out) + len(rec) > MAX_DATA * 2:
                status = ST_PARTIAL
                break
            out += rec
        return cip_reply(SVC_GET_INSTANCE_ATTRIBUTE_LIST, status, out)

    # Template Object: only the built in STRING
    def template(self, service, inst, data) -> bytes:
        if inst != STRUCT_STRING_HANDLE:
            raise CipError(ST_OBJECT_DOES_NOT_EXIST)
        names = b"ASCIISTRING82\x00LEN\x00DATA\x00"
        members = struct.pack("<HHI", 0, T_DINT, 0) + struct.pack("<HHI", STRING_LEN, T_SINT, 4)
        definition = members + names
        def_words = (len(definition) + 21) // 4
        if service == SVC_GET_ATTRIBUTE_LIST:
            (n,) = struct.unpack_from("<H", data, 0)
            ids = struct.unpack_from(f"<{n}H", data, 2)
            vals = {1: struct.pack("<H", STRUCT_STRING_HANDLE), 2: struct.pack("<H", 2),
                    4: struct.pack("<I", def_words), 5: struct.pack("<I", STRING_SIZE)}
            out = struct.pack("<H", n)
            for a in ids:
                if a in vals:
                    out += struct.pack("<HH", a, 0) + vals[a]
                else:
                    out += struct.pack("<HH", a, ST_ATTRIBUTE_NOT_SUPPORTED)
            return cip_reply(service, data=out)
        if service == SVC_READ_TAG:
            offset, count = struct.unpack_from("<IH", data, 0)
            return cip_reply(service, ST_OK, definition[offset:offset + count])
        raise CipError(ST_SERVICE_NOT_SUPPORTED)

    # ── connection manager ────────────────────────────────────────────────
    def connection_manager(self, service, inst, data, ctx) -> bytes:
        if service == SVC_UNCONNECTED_SEND:
            if len(data) < 4:
                raise CipError(ST_NOT_ENOUGH_DATA)
            (msize,) = struct.unpack_from("<H", data, 2)
            embedded = data[4:4 + msize]
            return self.process(embedded, ctx)
        if service in (SVC_FORWARD_OPEN, SVC_LARGE_FORWARD_OPEN):
            return self.forward_open(service, data, ctx)
        if service == SVC_FORWARD_CLOSE:
            return self.forward_close(data, ctx)
        if service == SVC_GET_ATTRIBUTE_SINGLE:
            raise CipError(ST_ATTRIBUTE_NOT_SUPPORTED)
        raise CipError(ST_SERVICE_NOT_SUPPORTED)

    def forward_open(self, service, data, ctx) -> bytes:
        large = service == SVC_LARGE_FORWARD_OPEN
        fmt = "<BBIIHHIB3x" + ("I" + ("I" if large else "H")) * 2 + "BB"
        try:
            (_pri, _tick, ot_id, to_id, cserial, vendor, oserial, mult,
             ot_rpi, ot_par, to_rpi, to_par, trans, psize) = struct.unpack_from(fmt, data, 0)
        except struct.error:
            raise CipError(ST_NOT_ENOUGH_DATA)
        hdr_len = struct.calcsize(fmt)
        path = data[hdr_len:hdr_len + psize * 2]
        key = (cserial, vendor, oserial)
        fail_tail = struct.pack("<HHIBB", cserial, vendor, oserial, 0, 0)
        mask = 0xFFFF if large else 0x01FF
        ot_size, to_size = ot_par & mask, to_par & mask
        klass = trans & 0x0F
        try:
            segs = parse_epath(path)
        except CipError:
            return cip_reply(service, ST_CONNECTION_FAILURE, fail_tail, struct.pack("<H", 0x0315))
        conn = Connection()
        conn.key, conn.klass = key, klass
        conn.session = ctx["session"]
        conn.ot_rpi, conn.to_rpi, conn.timeout_mult = ot_rpi, to_rpi, mult
        conn.ot_size, conn.to_size = ot_size, to_size
        conn.peer_ip = ctx["state"].get("peer_ip", "")
        if klass == 3:
            cls, inst, _ = self._addr(segs)
            if cls != CLASS_MESSAGE_ROUTER:
                return cip_reply(service, ST_CONNECTION_FAILURE, fail_tail, struct.pack("<H", 0x0311))
        elif klass in (0, 1):
            cps = [v for k, v in segs if k == "connpoint"]
            if len(cps) < 2 or not any(k == "class" and v == CLASS_ASSEMBLY for k, v in segs):
                return cip_reply(service, ST_CONNECTION_FAILURE, fail_tail, struct.pack("<H", 0x0117))
            conn.out_cp, conn.in_cp = cps[0], cps[1]
            if conn.out_cp != 101 or conn.in_cp != 100:
                return cip_reply(service, ST_CONNECTION_FAILURE, fail_tail, struct.pack("<H", 0x0117))
            conn.multicast = ((to_par >> 13) & 3) == 1
            port = self.io_port
            for t, d in ctx.get("items", []):
                if t == ITEM_SOCKADDR_TO and len(d) >= 8:
                    port = struct.unpack_from(">H", d, 2)[0] or port
            conn.to_addr = (conn.peer_ip, port)
        else:
            return cip_reply(service, ST_CONNECTION_FAILURE, fail_tail, struct.pack("<H", 0x0103))  # transport not supported
        with self.lock:
            for cid, c in list(self.connections.items()):
                if c.key == key:  # same originator reopening: replace
                    c.alive = False
                    del self.connections[cid]
            conn.ot_id = self.next_conn_id
            self.next_conn_id += 1
            conn.to_id = to_id
            self.connections[conn.ot_id] = conn
        if klass in (0, 1) and conn.multicast:
            group = f"239.192.{(conn.ot_id >> 8) & 0xFF}.{conn.ot_id & 0xFF or 1}"
            conn.to_addr = (group, self.io_port)
            ctx["extra"].append((ITEM_SOCKADDR_TO, sockaddr(group, self.io_port)))
        api_ot = ot_rpi
        api_to = to_rpi
        body = struct.pack("<IIHHIIIBB", conn.ot_id, conn.to_id, cserial, vendor, oserial, api_ot, api_to, 0, 0)
        return cip_reply(service, ST_OK, body)

    def forward_close(self, data, ctx) -> bytes:
        _pri, _tick, cserial, vendor, oserial = struct.unpack_from("<BBHHI", data, 0)
        key = (cserial, vendor, oserial)
        found = False
        with self.lock:
            for cid, c in list(self.connections.items()):
                if c.key == key:
                    c.alive = False
                    del self.connections[cid]
                    found = True
        if not found:
            tail = struct.pack("<HHIBB", cserial, vendor, oserial, 0, 0)
            return cip_reply(SVC_FORWARD_CLOSE, ST_CONNECTION_FAILURE, tail, struct.pack("<H", 0x0107))
        return cip_reply(SVC_FORWARD_CLOSE, ST_OK, struct.pack("<HHIBB", cserial, vendor, oserial, 0, 0))

    # ── implicit I/O ──────────────────────────────────────────────────────
    def io_packet(self, conn: Connection) -> bytes:
        data = self.input_image()
        want = max(0, conn.to_size - 2)
        data = data[:want].ljust(want, b"\x00")
        conn.seq_to = (conn.seq_to + 1) & 0xFFFF
        conn.enc_seq = (conn.enc_seq + 1) & 0xFFFFFFFF
        return cpf_encode([
            (ITEM_SEQUENCED_ADDRESS, struct.pack("<II", conn.to_id, conn.enc_seq)),
            (ITEM_CONNECTED_DATA, struct.pack("<H", conn.seq_to) + data),
        ])

    def io_receive(self, pkt: bytes):
        try:
            items = cpf_decode(pkt)
        except CipError:
            return
        addr = next((d for t, d in items if t == ITEM_SEQUENCED_ADDRESS), None)
        payload = next((d for t, d in items if t == ITEM_CONNECTED_DATA), None)
        if addr is None or payload is None or len(addr) < 4:
            return
        (cid,) = struct.unpack_from("<I", addr, 0)
        with self.lock:
            conn = self.connections.get(cid)
        if conn is None:
            return
        conn.last_rx = time.monotonic()
        body = payload[2:]
        if conn.ot_size > 2 + 4 or len(body) > 4:
            self.apply_output(body[4:])  # skip the 32 bit run/idle header

    def io_connections(self) -> List[Connection]:
        with self.lock:
            return [c for c in self.connections.values() if c.klass in (0, 1) and c.alive]


# ── servers ────────────────────────────────────────────────────────────────
def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class _TCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        device: EnipDevice = self.server.device
        sock = self.request
        sock.settimeout(300)
        state = {"local_ip": sock.getsockname()[0], "peer_ip": self.client_address[0], "sessions": set()}
        try:
            while not state.get("closed"):
                head = _recv_exact(sock, HDR.size)
                if head is None:
                    break
                length = struct.unpack_from("<H", head, 2)[0]
                body = _recv_exact(sock, length) if length else b""
                if body is None:
                    break
                reply = device.handle_encap(head + body, state)
                if reply:
                    sock.sendall(reply)
        except (OSError, socket.timeout):
            pass
        finally:
            for s in state["sessions"]:
                device.drop_session(s)


class _TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _local_ip_for(peer: str) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((peer, 9))
        return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        s.close()


class EtherNetIPPublisher(SimProtocolPublisher):
    """EtherNet/IP server. Config key: publishers.ethernet_ip."""

    config_key = "ethernet_ip"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.device: Optional[EnipDevice] = None
        self._tcp: Optional[_TCPServer] = None
        self._threads: List[threading.Thread] = []
        self._udp: Optional[socket.socket] = None
        self._io: Optional[socket.socket] = None
        self._stop = threading.Event()

    def on_value(self, tag_name, value):
        if self.device is not None:
            self.device.set_tag(tag_name, value)

    def start(self):
        if not self.enabled:
            self.logger.info("EtherNet/IP publisher is disabled")
            return
        host = self.config.get("host", "0.0.0.0")
        port = int(self.config.get("port", 44818))
        io_port = int(self.config.get("io_port", 2222))
        self._stop.clear()
        self.device = EnipDevice(self.config, self.logger, write_cb=self.client_write)
        try:
            self._tcp = _TCPServer((host, port), _TCPHandler)
            self._tcp.device = self.device
            self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._udp.bind((host, port))
            self._io = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._io.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._io.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(self.config.get("multicast_ttl", 1)))
            self._io.bind((host, io_port))
        except OSError as exc:
            self.logger.error(f"EtherNet/IP could not bind {host}:{port} (UDP io {io_port}): {exc}")
            self._close_sockets()
            return
        for target in (self._tcp.serve_forever, self._udp_loop, self._io_rx_loop, self._io_tx_loop):
            t = threading.Thread(target=target, daemon=True, name=f"enip-{target.__name__}")
            t.start()
            self._threads.append(t)
        self.running = True
        self.logger.info(f"EtherNet/IP server on {host}:{port} (TCP and UDP), implicit I/O on UDP {io_port}")

    def stop(self):
        self.running = False
        self._stop.set()
        if self._tcp is not None:
            try:
                self._tcp.shutdown()
            except Exception:
                pass
        self._close_sockets()
        self._threads = []
        self.logger.info("EtherNet/IP publisher stopped")

    def _close_sockets(self):
        for s in (self._udp, self._io):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        if self._tcp is not None:
            try:
                self._tcp.server_close()
            except OSError:
                pass
        self._tcp = self._udp = self._io = None

    def _udp_loop(self):
        sock = self._udp
        while not self._stop.is_set() and sock is not None:
            try:
                pkt, addr = sock.recvfrom(2048)
            except OSError:
                return
            state = {"local_ip": _local_ip_for(addr[0]), "peer_ip": addr[0]}
            try:
                reply = self.device.handle_encap(pkt, state)
            except Exception as exc:
                self.logger.debug(f"EtherNet/IP UDP frame from {addr} dropped: {exc}")
                continue
            if reply:
                try:
                    sock.sendto(reply, addr)
                except OSError:
                    pass

    def _io_rx_loop(self):
        sock = self._io
        while not self._stop.is_set() and sock is not None:
            try:
                pkt, _addr = sock.recvfrom(2048)
            except OSError:
                return
            self.device.io_receive(pkt)

    def _io_tx_loop(self):
        """Producer: every implicit connection gets its T->O packet at its RPI."""
        last: Dict[int, float] = {}
        while not self._stop.is_set():
            now = time.monotonic()
            for c in self.device.io_connections():
                period = max(c.to_rpi / 1_000_000.0, 0.01)
                if c.last_rx and c.ot_rpi and c.timeout_mult is not None:
                    limit = (c.ot_rpi / 1_000_000.0) * (4 << min(c.timeout_mult, 7))
                    if c.ot_size and now - c.last_rx > max(limit, 10.0):
                        c.alive = False
                        with self.device.lock:
                            self.device.connections.pop(c.ot_id, None)
                        continue
                if now - last.get(c.ot_id, 0.0) >= period:
                    last[c.ot_id] = now
                    try:
                        self._io.sendto(self.device.io_packet(c), c.to_addr)
                    except OSError:
                        pass
            self._stop.wait(0.005)
