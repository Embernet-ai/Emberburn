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
    for name, value in (("Plant/Temp", 21.5), ("Plant/Run", True), ("Plant/Level", 41),
                        ("Plant/Count", 5), ("Plant/Valve", False), ("Plant/Setpoint", 12.5)):
        pub.publish(name, value)
    time.sleep(1)
    try:
        asyncio.run(asyncio.wait_for(master_checks(pub, writes), 40))
    finally:
        pub.stop()
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


def check_manager():
    import publishers
    mgr = publishers.PublisherManager({"publishers": {"dnp3": {"enabled": True, "port": PORT + 2}}})
    assert [type(p).__name__ for p in mgr.initialize_publishers()] == ["DNP3Publisher"]
    assert [s["name"] for s in mgr.get_publisher_statuses()] == ["DNP3"]
    return True


def main():
    results = []
    for name, fn in (("integrity poll, class 1 event, controls", check_wire), ("master role", check_master_role), ("publisher manager wiring", check_manager)):
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
