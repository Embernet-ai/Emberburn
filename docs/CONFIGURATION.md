# OPC UA Server Configuration Guide

## Overview

The OPC UA server is configured via a JSON file (`tags_config.json`) that defines all tags, their data types, and simulation behavior.

## Configuration File Structure

```json
{
  "TagName": {
    "type": "float|int|string|bool",
    "initial_value": <value>,
    "simulate": true|false,
    "simulation_type": "random|increment|sine|static",
    "description": "Tag description",
    ... additional parameters... 
  }
}
```

## Tag Parameters

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `type` | string | Data type:  `float`, `int`, `string`, or `bool` |
| `initial_value` | varies | Starting value for the tag |

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `simulate` | boolean | `false` | Enable value simulation |
| `simulation_type` | string | `"random"` | Simulation mode |
| `description` | string | `""` | Tag description |

## Simulation Types

### 1. Random Simulation

Generates random values within a specified range.

**Parameters:**
- `min` (number): Minimum value
- `max` (number): Maximum value

**Example:**
```json
{
  "Temperature": {
    "type": "float",
    "initial_value": 20.0,
    "simulate": true,
    "simulation_type": "random",
    "min": 15.0,
    "max": 25.0
  }
}
```

### 2. Increment Simulation

Increments value by a fixed amount each update.

**Parameters:**
- `increment` (number): Amount to add each update
- `max` (number, optional): Maximum value before rollover
- `reset_on_max` (boolean, optional): Reset to min when max reached

**Example:**
```json
{
  "Counter": {
    "type": "int",
    "initial_value": 0,
    "simulate": true,
    "simulation_type": "increment",
    "increment": 1,
    "max": 1000,
    "reset_on_max": true
  }
}
```

### 3. Sine Wave Simulation

Generates values following a sine wave pattern.

**Parameters:**
- `amplitude` (number): Wave amplitude
- `offset` (number): Center point of wave
- `period` (number): Period in seconds

**Example:**
```json
{
  "Level": {
    "type": "float",
    "initial_value": 50.0,
    "simulate":  true,
    "simulation_type": "sine",
    "amplitude": 30.0,
    "offset": 50.0,
    "period":  60
  }
}
```

### 4. Static (No Simulation)

Tag value remains constant unless written to.

**Example:**
```json
{
  "Status": {
    "type": "string",
    "initial_value": "Running",
    "simulate": false
  }
}
```

## Data Types

### Float
Floating-point numbers with decimal precision.

```json
{
  "Pressure": {
    "type":  "float",
    "initial_value": 101.325
  }
}
```

### Integer
Whole numbers only.

```json
{
  "Count": {
    "type": "int",
    "initial_value": 0
  }
}
```

### String
Text values. 

```json
{
  "Message": {
    "type": "string",
    "initial_value": "System OK"
  }
}
```

### Boolean
True/False values.

```json
{
  "AlarmActive": {
    "type": "bool",
    "initial_value": false
  }
}
```

## Environment Variables

The server can be configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `UPDATE_INTERVAL` | `2` | Tag update interval in seconds |
| `OPC_ENDPOINT` | `opc.tcp://0.0.0.0:4840/freeopcua/server/` | OPC UA endpoint |
| `OPC_SERVER_NAME` | `Python OPC UA Server` | Server name |
| `OPC_DEVICE_NAME` | `EdgeDevice` | Device/folder name |
| `OPC_NAMESPACE` | `http://opcua.edge.server` | OPC UA namespace |

### Setting Environment Variables

**In systemd service:**
```ini
[Service]
Environment="UPDATE_INTERVAL=5"
Environment="OPC_DEVICE_NAME=Tank1"
```

**In command line:**
```bash
UPDATE_INTERVAL=5 python3 opcua_server.py
```

**In LXC container:**
```bash
lxc exec opcua-server -- systemctl edit opcua-server
# Add Environment variables
```

## Command Line Options

```bash
python3 opcua_server.py --help

Options:
  -c, --config CONFIG     Path to config file (default: tags_config. json)
  -l, --log-level LEVEL   Logging level:  DEBUG, INFO, WARNING, ERROR
  -i, --interval SECONDS  Update interval in seconds
```

**Examples:**
```bash
# Use custom config file
python3 opcua_server.py -c my_tags.json

# Enable debug logging
python3 opcua_server.py -l DEBUG

# Set 5 second update interval
python3 opcua_server.py -i 5

# Combine options
python3 opcua_server.py -c custom. json -l INFO -i 1
```

## Complete Examples

### Manufacturing Line
See `config/example_tags_manufacturing.json`

### Process Control
See `config/example_tags_process_control.json`

### Simple Test Setup
See `config/example_tags_simple.json`

## Best Practices

1. **Use descriptive tag names**: Makes debugging easier
2. **Add descriptions**: Document what each tag represents
3. **Set realistic ranges**: Match real-world sensor ranges
4. **Use appropriate data types**: Don't use float for counters
5. **Test configuration**: Use `--log-level DEBUG` to verify tags load correctly

## Troubleshooting

### Tags not updating
- Check `"simulate": true` is set
- Verify `simulation_type` is valid
- Check logs:  `journalctl -u opcua-server -f`

### Invalid JSON
- Validate JSON syntax (use jsonlint. com)
- Check for trailing commas
- Ensure all brackets/braces are closed

### Type conversion errors
- Ensure `initial_value` matches `type`
- Check min/max values are correct type
- Review logs for specific error messages