---
layout: post
title: "Running Prometheus + Grafana on a single VPS"
categories: tech
tags: [prometheus, grafana, monitoring, devtools]
comments: True
---

I run a bunch of services on a single Hetzner VPS. Nothing fancy — a few Node.js apps behind nginx, some cron jobs, the usual. For a long time my "monitoring" was `htop` over SSH and hoping nothing breaks while I sleep. That's embarrassing to admit, but I think a lot of solo devs are in the same boat.

<!-- readmore -->

## Why bother?

Two reasons. First, I woke up to a dead app that had been down for 11 hours. No alerts, no logs telling me when it happened, nothing. Second, I wanted to understand my resource usage — the VPS has 4 cores and 8GB RAM, and I had no idea if I was using 20% or 80%.

The usual answer is "use Datadog" or "use New Relic." But I'm running side projects on a single box, not a startup. I don't want to pay $15/month for monitoring that costs more than the server itself.

## The stack

```
Prometheus  →  scrapes metrics every 15s
node_exporter  →  exposes system metrics (CPU, RAM, disk, network)
Grafana  →  dashboards and alerts
```

That's the whole thing. All three run on the same VPS. Total RAM overhead: ~200MB.

The architecture is intentionally simple. `node_exporter` runs as a systemd service, exposes metrics on `:9100`. Your apps expose `/metrics` on their own ports. Prometheus scrapes all of them on a schedule and stores time-series data locally. Grafana queries Prometheus and visualizes it. No cloud, no SaaS, no per-seat pricing.

## Setup

`node_exporter` is the easiest part — download the binary, run it, it exposes metrics on `:9100`. No config needed. The metrics it exports are comprehensive: CPU per-core, memory breakdown (not just "used"), disk I/O by device, network throughput by interface, filesystem usage per mount point, load average, file descriptor counts.

`prometheus.yml` is minimal:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']

  - job_name: 'my-app'
    static_configs:
      - targets: ['localhost:3333']
    metrics_path: /metrics
```

If your app exposes a `/metrics` endpoint (and it should), Prometheus scrapes it alongside the system metrics. Most language ecosystems have a Prometheus client library. For Node.js, `prom-client` is the standard:

```js
const client = require('prom-client');
const register = client.register;
client.collectDefaultMetrics();

app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});
```

That gives you Node.js process metrics (event loop lag, heap usage, GC stats) for free, plus you can add custom metrics on top.

Grafana connects to Prometheus as a data source. I imported the "Node Exporter Full" dashboard (ID `1860`) and had system metrics visualized in 30 seconds.

## PromQL — the part people skip

Most guides stop at the pretty dashboard and don't explain how to actually query Prometheus. That's a shame because PromQL is where the power is. Let me share the queries I actually use.

**CPU usage percentage:**

```promql
100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

`node_cpu_seconds_total` is a counter, so we use `rate()` to get the per-second rate over a 5-minute window. Mode "idle" is what's *not* being used, so we subtract from 100. The `avg by(instance)` aggregates across all cores.

**Memory usage percentage:**

```promql
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100
```

Use `MemAvailable`, not `MemFree`. Available accounts for cached/buffered memory that's reclaimable — free doesn't. `MemFree` on Linux is almost always low and almost always meaningless.

**Disk usage per filesystem:**

```promql
(node_filesystem_size_bytes - node_filesystem_avail_bytes) 
  / node_filesystem_size_bytes * 100
```

Filter to specific mount points if you have many:

```promql
(node_filesystem_size_bytes{mountpoint="/"} - node_filesystem_avail_bytes{mountpoint="/"}) 
  / node_filesystem_size_bytes{mountpoint="/"} * 100
```

**Network throughput (inbound):**

```promql
rate(node_network_receive_bytes_total{device="eth0"}[5m]) * 8
```

Multiply by 8 to convert bytes to bits. Replace `eth0` with your actual interface name.

**HTTP request rate from your app (if you're tracking it):**

```promql
rate(http_requests_total[5m])
```

Or broken down by status code:

```promql
sum by (status_code) (rate(http_requests_total[5m]))
```

The 5-minute window `[5m]` in `rate()` is a trade-off. Shorter windows are more responsive but noisier. Longer windows are smoother but lag behind spikes. I use `[5m]` for everything and adjust up to `[15m]` for capacity planning graphs.

## Alert rules

Grafana can alert directly from panels, but I prefer defining alerts in Prometheus itself using recording rules and alerting rules. They live alongside the data, version-controlled with your config, and don't depend on the Grafana UI being up.

`/etc/prometheus/rules.yml`:

```yaml
groups:
  - name: node_alerts
    rules:
      - alert: HighDiskUsage
        expr: >
          (node_filesystem_size_bytes{mountpoint="/"} - node_filesystem_avail_bytes{mountpoint="/"})
          / node_filesystem_size_bytes{mountpoint="/"} * 100 > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk usage above 85% on {{ $labels.instance }}"
          description: "Current usage: {{ $value | printf \"%.1f\" }}%"

      - alert: HighMemoryUsage
        expr: >
          (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Memory usage above 90% on {{ $labels.instance }}"

      - alert: ServiceDown
        expr: up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.job }} is down on {{ $labels.instance }}"
```

The `for: 5m` condition means the alert only fires if the condition holds for 5 minutes continuously. This kills most false positives from brief spikes. `up == 0` is a built-in metric Prometheus sets to 0 whenever it fails to scrape a target — dead simple service monitoring.

Reference the rules file from `prometheus.yml`:

```yaml
rule_files:
  - /etc/prometheus/rules.yml
```

## Alertmanager — optional but worth it

Prometheus fires alerts; Alertmanager routes them. You can skip Alertmanager and use Grafana's built-in alerting, but Alertmanager has better deduplication and silence management.

A minimal Alertmanager config that sends to Telegram:

```yaml
global:
  resolve_timeout: 5m

route:
  receiver: telegram

receivers:
  - name: telegram
    telegram_configs:
      - bot_token: YOUR_BOT_TOKEN
        chat_id: YOUR_CHAT_ID
        message: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
```

Telegram is my preferred alert destination for personal projects. It's free, the API is simple, and a bot token takes 2 minutes to set up. PagerDuty is overkill for a single VPS; email is too easy to ignore at 3am.

## What I actually monitor

After several months of iteration, I settled on these alerts:

- **Disk > 85%** — gave me a week of warning before logs ate the disk
- **RAM > 90% for 5min** — catches memory leaks before OOM kills something
- **Target down for 2min** — if Prometheus can't scrape an app, something's wrong
- **CPU sustained > 80% for 10min** — hasn't fired in anger yet, but good to have
- **Node.js event loop lag > 100ms** — early warning that an app is struggling

The event loop lag one is particularly useful. By the time you see it in HTTP response times, things are already bad. Catching it in the event loop metric gives you time to react.

## Dashboard design tips

A few things I learned about building useful Grafana dashboards:

**Rows and collapse.** Group related panels into rows, keep critical at the top. I have three rows: "Overview" (CPU, RAM, disk, network at a glance), "Services" (per-app metrics), "Alerts" (current alert state). The overview is always expanded; the others collapse when not needed.

**Time ranges matter.** The default dashboard time range is often "last 6 hours" or "last 24 hours." For debugging, you want "last 15 minutes." For capacity planning, you want "last 30 days." Build dashboards for the use case, not just as a default view.

**Use stat panels for current values, time series for trends.** A stat panel showing current CPU at 23% is immediately readable. A time series shows if 23% is normal or if it's been climbing for 6 hours.

**Templating for multi-instance.** Even on a single VPS, I use template variables for `$instance` and `$job`. It costs nothing to set up and makes dashboards portable if I ever add a second server:

```
Variable: instance
Type: Query
Query: label_values(up, instance)
```

## The "is this overkill?" question

For a single VPS? Honestly, maybe. You could get 70% of the value from a bash script that checks `df` and `free` on a cron. But:

- Prometheus gives you historical data. "What was CPU doing at 3am last Tuesday?" is a PromQL query away
- Grafana makes it visual. Patterns jump out of graphs that you'd never spot in logs
- The setup took an afternoon. The maintenance cost is basically zero

The point isn't that you need enterprise monitoring for a side project. The point is that `htop` over SSH is reactive — you only look when something's already wrong. Prometheus is proactive — it tells you before things break.

## Resource cost

On my 4-core, 8GB box:

| Service | RAM | CPU |
|---------|-----|-----|
| Prometheus | ~120MB | <1% |
| Grafana | ~60MB | <1% |
| node_exporter | ~15MB | <1% |

Under 200MB total. Prometheus disk usage grows over time — default retention is 15 days, and on a busy server with many metrics you might see 2-5GB. Tune it:

```bash
# In your prometheus systemd service or startup flags
--storage.tsdb.retention.time=30d
--storage.tsdb.retention.size=5GB
```

The `size` flag is a hard ceiling; Prometheus deletes oldest data once it's reached. Useful if you don't want to think about it again.

If your VPS can't spare 200MB for monitoring, you need a bigger VPS, not less monitoring.

3h4x
