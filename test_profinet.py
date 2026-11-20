#!/usr/bin/env python3
"""PROFINET DCP and RT over a real Ethernet link.

Needs root (or CAP_NET_RAW and CAP_NET_ADMIN): a veth pair, the device on one end,
and a hand written DCP client on the other that does not import the simulator's
codec. Frames are built and parsed here from IEC 61158-6-10: Identify with the All
and NameOfStation filters, Get, Set of the name, IP and Signal, and the RT cyclic
frame (FrameID, IO data, cycle counter, data status). tshark decodes the same
traffic in the release evidence.

    sudo python test_profinet.py
"""
import os
import socket
import struct
import subprocess
import time

from protocols.profinet import ProfinetPublisher

A, B = "ebp0", "ebp1"
MCAST = bytes.fromhex("010ecf000000")


def sh(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def make_veth():
    subprocess.run(["ip", "link", "del", A], capture_output=True)
    sh("ip", "link", "add", A, "type", "veth", "peer", "name", B)
    for n in (A, B):
        sh("ip", "link", "set", n, "up")
    time.sleep(1)


def raw(ifname):
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
    s.bind((ifname, 0))
    s.settimeout(0.2)
    return s


def mac_of(ifname):
    return bytes.fromhex(open(f"/sys/class/net/{ifname}/address").read().strip().replace(":", ""))


def pn_frames(s, seconds, frame_ids=None):
    end = time.time() + seconds
    while time.time() < end:
        try:
            f, addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        if addr[2] == socket.PACKET_OUTGOING:
            continue
        off = 16 if f[12:14] == b"\x81\x00" else 12
        if f[off:off + 2] != b"\x88\x92":
            continue
        fid = struct.unpack_from(">H", f, off + 2)[0]
        if frame_ids is None or fid in frame_ids:
            yield f, off, fid


def blk(o, s_, data):
    b = struct.pack(">BBH", o, s_, len(data)) + data
    return b + b"\x00" if len(data) & 1 else b


def dcp(dst, src, fid, service, xid, blocks, delay=1):
    return dst + src + struct.pack(">HH", 0x8892, fid) + struct.pack(">BBIHH", service, 0, xid, delay, len(blocks)) + blocks


def blocks_of(data):
    out, p = {}, 0
    while p + 4 <= len(data):
        o, s_, ln = struct.unpack_from(">BBH", data, p)
        out[(o, s_)] = data[p + 4:p + 4 + ln]
        p += 4 + ln + (ln & 1)
    return out


def ask(tx, frame, fids, seconds=1.5):
    tx.send(frame)
    for f, off, fid in pn_frames(tx, seconds, fids):
        return f, off, fid
    return None


def check_dcp():
    dev = ProfinetPublisher({"enabled": True, "interface": A, "station_name": "ember-io-1", "vendor_name": "EmberBurn",
                             "vendor_id": 0x00AB, "device_id": 0x0102, "ip": "192.168.0.50", "netmask": "255.255.255.0",
                             "gateway": "192.168.0.1"})
    dev.start()
    assert dev.running
    tx = raw(B)
    me = mac_of(B)
    dmac = mac_of(A)
    try:
        # Identify All
        r = ask(tx, dcp(MCAST, me, 0xFEFE, 5, 0x11223344, blk(0xFF, 0xFF, b"")), {0xFEFF})
        assert r, "no identify response"
        f, off, fid = r
        assert f[0:6] == me and f[6:12] == dmac
        service, stype, xid, _, length = struct.unpack_from(">BBIHH", f, off + 4)
        assert (service, stype, xid) == (5, 1, 0x11223344), (service, stype, xid)
        b = blocks_of(f[off + 14:off + 14 + length])
        assert b[(2, 2)] == b"\x00\x00ember-io-1" and b[(2, 1)] == b"\x00\x00EmberBurn", b
        assert b[(2, 3)] == b"\x00\x00" + struct.pack(">HH", 0xAB, 0x0102)
        assert b[(2, 4)] == b"\x00\x00\x01\x00"                              # IO-Device role
        assert b[(1, 2)][2:] == bytes([192, 168, 0, 50, 255, 255, 255, 0, 192, 168, 0, 1]), b[(1, 2)].hex()
        assert b[(1, 1)][2:] == dmac
        # Identify with a name filter that does not match: silence
        assert ask(tx, dcp(MCAST, me, 0xFEFE, 5, 1, blk(2, 2, b"other-name")), {0xFEFF}, 1.0) is None
        # ... and one that does
        assert ask(tx, dcp(MCAST, me, 0xFEFE, 5, 2, blk(2, 2, b"EMBER-IO-1")), {0xFEFF}), "name filter should match case blind"
        # Get NameOfStation
        r = ask(tx, dcp(dmac, me, 0xFEFD, 3, 3, blk(2, 2, b"")[:4]), {0xFEFD})
        assert r
        f, off, _ = r
        assert f[off + 4] == 3 and f[off + 5] == 1
        assert blocks_of(f[off + 14:])[(2, 2)] == b"\x00\x00ember-io-1"
        # Set NameOfStation and IP
        r = ask(tx, dcp(dmac, me, 0xFEFD, 4, 4, blk(2, 2, b"\x00\x01newname")
                        + blk(1, 2, b"\x00\x01" + bytes([10, 0, 0, 9, 255, 0, 0, 0, 10, 0, 0, 1]))), {0xFEFD})
        assert r
        f, off, _ = r
        assert f[off + 4] == 4 and f[off + 5] == 1
        resp = f[off + 14:]
        assert resp[:6] == bytes([5, 4, 0, 3, 2, 2]) and resp[6:7] == b"\x00", resp.hex()   # Control/Response block: option 2, sub 2, no error
        assert dev.station_name == "newname" and dev.ip == (10, 0, 0, 9)
        assert ask(tx, dcp(MCAST, me, 0xFEFE, 5, 5, blk(2, 2, b"newname")), {0xFEFF})
        # Signal (flash the LED)
        assert ask(tx, dcp(dmac, me, 0xFEFD, 4, 6, blk(5, 3, b"\x00\x00\x01\x00")), {0xFEFD})
        assert dev.signalled == 1
    finally:
        tx.close()
        dev.stop()
    return True


def check_rt():
    rx = raw(B)
    dev = ProfinetPublisher({"enabled": True, "interface": A, "controller_mac": ":".join(f"{x:02x}" for x in mac_of(B)),
                             "tags": ["Plant/Run", "Plant/Count", "Plant/Temp"], "cycle_ms": 20, "frame_id": 0xC000})
    dev.start()
    dev.publish("Plant/Run", True)
    dev.publish("Plant/Count", 41)
    dev.publish("Plant/Temp", 21.5)
    try:
        got = []
        for f, off, fid in pn_frames(rx, 1.5, {0xC000}):
            got.append((f, off))
            if len(got) >= 6:
                break
        assert len(got) >= 4, len(got)
        f, off = got[-1]
        payload = f[off + 4:]
        assert len(payload) >= 44, len(payload)
        assert payload[0:2] == b"\xff\x80" and payload[2:7] == b"\x00\x00\x00\x29\x80" and payload[7:12] == struct.pack(">f", 21.5) + b"\x80", payload[:12].hex()
        cycles = [struct.unpack_from(">H", p[0][p[1] + 4:], len(p[0][p[1] + 4:]) - 4)[0] for p in got]
        assert all(b > a for a, b in zip(cycles, cycles[1:])), cycles
        assert 400 < cycles[-1] - cycles[-2] < 900, cycles                      # 20 ms in 31.25 us units = 640
        assert payload[-2:] == b"\x35\x00", payload[-4:].hex()                  # data status, transfer status
    finally:
        rx.close()
        dev.stop()
    return True


def main():
    if os.geteuid() != 0:
        print("test_profinet.py needs root (veth and raw sockets)")
        return 1
    make_veth()
    results = []
    try:
        for name, fn in (("DCP identify, get, set, signal", check_dcp), ("RT cyclic frame", check_rt)):
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


def test_profinet():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
