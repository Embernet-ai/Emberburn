# OPC UA Server for Testing & Simulation

> Because sometimes you need fake industrial data that's more reliable than your actual production environment

A lightweight, configurable OPC UA server built with Python that simulates industrial process tags. Perfect for testing Ignition Edge, SCADA systems, or any OPC UA client without needing actual hardware. (Revolutionary concept, we know.)

## What Does This Do?

Spins up an OPC UA server with customizable tags that can:
- **Random values**: Because chaos is a feature, not a bug
- **Sine waves**: For that smooth, oscillating aesthetic
- **Incrementing counters**: They go up. Sometimes they reset. It's thrilling.
- **Static values**: For when you want your simulation to be as exciting as watching paint dry

Great for development, testing, demos, or just pretending you have a fully instrumented factory.

## Features

- 📊 Multiple data types (int, float, string, bool)
- 🎲 Configurable simulation modes (random, sine wave, increment, static)
- 🔧 JSON-based configuration (because YAML has enough problems)
- 🐳 Easy deployment with systemd service files
- 📝 Comprehensive logging (so you know exactly when things go sideways)
- 🚀 Zero hardware requirements (finally!)

## Quick Start

### Installation

```bash
# Clone this bad boy
git clone <your-repo-url>
cd Small-Application

# Install dependencies (there's literally one)
pip install -r requirements.txt
```

### Running the Server

```bash
# Basic usage
python opcua_server.py

# With custom config file
python opcua_server.py -c config/example_tags_manufacturing.json

# Debug mode (for when things inevitably break)
python opcua_server.py -l DEBUG

# Custom update interval
python opcua_server.py -i 0.5
```

The server starts at `opc.tcp://0.0.0.0:4840/freeopcua/server/` by default.

## Configuration

Tags are configured via JSON files. Check out [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full documentation (yes, we actually wrote docs).

### Basic Example

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
- opcua library (that's it, seriously)

## Project Structure

```
├── opcua_server.py              # Main server implementation
├── tags_config.json             # Default tag configuration
├── requirements.txt             # Dependencies (singular)
├── config/                      # Example configurations
├── docs/                        # Documentation
├── scripts/                     # Utility scripts
└── systemd/                     # Service files
```

## Common Use Cases

- **Development**: Test your OPC UA client without hardware
- **Demos**: Impress stakeholders with "live" data that never fails
- **Integration Testing**: Validate SCADA/HMI integrations
- **Training**: Teach OPC UA concepts without expensive PLCs
- **Chaos Engineering**: Because why not?

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

## License

MIT License - Do whatever you want with this. We're not your mom.

## Acknowledgments

Built with [python-opcua](https://github.com/FreeOpcUa/python-opcua) because reinventing the wheel is overrated.

---

*Made with ☕ and mild existential dread about industrial automation security*
