---
layout: post
title:  "mcp-http-tools - any HTTP API as an MCP tool, zero code"
categories: tech
tags: [mcp, claude, devtools, monitoring]
comments: True
---

I've been using Grafana since around 2014 and added Prometheus and Loki to the stack not long after. Dashboards and alerts are great for knowing *what* happened — but when I want to actually poke at the data, it's still `curl` commands in a terminal. I wanted Claude to be able to query my monitoring stack directly — but writing a custom MCP server for every API felt like too much work. So I built `mcp-http-tools`: a generic MCP server where you define tools in YAML and it proxies requests to any HTTP API.

<!-- readmore -->

## The problem with custom MCP servers

The [MCP SDK](https://www.npmjs.com/package/@modelcontextprotocol/sdk) is actually pretty nice to use. But every time you want to expose a new API to Claude, you end up writing the same boilerplate: server setup, tool registration, request building, error handling, response formatting. For a monitoring stack with five APIs, that's five times the same plumbing. And if you just want to expose a single `/health` endpoint or a simple query API — do you really need to write a Node.js service for that?

Probably not. The pattern is always the same: receive tool args from Claude → build an HTTP request → return the response. That's generic enough to configure, not code.

## The idea

Instead of code, you write config:

```yaml
tools:
  - name: prometheus_query
    description: Run a PromQL instant query
    url: http://localhost:9090/api/v1/query
    params:
      - name: query
        description: PromQL expression
        required: true
    response:
      type: json
      path: data.result

  - name: loki_logs
    description: Fetch logs via LogQL
    url: http://localhost:3100/loki/api/v1/query_range
    params:
      - name: query
        description: LogQL query
        required: true
      - name: limit
        default: "50"
    response:
      type: json
      path: data.result
```

Drop this in `~/.config/mcp-http-tools/config.yaml`, start the server, and those become proper MCP tools Claude can call. No code. Just YAML.

## How it works under the hood

The architecture is deliberately boring:

```
YAML config → configToTools() → MCP tool schemas
                                        ↓
MCP client calls tool → buildRequest() → fetch() → extractResponse() → MCP response
```

Two files. `lib.js` has all the logic — config loading, schema generation, request building, response extraction. `index.js` is 45 lines of MCP server wiring that calls into lib. That's it. Easy to test (53 tests), easy to reason about.

**GET requests** — params become URL query parameters. So for the Prometheus example above, Claude calling `prometheus_query` with `query=up` sends `GET /api/v1/query?query=up`.

**POST requests** — set `method: POST` and params go into a JSON body with `Content-Type: application/json` automatically.

**Path parameters** — use `{param}` in the URL and it becomes a path segment instead of a query param:

```yaml
- name: get_label_values
  description: List all values for a Loki label
  url: http://localhost:3100/loki/api/v1/label/{label}/values
  params:
    - name: label
      description: Label name, e.g. app or job
      required: true
  response:
    type: json
    path: data
```

**Defaults** — any param with a `default` is optional. Claude can override it, but if it doesn't, the default kicks in. Great for things like `limit` or `step` that you rarely want to tweak.

**Auth** — env var substitution in headers via `${ENV_VAR}`. So you're not hardcoding tokens into config files:

```yaml
- name: list_alerts
  description: List active Alertmanager alerts
  url: http://alertmanager.internal/api/v2/alerts
  headers:
    Authorization: "Bearer ${ALERTMANAGER_TOKEN}"
  response:
    type: json
```

## The response path trick

One thing that makes this actually usable in practice: `response.path`. Prometheus wraps every response like this:

```json
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [
      { "metric": { "__name__": "up", "job": "node_exporter" }, "value": [1743200000, "1"] }
    ]
  }
}
```

Without `path: data.result`, Claude gets the entire JSON blob and has to parse the wrapper. With it, Claude gets just the `result` array. Cleaner, fewer tokens, less chance of the LLM getting confused by the envelope.

The path is dot-notation — `data.result`, `status`, `items.0.name` — just descend the object. If the path doesn't resolve you get the raw response as a fallback.

## My actual monitoring config

Here's the full config I'm running for my monitoring stack:

```yaml
tools:
  - name: prometheus_query
    description: Run a PromQL instant query against Prometheus
    url: http://localhost:9090/api/v1/query
    params:
      - name: query
        description: PromQL expression, e.g. up, rate(http_requests_total[5m])
        required: true
    response:
      type: json
      path: data.result

  - name: loki_logs
    description: Fetch logs via LogQL from Loki
    url: http://localhost:3100/loki/api/v1/query_range
    params:
      - name: query
        description: LogQL query, e.g. {app="my-api"} |~ "error"
        required: true
      - name: limit
        description: Max log lines to return
        default: "50"
      - name: start
        description: Start time as Unix nanoseconds
    response:
      type: json
      path: data.result

  - name: pm2_app_logs
    description: Tail logs for a specific PM2 app via Loki
    url: http://localhost:3100/loki/api/v1/query_range
    params:
      - name: app
        description: PM2 app name, e.g. my-api, my-worker, my-bot
        required: true
      - name: limit
        default: "30"
    response:
      type: json
      path: data.result

  - name: health_overview
    description: Check all Prometheus scrape targets and their health
    url: http://localhost:9090/api/v1/targets
    response:
      type: json
      path: data.activeTargets

  - name: error_scan
    description: Scan all service logs for errors and panics in the last hour
    url: http://localhost:3100/loki/api/v1/query_range
    params:
      - name: limit
        default: "50"
    response:
      type: json
      path: data.result
```

Each of these becomes a real Claude tool. No custom code, no build step, no dependencies beyond the server itself.

## What it actually looks like

This is what working with it feels like in Claude Desktop:

> **Me:** Are there any errors in the last hour?
>
> **Claude:** *calls `error_scan`* — Found 3 error-level log entries. Two are `"Network request failed (will retry)"` from the scheduler — those are transient and expected. One is a `SQLITE_BUSY` from the chat service at 14:23 — looks like a brief lock contention, no crash, resolved itself.

> **Me:** What's the memory usage on the server right now?
>
> **Claude:** *calls `prometheus_query` with `(1-node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)*100`* — 71.4% RAM used, which is normal. No spike.

> **Me:** Show me the last 10 API logs
>
> **Claude:** *calls `pm2_app_logs` with `app=my-api, limit=10`* — [last 10 lines]

No context-switching, no terminal, no copy-pasting curl commands. Claude just knows what to ask and how to ask it. The good tool descriptions do a lot of heavy lifting here — if you tell Claude "PromQL expression, e.g. `up`, `rate(http_requests_total[5m])`" it actually writes better queries than if you leave it vague.

## Setting it up

```bash
git clone https://github.com/3h4x/mcp-http-tools
cd mcp-http-tools
npm install

# Create config dir
mkdir -p ~/.config/mcp-http-tools

# Drop your config there
cp config.yaml ~/.config/mcp-http-tools/config.yaml
# edit it to point at your APIs
```

Then wire it up to Claude Desktop. It runs as a stdio MCP server — no extra proxy, no port binding. Just add it to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mcp-http-tools": {
      "command": "node",
      "args": ["/path/to/mcp-http-tools/index.js"]
    }
  }
}
```

Same thing for Claude Code — add it to `.claude/settings.json` or your global settings:

```json
{
  "mcpServers": {
    "mcp-http-tools": {
      "command": "node",
      "args": ["/path/to/mcp-http-tools/index.js"]
    }
  }
}
```

## What's next

Before I publish to npm I want a few things nailed down: config validation on startup (right now bad YAML silently gives you zero tools — not great), per-tool request timeouts so a slow API doesn't hang the whole server, and a `bin` field so `npx mcp-http-tools` just works.

After that:

**Hot reload** — add tools without restarting the server. Watch the config file for changes and reload tool definitions in-place. The MCP session would keep running, just with updated tools on the next `ListTools` call.

**Config merging** — a global `~/.config/mcp-http-tools/config.yaml` for shared tools plus per-project overlays. So your Prometheus and Loki tools are always there, but a specific project can add its own API tools on top.

**Response transforms** — right now `path` extracts a subtree and stringifies it. A basic `jq`-style transform or a handlebars template would let you format responses before they hit Claude. Useful when the raw API output is verbose and you want to summarize it at the config level rather than relying on the LLM to do it.

**Multiple HTTP methods** — right now it's GET and POST. PATCH, PUT, DELETE would unlock full CRUD APIs like k8s or any REST service.

The whole thing is ~200 lines of actual logic. If you've got HTTP APIs you want to talk to from Claude, this is probably the fastest path there.

Check it out: [github.com/3h4x/mcp-http-tools](https://github.com/3h4x/mcp-http-tools)

3h4x
