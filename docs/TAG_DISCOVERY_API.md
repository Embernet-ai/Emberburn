# 🔥 EmberBurn Tag Discovery API
## Dynamic Tag Browsing with Metadata

### Overview

The Tag Discovery API provides comprehensive tag browsing capabilities with rich metadata support. Browse available tags dynamically, filter by category or type, search by name, and access detailed metadata including units, ranges, descriptions, and quality indicators.

**Key Features:**
- Dynamic tag discovery with real-time values
- Rich metadata (units, ranges, descriptions, categories)
- Filtering by category and data type
- Full-text search across tag names and descriptions
- Quality indicators and write permissions
- Integration with REST API and GraphQL
- Web UI with live filtering and search

---

## REST API Endpoints

### GET `/api/tags/discovery`

Discover all available tags with complete metadata.

**Query Parameters:**
- `type` (optional): Filter by data type (float, int, bool, string)
- `search` (optional): Search term (matches tag name or description)
- `category` (optional): Filter by category

**Response:**
```json
{
  "tags": [
    {
      "name": "Temperature",
      "value": 22.5,
      "timestamp": 1704902400.0,
      "type": "float",
      "description": "Ambient temperature sensor",
      "units": "°C",
      "min": 15.0,
      "max": 25.0,
      "category": "environmental",
      "quality": "good",
      "writable": false,
      "simulation_type": "random"
    },
    {
      "name": "ProductionCounter",
      "value": 1542,
      "timestamp": 1704902401.0,
      "type": "int",
      "description": "Production line piece counter",
      "units": "pieces",
      "min": null,
      "max": 10000,
      "category": "production",
      "quality": "good",
      "writable": true,
      "simulation_type": "increment"
    }
  ],
  "count": 2,
  "total_tags": 20
}
```

**Example Requests:**

```bash
# Get all tags
curl http://localhost:9090/api/tags/discovery

# Filter by type
curl http://localhost:9090/api/tags/discovery?type=float

# Search tags
curl http://localhost:9090/api/tags/discovery?search=temperature

# Filter by category
curl http://localhost:9090/api/tags/discovery?category=process

# Combine filters
curl "http://localhost:9090/api/tags/discovery?type=float&category=environmental"
```

---

### GET `/api/tags/<tag_name>/metadata`

Get detailed metadata for a specific tag.

**Response:**
```json
{
  "name": "FlowRate",
  "current_value": 105.3,
  "timestamp": 1704902400.0,
  "metadata": {
    "type": "float",
    "description": "Liquid flow rate through main pipeline",
    "units": "L/min",
    "min": 80.0,
    "max": 120.0,
    "category": "process",
    "quality": "good",
    "writable": false,
    "simulation_type": "sine"
  }
}
```

**Example:**
```bash
curl http://localhost:9090/api/tags/Temperature/metadata
```

---

### GET `/api/tags/categories`

Get all tag categories.

**Response:**
```json
{
  "categories": [
    "alarms",
    "control",
    "environmental",
    "equipment",
    "process",
    "production",
    "status",
    "storage",
    "utilities"
  ],
  "count": 9
}
```

**Example:**
```bash
curl http://localhost:9090/api/tags/categories
```

---

### GET `/api/tags/types`

Get all data types used by tags.

**Response:**
```json
{
  "types": [
    "bool",
    "float",
    "int",
    "string"
  ],
  "count": 4
}
```

**Example:**
```bash
curl http://localhost:9090/api/tags/types
```

---

## GraphQL API

### Enhanced Tag Type

The GraphQL TagType now includes comprehensive metadata:

```graphql
type Tag {
  name: String!
  value: String
  type: String!
  timestamp: Float
  description: String
  units: String
  min_value: Float
  max_value: Float
  category: String
  quality: String
  writable: Boolean
  simulation_type: String
}
```

### Queries

**Get all tags with metadata:**
```graphql
query {
  tags {
    name
    value
    type
    description
    units
    category
    quality
    writable
  }
}
```

**Get specific tag:**
```graphql
query {
  tag(name: "Temperature") {
    name
    value
    type
    description
    units
    min_value
    max_value
    category
    quality
    timestamp
  }
}
```

**Filter tags:**
```graphql
query {
  tags(filter: "temp") {
    name
    value
    description
    units
  }
}
```

**Example with curl:**
```bash
curl -X POST http://localhost:5002/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{ tags { name value type description units category } }"
  }'
```

---

## Tag Metadata Schema

### Required Fields
- `name`: Tag identifier
- `type`: Data type (float, int, bool, string)
- `value`: Current value

### Optional Metadata
- `description`: Human-readable tag description
- `units`: Engineering units (°C, kPa, RPM, etc.)
- `min`: Minimum expected/allowed value
- `max`: Maximum expected/allowed value
- `category`: Tag grouping (process, control, alarms, etc.)
- `quality`: Quality indicator (good, bad, uncertain)
- `writable`: Whether tag can be written to
- `simulation_type`: Simulation mode (random, sine, increment, static)

### Example Tag Configuration

```json
{
  "Temperature": {
    "type": "float",
    "initial_value": 20.0,
    "simulate": true,
    "simulation_type": "random",
    "min": 15.0,
    "max": 25.0,
    "description": "Ambient temperature sensor",
    "units": "°C",
    "category": "environmental",
    "quality": "good",
    "writable": false
  },
  "SetpointPressure": {
    "type": "float",
    "initial_value": 101.0,
    "simulate": false,
    "description": "Pressure control setpoint",
    "units": "kPa",
    "category": "control",
    "quality": "good",
    "writable": true,
    "min": 90.0,
    "max": 110.0
  }
}
```

---

## Tag Categories

Standard categories for organizing tags:

| Category | Description | Examples |
|----------|-------------|----------|
| **environmental** | Environmental sensors | Temperature, Humidity |
| **process** | Process measurements | Pressure, FlowRate, pH |
| **production** | Production tracking | ProductionCounter, BatchID |
| **control** | Control setpoints | SetpointTemp, ValvePosition |
| **equipment** | Equipment status | MotorSpeed, Vibration |
| **alarms** | Alarm indicators | AlarmActive, FaultStatus |
| **status** | System status | RunStatus, SystemMode |
| **storage** | Storage/inventory | TankLevel, InventoryCount |
| **utilities** | Utility consumption | PowerConsumption, WaterUsage |
| **general** | Uncategorized tags | Default category |

---

## Web UI Integration

The EmberBurn Web UI includes an enhanced Tag Discovery page with:

### Features

**1. Real-time Tag Table**
- Live updating tag values (2-second refresh)
- Color-coded by quality (good=green, bad=red, uncertain=yellow)
- Writable indicator (✎ symbol)
- Units displayed inline with values

**2. Filtering & Search**
- Category dropdown filter
- Real-time search box
- Filters apply instantly without page reload

**3. Tag Details Modal**
- Click "Details" button on any tag
- Shows complete metadata
- Current value with timestamp
- Range information
- Quality and write status

### Screenshot Walkthrough

```
┌─────────────────────────────────────────────────────────────┐
│ 🏷️ Tag Discovery & Monitor                                  │
│ Browse and monitor all available tags with metadata         │
├─────────────────────────────────────────────────────────────┤
│ Search Tags: [______________]  Category: [All Categories ▼] │
├─────────────────────────────────────────────────────────────┤
│ Tag Name       │ Value      │ Type  │ Description          │
├────────────────┼────────────┼───────┼──────────────────────┤
│ Temperature ✎  │ 22.5 °C    │ float │ Ambient temp sensor  │
│ FlowRate       │ 105.3 L/min│ float │ Main pipeline flow   │
│ RunStatus      │ true       │ bool  │ Production running   │
└─────────────────────────────────────────────────────────────┘
```

---

## Python API Usage

### Using requests library

```python
import requests

# Discover all tags
response = requests.get('http://localhost:9090/api/tags/discovery')
data = response.json()

for tag in data['tags']:
    print(f"{tag['name']}: {tag['value']} {tag['units']}")
    print(f"  Description: {tag['description']}")
    print(f"  Category: {tag['category']}")

# Filter by category
response = requests.get(
    'http://localhost:9090/api/tags/discovery',
    params={'category': 'process'}
)
process_tags = response.json()['tags']

# Search tags
response = requests.get(
    'http://localhost:9090/api/tags/discovery',
    params={'search': 'temperature'}
)

# Get specific tag metadata
response = requests.get('http://localhost:9090/api/tags/Temperature/metadata')
metadata = response.json()
print(f"Range: {metadata['metadata']['min']} - {metadata['metadata']['max']}")
```

### Using GraphQL client

```python
import requests

graphql_url = 'http://localhost:5002/graphql'

query = '''
{
  tags {
    name
    value
    type
    description
    units
    category
  }
}
'''

response = requests.post(graphql_url, json={'query': query})
data = response.json()

for tag in data['data']['tags']:
    print(f"{tag['name']}: {tag['value']} {tag['units']}")
```

---

## JavaScript/Node.js Usage

```javascript
// Fetch all tags with metadata
async function discoverTags() {
    const response = await fetch('http://localhost:9090/api/tags/discovery');
    const data = await response.json();
    
    console.log(`Found ${data.count} tags`);
    
    data.tags.forEach(tag => {
        console.log(`${tag.name}: ${tag.value} ${tag.units || ''}`);
        console.log(`  Category: ${tag.category}, Type: ${tag.type}`);
    });
}

// Filter by category
async function getProcessTags() {
    const response = await fetch(
        'http://localhost:9090/api/tags/discovery?category=process'
    );
    const data = await response.json();
    return data.tags;
}

// Search tags
async function searchTags(term) {
    const response = await fetch(
        `http://localhost:9090/api/tags/discovery?search=${encodeURIComponent(term)}`
    );
    const data = await response.json();
    return data.tags;
}

// Get tag metadata
async function getTagMetadata(tagName) {
    const response = await fetch(
        `http://localhost:9090/api/tags/${tagName}/metadata`
    );
    return await response.json();
}
```

---

## Use Cases

### 1. Dynamic HMI Tag Binding

```javascript
// Automatically populate HMI dropdown with available tags
async function populateTagDropdown(categoryFilter = null) {
    const url = categoryFilter 
        ? `http://localhost:9090/api/tags/discovery?category=${categoryFilter}`
        : 'http://localhost:9090/api/tags/discovery';
    
    const response = await fetch(url);
    const data = await response.json();
    
    const dropdown = document.getElementById('tag-selector');
    dropdown.innerHTML = data.tags.map(tag => 
        `<option value="${tag.name}">${tag.name} - ${tag.description}</option>`
    ).join('');
}
```

### 2. Tag Browser with Filtering

```python
def browse_tags(category=None, data_type=None, search=None):
    """Browse tags with multiple filters."""
    params = {}
    if category:
        params['category'] = category
    if data_type:
        params['type'] = data_type
    if search:
        params['search'] = search
    
    response = requests.get(
        'http://localhost:9090/api/tags/discovery',
        params=params
    )
    
    return response.json()['tags']

# Usage
process_floats = browse_tags(category='process', data_type='float')
temperature_tags = browse_tags(search='temp')
```

### 3. Tag Documentation Generator

```python
import requests

def generate_tag_documentation():
    """Generate markdown documentation for all tags."""
    response = requests.get('http://localhost:9090/api/tags/discovery')
    tags = response.json()['tags']
    
    # Group by category
    by_category = {}
    for tag in tags:
        cat = tag['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(tag)
    
    # Generate markdown
    md = "# Tag Documentation\\n\\n"
    
    for category, tags in sorted(by_category.items()):
        md += f"## {category.title()}\\n\\n"
        md += "| Tag Name | Type | Units | Range | Description |\\n"
        md += "|----------|------|-------|-------|-------------|\\n"
        
        for tag in sorted(tags, key=lambda t: t['name']):
            range_str = f"{tag['min']}-{tag['max']}" if tag['min'] else "N/A"
            md += f"| {tag['name']} | {tag['type']} | {tag['units'] or 'N/A'} | {range_str} | {tag['description']} |\\n"
        
        md += "\\n"
    
    return md

# Generate and save
doc = generate_tag_documentation()
with open('TAG_REFERENCE.md', 'w') as f:
    f.write(doc)
```

### 4. Alarm Configuration from Tags

```python
def create_alarms_from_tags():
    """Auto-generate alarm configurations from tag metadata."""
    response = requests.get('http://localhost:9090/api/tags/discovery')
    tags = response.json()['tags']
    
    alarms = []
    
    for tag in tags:
        # Create high alarm if max is defined
        if tag['max'] is not None:
            alarms.append({
                'name': f"{tag['name']}_High",
                'tag': tag['name'],
                'condition': '>',
                'threshold': tag['max'],
                'priority': 'warning',
                'message': f"{tag['name']} above maximum ({tag['max']} {tag['units']})"
            })
        
        # Create low alarm if min is defined
        if tag['min'] is not None:
            alarms.append({
                'name': f"{tag['name']}_Low",
                'tag': tag['name'],
                'condition': '<',
                'threshold': tag['min'],
                'priority': 'warning',
                'message': f"{tag['name']} below minimum ({tag['min']} {tag['units']})"
            })
    
    return alarms
```

---

## Performance Considerations

### Caching

The Tag Discovery API reads from the in-memory tag cache, making it extremely fast:

- **Response time**: < 5ms for 100 tags
- **Memory usage**: ~1KB per tag
- **Concurrent requests**: Thousands per second

### Filtering Performance

Filters are applied server-side to reduce bandwidth:

```bash
# Without filter: Returns all 100 tags (~15KB)
curl http://localhost:9090/api/tags/discovery

# With filter: Returns 10 tags (~1.5KB)
curl http://localhost:9090/api/tags/discovery?category=process
```

### Recommendations

1. **Use category filters** when possible to reduce payload
2. **Cache tag metadata** on the client side (changes infrequently)
3. **Subscribe to value changes** via WebSocket for real-time updates
4. **Use GraphQL** for selective field queries

---

## Best Practices

1. **Consistent Naming**: Use clear, descriptive tag names
2. **Complete Metadata**: Always provide description and units
3. **Logical Categories**: Group related tags together
4. **Set Ranges**: Define min/max for numeric tags
5. **Quality Indicators**: Mark questionable data as "uncertain"
6. **Write Permissions**: Only mark truly writable tags as such
7. **Documentation**: Use descriptions to explain tag purpose

---

## Migration Guide

### Upgrading Existing Configs

Old format:
```json
{
  "Temperature": {
    "type": "float",
    "initial_value": 20.0,
    "simulate": true,
    "min": 15.0,
    "max": 25.0
  }
}
```

Enhanced format:
```json
{
  "Temperature": {
    "type": "float",
    "initial_value": 20.0,
    "simulate": true,
    "simulation_type": "random",
    "min": 15.0,
    "max": 25.0,
    "description": "Ambient temperature sensor",
    "units": "°C",
    "category": "environmental",
    "quality": "good",
    "writable": false
  }
}
```

**The old format still works!** Metadata fields are optional. Defaults:
- `description`: "" (empty)
- `units`: "" (empty)
- `category`: "general"
- `quality`: "good"
- `writable`: false

---

## Troubleshooting

### Tags Missing Metadata

**Problem**: Tag shows up but has no description/units

**Solution**: Check your tag config file includes metadata:
```json
{
  "YourTag": {
    "description": "Your description here",
    "units": "your units"
  }
}
```

### Category Filter Not Working

**Problem**: Filtering by category returns no results

**Solution**: Verify category names match exactly (case-sensitive):
```bash
# Check available categories
curl http://localhost:9090/api/tags/categories

# Use exact category name
curl http://localhost:9090/api/tags/discovery?category=process
```

### GraphQL Not Showing Metadata

**Problem**: GraphQL queries missing metadata fields

**Solution**: The GraphQL server caches metadata on startup. Restart the server or check that `_setup_tag_metadata()` was called.

---

## CTO's Wisdom 🔥

*"Look, I know it's tempting to just call your tags 'Tag1', 'Tag2', 'Tag3', but when you're troubleshooting at 2 AM and trying to figure out which sensor is throwing alarms, you'll thank past-you for writing actual descriptions. Future-you is watching. Don't let them down."*

. Patrick Ryan, CTO, Fireball Industries

*"And for the love of all that is holy, USE UNITS. I don't care if 'everyone knows' it's in Celsius. Someone WILL assume Fahrenheit. Someone WILL multiply by the wrong conversion factor. Save yourself the pain. Add. The. Units."*

---

## Additional Resources

- [REST API Documentation](REST_API.md)
- [GraphQL Integration](GRAPHQL_INTEGRATION.md)
- [Web UI Guide](WEB_UI_GUIDE.md)
- [Tag Configuration](CONFIGURATION.md)

---

**EmberBurn** - *Where industrial data meets fire-tested reliability* 🔥
