---
layout: post
title: "Upgrading EKS across four environments — the rolling strategy"
categories: tech
tags: [kubernetes, aws, terraform, eks, devtools]
comments: True
---

Upgrading Kubernetes on EKS sounds simple — change a version number, apply, done. In practice, with four environments (devnet, testnet, preprod, prod) and services that can't afford downtime, it's a multi-week process with a lot of "apply and watch" in between. I just finished rolling from 1.29 to 1.33 across the board, and here's what that actually looked like.

<!-- readmore -->

## The environment ladder

The upgrade order is always the same:

```
devnet → testnet → preprod → prod
```

Each environment sits for at least a few days on the new version before the next one moves. Devnet can break — it's where we catch the obvious stuff. Testnet runs real workloads but with synthetic traffic. Preprod mirrors prod topology. Prod is prod.

The gap between environments is intentional. Kubernetes deprecation warnings don't always show up in CI — they show up when a specific workload hits a removed API or a changed default. Running each environment for a few days on the new version before promoting catches these.

## Pre-upgrade: find the deprecated API calls before they bite you

Before touching anything, I check what deprecated API calls are actually in flight. AWS will remove deprecated APIs when the version that drops them goes GA, and the warnings are not always obvious in application logs.

```bash
# Check deprecated API usage from the API server metrics
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis
```

This gives you a count of requests per API group/version/resource. If you see anything with a non-zero count for an API that's being removed in your target version, that workload needs fixing before the upgrade. Don't skip this.

```bash
# More readable with a filter
kubectl get --raw /metrics \
  | grep apiserver_requested_deprecated_apis \
  | grep -v "# "
```

Also worth running `kubectl convert` dry-runs on your Helm chart manifests if you manage any directly:

```bash
kubectl convert -f deployment.yaml --output-version apps/v1 --dry-run=client
```

And a quick sanity check on what's currently deployed cluster-wide:

```bash
# List all API versions in use across the cluster
kubectl api-resources --verbs=list -o name \
  | xargs -I{} kubectl get {} --all-namespaces -o jsonpath='{range .items[*]}{.apiVersion}{"\n"}{end}' 2>/dev/null \
  | sort -u
```

Yes, this takes a minute to run. Worth it.

## The Terragrunt side

We use Terragrunt, not plain Terraform — so the `kubernetes_version` lives in the environment-specific `terragrunt.hcl`, not a shared module:

```hcl
# environments/prod/eks/terragrunt.hcl
inputs = {
  kubernetes_version = "1.33"
}
```

Each environment directory has its own `terragrunt.hcl` that inherits from a root config. When we bump the version in devnet's file and `terragrunt apply`, it only touches devnet. No cross-environment blast radius.

But changing that one variable still triggers a cascade:

1. The EKS control plane upgrades (managed by AWS, **takes 15-25 minutes**)
2. Managed node groups need to be updated to the new AMI (**5-10 minutes per node group**, depends on pod count and drain speed)
3. EKS add-ons (`coredns`, `kube-proxy`, `aws-ebs-csi-driver`, `vpc-cni`) need version bumps
4. The `cloudposse/eks-node-group` module version might need updating

The Terragrunt dependency graph matters here. If your node group module `depends_on` the EKS cluster, Terragrunt will wait for the control plane to finish before touching node groups. That's correct behavior — but it means you can't parallelize control plane + node group upgrades. The total wall time is additive.

For a cluster with three node groups (system, on-demand, spot), budget roughly:

- Control plane: 15-25 min
- Node groups: 10-20 min each (rolling, so longer if you have many nodes or slow-draining pods)
- Add-on updates: 2-5 min

So 1-2 hours of apply time total, in practice.

## Add-on version compatibility — the annoying part

The add-on version matrix is where people get burned. Each Kubernetes version has a specific range of compatible add-on versions, and the AWS docs are perpetually a release behind. By the time 1.33 was available, the docs still showed the 1.32 max versions for several add-ons.

What actually works: open the EKS console, navigate to your cluster → Add-ons, and click on each one. AWS shows you the available versions directly. Cross-reference with the add-on's GitHub releases to understand what changed.

For 1.33, this is where I landed:

```hcl
cluster_addons = {
  coredns    = { addon_version = "v1.12.1-eksbuild.2" }
  kube-proxy = { addon_version = "v1.33.0-eksbuild.1" }
  vpc-cni    = { addon_version = "v1.19.3-eksbuild.1" }
  aws-ebs-csi-driver = { addon_version = "v1.44.0" }
}
```

The EKS build suffix (`-eksbuild.N`) indicates AWS patches on top of upstream. Higher is generally better — they backport fixes. Don't pin to `-eksbuild.1` if `-eksbuild.3` is available.

Get one of these wrong and you'll see pods failing to schedule, volumes not attaching, or DNS resolution breaking. None of these fail loudly during `terragrunt apply` — they fail when workloads try to use them. By then you're debugging at midnight wondering why new PVCs are stuck in `Pending`.

## Node group rolling updates

The trickiest part is updating node groups without downtime. EKS managed node groups support rolling updates — old nodes drain, new nodes launch with the updated AMI, pods migrate. But "drain" means evicting all pods, and if your pod disruption budgets are misconfigured (or missing), you'll drop traffic.

What I do:

1. Set `force_update_version = true` so Terraform doesn't get stuck waiting for manual intervention
2. Ensure every deployment has a PDB with `minAvailable: 1` (for small deployments) or a meaningful percentage
3. Watch `kubectl get nodes -w` during the rollout — old nodes go `SchedulingDisabled`, new nodes come up `Ready`
4. If a node stays in `NotReady` for more than 5 minutes, something's wrong with the new AMI — check `kubectl describe node <name>` and the EC2 console

```bash
# Watch node status live during rollout
kubectl get nodes -w

# Check which nodes are on old AMI
kubectl get nodes -o custom-columns=\
'NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,AMI:.metadata.annotations.alpha\.kubernetes\.io/provided-node-ip'
```

The node repair feature in newer `cloudposse/eks-node-group` module versions (3.3.0+) helps — it automatically replaces unhealthy nodes. I enabled it across all node groups:

```hcl
node_repair_enabled = true
```

Without this, a node that gets stuck in `NotReady` just sits there until you manually terminate it. With repair enabled, the module handles it automatically.

## What broke during 1.32 → 1.33

Every major upgrade has at least one surprise. This time:

**CoreDNS version mismatch.** The old CoreDNS version (`v1.11.4`) wasn't compatible with Kubernetes 1.33 API changes. Pods could still resolve DNS, but CoreDNS was logging errors about deprecated API calls. Updated to `v1.12.1` and the errors stopped.

**EBS CSI driver.** The old version couldn't provision new `gp3` volumes on 1.33 nodes. Existing volumes worked fine (they were already attached), but new pod starts that needed a fresh PVC would hang. Updated from `v1.43.0` to `v1.44.0`.

**kube-prometheus-stack Helm chart.** The monitoring stack's ServiceMonitors referenced some API paths that changed in 1.33. Had to bump the chart from `72.2.0` to `73.2.0`. While I was at it, I disabled monitoring rules for `etcd` and `kube-apiserver` — these are managed by AWS on EKS, I can't see their metrics anyway, and the alerts were just noise.

**`kubectl` client version.** Obvious in hindsight, but if your local `kubectl` is two minor versions behind the cluster, some commands behave oddly. Keep your local tooling current. Same goes for `helm` — the API deprecations affect Helm releases too if your chart templates are old.

## The full upgrade checklist

After doing this enough times, I wrote it down:

```
Pre-upgrade:
1. kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis
2. Check EKS add-on compatibility matrix for target version (use console, not docs)
3. Update add-on versions in Terragrunt inputs
4. Bump cloudposse module if needed
5. Review Helm chart changelogs for anything that touches removed APIs

Per-environment:
6. Apply to devnet (control plane: ~20min, nodes: ~15min per group)
7. Watch kubectl get nodes -w until all nodes show new kubelet version
8. Check Prometheus for elevated error rates (5xx, latency spikes)
9. Check CoreDNS logs for deprecation warnings
10. Check EBS CSI driver — try creating a test PVC
11. Sit on the version for 2-3 days before promoting
12. Repeat for testnet, then preprod

Prod:
13. Apply during low-traffic window
14. Watch Grafana for 30 minutes post-apply
15. Verify all node groups rolled over (no old nodes lingering)
16. Update your runbook / documentation
```

Steps 8 and 9 catch most issues. If error rates are flat and CoreDNS is quiet, the upgrade probably went fine.

## Why not blue/green clusters?

The "proper" way is to spin up a new cluster on the target version and migrate workloads. No in-place upgrade risk, easy rollback (just switch DNS back).

I tried this once. The migration was clean, but the networking setup (VPC peering, security groups, IAM roles, service accounts, IRSA annotations on every service account) took longer to replicate than the in-place upgrade itself. With Terragrunt, you also have to wire up a parallel dependency graph for the new cluster — and then tear it down cleanly when you're done.

For a small team running a handful of services, in-place upgrades with the environment ladder are faster and simpler. If your cluster has dozens of services with complex cross-service networking or strict compliance requirements around rollback guarantees, blue/green is probably worth it. For mine, it's not.

## Staying current

The worst thing you can do with EKS is fall behind. AWS supports three Kubernetes versions at any time. Fall two versions behind and you're doing a multi-hop upgrade. Fall three behind and you're in extended support territory — AWS charges extra for that, and rightfully so.

I try to upgrade within a month of a new EKS version being available. The cadence is roughly quarterly, so it's a week of work (spread across a few weeks of baking time) every three months. Not glamorous, but the alternative is a panic upgrade when AWS announces end-of-support with a deadline.

Set a calendar reminder when AWS announces a new version. Don't let it slip.

3h4x
