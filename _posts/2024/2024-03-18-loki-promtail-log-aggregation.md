---
layout: post
title: "Loki + Promtail for log aggregation on a budget"
categories: tech
tags: [loki, monitoring, devtools, prometheus]
comments: True
---

I've been running Prometheus + Grafana for over a year now and it's great for metrics. But metrics tell you *what* happened — not *why*. For that you need logs. And my logging strategy was `ssh` into the server and `tail -f` whatever PM2 was writing to disk. Not scalable, not searchable, and definitely not "check this from my phone at 2am" friendly.

<!-- readmore -->

## Why Loki?

The alternatives I considered:

- **ELK (Elasticsearch + Logstash + Kibana)** — powerful, but Elasticsearch alone wants 2GB+ of RAM. That's a quarter of my VPS for log indexing
- **Graylog** — same problem, Java-based, heavy
- **Papertrail/Logtail** — SaaS, costs money, sends my logs to someone else's servers

Loki is Grafana Labs' answer to "what if log aggregation was cheap?" The key insight: Loki indexes only labels (like app name, log level), not the full text of every log line. It's like `grep` with a time filter and label selectors. Way less storage and RAM than Elasticsearch.

The trade-off is query speed. Full-text search in Elasticsearch is fast because everything is indexed. Loki scans through compressed log chunks at query time — it's slower for "find this string anywhere in 30 days of logs" queries. For "show me errors from my API in the last hour" queries, it's fast enough that you'll never notice.

## Architecture

```
PM2 apps → log files → Promtail → Loki → Grafana
systemd services → journald → Promtail → Loki → Grafana
Docker containers → json-file logs → Promtail → Loki → Grafana
```

`Promtail` is the agent — it tails log files and ships them to Loki. If you're already running Prometheus, this mental model is familiar: Promtail is to Loki what `node_exporter` is to Prometheus. It runs on the same host as your apps, reads log files (or `journald`), and pushes entries upstream with labels attached.

Everything talks HTTP. Loki exposes a push endpoint and a query API. No special protocols, no message queues. Simple.

## Promtail config

```yaml
server:
  http_listen_port: 9080

positions:
  filename: /var/lib/promtail/positions.yaml

clients:
  - url: http://localhost:3100/loki/api/v1/push

scrape_configs:
  - job_name: pm2
    static_configs:
      - targets: [localhost]
        labels:
          job: pm2
          __path__: /home/*/.pm2/logs/*.log
    pipeline_stages:
      - regex:
          expression: '(?P<app>[^/]+?)(?:-out|-error)\.log$'
          source: filename
      - labels:
          app:

  - job_name: journald
    journal:
      labels:
        job: journald
    relabel_configs:
      - source_labels: ['__journal__systemd_unit']
        target_label: unit
      - source_labels: ['__journal_priority_keyword']
        target_label: level

  - job_name: docker
    static_configs:
      - targets: [localhost]
        labels:
          job: docker
          __path__: /var/lib/docker/containers/*/*-json.log
    pipeline_stages:
      - json:
          expressions:
            stream: stream
            log: log
      - labels:
          stream:
      - output:
          source: log
```

Three scrape configs. PM2 log files with the app name extracted from the filename. `journald` for systemd services with priority mapped to a `level` label. Docker containers with the JSON log format parsed so you get the actual message, not the raw JSON blob.

The `positions.yaml` file tracks how far Promtail has read into each log file. If Promtail restarts, it picks up where it left off instead of re-shipping everything. Essential for not flooding Loki with duplicates.

## Loki config

Loki's config is straightforward for a single-node setup:

```yaml
auth_enabled: false

server:
  http_listen_port: 3100

ingester:
  lifecycler:
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1
  chunk_idle_period: 1h
  max_chunk_age: 1h

schema_config:
  configs:
    - from: 2024-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

storage_config:
  boltdb_shipper:
    active_index_directory: /var/lib/loki/index
    cache_location: /var/lib/loki/cache
  filesystem:
    directory: /var/lib/loki/chunks

limits_config:
  retention_period: 744h  # 31 days
```

Run it with `docker run` or as a binary — I use the binary via systemd. The retention config keeps 31 days of logs, after which Loki automatically deletes old chunks. No manual cleanup needed.

## Querying with LogQL

LogQL is Loki's query language. It's PromQL-flavored but for logs:

```
# All logs from a specific PM2 app
{job="pm2", app="api"}

# Errors across all apps in the last hour
{job="pm2"} |~ "(?i)error|fatal|panic"

# Nginx 5xx responses
{job="journald", unit="nginx.service"} |= "\" 5"

# Exclude noisy health check logs
{job="pm2", app="api"} != "/health"

# Rate of errors per minute
rate({job="pm2"} |~ "(?i)error" [1m])

# Count of log lines per app over time
sum by (app) (count_over_time({job="pm2"}[5m]))
```

That last metric query is where it gets powerful — you can turn log patterns into metrics and alert on them. "Alert me if errors exceed 10/minute" is a one-liner. Grafana's alerting can fire on LogQL metric queries just like Prometheus ones.

The `|=` operator is exact string match. `|~` is regex. `!=` and `!~` are the negations. Combine them:

```
{job="pm2", app="api"} |~ "error" != "404"
```

That gives you all errors except 404s — useful when your app logs 404s as errors and you're tired of seeing them.

## Grafana integration

Since Loki is a Grafana Labs project, the integration is native. Add Loki as a data source (URL: `http://localhost:3100`), and you can put log panels right next to your Prometheus metric graphs on the same dashboard.

CPU spikes at 3:14am? Switch to the log panel and see exactly what your app was doing at 3:14am. This correlation between metrics and logs on a single dashboard is the real win. I don't need to SSH in and mentally sync timestamps between `htop` output and log files anymore.

One underrated Grafana feature: the "Explore" view. Pick a time range on a metric graph, right-click, "Explore logs". Grafana pre-fills a LogQL query with that exact time range. From "something went wrong" to "here's every log line during the incident" in two clicks.

## Accessing it safely

Loki has no authentication in single-tenant mode. Don't expose port 3100 to the internet. I use an SSH tunnel:

```bash
# On local machine
ssh -L 3100:localhost:3100 -L 3000:localhost:3000 -N user@server
```

Now Grafana is at `http://localhost:3000` and Loki is at `http://localhost:3100` locally. I have this as a launchd service on my Mac so it's always up. All observability data stays on the server — the tunnel is just for viewing.

## Resource usage

| Service | RAM | Disk (30 days) |
|---------|-----|----------------|
| Loki | ~80MB | ~500MB |
| Promtail | ~30MB | negligible |

Under 120MB for full log aggregation. Loki's label-only indexing keeps storage low. Compare that to Elasticsearch at 2GB+ RAM for the same workload.

The 500MB figure depends heavily on log volume and compression. Loki stores chunks as compressed `gzip` — raw log text compresses extremely well, usually 10-20x. If you're logging 50MB/day of raw text, expect around 3MB/day stored.

## What I learned the hard way

**High-cardinality labels kill performance.** Don't use request IDs, user IDs, or anything unique-per-request as a label. Labels are used to build the index — a million unique label values means a million index entries. Use labels for things with low cardinality: app name, log level, environment.

**Log level parsing.** If your apps log structured JSON, add a pipeline stage to extract the level:

```yaml
pipeline_stages:
  - json:
      expressions:
        level: level
  - labels:
      level:
```

Then `{job="pm2", level="error"}` just works. Much better than `|~ "\"level\":\"error\""`.

**Retention and disk.** Set `retention_period` from day one. I forgot on my first deployment and Loki grew unbounded for a month. Not catastrophic, but awkward to clean up.

## The setup that changed my debugging

The whole observability stack on a single VPS — Prometheus for metrics, Loki for logs, Grafana for visualization, all accessible through an SSH tunnel. Total overhead: ~400MB RAM. No SaaS subscriptions, no vendor lock-in, all my data stays on my machine.

Is it as powerful as Datadog? No. But for side projects on a single server, it's more than enough. And when something breaks at 2am, I can actually figure out why without getting out of bed.

3h4x
