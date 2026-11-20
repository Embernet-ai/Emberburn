#!/usr/bin/env python3
"""Modbus TCP server of a running EmberBurn, read by an independent client.

The publisher never started on pymodbus 3.16 (its imports used names that no longer
exist, so MODBUS_AVAILABLE went False and the gateway only logged a warning). This
starts the real gateway process with the Modbus publisher on, and reads holding
registers over a plain socket with a hand built Modbus TCP frame (MBAP header and
function code 3, from the Modbus Application Protocol specification), not through
pymodbus, so the check does not share the library under test.

    python test_modbus.py
"""
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time

PORT = 1502


def read_holding(sock, unit, address, count, tid=1):
    sock.sendall(struct.pack(">HHHBBHH", tid, 0, 6, unit, 3, address, count))
    head = sock.recv(9)
    assert len(head) == 9, head
    t, proto, length, u, fc, nbytes = struct.unpack(">HHHBBB", head)
    assert (t, proto, u) == (tid, 0, unit), head.hex()
    assert fc == 3, f"exception response fc=0x{fc:02x}"
    data = b""
    while len(data) < nbytes:
        data += sock.recv(nbytes - len(data))
    return struct.unpack(f">{count}H", data)


def main():
    cfg = {
        "tags": {
            "Temperature": {"type": "float", "initial_value": 21.5, "simulate": False},
            "Counter": {"type": "int", "initial_value": 7, "simulate": False},
            "IsRunning": {"type": "bool", "initial_value": True, "simulate": False},
        },
        "publishers": {
            "rest_api": {"enabled": False},
            "modbus_tcp": {"enabled": True, "host": "127.0.0.1", "port": PORT, "register_mapping": {
                "Temperature": {"register": 0, "type": "float"},
                "Counter": {"register": 6, "type": "int"},
                "IsRunning": {"register": 7, "type": "bool"}}},
        },
    }
    d = tempfile.mkdtemp()
    path = os.path.join(d, "modbus.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    env = dict(os.environ, UPDATE_INTERVAL="0.5", EMBERBURN_TAG_STORE=os.path.join(d, "tags.json"))
    proc = subprocess.Popen([sys.executable, "opcua_server.py", "-c", path], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=os.path.dirname(os.path.abspath(__file__)) or ".")
    ok, detail = False, ""
    try:
        deadline = time.time() + 90
        sock = None
        while time.time() < deadline and proc.poll() is None:
            try:
                sock = socket.create_connection(("127.0.0.1", PORT), timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        assert sock, "the Modbus port never opened (the publisher did not start)"
        sock.settimeout(5)
        end = time.time() + 20
        regs = None
        while time.time() < end:
            regs = read_holding(sock, 1, 0, 8)
            if regs[6] == 7:   # the scan loop has written the tags
                break
            time.sleep(0.3)
        assert regs[6] == 7 and regs[7] == 1, regs
        temp = struct.unpack(">f", struct.pack(">HH", regs[0], regs[1]))[0]
        assert temp == 21.5, (temp, regs)
        ok = True
        sock.close()
    except Exception:
        import traceback
        detail = traceback.format_exc()
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=10)[0].decode(errors="replace")
        except subprocess.TimeoutExpired:
            proc.kill()
            out = ""
        if not ok:
            detail += "\n--- gateway output ---\n" + out[-2000:]
    print(("PASS " if ok else "FAIL ") + "Modbus TCP read of a running gateway")
    if detail:
        print(detail)
    print("1/1" if ok else "0/1")
    return 0 if ok else 1


def test_modbus():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
