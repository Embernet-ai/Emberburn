#!/usr/bin/env python3
"""IEC 60870-5-104 simulator, verified with a hand written raw client.

The client below does not import the simulator's codec: every frame is built and
parsed here from the standard's formats (IEC 60870-5-104 clause 5 and
IEC 60870-5-101 clause 7), so a misreading of the standard in the simulator is not
repeated in the check. It covers STARTDT, TESTFR, station and counter
interrogation, time tagged spontaneous reports, single and setpoint commands with
select and execute, the negative confirmations, and flow control acknowledgement.
EmberBurn's own master role is then run against the station. tshark decodes the
same traffic in the release evidence.

    python test_iec104.py
"""
import socket
import struct
import time

from protocols.iec104 import IEC104MasterPublisher, IEC104Publisher

HOST, PORT = "127.0.0.1", 2414
CA = 1


class Client:
    def __init__(self, port=PORT):
        self.s = socket.create_connection((HOST, port), timeout=5)
        self.send = 0
        self.recv = 0
        self.buf = b""

    def raw(self, b):
        self.s.sendall(b)

    def i_frame(self, asdu_bytes):
        f = bytes([0x68, 4 + len(asdu_bytes), (self.send << 1) & 0xFF, (self.send << 1) >> 8,
                   (self.recv << 1) & 0xFF, (self.recv << 1) >> 8]) + asdu_bytes
        self.send += 1
        self.raw(f)

    def read_apdu(self, timeout=5):
        self.s.settimeout(timeout)
        while True:
            if len(self.buf) >= 2:
                assert self.buf[0] == 0x68, self.buf.hex()
                n = self.buf[1]
                if len(self.buf) >= 2 + n:
                    f, self.buf = self.buf[2:2 + n], self.buf[2 + n:]
                    return f
            chunk = self.s.recv(4096)
            assert chunk, "closed"
            self.buf += chunk

    def read_i(self, timeout=5):
        """Next I frame as dict; U and S frames are skipped (S frames noted)."""
        while True:
            f = self.read_apdu(timeout)
            if f[0] & 1 == 0:
                assert ((f[1] << 8 | f[0]) >> 1) == self.recv, ("send seq", f.hex(), self.recv)
                self.recv += 1
                return decode(f[4:])


def decode(a):
    t, vsq, cot_b, orig = a[0], a[1], a[2], a[3]
    ca = struct.unpack_from("<H", a, 4)[0]
    return {"type": t, "n": vsq & 0x7F, "sq": vsq >> 7, "cot": cot_b & 0x3F, "neg": bool(cot_b & 0x40),
            "orig": orig, "ca": ca, "body": a[6:]}


def asdu(t, ioa, element, cot=6, ca=CA):
    return bytes([t, 1, cot, 0]) + struct.pack("<H", ca) + struct.pack("<I", ioa)[:3] + element


def objects(a, esize):
    out, pos = {}, 0
    for _ in range(a["n"]):
        ioa = a["body"][pos] | a["body"][pos + 1] << 8 | a["body"][pos + 2] << 16
        out[ioa] = a["body"][pos + 3:pos + 3 + esize]
        pos += 3 + esize
    return out


def check_station():
    pub = IEC104Publisher({"enabled": True, "host": HOST, "port": PORT, "common_address": CA,
                           "tag_mapping": {"Plant/Valve": {"type": "command"}, "Plant/Setpoint": {"type": "command"},
                                           "Plant/Count": {"type": "counter"}}})
    pub.start()
    assert pub.running
    writes = []
    pub.set_write_callback(lambda n, v: writes.append((n, v)) or True)
    for name, value in (("Plant/Run", True), ("Plant/Level", 41), ("Plant/Temp", 21.5), ("Plant/Count", 7),
                        ("Plant/Valve", False), ("Plant/Setpoint", 10.0)):
        pub.publish(name, value)
    c = Client()
    try:
        # STARTDT act -> con, byte for byte from the standard
        c.raw(bytes.fromhex("680407000000"))
        assert c.read_apdu() == bytes.fromhex("0b000000")
        # data transfer is not started for spontaneous data before STARTDT: none queued here
        # station interrogation, QOI 20, exactly the frame in the standard's examples
        c.i_frame(bytes.fromhex("64010600010000000014"))
        con = c.read_i()
        assert (con["type"], con["cot"], con["neg"]) == (100, 7, False) and con["body"] == bytes.fromhex("00000014"), con
        got = {}
        while True:
            a = c.read_i()
            if a["type"] == 100:
                assert a["cot"] == 10, a  # activation termination
                break
            assert a["cot"] == 20 and a["ca"] == CA, a
            got[a["type"]] = objects(a, {1: 1, 11: 3, 13: 5}[a["type"]])
        assert got[1][1] == b"\x01", got                                   # Run single point ioa 1 = on
        assert got[1][2] == b"\x00", got                                   # Valve, off
        assert struct.unpack("<hB", got[11][2001]) == (41, 0), got         # Level scaled
        assert struct.unpack("<fB", got[13][3001]) == (21.5, 0), got       # Temp short float, quality 0
        assert struct.unpack("<fB", got[13][3002])[0] == 10.0, got         # Setpoint
        c.raw(bytes([0x68, 4, 1, 0, (c.recv << 1) & 0xFF, (c.recv << 1) >> 8]))  # S frame
        # counter interrogation
        c.i_frame(asdu(101, 0, bytes([5])))
        assert c.read_i()["cot"] == 7
        a = c.read_i()
        assert (a["type"], a["cot"]) == (15, 37), a
        assert struct.unpack("<iB", objects(a, 5)[4001]) == (7, 0), a
        assert c.read_i()["cot"] == 10
        # a spontaneous report on change: time tagged short float, COT 3
        pub.publish("Plant/Temp", 33.25)
        a = c.read_i()
        assert (a["type"], a["cot"]) == (36, 3), a
        el = objects(a, 12)[3001]
        assert struct.unpack("<fB", el[:5]) == (33.25, 0), el.hex()
        ms, minute, hour, dom, month, year = struct.unpack("<HBBBBB", el[5:])
        assert ms < 60000 and minute & 0x3F < 60 and hour & 0x1F < 24 and 1 <= (dom & 0x1F) <= 31 and 1 <= month <= 12 and year >= 26, el.hex()
        # a change inside the deadband is not reported; a bool change is
        pub.publish("Plant/Temp", 33.3)
        pub.publish("Plant/Run", False)
        a = c.read_i()
        assert (a["type"], a["cot"]) == (30, 3), a
        assert objects(a, 8)[1][0] == 0, a
        # single command: select then execute on the command point (ioa 5001)
        c.i_frame(asdu(45, 5001, bytes([0x81])))          # select, on
        a = c.read_i()
        assert (a["type"], a["cot"], a["neg"]) == (45, 7, False), a
        assert writes == [], writes                       # select alone writes nothing
        c.i_frame(asdu(45, 5001, bytes([0x01])))          # execute, on
        assert c.read_i()["cot"] == 7
        assert c.read_i()["cot"] == 10
        assert ("Plant/Valve", True) in writes, writes
        # setpoint short float, execute (ioa 5002)
        c.i_frame(asdu(50, 5002, struct.pack("<fB", 55.5, 0)))
        assert c.read_i()["cot"] == 7
        assert c.read_i()["cot"] == 10
        assert ("Plant/Setpoint", 55.5) in writes, writes
        # negative confirmations: unknown IOA 47, unknown CA 46, unknown type 44
        a = (c.i_frame(asdu(45, 5999, bytes([0x01]))), c.read_i())[1]
        assert (a["cot"], a["neg"]) == (47, True), a
        a = (c.i_frame(asdu(45, 5001, bytes([0x01]), ca=9)), c.read_i())[1]
        assert (a["cot"], a["neg"]) == (46, True), a
        a = (c.i_frame(asdu(200, 0, b"\x00")), c.read_i())[1]
        assert (a["cot"], a["neg"]) == (44, True), a
        # clock synchronisation is confirmed
        a = (c.i_frame(asdu(103, 0, bytes(7))), c.read_i())[1]
        assert (a["type"], a["cot"]) == (103, 7), a
        # TESTFR
        c.raw(bytes.fromhex("680443000000"))
        while True:
            f = c.read_apdu()
            if f[0] == 0x83:
                break
        # STOPDT: spontaneous data stops
        c.raw(bytes.fromhex("680413000000"))
        while c.read_apdu()[0] != 0x23:
            pass
        pub.publish("Plant/Temp", 90.0)
        c.s.settimeout(1)
        try:
            extra = c.s.recv(100)
        except socket.timeout:
            extra = b""
        assert extra == b"", extra
    finally:
        c.s.close()
        pub.stop()
    return True


def check_flow_control():
    """More than w=8 I frames from the station are acknowledged by us, and the
    station stops at k=12 unacknowledged: with 600 points an interrogation makes
    several ASDUs, and none is dropped."""
    pub = IEC104Publisher({"enabled": True, "host": HOST, "port": PORT + 1, "common_address": CA})
    pub.start()
    for i in range(600):
        pub.publish(f"P/{i}", float(i))
    c = Client(PORT + 1)
    try:
        c.raw(bytes.fromhex("680407000000"))
        c.read_apdu()
        c.i_frame(bytes.fromhex("64010600010000000014"))
        total, frames = 0, 0
        while True:
            a = c.read_i()
            if a["type"] == 100 and a["cot"] == 10:
                break
            if a["type"] == 13:
                total += a["n"]
                frames += 1
                if frames % 6 == 0:
                    c.raw(bytes([0x68, 4, 1, 0, (c.recv << 1) & 0xFF, (c.recv << 1) >> 8]))
        assert total == 600 and frames > 12, (total, frames)
    finally:
        c.s.close()
        pub.stop()
    return True


def check_master_role():
    st = IEC104Publisher({"enabled": True, "host": HOST, "port": PORT + 2, "common_address": CA})
    st.start()
    st.publish("Plant/Temp", 18.5)
    st.publish("Plant/Run", True)
    st.publish("Plant/Cmd", False)
    st.set_write_callback(lambda n, v: True)
    m = IEC104MasterPublisher({"enabled": True, "host": HOST, "port": PORT + 2, "interval": 0.5, "common_address": CA})
    m.start()
    try:
        deadline = time.time() + 15
        while time.time() < deadline and 3001 not in m.polled:
            time.sleep(0.2)
        assert m.polled.get(3001) == 18.5 and m.polled.get(1) is True, m.polled
    finally:
        m.stop()
        st.stop()
    return True


def check_manager():
    import publishers
    mgr = publishers.PublisherManager({"publishers": {"iec104": {"enabled": True, "port": PORT + 3}}})
    assert [type(p).__name__ for p in mgr.initialize_publishers()] == ["IEC104Publisher"]
    assert [s["name"] for s in mgr.get_publisher_statuses()] == ["IEC 104"]
    return True


def main():
    results = []
    for name, fn in (("raw client: STARTDT, interrogation, spontaneous, commands, negatives", check_station),
                     ("flow control and acknowledgement", check_flow_control),
                     ("master role", check_master_role), ("publisher manager wiring", check_manager)):
        try:
            results.append((name, bool(fn()), ""))
        except Exception:
            import traceback
            results.append((name, False, traceback.format_exc()))
    for name, ok, detail in results:
        print(("PASS " if ok else "FAIL ") + name)
        if detail:
            print(detail)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)}")
    return 0 if passed == len(results) else 1


def test_iec104():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
