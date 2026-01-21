# Emberburn for Testing & Simulation
> *Because Your Production Environment is Too Precious to Test On*
> 
> **By Patrick Ryan, CTO @ Fireball Industries**  
> *"I put the 'fun' in 'functional testing' (citation needed)"*

> Sometimes you need fake industrial data that's more reliable than your actual production environment. This is that.

A lightweight, configurable server built with Python that simulates industrial process tags **AND publishes data to 15 different protocols simultaneously**. Perfect for testing Ignition Edge, SCADA systems, or any OPC UA client without needing actual hardware. Or money. Or patience.

Now with MQTT, REST API, Sparkplug B, Kafka, AMQP, WebSocket, MODBUS TCP, GraphQL, InfluxDB, Alarms, OPC UA Client, Prometheus, SQLite Persistence, Data Transformation, AND a beautiful web-based configuration UI! (Yes, we got carried away. No, we're not sorry.)

## What Does This Actually Do?
*The TL;DR for People With Deadlines*

Spins up an OPC UA server with customizable tags that can:
- **Random values**: Because chaos is a feature, not a bug ✨
- **Sine waves**: For that smooth, oscillating aesthetic (engineers love this stuff)
- **Incrementing counters**: They go up. Sometimes they reset. It's thrilling, really.
- **Static values**: For when you want your simulation to be as exciting as watching paint dry
- **🔥 Multi-protocol publishing**: Stream data to MQTT, REST API, Kafka, and 6 other protocols simultaneously! (We have a problem and that problem is protocol addiction)

Great for development, testing, demos, or just pretending you have a fully instrumented factory.

**Fun fact:** This started as a simple OPC UA server. Then feature creep happened. Now it's a Swiss Army knife of industrial protocols.
*The Kitchen Sink Approach to Industrial Protocols*

- 📊 Multiple data types (int, float, string, bool) - Because variety is the spice of life
- 🎲 Configurable simulation modes (random, sine wave, increment, static) - Choose your chaos level
- 🔧 JSON-based configuration (because YAML has enough problems) - Fight me
- 🐳 Easy deployment with systemd service files - For when you want it running forever
- 📝 Comprehensive logging (so you know exactly when things go sideways) - Narrator: They will
- 🚀 Zero hardware requirements (finally!) - Your wallet thanks you
- **🆕 MQTT Publisher**: Stream real-time tag data to any MQTT broker - IoT approved ✓
- **🆕 Sparkplug B**: Native Ignition Edge protocol support - Inductive Automation's favorite
- **🆕 Apache Kafka**: Enterprise-grade data streaming - For when you need to justify that budget
- **🆕 AMQP (RabbitMQ)**: Enterprise messaging - The rabbit is still hopping
- **🆕 WebSocket**: Real-time browser updates - Make those dashboards dance
- **🆕 REST API**: Query and write tags via HTTP endpoints - The protocol even your PM understands
- **🆕 GraphQL API**: Modern query interface - REST's cooler younger sibling
- **🆕 MODBUS TCP**: Legacy PLC and SCADA support - Respect your elders (even if they're from 1979)
- **🆕 InfluxDB**: Time-series database storage + Grafana dashboards - Historical data that doesn't lie
- **🆕 Alarms**: Threshold-based alerting via email/Slack/SMS - Sleep soundly (or don't, when things break)
- **🆕 OPC UA Client**: Push data to other OPC UA servers (Ignition, historians) - Bidirectional baby!
- **🆕 Prometheus**: Operational metrics (uptime, message counts, errors) - Monitor all the things!
- **🆕 SQLite Persistence**: Local data storage with historical tag values and audit logging - Never lose data again!
- **🆕 Data Transformation**: Unit conversions, scaling, and computed tags - Transform data on the fly!
- **🆕 Multi-Protocol**: Run 15 protocols simultaneously - Because we have issues
- **🔥 EmberBurn Web UI**: Beautiful **Python Flask** web application for configuration and monitoring - Professional, scalable, no build step!
- **🏗️ Multi-Architecture Support**: Native ARM64 and AMD64 Docker images - Run on Raspberry Pi, AWS Graviton, Apple Silicon, and traditional x86 servers!

## Quick Start

### Installation

```bash
# Clone this bad boy
git clone <your-repo-url>
cd Small-Application

# Install dependencies
pip install -r requirements.txt
```

**Dependencies:**
- `opcua` - OPC UA server implementation
- `paho-mqtt` - MQTT client for publishing
- `flask` - REST API server
- `flask-cors` - CORS support for web clients
- `websocket-server` - WebSocket support (future expansion)

### Running the Server

```bash
# Basic usage (OPC UA only, no publishers)
python opcua_server.py

# With MQTT and REST API enabled (use the new config file)
python opcua_server.py -c config/config_with_mqtt.json

# With custom config file
python opcua_server.py -c config/example_tags_manufacturing.json

# Debug mode (for when things inevitably break)
python opcua_server.py -l DEBUG

# Custom update interval
python opcua_server.py -i 0.5
```

The server starts at `opc.tcp://0.0.0.0:4840/freeopcua/server/` by default.

**When publishers are enabled:**
- **MQTT**: Publishes to `industrial/opcua/<tag_name>` (configurable)
- **REST API**: Available at `http://localhost:5000/api/tags`

## Configuration

Tags and publishers are configured via JSON files. Check out [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full documentation (yes, we actually wrote docs).

### Configuration Structure (New!)

```json
{
  "tags": {
    // Your tag definitions go here
  },
  "publishers": {
    "mqtt": {
      "enabled": true,
      "broker": "localhost",
      "port": 1883,
      "topic_prefix": "industrial/opcua"
    },
    "rest_api": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 5000
    }
  }
}
```

**Note**: Old configuration files (without the `tags` wrapper) are still supported for backward compatibility.

### Basic Tag Example

```json
{
  "Temperature": {
    "type": "float",
    "initial_value": 20.0,
    "simulate": true,
    "simulation_type": "random",
    "min": 15.0,
    "max": 25.0,
    "description": "Ambient temperature in Celsius"
  },
  "Counter": {
    "type": "int",
    "initial_value": 0,
    "simulate": true,
    "simulation_type": "increment",
    "increment": 1,
    "max": 1000,
    "reset_on_max": true,
    "description": "Production counter with rollover"
  }
}
```

### Example Configs

We've included some ready-to-use configurations in the [config/](config/) directory:
- `example_tags_simple.json` - Basic setup for beginners
- `example_tags_manufacturing.json` - Production line simulation
- `example_tags_process_control.json` - Process control scenarios
- `config_with_mqtt.json` - **NEW!** Full config with MQTT and REST API enabled

## Data Publishers

### MQTT Publisher

Publish tag values to any MQTT broker in real-time!

**Configuration:**
```json
{
  "publishers": {
    "mqtt": {
      "enabled": true,
      "broker": "localhost",          // MQTT broker address
      "port": 1883,                    // MQTT broker port
      "client_id": "opcua_server",     // Client identifier
      "username": "",                  // Optional authentication
      "password": "",
      "use_tls": false,                // Enable TLS/SSL
      "topic_prefix": "industrial/opcua",  // Topic prefix
      "command_topic": "industrial/opcua/commands",  // For write-backs
      "payload_format": "json",        // "json" or "string"
      "qos": 1,                        // QoS level (0, 1, or 2)
      "retain": false                  // Retain messages
    }
  }
}
```

**MQTT Topics:**
- Published data: `industrial/opcua/<tag_name>`
- Example: `industrial/opcua/Temperature` → `{"tag": "Temperature", "value": 22.5, "timestamp": 1736476800}`

**Test with mosquitto:**
```bash
# Subscribe to all tag updates
mosquitto_sub -h localhost -t "industrial/opcua/#" -v

# Publish a command (future feature - write-back)
mosquitto_pub -h localhost -t "industrial/opcua/commands/Temperature" -m "25.0"
```

### REST API Publisher

Query and control tags via HTTP endpoints!

**Configuration:**
```json
{
  "publishers": {
    "rest_api": {
      "enabled": true,
      "host": "0.0.0.0",   // Listen on all interfaces
      "port": 5000          // API port
    }
  }
}
```

**API Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/tags` | Get all tag values |
| `GET` | `/api/tags/<tag_name>` | Get specific tag value |
| `POST/PUT` | `/api/tags/<tag_name>` | Write tag value (future) |
| `GET` | `/api/health` | Health check |

**Examples:**
```bash
# Get all tags
curl http://localhost:5000/api/tags

# Get specific tag
curl http://localhost:5000/api/tags/Temperature

# Write to a tag (if write callback is implemented)
curl -X POST http://localhost:5000/api/tags/Temperature \
  -H "Content-Type: application/json" \
  -d '{"value": 25.0}'
```

**Response Format:**
```json
{
  "tags": {
    "Temperature": {
      "value": 22.5,
      "timestamp": 1736476800.123
    },
    "Pressure": {
      "value": 101.3,
      "timestamp": 1736476800.123
    }
  },
  "count": 2
}
```

## Environment Variables

Customize the server without touching code (the dream):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPC_ENDPOINT` | `opc.tcp://0.0.0.0:4840/freeopcua/server/` | Server endpoint URL |
| `OPC_SERVER_NAME` | `Python OPC UA Server` | Server display name |
| `OPC_NAMESPACE` | `http://opcua.edge.server` | OPC UA namespace URI |
| `OPC_DEVICE_NAME` | `EdgeDevice` | Device/folder name in OPC UA tree |
| `UPDATE_INTERVAL` | `2` | Tag update interval in seconds |

## Running as a Service

Because manually starting things is so 2015.

### Linux (systemd)

```bash
# Copy service file
sudo cp systemd/opcua-server.service /etc/systemd/system/

# Edit paths in the service file to match your installation
sudo nano /etc/systemd/system/opcua-server.service

# Enable and start
sudo systemctl enable opcua-server
sudo systemctl start opcua-server

# Check status
sudo systemctl status opcua-server
```

### Using the Management Script

```bash
# Install as service
./scripts/manage.sh install

# Start/stop/restart
./scripts/manage.sh start
./scripts/manage.sh stop
./scripts/manage.sh restart

# View logs
./scripts/manage.sh logs
```

## Requirements

- Python 3.6+ (because we live in the future)
- opcua library - OPC UA server
- paho-mqtt - MQTT publishing
- flask - REST API server
- flask-cors - CORS support
- websocket-server - Future WebSocket support

## Project Structure

```
├── opcua_server.py              # Main server implementation
├── publishers.py                # NEW: Multi-protocol publishers (MQTT, REST, etc.)
├── tags_config.json             # Default tag configuration
├── requirements.txt             # Dependencies
├── config/
│   ├── config_with_mqtt.json   # NEW: Full config with all publishers
│   ├── example_tags_*.json     # Example tag configurations
├── docs/                        # Documentation
├── scripts/                     # Utility scripts
└── systemd/                     # Service files
```

## Common Use Cases

- **Development**: Test your OPC UA client without hardware
- **Demos**: Impress stakeholders with "live" data that never fails
- **Integration Testing**: Validate SCADA/HMI integrations
- **Training**: Teach OPC UA concepts without expensive PLCs
- **MQTT Integration**: Bridge OPC UA to MQTT-based systems (IoT, cloud platforms)
- **Multi-Protocol Testing**: Test systems that consume data from multiple sources
- **REST API Access**: Web dashboards and modern applications
- **Chaos Engineering**: Because why not?

## Architecture

The server now supports a **modular publisher architecture**:

```
OPC UA Server (Core)
    ↓
Publisher Manager
    ├─→ MQTT Publisher → MQTT Broker → IoT Devices/Cloud
    ├─→ REST API Publisher → HTTP Clients/Web Apps
    ├─→ WebSocket Publisher (Coming Soon) → Real-time Web UIs
    └─→ InfluxDB Publisher (Future) → Time-Series Database
```

All publishers run simultaneously and independently. Enable/disable any publisher via configuration without code changes.

## Troubleshooting

**Server won't start?**
- Check if port 4840 is already in use: `netstat -an | grep 4840`
- Verify Python version: `python --version`
- Check the logs with `-l DEBUG` flag

**Tags not updating?**
- Ensure `"simulate": true` is set in your config
- Verify your `simulation_type` is valid
- Check the `UPDATE_INTERVAL` isn't set to something ridiculous

**Can't connect from client?**
- Firewall blocking port 4840? (Classic.)
- Using the right endpoint URL?
- Server actually running? (Don't @ us.)

## Contributing

Found a bug? Have an idea? PRs welcome. Please include:
- What you changed and why
- Tests if applicable (we believe in you)
- Your favorite industrial automation horror story
- Have an idea? Let me know!

## Documentation

**Core Guides:**
- [Configuration Guide](docs/CONFIGURATION.md) - Complete tag and publisher configuration
- [Architecture Overview](docs/ARCHITECTURE_OVERVIEW.md) - System architecture and data flow
- [Multi-Protocol Summary](docs/MULTI_PROTOCOL_SUMMARY.md) - All 15 protocols explained
- [Prometheus Integration](docs/PROMETHEUS_INTEGRATION.md) - Operational metrics and monitoring
- [SQLite Persistence](docs/SQLITE_PERSISTENCE.md) - Historical data storage and audit logging
- [Data Transformation](docs/DATA_TRANSFORMATION.md) - Unit conversions, scaling, and computed tags ⭐ NEW!
- [Protocol Comparison Guide](docs/PROTOCOL_GUIDE.md) - Which protocol for which job?
- **[🔥 EmberBurn Web UI](docs/PYTHON_WEB_APP.md) - Python Flask web application guide** ⭐ NEW!
- [Web UI Features](docs/WEB_UI.md) - Complete UI feature documentation
- [Web UI Quick Start](docs/WEB_UI_QUICKSTART.md) - 60-second start guide

**Integration Guides:**
- [Ignition Edge Integration](docs/IGNITION_INTEGRATION.md) - Sparkplug B + OPC UA Client setup
- [Node-RED Integration](docs/NODERED_INTEGRATION.md) - Flow-based programming
- [MODBUS Integration](docs/MODBUS_INTEGRATION.md) - Legacy PLC integration
- [OPC UA Client Mode](docs/OPCUA_CLIENT_CONFIGURATION.md) - Push to other OPC UA servers
- [GraphQL Integration](docs/GRAPHQL_INTEGRATION.md) - Modern query interface
- [InfluxDB + Grafana](docs/INFLUXDB_GRAFANA_INTEGRATION.md) - Time-series storage and visualization
- [Alarms & Notifications](docs/ALARMS_NOTIFICATIONS.md) - Alerting via email/Slack/SMS

All docs written in Patrick Ryan's signature style - snarky but helpful.

## Quick Start with Web UI 🔥

**The easiest way to get started** - Proper Python Flask web application:

1. **Start the server:**
   ```bash
   python opcua_server.py -c config/config_web_ui.json
   ```

2. **Open your browser:**
   ```
   http://localhost:5000/
   ```

3. **Explore the UI:**
   - 📊 **Dashboard** - Live metrics and tag values
   - 🏷️ **Tag Monitor** - Complete tag listing
   - 📡 **Publishers** - Enable/disable protocols
   - 🚨 **Alarms** - Active alarm monitoring
   - ⚙️ **Configuration** - System settings

**Features:**
- ✅ Python Flask Blueprint architecture
- ✅ Jinja2 server-side templates
- ✅ Vanilla JavaScript (no build step!)
- ✅ Fire-themed dark mode design
- ✅ Real-time updates (2-second intervals)
- ✅ ASCII art branding (Fireball Industries + EmberBurn)

See [docs/PYTHON_WEB_APP.md](docs/PYTHON_WEB_APP.md) for complete setup and customization.

## License

MIT License - Do whatever you want with this. We're not your mom.

## Acknowledgments

Built with [python-opcua](https://github.com/FreeOpcUa/python-opcua) because reinventing the wheel is overrated.

---

*Made with ☕ and mild existential dread about industrial automation security*
