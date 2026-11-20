#!/usr/bin/env python3
"""S7comm simulator, verified through a client over the wire.

python-snap7's client reads and writes data blocks the way a Step 7 style driver
does; the checks assert the tag to data block mapping (types, byte order, bit
packing, strings) and that a client write reaches the tag store. tshark decodes
the same traffic in the release evidence.

    pip install python-snap7
    python test_s7.py
"""
import struct
import time

from snap7 import Client
from snap7.util import get_bool, get_int, get_dword, get_real

from protocols.s7 import S7CommPublisher

HOST, PORT = "127.0.0.1", 1102


def check_mapping():
    pub = S7CommPublisher({"enabled": True, "port": PORT, "db": 1, "db_size": 128, "string_length": 16})
    pub.start()
    assert pub.running
    writes = []
    pub.set_write_callback(lambda n, v: writes.append((n, v)) or True)
    for name, value in (("Temp", 21.5), ("Count", 41), ("Run", True), ("Fault", False), ("Mode", "AUTO")):
        pub.publish(name, value)
    c = Client()
    c.connect(HOST, 0, 1, PORT)
    try:
        # REAL at 0, DINT at 4, then the two BOOLs share byte 8, then the STRING
        assert abs(get_real(c.db_read(1, 0, 4), 0) - 21.5) < 1e-6
        assert get_dword(c.db_read(1, 4, 4), 0) == 41
        b = c.db_read(1, 8, 1)
        assert get_bool(b, 0, 0) is True and get_bool(b, 0, 1) is False, b
        s = c.db_read(1, 10, 18)
        assert s[0] == 16 and s[1] == 4 and bytes(s[2:6]) == b"AUTO", bytes(s)
        # a new scan value shows on the next read
        pub.publish("Count", 42)
        assert get_dword(c.db_read(1, 4, 4), 0) == 42
        # client write goes back to the tag store
        c.db_write(1, 4, bytearray(struct.pack(">i", 777)))
        time.sleep(0.4)
        assert ("Count", 777) in writes, writes
        # the CPU answers identification
        assert c.get_cpu_info().ModuleTypeName
    finally:
        c.disconnect()
        pub.stop()
    return True


def check_manager():
    import publishers
    mgr = publishers.PublisherManager({"publishers": {"s7comm": {"enabled": True, "port": PORT + 1}}})
    pubs = mgr.initialize_publishers()
    assert [type(p).__name__ for p in pubs] == ["S7CommPublisher"], pubs
    assert [s["name"] for s in mgr.get_publisher_statuses()] == ["S7comm"]
    return True


def main():
    results = []
    for name, fn in (("data block mapping and client write", check_mapping), ("publisher manager wiring", check_manager)):
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


def test_s7():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
