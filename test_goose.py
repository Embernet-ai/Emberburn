#!/usr/bin/env python3
"""GOOSE publisher and subscriber over a real Ethernet link.

Needs root (or CAP_NET_RAW and CAP_NET_ADMIN): it creates a veth pair, runs the
publisher on one end and reads the frames on the other end with a raw socket and a
decoder written in this file from IEC 61850-8-1 clause 18 and X.690, not the
simulator's codec. The checks are the frame layout, the BER fields, the stNum and
sqNum rules, the retransmission growth, a state change, and the subscriber writing a
frame it receives into the tag store. tshark decodes the same traffic in the
release evidence.

    sudo python test_goose.py
"""
import os
import socket
import struct
import subprocess
import time

from protocols.goose import GoosePublisher, GooseSubscriberPublisher

A, B = "ebg0", "ebg1"
DST = bytes.fromhex("010ccd010001")


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


def frames(s, seconds):
    end = time.time() + seconds
    out = []
    while time.time() < end:
        try:
            f, addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        if addr[2] != socket.PACKET_OUTGOING and (f[16:18] == b"\x88\xb8" and f[12:14] == b"\x81\x00" or f[12:14] == b"\x88\xb8"):
            out.append((time.time(), f))
    return out


def tlv(b, p):
    tag, ln = b[p], b[p + 1]
    p += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(b[p:p + n], "big")
        p += n
    return tag, b[p:p + ln], p + ln


def parse(f):
    assert f[0:6] == DST, f[0:6].hex()
    # The 802.1Q tag (priority 4) is on the wire; a veth end may hand the frame up with
    # the tag already moved into the packet's metadata, so accept both and check the
    # priority when the tag is there.
    off = 12
    if f[12:14] == b"\x81\x00":
        assert (struct.unpack(">H", f[14:16])[0] >> 13) == 4
        off = 16
    assert f[off:off + 2] == b"\x88\xb8"
    base = off + 2
    appid, length, r1, r2 = struct.unpack(">HHHH", f[base:base + 8])
    assert appid == 1 and r1 == 0 and r2 == 0
    pdu = f[base + 8:base + length]
    assert len(pdu) == length - 8, (len(pdu), length)
    tag, body, _ = tlv(pdu, 0)
    assert tag == 0x61
    d, p = {}, 0
    while p < len(body):
        t, v, p = tlv(body, p)
        d[t] = v
    return d


def check_publisher():
    pub = GoosePublisher({"enabled": True, "interface": A, "tags": ["Plant/Trip", "Plant/Level", "Plant/Temp", "Plant/Mode"],
                          "min_time_ms": 20, "max_time_ms": 400, "appid": 1})
    rx = raw(B)
    pub.start()
    assert pub.running
    for n, v in (("Plant/Trip", False), ("Plant/Level", 41), ("Plant/Temp", 21.5), ("Plant/Mode", "AUTO")):
        pub.publish(n, v)
    try:
        got = frames(rx, 2.0)
        assert len(got) >= 5, len(got)
        first = parse(got[0][1])
        assert first[0x80] == b"EmberBurnIED/LLN0$GO$gcb01" and first[0x82] == b"EmberBurnIED/LLN0$DataSet1"
        assert first[0x83] == b"EmberBurnGOOSE1"
        assert int.from_bytes(first[0x81], "big") == 800            # timeAllowedtoLive = 2 x max time
        assert int.from_bytes(first[0x85], "big") == 1 and int.from_bytes(first[0x86], "big") == 0  # stNum 1, sqNum 0
        assert first[0x87] == b"\x00" and first[0x89] == b"\x00"     # test, ndsCom false
        assert int.from_bytes(first[0x88], "big") == 1 and int.from_bytes(first[0x8A], "big") == 4
        sec = int.from_bytes(first[0x84][:4], "big")
        assert abs(sec - time.time()) < 5 and len(first[0x84]) == 8
        data = first[0xAB]
        items, p = [], 0
        while p < len(data):
            t, v, p = tlv(data, p)
            items.append((t, v))
        assert items[0] == (0x83, b"\x00")                            # Trip BOOLEAN false
        assert items[1] == (0x85, b"\x29")                            # Level INTEGER 41
        assert items[2][0] == 0x87 and items[2][1][0] == 8 and struct.unpack(">f", items[2][1][1:])[0] == 21.5
        assert items[3] == (0x8A, b"AUTO")
        # retransmission: sqNum counts up while stNum stays, and the gaps grow to max time
        sq = [int.from_bytes(parse(f)[0x86], "big") for _, f in got]
        assert sq[:5] == [0, 1, 2, 3, 4], sq
        gaps = [got[i + 1][0] - got[i][0] for i in range(len(got) - 1)]
        assert gaps[1] > gaps[0] * 1.5 and max(gaps) < 0.6, gaps
        # a change: stNum 2, sqNum 0, sent at once
        t0 = time.time()
        pub.publish("Plant/Trip", True)
        deadline = time.time() + 2
        changed = None
        while time.time() < deadline and changed is None:
            for ts, f in frames(rx, 0.3):
                d = parse(f)
                if int.from_bytes(d[0x85], "big") == 2:
                    changed = (ts, d)
                    break
        assert changed, "no stNum 2 frame"
        assert changed[0] - t0 < 0.5 and int.from_bytes(changed[1][0x86], "big") == 0
        assert changed[1][0xAB][:3] == bytes([0x83, 1, 0xFF])        # Trip now true
    finally:
        rx.close()
        pub.stop()
    return True


def check_subscriber():
    from protocols.goose import build_frame, build_pdu
    sub = GooseSubscriberPublisher({"enabled": True, "interface": A, "tags": ["Rx/Breaker", "Rx/Count"],
                                    "gocb_ref": "OtherIED/LLN0$GO$gcb9"})
    writes = []
    sub.set_write_callback(lambda n, v: writes.append((n, v)) or True)
    sub.start()
    assert sub.running
    tx = raw(B)
    try:
        for st, vals in ((1, [True, 5]), (1, [True, 5]), (2, [False, 6])):
            pdu = build_pdu("OtherIED/LLN0$GO$gcb9", 2000, "OtherIED/LLN0$DS", "other", time.time(), st, 0, False, 1, False, vals)
            tx.send(build_frame(DST, bytes.fromhex("020000000009"), 5, pdu))
            time.sleep(0.2)
        # a frame from a different control block is ignored
        pdu = build_pdu("Else/LLN0$GO$x", 2000, "d", "g", time.time(), 9, 0, False, 1, False, [True, 99])
        tx.send(build_frame(DST, bytes.fromhex("020000000009"), 5, pdu))
        time.sleep(0.4)
        assert writes == [("Rx/Breaker", True), ("Rx/Count", 5), ("Rx/Breaker", False), ("Rx/Count", 6)], writes
    finally:
        tx.close()
        sub.stop()
    return True


def main():
    if os.geteuid() != 0:
        print("test_goose.py needs root (veth and raw sockets)")
        return 1
    make_veth()
    results = []
    try:
        for name, fn in (("publisher frames, retransmission, state change", check_publisher), ("subscriber writes tags", check_subscriber)):
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


def test_goose():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
