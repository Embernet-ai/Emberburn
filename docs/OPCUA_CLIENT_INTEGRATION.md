# OPC UA Client Mode - Integration Guide

## Overview

The OPC UA Client Mode allows your server to **push data to other OPC UA servers**. Instead of only being an OPC UA server that clients connect to, your system can now also act as an OPC UA client and write values to remote OPC UA servers.

This is incredibly useful for:
- **Pushing data to Ignition's OPC UA server** for visualization and control
- **Writing to historian systems** (OSIsoft PI, Canary, etc.) with OPC UA interfaces
- **Data replication** across multiple OPC UA servers for redundancy
- **Gateway scenarios** where you aggregate data and push to central servers
- **Cloud integration** with OPC UA cloud platforms

---

## Key Features ✨

### 1. **Multiple Server Support**
Connect to multiple OPC UA servers simultaneously and push the same tag data to all of them.

### 2. **Auto-Reconnect**
Automatically reconnects to servers if connection is lost. Configurable reconnection interval.

### 3. **Node Auto-Creation**
Optionally create nodes on the remote server if they don't exist (requires write permissions).

### 4. **Flexible Node Mapping**
- **Automatic**: Use base_node + tag_name pattern
- **Explicit**: Map specific tags to specific node IDs

### 5. **Authentication Support**
- Anonymous connections
- Username/password authentication
- Certificate-based security (planned)

### 6. **Type Conversion**
Automatically converts Python types to OPC UA DataValue variants:
- `bool` → Boolean
- `int` → Int32
- `float` → Double
- `str` → String

---

## Configuration

### Basic Configuration

```json
{
  "publishers": {
    "opcua_client": {
      "enabled": true,
      "servers": [
        {
          "url": "opc.tcp://remote-server:4841",
          "name": "Ignition Server",
          "namespace": 2,
          "base_node": "ns=2;s=Gateway/",
          "auto_create_nodes": true
        }
      ],
      "reconnect_interval": 5
    }
  }
}
```

### Advanced Multi-Server Configuration

```json
{
  "publishers": {
    "opcua_client": {
      "enabled": true,
      "servers": [
        {
          "url": "opc.tcp://ignition:4841",
          "name": "Ignition Production",
          "username": "admin",
          "password": "password",
          "namespace": 2,
          "base_node": "ns=2;s=Gateway/",
          "auto_create_nodes": true
        },
        {
          "url": "opc.tcp://historian:4840",
          "name": "Historian",
          "namespace": 1,
          "auto_create_nodes": false,
          "node_mapping": {
            "Temperature": "ns=1;s=Process/Reactor/Temperature",
            "Pressure": "ns=1;s=Process/Reactor/Pressure",
            "FlowRate": "ns=1;s=Process/Reactor/FlowRate"
          }
        },
        {
          "url": "opc.tcp://backup:4842",
          "name": "Backup Server",
          "namespace": 3,
          "base_node": "ns=3;s=Backup/",
          "auto_create_nodes": true
        }
      ],
      "reconnect_interval": 10
    }
  }
}
```

---

## Configuration Parameters

### Server Configuration

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | - | OPC UA server endpoint (e.g., `opc.tcp://server:4841`) |
| `name` | string | No | url | Friendly name for logging |
| `username` | string | No | "" | Username for authentication |
| `password` | string | No | "" | Password for authentication |
| `namespace` | int | No | 2 | Namespace index for node creation |
| `base_node` | string | No | "" | Base node path (e.g., `ns=2;s=Gateway/`) |
| `auto_create_nodes` | bool | No | false | Create nodes if they don't exist |
| `node_mapping` | object | No | {} | Explicit tag-to-node mappings |

### Global Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reconnect_interval` | int | 5 | Seconds between reconnection attempts |

---

## Usage Examples

### Example 1: Push to Ignition Edge

```bash
python opcua_server.py config/config_opcua_client.json
```

**config_opcua_client.json:**
```json
{
  "publishers": {
    "opcua_client": {
      "enabled": true,
      "servers": [
        {
          "url": "opc.tcp://localhost:4841",
          "name": "Ignition Server",
          "namespace": 2,
          "base_node": "ns=2;s=Gateway/",
          "auto_create_nodes": true
        }
      ]
    }
  }
}
```

**What happens:**
- Your tags are written to Ignition at: `ns=2;s=Gateway/Temperature`, `ns=2;s=Gateway/Pressure`, etc.
- Nodes are automatically created if they don't exist
- Reconnects automatically if Ignition restarts

---

### Example 2: Push to Multiple Servers (Redundancy)

```json
{
  "publishers": {
    "opcua_client": {
      "enabled": true,
      "servers": [
        {
          "url": "opc.tcp://primary-scada:4841",
          "name": "Primary SCADA",
          "username": "gateway",
          "password": "secure123",
          "namespace": 2,
          "base_node": "ns=2;s=Gateway1/"
        },
        {
          "url": "opc.tcp://backup-scada:4841",
          "name": "Backup SCADA",
          "username": "gateway",
          "password": "secure123",
          "namespace": 2,
          "base_node": "ns=2;s=Gateway1/"
        }
      ]
    }
  }
}
```

**What happens:**
- Same data pushed to both primary and backup SCADA systems
- If primary goes down, backup continues receiving data
- Automatic failover and reconnection

---

### Example 3: Historian Integration with Node Mapping

```json
{
  "publishers": {
    "opcua_client": {
      "enabled": true,
      "servers": [
        {
          "url": "opc.tcp://historian.company.com:4840",
          "name": "PI Historian",
          "username": "pi-interface",
          "password": "historian-pass",
          "auto_create_nodes": false,
          "node_mapping": {
            "Temperature": "ns=1;s=Plant/Area1/Reactor1/Temperature",
            "Pressure": "ns=1;s=Plant/Area1/Reactor1/Pressure",
            "FlowRate": "ns=1;s=Plant/Area1/Reactor1/FlowRate",
            "Counter": "ns=1;s=Plant/Area1/Reactor1/Counter"
          }
        }
      ]
    }
  }
}
```

**What happens:**
- Tags are written to specific historian nodes
- No auto-creation (historian has predefined structure)
- Explicit mapping ensures correct historian paths

---

### Example 4: Combined with Other Publishers

You can use OPC UA Client Mode alongside other publishers:

```json
{
  "publishers": {
    "opcua_client": {
      "enabled": true,
      "servers": [
        {
          "url": "opc.tcp://ignition:4841",
          "name": "Ignition",
          "namespace": 2,
          "base_node": "ns=2;s=Gateway/"
        }
      ]
    },
    "mqtt": {
      "enabled": true,
      "broker": "mqtt.cloud.com",
      "port": 8883,
      "topic_prefix": "industrial/plant1"
    },
    "kafka": {
      "enabled": true,
      "bootstrap_servers": ["kafka:9092"],
      "topic": "sensor-data"
    },
    "rest_api": {
      "enabled": true,
      "port": 5001
    }
  }
}
```

**Result:** Data flows to:
- Ignition via OPC UA
- Cloud via MQTT
- Data lake via Kafka
- Local monitoring via REST API

---

## Integration Scenarios

### Scenario 1: Ignition Gateway Setup

**Goal:** Push data from edge device to Ignition server

```
┌─────────────────┐         OPC UA Client          ┌──────────────────┐
│  Your OPC UA    │──────────────────────────────▶ │  Ignition        │
│  Server (Edge)  │    opc.tcp://ignition:4841     │  OPC UA Server   │
│                 │                                 │                  │
│  - Temperature  │                                 │  Gateway/        │
│  - Pressure     │                                 │  ├─Temperature   │
│  - FlowRate     │                                 │  ├─Pressure      │
└─────────────────┘                                 │  └─FlowRate      │
                                                    └──────────────────┘
```

**Configuration:**
```json
{
  "opcua_client": {
    "enabled": true,
    "servers": [{
      "url": "opc.tcp://ignition:4841",
      "namespace": 2,
      "base_node": "ns=2;s=Gateway/",
      "auto_create_nodes": true
    }]
  }
}
```

**Ignition Setup:**
1. Enable OPC UA server in Ignition Gateway
2. Configure security (allow anonymous or create user)
3. Your tags will appear under `Gateway/` folder
4. Use in Vision/Perspective components

---

### Scenario 2: Cloud OPC UA Platform

**Goal:** Push to cloud OPC UA service (Azure IoT, AWS IoT, etc.)

```
┌─────────────────┐         Secure OPC UA          ┌──────────────────┐
│  Your Server    │──────────────────────────────▶ │  Cloud Platform  │
│  (On-Premise)   │  opc.tcp://cloud.azure.com     │  OPC UA Server   │
│                 │  (TLS + username/password)     │                  │
└─────────────────┘                                 └──────────────────┘
```

**Configuration:**
```json
{
  "opcua_client": {
    "enabled": true,
    "servers": [{
      "url": "opc.tcp://opcua.azureiotcentral.com:4841",
      "username": "device-001",
      "password": "iot-token-12345",
      "namespace": 1,
      "base_node": "ns=1;s=Devices/Device001/",
      "auto_create_nodes": true
    }]
  }
}
```

---

### Scenario 3: Historian Replication

**Goal:** Write to OSIsoft PI, Canary, or other historians

```
┌─────────────────┐         OPC UA                 ┌──────────────────┐
│  Data Source    │──────────────────────────────▶ │  PI Historian    │
│                 │                                 │  OPC UA Interface│
│  - Sensor Data  │                                 │                  │
│  - Process Vars │                                 │  Predefined      │
└─────────────────┘                                 │  Tag Structure   │
                                                    └──────────────────┘
```

**Configuration:**
```json
{
  "opcua_client": {
    "enabled": true,
    "servers": [{
      "url": "opc.tcp://pi-server:4840",
      "username": "pi-interface",
      "password": "secure-password",
      "auto_create_nodes": false,
      "node_mapping": {
        "Temperature": "ns=1;s=Plant.Area1.Temp",
        "Pressure": "ns=1;s=Plant.Area1.Press"
      }
    }]
  }
}
```

---

## Node Addressing

### Method 1: Automatic (base_node + tag_name)

**Configuration:**
```json
{
  "base_node": "ns=2;s=Gateway/",
  "auto_create_nodes": true
}
```

**Result:**
- Tag `Temperature` → `ns=2;s=Gateway/Temperature`
- Tag `Pressure` → `ns=2;s=Gateway/Pressure`

### Method 2: Explicit Mapping

**Configuration:**
```json
{
  "node_mapping": {
    "Temperature": "ns=2;s=Custom/Path/To/Temp",
    "Pressure": "ns=1;i=1001"
  }
}
```

**Result:**
- Tag `Temperature` → `ns=2;s=Custom/Path/To/Temp`
- Tag `Pressure` → `ns=1;i=1001` (numeric identifier)

### Node ID Formats

OPC UA supports multiple node ID types:

1. **String**: `ns=2;s=Gateway/Temperature`
2. **Numeric**: `ns=1;i=1001`
3. **GUID**: `ns=3;g=12345678-1234-1234-1234-123456789012`
4. **Opaque**: `ns=4;b=base64data==`

Most common: **String IDs** (like Ignition, KEPServerEX)

---

## Testing

### Test with UaExpert

1. **Connect to Your Server** (data source)
   - Connect to `opc.tcp://localhost:4840`
   - Browse your tags

2. **Connect to Remote Server** (destination)
   - Connect to `opc.tcp://remote-server:4841`
   - Verify nodes are being created/updated

3. **Monitor Live Data**
   - Subscribe to nodes on remote server
   - Should see values updating in real-time

### Test with Python Client

```python
from opcua import Client

# Connect to the remote server (destination)
client = Client("opc.tcp://localhost:4841")
client.connect()

try:
    # Get the node
    node = client.get_node("ns=2;s=Gateway/Temperature")
    
    # Read value
    value = node.get_value()
    print(f"Temperature: {value}")
    
    # Monitor for changes
    import time
    for _ in range(10):
        value = node.get_value()
        print(f"Temperature: {value}")
        time.sleep(1)
        
finally:
    client.disconnect()
```

---

## Troubleshooting

### Issue: Cannot Connect to Remote Server

**Error:** `Failed to connect to Server: Connection refused`

**Solutions:**
1. Verify server URL and port: `opc.tcp://server:4841`
2. Check firewall rules (allow port 4841)
3. Ensure remote OPC UA server is running
4. Test connectivity: `telnet server 4841`

### Issue: Authentication Failed

**Error:** `BadUserAccessDenied`

**Solutions:**
1. Verify username/password in config
2. Check remote server's user configuration
3. Ensure user has write permissions
4. Try anonymous connection first (remove username/password)

### Issue: Cannot Write to Nodes

**Error:** `BadNotWritable`

**Solutions:**
1. Check if `auto_create_nodes` is enabled
2. Verify remote node has write permissions
3. Use UaExpert to check node attributes (writable?)
4. Ensure correct node ID in `node_mapping`

### Issue: Nodes Not Being Created

**Error:** Node not found, auto-creation fails

**Solutions:**
1. Verify `auto_create_nodes: true` in config
2. Check user has permission to create nodes
3. Verify namespace index is correct
4. Check remote server logs for permission errors

### Issue: Connection Drops Frequently

**Solutions:**
1. Increase `reconnect_interval` in config
2. Check network stability
3. Verify server timeout settings
4. Use persistent connection (already implemented)

---

## Performance Considerations

### Connection Overhead

- Each server connection uses a persistent TCP socket
- Minimal overhead after initial connection
- Reconnection handled in background thread

### Write Performance

- Direct OPC UA writes are synchronous
- Typical latency: 5-50ms per write
- For high-frequency updates (>100 Hz), consider batching

### Multiple Servers

- Writes happen sequentially to each server
- 3 servers × 10ms = 30ms total per tag update
- For critical latency, prioritize server order

### Optimization Tips

1. **Use node_mapping** for static node structures (faster lookup)
2. **Disable auto_create_nodes** in production (faster writes)
3. **Increase reconnect_interval** for stable networks (less overhead)
4. **Batch updates** if possible (future enhancement)

---

## Security Best Practices

### 1. Use Authentication

Always use username/password for production:
```json
{
  "username": "gateway-user",
  "password": "secure-password-here"
}
```

### 2. Network Security

- Use VPN for remote connections
- Whitelist IP addresses on firewall
- Use OPC UA security policies (future enhancement)

### 3. Credential Management

**Don't hardcode passwords!** Use environment variables:

```python
import os
import json

config = json.load(open('config.json'))
config['publishers']['opcua_client']['servers'][0]['password'] = os.getenv('OPCUA_PASSWORD')
```

### 4. Certificate-Based Security

Coming soon:
- X.509 certificates
- SignAndEncrypt security policy
- Application instance certificates

---

## Advanced Features (Future)

### Planned Enhancements

1. **Certificate Support**: Full X.509 certificate handling
2. **Batch Writes**: Write multiple nodes in one call
3. **Method Calls**: Call methods on remote servers
4. **Subscription Mode**: Subscribe to remote nodes (bidirectional)
5. **Historical Data**: Write historical values with timestamps
6. **Retry Logic**: Configurable retry strategies

---

## Common Use Cases Summary

| Use Case | Configuration | Benefits |
|----------|---------------|----------|
| **Ignition Integration** | Single server, auto-create | Easy setup, dynamic tags |
| **Historian Logging** | Single server, node_mapping | Predefined structure |
| **Redundancy** | Multiple servers, same paths | High availability |
| **Gateway Aggregation** | Multiple sources → 1 destination | Centralized data |
| **Cloud Upload** | TLS + auth | Secure remote access |
| **Local + Cloud** | Combined with MQTT/Kafka | Hybrid architecture |

---

## Quick Reference

### Start Server with OPC UA Client

```bash
python opcua_server.py config/config_opcua_client.json
```

### Minimal Config

```json
{
  "publishers": {
    "opcua_client": {
      "enabled": true,
      "servers": [{
        "url": "opc.tcp://server:4841"
      }]
    }
  }
}
```

### Check Logs

```
INFO: Connected to OPC UA server: Server (opc.tcp://server:4841)
DEBUG: Wrote Temperature=25.5 to Server
DEBUG: Wrote Pressure=101.3 to Server
```

### Dependencies

```bash
pip install opcua  # Same library used for server
```

---

## Summary

The OPC UA Client Mode turns your server into a **bidirectional gateway**:

- **Server Mode** (original): Other clients connect to you
- **Client Mode** (new): You push data to other servers

This enables sophisticated architectures:
- Edge → Cloud
- PLC → SCADA
- Gateway → Multiple Historians
- Local → Ignition

All while maintaining the other publishers (MQTT, Kafka, WebSocket, etc.) for a complete multi-protocol solution! 🚀
