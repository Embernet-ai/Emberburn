# Data Transformation Quick Start Guide

## 🚀 Quick Start (60 seconds)

### 1. Start Server with Transformations

```bash
python opcua_server.py -c config/config_transformations_demo.json
```

### 2. What You Get

The demo configuration creates:

**Source Tags:**
- `Temperature` (15-25°C)
- `SetPoint` (20-24°C)
- `Pressure` (95-105 kPa)
- `FlowRate` (40-60 L/min)
- `SecondaryFlow` (25-35 L/min)
- `Voltage` (230-250 V)
- `Current` (8-12 A)
- `PowerFactor` (0.90-0.98)

**Transformed Tags (Unit Conversions):**
- `Temperature_F` - Temperature in Fahrenheit
- `Pressure_PSI` - Pressure in PSI
- `FlowRate_GPM` - Flow in gallons per minute

**Computed Tags (Calculations):**
- `AverageTemperature` - Average of Temperature and SetPoint
- `TotalFlow` - Sum of primary and secondary flow
- `TemperatureDelta` - Absolute difference from setpoint
- `PowerCalculation` - V × I × PF (electrical power)

### 3. Access Transformed Tags

#### Via OPC UA Client
```python
from opcua import Client

client = Client("opc.tcp://localhost:4840")
client.connect()

# Read source tag
temp_c = client.get_node("ns=2;s=Temperature").get_value()
# >> 21.5

# Read transformed tag
temp_f = client.get_node("ns=2;s=Temperature_F").get_value()
# >> 70.7

# Read computed tag
avg_temp = client.get_node("ns=2;s=AverageTemperature").get_value()
# >> 21.75

client.disconnect()
```

#### Via REST API
```bash
# Get all tags (including transformed)
curl http://localhost:5000/api/tags

# Get specific transformed tag
curl http://localhost:5000/api/tags/Temperature_F

# Get computed tag
curl http://localhost:5000/api/tags/PowerCalculation
```

## 📝 Configuration Basics

### Unit Conversion

```json
{
  "type": "unit_conversion",
  "source_tag": "Temperature",
  "target_tag": "Temperature_F",
  "conversion": "celsius_to_fahrenheit"
}
```

### Scaling & Offset

```json
{
  "type": "scale_offset",
  "source_tag": "RawSensor",
  "target_tag": "CalibratedSensor",
  "scale": 1.05,
  "offset": 0.5
}
```

### Computed Tag

```json
{
  "target_tag": "AverageTemperature",
  "expression": "(Temperature + SetPoint) / 2",
  "dependencies": ["Temperature", "SetPoint"]
}
```

## 🔥 Common Unit Conversions

### Temperature
- `celsius_to_fahrenheit` / `fahrenheit_to_celsius`
- `celsius_to_kelvin` / `kelvin_to_celsius`
- `fahrenheit_to_kelvin` / `kelvin_to_fahrenheit`

### Pressure
- `kpa_to_psi` / `psi_to_kpa`
- `bar_to_psi` / `psi_to_bar`
- `kpa_to_bar` / `bar_to_kpa`

### Flow
- `lpm_to_gpm` / `gpm_to_lpm` (liters/min ↔ gallons/min)

### Length
- `mm_to_inch` / `inch_to_mm`
- `cm_to_inch` / `inch_to_cm`
- `m_to_ft` / `ft_to_m`

## 📊 Expression Examples

### Basic Math
```json
"expression": "Temperature * 1.8 + 32"
"expression": "(Pressure * 0.145038)"
"expression": "FlowRate + SecondaryFlow"
```

### Using Functions
```json
"expression": "abs(Temperature - SetPoint)"
"expression": "max(Temp1, Temp2, Temp3)"
"expression": "round(FlowRate * 60, 2)"
"expression": "sqrt(Voltage**2 + Current**2)"
```

### Conditional Logic
```json
"expression": "(Output / Input) * 100 if Input > 0 else 0"
"expression": "Temperature if Temperature < 100 else 100"
```

## 🎯 Use Cases

### 1. Multi-Unit Dashboard
Display same data in different units for different users:
```json
{
  "transformations": [
    {"source_tag": "Temperature", "target_tag": "Temperature_F", "conversion": "celsius_to_fahrenheit"},
    {"source_tag": "Temperature", "target_tag": "Temperature_K", "conversion": "celsius_to_kelvin"}
  ]
}
```

### 2. Sensor Calibration
Apply calibration factors to raw sensors:
```json
{
  "type": "scale_offset",
  "source_tag": "RawSensor",
  "target_tag": "CalibratedSensor",
  "scale": 1.05,
  "offset": -0.2,
  "description": "Apply calibration correction"
}
```

### 3. KPI Calculation
Calculate performance metrics:
```json
{
  "target_tag": "Efficiency",
  "expression": "(Output / Input) * 100 if Input > 0 else 0",
  "dependencies": ["Output", "Input"],
  "description": "System efficiency percentage"
}
```

### 4. Multi-Sensor Average
Create virtual sensor from multiple inputs:
```json
{
  "target_tag": "AveragePressure",
  "expression": "(Pressure1 + Pressure2 + Pressure3) / 3",
  "dependencies": ["Pressure1", "Pressure2", "Pressure3"]
}
```

## 🔧 Testing Transformations

### Check Logs
```bash
python opcua_server.py -c config/config_transformations_demo.json -l DEBUG

# Look for:
# INFO:DataPublisher:Data transformation started (3 transformations, 4 computed tags)
# DEBUG:DataPublisher:Wrote transformed tag Temperature_F = 70.7
# INFO:OPCUAServer:Created new transformed tag: AverageTemperature = 21.75
```

### Verify Tag Creation
```python
from opcua import Client

client = Client("opc.tcp://localhost:4840")
client.connect()

# Browse all tags
root = client.get_root_node()
objects = client.get_objects_node()
ignition = objects.get_child(["2:IgnitionEdge"])

# List all tags (including transformed)
for child in ignition.get_children():
    print(f"{child.get_browse_name()} = {child.get_value()}")

client.disconnect()
```

## 📖 Full Documentation

For complete reference, see:
- [DATA_TRANSFORMATION.md](../docs/DATA_TRANSFORMATION.md) - Complete guide
- [CONFIGURATION.md](../docs/CONFIGURATION.md) - Configuration reference
- [config_transformations.json](config_transformations.json) - All examples

## 🐛 Troubleshooting

### Transformation Not Working?
1. Check `enable_conversions: true` in config
2. Verify source_tag name matches exactly
3. Check logs with `-l DEBUG`

### Computed Tag Not Updating?
1. Verify all dependencies are available
2. Check expression syntax
3. Ensure `enable_computed: true`

### Expression Error?
1. Test expression in Python first
2. Check for division by zero
3. Verify all variables are in dependencies

## 💡 Pro Tips

1. **Start Simple**: Test unit conversions before complex expressions
2. **Use Descriptive Names**: `Temperature_F` better than `Temp2`
3. **Check Dependencies**: List ALL tags used in expression
4. **Test Expressions**: Validate in Python REPL first
5. **Monitor Performance**: Complex expressions add latency

## 🎓 Next Steps

1. ✅ Run the demo: `python opcua_server.py -c config/config_transformations_demo.json`
2. 📝 Modify `config_transformations.json` with your own transformations
3. 🔌 Combine with other publishers (MQTT, InfluxDB, etc.)
4. 📊 View in Grafana or other dashboards
5. 🚀 Deploy to production!

**Happy Transforming! 🔥**
