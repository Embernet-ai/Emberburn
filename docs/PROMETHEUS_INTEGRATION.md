# 🔥 EmberBurn Prometheus Integration
## Protocol #13: Operational Metrics & Monitoring

### Overview

The Prometheus integration provides comprehensive operational metrics for the EmberBurn multi-protocol industrial data platform. It exposes metrics at the standard `/metrics` endpoint for scraping by Prometheus servers and visualization in Grafana dashboards.

**Key Features:**
- System health metrics (uptime, tag counts)
- Tag operation tracking (updates, errors, current values)
- Publisher health monitoring (per-publisher status, message counts, error rates)
- Alarm state tracking (active, critical, warning counts)
- Performance metrics (publish duration histograms)
- Standard Prometheus exposition format
- Integration with existing REST API (no separate server needed)

---

## Installation

### Requirements

```bash
pip install prometheus-client==0.19.0
```

### Configuration

Create or edit `config/config_prometheus.json`:

```json
{
  "prometheus": {
    "enabled": true,
    "description": "Prometheus Metrics Publisher",
    "config": {
      "port": 9090,
      "collect_system_metrics": true,
      "collect_tag_metrics": true,
      "collect_publisher_metrics": true,
      "collect_alarm_metrics": true,
      "metrics_update_interval": 5,
      "enable_performance_metrics": true,
      "metric_prefix": "emberburn_",
      "labels": {
        "environment": "production",
        "instance": "opcua-server-01",
        "datacenter": "dc1"
      }
    }
  }
}
```

**Configuration Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable/disable Prometheus metrics |
| `port` | integer | `9090` | Port for metrics endpoint (uses REST API port) |
| `collect_system_metrics` | boolean | `true` | Collect system uptime and tag count |
| `collect_tag_metrics` | boolean | `true` | Collect per-tag update counts and values |
| `collect_publisher_metrics` | boolean | `true` | Collect publisher health and message counts |
| `collect_alarm_metrics` | boolean | `true` | Collect alarm state and trigger counts |
| `metrics_update_interval` | integer | `5` | Interval (seconds) for metric updates |
| `enable_performance_metrics` | boolean | `true` | Collect performance histograms |
| `metric_prefix` | string | `"emberburn_"` | Prefix for all metric names |
| `labels` | object | `{}` | Additional labels for all metrics |

---

## Metrics Reference

### System Metrics

#### `emberburn_system_info`
**Type:** Info  
**Description:** System version and platform information  
**Labels:**
- `version`: EmberBurn version
- `platform`: Operating system platform
- `protocol_count`: Number of enabled protocols

**Example:**
```
emberburn_system_info{version="1.0.0",platform="Linux",protocol_count="13"} 1
```

#### `emberburn_system_uptime_seconds`
**Type:** Gauge  
**Description:** System uptime in seconds since last restart  
**Example:**
```
emberburn_system_uptime_seconds 3600.5
```

#### `emberburn_tags_total`
**Type:** Gauge  
**Description:** Total number of configured tags  
**Example:**
```
emberburn_tags_total 150
```

---

### Tag Metrics

#### `emberburn_tag_updates_total`
**Type:** Counter  
**Description:** Total number of tag value updates  
**Labels:**
- `tag_name`: Name of the tag

**Example:**
```
emberburn_tag_updates_total{tag_name="Temperature"} 5432
emberburn_tag_updates_total{tag_name="Pressure"} 5430
```

#### `emberburn_tag_update_errors_total`
**Type:** Counter  
**Description:** Total number of tag update errors  
**Labels:**
- `tag_name`: Name of the tag

**Example:**
```
emberburn_tag_update_errors_total{tag_name="FlowRate"} 3
```

#### `emberburn_tag_value`
**Type:** Gauge  
**Description:** Current value of numeric tags  
**Labels:**
- `tag_name`: Name of the tag

**Example:**
```
emberburn_tag_value{tag_name="Temperature"} 72.5
emberburn_tag_value{tag_name="Pressure"} 101325
```

---

### Publisher Metrics

#### `emberburn_publishers_total`
**Type:** Gauge  
**Description:** Total number of configured publishers  
**Example:**
```
emberburn_publishers_total 13
```

#### `emberburn_publishers_enabled`
**Type:** Gauge  
**Description:** Number of enabled publishers  
**Example:**
```
emberburn_publishers_enabled 8
```

#### `emberburn_publisher_health`
**Type:** Gauge  
**Description:** Publisher health status (1=healthy, 0=unhealthy)  
**Labels:**
- `publisher_name`: Name of the publisher

**Example:**
```
emberburn_publisher_health{publisher_name="MQTT"} 1
emberburn_publisher_health{publisher_name="Kafka"} 1
emberburn_publisher_health{publisher_name="InfluxDB"} 0
```

#### `emberburn_publisher_messages_sent_total`
**Type:** Counter  
**Description:** Total messages sent by publisher  
**Labels:**
- `publisher_name`: Name of the publisher

**Example:**
```
emberburn_publisher_messages_sent_total{publisher_name="MQTT"} 10543
emberburn_publisher_messages_sent_total{publisher_name="REST API"} 8721
```

#### `emberburn_publisher_errors_total`
**Type:** Counter  
**Description:** Total errors encountered by publisher  
**Labels:**
- `publisher_name`: Name of the publisher

**Example:**
```
emberburn_publisher_errors_total{publisher_name="Kafka"} 5
```

#### `emberburn_publish_duration_seconds`
**Type:** Histogram  
**Description:** Time taken to publish messages  
**Labels:**
- `publisher_name`: Name of the publisher

**Buckets:** 0.001, 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0

**Example:**
```
emberburn_publish_duration_seconds_bucket{publisher_name="MQTT",le="0.01"} 9543
emberburn_publish_duration_seconds_bucket{publisher_name="MQTT",le="0.025"} 10500
emberburn_publish_duration_seconds_sum{publisher_name="MQTT"} 125.3
emberburn_publish_duration_seconds_count{publisher_name="MQTT"} 10543
```

---

### Alarm Metrics

#### `emberburn_alarms_active`
**Type:** Gauge  
**Description:** Total number of active alarms  
**Example:**
```
emberburn_alarms_active 3
```

#### `emberburn_alarms_critical`
**Type:** Gauge  
**Description:** Number of active critical alarms  
**Example:**
```
emberburn_alarms_critical 1
```

#### `emberburn_alarms_warning`
**Type:** Gauge  
**Description:** Number of active warning alarms  
**Example:**
```
emberburn_alarms_warning 2
```

#### `emberburn_alarms_triggered_total`
**Type:** Counter  
**Description:** Total number of alarm trigger events  
**Labels:**
- `alarm_name`: Name of the alarm
- `priority`: Alarm priority (critical, warning, info)

**Example:**
```
emberburn_alarms_triggered_total{alarm_name="HighTemperature",priority="critical"} 15
emberburn_alarms_triggered_total{alarm_name="LowPressure",priority="warning"} 42
```

---

## Prometheus Setup

### Prometheus Configuration

Add a scrape job to your `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'emberburn'
    static_configs:
      - targets: ['localhost:9090']
        labels:
          environment: 'production'
          application: 'emberburn'
    scrape_interval: 10s
    scrape_timeout: 5s
```

### Docker Compose Example

```yaml
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
    ports:
      - "9091:9090"
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
    restart: unless-stopped

  emberburn:
    build: .
    container_name: emberburn
    ports:
      - "9090:9090"
      - "4840:4840"
    volumes:
      - ./config:/app/config
      - ./tags_config.json:/app/tags_config.json
    restart: unless-stopped

volumes:
  prometheus_data:
  grafana_data:
```

---

## Grafana Integration

### Add Prometheus Data Source

1. Navigate to **Configuration → Data Sources**
2. Click **Add data source**
3. Select **Prometheus**
4. Configure:
   - **URL:** `http://prometheus:9090`
   - **Access:** Server (default)
5. Click **Save & Test**

### Import EmberBurn Dashboard

Create a new dashboard with the following panels:

#### System Overview Panel

```promql
# System Uptime (hours)
emberburn_system_uptime_seconds / 3600

# Total Tags
emberburn_tags_total

# Active Publishers
emberburn_publishers_enabled
```

#### Publisher Health Panel

```promql
# Publisher Health Heatmap
emberburn_publisher_health
```

**Visualization:** Gauge  
**Thresholds:**
- Red: < 1
- Green: = 1

#### Message Throughput Panel

```promql
# Messages per second (rate over 1 minute)
rate(emberburn_publisher_messages_sent_total[1m])
```

**Visualization:** Graph  
**Legend:** `{{publisher_name}}`

#### Error Rate Panel

```promql
# Errors per minute
rate(emberburn_publisher_errors_total[5m]) * 60
```

**Visualization:** Graph (stacked)  
**Alert Threshold:** > 5 errors/min

#### Tag Updates Panel

```promql
# Tag update rate (updates per second)
rate(emberburn_tag_updates_total[1m])
```

**Visualization:** Graph  
**Top 10:** `topk(10, rate(emberburn_tag_updates_total[5m]))`

#### Publish Latency Panel

```promql
# 95th percentile publish duration
histogram_quantile(0.95, rate(emberburn_publish_duration_seconds_bucket[5m]))

# Average publish duration
rate(emberburn_publish_duration_seconds_sum[5m]) / rate(emberburn_publish_duration_seconds_count[5m])
```

**Visualization:** Graph  
**Legend:** `{{publisher_name}}`

#### Active Alarms Panel

```promql
# Total Active Alarms
emberburn_alarms_active

# Critical Alarms
emberburn_alarms_critical

# Warning Alarms
emberburn_alarms_warning
```

**Visualization:** Stat (big number)

#### Alarm Trigger Rate Panel

```promql
# Alarm triggers per hour
rate(emberburn_alarms_triggered_total[1h]) * 3600
```

**Visualization:** Bar gauge  
**Legend:** `{{alarm_name}} - {{priority}}`

---

## Sample Grafana Queries

### Publisher Performance Comparison

```promql
# Compare message throughput across publishers
sort_desc(
  sum by (publisher_name) (
    rate(emberburn_publisher_messages_sent_total[5m])
  )
)
```

### Tag Update Frequency

```promql
# Tags with highest update frequency
topk(10, 
  rate(emberburn_tag_updates_total[5m])
)
```

### Error Rate by Publisher

```promql
# Error percentage per publisher
(
  rate(emberburn_publisher_errors_total[5m]) / 
  rate(emberburn_publisher_messages_sent_total[5m])
) * 100
```

### Publish Latency Distribution

```promql
# Show latency buckets for specific publisher
sum(rate(emberburn_publish_duration_seconds_bucket{publisher_name="MQTT"}[5m])) by (le)
```

### System Health Score

```promql
# Overall system health (0-100)
(
  (emberburn_publishers_enabled / emberburn_publishers_total) * 50 +
  (sum(emberburn_publisher_health) / emberburn_publishers_enabled) * 50
)
```

---

## Alerting Rules

### prometheus_rules.yml

```yaml
groups:
  - name: emberburn_alerts
    interval: 30s
    rules:
      # High Error Rate
      - alert: HighPublisherErrorRate
        expr: rate(emberburn_publisher_errors_total[5m]) > 0.1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High error rate on {{ $labels.publisher_name }}"
          description: "{{ $labels.publisher_name }} has error rate of {{ $value | humanize }} errors/sec"

      # Publisher Down
      - alert: PublisherDown
        expr: emberburn_publisher_health == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Publisher {{ $labels.publisher_name }} is down"
          description: "{{ $labels.publisher_name }} has been unhealthy for 1 minute"

      # Critical Alarms Active
      - alert: CriticalAlarmsActive
        expr: emberburn_alarms_critical > 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "{{ $value }} critical alarms active"
          description: "System has {{ $value }} active critical alarms"

      # High Publish Latency
      - alert: HighPublishLatency
        expr: |
          histogram_quantile(0.95, 
            rate(emberburn_publish_duration_seconds_bucket[5m])
          ) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High publish latency on {{ $labels.publisher_name }}"
          description: "95th percentile latency is {{ $value | humanize }}s"

      # Tag Update Stalled
      - alert: TagUpdateStalled
        expr: |
          rate(emberburn_tag_updates_total[5m]) == 0 and 
          emberburn_tags_total > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Tag updates have stopped"
          description: "No tag updates detected for 2 minutes"

      # System Memory/Performance
      - alert: LowPublisherCount
        expr: |
          (emberburn_publishers_enabled / emberburn_publishers_total) < 0.5
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Less than 50% of publishers enabled"
          description: "Only {{ $value | humanizePercentage }} publishers running"
```

---

## Testing Metrics Endpoint

### Manual Testing

```bash
# Test metrics endpoint
curl http://localhost:9090/metrics

# Expected output (sample):
# HELP emberburn_system_uptime_seconds System uptime in seconds
# TYPE emberburn_system_uptime_seconds gauge
# emberburn_system_uptime_seconds 3600.5
# ...
```

### Prometheus Validation

```bash
# Validate Prometheus is scraping
curl http://localhost:9091/api/v1/targets

# Query specific metric
curl 'http://localhost:9091/api/v1/query?query=emberburn_tags_total'
```

### Python Test Script

```python
import requests
import time

def test_metrics():
    """Test EmberBurn metrics endpoint"""
    url = "http://localhost:9090/metrics"
    
    response = requests.get(url)
    assert response.status_code == 200
    assert 'emberburn_system_uptime_seconds' in response.text
    assert 'emberburn_tags_total' in response.text
    assert 'emberburn_publisher_health' in response.text
    
    print("✅ Metrics endpoint working")
    print(f"Response size: {len(response.text)} bytes")
    
    # Count metric types
    lines = response.text.split('\n')
    help_lines = [l for l in lines if l.startswith('# HELP')]
    type_lines = [l for l in lines if l.startswith('# TYPE')]
    
    print(f"Metrics defined: {len(help_lines)}")
    print(f"Metric types: {len(type_lines)}")

if __name__ == '__main__':
    test_metrics()
```

---

## Performance Considerations

### Metric Cardinality

- **Tag metrics:** Limited by number of configured tags (~150 typical)
- **Publisher metrics:** Limited by number of publishers (13 max)
- **Alarm metrics:** Limited by number of alarm conditions (~50 typical)
- **Total cardinality:** ~500-1000 time series (very efficient)

### Resource Usage

- **Memory:** ~5-10 MB for metric storage
- **CPU:** < 1% additional overhead
- **Network:** ~10-50 KB per scrape (depending on tag count)

### Optimization Tips

1. **Scrape Interval:** Use 15-30s for production (balance freshness vs load)
2. **Retention:** Keep 15 days locally, 6 months in Grafana/Thanos
3. **Cardinality:** Avoid high-cardinality labels (don't use tag values as labels)
4. **Histograms:** Publish duration histogram has 15 buckets (reasonable)

---

## Troubleshooting

### Metrics Not Appearing

**Problem:** `/metrics` endpoint returns 500 error

**Solution:**
```bash
# Check if prometheus-client is installed
pip list | grep prometheus

# Install if missing
pip install prometheus-client==0.19.0

# Check logs
tail -f /var/log/emberburn/opcua_server.log
```

### Publisher Health Always 0

**Problem:** All publishers show `emberburn_publisher_health{publisher_name="..."} 0`

**Solution:**
```python
# Check publisher statuses
import requests
response = requests.get('http://localhost:9090/api/tags')
print(response.json())

# Verify publishers are starting
# Check opcua_server.py startup logs
```

### Prometheus Not Scraping

**Problem:** Targets show "DOWN" in Prometheus UI

**Solution:**
```yaml
# Verify prometheus.yml has correct target
scrape_configs:
  - job_name: 'emberburn'
    static_configs:
      - targets: ['host.docker.internal:9090']  # Docker on Mac/Windows
      # or
      - targets: ['172.17.0.1:9090']  # Docker on Linux
```

### High Memory Usage

**Problem:** Prometheus consuming excessive memory

**Solution:**
```yaml
# Add storage retention limits to prometheus.yml
storage:
  tsdb:
    retention.time: 15d
    retention.size: 10GB
```

---

## Integration Examples

### AlertManager Integration

```yaml
# prometheus.yml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

rule_files:
  - 'prometheus_rules.yml'
```

### Thanos Long-term Storage

```yaml
# docker-compose.yml
services:
  thanos-sidecar:
    image: quay.io/thanos/thanos:latest
    command:
      - 'sidecar'
      - '--prometheus.url=http://prometheus:9090'
      - '--tsdb.path=/prometheus'
      - '--objstore.config-file=/etc/thanos/bucket.yml'
    volumes:
      - prometheus_data:/prometheus
      - ./thanos/bucket.yml:/etc/thanos/bucket.yml
```

### Grafana Cloud Integration

```bash
# Add Grafana Cloud Prometheus remote write
# prometheus.yml
remote_write:
  - url: https://prometheus-prod-01-eu-west-0.grafana.net/api/prom/push
    basic_auth:
      username: 123456
      password: your_grafana_cloud_api_key
```

---

## Best Practices

1. **Use PromQL Aggregations:** Always use `rate()` for counters, not raw values
2. **Set Appropriate Intervals:** Match rate interval to scrape interval (2x minimum)
3. **Label Wisely:** Don't use high-cardinality values (IPs, UUIDs) as labels
4. **Monitor Cardinality:** Track metric count with Prometheus's own metrics
5. **Dashboard Organization:** Group by concern (system, publishers, alarms)
6. **Alert Fatigue:** Set appropriate thresholds and durations to avoid noise
7. **Retention Policy:** Balance storage costs with query requirements
8. **Security:** Use TLS and authentication for production deployments

---

## CTO's Wisdom 🔥

*"Listen up - Prometheus ain't just metrics, it's your early warning system for when stuff goes sideways at 3 AM. You wanna know your MQTT publisher died? Check `emberburn_publisher_health`. Wanna know why your ops team is getting paged? Look at `emberburn_alarms_critical`. And for the love of all that is holy, SET UP ALERTS. Dashboards are pretty, but alerts keep you employed."*

. Patrick Ryan, CTO, Fireball Industries

*"Oh, and one more thing: If you're running this in production without monitoring, you're not running a system - you're running a ticking time bomb. Prometheus gives you the detonator switch. Use it wisely."*

---

## Additional Resources

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Dashboards](https://grafana.com/grafana/dashboards/)
- [PromQL Tutorial](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Alerting Best Practices](https://prometheus.io/docs/practices/alerting/)
- [EmberBurn Architecture](ARCHITECTURE_OVERVIEW.md)
- [Multi-Protocol Summary](MULTI_PROTOCOL_SUMMARY.md)

---

**EmberBurn** - *Where industrial data meets fire-tested reliability* 🔥
