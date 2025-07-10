---
layout: post
title: "Spot instances on EKS — cutting costs without cutting reliability"
categories: tech
tags: [kubernetes, aws, eks, cost reduction, terraform]
comments: True
---

Our EKS bill was growing faster than our traffic. Most of it was compute — on-demand `t3.medium` and `t3a.medium` instances running 24/7 for services that could tolerate occasional restarts. Spot instances are 60-70% cheaper than on-demand, but the trade-off is AWS can reclaim them with 2 minutes notice. The question was: which services can handle that, and how do you set it up without making the cluster fragile?

<!-- readmore -->

## Which services go on spot

Not everything. The rule is simple: if the service is stateless, horizontally scaled, and can handle a cold restart without data loss — it's a spot candidate. If it holds state, runs a single replica, or has a long startup time — it stays on-demand.

In our case:

| Service type | Spot? | Why |
|---------|-------|-----|
| Stateless workers (16 replicas) | Yes | Fast startup, tolerates pod eviction |
| RPC / full nodes | No | Long sync time, needs stable connectivity |
| Singleton services | No | Single instance, holds in-memory state |
| Coordination layer | No | Can't afford interruption |

The stateless worker pool was the obvious first candidate. It runs 16 replicas doing independent calculations. If one pod gets evicted, the other 15 keep serving. By the time Kubernetes reschedules the evicted pod on a new node, the interruption is invisible.

## Terraform setup

The node group config uses mixed instance types to maximize spot availability:

```hcl
variable "spot_instance_types" {
  default = ["t3.medium", "t3a.medium", "t3.small", "t3a.small"]
}

module "spot_node_group" {
  source = "cloudposse/eks-node-group/aws"

  cluster_name    = var.cluster_name
  instance_types  = var.spot_instance_types
  capacity_type   = "SPOT"

  desired_size = var.worker_instance_count
  min_size     = 1
  max_size     = var.worker_instance_count * 2

  kubernetes_labels = {
    "node-type" = "spot"
    "worker"    = "true"
  }

  taints = [{
    key    = "spot"
    value  = "true"
    effect = "NO_SCHEDULE"
  }]
}
```

**Multiple instance types.** If you specify only `t3.medium`, AWS might not have spot capacity in your AZ. Adding `t3a.medium` (AMD variant, slightly cheaper), `t3.small`, and `t3a.small` gives the spot allocator more options. More on the allocation strategy in a second.

**Taints.** The `spot=true:NoSchedule` taint prevents non-spot-tolerant pods from landing on these nodes. Only pods with the matching toleration get scheduled here. This keeps your critical services off spot nodes even if the scheduler has room.

**Max size headroom.** Setting `max_size` to double `desired_size` gives the cluster autoscaler room to spin up replacement nodes quickly when a spot interruption hits.

## `capacity-optimized` vs `lowest-price` — pick one and understand it

This is a decision that actually matters. AWS offers two spot allocation strategies:

**`lowest-price`**: Picks the cheapest instance type from your list. Sounds good until you realize the cheapest spot pool is often the most contended one. If everyone's chasing the same `t3.medium` pool in `us-east-1a`, interruption rates go up. You're optimizing for penny savings while increasing the chance AWS yanks your nodes.

**`capacity-optimized`**: Picks the instance type with the most available spot capacity — not necessarily the cheapest. The logic is that AWS is less likely to interrupt instances from deep pools because they have spare capacity to absorb demand. In practice, this means slightly higher spot pricing but meaningfully lower interruption rates.

I use `capacity-optimized`. The cost difference is small (usually 5-15% more than `lowest-price`), but the stability improvement is worth it for anything production-adjacent. If you're running batch jobs where interruptions are trivially retried, `lowest-price` is fine. If your pods take 30+ seconds to warm up, you want fewer interruptions, not cheaper instances.

In the `cloudposse/eks-node-group` module, this maps to:

```hcl
spot_allocation_strategy = "capacity-optimized"
```

## aws-node-termination-handler setup

When AWS decides to reclaim a spot instance, the node gets an interruption notice via the EC2 metadata endpoint and EventBridge — about 2 minutes before termination. Without handling this, your pods get killed ungracefully and Kubernetes takes time to notice the node is gone.

`aws-node-termination-handler` (NTH) runs as a `DaemonSet` and watches for:
- Spot interruption notices
- Scheduled maintenance events
- Instance health events

When it sees an interruption, it cordons the node immediately (stops new pods from scheduling there) and starts draining pods gracefully. This gives your pods time to finish in-flight requests and lets Kubernetes reschedule them elsewhere before the axe falls.

Install via Helm:

```bash
helm repo add eks https://aws.github.io/eks-charts
helm install aws-node-termination-handler eks/aws-node-termination-handler \
  --namespace kube-system \
  --set enableSpotInterruptionDraining=true \
  --set enableScheduledEventDraining=true \
  --set nodeSelector."node-type"=spot
```

The `nodeSelector` matters — you want NTH running on your spot nodes specifically. Running it everywhere adds overhead without benefit for on-demand nodes.

In Terraform/Helm via Terragrunt:

```hcl
resource "helm_release" "aws_node_termination_handler" {
  name       = "aws-node-termination-handler"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-node-termination-handler"
  namespace  = "kube-system"
  version    = "0.21.0"

  set {
    name  = "enableSpotInterruptionDraining"
    value = "true"
  }
  set {
    name  = "enableScheduledEventDraining"
    value = "true"
  }
  set {
    name  = "nodeSelector.node-type"
    value = "spot"
  }
}
```

The drain respects PodDisruptionBudgets. If you have `minAvailable: 12` on your 16-replica worker deployment, the drain will only evict pods if at least 12 remain available elsewhere. If there isn't room, the drain waits (up to the 2-minute deadline), and the pod gets killed ungracefully anyway. This is why max_size headroom matters — you need spare capacity for evicted pods to land.

## Pod tolerations and affinity

The worker deployment needs to tolerate the spot taint and prefer spot nodes:

```yaml
spec:
  tolerations:
    - key: "spot"
      value: "true"
      effect: "NoSchedule"
    - key: "worker"
      value: "true"
      effect: "NoSchedule"
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchExpressions:
              - key: worker
                operator: In
                values: ["true"]
```

The double taint (`spot` + `worker`) ensures only worker pods land on worker spot nodes. Without this, you risk other spot-tolerant services competing for the same nodes.

## The mixed on-demand + spot fallback

Pure spot node groups are great until spot capacity dries up in your AZ. This happens during AWS demand spikes — re:Invent week, end-of-month batch job rushes, certain AZs just running low. When it happens, new nodes can't launch, evicted pods go `Pending`, and your "cost-optimized" setup becomes an incident.

The safest approach is a mixed node group or a dedicated on-demand fallback group with its own tolerations:

```hcl
# Fallback on-demand node group with same labels
module "spot_fallback_node_group" {
  source = "cloudposse/eks-node-group/aws"

  cluster_name   = var.cluster_name
  instance_types = ["t3.medium"]
  capacity_type  = "ON_DEMAND"

  desired_size = 1
  min_size     = 0
  max_size     = var.worker_instance_count

  kubernetes_labels = {
    "node-type" = "spot-fallback"
    "worker"    = "true"
  }

  # Same taint as spot, so worker pods tolerate it
  taints = [{
    key    = "spot"
    value  = "true"
    effect = "NO_SCHEDULE"
  }]
}
```

With this setup, if the spot group can't scale, the cluster autoscaler falls back to the on-demand group automatically. Worker pods land there at higher cost, but they run. When spot capacity returns, the autoscaler scales down on-demand nodes and moves pods back.

I haven't needed this fallback in practice — diversifying instance types across AZs has kept capacity available. But it's a 10-line Terragrunt addition for meaningful insurance.

## Monitoring spot health

A few things I watch in Grafana:

**Spot interruption rate.** NTH exposes metrics. If interruptions spike above baseline, it might be time to add more instance types or switch AZs.

**Pod restart count.** A steady trickle of restarts on spot nodes is normal. A sudden spike means something else is going on.

**Scheduling latency.** If evicted pods take more than 60 seconds to get rescheduled, the cluster autoscaler might be struggling to provision replacement nodes.

**Pending pods.** Should be near zero normally. If it climbs, check autoscaler logs — it'll tell you why it can't provision.

```promql
# Pod restarts on spot nodes (last 5m rate, by pod)
sum(rate(kube_pod_container_status_restarts_total[5m])) by (pod, node)
  * on(node) group_left() kube_node_labels{label_node_type="spot"}

# Pending pods — should be near zero
count(kube_pod_status_phase{phase="Pending"}) by (namespace)

# Spot nodes that were recently terminated (from NTH metrics)
increase(aws_node_termination_handler_actions_total{action="cordon"}[1h])

# Cluster autoscaler scale-up events
increase(cluster_autoscaler_scaled_up_nodes_total[1h])

# Pod scheduling latency (time from Pending to Running)
histogram_quantile(0.95, 
  rate(kube_pod_scheduler_duration_seconds_bucket[5m])
)
```

Set an alert if pending pods stay elevated for more than 3 minutes. That's the signal that something structural is wrong — not just normal churn.

## Cost impact

Before spot (16 x `t3.medium` on-demand):

```
16 instances × $0.0416/hr × 730 hours/month = $486/month
```

After spot (16 x mixed `t3.medium`/`t3a.medium` spot):

```
16 instances × ~$0.0125/hr × 730 hours/month = $146/month
```

That's a 70% reduction on the worker node group. For the whole cluster, spot instances brought the monthly compute bill down by about 40% — the on-demand node groups for RPC, singletons, and coordination services still run at full price.

## Lessons learned

**Don't put all spot eggs in one AZ.** If your node group only spans one availability zone and that zone runs out of spot capacity, you get zero nodes. Always spread across at least 2 AZs — preferably 3.

**Start with one service.** Don't flip everything to spot at once. Pick the most resilient service, run it on spot for a month, watch the metrics, then expand. Steady trickle of restarts is fine. Pods stuck in `Pending` is not.

**Use `capacity-optimized`.** Yes, it's slightly more expensive. No, it's not worth the interruption headaches of chasing the `lowest-price` pool.

**Test the interruption path.** Before going to prod, simulate a spot interruption by draining a node manually:

```bash
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
```

Watch what happens. If pods don't reschedule cleanly, fix your PDBs and resource requests before real interruptions do it for you. The 2-minute window feels long until you're watching pods fail to reschedule because max_size is too low.

3h4x
