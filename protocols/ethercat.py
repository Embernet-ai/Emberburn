"""EtherCAT: EmberBurn as one or more EtherCAT slaves (ESC), and as the master.
Config keys: publishers.ethercat (slaves) and publishers.ethercat_master.

EtherCAT is a layer 2 protocol (Ethernet type 0x88A4): a master sends a frame of
datagrams that each slave reads and writes on the fly, and the frame returns to the
master. Here the slave side answers each frame on the same interface (a slave
device on a point to point link returns the frame, with its working counter added),
so it needs a raw socket (NET_RAW) and only reaches the interface's Ethernet segment
(see protocols/rawnet.py).

Slave model: each simulated slave has a 4 KiB register space and a process data RAM
from 0x1000. Registers that matter to a master are live: type, revision, build and
FMMU and SyncManager counts (0x0000), the configured station address (0x0010), the
DL status (0x0110), the AL control and status state machine (0x0120, 0x0130, INIT,
PRE-OP, SAFE-OP, OP, with the error acknowledge and status code on an invalid
request), the SII EEPROM interface (0x0500) serving the identity words (vendor,
product, revision, serial), and the FMMUs (0x0600) and SyncManagers (0x0800), which
the master configures and which then decide how a logical datagram (LRD, LWR, LRW)
maps onto process RAM. The working counter follows the standard (a successful read
or write adds 1; a logical read write, LRW, adds 1 for the read and 2 for the write; the
other read write commands add 3).

Process data: `tags_in` (slave to master, TxPDO) are written into RAM at 0x1100 in
order, and `tags_out` (master to slave, RxPDO) are read from RAM at 0x1000 and
written back to the tag store when the master writes them. A bool is 1 byte, an int
4 bytes little endian, a float REAL32 little endian.

No library is used. The wire format is written against IEC 61158-3-12 and
IEC 61158-4-12 (EtherCAT data link service and protocol: frame header, datagram
header, the command types, the working counter) and the ETG.1000 series and the
ESC hardware data sheet register map for the registers above.

Master role (publishers.ethercat_master): scans the bus (BRD of the ESC type to count
slaves), assigns station addresses, reads each slave's identity from the SII,
configures FMMUs and SyncManagers for the process data, takes each slave through
INIT, PRE-OP, SAFE-OP to OP, then exchanges process data with a cyclic LRW every
`cycle_ms`. It is what a configuration tool does on start, for an analyzer to see.

Not simulated: distributed clocks (ARMW, FRMW return a working counter and no time),
mailbox protocols (CoE, FoE, EoE), SII categories beyond identity, ring topology and
port handling, and the t of a real bus. FPRD of a slave that does not exist returns a
working counter of 0.
"""
import logging
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from protocols.base import SimProtocolPublisher
from protocols.rawnet import RawInterface, mac_bytes

ETHERTYPE_ECAT = 0x88A4
BROADCAST = b"\xff" * 6

CMD_NOP, CMD_APRD, CMD_APWR, CMD_APRW, CMD_FPRD, CMD_FPWR, CMD_FPRW = 0, 1, 2, 3, 4, 5, 6
CMD_BRD, CMD_BWR, CMD_BRW, CMD_LRD, CMD_LWR, CMD_LRW, CMD_ARMW, CMD_FRMW = 7, 8, 9, 10, 11, 12, 13, 14

AL_INIT, AL_PREOP, AL_BOOT, AL_SAFEOP, AL_OP = 1, 2, 3, 4, 8
AL_ERROR = 0x10

REG_SIZE = 0x1000
RAM_SIZE = 0x2000          # process RAM 0x1000 to 0x2FFF
PD_OUT, PD_IN = 0x1000, 0x1100


def encode_frame(dst: bytes, src: bytes, datagrams: List[Dict[str, Any]]) -> bytes:
    body = b""
    for i, d in enumerate(datagrams):
        more = 0x8000 if i < len(datagrams) - 1 else 0
        body += struct.pack("<BBIHH", d["cmd"], d["idx"], d["addr"], (len(d["data"]) & 0x7FF) | more, d.get("irq", 0))
        body += d["data"] + struct.pack("<H", d.get("wkc", 0))
    hdr = struct.pack("<H", (len(body) & 0x7FF) | (1 << 12))
    return dst + src + struct.pack(">H", ETHERTYPE_ECAT) + hdr + body


def decode_frame(frame: bytes) -> Optional[List[Dict[str, Any]]]:
    off = 14
    if frame[12:14] == b"\x81\x00":
        off = 18
    (h,) = struct.unpack_from("<H", frame, off)
    if (h >> 12) != 1:
        return None
    length = h & 0x7FF
    p, end, out = off + 2, off + 2 + length, []
    while p + 10 <= end:
        cmd, idx, addr, lf, irq = struct.unpack_from("<BBIHH", frame, p)
        ln = lf & 0x7FF
        data = bytearray(frame[p + 10:p + 10 + ln])
        (wkc,) = struct.unpack_from("<H", frame, p + 10 + ln)
        out.append({"cmd": cmd, "idx": idx, "addr": addr, "data": data, "wkc": wkc, "irq": irq})
        p += 12 + ln
        if not lf & 0x8000:
            break
    return out


class Slave:
    """One ESC: registers, process RAM, AL state machine, SII, FMMU mapping."""

    def __init__(self, index: int, cfg: Dict[str, Any]):
        self.index = index
        self.mem = bytearray(REG_SIZE + RAM_SIZE)   # registers 0x0000-0x0FFF, then RAM at 0x1000
        self.lock = threading.RLock()
        self.vendor = int(cfg.get("vendor_id", 0x00000ABC))
        self.product = int(cfg.get("product_code", 0x00001234))
        self.revision = int(cfg.get("revision", 1))
        self.serial = int(cfg.get("serial", 0x1000 + index))
        self.mem[0x0000] = 0x11            # ESC type: ET1100
        self.mem[0x0001] = 0x00            # revision
        struct.pack_into("<H", self.mem, 0x0002, 0x0002)  # build
        self.mem[0x0004] = 16              # FMMUs supported
        self.mem[0x0005] = 8               # SyncManagers supported
        self.mem[0x0006] = 8               # RAM size in KiB
        self.mem[0x0007] = 0x0F            # port descriptor: four MII ports
        struct.pack_into("<H", self.mem, 0x0008, 0x000C)  # ESC features
        struct.pack_into("<H", self.mem, 0x0110, 0x0001)  # DL status: link on port 0
        self.mem[0x0130] = AL_INIT
        self.sii = self._build_sii()
        self.on_write_out = None           # callback(bytes) when RxPDO RAM changes

    def _build_sii(self) -> bytearray:
        """SII EEPROM words: 0x08 vendor, 0x0A product, 0x0C revision, 0x0E serial (each 32 bit)."""
        e = bytearray(256)
        struct.pack_into("<IIII", e, 0x10, self.vendor, self.product, self.revision, self.serial)
        return e

    @property
    def station(self) -> int:
        return struct.unpack_from("<H", self.mem, 0x0010)[0]

    @property
    def al_state(self) -> int:
        return self.mem[0x0130] & 0x0F

    # register access -------------------------------------------------------
    def read(self, ado: int, n: int) -> bytes:
        with self.lock:
            return bytes(self.mem[ado:ado + n]) if ado + n <= len(self.mem) else b"\x00" * n

    def write(self, ado: int, data: bytes):
        with self.lock:
            if ado + len(data) > len(self.mem):
                return
            self.mem[ado:ado + len(data)] = data
            end = ado + len(data)
            if ado <= 0x0120 < end:
                self._al_control(self.mem[0x0120])
            if ado <= 0x0502 < end or ado <= 0x0503 < end:
                self._sii_command()
            if ado < PD_OUT + 0x100 and end > PD_OUT and self.on_write_out:
                self.on_write_out(bytes(self.mem[PD_OUT:PD_OUT + 0x100]))

    def _al_control(self, ctl: int):
        want = ctl & 0x0F
        cur = self.al_state
        legal = {AL_INIT: (AL_INIT, AL_PREOP), AL_PREOP: (AL_INIT, AL_PREOP, AL_SAFEOP),
                 AL_SAFEOP: (AL_INIT, AL_PREOP, AL_SAFEOP, AL_OP), AL_OP: (AL_INIT, AL_PREOP, AL_SAFEOP, AL_OP)}
        if ctl & 0x10 and self.mem[0x0130] & AL_ERROR:   # error acknowledge
            self.mem[0x0130] = cur
            struct.pack_into("<H", self.mem, 0x0134, 0)
        if want in legal.get(cur, ()) and (want < AL_SAFEOP or want == cur or self._pd_configured()):
            self.mem[0x0130] = want
            struct.pack_into("<H", self.mem, 0x0134, 0)
        else:
            self.mem[0x0130] = cur | AL_ERROR
            struct.pack_into("<H", self.mem, 0x0134, 0x0011 if want not in legal.get(cur, ()) else 0x001E)  # invalid change / invalid input config

    def _pd_configured(self) -> bool:
        """SAFE-OP and OP need process data mapped: at least one active FMMU, the check a
        real ESC application does on the master's configuration (AL status code 0x001E,
        invalid input configuration, otherwise)."""
        return bool(self.fmmus())

    def _sii_command(self):
        cmd = struct.unpack_from("<H", self.mem, 0x0502)[0]
        if cmd & 0x0100:   # read
            addr = struct.unpack_from("<I", self.mem, 0x0504)[0] * 2
            self.mem[0x0508:0x0510] = bytes(self.sii[addr:addr + 8]).ljust(8, b"\x00")
            struct.pack_into("<H", self.mem, 0x0502, cmd & ~0x8000 & ~0x0100)  # busy cleared, command done
        elif cmd & 0x0200:  # write: accepted, no persistent store
            struct.pack_into("<H", self.mem, 0x0502, cmd & ~0x8000 & ~0x0200)

    # logical addressing ----------------------------------------------------
    def fmmus(self) -> List[Tuple[int, int, int, int, int]]:
        out = []
        for i in range(16):
            b = 0x0600 + 16 * i
            logical, length, _, _, phys, _, typ, active = struct.unpack_from("<IHBBHBBB", self.mem, b)
            if active & 1 and length:
                out.append((logical, length, phys, typ, i))
        return out

    def logical(self, cmd: int, addr: int, data: bytearray) -> int:
        """Process a logical datagram against the FMMUs. Returns the working counter increment."""
        wkc = 0
        n = len(data)
        for logical, length, phys, typ, _ in self.fmmus():
            lo, hi = max(addr, logical), min(addr + n, logical + length)
            if lo >= hi:
                continue
            d0, p0, cnt = lo - addr, phys + (lo - logical), hi - lo
            did_read = did_write = False
            if typ & 1 and cmd in (CMD_LRD, CMD_LRW):          # FMMU type read: slave data to master
                data[d0:d0 + cnt] = self.read(p0, cnt)
                did_read = True
            if typ & 2 and cmd in (CMD_LWR, CMD_LRW):          # FMMU type write: master data to slave
                self.write(p0, bytes(data[d0:d0 + cnt]))
                did_write = True
            # IEC 61158-4-12: LRD and LWR add 1 on success, LRW adds 1 for the read and 2 for the write
            wkc += (1 if did_read else 0) + ((2 if cmd == CMD_LRW else 1) if did_write else 0)
        return wkc

    def set_inputs(self, blob: bytes):
        with self.lock:
            self.mem[PD_IN:PD_IN + len(blob)] = blob


class EtherCATPublisher(SimProtocolPublisher):
    """EtherCAT slave(s). Config key: publishers.ethercat."""

    config_key = "ethercat"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        n = max(1, min(8, int(config.get("slave_count", 1))))
        self.slaves = [Slave(i, config) for i in range(n)]
        self.tags_in: List[str] = [str(t) for t in (config.get("tags_in") or [])]
        self.tags_out: List[str] = [str(t) for t in (config.get("tags_out") or [])]
        self.out_types: Dict[str, Any] = {}
        self.iface: Optional[RawInterface] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        for s in self.slaves:
            s.on_write_out = self._outputs

    def start(self):
        if not self.enabled:
            return
        try:
            self.iface = RawInterface(self.config.get("interface"), [ETHERTYPE_ECAT])
        except OSError as exc:
            self.logger.error(f"EtherCAT needs a raw socket (NET_RAW) on an interface: {exc}")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ethercat")
        self._thread.start()
        self.running = True
        self.logger.info(f"EtherCAT: {len(self.slaves)} slave(s) on {self.iface.name}")

    def stop(self):
        self.running = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self.iface is not None:
            self.iface.close()
        self.logger.info("EtherCAT publisher stopped")

    # process data ----------------------------------------------------------
    @staticmethod
    def _pack(v: Any) -> bytes:
        if isinstance(v, bool):
            return b"\x01" if v else b"\x00"
        if isinstance(v, float):
            return struct.pack("<f", v)
        if isinstance(v, int):
            return struct.pack("<i", max(-2**31, min(2**31 - 1, v)))
        return b""

    def on_value(self, tag, value):
        if tag in self.tags_in:
            blob = b"".join(self._pack(self.values.get(t, 0)) for t in self.tags_in)
            for s in self.slaves:
                s.set_inputs(blob)
        if tag in self.tags_out and tag not in self.out_types:
            self.out_types[tag] = value

    def _outputs(self, ram: bytes):
        """The master wrote RxPDO RAM: decode it into the tag store."""
        p = 0
        for t in self.tags_out:
            proto = self.out_types.get(t)
            if proto is None:
                continue
            size = 1 if isinstance(proto, bool) else 4
            raw = ram[p:p + size]
            p += size
            if len(raw) < size:
                break
            v = bool(raw[0]) if isinstance(proto, bool) else (struct.unpack("<f", raw)[0] if isinstance(proto, float) else struct.unpack("<i", raw)[0])
            if v != self.values.get(t):
                self.client_write(t, v)

    # frames ----------------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            f = self.iface.recv()
            if f is None:
                continue
            try:
                dgs = decode_frame(f)
                if not dgs:
                    continue
                for d in dgs:
                    self._datagram(d)
                self.iface.send(encode_frame(f[6:12], self.iface.mac, dgs))
            except Exception as exc:
                self.logger.debug(f"EtherCAT frame dropped: {exc}")

    def _datagram(self, d: Dict[str, Any]):
        cmd, data = d["cmd"], d["data"]
        n = len(data)
        adp, ado = d["addr"] & 0xFFFF, d["addr"] >> 16   # physical addressing: ADP low 16 bits, ADO high 16 bits
        if cmd in (CMD_LRD, CMD_LWR, CMD_LRW):
            for s in self.slaves:
                d["wkc"] += s.logical(cmd, d["addr"], data)
            return
        for s in self.slaves:
            hit = False
            if cmd in (CMD_APRD, CMD_APWR, CMD_APRW, CMD_ARMW):
                hit = adp == 0
                adp = (adp + 1) & 0xFFFF                 # every slave increments the auto-increment address
            elif cmd in (CMD_FPRD, CMD_FPWR, CMD_FPRW, CMD_FRMW):
                hit = s.station == adp and s.station != 0
            elif cmd in (CMD_BRD, CMD_BWR, CMD_BRW):
                hit = True
            if not hit:
                continue
            reads = cmd in (CMD_APRD, CMD_APRW, CMD_FPRD, CMD_FPRW, CMD_BRD, CMD_BRW)
            writes = cmd in (CMD_APWR, CMD_APRW, CMD_FPWR, CMD_FPRW, CMD_BWR, CMD_BRW)
            if cmd in (CMD_ARMW, CMD_FRMW):
                d["wkc"] += 1
                continue
            if reads:
                cur = s.read(ado, n)
                if cmd in (CMD_BRD, CMD_BRW):
                    data[:] = bytes(a | b for a, b in zip(data, cur))   # a broadcast read ORs the slaves' data
                else:
                    data[:] = cur
            if writes:
                s.write(ado, bytes(data))
            # a read or a write adds 1, a read and write command (APRW, FPRW, BRW) adds 3
            d["wkc"] += 3 if (reads and writes) else 1
        d["addr"] = (ado << 16) | adp


class EtherCATMasterPublisher(SimProtocolPublisher):
    """EtherCAT master. Config key: publishers.ethercat_master.

    Brings the bus up (scan, station addresses, SII identity, FMMU and SyncManager
    configuration, INIT to OP) and then exchanges process data with a cyclic LRW.
    `tags_out` are sent to the slaves, `tags_in` are read from them into `inputs`.
    Every slave gets the same process data layout as the EtherCAT slave simulator."""

    config_key = "ethercat_master"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.iface: Optional[RawInterface] = None
        self.tags_out: List[str] = [str(t) for t in (config.get("tags_out") or [])]
        self.in_size = int(config.get("input_bytes", 8))
        self.out_size = int(config.get("output_bytes", 8))
        self.slaves_found = 0
        self.identities: List[Tuple[int, int]] = []
        self.al_states: List[int] = []
        self.inputs: bytes = b""
        self.wkc = 0
        self.cycles = 0
        self._idx = 0
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self):
        if not self.enabled:
            return
        try:
            self.iface = RawInterface(self.config.get("interface"), [ETHERTYPE_ECAT])
        except OSError as exc:
            self.logger.error(f"EtherCAT master needs a raw socket (NET_RAW): {exc}")
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="ethercat-master")
        self._thread.start()

    def stop(self):
        self.running = False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self.iface is not None:
            self.iface.close()

    def _xchg(self, cmd: int, addr: int, data: bytes) -> Optional[Dict[str, Any]]:
        self._idx = (self._idx + 1) & 0xFF
        dst = mac_bytes(str(self.config.get("dest_mac", "ff:ff:ff:ff:ff:ff")))
        self.iface.send(encode_frame(dst, self.iface.mac, [{"cmd": cmd, "idx": self._idx, "addr": addr, "data": data}]))
        end = time.time() + 1.0
        while time.time() < end:
            f = self.iface.recv()
            if f is None:
                continue
            dgs = decode_frame(f)
            if dgs and dgs[0]["idx"] == self._idx and dgs[0]["cmd"] == cmd:
                return dgs[0]
        return None

    def _al(self, state: int, n: int) -> bool:
        for i in range(n):
            self._xchg(CMD_FPWR, (0x0120 << 16) | (0x1001 + i), struct.pack("<H", state))
        time.sleep(0.02)
        ok = True
        self.al_states = []
        for i in range(n):
            r = self._xchg(CMD_FPRD, (0x0130 << 16) | (0x1001 + i), b"\x00\x00")
            st = r["data"][0] if r and r["wkc"] else 0
            self.al_states.append(st)
            ok = ok and st == state
        return ok

    def _bring_up(self) -> int:
        r = self._xchg(CMD_BRD, 0x0000 << 16, b"\x00")           # ESC type of every slave, WKC = slaves
        n = r["wkc"] if r else 0
        if not n:
            raise ConnectionError("no EtherCAT slave answered the bus scan")
        self.slaves_found = n
        for i in range(n):                                          # auto increment address -i, then a fixed station address
            self._xchg(CMD_APWR, (0x0010 << 16) | ((0x10000 - i) & 0xFFFF), struct.pack("<H", 0x1001 + i))
        self.identities = []
        for i in range(n):
            st = 0x1001 + i
            self._xchg(CMD_FPWR, (0x0504 << 16) | st, struct.pack("<I", 0x08))                  # SII word address 0x08
            self._xchg(CMD_FPWR, (0x0502 << 16) | st, struct.pack("<H", 0x0100))                # read command
            d = self._xchg(CMD_FPRD, (0x0508 << 16) | st, bytes(8))
            self.identities.append(struct.unpack_from("<II", d["data"], 0) if d and d["wkc"] else (0, 0))
        self._al(AL_INIT, n)
        for i in range(n):
            st = 0x1001 + i
            # FMMU0 outputs (write type), FMMU1 inputs (read type), logical 0 and 0x100
            fm0 = struct.pack("<IHBBHBBBBBB", 0x0000, self.out_size, 0, 7, PD_OUT, 0, 2, 1, 0, 0, 0)[:16].ljust(16, b"\x00")
            fm1 = struct.pack("<IHBBHBBBBBB", 0x0100 + i * self.in_size, self.in_size, 0, 7, PD_IN, 0, 1, 1, 0, 0, 0)[:16].ljust(16, b"\x00")
            self._xchg(CMD_FPWR, (0x0600 << 16) | st, fm0 + fm1)
            sm2 = struct.pack("<HHBBBB", PD_OUT, self.out_size, 0x64, 0, 1, 0)                  # SM2 outputs
            sm3 = struct.pack("<HHBBBB", PD_IN, self.in_size, 0x20, 0, 1, 0)                    # SM3 inputs
            self._xchg(CMD_FPWR, (0x0810 << 16) | st, sm2 + sm3)
        if not self._al(AL_PREOP, n) or not self._al(AL_SAFEOP, n) or not self._al(AL_OP, n):
            raise ConnectionError(f"slaves did not reach OP (AL states {self.al_states})")
        self.logger.info(f"EtherCAT master: {n} slave(s) in OP, identities {self.identities}")
        return n

    def _run(self):
        delay = 2.0
        cycle = float(self.config.get("cycle_ms", 10)) / 1000.0
        while not self._stop.is_set():
            try:
                n = self._bring_up()
                self.unavailable_reason = None
                delay = 2.0
                while not self._stop.is_set():
                    with self.lock:
                        out = b"".join(EtherCATPublisher._pack(self.values.get(t, 0)) for t in self.tags_out)
                    out = out[:self.out_size].ljust(self.out_size, b"\x00")
                    total = self.out_size  # logical 0.. outputs, 0x100.. inputs of slave 0, then the rest
                    buf = out.ljust(0x100, b"\x00") + bytes(self.in_size * n)
                    r = self._xchg(CMD_LRW, 0, buf)
                    if r is None:
                        raise ConnectionError("no answer to the cyclic LRW")
                    self.wkc = r["wkc"]
                    self.inputs = bytes(r["data"][0x100:0x100 + self.in_size * n])
                    self.cycles += 1
                    self._stop.wait(cycle)
            except Exception as exc:
                self.unavailable_reason = str(exc)
                self.logger.warning(f"EtherCAT master: {exc}")
                self._stop.wait(delay)
                delay = min(delay * 2, 60.0)
