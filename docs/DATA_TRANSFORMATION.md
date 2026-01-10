# Data Transformation System

## Overview

The Data Transformation system provides real-time data processing capabilities including unit conversions, scaling/offset calculations, and expression-based computed tags. This allows you to transform raw sensor data, create virtual tags, and perform calculations on tag values without modifying the source data.

## Features

- **Unit Conversions**: Automatic conversion between measurement units (temperature, pressure, flow, etc.)
- **Scaling & Offset**: Linear transformations for sensor calibration and engineering unit conversion
- **Computed Tags**: Virtual tags calculated from expressions using multiple source tags
- **Safe Expression Evaluation**: Secure mathematical expression evaluation with standard math functions
- **Real-time Processing**: Transformations applied immediately as source tags update
- **Dynamic Tag Creation**: Automatically creates OPC UA tags for transformed and computed values

## Architecture

```
Source Tags (OPC UA) → DataTransformationPublisher → Transformed Tags (OPC UA)
                                  ↓
                          Other Publishers (MQTT, InfluxDB, etc.)
```

The transformation publisher:
1. Receives source tag updates via `publish()`
2. Applies configured transformations
3. Writes transformed values back to OPC UA server
4. Transformed tags are then published to other protocols

## Configuration

### Basic Structure

Transformations are configured in `config/config_transformations.json`:

```json
{
  "transformations": [
    { /* transformation definitions */ }
  ],
  "computed_tags": [
    { /* computed tag definitions */ }
  ],
  "settings": {
    "enable_conversions": true,
    "enable_computed": true,
    "update_interval": 1.0,
    "cache_size": 1000
  }
}
```

### Enabling in Publishers Config

Add to your `tags_config.json` or main configuration file:

```json
{
  "publishers": {
    "data_transformation": {
      "enabled": true,
      "transformations": [ /* ... */ ],
      "computed_tags": [ /* ... */ ],
      "enable_conversions": true,
      "enable_computed": true
    }
  }
}
```

## Transformation Types

### 1. Unit Conversion

Convert values between standard measurement units.

**Configuration:**
```json
{
  "type": "unit_conversion",
  "source_tag": "Temperature",
  "target_tag": "Temperature_F",
  "conversion": "celsius_to_fahrenheit",
  "description": "Convert temperature from Celsius to Fahrenheit"
}
```

**Available Conversions:**

#### Temperature
- `celsius_to_fahrenheit`, `fahrenheit_to_celsius`
- `celsius_to_kelvin`, `kelvin_to_celsius`
- `fahrenheit_to_kelvin`, `kelvin_to_fahrenheit`

#### Pressure
- `kpa_to_psi`, `psi_to_kpa`
- `bar_to_psi`, `psi_to_bar`
- `kpa_to_bar`, `bar_to_kpa`

#### Flow
- `lpm_to_gpm`, `gpm_to_lpm` (liters/min ↔ gallons/min)
- `lps_to_gps`, `gps_to_lps` (liters/sec ↔ gallons/sec)

#### Length
- `mm_to_inch`, `inch_to_mm`
- `cm_to_inch`, `inch_to_cm`
- `m_to_ft`, `ft_to_m`

#### Mass
- `kg_to_lb`, `lb_to_kg`
- `g_to_oz`, `oz_to_g`

#### Volume
- `l_to_gal`, `gal_to_l`
- `ml_to_floz`, `floz_to_ml`

#### Speed
- `mps_to_fps`, `fps_to_mps` (meters/sec ↔ feet/sec)
- `kph_to_mph`, `mph_to_kph`

**Example:**
```python
# Source: Temperature = 20.0°C
# Result: Temperature_F = 68.0°F
```

### 2. Scale and Offset

Apply linear transformation: `output = (input * scale) + offset`

**Configuration:**
```json
{
  "type": "scale_offset",
  "source_tag": "AnalogInput1",
  "target_tag": "AnalogInput1_Scaled",
  "scale": 0.1,
  "offset": -10,
  "description": "Scale analog input: (value * 0.1) - 10"
}
```

**Common Use Cases:**

1. **Sensor Calibration:**
   ```json
   {
     "scale": 1.05,
     "offset": 0.5,
     "description": "Apply 5% gain and 0.5 offset correction"
   }
   ```

2. **4-20mA to Engineering Units:**
   ```json
   {
     "scale": 6.25,
     "offset": -25,
     "description": "Convert 4-20mA (4-20) to 0-100 units"
   }
   ```

3. **Normalization:**
   ```json
   {
     "scale": 0.01,
     "offset": 0,
     "description": "Convert 0-100 to 0-1 range"
   }
   ```

**Example:**
```python
# Source: AnalogInput1 = 150.0
# Transformation: (150 * 0.1) + (-10) = 5.0
# Result: AnalogInput1_Scaled = 5.0
```

### 3. Alias

Create a simple copy/alias of a tag.

**Configuration:**
```json
{
  "type": "alias",
  "source_tag": "Temperature",
  "target_tag": "CurrentTemp",
  "description": "Create alias for temperature"
}
```

**Use Cases:**
- Rename tags for different systems
- Create multiple references to the same data
- Maintain backwards compatibility

### 4. Custom Expression

Apply a custom mathematical expression to a single tag.

**Configuration:**
```json
{
  "type": "custom",
  "source_tag": "Humidity",
  "target_tag": "Humidity_Percent",
  "expression": "value * 100",
  "description": "Convert humidity from 0-1 to percentage"
}
```

**Available in Expressions:**
- `value`: The current tag value
- All functions listed in "Safe Math Functions" below

**Example:**
```python
# Source: Humidity = 0.65
# Expression: value * 100
# Result: Humidity_Percent = 65.0
```

## Computed Tags

Computed tags are virtual tags calculated from expressions that reference multiple source tags.

### Configuration

```json
{
  "target_tag": "AverageTemperature",
  "expression": "(Temperature + SetPoint) / 2",
  "dependencies": ["Temperature", "SetPoint"],
  "description": "Average of Temperature and SetPoint"
}
```

### Components

- **target_tag**: Name of the virtual tag to create
- **expression**: Mathematical expression to evaluate
- **dependencies**: List of source tags used in the expression
- **description**: Human-readable description

### Expression Variables

In computed tag expressions, you can reference any tag listed in `dependencies` by name:

```python
# Dependencies: ["Voltage", "Current", "PowerFactor"]
# Expression: Voltage * Current * PowerFactor
```

### Safe Math Functions

The following functions are available in all expressions:

#### Basic Math
- `abs(x)`: Absolute value
- `round(x)`: Round to nearest integer
- `min(a, b, ...)`: Minimum value
- `max(a, b, ...)`: Maximum value
- `sum([a, b, ...])`: Sum of values
- `pow(x, y)`: x raised to power y

#### Advanced Math
- `sqrt(x)`: Square root
- `sin(x)`, `cos(x)`, `tan(x)`: Trigonometric functions
- `log(x)`: Natural logarithm
- `log10(x)`: Base-10 logarithm
- `exp(x)`: Exponential (e^x)
- `floor(x)`: Round down
- `ceil(x)`: Round up

### Example Computed Tags

#### 1. Average of Multiple Sensors
```json
{
  "target_tag": "AverageTemperature",
  "expression": "(Temperature + SetPoint) / 2",
  "dependencies": ["Temperature", "SetPoint"]
}
```

#### 2. Total Flow Rate
```json
{
  "target_tag": "TotalFlow",
  "expression": "FlowRate + SecondaryFlow",
  "dependencies": ["FlowRate", "SecondaryFlow"]
}
```

#### 3. Temperature Deviation
```json
{
  "target_tag": "TemperatureDelta",
  "expression": "abs(Temperature - SetPoint)",
  "dependencies": ["Temperature", "SetPoint"]
}
```

#### 4. Power Calculation
```json
{
  "target_tag": "PowerCalculation",
  "expression": "Voltage * Current * PowerFactor",
  "dependencies": ["Voltage", "Current", "PowerFactor"]
}
```

#### 5. Conditional Expression
```json
{
  "target_tag": "Efficiency",
  "expression": "(Output / Input) * 100 if Input > 0 else 0",
  "dependencies": ["Output", "Input"],
  "description": "Calculate efficiency percentage (avoid division by zero)"
}
```

#### 6. Normalization
```json
{
  "target_tag": "NormalizedPressure",
  "expression": "(Pressure - 100) / (1000 - 100)",
  "dependencies": ["Pressure"],
  "description": "Normalize pressure to 0-1 range (100-1000 kPa)"
}
```

#### 7. Unit Conversion in Expression
```json
{
  "target_tag": "RunningHours",
  "expression": "RunTime / 3600",
  "dependencies": ["RunTime"],
  "description": "Convert runtime from seconds to hours"
}
```

#### 8. Complex Calculation
```json
{
  "target_tag": "HeatIndex",
  "expression": "-42.379 + 2.04901523*Temperature + 10.14333127*Humidity - 0.22475541*Temperature*Humidity",
  "dependencies": ["Temperature", "Humidity"],
  "description": "Calculate heat index (simplified Rothfusz equation)"
}
```

## Complete Configuration Example

```json
{
  "transformations": [
    {
      "type": "unit_conversion",
      "source_tag": "Temperature",
      "target_tag": "Temperature_F",
      "conversion": "celsius_to_fahrenheit",
      "description": "Convert temperature to Fahrenheit"
    },
    {
      "type": "unit_conversion",
      "source_tag": "Pressure",
      "target_tag": "Pressure_PSI",
      "conversion": "kpa_to_psi",
      "description": "Convert pressure to PSI"
    },
    {
      "type": "unit_conversion",
      "source_tag": "FlowRate",
      "target_tag": "FlowRate_GPM",
      "conversion": "lpm_to_gpm",
      "description": "Convert flow to gallons per minute"
    },
    {
      "type": "scale_offset",
      "source_tag": "AnalogInput1",
      "target_tag": "AnalogInput1_Scaled",
      "scale": 0.1,
      "offset": -10,
      "description": "4-20mA sensor calibration"
    },
    {
      "type": "custom",
      "source_tag": "Humidity",
      "target_tag": "Humidity_Percent",
      "expression": "value * 100",
      "description": "Convert to percentage"
    }
  ],
  "computed_tags": [
    {
      "target_tag": "AverageTemperature",
      "expression": "(Temperature + SetPoint) / 2",
      "dependencies": ["Temperature", "SetPoint"],
      "description": "Average temperature"
    },
    {
      "target_tag": "TotalFlow",
      "expression": "FlowRate + SecondaryFlow",
      "dependencies": ["FlowRate", "SecondaryFlow"],
      "description": "Combined flow rate"
    },
    {
      "target_tag": "PowerCalculation",
      "expression": "Voltage * Current * PowerFactor",
      "dependencies": ["Voltage", "Current", "PowerFactor"],
      "description": "Electrical power consumption"
    },
    {
      "target_tag": "Efficiency",
      "expression": "(Output / Input) * 100 if Input > 0 else 0",
      "dependencies": ["Output", "Input"],
      "description": "System efficiency percentage"
    }
  ],
  "settings": {
    "enable_conversions": true,
    "enable_computed": true,
    "update_interval": 1.0,
    "cache_size": 1000
  }
}
```

## Usage Examples

### Starting the Server with Transformations

```bash
# Using example configuration
python opcua_server.py -c config/example_tags_with_transformations.json

# The transformation publisher will automatically:
# 1. Create transformed tags (Temperature_F, Pressure_PSI, etc.)
# 2. Calculate computed tags (AverageTemperature, TotalFlow, etc.)
# 3. Update values in real-time as source tags change
```

### Accessing Transformed Tags

Transformed and computed tags appear as regular OPC UA tags:

```python
# OPC UA Client Example
from opcua import Client

client = Client("opc.tcp://localhost:4840")
client.connect()

# Read source tag
temp_celsius = client.get_node("ns=2;s=Temperature").get_value()
# >> 20.5

# Read transformed tag
temp_fahrenheit = client.get_node("ns=2;s=Temperature_F").get_value()
# >> 68.9

# Read computed tag
avg_temp = client.get_node("ns=2;s=AverageTemperature").get_value()
# >> 21.25

client.disconnect()
```

### Monitoring Transformations

Check server logs for transformation activity:

```
INFO:DataPublisher:Data transformation started (7 transformations, 4 computed tags)
INFO:OPCUAServer:Transformation publisher write callback configured
DEBUG:DataPublisher:Wrote transformed tag Temperature_F = 68.9
DEBUG:DataPublisher:Wrote transformed tag Pressure_PSI = 14.7
INFO:OPCUAServer:Created new transformed tag: AverageTemperature = 21.25
```

## API Reference

### DataTransformationPublisher Class

#### Methods

##### `publish(tag_name, value, timestamp=None)`
Store source tag value and trigger transformations.

```python
transformation_pub.publish("Temperature", 20.5, time.time())
```

##### `add_transformation(transformation)`
Add a transformation at runtime.

```python
transformation_pub.add_transformation({
    "type": "unit_conversion",
    "source_tag": "NewTag",
    "target_tag": "NewTag_Converted",
    "conversion": "celsius_to_fahrenheit"
})
```

##### `add_computed_tag(computed_tag)`
Add a computed tag at runtime.

```python
transformation_pub.add_computed_tag({
    "target_tag": "NewComputed",
    "expression": "Tag1 + Tag2",
    "dependencies": ["Tag1", "Tag2"]
})
```

##### `get_transformed_tags()`
Get all transformed tag values.

```python
transformed = transformation_pub.get_transformed_tags()
# {
#   "Temperature_F": {"value": 68.9, "timestamp": 1234567890.123},
#   "AverageTemperature": {"value": 21.25, "timestamp": 1234567890.123}
# }
```

##### `get_available_conversions()`
Get list of available unit conversions.

```python
conversions = transformation_pub.get_available_conversions()
# ['bar_to_kpa', 'bar_to_psi', 'celsius_to_fahrenheit', ...]
```

##### `set_write_callback(callback)`
Set callback function for writing transformed tags.

```python
def write_tag(tag_name, value):
    # Write to OPC UA or other destination
    pass

transformation_pub.set_write_callback(write_tag)
```

## Performance Considerations

### Optimization Tips

1. **Expression Complexity**: Keep expressions simple for better performance
   - Good: `Temperature * 1.8 + 32`
   - Avoid: Nested loops or complex conditionals

2. **Dependency Management**: Minimize dependencies for computed tags
   - Only list tags actually used in the expression
   - Fewer dependencies = faster updates

3. **Caching**: Transformed values are automatically cached
   - No need to recalculate if source hasn't changed
   - Cache size configurable via `settings.cache_size`

4. **Update Frequency**: Adjust based on your needs
   - Default: Transforms on every source tag update
   - Consider throttling for high-frequency tags

### Performance Metrics

Typical transformation performance:
- Unit conversion: < 0.1 ms
- Scale/offset: < 0.1 ms
- Computed tag (3 dependencies): < 0.5 ms
- Complex expression: < 2 ms

## Security

### Expression Safety

The transformation system uses safe expression evaluation:

- **Restricted Builtins**: No access to file system, network, or system functions
- **Whitelist Functions**: Only approved math functions available
- **No Imports**: Cannot import modules or execute arbitrary code
- **Sandboxed**: Expressions run in isolated context

**Safe:**
```python
"Temperature * 1.8 + 32"
"sqrt(Voltage**2 + Current**2)"
"max(Temp1, Temp2, Temp3)"
```

**Blocked:**
```python
"__import__('os').system('rm -rf /')"  # ❌ No imports
"open('/etc/passwd').read()"            # ❌ No file access
"eval(user_input)"                      # ❌ No nested eval
```

### Best Practices

1. **Validate Configuration**: Review transformation configs before deployment
2. **Test Expressions**: Verify computed tags produce expected results
3. **Monitor Logs**: Watch for expression evaluation errors
4. **Limit Complexity**: Keep expressions simple and auditable
5. **Version Control**: Track transformation config changes

## Troubleshooting

### Common Issues

#### 1. Transformation Not Applied

**Symptom**: Source tag updates but transformed tag doesn't change

**Solutions**:
- Check `enable_conversions: true` in settings
- Verify source_tag name matches exactly
- Check logs for error messages
- Confirm transformation publisher is enabled

```bash
# Check logs
grep "Data transformation started" server.log
grep "transformation" server.log
```

#### 2. Computed Tag Not Updating

**Symptom**: Computed tag remains at initial value or 0

**Solutions**:
- Verify all dependencies are available
- Check expression syntax
- Ensure `enable_computed: true` in settings
- Confirm dependencies list matches expression variables

```python
# Debugging
transformation_pub.source_tags  # Check available source tags
transformation_pub.get_transformed_tags()  # Check computed values
```

#### 3. Expression Evaluation Error

**Symptom**: "Error evaluating expression" in logs

**Solutions**:
- Check for division by zero
- Verify all variables in expression are in dependencies
- Ensure expression uses only allowed functions
- Test expression in Python REPL first

```python
# Test expression
context = {"Temperature": 20.5, "SetPoint": 22.0}
result = eval("(Temperature + SetPoint) / 2", {"__builtins__": {}}, context)
```

#### 4. Tag Not Created

**Symptom**: Transformed tag doesn't appear in OPC UA

**Solutions**:
- Check write callback is configured
- Verify OPC UA server is running
- Ensure tag name doesn't conflict with existing tag
- Check server has permission to create tags

```bash
# Verify callback setup
grep "Transformation publisher write callback configured" server.log
```

### Debug Mode

Enable debug logging for detailed transformation information:

```bash
python opcua_server.py -l DEBUG

# You'll see:
# DEBUG:DataPublisher:Wrote transformed tag Temperature_F = 68.9
# DEBUG:DataPublisher:Created new transformed tag: AverageTemperature = 21.25
```

## Integration Examples

### With MQTT

Publish both source and transformed tags:

```json
{
  "publishers": {
    "mqtt": {
      "enabled": true,
      "broker": "localhost",
      "port": 1883,
      "topic_prefix": "factory/sensors"
    },
    "data_transformation": {
      "enabled": true,
      "transformations": [
        {
          "source_tag": "Temperature",
          "target_tag": "Temperature_F",
          "type": "unit_conversion",
          "conversion": "celsius_to_fahrenheit"
        }
      ]
    }
  }
}
```

Result:
```
factory/sensors/Temperature: 20.5
factory/sensors/Temperature_F: 68.9
```

### With InfluxDB

Store transformed values for analysis:

```json
{
  "publishers": {
    "influxdb": {
      "enabled": true,
      "url": "http://localhost:8086",
      "token": "your-token",
      "org": "your-org",
      "bucket": "sensors"
    },
    "data_transformation": {
      "enabled": true,
      "computed_tags": [
        {
          "target_tag": "Efficiency",
          "expression": "(Output / Input) * 100",
          "dependencies": ["Output", "Input"]
        }
      ]
    }
  }
}
```

Query in InfluxDB:
```flux
from(bucket: "sensors")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "Efficiency")
```

### With Grafana

Display both raw and computed values:

```sql
-- Show temperature in both units
SELECT mean("Temperature") AS "Celsius",
       mean("Temperature_F") AS "Fahrenheit"
FROM "sensors"
WHERE time > now() - 1h
GROUP BY time(1m)
```

## Advanced Topics

### Dynamic Transformation Rules

Add transformations programmatically:

```python
from publishers import DataTransformationPublisher

# Get transformation publisher instance
transform_pub = publisher_manager.get_publisher("DataTransformationPublisher")

# Add new transformation
transform_pub.add_transformation({
    "type": "scale_offset",
    "source_tag": "NewSensor",
    "target_tag": "CalibratedSensor",
    "scale": 1.05,
    "offset": -0.2
})

# Add computed tag
transform_pub.add_computed_tag({
    "target_tag": "DerivedValue",
    "expression": "NewSensor * 2.5 + OtherTag",
    "dependencies": ["NewSensor", "OtherTag"]
})
```

### Custom Conversion Functions

Extend available conversions:

```python
# In publishers.py, add to UNIT_CONVERSIONS dict
UNIT_CONVERSIONS = {
    # ... existing conversions ...
    
    # Custom conversions
    'custom_scale': lambda x: x * 2.54 + 10,
    'nonlinear_conversion': lambda x: math.pow(x, 2) / 100,
}
```

### Transformation Chains

Create multi-stage transformations:

```json
{
  "transformations": [
    {
      "source_tag": "RawSensor",
      "target_tag": "CalibratedSensor",
      "type": "scale_offset",
      "scale": 1.05,
      "offset": 0.5
    },
    {
      "source_tag": "CalibratedSensor",
      "target_tag": "EngineeringUnits",
      "type": "scale_offset",
      "scale": 10,
      "offset": 0
    }
  ]
}
```

## References

- [OPC UA Server Documentation](../README.md)
- [Publishers Configuration](CONFIGURATION.md)
- [SQLite Persistence](SQLITE_PERSISTENCE.md)
- [Tag Discovery API](TAG_DISCOVERY_API.md)

## Support

For issues or questions:
- Check [Troubleshooting](#troubleshooting) section
- Review server logs with DEBUG level
- Create an issue on GitHub
- Contact: your-friendly-neighborhood-engineer@example.com
