#!/usr/bin/env python3
"""EtherCAT slave and master over a real Ethernet link.

Needs root (or CAP_NET_RAW and CAP_NET_ADMIN): a veth pair, the slaves on one end,
and a hand written master on the other that builds and parses frames itself from
IEC 61158-4-12 (it does not import the simulator's codec). It scans the bus,
assigns station addresses, reads the identity through the SII, configures FMMUs and
SyncManagers, walks the AL state machine to OP, exchanges process data by LRW,
and checks the working counters and the error paths. EmberBurn's own master role is
then run against the slaves. tshark decodes the same traffic in the release evidence.

    sudo python test_ethercat.py
"""
import os
import socket
import struct
import subprocess
import time

from protocols.ethercat import EtherCATMasterPublisher, EtherCATPublisher

A, B = "ebe0", "ebe1"


def sh(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def make_veth():
    subprocess.run(["ip", "link", "del", A], capture_output=True)
    sh("ip", "link", "add", A, "type", "veth", "peer", "name", B)
    for n in (A, B):
        sh("ip", "link", "set", n, "up")
    time.sleep(1)


class Master:
    def __init__(self, ifname):
        self.s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
        self.s.bind((ifname, 0))
        self.s.settimeout(0.3)
        self.mac = bytes.fromhex(open(f"/sys/class/net/{ifname}/address").read().strip().replace(":", ""))
        self.idx = 0

    def xchg(self, cmd, adp, ado, data):
        self.idx = (self.idx + 1) & 0xFF
        dg = struct.pack("<BBHHHH", cmd, self.idx, adp & 0xFFFF, ado, len(data), 0) + bytes(data) + b"\x00\x00"
        frame = b"\xff" * 6 + self.mac + b"\x88\xa4" + struct.pack("<H", (len(dg) & 0x7FF) | 0x1000) + dg
        self.s.send(frame.ljust(60, b"\x00"))
        end = time.time() + 2
        while time.time() < end:
            try:
                f, addr = self.s.recvfrom(4096)
            except socket.timeout:
                continue
            if addr[2] == socket.PACKET_OUTGOING or f[12:14] != b"\x88\xa4":
                continue
            c, i, a, ado2, lf, irq = struct.unpack_from("<BBHHHH", f, 16)
            if i != self.idx:
                continue
            n = lf & 0x7FF
            return {"cmd": c, "adp": a, "ado": ado2, "data": f[26:26 + n], "wkc": struct.unpack_from("<H", f, 26 + n)[0], "src": f[6:12]}
        return None


def check_slave():
    pub = EtherCATPublisher({"enabled": True, "interface": A, "slave_count": 2, "vendor_id": 0xABC, "product_code": 0x1234,
                             "tags_in": ["Plant/Temp", "Plant/Run"], "tags_out": ["Plant/Setpoint"]})
    pub.start()
    assert pub.running
    writes = []
    pub.set_write_callback(lambda n, v: writes.append((n, v)) or True)
    pub.publish("Plant/Temp", 21.5)
    pub.publish("Plant/Run", True)
    pub.publish("Plant/Setpoint", 10.0)
    m = Master(B)
    try:
        # bus scan: BRD of the ESC type, working counter = number of slaves
        r = m.xchg(7, 0, 0x0000, b"\x00")
        assert r and r["wkc"] == 2 and r["data"] == b"\x11", r
        # auto increment addressing: ADP 0 is the first slave, 0xFFFF the second; assign station addresses
        for i in range(2):
            r = m.xchg(2, (0x10000 - i), 0x0010, struct.pack("<H", 0x1001 + i))
            assert r["wkc"] == 1, r
        r = m.xchg(4, 0x1002, 0x0010, b"\x00\x00")
        assert struct.unpack("<H", r["data"])[0] == 0x1002 and r["wkc"] == 1
        # a station address nobody has: working counter 0
        r = m.xchg(4, 0x7777, 0x0010, b"\x00\x00")
        assert r["wkc"] == 0, r
        # identity through the SII: word address 8, vendor then product
        m.xchg(5, 0x1001, 0x0504, struct.pack("<I", 8))
        m.xchg(5, 0x1001, 0x0502, struct.pack("<H", 0x0100))
        r = m.xchg(4, 0x1001, 0x0508, bytes(8))
        assert struct.unpack("<II", r["data"]) == (0xABC, 0x1234), r
        # AL state machine: INIT to OP directly is refused with the error bit and code 0x0011
        m.xchg(5, 0x1001, 0x0120, struct.pack("<H", 8))
        r = m.xchg(4, 0x1001, 0x0130, b"\x00\x00")
        assert r["data"][0] == (1 | 0x10), r
        assert struct.unpack("<H", m.xchg(4, 0x1001, 0x0134, b"\x00\x00")["data"])[0] == 0x0011
        m.xchg(5, 0x1001, 0x0120, struct.pack("<H", 0x11))      # acknowledge, stay INIT
        # configure process data for both slaves, then INIT -> PRE-OP -> SAFE-OP -> OP
        for st in (0x1001, 0x1002):
            fm = struct.pack("<IHBBHBBB", 0, 4, 0, 7, 0x1000, 0, 2, 1).ljust(16, b"\x00")     # outputs, write type
            fm += struct.pack("<IHBBHBBB", 0x100 + (st - 0x1001) * 8, 8, 0, 7, 0x1100, 0, 1, 1).ljust(16, b"\x00")  # inputs, read type
            assert m.xchg(5, st, 0x0600, fm)["wkc"] == 1
            for state in (2, 4, 8):
                m.xchg(5, st, 0x0120, struct.pack("<H", state))
                assert m.xchg(4, st, 0x0130, b"\x00\x00")["data"][0] == state, (st, state)
        # cyclic LRW: outputs at logical 0 (Setpoint REAL32 = 55.5), inputs at 0x100 (Temp REAL32, Run BYTE)
        buf = struct.pack("<f", 55.5).ljust(0x100, b"\x00") + bytes(16)
        r = m.xchg(12, 0, 0, buf)
        assert r["wkc"] == 6, r["wkc"]                       # (1 read + 2 write) x 2 slaves
        assert struct.unpack_from("<f", r["data"], 0x100)[0] == 21.5 and r["data"][0x104] == 1, r["data"][0x100:0x108].hex()
        deadline = time.time() + 2
        while ("Plant/Setpoint", 55.5) not in writes and time.time() < deadline:
            time.sleep(0.05)
        assert ("Plant/Setpoint", 55.5) in writes, writes
        # a live change shows on the next cycle
        pub.publish("Plant/Temp", 30.0)
        r = m.xchg(12, 0, 0, buf)
        assert struct.unpack_from("<f", r["data"], 0x100)[0] == 30.0
        # logical read only
        r = m.xchg(10, 0x100, 0, bytes(8))
        assert r["wkc"] == 1 and struct.unpack_from("<f", r["data"], 0)[0] == 30.0, r
    finally:
        m.s.close()
        pub.stop()
    return True


def check_master_role():
    slave = EtherCATPublisher({"enabled": True, "interface": A, "slave_count": 2, "tags_in": ["Plant/Temp"], "tags_out": ["Plant/Setpoint"]})
    slave.start()
    slave.publish("Plant/Temp", 18.25)
    slave.publish("Plant/Setpoint", 0.0)
    writes = []
    slave.set_write_callback(lambda n, v: writes.append((n, v)) or True)
    master = EtherCATMasterPublisher({"enabled": True, "interface": B, "tags_out": ["Plant/Setpoint"], "input_bytes": 4,
                                      "output_bytes": 4, "cycle_ms": 20})
    master.start()
    master.publish("Plant/Setpoint", 12.5)
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not (master.cycles > 3 and master.inputs):
            time.sleep(0.2)
        assert master.slaves_found == 2 and master.al_states == [8, 8], (master.slaves_found, master.al_states, master.unavailable_reason)
        assert master.identities == [(0xABC, 0x1234)] * 2 or all(i[0] for i in master.identities), master.identities
        assert master.wkc == 6, master.wkc
        assert struct.unpack_from("<f", master.inputs, 0)[0] == 18.25, master.inputs.hex()
        deadline = time.time() + 3
        while ("Plant/Setpoint", 12.5) not in writes and time.time() < deadline:
            time.sleep(0.05)
        assert ("Plant/Setpoint", 12.5) in writes, writes
    finally:
        master.stop()
        slave.stop()
    return True


def main():
    if os.geteuid() != 0:
        print("test_ethercat.py needs root (veth and raw sockets)")
        return 1
    make_veth()
    results = []
    try:
        for name, fn in (("slave: scan, SII, AL states, FMMU, LRW, errors", check_slave), ("master role", check_master_role)):
            try:
                results.append((name, bool(fn()), ""))
            except Exception:
                import traceback
                results.append((name, False, traceback.format_exc()))
    finally:
        subprocess.run(["ip", "link", "del", A], capture_output=True)
    for name, ok, detail in results:
        print(("PASS " if ok else "FAIL ") + name)
        if detail:
            print(detail)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)}")
    return 0 if passed == len(results) else 1


def test_ethercat():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
