"""Verification for the publish-error flood: backoff, quiet logs, recovery.

EmberBurn produced 63,720 publish errors in 30 minutes — about 35 a second —
against an AnvilMQ broker that had gone away. `SparkplugBPublisher.connected`
was set True by start() and never cleared, so publish() kept addressing a dead
broker: one failed publish per tag, per scan, each with its own log line, and
no reconnect anywhere so it never recovered without a pod restart.

This asserts on the behaviour that was missing, not on the code shape:

  * a dead broker produces a handful of log lines, not one per tag per scan
  * publishing stops costing anything while the broker is down
  * the publisher reconnects on its own, with the gap between attempts growing
  * the broker coming back is noticed without a restart

The Sparkplug section runs a real in-process amqtt broker and kills it, because
the whole bug was a false belief about a socket — mocking the socket would mock
away the thing under test.

    pip install amqtt
    python test_backoff.py
"""
import asyncio
import logging
import socket
import threading
import time

from amqtt.broker import Broker

import publishers

logging.getLogger("amqtt").setLevel(logging.CRITICAL)
logging.getLogger("transitions").setLevel(logging.CRITICAL)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class CountingHandler(logging.Handler):
    """Counts records by level so a test can assert on log volume."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append((record.levelno, record.getMessage()))

    def count(self, level):
        return sum(1 for lvl, _ in self.records if lvl == level)

    def messages(self, level):
        return [msg for lvl, msg in self.records if lvl == level]

    def reset(self):
        self.records.clear()


# ── ConnectionBackoff ─────────────────────────────────────────────────────
backoff = publishers.ConnectionBackoff(initial=1.0, maximum=10.0, factor=2.0,
                                       jitter=0.0)

check("backoff starts ready", backoff.ready())

delays = []
for _ in range(6):
    delays.append(backoff.fail())

check("backoff delay grows exponentially", delays[:4] == [1.0, 2.0, 4.0, 8.0],
      str(delays[:4]))
check("backoff caps at maximum", all(d == 10.0 for d in delays[4:]),
      str(delays[4:]))
check("backoff not ready while waiting", not backoff.ready())

backoff.reset()
check("backoff ready again after reset", backoff.ready() and backoff.failures == 0)

# Jitter must stay inside the band, and must actually vary — a fleet of
# gateways that all lost the same broker must not retry in lockstep.
jittered = publishers.ConnectionBackoff(initial=10.0, maximum=10.0, jitter=0.2)
waits = []
for _ in range(20):
    waits.append(jittered.fail())
check("jitter stays within +/-20%", all(8.0 <= w <= 12.0 for w in waits),
      f"min={min(waits):.2f} max={max(waits):.2f}")
check("jitter actually varies", len(set(waits)) > 1)


# ── ErrorThrottle ─────────────────────────────────────────────────────────
throttle_log = logging.getLogger("throttle-test")
throttle_log.setLevel(logging.DEBUG)
throttle_log.propagate = False
counter = CountingHandler()
throttle_log.addHandler(counter)

throttle = publishers.ErrorThrottle(throttle_log, summary_interval=3600.0)

for _ in range(5000):
    throttle.record("Sparkplug", "Error publishing to Sparkplug: broker gone")

check("5000 identical errors log once", counter.count(logging.ERROR) == 1,
      f"{counter.count(logging.ERROR)} error lines")

throttle.record("Sparkplug", "Error publishing to Sparkplug: auth failed")
check("a changed error message logs immediately",
      counter.count(logging.ERROR) == 2,
      f"{counter.count(logging.ERROR)} error lines")

throttle.clear("Sparkplug")
check("recovery logs one line", counter.count(logging.INFO) == 1,
      str(counter.messages(logging.INFO)))
check("recovery line reports the total",
      "5001" in "".join(counter.messages(logging.INFO)),
      str(counter.messages(logging.INFO)))

counter.reset()
throttle.clear("NeverFailed")
check("clearing a healthy publisher logs nothing", not counter.records)

# The periodic summary keeps a long outage visible rather than silent.
counter.reset()
summary = publishers.ErrorThrottle(throttle_log, summary_interval=0.0)
for _ in range(3):
    summary.record("Kafka", "Error publishing to Kafka: no brokers")
check("a long outage still emits periodic summaries",
      counter.count(logging.ERROR) == 3,
      f"{counter.count(logging.ERROR)} error lines")


# ── Sparkplug B against a broker that dies ────────────────────────────────
PORT = _free_port()
TAGS = [f"Reactor/Tag{i:02d}" for i in range(90)]   # the live Fragua tag count

_loop = asyncio.new_event_loop()
_broker = None


def _run_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


threading.Thread(target=_run_loop, daemon=True).start()


def start_broker():
    global _broker

    async def go():
        global _broker
        _broker = Broker({
            "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{PORT}"}},
            "sys_interval": 0,
            "auth": {"allow-anonymous": True},
            "topic-check": {"enabled": False},
        })
        await _broker.start()

    asyncio.run_coroutine_threadsafe(go(), _loop).result(timeout=30)


def stop_broker():
    global _broker

    async def go():
        global _broker
        if _broker is not None:
            await _broker.shutdown()
            _broker = None

    asyncio.run_coroutine_threadsafe(go(), _loop).result(timeout=30)


start_broker()
time.sleep(1.5)

sp_log = logging.getLogger("sparkplug-backoff-test")
sp_log.setLevel(logging.DEBUG)
sp_log.propagate = False
sp_counter = CountingHandler()
sp_log.addHandler(sp_counter)

pub = publishers.SparkplugBPublisher({
    "enabled": True,
    "broker": "127.0.0.1",
    "port": PORT,
    "group_id": "FireballTest",
    "edge_node_id": "EdgeNode1",
    "device_id": "Line1",
    "reconnect_initial_seconds": 0.5,
    "reconnect_max_seconds": 4.0,
}, logger=sp_log)
pub.tag_metadata = {name: {"type": "float"} for name in TAGS}

pub.start()
time.sleep(2.0)
check("publisher connected to live broker", pub.connected)

# One healthy scan.
sp_counter.reset()
for i, name in enumerate(TAGS):
    pub.publish(name, float(i))
time.sleep(0.5)
check("healthy scan logs no errors", sp_counter.count(logging.ERROR) == 0,
      str(sp_counter.messages(logging.ERROR)))

# ── kill the broker ───────────────────────────────────────────────────────
stop_broker()
time.sleep(3.0)          # let the monitor notice

sp_counter.reset()

SCANS = 20
started = time.monotonic()
for _ in range(SCANS):
    for i, name in enumerate(TAGS):
        pub.publish(name, float(i))
elapsed = time.monotonic() - started

publish_calls = SCANS * len(TAGS)
noisy = sp_counter.count(logging.ERROR) + sp_counter.count(logging.WARNING)

check("broker death is detected", not pub.connected)
check(f"{publish_calls} publishes to a dead broker stay quiet",
      noisy <= 3,
      f"{noisy} error/warning lines for {publish_calls} publishes")
check("publishing while down is effectively free",
      elapsed < 1.0,
      f"{publish_calls} calls took {elapsed:.3f}s")
check("drops are counted, not silently discarded",
      pub._dropped_while_down >= publish_calls,
      f"counted {pub._dropped_while_down}")

# Reconnect attempts must be paced, not continuous.
time.sleep(6.0)
attempts = pub._backoff.failures
check("reconnect attempts are paced by backoff",
      1 <= attempts <= 12,
      f"{attempts} attempts in ~9s against a dead broker")

# ── bring the broker back ─────────────────────────────────────────────────
sp_counter.reset()
start_broker()

deadline = time.time() + 30
while time.time() < deadline and not pub.connected:
    time.sleep(0.5)

check("reconnects on its own once the broker returns", pub.connected,
      "" if pub.connected else "still down 30s after the broker came back")

if pub.connected:
    recovery = [m for m in sp_counter.messages(logging.INFO)
                if "reconnect" in m.lower() or "restored" in m.lower()]
    check("recovery is logged exactly once", len(recovery) == 1, str(recovery))

    sp_counter.reset()
    for i, name in enumerate(TAGS):
        pub.publish(name, float(i))
    time.sleep(1.0)
    check("publishing resumes after recovery",
          sp_counter.count(logging.ERROR) == 0,
          str(sp_counter.messages(logging.ERROR)))

pub.stop()
stop_broker()

# ── report ────────────────────────────────────────────────────────────────
print()
for name, ok, detail in results:
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))
passed = sum(1 for _, o, _ in results if o)
print(f"\n{passed}/{len(results)} passed")

raise SystemExit(0 if passed == len(results) else 1)
