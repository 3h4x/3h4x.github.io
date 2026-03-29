---
layout: post
title:  "mcp-http-tools - any HTTP API as an MCP tool, zero code"
categories: tech
tags: [mcp, claude, devtools, monitoring]
comments: True
---

I run a bunch of services on a single server. Prometheus for metrics, Loki for logs, PM2 for process management. Checking on them usually meant opening terminals and curling endpoints. I wanted Claude to be able to do that for me — but writing a custom MCP server for every API felt like too much work. So I built `mcp-http-tools`: a generic MCP server where you define tools in YAML and it proxies requests to any HTTP API.

<!-- readmore -->

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

Drop this in `~/.config/mcp-http-tools/config.yaml`, start the server, and those become proper MCP tools that Claude can call. GET params become query strings, POST params go into a JSON body, `{param}` in the URL becomes a path segment. JSON responses can be extracted via dot-path notation so you're not handing Claude a wall of raw API output.

## The implementation

The architecture is deliberately boring:

```
YAML config → configToTools() → MCP tool schemas
                                        ↓
MCP client calls tool → buildRequest() → fetch() → extractResponse() → MCP response
```

Two files. `lib.js` has all the logic — config loading, schema generation, request building, response extraction. `index.js` is 45 lines of MCP server wiring that calls into lib. Nothing else. Easy to test (53 tests), easy to reason about.

One thing I'm pleased with: env var substitution in headers via `${ENV_VAR}`. So auth headers stay out of the config file:

```yaml
headers:
  Authorization: "Bearer ${MY_API_TOKEN}"
```

## How I actually use it

My monitoring stack is now a set of Claude tools. When I ask "are there any errors in the last hour?", Claude calls `loki_logs` with the right LogQL query. "What's the memory usage?" → `prometheus_query` with the right PromQL. I have `pm2_app_logs`, `health_overview`, `error_scan` all wired up. No context-switching, no terminal, no copy-pasting curl commands.

It's connected via [supergateway](https://www.npmjs.com/package/supergateway) for SSE transport with Claude Desktop. The config in `claude_desktop_config.json` is just:

```json
{
  "mcpServers": {
    "mcp-http-tools": {
      "url": "http://localhost:9191/sse"
    }
  }
}
```

## What's next

Before I publish to npm: config validation on startup (right now bad YAML silently gives you zero tools), per-tool request timeouts, and a `bin` field so `npx mcp-http-tools` works. After that I want hot reload so you can add tools without restarting the server. And maybe config merging — global tools plus per-project overlays.

The whole thing is ~200 lines of actual logic. If you've got HTTP APIs you want to talk to from Claude, this is probably the fastest path there.

Know what you are doing and have fun!

3h4x
