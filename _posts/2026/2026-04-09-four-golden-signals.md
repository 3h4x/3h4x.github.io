---
layout: post
title: "The four golden signals — what I actually monitor and why"
categories: tech
tags: [observability, sre, prometheus, kubernetes, aws]
comments: True
---

Got asked about golden metrics in an interview recently. Named three out of four on the spot — latency, errors, saturation — and completely blanked on traffic. The one signal I look at every single day, and my brain just decided it wasn't worth mentioning under pressure. So here's the post I'm writing partly out of spite at my own memory. The four golden signals from Google's SRE book are a solid framework, but how you implement them — and what you learn the hard way about each one — is where it gets interesting.

<!-- readmore -->

## The framework

Google's SRE book defines four golden signals for monitoring any user-facing system: latency, traffic, errors, and saturation. The idea is simple — if you only measure four things, measure these. Everything else is either a derivative or noise.

That's a good starting point. But "measure latency" is about as helpful as "write good code." The details matter.

## Latency

The signal everyone gets wrong first. Not because they don't measure it, but because they measure the wrong thing.

If you're looking at average latency, stop. Averages lie. A service with 50ms average response time sounds fine until you realize 1% of requests take 3 seconds. That 1% is someone's checkout flow, someone's API integration, someone's patience running out.

What you want:

```yaml
# Prometheus histogram for request duration
- record: http_request_duration_seconds:p99
  expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))

- record: http_request_duration_seconds:p50
  expr: histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))
```

p50 tells you what most users experience. p99 tells you what your worst-off users experience. The gap between them tells you how consistent your service is. When I set up alerting, I alert on p99 crossing a threshold, not p50. If p50 is bad, everyone already knows — support tickets are flowing. p99 degradation is the silent one.

The other mistake: not separating successful request latency from error latency. A request that fails fast (returns a `500` in 2ms) pulls your average down and makes things look better than they are. Always split:

```promql
# Latency of only successful requests
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{status_code!~"5.."}[5m])) by (le, service)
)
```

Failed requests being fast is not a sign of health. It's a sign that your errors are cheap and your dashboard is lying.

## Traffic

Traffic is the "how much" signal — requests per second, messages processed, queries executed. It's the least interesting signal on its own and the most important as context for every other signal.

```promql
# Request rate per service
sum(rate(http_requests_total[5m])) by (service, method)
```

Here's what traffic data actually buys you: correlation. Latency went up at 14:00? Check traffic at 14:00. If traffic doubled, your latency spike is probably just load — scale horizontally. If traffic is flat and latency spiked, something broke. That distinction saves you from chasing the wrong root cause.

For Kubernetes workloads on EKS, I pair this with HPA metrics:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "100"
```

Custom metrics via the Prometheus adapter, not just CPU. CPU-based autoscaling is almost always too late — by the time CPU spikes, latency has already degraded. Request rate is a leading indicator; CPU is a trailing one.

## Errors

Errors seem straightforward: count the failures, divide by total, alert when the ratio crosses a threshold. It's the one signal most teams implement first and think they've nailed.

```promql
# Error rate
sum(rate(http_requests_total{status_code=~"5.."}[5m])) by (service)
/
sum(rate(http_requests_total[5m])) by (service)
```

Two things I've learned the hard way:

**First, not all errors are equal.** A `503` from a circuit breaker doing its job is different from a `500` because your database connection pool is exhausted. I categorize errors by whether they're expected (rate limiting, circuit breaking, validation failures) or unexpected (unhandled exceptions, timeouts, OOMs). Only the unexpected ones should page someone at 3am.

{% raw %}
```yaml
# Alert only on unexpected errors
- alert: HighUnexpectedErrorRate
  expr: |
    sum(rate(http_requests_total{status_code=~"5..", error_type="unexpected"}[5m])) by (service)
    /
    sum(rate(http_requests_total[5m])) by (service)
    > 0.01
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "{{ $labels.service }} unexpected error rate above 1%"
```
{% endraw %}

**Second, the errors you don't count are worse than the ones you do.** Timeouts that never return a status code, requests that get dropped at the load balancer, connections refused before they reach your application — none of these show up in your HTTP error metrics. You need infrastructure-level error tracking alongside application-level. ELB 5xx metrics, TCP connection errors, DNS failures. If you only look at what your app reports, you're looking at survivors.

```promql
# ALB 5xx that never reached your app
aws_alb_httpcode_elb_5xx_count_sum / aws_alb_request_count_sum
```

When this number is high and your app error rate is low, the problem is between the load balancer and your pods. Network policy, security group, target group health checks — look there.

## Saturation

The hardest signal to get right because it's different for every service. Saturation is "how full is your system" — but full of what?

For a web service, it might be connection pool utilization. For a queue consumer, it's queue depth and processing lag. For a database, it's active connections vs. max connections, or disk I/O utilization. For Kubernetes nodes, it's CPU and memory requests vs. allocatable capacity.

Here's what I track on EKS:

```promql
# Node CPU saturation — requested vs allocatable
sum(kube_pod_container_resource_requests{resource="cpu"}) by (node)
/
sum(kube_node_status_allocatable{resource="cpu"}) by (node)

# Memory pressure
sum(kube_pod_container_resource_requests{resource="memory"}) by (node)
/
sum(kube_node_status_allocatable{resource="memory"}) by (node)
```

The trap with saturation is that utilization and saturation are not the same thing. A node at 80% CPU utilization might be fine — or it might be throttling pods that need burst capacity. What matters is whether the utilization is causing degradation. I connect saturation to the other three signals: if saturation is high *and* latency is climbing *or* errors are increasing, that's a real problem. High saturation with stable latency and zero errors? That's efficient.

For DynamoDB (used it heavily at CaseFleet), saturation means consumed capacity vs. provisioned capacity, and it's one of the few places where the AWS metric alone is enough:

```promql
# DynamoDB throttling — the real saturation signal
aws_dynamodb_throttled_requests_sum > 0
```

If you're getting throttled, you're saturated. Period. No need for percentages.

## What the textbook doesn't tell you

The four signals are a monitoring framework, not an alerting framework. The mistake I see over and over is turning each signal into an independent alert. Latency above X? Page. Error rate above Y? Page. Saturation above Z? Page.

That gives you alert storms. All four signals degrade together during a real incident, so you get four pages for one problem. What you want is correlated alerting — or at minimum, grouped alerts with a single escalation path.

The other thing: these signals are for user-facing services. Background workers, batch jobs, async pipelines — they need different signals. Queue depth and processing lag matter more than request latency when nothing is request/response. Don't cargo-cult the framework into systems it wasn't designed for.

## The Grafana dashboard I keep rebuilding

Every new gig, I rebuild roughly the same dashboard. Four rows, one per signal. Top row is latency histograms (p50, p95, p99). Second row is traffic (RPS by endpoint, split by method). Third is errors (rate and ratio, split by expected/unexpected). Fourth is saturation (whatever is the bottleneck for that system).

The layout matters because when something breaks, you scan top to bottom. Latency spike → check traffic → check errors → check saturation. Every time. The order matches the diagnostic flow.

I've published enough Grafana JSON to know nobody imports someone else's dashboards. But the structure is the thing. Four rows. Consistent signal ordering. Every service gets the same layout so you don't have to relearn where to look when you're debugging at 2am.

## When to go beyond four

The golden signals are necessary but not sufficient. Once you have them, you'll find gaps:

Dependency health — are your downstream services healthy? Your latency might be fine, but if a dependency is degraded, you're on borrowed time. I add a fifth row to the dashboard for upstream/downstream health.

Business metrics — requests per second doesn't tell you if users are actually completing what they came to do. Conversion rate, successful transactions, jobs completed. These are harder to instrument but they're what the business actually cares about.

Cost — especially on AWS. If your traffic doubles and your autoscaler responds correctly, all four signals stay green. But your bill just doubled too. CloudWatch + Cost Explorer integration is worth the effort.

## The interview answer vs. the real answer

The interview answer is: latency, traffic, errors, saturation. The real answer is: those four, instrumented with histograms not averages, correlated not independent, split by error type, paired with infrastructure metrics your application can't see, and adapted per service type. The framework is the starting point, not the destination.

3h4x
