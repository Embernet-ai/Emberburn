#!/usr/bin/env python3
"""BACnet/IP simulator, verified with a bacpypes3 client on the wire.

The client discovers the device with Who-Is, reads the object list and present
values (Analog, Binary and Character String Value), sees a live change, and
writes a present value that must reach the tag store. tshark decodes the same
traffic in the release evidence.

    pip install bacpypes3
    python test_bacnet.py
"""
import asyncio

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Real

from protocols.bacnet import BACnetPublisher

DEV = Address("127.0.0.1:47808")


async def client_checks(pub, writes):
    args = SimpleArgumentParser().parse_args(["--name", "probe", "--instance", "4321", "--address", "127.0.0.1/24:47809"])
    cli = Application.from_args(args)
    try:
        iams = await cli.who_is(1234, 1234, address=DEV)
        assert iams and iams[0].iAmDeviceIdentifier[1] == 1234, iams
        assert abs(float(await cli.read_property(DEV, "analogValue,1", "present-value")) - 21.5) < 1e-6
        assert str(await cli.read_property(DEV, "binaryValue,1", "present-value")) == "active"
        assert str(await cli.read_property(DEV, "characterstringValue,1", "present-value")) == "AUTO"
        assert str(await cli.read_property(DEV, "analogValue,1", "object-name")) == "Plant/Temp"
        olist = await cli.read_property(DEV, "device,1234", "object-list")
        kinds = sorted(str(t) for t, _ in olist)
        assert any("analog-value" in k for k in kinds) and any("binary-value" in k for k in kinds), kinds
        # a new scan value shows on the next read
        pub.publish("Plant/Temp", 30.25)
        await asyncio.sleep(0.3)
        assert abs(float(await cli.read_property(DEV, "analogValue,1", "present-value")) - 30.25) < 1e-6
        # WriteProperty reaches the tag store
        await cli.write_property(DEV, "analogValue,1", "present-value", Real(5.5))
        for _ in range(20):
            if ("Plant/Temp", 5.5) in writes:
                break
            await asyncio.sleep(0.2)
        assert ("Plant/Temp", 5.5) in writes, writes
    finally:
        cli.close()


def check_wire():
    pub = BACnetPublisher({"enabled": True, "host": "127.0.0.1", "port": 47808, "device_instance": 1234})
    pub.start()
    assert pub.running
    writes = []
    pub.set_write_callback(lambda n, v: writes.append((n, v)) or True)
    for name, value in (("Plant/Temp", 21.5), ("Plant/Run", True), ("Plant/Mode", "AUTO")):
        pub.publish(name, value)
    try:
        import time
        time.sleep(1)
        asyncio.run(asyncio.wait_for(client_checks(pub, writes), 40))
    finally:
        pub.stop()
    return True


def check_manager():
    import publishers
    mgr = publishers.PublisherManager({"publishers": {"bacnet": {"enabled": True, "host": "127.0.0.1", "port": 47810}}})
    pubs = mgr.initialize_publishers()
    assert [type(p).__name__ for p in pubs] == ["BACnetPublisher"], pubs
    assert [s["name"] for s in mgr.get_publisher_statuses()] == ["BACnet/IP"]
    return True


def main():
    results = []
    for name, fn in (("Who-Is, ReadProperty, WriteProperty on the wire", check_wire), ("publisher manager wiring", check_manager)):
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


def test_bacnet():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
