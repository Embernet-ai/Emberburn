#!/usr/bin/env python3
"""DNP3 simulator, verified with a DNP3 master over the wire.

The master (dnp3py's, the protocol library itself, driven as an independent
client of the outstation) does an integrity poll, sees a change arrive as a class
1 event, and directs operate a binary and an analog output, which must reach the
tag store. EmberBurn's own master role then polls the outstation. tshark decodes
the same traffic in the release evidence.

    pip install dnp3py
    python test_dnp3.py
"""
import asyncio
import time

from protocols.dnp3 import DNP3Publisher
from protocols.dnp3_master import DNP3MasterPublisher

PORT = 20010


async def master_checks(pub, writes):
    from dnp3.master import DefaultSOEHandler, Master, MasterConfig, MasterTcpRunner
    handler = DefaultSOEHandler()
    master = Master(handler=handler, config=MasterConfig(address=2, outstation_address=10))
    async with MasterTcpRunner(master=master, host="127.0.0.1", port=PORT) as runner:
        await runner.integrity_poll()
        assert handler.analog_inputs[0].value == 2150  # 21.5 x scale 100, handler.analog_inputs
        assert handler.binary_inputs[0].value is True, handler.binary_inputs
        assert handler.analog_inputs[1].value == 41, handler.analog_inputs
        assert handler.counters[0].value == 5, handler.counters
        # a change beyond the deadband arrives as a class 1 event
        pub.publish("Plant/Temp", 30.0)
        await asyncio.sleep(0.5)
        handler.clear()
        await runner.class_poll()
        assert handler.analog_inputs[0].value == 3000, handler.analog_inputs
        # direct operate a binary output (CROB latch on) and an analog output
        from dnp3.master import CommandBuilder
        await runner.request(master.build_direct_operate(CommandBuilder().latch_on(0).build_direct_operate()))
        await runner.request(master.build_direct_operate(CommandBuilder().add_analog(0, 9950).build_direct_operate()))
        await asyncio.sleep(0.3)
        assert ("Plant/Valve", True) in writes, writes
        assert ("Plant/Setpoint", 99.5) in writes, writes
        # a control to a point that does not exist is refused, nothing written
        n = len(writes)
        await runner.request(master.build_direct_operate(CommandBuilder().latch_on(7).build_direct_operate()))
        await asyncio.sleep(0.3)
        assert len(writes) == n, writes
    return True


def check_wire():
    pub = DNP3Publisher({"enabled": True, "host": "127.0.0.1", "port": PORT, "address": 10,
                         "tag_mapping": {"Plant/Count": {"type": "counter"},
                                         "Plant/Valve": {"type": "binary_output"},
                                         "Plant/Setpoint": {"type": "analog_output"}}})
    pub.start()
    assert pub.running
    writes = []
    pub.set_write_callback(lambda n, v: writes.append((n, v)) or True)
    import logging
    seen = []

    class Catch(logging.Handler):
        def emit(self, record):
            seen.append((record.levelno, record.getMessage()))
    pub.logger.addHandler(Catch())
    for name, value in (("Plant/Temp", 21.5), ("Plant/Run", True), ("Plant/Level", 41),
                        ("Plant/Count", 5), ("Plant/Valve", False), ("Plant/Setpoint", 12.5)):
        pub.publish(name, value)
    # a string tag has no DNP3 point: it is skipped with one info line, never an error, and the others still serve
    for _ in range(5):
        pub.publish("Plant/Mode", "AUTO")
    time.sleep(1)
    try:
        asyncio.run(asyncio.wait_for(master_checks(pub, writes), 40))
    finally:
        pub.stop()
    errors = [m for lvl, m in seen if lvl >= logging.ERROR]
    assert not errors, errors
    notes = [m for lvl, m in seen if "Plant/Mode" in m]
    assert len(notes) == 1, notes
    return True


def check_master_role():
    """EmberBurn's own master polls an EmberBurn outstation."""
    out = DNP3Publisher({"enabled": True, "host": "127.0.0.1", "port": PORT + 1, "address": 10})
    out.start()
    out.publish("Plant/Temp", 18.25)
    out.publish("Plant/Run", True)
    time.sleep(0.5)
    mst = DNP3MasterPublisher({"enabled": True, "host": "127.0.0.1", "port": PORT + 1, "interval": 0.5})
    mst.start()
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not (mst.polled and mst.polls):
            time.sleep(0.2)
        assert mst.polled.get("analog_input/0") == 1825, mst.polled
        assert mst.polled.get("binary_input/0") is True, mst.polled
    finally:
        mst.stop()
        out.stop()
    return True


def check_link_order():
    """The master waits for the ACK to its Reset of Remote Link before it sends its first
    request. A stand-in outstation holds the ACK back for 0.5 s and counts any byte that
    arrives meanwhile: a master that sends the first Read straight after the reset (as
    dnp3py's own runner does) puts the Read on the wire before the ACK, and the Read is
    the byte this check catches."""
    import socket
    from dnp3.datalink.builder import build_ack
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT + 3))
    srv.listen(1)
    srv.settimeout(15)
    mst = DNP3MasterPublisher({"enabled": True, "host": "127.0.0.1", "port": PORT + 3, "address": 1,
                               "outstation_address": 10, "interval": 60})
    mst.start()
    try:
        conn, _ = srv.accept()
        conn.settimeout(5)
        first = conn.recv(4096)
        # a link frame without user data is 10 bytes: 05 64 05 C0 dest src crc
        assert first[:2] == b"\x05\x64" and first[2] == 5 and first[3] & 0x0F == 0 and len(first) == 10, first.hex()
        conn.settimeout(0.5)
        try:
            early = conn.recv(4096)
        except socket.timeout:
            early = b""
        assert early == b"", f"request sent before the ACK to the link reset: {early.hex()}"
        conn.sendall(build_ack(1, 10, False).to_bytes())
        conn.settimeout(5)
        after = conn.recv(4096)
        assert after[:2] == b"\x05\x64" and len(after) > 10, after.hex()   # now the integrity poll
        conn.close()
    finally:
        mst.stop()
        srv.close()
    return True


def check_manager():
    import publishers
    mgr = publishers.PublisherManager({"publishers": {"dnp3": {"enabled": True, "port": PORT + 2}}})
    assert [type(p).__name__ for p in mgr.initialize_publishers()] == ["DNP3Publisher"]
    assert [s["name"] for s in mgr.get_publisher_statuses()] == ["DNP3"]
    return True


def main():
    results = []
    for name, fn in (("integrity poll, class 1 event, controls", check_wire), ("master role", check_master_role), ("master waits for the link reset ACK", check_link_order), ("publisher manager wiring", check_manager)):
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


def test_dnp3():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
