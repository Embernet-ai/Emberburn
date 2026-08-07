# 🔥 EmberBurn SQLite Persistence Layer
## Protocol #14: Data Persistence, Historical Storage & Audit Logging

### Overview

The SQLite Persistence Layer provides comprehensive local data storage for the EmberBurn platform. It stores historical tag values, audit logs, system events, and publisher statistics in a lightweight, embedded SQLite database with configurable retention policies and automatic cleanup.

**Key Features:**
- Historical tag value storage with timestamps
- Comprehensive audit logging for compliance
- System event tracking
- Publisher statistics logging
- Thread-safe batch operations
- Configurable retention policies
- Automatic database cleanup and vacuuming
- Query APIs for historical analysis
- Zero external dependencies (SQLite is built into Python)

---

## Installation

### Requirements

SQLite3 is included with Python - no additional installation needed!

### Configuration

Create or edit `config/config_sqlite_persistence.json`:

```json
{
  "sqlite_persistence": {
    "enabled": true,
    "description": "SQLite Persistence - Local data storage",
    "config": {
      "db_path": "emberburn_data.db",
      "retention_days": 30,
      "batch_size": 100,
      "enable_tag_history": true,
      "enable_audit_log": true,
      "auto_vacuum": true,
      "cleanup_interval_hours": 24,
      "max_db_size_mb": 1000,
      "export_enabled": false,
      "export_path": "./exports/",
      "compression": false
    }
  }
}
```

**Configuration Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable/disable SQLite persistence |
| `db_path` | string | `"emberburn_data.db"` | Path to SQLite database file |
| `retention_days` | integer | `30` | Days to retain historical data |
| `batch_size` | integer | `100` | Number of records to batch before flushing |
| `enable_tag_history` | boolean | `true` | Store historical tag values |
| `enable_audit_log` | boolean | `true` | Store audit log entries |
| `auto_vacuum` | boolean | `true` | Automatically reclaim disk space |
| `cleanup_interval_hours` | integer | `24` | Hours between automatic cleanup runs |
| `max_db_size_mb` | integer | `1000` | Maximum database size (MB) before warning |
| `export_enabled` | boolean | `false` | Enable automatic data export |
| `export_path` | string | `"./exports/"` | Path for data exports |
| `compression` | boolean | `false` | Compress exported data |

---

## Database Schema

### Table: `tag_history`

Stores historical tag values with timestamps.

```sql
CREATE TABLE tag_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_name TEXT NOT NULL,
    value TEXT NOT NULL,
    data_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_tag_history_tag_name ON tag_history(tag_name);
CREATE INDEX idx_tag_history_timestamp ON tag_history(timestamp DESC);
CREATE INDEX idx_tag_history_created_at ON tag_history(created_at DESC);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `tag_name`: Name of the tag (e.g., "Temperature", "Pressure")
- `value`: Tag value stored as text
- `data_type`: Data type (int, float, string, bool)
- `timestamp`: ISO 8601 timestamp of tag update
- `created_at`: Database insertion timestamp

**Sample Data:**
```
id | tag_name    | value   | data_type | timestamp                  | created_at
---+-------------+---------+-----------+----------------------------+----------------------------
1  | Temperature | 72.5    | float     | 2026-01-10T10:30:15.123456 | 2026-01-10 10:30:15.123456
2  | Pressure    | 101325  | int       | 2026-01-10T10:30:15.234567 | 2026-01-10 10:30:15.234567
3  | Running     | true    | bool      | 2026-01-10T10:30:15.345678 | 2026-01-10 10:30:15.345678
```

---

### Table: `audit_log`

Stores audit trail for compliance and security.

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    event_source TEXT NOT NULL,
    event_details TEXT,
    severity TEXT DEFAULT 'info',
    user TEXT,
    timestamp TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX idx_audit_log_timestamp ON audit_log(timestamp DESC);
CREATE INDEX idx_audit_log_severity ON audit_log(severity);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `event_type`: Type of event (system, tag, publisher, alarm, user)
- `event_source`: Source component that triggered event
- `event_details`: Detailed description of the event
- `severity`: Severity level (info, warning, error, critical)
- `user`: User who triggered event (optional)
- `timestamp`: ISO 8601 timestamp
- `created_at`: Database insertion timestamp

**Event Types:**
- `system`: System-level events (startup, shutdown, configuration changes)
- `tag`: Tag-related events (creation, deletion, value changes)
- `publisher`: Publisher events (start, stop, errors)
- `alarm`: Alarm events (triggered, acknowledged, cleared)
- `user`: User actions (login, config changes, manual operations)

**Sample Data:**
```
id | event_type | event_source       | event_details                  | severity | user  | timestamp
---+------------+--------------------+--------------------------------+----------+-------+---------------------------
1  | system     | SQLitePersistence  | Publisher started              | info     | NULL  | 2026-01-10T10:00:00.000000
2  | publisher  | MQTT               | Connected to broker            | info     | NULL  | 2026-01-10T10:00:01.123456
3  | alarm      | HighTemperature    | Alarm triggered (value: 85.3)  | critical | NULL  | 2026-01-10T10:15:30.456789
4  | user       | WebUI              | User changed retention policy  | warning  | admin | 2026-01-10T10:20:00.789012
```

---

### Table: `system_events`

Stores system-level events for troubleshooting.

```sql
CREATE TABLE system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    severity TEXT DEFAULT 'info',
    details TEXT,
    timestamp TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_system_events_timestamp ON system_events(timestamp DESC);
CREATE INDEX idx_system_events_severity ON system_events(severity);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `event_type`: Type of system event (startup, shutdown, error, config, etc.)
- `message`: Short event message
- `severity`: Severity level (info, warning, error, critical)
- `details`: Detailed information (stack traces, JSON data, etc.)
- `timestamp`: ISO 8601 timestamp
- `created_at`: Database insertion timestamp

**Sample Data:**
```
id | event_type | message                        | severity | details             | timestamp
---+------------+--------------------------------+----------+---------------------+---------------------------
1  | startup    | EmberBurn system started       | info     | Version 1.0.0       | 2026-01-10T10:00:00.000000
2  | error      | Failed to connect to Kafka     | error    | Connection timeout  | 2026-01-10T10:05:30.123456
3  | config     | Retention policy changed       | warning  | 30d -> 60d          | 2026-01-10T10:20:00.456789
```

---

### Table: `publisher_stats`

Stores publisher performance statistics.

```sql
CREATE TABLE publisher_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher_name TEXT NOT NULL,
    status TEXT NOT NULL,
    messages_sent INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    last_message TEXT,
    timestamp TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_publisher_stats_publisher ON publisher_stats(publisher_name, timestamp DESC);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `publisher_name`: Name of the publisher
- `status`: Current status (running, stopped, error)
- `messages_sent`: Cumulative message count
- `errors`: Cumulative error count
- `last_message`: Last message content (truncated)
- `timestamp`: ISO 8601 timestamp
- `created_at`: Database insertion timestamp

**Sample Data:**
```
id | publisher_name | status  | messages_sent | errors | last_message              | timestamp
---+----------------+---------+---------------+--------+---------------------------+---------------------------
1  | MQTT           | running | 10543         | 0      | {"tag":"Temp","val":72.5} | 2026-01-10T10:30:00.000000
2  | Kafka          | error   | 8721          | 5      | Connection failed         | 2026-01-10T10:30:00.123456
3  | InfluxDB       | running | 9876          | 2      | {"temp":72.5,"ts":...}    | 2026-01-10T10:30:00.234567
```

---

## API Reference

### Publishing Tag History

Tag history is automatically recorded when data is published:

```python
# In your OPC UA server code
publisher_manager.publish_to_all("Temperature", 72.5, timestamp)

# SQLite automatically stores:
# - tag_name: "Temperature"
# - value: "72.5"
# - data_type: "float"
# - timestamp: Current ISO timestamp
```

### Logging Audit Events

```python
# Get SQLite publisher instance
sqlite_pub = None
for pub in publisher_manager.publishers:
    if isinstance(pub, SQLitePersistencePublisher):
        sqlite_pub = pub
        break

# Log audit event
if sqlite_pub:
    sqlite_pub._log_audit_event(
        event_type="user",
        event_source="WebUI",
        event_details="User changed tag configuration",
        severity="warning",
        user="admin"
    )
```

### Logging System Events

```python
# Log system event
if sqlite_pub:
    sqlite_pub.log_system_event(
        event_type="startup",
        message="EmberBurn system started successfully",
        severity="info",
        details="Version 1.0.0, 13 protocols enabled"
    )
```

### Logging Publisher Statistics

```python
# Log publisher stats
if sqlite_pub:
    sqlite_pub.log_publisher_stats(
        publisher_name="MQTT",
        status="running",
        messages_sent=10543,
        errors=0,
        last_message='{"tag":"Temperature","value":72.5}'
    )
```

### Querying Tag History

```python
# Get last 1000 temperature readings
history = sqlite_pub.get_tag_history(
    tag_name="Temperature",
    limit=1000
)

# Get history within time range
from datetime import datetime, timedelta
end_time = datetime.now()
start_time = end_time - timedelta(hours=24)

history = sqlite_pub.get_tag_history(
    tag_name="Temperature",
    start_time=start_time.isoformat(),
    end_time=end_time.isoformat(),
    limit=10000
)

# Results format:
# [(tag_name, value, data_type, timestamp), ...]
# [('Temperature', '72.5', 'float', '2026-01-10T10:30:15.123456'), ...]
```

### Querying Audit Log

```python
# Get all critical audit events
audit_log = sqlite_pub.get_audit_log(
    severity="critical",
    limit=100
)

# Get alarm-related audit events from last 7 days
from datetime import datetime, timedelta
start_time = (datetime.now() - timedelta(days=7)).isoformat()

audit_log = sqlite_pub.get_audit_log(
    event_type="alarm",
    start_time=start_time,
    limit=1000
)

# Results format:
# [(event_type, event_source, event_details, severity, user, timestamp), ...]
```

### Getting Database Statistics

```python
# Get database stats
stats = sqlite_pub.get_database_stats()

print(f"Tag history records: {stats['tag_history_count']}")
print(f"Audit log entries: {stats['audit_log_count']}")
print(f"Database size: {stats['database_size_mb']} MB")
print(f"Oldest record: {stats['oldest_record']}")
print(f"Newest record: {stats['newest_record']}")

# Output:
# Tag history records: 543210
# Audit log entries: 12345
# Database size: 125.4 MB
# Oldest record: 2025-12-11T10:00:00.000000
# Newest record: 2026-01-10T10:30:00.000000
```

### Manual Data Cleanup

```python
# Manually trigger cleanup (removes records older than retention_days)
sqlite_pub.cleanup_old_data()

# This is automatically run every cleanup_interval_hours
# Default: every 24 hours
```

---

## Integration Examples

### REST API Endpoints

Add these endpoints to your REST API publisher to expose historical data:

```python
# In RESTAPIPublisher class

@app.route('/api/history/<tag_name>', methods=['GET'])
def get_tag_history(tag_name):
    """Get historical tag values."""
    start_time = request.args.get('start_time')
    end_time = request.args.get('end_time')
    limit = int(request.args.get('limit', 1000))
    
    # Get SQLite publisher
    sqlite_pub = get_sqlite_publisher()
    if not sqlite_pub:
        return jsonify({'error': 'SQLite persistence not enabled'}), 500
    
    history = sqlite_pub.get_tag_history(tag_name, start_time, end_time, limit)
    
    return jsonify({
        'tag_name': tag_name,
        'count': len(history),
        'history': [
            {
                'tag_name': h[0],
                'value': h[1],
                'data_type': h[2],
                'timestamp': h[3]
            }
            for h in history
        ]
    })

@app.route('/api/audit', methods=['GET'])
def get_audit_log():
    """Get audit log entries."""
    event_type = request.args.get('event_type')
    severity = request.args.get('severity')
    limit = int(request.args.get('limit', 1000))
    
    sqlite_pub = get_sqlite_publisher()
    if not sqlite_pub:
        return jsonify({'error': 'SQLite persistence not enabled'}), 500
    
    audit_log = sqlite_pub.get_audit_log(event_type, severity, None, None, limit)
    
    return jsonify({
        'count': len(audit_log),
        'entries': [
            {
                'event_type': a[0],
                'event_source': a[1],
                'event_details': a[2],
                'severity': a[3],
                'user': a[4],
                'timestamp': a[5]
            }
            for a in audit_log
        ]
    })

@app.route('/api/database/stats', methods=['GET'])
def get_db_stats():
    """Get database statistics."""
    sqlite_pub = get_sqlite_publisher()
    if not sqlite_pub:
        return jsonify({'error': 'SQLite persistence not enabled'}), 500
    
    stats = sqlite_pub.get_database_stats()
    return jsonify(stats)
```

### Grafana Dashboard Integration

Use Grafana's SQLite plugin to create dashboards:

```sql
-- Query: Tag value trend
SELECT 
    timestamp,
    CAST(value AS REAL) as value
FROM tag_history
WHERE tag_name = 'Temperature'
  AND timestamp >= datetime('now', '-24 hours')
ORDER BY timestamp DESC;

-- Query: Alarm frequency
SELECT 
    event_source as alarm_name,
    COUNT(*) as trigger_count
FROM audit_log
WHERE event_type = 'alarm'
  AND timestamp >= datetime('now', '-7 days')
GROUP BY event_source
ORDER BY trigger_count DESC;

-- Query: Publisher error rate
SELECT 
    publisher_name,
    SUM(errors) as total_errors,
    SUM(messages_sent) as total_messages,
    CAST(SUM(errors) AS REAL) / NULLIF(SUM(messages_sent), 0) * 100 as error_rate
FROM publisher_stats
WHERE timestamp >= datetime('now', '-24 hours')
GROUP BY publisher_name;
```

### Python Analysis Script

```python
#!/usr/bin/env python3
"""
EmberBurn Data Analysis Script
Analyze historical tag data and generate reports.
"""

import sqlite3
from datetime import datetime, timedelta
import statistics

def analyze_tag_statistics(db_path, tag_name, hours=24):
    """Analyze tag statistics over time period."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    
    cursor.execute("""
        SELECT value, timestamp 
        FROM tag_history 
        WHERE tag_name = ? AND timestamp >= ?
        ORDER BY timestamp
    """, (tag_name, cutoff))
    
    data = cursor.fetchall()
    conn.close()
    
    if not data:
        return None
    
    # Convert to floats (assuming numeric tag)
    values = [float(row[0]) for row in data]
    
    return {
        'tag_name': tag_name,
        'count': len(values),
        'min': min(values),
        'max': max(values),
        'mean': statistics.mean(values),
        'median': statistics.median(values),
        'stdev': statistics.stdev(values) if len(values) > 1 else 0,
        'range': max(values) - min(values)
    }

# Usage
stats = analyze_tag_statistics('emberburn_data.db', 'Temperature', hours=24)
print(f"Temperature Statistics (Last 24 Hours):")
print(f"  Samples: {stats['count']}")
print(f"  Min: {stats['min']:.2f}")
print(f"  Max: {stats['max']:.2f}")
print(f"  Mean: {stats['mean']:.2f}")
print(f"  Median: {stats['median']:.2f}")
print(f"  StdDev: {stats['stdev']:.2f}")
```

---

## Performance Optimization

### Batch Writing

The persistence layer uses batch writing to minimize disk I/O:

```python
# Configuration
"batch_size": 100  # Flush to disk every 100 records

# This balances:
# - Write performance (larger batches = fewer disk operations)
# - Data safety (smaller batches = less data loss on crash)
# - Memory usage (larger batches = more RAM)
```

**Recommendations:**
- **High-frequency tags (>10 Hz)**: `batch_size: 500-1000`
- **Medium-frequency tags (1-10 Hz)**: `batch_size: 100-500`
- **Low-frequency tags (<1 Hz)**: `batch_size: 10-100`

### Database Vacuuming

SQLite databases can become fragmented over time. Enable auto-vacuum:

```json
{
  "auto_vacuum": true
}
```

This automatically reclaims disk space when records are deleted. Without vacuuming, deleted records leave empty pages.

### Index Optimization

The persistence layer creates indexes on commonly-queried columns:

```sql
-- These indexes are created automatically
CREATE INDEX idx_tag_history_tag_name ON tag_history(tag_name);
CREATE INDEX idx_tag_history_timestamp ON tag_history(timestamp DESC);
CREATE INDEX idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX idx_audit_log_severity ON audit_log(severity);
```

**Query Performance:**
- Tag lookup by name: O(log n) with index vs O(n) without
- Time range queries: O(log n + k) where k = results returned
- Without indexes: Full table scan for every query

### Retention Policy

Set appropriate retention based on storage and query needs:

```json
{
  "retention_days": 30  // Keep 30 days of data
}
```

**Storage Estimates:**
- **150 tags @ 1 Hz, 30 days**: ~388M records ≈ 15 GB
- **150 tags @ 0.1 Hz, 90 days**: ~117M records ≈ 4.5 GB
- **50 tags @ 10 Hz, 7 days**: ~302M records ≈ 11 GB

**Formula**: Records = (tags × frequency_hz × 86400 × days)

### Thread Safety

All database operations use a lock for thread safety:

```python
self.db_lock = threading.Lock()

with self.db_lock:
    cursor = self.connection.cursor()
    # ... database operations ...
```

This prevents concurrent write conflicts when multiple publishers are active.

---

## Backup & Recovery

### Manual Backup

```bash
# Simple file copy (database must not be in use)
cp emberburn_data.db emberburn_data.db.backup

# Online backup using SQLite command
sqlite3 emberburn_data.db ".backup emberburn_data_backup.db"

# Export to SQL dump
sqlite3 emberburn_data.db .dump > emberburn_data.sql
```

### Automated Backup Script

```bash
#!/bin/bash
# backup_emberburn.sh

DB_PATH="emberburn_data.db"
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/emberburn_${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

# Compress backup
gzip "$BACKUP_FILE"

# Keep only last 30 backups
ls -t ${BACKUP_DIR}/emberburn_*.db.gz | tail -n +31 | xargs rm -f

echo "Backup completed: ${BACKUP_FILE}.gz"
```

### Restore from Backup

```bash
# Restore from backup file
cp emberburn_data_backup.db emberburn_data.db

# Restore from SQL dump
sqlite3 emberburn_data.db < emberburn_data.sql

# Restore from compressed backup
gunzip -c emberburn_20260110_103000.db.gz > emberburn_data.db
```

---

## Troubleshooting

### Database is Locked

**Problem:** `sqlite3.OperationalError: database is locked`

**Causes:**
- Another process has the database open
- Long-running transaction not committed
- File system locking issues

**Solutions:**
```python
# 1. Increase timeout in connection
self.connection = sqlite3.connect(self.db_path, timeout=30.0)

# 2. Use WAL mode for better concurrency
cursor.execute("PRAGMA journal_mode=WAL")

# 3. Check for stuck processes
lsof emberburn_data.db  # Linux/Mac
```

### Database Growing Too Large

**Problem:** Database file exceeds `max_db_size_mb`

**Solutions:**
```python
# 1. Reduce retention period
"retention_days": 7  # Instead of 30

# 2. Manually cleanup old data
sqlite_pub.cleanup_old_data()

# 3. Vacuum database
import sqlite3
conn = sqlite3.connect('emberburn_data.db')
conn.execute('VACUUM')
conn.close()

# 4. Export and purge old data
# See backup section above
```

### Slow Queries

**Problem:** Queries taking > 1 second

**Solutions:**
```sql
-- 1. Analyze query plan
EXPLAIN QUERY PLAN 
SELECT * FROM tag_history 
WHERE tag_name = 'Temperature' 
  AND timestamp >= '2026-01-01';

-- 2. Rebuild indexes
REINDEX;

-- 3. Analyze statistics
ANALYZE;

-- 4. Add missing indexes
CREATE INDEX idx_custom ON tag_history(tag_name, timestamp);
```

### Batch Not Flushing

**Problem:** Recent data not appearing in database

**Cause:** Batch buffer not yet flushed (< batch_size records)

**Solutions:**
```python
# 1. Manually flush buffers
sqlite_pub._flush_buffers()

# 2. Reduce batch size
"batch_size": 10  # Flush more frequently

# 3. Buffers auto-flush on shutdown
# Ensure clean shutdown of publishers
```

---

## Security & Compliance

### Audit Trail for Compliance

The audit log provides a complete trail for regulatory compliance:

- **21 CFR Part 11** (FDA): Electronic records and signatures
- **HIPAA**: Healthcare data access logging
- **SOX**: Financial data audit requirements
- **GDPR**: Data access and modification tracking

**Required Audit Fields:**
- ✅ What happened (`event_details`)
- ✅ When it happened (`timestamp`)
- ✅ Who did it (`user`)
- ✅ What was the impact (`severity`)
- ✅ Where it happened (`event_source`)

### Data Retention Policies

Configure retention to meet compliance requirements:

```json
{
  "retention_days": 2555  // 7 years for SOX compliance
}
```

**Common Requirements:**
- **FDA 21 CFR Part 11**: Electronic records must be retained per predicate rules
- **SOX**: Financial records for 7 years
- **HIPAA**: 6 years from creation or last use
- **GDPR**: No longer than necessary (varies by purpose)

### Access Control

Implement access control for database file:

```bash
# Restrict database file permissions
chmod 600 emberburn_data.db
chown emberburn:emberburn emberburn_data.db

# Restrict backup directory
chmod 700 backups/
```

### Encryption at Rest

Encrypt the database file for sensitive data:

```bash
# Option 1: SQLite encryption extension (SQLCipher)
pip install pysqlcipher3

# Option 2: File system encryption (LUKS, BitLocker, FileVault)
# Option 3: Encrypt backups
openssl enc -aes-256-cbc -salt -in emberburn_data.db -out emberburn_data.db.enc
```

---

## Best Practices

1. **Set Appropriate Retention**: Balance storage costs with compliance needs
2. **Regular Backups**: Automate daily backups with off-site storage
3. **Monitor Database Size**: Alert when approaching `max_db_size_mb`
4. **Use WAL Mode**: Better concurrency for high-write workloads
5. **Batch Appropriately**: Balance write performance vs data safety
6. **Index Strategically**: Don't over-index; each index costs write performance
7. **Vacuum Regularly**: Reclaim space from deleted records
8. **Log Audit Events**: Comprehensive logging for compliance and debugging
9. **Test Restore Process**: Verify backups can be restored successfully
10. **Secure the Database**: File permissions, encryption, access control

---

## CTO's Wisdom 🔥

*"Listen, if you're not logging it, it didn't happen. And when the auditors show up asking why production went down at 3 AM last Tuesday, you better have an audit trail that tells the story. SQLite isn't sexy, but it's reliable as hell and it's already on your system. Use it."*

. Patrick Ryan, CTO, Fireball Industries

*"Oh, and pro tip: Set your retention policy BEFORE you fill up your entire disk with sensor data. I learned that the hard way. Twice. Don't be like me."*

*"One more thing: That 'batch_size' config? It's the difference between your database humming along smoothly and your disk I/O looking like a denial-of-service attack. Start with 100, tune from there. You're welcome."*

---

## Additional Resources

- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [SQLite Performance Tuning](https://www.sqlite.org/queryplanner.html)
- [FDA 21 CFR Part 11](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/part-11-electronic-records-electronic-signatures-scope-and-application)
- [GDPR Compliance Guide](https://gdpr.eu/)
- [EmberBurn Architecture](ARCHITECTURE_OVERVIEW.md)
- [Multi-Protocol Summary](MULTI_PROTOCOL_SUMMARY.md)

---

**EmberBurn** - *Where industrial data meets fire-tested reliability* 🔥
