# 🔥 EMBERBURN 🔥
### The Industrial Simulator That Got Completely Out of Hand

> **By Patrick Ryan, CTO @ Fireball Industries**
>
> *"I started building a simple OPC UA server. I blacked out. When I came to, it supported 15 protocols and had a web UI. I regret nothing."*

---

Look, you clicked on this repo, so either you're into industrial automation, you Googled something cursed, or GitHub's algorithm finally snapped. Either way, welcome. Buckle up. This README is the only therapy session you're getting.

## So What the Hell Is This?

Emberburn is a **fully simulated industrial data gateway** written in Python. It pretends to be an entire factory floor so you don't have to buy one. It generates fake-but-realistic OPC UA tag data (temperatures, pressures, counters, booleans, strings, the whole nine yards) and then absolutely **firehoses** that data out to every protocol known to mankind.

Think of it as a digital twin, except the twin has ADHD and subscriptions to 15 different messaging services.

**The core loop is stupidly simple:**
1. Spin up an OPC UA server
2. Create tags that simulate industrial data (random noise, sine waves, incrementing counters, or just... sit there)
3. Publish that data to literally whatever protocol your stakeholders are asking about this week
4. Serve it all through a sleek fire-themed web dashboard because we're not animals

That's it. That's the app. The rest is just scope creep that I've chosen to rebrand as "features."

## Why Does This Exist?

Because every industrial automation engineer has had this exact conversation:

> **You:** "I need test data to develop against."
>
> **Your Boss:** "Just connect to the production PLC."
>
> **You:** "The one controlling the $4 million press that will literally crush things if I mess up?"
>
> **Your Boss:** "Yeah that one."
>
> **You:** *(opens laptop, starts building Emberburn)*

Real PLCs cost money. Real SCADA systems cost *more* money. Real production environments cost "update your resume" money when you break them. Emberburn costs you nothing but the mass of Python packages currently having a party in your virtual environment.

**Use it for:**
- 🧪 **Development**: Build and test your OPC UA clients against something that won't fire you
- 🎭 **Demos**: Impress stakeholders with "live data" that has a 100% uptime SLA (it's fake, it literally can't fail)
- 🔌 **Integration Testing**: Validate your SCADA/HMI/historian pipelines without holding anyone's production environment hostage
- 📚 **Training**: Teach people OPC UA without needing a $50K PLC training rig
- 🌉 **Protocol Bridging**: OPC UA to MQTT? OPC UA to Kafka? OPC UA to carrier pigeon? (okay not that last one... yet)
- 💀 **Chaos Engineering**: Send garbage data to your systems on purpose and see what happens. Growth mindset.

## The Protocol Addiction Problem (15 and Counting)

What started as "let me add MQTT real quick" has spiraled into something my therapist would describe as "concerning." Here's the full damage report:

| Protocol | What It Does | Why I Added It | Emotional State When I Added It |
|----------|-------------|----------------|-------------------------------|
| **OPC UA Server** | The core. Serves tags to any OPC UA client. | This was the original idea. Pure. Innocent. | 😊 Hopeful |
| **MQTT** | Publishes tag data to any MQTT broker | "IoT is the future" | 🤔 Optimistic |
| **Sparkplug B** | Native Ignition Edge protocol | "Inductive will love this" | 😅 Fixed in 4.1.9 |
| **REST API** | HTTP endpoints for tag CRUD | "Even my PM knows what REST is" | 😐 Practical |
| **GraphQL** | Modern query interface for tags | "REST is so 2015" | 🧐 Pretentious |
| **Apache Kafka** | Enterprise event streaming | "I need to justify my Confluent subscription" | 💼 Corporate |
| **AMQP (RabbitMQ)** | Enterprise message queuing | "The rabbit just keeps hopping" | 🐰 Unhinged |
| **WebSocket** | Real-time browser push | "Dashboards should dance" | 💃 Vibing |
| **MODBUS TCP** | Legacy PLC and SCADA comms | "Respect your elders (even from 1979)" | 👴 Nostalgic |
| **InfluxDB** | Time-series database storage | "I should probably store this somewhere" | 📊 Responsible |
| **Prometheus** | Operational metrics endpoint | "Gotta monitor the thing that monitors things" | 🤯 Meta |
| **OPC UA Client** | Push data TO other OPC UA servers | "Bidirectional baby" | 🔄 Chaotic |
| **Alarms** | Threshold alerting via email/Slack/SMS | "Wake me up at 3AM, I dare you" | 😴 Masochistic |
| **SQLite Persistence** | Local historical storage + audit logs | "Data should survive a reboot, probably" | 🗄️ Adulting |
| **Data Transformation** | Unit conversion, scaling, computed tags | "Math is a protocol now, fight me" | 🧮 Deranged |

All of these run **simultaneously**. At the same time. In the same process. Like a one-man-band at the intersection of DevOps and industrial automation. Is it beautiful? Debatable. Does it work? Mostly. Will I add more? My keyboard is warm and my impulse control is nonexistent.

## Confession Time (The "15" Was Doing Some Heavy Lifting)

I audited that table in 4.1.9. Two rows were writing checks the code could not cash. In the interest of not being the guy whose README lies to you:

**GraphQL** had never started. Not "started badly." Never started, not once, in any shipped image. I wired it to `flask-graphql`, which pins `graphql-core<3`. `graphene` needs `graphql-core>=3.1`. Those two cannot coexist in the same virtualenv, so `pip install` quietly failed, the import guard politely caught the `ImportError`, GraphQL disabled itself, and I never noticed because I never looked. It's ported and working as of 4.1.9. You can actually query it now. I'm as surprised as you are.

**Sparkplug B** was worse, and I'm not dressing it up. The publisher imported a module called `sparkplug_b`. That package does not exist on PyPI. It was not vendored in this repo. It was never installable by anyone, ever. A genuinely well-written publisher for a library that, as far as Python is concerned, was imaginary.

And it got better: where it *did* build payloads, it sent **JSON** to `spBv1.0/` topics. Sparkplug B is protobuf. So even in the fantasy universe where the import worked, no real consumer (Ignition, Chariot, HiveMQ) could have decoded a single message. It was hand-rolling sequence numbers and `bdSeq` and birth/death ordering, which are exactly the parts of the spec that are easy to get quietly wrong, in service of a wire format that was wrong anyway.

Rewritten onto `pysparkplug` in 4.1.9. Real protobuf, real NBIRTH/DBIRTH/DDATA/NDEATH lifecycle, and the library owns the sequencing so I can't get it wrong again. There's a test, `test_sparkplug.py`, that stands up an in-process broker, sniffs the wire, and asserts the payloads decode as protobuf and specifically **are not JSON**, because that's the bug that hid for a year behind an import guard.

So: 15 protocols, 15 of which actually run. Took an embarrassing audit to get there. Honesty is a feature.

## The Tag System (Where the Magic Happens)

Tags are the heartbeat of any industrial system, and Emberburn lets you define them all through JSON config files because YAML had its chance and blew it.

### Create tags in the app, not in the chart

**Do not put a site's tag list in `config.tags` in the Helm chart.** It defaults
to empty and should stay that way. Tags are created in the running gateway:

```bash
# one tag
curl -X POST http://emberburn:5000/api/tags/create \
  -H 'Content-Type: application/json' -H "X-EmberBurn-Token: $KEY" \
  -d '{"name":"Refrigeration/ColdRoom_01/AirTemperature","type":"float",
       "units":"°C","initial_value":-20.0,"simulate":true,
       "simulation_type":"thermostat","driver_tag":"Refrigeration/ColdRoom_01/CompressorRun",
       "setpoint":-20.0,"band":2.0,"pull_rate":0.35}'

# or a whole site at once
curl -X POST http://emberburn:5000/api/tags/bulk \
  -H 'Content-Type: application/json' -H "X-EmberBurn-Token: $KEY" \
  -d @site-tags.json
```

…or just click them in at `:5000`. Either way EmberBurn writes the definitions
to its data volume (`EMBERBURN_TAG_STORE`, default `/app/data/tags.json`) and
reloads them at startup, so they outlive restarts, upgrades and rescheduling.

Keep the authoritative list in the site's own repo as data and push it in with a
script. A tag list baked into a chart needs a values edit, a `helm upgrade` and
usually a chart release to move one setpoint — that isn't a gateway, it's a
config file with extra steps.

**Writes need a token.** With no `EMBERBURN_API_KEY` configured, EmberBurn
generates an ephemeral per-pod token: the web UI gets it, external callers
can't. Set `security.apiKey` (or `security.existingSecret`) before automating.

Every tag gets:
- **A data type** (`float`, `int`, `string`, `bool`) because the real world has variety
- **A simulation mode**: how the value changes over time:
  - `random`: Chaotic. Unpredictable. Like your sprint velocity.
  - `sine`: Smooth, oscillating, beautiful. Engineers get unreasonably excited about this one.
  - `increment`: Goes up. Resets at max. Repeat. The Sisyphus of simulation modes.
  - `static`: Doesn't change. For when you want your simulation to have the personality of a brick.
- **Min/max bounds**: Keep your fake data within the realm of plausibility (or don't, I'm not your dad)
- **Metadata**: Engineering units, descriptions, alarm thresholds, whatever you want to slap on there

### Behavioural modes (use these for anything a human will look at)

The four above are independent and stateless. That's fine for a smoke test and
useless for a demo: `bool` + `random` flips a coin every scan, so a compressor
that "runs" 50% of every two seconds, and no tag has anything to do with any
other tag. Plants don't work like that. These do:

| Mode | What it is | Key config |
|---|---|---|
| `duty_cycle` | Boolean that runs on for a while, off for a while | `on_seconds`, `off_seconds`, `jitter_pct` |
| `hysteresis` | Boolean under two-position control of another tag | `process_tag`, `setpoint`/`setpoint_tag`, `differential`, `invert`, `min_on_seconds`, `min_off_seconds` |
| `event` | Boolean that's normally false and pulses rarely | `mtbe_seconds`, `duration_min`, `duration_max`, `overrun_probability`, `overrun_multiplier` |
| `walk` | Bounded random walk, optionally drifting | `step`, `drift_per_hour`, `min`, `max`, `reset_on_max` |
| `thermostat` | Value pulled toward setpoint by a driver boolean, drifting to ambient when it's off | `setpoint`/`setpoint_tag`, `driver_tag`, `band`, `pull_rate`, `rise_rate`, `ambient`, `noise` |
| `follows` | Mirrors another tag after a lag, and sometimes doesn't | `source_tag`, `lag_seconds`, `mismatch_probability`, `mismatch_seconds` |
| `accumulate` | Integrates another tag over time — energy counters | `source_tag`, `scale`, `max`, `reset_on_max` |
| `clock` | Hour / minute / second of local time | `part` |
| `computed` | Value from an expression over other tags | `expression`, `dependencies`, `window_seconds` |

Three things worth knowing:

**Use `hysteresis`, not `duty_cycle`, wherever the plant has a controller.** A
duty cycle runs to a clock regardless of the process, so its temperature settles
wherever the cooling and warming rates happen to cancel — which is not the
setpoint, and wanders the moment anything perturbs it. Closing the loop is what
makes a cold room sit at the number on its setpoint tag:

```json
"ColdRoom_01/AirTemperature": {
  "type": "float", "initial_value": -20.0, "units": "°C",
  "simulate": true, "simulation_type": "thermostat",
  "setpoint_tag": "ColdRoom_01/TemperatureSetpoint",
  "driver_tag": "ColdRoom_01/CompressorRun",
  "band": 2.0, "pull_rate": 0.35, "rise_rate": 0.22, "ambient": 8.0
},
"ColdRoom_01/CompressorRun": {
  "type": "bool", "initial_value": true,
  "simulate": true, "simulation_type": "hysteresis",
  "process_tag": "ColdRoom_01/AirTemperature",
  "setpoint_tag": "ColdRoom_01/TemperatureSetpoint",
  "differential": 1.5, "min_on_seconds": 180, "min_off_seconds": 180
}
```

That's circular on purpose, and it resolves: simulations run in rank order
(independent → `hysteresis` → `thermostat`/`follows`), so the controller reads
the temperature the room reached last scan, exactly like a real one sampling its
probe.

**`overrun_probability` and `drift_per_hour` are how alarms ever fire.** A door
that always closes in 90 seconds never trips a "door open > 5 min" alarm, and a
filter differential pressure that jitters around 50 Pa never reaches its High.
Give the rare case somewhere to go and the alarm list stops being decorative.

**Tag names can carry a UNS path.** `Refrigeration/ColdRoom_01/AirTemperature`
is a legal tag name and survives Sparkplug as a metric name, so brokers that
expand metrics into topics rebuild the hierarchy for free.

**A computed tag is just a tag with an expression.** `dependencies` maps
expression variables to tag names, which is required for UNS paths — to
`eval()`, `Power/Meter_01/CurrentA` is three divisions, not a variable. Add
`window_seconds` for a rolling average, which is what a "15-minute demand"
point actually is:

```json
"Power/Meter_01/TotalRealPower": {
  "type": "float", "units": "kW", "simulate": false,
  "simulation_type": "computed",
  "expression": "round(sqrt(3) * v * ((ia + ib + ic) / 3) * pf / 1000, 2)",
  "dependencies": {"v": "Power/Meter_01/VoltageAB", "ia": "Power/Meter_01/CurrentA",
                   "ib": "Power/Meter_01/CurrentB", "ic": "Power/Meter_01/CurrentC",
                   "pf": "Power/Meter_01/PowerFactor"}
}
```

Here's the vibe:

```json
{
  "tags": {
    "Reactor_Temperature": {
      "type": "float",
      "initial_value": 350.0,
      "simulate": true,
      "simulation_type": "sine",
      "min": 300.0,
      "max": 400.0,
      "description": "If this hits 500 we have bigger problems"
    },
    "Emergency_Stop": {
      "type": "bool",
      "initial_value": false,
      "simulate": false,
      "description": "The panic button. Static. Please stay false."
    }
  }
}
```

We've got example configs for days in the [config/](config/) directory, simple setups, full manufacturing simulations, process control scenarios, multi-protocol configs. Pick one, run it, feel powerful.

## The Web UI (It's Gorgeous and I'm Not Humble About It)

Emberburn ships with a full **Python Flask web application**: fire-themed dark mode, real-time dashboards, the works. No React. No webpack. No `node_modules` folder that weighs more than your actual code. Just Flask, Jinja2 templates, and vanilla JavaScript like the founding fathers intended.

**What you get:**
- 📊 **Dashboard**: Live metrics, tag counts, publisher statuses, and a general sense of accomplishment
- 🏷️ **Tag Monitor**: Every tag, every value, updating in real-time. It's like watching the Matrix but for industrial data.
- 📡 **Publishers**: See which protocols are running, enable/disable them, feel like a DJ mixing data streams
- 🚨 **Alarms**: Active alerts, alarm history, threshold configuration. Sleep is overrated anyway.
- ⚙️ **Configuration**: Server info, config export, and a live log viewer. Until 4.1.9 this page had four buttons that all popped `alert('Feature coming soon!')`. They do things now. The two that were never going to happen got deleted instead of faked.
- 🏗️ **Tag Generator**: Create new OPC UA tags from the browser. Point and click your way to industrial simulation.

The UI updates every 2 seconds because real-time means REAL TIME, and it's all wrapped in a dark mode fire aesthetic because we're EmberBurn, not EmberBoring.

**About that Tag Generator.** It shipped as a complete, polished, fully-wired UI talking to a backend that was connected to absolutely nothing. Every create, every write, every bulk import returned `501 Write not supported`, because the callback that hands the REST publisher a way into the OPC UA address space was only ever wired to a different publisher entirely. And underneath *that*, the write function had no `return` statement, so even once I fixed the wiring, every successful write would have reported itself as a failure. Two independent bugs stacked on the same code path, and a delete endpoint that cleared a cache the next update cycle refilled two seconds later while cheerfully returning `success: true`. All three fixed in 4.1.9. The Tag Generator is a real feature now instead of an elaborate diorama.

## Architecture (For the Diagram People)

```
                        ┌─────────────────────────┐
                        │   JSON Configuration     │
                        │   (tags + publishers)     │
                        └────────────┬────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │   OPC UA Server (Core)   │
                        │   Generates & manages    │
                        │   simulated tag data     │
                        └────────────┬────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │   Publisher Manager       │
                        │   "The Traffic Cop"       │
                        └────────────┬────────────┘
                                     │
            ┌──────────┬─────────┬───┴───┬─────────┬──────────┐
            ▼          ▼         ▼       ▼         ▼          ▼
         ┌──────┐ ┌────────┐ ┌──────┐ ┌──────┐ ┌───────┐ ┌────────┐
         │ MQTT │ │  REST  │ │Kafka │ │MODBUS│ │GraphQL│ │InfluxDB│
         └──────┘ └────────┘ └──────┘ └──────┘ └───────┘ └────────┘
            │         │         │        │         │          │
     ...and Sparkplug B, AMQP, WebSocket, OPC UA Client,
        Prometheus, Alarms, SQLite, Data Transforms...

                        ┌─────────────────────────┐
                        │   🔥 EmberBurn Web UI    │
                        │   Flask + Jinja2 + JS    │
                        │   (fire-themed, yes)     │
                        └─────────────────────────┘
```

The OPC UA server is the brain. The Publisher Manager is the nervous system. Everything else is just... appendages we keep growing. Each publisher runs independently in its own thread. If one dies, the others keep vibing. It's the cockroach architecture, unkillable, persistent, slightly unnerving.

All publishers are **opt-in via config**. Don't want Kafka? Don't enable it. Don't have a RabbitMQ instance? Cool, AMQP stays asleep. The app only loads what you ask for. We're chaotic, not wasteful.

## Deployment (Many Flavors of "Run This Thing")

**Docker?** Yep. Multi-arch images for AMD64 and ARM64. Run it on a Raspberry Pi, an AWS Graviton instance, your M-series Mac, or that mysterious server in the closet that nobody admits to owning.

**Kubernetes/Helm?** Obviously. There's a full Helm chart with configurable values, persistent volume claims, service definitions, and enough YAML to make your eyes bleed (ironic, I know, since I trash-talked YAML earlier).

**Systemd?** Old school, I respect it. Service files included. Set it and forget it like a crockpot.

**Just... Python?** `pip install -r requirements.txt` and `python opcua_server.py`. You're an adult. I believe in you.

## Security (New in 4.1.9, Previously a Rumor)

Let me tell you what this looked like before 4.1.9. Grep the entire codebase for `login_required`, `authenticate`, `Authorization`, `jwt`, `api_key`, zero hits. Not one. CORS was open to every origin on the internet. `POST` and `DELETE` on `/api/tags/*` took anyone who could reach the port. The OPC UA endpoint sat on `0.0.0.0:4840` anonymous and unencrypted.

On an industrial gateway. With an ingress template shipped in the box.

I'd like to say this was a considered threat model. It was not. It was scope creep's evil twin: scope *omission*.

**What it does now:**

- **Writes need a token.** `POST`/`PUT`/`PATCH`/`DELETE` on `/api/*` require an `X-EmberBurn-Token` header. Reads stay open, because the dashboard polls them constantly and there's no session to authenticate against
- **The UI still just works.** The pod injects the token into the HTML it serves, so the dashboard iframe has zero login prompts, zero redirects, zero usernames. It authenticates itself and you never see it
- **Unless you don't want that.** Set `security.uiWrites: false` and the UI drops to read-only while your automation, holding the token, keeps writing. That's the setting you want if this is reachable from anything you don't trust, because if the UI can write without a login, anyone who can load the UI can write. I can't engineer that away, so I gave you a switch instead of pretending
- **CORS is same-origin** by default now. Widen it deliberately via `security.corsOrigins`
- **OPC UA gets real auth**: Basic256Sha256 signing and encryption, plus username/password against a Secret. It's **off by default**, because turning it on breaks every anonymous SCADA client you own until each one is reconfigured with credentials and a trusted cert. Your call, your timeline. If you enable it half-configured it refuses to start rather than quietly serving plaintext and letting you believe you're encrypted

Credentials come from a Helm-managed Secret, or point `security.existingSecret` at sealed-secrets / external-secrets / vault and keep them out of the chart entirely.

Still not a hardened appliance. It's a simulator that grew up in public. But "no auth whatsoever" is no longer the answer to "how is this secured."

**The OPC UA listener got resource bounds, too.** A protocol server that accepts whatever a client feels like sending is a protocol server that eventually meets a client who sends too much. Message reassembly is capped now, a client that blows past the cap loses its channel and nobody else notices, and there's a test that proves the cap actually engages instead of just existing in a config file I feel good about. Defaults are generous, you'd have to be doing something genuinely unhinged with your address space to notice, and if you are, it's tunable.

Belt and braces regardless: the chart's NetworkPolicy keeps 4840 inside the cluster and the pod memory limits mean the worst day is a restart. **Still don't put 4840 on an untrusted network.** It's an industrial protocol from an era that assumed the network was a friend.

And dependency CVEs now fail CI, `.github/workflows/security-audit.yml`, on every `requirements.txt` change plus weekly, because a vulnerability published against a pin I haven't touched in six months is exactly the one I'd never look for. This is not hypothetical: two transitive ones sat in this repo unnoticed until 4.1.9, entirely because nothing was checking and I am not a person who checks.

## Environment Variables

For the "I refuse to edit config files" crowd (honestly, same):

| Variable | Default | What It Does |
|----------|---------|-------------|
| `OPC_ENDPOINT` | `opc.tcp://0.0.0.0:4840/freeopcua/server/` | Where the OPC UA server lives |
| `OPC_SERVER_NAME` | `Python OPC UA Server` | The name your clients see |
| `OPC_NAMESPACE` | `http://opcua.edge.server` | OPC UA namespace URI |
| `OPC_DEVICE_NAME` | `EdgeDevice` | Device folder in the OPC UA tree |
| `UPDATE_INTERVAL` | `2` | How often tags update (seconds). Set to 0.1 if you hate your CPU. |

## Documentation (We Actually Wrote Some)

Look, I know nobody reads docs. But if you're going to ignore them, at least ignore the *right* ones:

**Understanding the System:**
- [Architecture Overview](docs/ARCHITECTURE_OVERVIEW.md): How all the pieces fit together (with diagrams and everything)
- [Configuration Guide](docs/CONFIGURATION.md): Every knob, switch, and lever explained
- [Multi-Protocol Summary](docs/MULTI_PROTOCOL_SUMMARY.md): All 15 protocols, side by side, questioning my life choices
- [Protocol Comparison Guide](docs/PROTOCOL_GUIDE.md): "Which protocol should I use?" answered once and for all

**The Web UI:**
- [EmberBurn Web UI Guide](docs/PYTHON_WEB_APP.md): The Flask app in all its fire-themed glory
- [Web UI Features](docs/WEB_UI.md): Complete feature documentation
- [Web UI Quick Start](docs/WEB_UI_QUICKSTART.md): 60 seconds to dashboard nirvana

**Integration Guides (Pick Your Poison):**
- [Ignition Edge](docs/IGNITION_INTEGRATION.md): Sparkplug B + OPC UA Client for Inductive's ecosystem
- [Node-RED](docs/NODERED_INTEGRATION.md): Flow-based programming for the visual thinkers
- [MODBUS](docs/MODBUS_INTEGRATION.md): Legacy PLC integration (1979 called, it wants its protocol back... but it still works)
- [OPC UA Client Mode](docs/OPCUA_CLIENT_INTEGRATION.md): Push data to other OPC UA servers
- [GraphQL](docs/GRAPHQL_INTEGRATION.md): For when REST feels too pedestrian
- [InfluxDB + Grafana](docs/INFLUXDB_GRAFANA_INTEGRATION.md): Time-series storage and those dashboards your boss loves
- [Alarms & Notifications](docs/ALARMS_NOTIFICATIONS.md): Get yelled at by email, Slack, or SMS when thresholds breach

**Advanced Stuff:**
- [Data Transformation](docs/DATA_TRANSFORMATION.md): Unit conversions, scaling, computed tags
- [Prometheus Integration](docs/PROMETHEUS_INTEGRATION.md): Monitor the thing that monitors things (inception)
- [SQLite Persistence](docs/SQLITE_PERSISTENCE.md): Because data should survive a reboot
- [ARM64 Deployment](docs/ARM64_DEPLOYMENT.md): Running on ARM because x86 is basic

## Project Structure

```
├── opcua_server.py       # The brain. Main OPC UA server + tag simulation engine.
├── publishers.py         # 3,800 lines of publisher madness. Every protocol lives here.
├── web_app.py            # Flask web UI blueprint. Fire-themed. No apologies.
├── tags_config.json      # Default tag config for the commitment-phobic.
├── requirements.txt      # The dependency party guest list.
├── Dockerfile            # Containerize it. Ship it. Forget it.
├── config/               # Pre-built configs for every scenario imaginable.
├── docs/                 # Extensive docs. Yes, really. I'm as surprised as you.
├── helm/                 # Kubernetes Helm chart. Enterprise-ready (allegedly).
├── static/               # CSS, JS, images for the web UI.
├── templates/            # Jinja2 templates. Server-side rendering like it's 2012 (complimentary).
├── scripts/              # Build scripts, install scripts, management scripts.
├── systemd/              # Service files for the systemd faithful.
└── web/                  # Static web assets.
```

## Contributing

Found a bug? Feature idea? Existential crisis about protocol selection? PRs are welcome. Just include:
- What you changed and why
- Tests if you're feeling heroic
- Your worst industrial automation horror story (mandatory)

Seriously though, if you have an idea, open an issue. The bar for "should we add this" is apparently on the floor, as evidenced by the 15 protocols currently in this repo.

## License

**MIT**: Do literally whatever you want with this. Fork it, ship it, tattoo the source code on your body. I'm not your mom and this is not legal advice.

## One Last Thing

This project started as a weekend hack to test some Ignition tags. It now has more protocols than most enterprise integration platforms, a full web UI, Helm charts, multi-arch Docker images, and documentation that I actually maintain. Feature creep isn't a bug, it's a lifestyle.

If Emberburn saves you from plugging your laptop into a production PLC and accidentally shutting down a conveyor belt (ask me how I know), then it was all worth it.

Star the repo if you're feeling generous. Open an issue if you're feeling brave. Add another protocol if you're feeling unhinged.

**Let's go.** 🔥

---

*Built by Patrick Ryan @ [Fireball Industries](https://github.com/embernet-ai) with mass quantities of caffeine, mass quantities of mass existential dread about industrial cybersecurity, and a mass refusal to stop adding protocols.*

*Made with ☕ and the kind of ambition that borders on a personality disorder.*
