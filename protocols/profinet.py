"""PROFINET at layer 2: a DCP responder and RT cyclic output. Config key:
publishers.profinet.

PROFINET IO runs on Ethernet type 0x8892. This module is an IO device's layer 2
side, so an engineering tool, a controller or a network scanner finds EmberBurn and
sees process data:

  * DCP (Discovery and basic Configuration Protocol): answers Identify requests
    (multicast 01:0E:CF:00:00:00, FrameID 0xFEFE, filters All and NameOfStation)
    with the device's name, vendor, device and vendor IDs, role, options and IP
    parameters; answers Get for the same blocks; accepts Set of NameOfStation and IP
    (and the Control Signal request, which a tool uses to flash a device) and
    confirms. A Set of the name takes effect in later Identify answers.
  * RT cyclic: a Class 1 RT frame (FrameID 0xC000 and up, VLAN priority 6) with the
    configured tags as IO data followed by the cycle counter, data status and
    transfer status, sent to `controller_mac` every `cycle_ms`.

No library is used. The wire format is written against IEC 61158-6-10 (PROFINET IO
protocol: DCP clause 4.3, RT frame and APDU status, cycle counter in 1/32 ms units)
and the PROFIBUS and PROFINET International document "PROFINET IO Specification".

Not simulated here: the IO connection manager (DCE/RPC Connect, Control and Release
on UDP 34964, which sets up an application relationship), acyclic Read and Write
records, alarms, LLDP, MRP, and IRT. The RT frame is therefore a producer without
an AR, which a passive analyzer or IDS sees as device traffic; a controller will not
cyclically exchange data with it.
"""
import logging
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from protocols.base import SimProtocolPublisher
from protocols.rawnet import RawInterface, mac_bytes, mac_str

ETHERTYPE_PN = 0x8892
DCP_MULTICAST = "01:0e:cf:00:00:00"
FRAME_IDENTIFY_REQ, FRAME_IDENTIFY_RES, FRAME_GET_SET, FRAME_HELLO = 0xFEFE, 0xFEFF, 0xFEFD, 0xFEFC
SVC_GET, SVC_SET, SVC_IDENTIFY, SVC_HELLO = 3, 4, 5, 6
TYPE_REQUEST, TYPE_RESPONSE_OK, TYPE_RESPONSE_UNSUPPORTED = 0, 1, 5

# options and suboptions (IEC 61158-6-10 table 4-x)
OPT_IP, OPT_DEVICE, OPT_CONTROL, OPT_ALL = 1, 2, 5, 0xFF
IP_MAC, IP_PARAM = 1, 2
DEV_VENDOR, DEV_NAME, DEV_ID, DEV_ROLE, DEV_OPTIONS, DEV_ALIAS, DEV_INSTANCE = 1, 2, 3, 4, 5, 6, 7
CTL_START, CTL_STOP, CTL_SIGNAL, CTL_RESPONSE = 1, 2, 3, 4


def pad_even(b: bytes) -> bytes:
    return b + b"\x00" if len(b) & 1 else b


def block(option: int, sub: int, data: bytes) -> bytes:
    return pad_even(struct.pack(">BBH", option, sub, len(data)) + data)


def parse_blocks(data: bytes) -> List[Tuple[int, int, bytes]]:
    out, p = [], 0
    while p + 4 <= len(data):
        o, s, ln = struct.unpack_from(">BBH", data, p)
        out.append((o, s, data[p + 4:p + 4 + ln]))
        p += 4 + ln + (ln & 1)
    return out


def dcp_frame(dst: bytes, src: bytes, frame_id: int, service: int, stype: int, xid: int, blocks: bytes,
              vlan: Optional[Tuple[int, int]] = None, delay: int = 0) -> bytes:
    hdr = dst + src
    if vlan is not None:
        hdr += struct.pack(">HH", 0x8100, (vlan[0] << 13) | vlan[1])
    hdr += struct.pack(">HH", ETHERTYPE_PN, frame_id)
    return hdr + struct.pack(">BBIHH", service, stype, xid, delay, len(blocks)) + blocks


class ProfinetPublisher(SimProtocolPublisher):
    """PROFINET DCP responder and RT cyclic producer."""

    config_key = "profinet"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        c = config
        self.station_name = str(c.get("station_name", "emberburn")).lower()
        self.vendor_name = str(c.get("vendor_name", "EmberBurn"))
        self.vendor_id = int(c.get("vendor_id", 0x0000))
        self.device_id = int(c.get("device_id", 0x0001))
        self.ip = tuple(int(x) for x in str(c.get("ip", "0.0.0.0")).split("."))
        self.mask = tuple(int(x) for x in str(c.get("netmask", "0.0.0.0")).split("."))
        self.gateway = tuple(int(x) for x in str(c.get("gateway", "0.0.0.0")).split("."))
        self.tags: List[str] = [str(t) for t in (c.get("tags") or [])]
        self.iface: Optional[RawInterface] = None
        self.cycle = 0
        self.signalled = 0
        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()
        self._t0 = time.monotonic()

    # lifecycle -------------------------------------------------------------
    def start(self):
        if not self.enabled:
            return
        try:
            self.iface = RawInterface(self.config.get("interface"), [ETHERTYPE_PN])
            self.iface.join(DCP_MULTICAST)
        except OSError as exc:
            self.logger.error(f"PROFINET needs a raw socket (NET_RAW) on an interface: {exc}")
            return
        self._stop.clear()
        loops = [self._dcp_loop]
        if self.config.get("controller_mac") and self.tags:
            loops.append(self._rt_loop)
        for fn in loops:
            t = threading.Thread(target=fn, daemon=True, name=f"pn-{fn.__name__}")
            t.start()
            self._threads.append(t)
        self.running = True
        self.logger.info(f"PROFINET device '{self.station_name}' on {self.iface.name} (DCP{', RT' if len(loops) > 1 else ''})")

    def stop(self):
        self.running = False
        self._stop.set()
        for t in self._threads:
            t.join(timeout=3)
        self._threads = []
        if self.iface is not None:
            self.iface.close()
        self.logger.info("PROFINET publisher stopped")

    # DCP -------------------------------------------------------------------
    def _device_blocks(self) -> Dict[Tuple[int, int], bytes]:
        info = b"\x00\x00"
        return {
            (OPT_DEVICE, DEV_VENDOR): block(OPT_DEVICE, DEV_VENDOR, info + self.vendor_name.encode()),
            (OPT_DEVICE, DEV_NAME): block(OPT_DEVICE, DEV_NAME, info + self.station_name.encode()),
            (OPT_DEVICE, DEV_ID): block(OPT_DEVICE, DEV_ID, info + struct.pack(">HH", self.vendor_id, self.device_id)),
            (OPT_DEVICE, DEV_ROLE): block(OPT_DEVICE, DEV_ROLE, info + b"\x01\x00"),  # IO-Device
            (OPT_DEVICE, DEV_OPTIONS): block(OPT_DEVICE, DEV_OPTIONS, bytes([OPT_IP, IP_PARAM, OPT_IP, IP_MAC, OPT_DEVICE, DEV_VENDOR,
                                                                              OPT_DEVICE, DEV_NAME, OPT_DEVICE, DEV_ID, OPT_DEVICE, DEV_ROLE,
                                                                              OPT_DEVICE, DEV_OPTIONS])),
            (OPT_IP, IP_MAC): block(OPT_IP, IP_MAC, info + self.iface.mac),
            (OPT_IP, IP_PARAM): block(OPT_IP, IP_PARAM, (b"\x00\x01" if any(self.ip) else b"\x00\x00")
                                      + bytes(self.ip) + bytes(self.mask) + bytes(self.gateway)),
        }

    def _dcp_loop(self):
        while not self._stop.is_set():
            f = self.iface.recv()
            if f is None:
                continue
            try:
                self._dcp(f)
            except Exception as exc:
                self.logger.debug(f"PROFINET frame dropped: {exc}")

    def _dcp(self, f: bytes):
        off = 12
        if f[12:14] == b"\x81\x00":
            off = 16
        et, frame_id = struct.unpack_from(">HH", f, off)
        if et != ETHERTYPE_PN or frame_id not in (FRAME_IDENTIFY_REQ, FRAME_GET_SET):
            return
        service, stype, xid, delay, length = struct.unpack_from(">BBIHH", f, off + 4)
        if stype != TYPE_REQUEST:
            return
        src = f[6:12]
        data = f[off + 14:off + 14 + length]
        req = parse_blocks(data)
        if service == SVC_IDENTIFY and frame_id == FRAME_IDENTIFY_REQ:
            if not self._identify_match(req):
                return
            dev = self._device_blocks()
            order = [(OPT_IP, IP_MAC), (OPT_IP, IP_PARAM), (OPT_DEVICE, DEV_VENDOR), (OPT_DEVICE, DEV_NAME),
                     (OPT_DEVICE, DEV_ID), (OPT_DEVICE, DEV_ROLE), (OPT_DEVICE, DEV_OPTIONS)]
            body = b"".join(dev[k] for k in order)
            # the standard spreads answers by the ResponseDelayFactor to avoid a storm;
            # a short fixed spread is enough for one device
            time.sleep(min(0.01 * (delay & 0x7FFF), 0.2) if delay else 0)
            self.iface.send(dcp_frame(src, self.iface.mac, FRAME_IDENTIFY_RES, SVC_IDENTIFY, TYPE_RESPONSE_OK, xid, body))
        elif service == SVC_GET and frame_id == FRAME_GET_SET:
            dev = self._device_blocks()
            out = b""
            for o, s, _ in req:
                if (o, s) in dev:
                    out += dev[(o, s)]
            if not out:
                out = block(OPT_CONTROL, CTL_RESPONSE, bytes([req[0][0], req[0][1], 2])) if req else b""  # option unsupported
            self.iface.send(dcp_frame(src, self.iface.mac, FRAME_GET_SET, SVC_GET, TYPE_RESPONSE_OK, xid, out))
        elif service == SVC_SET and frame_id == FRAME_GET_SET:
            out = b""
            for o, s, v in req:
                err = 0
                if (o, s) == (OPT_DEVICE, DEV_NAME) and len(v) >= 2:
                    self.station_name = v[2:].decode("ascii", "replace").lower()
                elif (o, s) == (OPT_IP, IP_PARAM) and len(v) >= 14:
                    self.ip, self.mask, self.gateway = tuple(v[2:6]), tuple(v[6:10]), tuple(v[10:14])
                elif (o, s) == (OPT_CONTROL, CTL_SIGNAL):
                    self.signalled += 1
                elif (o, s) in ((OPT_CONTROL, CTL_START), (OPT_CONTROL, CTL_STOP)):
                    pass
                else:
                    err = 2  # option not supported
                out += block(OPT_CONTROL, CTL_RESPONSE, bytes([o, s, err]))
            self.iface.send(dcp_frame(src, self.iface.mac, FRAME_GET_SET, SVC_SET, TYPE_RESPONSE_OK, xid, out))

    def _identify_match(self, req: List[Tuple[int, int, bytes]]) -> bool:
        if not req:
            return True
        for o, s, v in req:
            if (o, s) == (OPT_ALL, 0xFF):
                continue
            if (o, s) == (OPT_DEVICE, DEV_NAME):
                if v.decode("ascii", "replace").lower() != self.station_name:
                    return False
            elif (o, s) == (OPT_DEVICE, DEV_ID) and len(v) >= 4:
                if struct.unpack(">HH", v[:4]) != (self.vendor_id, self.device_id):
                    return False
            elif (o, s) == (OPT_DEVICE, DEV_VENDOR):
                if v.decode("ascii", "replace") != self.vendor_name:
                    return False
        return True

    # RT cyclic -------------------------------------------------------------
    def _io_data(self) -> bytes:
        out = b""
        with self.lock:
            vals = [self.values.get(t, 0) for t in self.tags]
        for v in vals:
            if isinstance(v, bool):
                out += b"\xff" if v else b"\x00"
            elif isinstance(v, float):
                out += struct.pack(">f", v)
            elif isinstance(v, int):
                out += struct.pack(">i", max(-2**31, min(2**31 - 1, v)))
            else:
                out += str(v).encode("latin-1", "replace")[:16].ljust(16, b"\x00")
            out += b"\x80"  # IOPS good for this submodule's data
        return out

    def _rt_frame(self) -> bytes:
        data = self._io_data()
        data = data.ljust(40, b"\x00")  # C_SDU is at least 40 bytes
        cycle = int((time.monotonic() - self._t0) * 32000) & 0xFFFF  # 31.25 us units
        apdu = struct.pack(">HBB", cycle, 0x35, 0x00)  # cycle counter, data status (primary, valid, run, no problem), transfer status
        vlan = struct.pack(">HH", 0x8100, 6 << 13)     # priority 6 for RT class 1
        return (mac_bytes(str(self.config["controller_mac"])) + self.iface.mac + vlan
                + struct.pack(">HH", ETHERTYPE_PN, int(self.config.get("frame_id", 0xC000))) + data + apdu)

    def _rt_loop(self):
        period = float(self.config.get("cycle_ms", 32)) / 1000.0
        nxt = time.monotonic()
        while not self._stop.is_set():
            try:
                self.iface.send(self._rt_frame())
                self.cycle += 1
            except OSError as exc:
                self.logger.warning(f"PROFINET RT send failed: {exc}")
            nxt += period
            self._stop.wait(max(0.0, nxt - time.monotonic()))
