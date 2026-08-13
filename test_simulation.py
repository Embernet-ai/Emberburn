"""Verification for the behavioral simulation types.

`random`, `sine` and `increment` are stateless and independent, so they were
easy to trust. The four added for site-shaped data are not: they carry state
between scans and two of them read other tags. The failure modes are quiet —
a compressor that never turns off, a thermostat that walks away from setpoint,
a feedback tag that follows its command instantly and so never trips the
mismatch alarm it exists to trip.

So this drives the generators over simulated time and asserts on behavior, not
on the fact that they returned something.

    python test_simulation.py
"""
import logging
import os
import tempfile

import publishers
from opcua_server import OPCUAServer, SIM_RANK, DEFAULT_SIM_RANK

logging.getLogger().setLevel(logging.ERROR)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


class FakeVariable:
    """Stand-in for an OPC UA variable node — only get/set are exercised."""

    def __init__(self, value):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


def build_server(tags):
    """An OPCUAServer with tags registered but no OPC UA stack started."""
    server = OPCUAServer(config_file="/nonexistent.json", log_level="ERROR")
    server.logger.setLevel(logging.ERROR)
    for name, (tag_type, initial, config) in tags.items():
        server.tags[name] = {
            "variable": FakeVariable(initial),
            "config": config,
            "type": tag_type,
        }
    return server


def run_scan(server, now):
    """One simulation pass at time `now`, honouring dependency ordering."""
    for name, tag_data in server.simulation_order():
        config = tag_data["config"]
        if not config.get("simulate", False):
            continue
        sim_type = config.get("simulation_type")
        current = tag_data["variable"].get_value()

        if sim_type == "duty_cycle":
            value = server.generate_duty_cycle_value(name, tag_data, now)
        elif sim_type == "hysteresis":
            value = server.generate_hysteresis_value(name, tag_data, current, now)
        elif sim_type == "event":
            value = server.generate_event_value(name, tag_data, now)
        elif sim_type == "walk":
            value = server.generate_walk_value(name, tag_data, current, now)
        elif sim_type == "thermostat":
            value = server.generate_thermostat_value(name, tag_data, current, now)
        elif sim_type == "follows":
            value = server.generate_follows_value(name, tag_data, current, now)
        else:
            continue

        tag_data["variable"].set_value(value)


# ── duty_cycle ────────────────────────────────────────────────────────────
def test_duty_cycle():
    server = build_server({
        "Compressor": ("bool", False, {
            "simulate": True, "simulation_type": "duty_cycle",
            "on_seconds": 600, "off_seconds": 900, "jitter_pct": 10,
        }),
    })
    tag = server.tags["Compressor"]

    samples = []
    for scan in range(3000):                      # 3000 scans x 2s = ~100 min
        now = scan * 2.0
        samples.append(server.generate_duty_cycle_value("Compressor", tag, now))

    transitions = sum(1 for a, b in zip(samples, samples[1:]) if a != b)
    on_fraction = sum(samples) / len(samples)

    check("duty_cycle switches state", transitions >= 2, f"{transitions} transitions")
    check("duty_cycle is not a coin flip", transitions < 50, f"{transitions} transitions in 3000 scans")
    # 600 on / 900 off = 40% duty. Generous bounds: the phase it starts in is
    # random and 100 minutes is only a few cycles.
    check("duty_cycle respects its ratio", 0.15 < on_fraction < 0.65, f"on {on_fraction:.0%}")


# ── event ─────────────────────────────────────────────────────────────────
def test_event():
    server = build_server({
        "DoorOpen": ("bool", False, {
            "simulate": True, "simulation_type": "event",
            "mtbe_seconds": 600, "duration_min": 30, "duration_max": 90,
        }),
    })
    tag = server.tags["DoorOpen"]

    samples = []
    for scan in range(10000):                     # ~5.5 hours at 2s
        samples.append(server.generate_event_value("DoorOpen", tag, scan * 2.0))

    active_fraction = sum(samples) / len(samples)
    rises = sum(1 for a, b in zip(samples, samples[1:]) if not a and b)

    check("event fires", rises >= 5, f"{rises} events")
    check("event is mostly inactive", active_fraction < 0.4, f"active {active_fraction:.0%}")


def test_event_overrun():
    """The overrun knob is what eventually trips a duration alarm."""
    server = build_server({
        "Defrost": ("bool", False, {
            "simulate": True, "simulation_type": "event",
            "mtbe_seconds": 300, "duration_min": 60, "duration_max": 120,
            "overrun_probability": 1.0, "overrun_multiplier": 5.0,
        }),
    })
    tag = server.tags["Defrost"]

    longest = 0
    run = 0
    for scan in range(20000):
        if server.generate_event_value("Defrost", tag, scan * 2.0):
            run += 2
            longest = max(longest, run)
        else:
            run = 0

    # duration_min 60 x multiplier 5 = 300s floor on every event.
    check("event overrun stretches duration", longest >= 300, f"longest {longest}s")


# ── walk ──────────────────────────────────────────────────────────────────
def test_walk_bounds():
    server = build_server({
        "Humidity": ("float", 50.0, {
            "simulate": True, "simulation_type": "walk",
            "step": 0.4, "min": 30.0, "max": 70.0,
        }),
    })
    tag = server.tags["Humidity"]

    value = 50.0
    lo, hi = value, value
    for scan in range(5000):
        value = server.generate_walk_value("Humidity", tag, value, scan * 2.0)
        lo, hi = min(lo, value), max(hi, value)

    check("walk stays within bounds", 30.0 <= lo and hi <= 70.0, f"range {lo}..{hi}")
    check("walk actually moves", hi - lo > 1.0, f"spread {hi - lo:.2f}")


def test_walk_drift_and_reset():
    """Filter DP creeping to its High setpoint, then being 'changed'."""
    server = build_server({
        "FilterDP": ("float", 50.0, {
            "simulate": True, "simulation_type": "walk",
            "step": 0.5, "drift_per_hour": 400.0,
            "min": 40.0, "max": 250.0, "initial_value": 50.0,
            "reset_on_max": True,
        }),
    })
    tag = server.tags["FilterDP"]

    value = 50.0
    peak = value
    resets = 0
    for scan in range(6000):                      # ~3.3 hours at 2s
        new_value = server.generate_walk_value("FilterDP", tag, value, scan * 2.0)
        if new_value < value - 50:                # snapped back to baseline
            resets += 1
        peak = max(peak, new_value)
        value = new_value

    check("walk drifts upward to its limit", peak >= 240.0, f"peak {peak}")
    check("walk resets at max", resets >= 1, f"{resets} resets")


# ── hysteresis ────────────────────────────────────────────────────────────
def test_hysteresis_closes_the_loop():
    """The pairing that keeps a cold room AT its setpoint, not near it."""
    server = build_server({
        "Setpoint": ("float", -20.0, {"simulate": False}),
        "Compressor": ("bool", True, {
            "simulate": True, "simulation_type": "hysteresis",
            "process_tag": "AirTemp", "setpoint_tag": "Setpoint",
            "differential": 1.5, "min_on_seconds": 180, "min_off_seconds": 180,
        }),
        "AirTemp": ("float", -20.0, {
            "simulate": True, "simulation_type": "thermostat",
            "setpoint_tag": "Setpoint", "driver_tag": "Compressor",
            "band": 2.0, "pull_rate": 0.35, "rise_rate": 0.22,
            "ambient": 8.0, "noise": 0.0,
        }),
    })

    temps, states = [], []
    for scan in range(20000):                    # ~11 hours at 2s
        run_scan(server, scan * 2.0)
        temps.append(server.tags["AirTemp"]["variable"].get_value())
        states.append(server.tags["Compressor"]["variable"].get_value())

    settled = temps[1000:]
    mean = sum(settled) / len(settled)
    cycles = sum(1 for a, b in zip(states, states[1:]) if not a and b)
    duty = sum(states) / len(states)

    check("closed loop holds setpoint", abs(mean - (-20.0)) < 0.6, f"mean {mean:.2f}")
    check("closed loop stays inside the differential",
          min(settled) > -22.5 and max(settled) < -17.5,
          f"{min(settled):.2f}..{max(settled):.2f}")
    check("compressor actually cycles", cycles > 10, f"{cycles} cycles")
    check("compressor is not stuck on", 0.1 < duty < 0.9, f"duty {duty:.0%}")


def test_hysteresis_respects_short_cycle_protection():
    server = build_server({
        "Process": ("float", 100.0, {"simulate": False}),
        "Device": ("bool", False, {
            "simulate": True, "simulation_type": "hysteresis",
            "process_tag": "Process", "setpoint": 0.0, "differential": 1.0,
            "min_off_seconds": 300,
        }),
    })
    tag = server.tags["Device"]

    # Process is far above setpoint from the first scan, so the only thing
    # holding the device off is the minimum-off timer.
    value = server.generate_hysteresis_value("Device", tag, False, 0.0)
    check("min_off_seconds holds the device off", value is False, f"got {value}")

    value = server.generate_hysteresis_value("Device", tag, value, 120.0)
    check("min_off_seconds still holding", value is False, f"got {value}")

    value = server.generate_hysteresis_value("Device", tag, value, 400.0)
    check("device starts once min_off elapses", value is True, f"got {value}")


def test_hysteresis_inverts_for_heating():
    server = build_server({
        "Process": ("float", 10.0, {"simulate": False}),
        "Heater": ("bool", False, {
            "simulate": True, "simulation_type": "hysteresis",
            "process_tag": "Process", "setpoint": 21.0, "differential": 1.0,
            "invert": True,
        }),
    })
    tag = server.tags["Heater"]

    value = server.generate_hysteresis_value("Heater", tag, False, 0.0)
    check("heating calls on when cold", value is True, f"got {value}")

    server.tags["Process"]["variable"].set_value(25.0)
    value = server.generate_hysteresis_value("Heater", tag, value, 10.0)
    check("heating calls off when hot", value is False, f"got {value}")


# ── thermostat ────────────────────────────────────────────────────────────
def test_thermostat_tracks_driver():
    server = build_server({
        "Compressor": ("bool", True, {"simulate": False}),
        "RoomTemp": ("float", -14.0, {
            "simulate": True, "simulation_type": "thermostat",
            "setpoint": -20.0, "band": 2.0, "driver_tag": "Compressor",
            "pull_rate": 0.5, "rise_rate": 0.2, "ambient": 5.0, "noise": 0.0,
        }),
    })
    tag = server.tags["RoomTemp"]

    # Compressor running: temperature must fall toward setpoint - band.
    value = -14.0
    for scan in range(600):
        value = server.generate_thermostat_value("RoomTemp", tag, value, scan * 2.0)
    cooled = value
    check("thermostat cools while driver on", cooled <= -21.5, f"reached {cooled}")

    # Compressor off: temperature must climb back toward ambient.
    server.tags["Compressor"]["variable"].set_value(False)
    for scan in range(600, 1200):
        value = server.generate_thermostat_value("RoomTemp", tag, value, scan * 2.0)
    check("thermostat warms while driver off", value > cooled + 1.0, f"{cooled} -> {value}")
    check("thermostat does not overshoot ambient", value <= 5.0, f"reached {value}")


def test_thermostat_sawtooths_with_duty_cycle():
    """The pairing the Fragua cold rooms actually use."""
    server = build_server({
        "Compressor": ("bool", False, {
            "simulate": True, "simulation_type": "duty_cycle",
            "on_seconds": 300, "off_seconds": 400, "jitter_pct": 5,
        }),
        "AirTemp": ("float", -20.0, {
            "simulate": True, "simulation_type": "thermostat",
            "setpoint": -20.0, "band": 2.0, "driver_tag": "Compressor",
            "pull_rate": 0.4, "rise_rate": 0.3, "ambient": 5.0, "noise": 0.02,
        }),
    })

    temps = []
    for scan in range(4000):
        run_scan(server, scan * 2.0)
        temps.append(server.tags["AirTemp"]["variable"].get_value())

    lo, hi = min(temps), max(temps)
    check("cold room oscillates", hi - lo > 1.0, f"band {lo:.2f}..{hi:.2f}")
    check("cold room stays cold", hi < 0.0, f"warmest {hi:.2f}")


def test_thermostat_follows_setpoint_tag():
    server = build_server({
        "Setpoint": ("float", 2.0, {"simulate": False}),
        "Cooling": ("bool", True, {"simulate": False}),
        "AirTemp": ("float", 2.0, {
            "simulate": True, "simulation_type": "thermostat",
            "setpoint_tag": "Setpoint", "band": 1.0, "driver_tag": "Cooling",
            "pull_rate": 1.0, "rise_rate": 0.2, "ambient": 20.0, "noise": 0.0,
        }),
    })
    tag = server.tags["AirTemp"]

    value = 2.0
    for scan in range(400):
        value = server.generate_thermostat_value("AirTemp", tag, value, scan * 2.0)
    check("thermostat honours setpoint_tag", abs(value - 1.0) < 0.2, f"settled at {value}")

    server.tags["Setpoint"]["variable"].set_value(-10.0)
    for scan in range(400, 1600):
        value = server.generate_thermostat_value("AirTemp", tag, value, scan * 2.0)
    check("changing the setpoint moves the process", abs(value - (-11.0)) < 0.2, f"settled at {value}")


# ── follows ───────────────────────────────────────────────────────────────
def test_follows_lag():
    server = build_server({
        "Command": ("bool", False, {"simulate": False}),
        "Feedback": ("bool", False, {
            "simulate": True, "simulation_type": "follows",
            "source_tag": "Command", "lag_seconds": 6.0,
        }),
    })
    tag = server.tags["Feedback"]

    value = False
    for scan in range(5):                          # settle
        value = server.generate_follows_value("Feedback", tag, value, scan * 2.0)

    server.tags["Command"]["variable"].set_value(True)
    at_command = 10.0
    value = server.generate_follows_value("Feedback", tag, value, at_command)
    check("follows lags its source", value is False, f"got {value}")

    value = server.generate_follows_value("Feedback", tag, value, at_command + 2.0)
    check("follows still lagging mid-lag", value is False, f"got {value}")

    value = server.generate_follows_value("Feedback", tag, value, at_command + 8.0)
    check("follows catches up after the lag", value is True, f"got {value}")


def test_follows_mismatch():
    """A stuck contactor — the condition the mismatch alarm watches for."""
    server = build_server({
        "Command": ("bool", False, {"simulate": False}),
        "Feedback": ("bool", False, {
            "simulate": True, "simulation_type": "follows",
            "source_tag": "Command", "lag_seconds": 0.0,
            "mismatch_probability": 1.0, "mismatch_seconds": 60.0,
        }),
    })
    tag = server.tags["Feedback"]

    value = server.generate_follows_value("Feedback", tag, False, 0.0)
    server.tags["Command"]["variable"].set_value(True)

    value = server.generate_follows_value("Feedback", tag, value, 2.0)
    check("mismatch holds feedback back", value is False, f"got {value}")

    value = server.generate_follows_value("Feedback", tag, value, 30.0)
    check("mismatch persists for its window", value is False, f"got {value}")

    value = server.generate_follows_value("Feedback", tag, value, 70.0)
    check("mismatch clears", value is True, f"got {value}")


# ── ordering ──────────────────────────────────────────────────────────────
def test_dependent_types_run_last():
    server = build_server({
        "AirTemp": ("float", 0.0, {"simulate": True, "simulation_type": "thermostat"}),
        "Compressor": ("bool", False, {"simulate": True, "simulation_type": "hysteresis"}),
        "Feedback": ("bool", False, {"simulate": True, "simulation_type": "follows"}),
        "Current": ("float", 0.0, {"simulate": True, "simulation_type": "walk"}),
    })

    order = [name for name, _ in server.simulation_order()]
    ranks = [
        SIM_RANK.get(server.tags[name]["config"]["simulation_type"], DEFAULT_SIM_RANK)
        for name in order
    ]

    check("simulations run in rank order", ranks == sorted(ranks), f"order {order} ranks {ranks}")
    # The controller must resolve between the independent tags and the process
    # it drives, or the refrigeration loop closes in the wrong direction.
    check("controller runs after drivers, before its process",
          order.index("Current") < order.index("Compressor") < order.index("AirTemp"),
          f"order {order}")


def test_unknown_reference_is_survivable():
    server = build_server({
        "AirTemp": ("float", 0.0, {
            "simulate": True, "simulation_type": "thermostat",
            "setpoint": -20.0, "driver_tag": "NoSuchTag", "noise": 0.0,
            "ambient": 5.0, "rise_rate": 0.5,
        }),
    })
    tag = server.tags["AirTemp"]

    value = 0.0
    for scan in range(50):
        value = server.generate_thermostat_value("AirTemp", tag, value, scan * 2.0)

    # Missing driver reads as False, so the room drifts toward ambient.
    check("unknown reference does not crash", isinstance(value, float), f"got {value!r}")
    check("unknown reference warned once", len(getattr(server, "_warned_refs", set())) == 1,
          f"{getattr(server, '_warned_refs', set())}")


# ── alarm on-delay ────────────────────────────────────────────────────────
def build_alarms(rules):
    publisher = publishers.AlarmsPublisher({"enabled": True, "rules": rules})
    publisher.start()
    return publisher


def test_alarm_on_delay_suppresses_brief_excursion():
    alarms = build_alarms([{
        "name": "HighHigh", "tag": "AirTemp", "condition": ">", "threshold": -12.0,
        "priority": "CRITICAL", "delay_seconds": 600, "message": "too warm",
    }])

    # Nine minutes above the limit — a door being held open, not an alarm.
    for scan in range(0, 540, 2):
        alarms.publish("AirTemp", -10.0, scan)
    check("on-delay suppresses a brief excursion", not alarms.active_alarms,
          f"active {list(alarms.active_alarms)}")

    # Back in range, then a fresh excursion: the delay restarts, it does not
    # resume from where it left off.
    alarms.publish("AirTemp", -20.0, 542)
    for scan in range(544, 1000, 2):
        alarms.publish("AirTemp", -10.0, scan)
    check("on-delay restarts after recovery", not alarms.active_alarms,
          f"active {list(alarms.active_alarms)}")


def test_alarm_on_delay_raises_when_sustained():
    alarms = build_alarms([{
        "name": "HighHigh", "tag": "AirTemp", "condition": ">", "threshold": -12.0,
        "priority": "CRITICAL", "delay_seconds": 600, "message": "too warm",
    }])

    for scan in range(0, 700, 2):
        alarms.publish("AirTemp", -10.0, scan)
    check("on-delay raises once sustained", len(alarms.active_alarms) == 1,
          f"active {list(alarms.active_alarms)}")

    alarms.publish("AirTemp", -20.0, 720)
    check("alarm auto-clears on recovery", not alarms.active_alarms,
          f"active {list(alarms.active_alarms)}")


def test_alarm_without_delay_is_immediate():
    """Faults specified as 'Immediate' must not need a delay to be configured."""
    alarms = build_alarms([{
        "name": "GeneralFault", "tag": "AHUFault", "condition": "==",
        "threshold": True, "priority": "CRITICAL", "message": "fault",
    }])

    alarms.publish("AHUFault", True, 0)
    check("no delay means immediate", len(alarms.active_alarms) == 1,
          f"active {list(alarms.active_alarms)}")


def test_alarm_matches_by_tag_name():
    """The bundled example configs use OPC node ids, which never match."""
    alarms = build_alarms([{
        "name": "HighTemperature", "tag": "ns=2;i=2", "condition": ">",
        "threshold": 26.0, "priority": "WARNING", "message": "hot",
    }])

    alarms.publish("Temperature", 99.0, 0)
    check("node-id rules never fire", not alarms.active_alarms,
          "confirms rules must reference tag names")


# ── runtime tag authoring ─────────────────────────────────────────────────
class FakeNode:
    """Stand-in for the OPC UA device folder — only add_variable is exercised."""

    def __init__(self):
        self.added = []

    def add_variable(self, idx, name, value):
        self.added.append(name)
        var = FakeVariable(value)
        var.set_writable = lambda: None
        return var


def build_authoring_server(tmp_path):
    server = build_server({})
    server.logger.setLevel(logging.ERROR)
    server.device_node = FakeNode()
    server.namespace_index = 2
    os.environ["EMBERBURN_TAG_STORE"] = str(tmp_path)
    return server


def test_defined_tag_keeps_its_simulation_config():
    """The whole point: a tag made at runtime must actually simulate."""
    with tempfile.TemporaryDirectory() as d:
        server = build_authoring_server(os.path.join(d, "tags.json"))
        ok = server.define_tag("Refrigeration/Room_01/CompressorRun", {
            "type": "bool", "initial_value": True,
            "simulate": True, "simulation_type": "duty_cycle",
            "on_seconds": 600, "off_seconds": 900,
        })
        entry = server.tags.get("Refrigeration/Room_01/CompressorRun")

        check("define_tag creates the tag", ok and entry is not None, f"ok={ok}")
        check("definition survives registration",
              entry["config"].get("simulation_type") == "duty_cycle"
              and entry["config"].get("on_seconds") == 600,
              f"{entry['config'] if entry else None}")
        check("defined tag is simulated", entry["config"].get("simulate") is True)
        check("defined tag reports its type", entry["type"] == "bool", entry["type"])

        # And it must move when the loop runs — a definition that registers but
        # never ticks is the same failure wearing a different hat.
        values = [server.generate_duty_cycle_value(
            "Refrigeration/Room_01/CompressorRun", entry, t * 2.0) for t in range(2000)]
        check("defined tag actually simulates", len(set(values)) == 2,
              f"distinct values {set(values)}")


def test_runtime_tags_survive_a_restart():
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "tags.json")

        server = build_authoring_server(store)
        server.define_tag("HVAC/AHU_01/FilterDiffPressure", {
            "type": "float", "initial_value": 55.0, "units": "Pa",
            "simulate": True, "simulation_type": "walk",
            "step": 1.2, "drift_per_hour": 150.0, "min": 45.0, "max": 265.0,
        })
        check("runtime store written", os.path.exists(store))

        # "Restart": a brand-new server reading the same volume.
        restarted = build_authoring_server(store)
        loaded = restarted.load_runtime_tags()
        check("tag reloaded after restart", "HVAC/AHU_01/FilterDiffPressure" in loaded,
              f"loaded {list(loaded)}")
        check("simulation config reloaded intact",
              loaded.get("HVAC/AHU_01/FilterDiffPressure", {}).get("drift_per_hour") == 150.0,
              f"{loaded.get('HVAC/AHU_01/FilterDiffPressure')}")


def test_deleting_a_runtime_tag_sticks():
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "tags.json")
        server = build_authoring_server(store)
        server.define_tag("Scratch/Tag", {"type": "float", "initial_value": 1.0})
        server.delete_tag("Scratch/Tag")

        restarted = build_authoring_server(store)
        check("deleted tag stays deleted", "Scratch/Tag" not in restarted.load_runtime_tags(),
              f"{list(restarted.load_runtime_tags())}")


def test_corrupt_store_does_not_stop_startup():
    """Losing added tags is bad; refusing to boot is worse."""
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "tags.json")
        with open(store, "w") as f:
            f.write("{ this is not json")
        server = build_authoring_server(store)
        check("corrupt store returns empty", server.load_runtime_tags() == {})


def test_api_definition_passes_through_model_keys():
    """An allow-list here would silently drop keys for any new model."""
    rest = publishers.RESTAPIPublisher({"enabled": False})
    definition = rest._tag_definition({
        "name": "Room/Temp",
        "type": "float",
        "simulate": True,
        "simulation_type": "thermostat",
        "driver_tag": "Room/Compressor",
        "pull_rate": 0.35,
        "access": "readwrite",
    })

    check("name is not part of the definition", "name" not in definition)
    check("model-specific keys pass through",
          definition.get("driver_tag") == "Room/Compressor" and definition.get("pull_rate") == 0.35,
          f"{definition}")
    check("access maps to writable", definition.get("writable") is True and "access" not in definition,
          f"{definition}")


# ── computed tags ─────────────────────────────────────────────────────────
def build_transform(computed_tags):
    publisher = publishers.DataTransformationPublisher({
        "enabled": True, "computed_tags": computed_tags,
    })
    written = {}
    publisher.set_write_callback(lambda name, value: written.__setitem__(name, value))
    publisher.start()
    return publisher, written


def test_computed_tag_alias_for_uns_paths():
    """A UNS path is not a Python identifier — it needs an alias to be usable."""
    transform, written = build_transform([{
        "target_tag": "Power/Switchboard_01/TotalRealPower",
        "expression": "round(sqrt(3) * v * ((ia + ib + ic) / 3) * pf / 1000, 2)",
        "dependencies": {
            "v": "Power/Switchboard_01/VoltageAB",
            "ia": "Power/Switchboard_01/CurrentA",
            "ib": "Power/Switchboard_01/CurrentB",
            "ic": "Power/Switchboard_01/CurrentC",
            "pf": "Power/Switchboard_01/TotalPowerFactor",
        },
    }])

    transform.publish("Power/Switchboard_01/VoltageAB", 220.0, 0)
    transform.publish("Power/Switchboard_01/CurrentA", 120.0, 0)
    transform.publish("Power/Switchboard_01/CurrentB", 120.0, 0)
    transform.publish("Power/Switchboard_01/CurrentC", 120.0, 0)
    transform.publish("Power/Switchboard_01/TotalPowerFactor", 0.95, 0)

    value = written.get("Power/Switchboard_01/TotalRealPower")
    # sqrt(3) * 220 * 120 * 0.95 / 1000
    check("computed tag resolves aliased UNS paths", value is not None and abs(value - 43.44) < 0.1,
          f"got {value}")


def test_computed_tag_plain_dependency_list_still_works():
    transform, written = build_transform([{
        "target_tag": "AverageTemperature",
        "expression": "(Temperature + SetPoint) / 2",
        "dependencies": ["Temperature", "SetPoint"],
    }])

    transform.publish("Temperature", 20.0, 0)
    transform.publish("SetPoint", 30.0, 0)
    check("list dependencies unchanged", written.get("AverageTemperature") == 25.0,
          f"got {written.get('AverageTemperature')}")


def test_computed_tag_rolling_window():
    transform, written = build_transform([{
        "target_tag": "Demand15Min",
        "expression": "kw",
        "dependencies": {"kw": "TotalRealPower"},
        "window_seconds": 900,
    }])

    # Ten minutes at 40 kW, then five at 100 kW. A 15-minute rolling mean must
    # still be dragged down by the earlier hour, not snap to the latest value.
    for t in range(0, 600, 2):
        transform.publish("TotalRealPower", 40.0, t)
    for t in range(600, 900, 2):
        transform.publish("TotalRealPower", 100.0, t)

    demand = written.get("Demand15Min")
    check("rolling demand averages its window", demand is not None and 55.0 < demand < 65.0,
          f"got {demand}")

    # Long after the 40 kW period has aged out, it must converge on the new load.
    for t in range(900, 2000, 2):
        transform.publish("TotalRealPower", 100.0, t)
    check("rolling demand ages out old samples", abs(written["Demand15Min"] - 100.0) < 0.01,
          f"got {written['Demand15Min']}")


if __name__ == "__main__":
    for test in [
        test_duty_cycle,
        test_event,
        test_event_overrun,
        test_walk_bounds,
        test_walk_drift_and_reset,
        test_hysteresis_closes_the_loop,
        test_hysteresis_respects_short_cycle_protection,
        test_hysteresis_inverts_for_heating,
        test_thermostat_tracks_driver,
        test_thermostat_sawtooths_with_duty_cycle,
        test_thermostat_follows_setpoint_tag,
        test_follows_lag,
        test_follows_mismatch,
        test_dependent_types_run_last,
        test_unknown_reference_is_survivable,
        test_alarm_on_delay_suppresses_brief_excursion,
        test_alarm_on_delay_raises_when_sustained,
        test_alarm_without_delay_is_immediate,
        test_alarm_matches_by_tag_name,
        test_defined_tag_keeps_its_simulation_config,
        test_runtime_tags_survive_a_restart,
        test_deleting_a_runtime_tag_sticks,
        test_corrupt_store_does_not_stop_startup,
        test_api_definition_passes_through_model_keys,
        test_computed_tag_alias_for_uns_paths,
        test_computed_tag_plain_dependency_list_still_works,
        test_computed_tag_rolling_window,
    ]:
        try:
            test()
        except Exception as e:
            check(test.__name__, False, f"raised {type(e).__name__}: {e}")

    print()
    failed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{mark}] {name}" + (f"  — {detail}" if detail else ""))
    print(f"\n{len(results) - failed}/{len(results)} passed")
    raise SystemExit(1 if failed else 0)
