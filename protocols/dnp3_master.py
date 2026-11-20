"""DNP3 master: EmberBurn as the polling station. Config key: publishers.dnp3_master.

Opens a TCP connection to a remote outstation (a real RTU or another EmberBurn
running publishers.dnp3), does an integrity poll, then every `interval` seconds an
integrity poll and a class 1, 2, 3 event poll. The values it reads are kept in
`polled`, keyed "binary_input/0", "analog_input/3" and so on. It gives an analyzer or
intrusion detection sensor the master side of a DNP3 conversation.

Uses dnp3py (MIT, https://github.com/craigpnnl/dnp3py) for the protocol, the same
library as the outstation. It only reads; it sends no control.

Link layer order: the master sends Reset of Remote Link and waits for the
outstation's ACK before its first request. dnp3py's own runner sends the reset and
the first Read back to back and consumes the ACK later ("advisory"), so the Read
reaches the wire before the ACK that confirms the reset. A real master, and an
analyzer that follows the link layer state (Zeek's DNP3 analyzers logged only the
second poll of a capture like that), expect the confirmed reset to complete first.
So the runner is opened with its own reset turned off and the reset and the wait
are done here (`_link_reset`).
"""
import asyncio
import logging
import threading
from typing import Any, Dict, Optional

from protocols.base import SimProtocolPublisher

LINK_RESET_TIMEOUT = 3.0


class DNP3MasterPublisher(SimProtocolPublisher):
    config_key = "dnp3_master"

    def __init__(self, config, logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.polled: Dict[str, Any] = {}
        self.polls = 0

    def start(self):
        if not self.enabled:
            self.logger.info("DNP3 master publisher is disabled")
            return
        if not self.config.get("host"):
            self.logger.error("DNP3 master needs publishers.dnp3_master.host")
            self.enabled = False
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True, name="dnp3-master")
        self._thread.start()
        self.logger.info(f"DNP3 master started toward {self.config['host']}")

    def stop(self):
        self.running = False
        self._stop.set()
        self.logger.info("DNP3 master publisher stopped")

    async def _main(self):
        from dnp3.master import DefaultSOEHandler, LinkResetPolicy, Master, MasterConfig, MasterTcpRunner

        host = str(self.config["host"])
        port = int(self.config.get("port", 20000))
        interval = float(self.config.get("interval", 5.0))
        delay = 2.0
        while not self._stop.is_set():
            try:
                handler = DefaultSOEHandler()
                master = Master(handler=handler, config=MasterConfig(
                    address=int(self.config.get("address", 1)),
                    outstation_address=int(self.config.get("outstation_address", 10))))
                async with MasterTcpRunner(master=master, host=host, port=port,
                                           link_reset=LinkResetPolicy.NEVER) as runner:
                    await self._link_reset(runner, master)
                    self.unavailable_reason = None
                    delay = 2.0
                    self.logger.info(f"DNP3 master connected to {host}:{port}")
                    await runner.integrity_poll()
                    while not self._stop.is_set():
                        self._collect(handler)
                        await asyncio.sleep(interval)
                        await runner.integrity_poll()
                        await runner.class_poll()
                        self.polls += 1
            except Exception as exc:
                self.unavailable_reason = f"cannot poll {host}:{port}: {exc}"
                self.logger.warning(f"DNP3 master {self.unavailable_reason}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)

    async def _link_reset(self, runner, master):
        """Reset Remote Link, then wait for the outstation's ACK (IEEE 1815-2012 data
        link layer: the reset is a confirmed primary function, so the primary waits for
        the secondary's confirmation before the next transaction). A NACK, a timeout or
        a closed link is logged and the session goes on, as a master with a silent
        outstation would."""
        from dnp3.core.enums import LinkFunctionCode
        from dnp3.datalink.builder import build_reset_link_state
        from dnp3.datalink.parser import FrameParser

        cfg = master.config
        channel = runner.channel
        await channel.write_all(build_reset_link_state(destination=cfg.outstation_address, source=cfg.address,
                                                       dir_from_master=True).to_bytes())
        parser = FrameParser()
        deadline = asyncio.get_running_loop().time() + LINK_RESET_TIMEOUT
        while True:
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                self.logger.warning("DNP3 master: no ACK to the link reset, carrying on")
                return
            try:
                data = await asyncio.wait_for(channel.read(4096), timeout=left)
            except asyncio.TimeoutError:
                continue
            if not data:
                raise ConnectionError("outstation closed the link during the reset")
            for frame in parser.feed(data):
                if not frame.header.control.prm:
                    if frame.header.control.function_code == LinkFunctionCode.SEC_ACK:
                        return
                    self.logger.warning("DNP3 master: link reset was not acknowledged (NACK), carrying on")
                    return

    def _collect(self, handler):
        for kind in ("binary_inputs", "analog_inputs", "counters", "binary_outputs", "analog_outputs"):
            for index, point in getattr(handler, kind, {}).items():
                self.polled[f"{kind[:-1]}/{index}"] = point.value
