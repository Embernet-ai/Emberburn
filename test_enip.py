#!/usr/bin/env python3
"""EtherNet/IP and CIP simulator, verified on the wire with an independent client.

pycomm3 (MIT) is the independent client: it uploads the tag list, reads the
STRING template, reads and writes tags, and discovers the device with
ListIdentity. A second set of checks speaks raw encapsulation to cover what
pycomm3 does not drive: ListServices, an implicit I/O connection through Forward
Open with the T->O stream on UDP, and the error paths.

    pip install pycomm3
    python test_enip.py        # or: pytest test_enip.py

Uses the default ports (44818 and 2222), so run it where nothing else holds them.
"""
import socket
import struct
import time

import protocols.enip as enip
from protocols.enip import (
    HDR, CMD_LIST_SERVICES, CMD_REGISTER_SESSION, CMD_SEND_RR_DATA,
    EtherNetIPPublisher, cpf_decode, cpf_encode, encode_epath,
)

HOST = "127.0.0.1"
TAGS = {
    "Plant/Line1/Temperature": 21.5,
    "Plant/Line1/Pressure": 101.25,
    "Plant/Line1/Counter": 41,
    "Plant/Line1/IsRunning": True,
    "Plant/Line1/Status": "Running",
}
CFG = {
    "enabled": True,
    "host": HOST,
    "port": 44818,
    "io_port": 2222,
    "assembly_output_size": 8,
}


def start_server():
    pub = EtherNetIPPublisher(dict(CFG))
    pub.start()
    pub.running = True
    for name, value in TAGS.items():
        pub.publish(name, value)
    writes = []
    pub.set_write_callback(lambda n, v: writes.append((n, v)) or True)
    assert pub.device is not None
    return pub, writes


# ── raw encapsulation helpers ─────────────────────────────────────────────
def encap(cmd, session, data=b"", ctx=b"EMBERBRN"):
    return HDR.pack(cmd, len(data), session, 0, ctx, 0) + data


def read_frame(sock):
    head = b""
    while len(head) < HDR.size:
        chunk = sock.recv(HDR.size - len(head))
        assert chunk, "connection closed"
        head += chunk
    cmd, length, session, status, ctx, _ = HDR.unpack(head)
    body = b""
    while len(body) < length:
        body += sock.recv(length - len(body))
    return cmd, session, status, body


def register(sock):
    sock.sendall(encap(CMD_REGISTER_SESSION, 0, struct.pack("<HH", 1, 0)))
    cmd, session, status, _ = read_frame(sock)
    assert status == 0 and session
    return session


def rr(sock, session, cip, extra_items=()):
    items = [(0x0000, b""), (0x00B2, cip)] + list(extra_items)
    sock.sendall(encap(CMD_SEND_RR_DATA, session, struct.pack("<IH", 0, 10) + cpf_encode(items)))
    cmd, _, status, body = read_frame(sock)
    assert status == 0, f"encap status {status}"
    items = cpf_decode(body[6:])
    return dict(items)


def forward_open_class1(serial, to_port, rpi=20000, to_size=2 + 16, ot_size=4 + 8 + 2):
    path = bytes([0x20, 0x04, 0x24, 0x01, 0x2C, 101, 0x2C, 100])
    params_ot = 0x4000 | ot_size            # point to point, fixed
    params_to = 0x4000 | to_size
    body = struct.pack("<BBIIHHIB3x", 0x0A, 0x0E, 0, 0x7000 + serial, serial, 0x1234, 0xC0FFEE00 + serial, 1)
    body += struct.pack("<IHIH", rpi, params_ot, rpi, params_to)
    body += bytes([0x01, len(path) // 2]) + path
    return bytes([0x54, 0x02]) + encode_epath(6, 1) + body


# ── tests ─────────────────────────────────────────────────────────────────
def check_pycomm3(pub, writes):
    from pycomm3 import LogixDriver, CIPDriver

    with LogixDriver(HOST) as plc:
        info = plc.info
        assert info["product_name"] == "1756-L83E/B", info
        assert info["vendor"].startswith("Rockwell"), info
        assert info["revision"] == {"major": 33, "minor": 11}, info
        assert info["name"] == "EmberBurn", info
        names = set(plc.tags)
        for expect in ("Plant_Line1_Temperature", "Plant_Line1_Pressure", "Plant_Line1_Counter",
                       "Plant_Line1_IsRunning", "Plant_Line1_Status"):
            assert expect in names, (expect, names)
        r = plc.read("Plant_Line1_Temperature", "Plant_Line1_Counter", "Plant_Line1_IsRunning", "Plant_Line1_Status")
        by = {t.tag: t for t in r}
        assert all(t.error is None for t in r), [t.error for t in r]
        assert abs(by["Plant_Line1_Temperature"].value - 21.5) < 1e-6
        assert by["Plant_Line1_Counter"].value == 41
        assert by["Plant_Line1_IsRunning"].value is True
        assert by["Plant_Line1_Status"].value == "Running", by["Plant_Line1_Status"]
        assert by["Plant_Line1_Temperature"].type == "REAL"
        assert by["Plant_Line1_Counter"].type == "DINT"
        # a live change shows on the next read
        pub.publish("Plant/Line1/Counter", 42)
        assert plc.read("Plant_Line1_Counter").value == 42
        # write goes back to the tag store through the write callback
        w = plc.write(("Plant_Line1_Counter", 99))
        assert w.error is None, w
        assert ("Plant/Line1/Counter", 99) in writes, writes
        # unknown tag is an error, not a crash
        bad = plc.read("NoSuchTag")
        assert bad.error, bad
    found = CIPDriver.list_identity(HOST)
    assert found and found["product_name"] == "1756-L83E/B", found
    return True


def check_raw(pub):
    # ListServices over TCP
    with socket.create_connection((HOST, 44818), timeout=5) as s:
        s.sendall(encap(CMD_LIST_SERVICES, 0))
        cmd, _, status, body = read_frame(s)
        items = cpf_decode(body)
        assert status == 0 and items[0][0] == 0x0100 and b"Communications" in items[0][1]

        session = register(s)
        # Get_Attribute_Single identity product name (attribute 7)
        resp = rr(s, session, bytes([0x0E, 0x03]) + bytes([0x20, 0x01, 0x24, 0x01, 0x30, 0x07]))[0x00B2]
        assert resp[2] == 0 and resp[4] == 11 and resp[5:16] == b"1756-L83E/B", resp
        # unknown class
        resp = rr(s, session, bytes([0x0E, 0x02]) + bytes([0x20, 0x77, 0x24, 0x01]))[0x00B2]
        assert resp[2] == 0x05, resp
        # service not supported on identity
        resp = rr(s, session, bytes([0x4B, 0x02]) + bytes([0x20, 0x01, 0x24, 0x01]))[0x00B2]
        assert resp[2] == 0x08, resp
        # input assembly 100 holds the packed numeric tags
        resp = rr(s, session, bytes([0x0E, 0x03]) + bytes([0x20, 0x04, 0x24, 100, 0x30, 0x03]))[0x00B2]
        assert resp[2] == 0
        image = resp[4:]
        assert struct.unpack_from("<f", image, 0)[0] == 21.5
        assert struct.unpack_from("<f", image, 4)[0] == 101.25
        # output assembly is writable, input is not
        resp = rr(s, session, bytes([0x10, 0x03]) + bytes([0x20, 0x04, 0x24, 100, 0x30, 0x03]) + b"\x00" * 8)[0x00B2]
        assert resp[2] == 0x0E, resp
        resp = rr(s, session, bytes([0x10, 0x03]) + bytes([0x20, 0x04, 0x24, 101, 0x30, 0x03]) + b"\x01" * 8)[0x00B2]
        assert resp[2] == 0, resp
        resp = rr(s, session, bytes([0x0E, 0x03]) + bytes([0x20, 0x04, 0x24, 101, 0x30, 0x03]))[0x00B2]
        assert resp[4:] == b"\x01" * 8
        # symbolic Read Tag (the form older clients use) and the unknown tag error
        sym = b"\x91" + bytes([len("Plant_Line1_Counter")]) + b"Plant_Line1_Counter" + b"\x00"
        req = bytes([0x4C, len(sym) // 2]) + sym + struct.pack("<H", 1)
        resp = rr(s, session, req)[0x00B2]
        assert resp[2] == 0 and resp[4:6] == b"\xc4\x00", resp.hex()
        assert struct.unpack_from("<i", resp, 6)[0] in (41, 42, 99), resp.hex()
        sym = b"\x91" + bytes([9]) + b"NoSuchTag" + b"\x00"
        resp = rr(s, session, bytes([0x4C, len(sym) // 2]) + sym + struct.pack("<H", 1))[0x00B2]
        assert resp[2] == 0x04, resp.hex()
        # Write Tag with the wrong data type is refused, not coerced
        sym = b"\x91" + bytes([len("Plant_Line1_Counter")]) + b"Plant_Line1_Counter" + b"\x00"
        req = bytes([0x4D, len(sym) // 2]) + sym + struct.pack("<HH", 0xCA, 1) + struct.pack("<f", 1.0)
        resp = rr(s, session, req)[0x00B2]
        assert resp[2] == 0xFF and resp[4:6] == struct.pack("<H", 0x2107), resp.hex()
        # a session handle nobody registered is refused
        s.sendall(encap(CMD_SEND_RR_DATA, 0xDEAD, struct.pack("<IH", 0, 10) + cpf_encode([(0, b""), (0xB2, b"\x0e\x00")])))
        _, _, status, _ = read_frame(s)
        assert status == enip.ENCAP_BAD_SESSION, status

        # Forward Open class 1: the target must stream T->O data to our UDP port
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.bind((HOST, 0))
        rx.settimeout(3)
        port = rx.getsockname()[1]
        items = rr(s, session, forward_open_class1(7, port),
                   extra_items=[(0x8001, enip.sockaddr(HOST, port))])
        resp = items[0x00B2]
        assert resp[2] == 0, f"forward open status {resp[2]:02x} ext {resp[4:6].hex()}"
        ot_id, to_id = struct.unpack_from("<II", resp, 4)
        assert to_id == 0x7007
        pkt, _ = rx.recvfrom(2048)
        got = dict(cpf_decode(pkt))
        assert struct.unpack_from("<I", got[0x8002], 0)[0] == to_id
        data = got[0x00B1][2:]
        assert len(data) == 16 and struct.unpack_from("<f", data, 0)[0] == 21.5, data.hex()
        pkt2, _ = rx.recvfrom(2048)
        got2 = dict(cpf_decode(pkt2))
        assert struct.unpack_from("<H", got2[0x00B1], 0)[0] == (struct.unpack_from("<H", got[0x00B1], 0)[0] + 1) & 0xFFFF
        # O->T: send output data to UDP 2222 with a run/idle header
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        out = cpf_encode([(0x8002, struct.pack("<II", ot_id, 1)),
                          (0x00B1, struct.pack("<H", 1) + struct.pack("<I", 1) + b"\xAA" * 8)])
        tx.sendto(out, (HOST, 2222))
        time.sleep(0.3)
        resp = rr(s, session, bytes([0x0E, 0x03]) + bytes([0x20, 0x04, 0x24, 101, 0x30, 0x03]))[0x00B2]
        assert resp[4:] == b"\xAA" * 8, resp.hex()
        # Forward Close ends the stream
        close = bytes([0x4E, 0x02]) + encode_epath(6, 1) + struct.pack("<BBHHIBB", 0x0A, 0x0E, 7, 0x1234, 0xC0FFEE07, 2, 0) + bytes([0x20, 0x02, 0x24, 0x01])
        resp = rr(s, session, close)[0x00B2]
        assert resp[2] == 0, resp.hex()
        time.sleep(0.2)
        rx.settimeout(0.5)
        while True:
            try:
                rx.recvfrom(2048)
            except socket.timeout:
                break
        # a bad assembly in the path is refused with the right extended status
        bad = forward_open_class1(8, port).replace(bytes([0x2C, 100]), bytes([0x2C, 105]))
        resp = rr(s, session, bad)[0x00B2]
        assert resp[2] == 0x01 and resp[4:6] == struct.pack("<H", 0x0117), resp.hex()
    # ListIdentity over UDP
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.settimeout(3)
    u.sendto(encap(enip.CMD_LIST_IDENTITY, 0), (HOST, 44818))
    pkt, _ = u.recvfrom(2048)
    assert b"1756-L83E/B" in pkt
    return True


def check_manager():
    """The publisher is wired into PublisherManager: enabled in config, it shows up
    in the publisher list under its display name, and disabled it does not load."""
    import publishers
    cfg = {"publishers": {"ethernet_ip": dict(CFG, port=44819, io_port=2223)}}
    mgr = publishers.PublisherManager(cfg)
    pubs = mgr.initialize_publishers()
    assert [type(p).__name__ for p in pubs] == ["EtherNetIPPublisher"], pubs
    names = [s["name"] for s in mgr.get_publisher_statuses()]
    assert names == ["EtherNet/IP"], names
    assert mgr.get_publisher_statuses()[0]["description"].startswith("Serves tags as a Logix")
    off = publishers.PublisherManager({"publishers": {"ethernet_ip": dict(CFG, enabled=False)}})
    assert off.initialize_publishers() == []
    return True


def check_client(pub, writes):
    """The client role writes EmberBurn tags into a remote controller (here the
    server above) and polls tags back, through pycomm3 on the wire."""
    from protocols.enip_client import EtherNetIPClientPublisher
    pub.publish("Remote/Setpoint", 10.0)
    cli = EtherNetIPClientPublisher({
        "enabled": True, "host": HOST, "interval": 0.3,
        "tag_map": {"Local/Out": "Remote_Setpoint"},
        "poll_tags": ["Plant_Line1_Counter"],
    })
    cli.start()
    cli.publish("Local/Out", 55.5)
    deadline = time.time() + 20
    try:
        while time.time() < deadline and not (cli.writes and cli.reads):
            time.sleep(0.2)
        assert cli.writes and cli.reads, (cli.writes, cli.reads, cli.unavailable_reason)
        assert ("Remote/Setpoint", 55.5) in writes, writes
        assert "Plant_Line1_Counter" in cli.polled, cli.polled
    finally:
        cli.stop()
    return True


def main():
    pub, writes = start_server()
    results = []
    try:
        for name, fn in (("pycomm3 client", lambda: check_pycomm3(pub, writes)), ("raw encapsulation and implicit I/O", lambda: check_raw(pub)), ("publisher manager wiring", check_manager), ("client role", lambda: check_client(pub, writes))):
            try:
                results.append((name, bool(fn()), ""))
            except Exception as exc:  # report every failing check, not just the first
                import traceback
                results.append((name, False, traceback.format_exc()))
    finally:
        pub.stop()
    for name, ok, detail in results:
        print(("PASS " if ok else "FAIL ") + name)
        if detail:
            print(detail)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)}")
    return 0 if passed == len(results) else 1


def test_enip():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
