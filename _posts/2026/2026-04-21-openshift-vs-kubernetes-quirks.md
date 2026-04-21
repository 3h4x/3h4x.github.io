---
layout: post
title: "OpenShift is Kubernetes, except when it isn't — notes after touching it again"
categories: tech
tags: [openshift, kubernetes, prometheus, monitoring, devops, platform, redhat]
comments: True
---

"OpenShift is just Kubernetes with a web console, right?" — that was the question. The short answer is yes, and that is exactly the trap. The API is Kubernetes. `kubectl` works. Your manifests mostly apply. And then you hit four or five things that behave nothing like plain Kubernetes and cost you a day each until you learn the shape of them.

I've spent most of the last decade on vanilla Kubernetes — EKS, GKE, and a pile of self-managed things before that — with a few OpenShift touchpoints in older lives and one recent one. This post is a write-up of the quirks that have bitten me or people around me, including the big one: **you cannot customize OpenShift's platform Prometheus**. Not "it's hard", not "you need to know the right flag" — the operator actively undoes your edits. That alone is worth writing down.

<!-- readmore -->

## Framing: what OpenShift actually is

OpenShift is Red Hat's Kubernetes distribution. Upstream Kubernetes at its core, plus a thick layer of opinionated defaults, operators, and CRDs that together form a *platform* rather than a toolkit. That layer is the interesting part. A short, incomplete list of what's different out of the box:

- **Routes** (a pre-Ingress Red Hat concept) sit alongside Ingress. Both work. They do slightly different things. You'll see both in the same cluster.
- **SecurityContextConstraints** (SCCs) are enforced by default. Your pod can't run as root unless a service account is bound to a permissive SCC. Most upstream Helm charts don't know this.
- **Projects** instead of Namespaces (they're Namespaces under the hood with extra annotations, but regular users can't `kubectl create namespace` — they `oc new-project`).
- **Cluster Monitoring Operator** installs and *owns* a Prometheus stack in `openshift-monitoring`. You can look at it. You cannot meaningfully change it. More on this below.
- **OperatorHub / OLM** as the default way to install anything non-trivial. Helm works, but the cluster's center of gravity is operators.
- **Cluster Version Operator** manages upgrades. You don't `apply` your way to a new version — you set a channel and let the CVO drive.
- **Built-in image registry**, ImageStreams, and (still, in 2026) the occasional stray `DeploymentConfig` in someone's repo that should have been a `Deployment` a decade ago.
- **SELinux enforcing** on RHCOS nodes, which catches a surprising amount of otherwise-fine container images.

None of that is a problem on its own. The problem is when you show up with muscle memory from `kubectl apply -f kube-prometheus-stack/values.yaml` and expect it to behave.

## A note on `oc` vs `kubectl`

`oc` is a superset of `kubectl`. Every `kubectl` command works. But a handful of things you do daily in vanilla Kubernetes have an `oc` equivalent that does *more* and is what everyone else on an OpenShift cluster will be running:

```bash
# Create a project (a namespace + default network policy + default limits)
oc new-project my-app      # NOT `kubectl create ns` — regular users can't

# Drop into a running pod
oc rsh my-app-xxx          # `kubectl exec -it ... -- /bin/sh` with better defaults

# Expose a Service as a Route
oc expose svc/my-app       # creates a Route, not an Ingress

# Bind an SCC to a serviceaccount
oc adm policy add-scc-to-user nonroot-v2 -z my-app

# Log in with a token from the web console
oc login --token=sha256~... --server=https://api.cluster.example.com:6443

# Switch projects without editing kubeconfig contexts
oc project my-app
```

The one that trips people up hardest is `oc new-project` vs `kubectl create namespace`. On most OpenShift clusters, RBAC forbids regular users from creating Namespaces directly — the project request flow goes through a project-request template that RH ships, and `oc new-project` is what triggers it. If `kubectl create ns foo` gives you "forbidden", that's not a cluster misconfiguration, it's the design.

## Pitfall #1: the static platform Prometheus

This is the one I want to spend the most time on because it's the one I've seen waste the most hours.

In a vanilla Kubernetes cluster, if you install `kube-prometheus-stack` via Helm, you own it. You want to add a scrape config? Edit the values file. You want a new alerting rule? Drop a `PrometheusRule` in any namespace with the right label and the operator picks it up. The Prometheus CR is yours to edit.

On OpenShift, the platform Prometheus is installed and reconciled by the **Cluster Monitoring Operator** (CMO). CMO treats `openshift-monitoring` as its domain. Any direct edit you make to the `Prometheus` CR, the `Alertmanager` CR, the generated ConfigMaps, or the Operators' deployment specs gets reverted by the operator. Usually in seconds. Sometimes fast enough that you don't notice your change landed before it was undone.

The "correct" shape of that config is very narrow:

```yaml
# cluster-monitoring-config ConfigMap in openshift-monitoring
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-monitoring-config
  namespace: openshift-monitoring
data:
  config.yaml: |
    prometheusK8s:
      retention: 15d
      volumeClaimTemplate:
        spec:
          storageClassName: gp3-csi
          resources:
            requests:
              storage: 100Gi
    alertmanagerMain:
      volumeClaimTemplate:
        spec:
          storageClassName: gp3-csi
          resources:
            requests:
              storage: 20Gi
```

That's it. That's your knob. A short list of fields CMO will accept. Retention, storage, a handful of resource tweaks, node selectors, tolerations. Things like `additionalScrapeConfigs`, arbitrary `externalLabels`, custom remote-write with full flexibility, or mounting a secret the operator doesn't know about are not on the menu. The config schema is a [documented, finite surface](https://docs.openshift.com/container-platform/latest/observability/monitoring/configuring-the-monitoring-stack.html). If what you need isn't in it, you don't get to have it on the platform Prometheus.

First time I watched this happen, I did it to myself. Edited the `prometheus-k8s` CR directly to add a scrape config, saved it, watched it land, moved on. Came back ten minutes later to check the target was up and the field was gone. Tried again — gone. Ran `oc get prometheus prometheus-k8s -n openshift-monitoring -o yaml -w` and watched my edit vanish inside of ninety seconds, clean. No error, no event I caught at first glance. The operator was doing what it's paid for. CMO's reconcile loop is on a resync period of a few minutes, but anything it notices via watch it stomps on almost immediately.

The useful event is there, you just have to know to look for it on the operator, not on the resource you edited:

```bash
oc -n openshift-monitoring logs deploy/cluster-monitoring-operator \
  | grep -i 'reconcil\|overwrit\|reverting'
```

The escape hatch is **User Workload Monitoring** (UWM), a *second* Prometheus in `openshift-user-workload-monitoring` that exists specifically so teams can have their own scrape targets. You enable it with a single field:

```yaml
# cluster-monitoring-config — enables UWM
data:
  config.yaml: |
    enableUserWorkload: true
```

And then you configure it with its own ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: user-workload-monitoring-config
  namespace: openshift-user-workload-monitoring
data:
  config.yaml: |
    prometheus:
      retention: 24h
      volumeClaimTemplate:
        spec:
          storageClassName: gp3-csi
          resources:
            requests:
              storage: 40Gi
```

Now `ServiceMonitor`, `PodMonitor`, and `PrometheusRule` resources dropped into your *own* namespaces get picked up by the UWM Prometheus. The platform Prometheus continues to scrape platform things — kubelet, node-exporter, etcd (which you can't see anyway on ROSA/ARO), the API server, the operators — and ignores you.

There's a silent failure mode hiding in here that I want to flag specifically because I've seen two different teams hit it:

> A `ServiceMonitor` in your application namespace is picked up by **UWM Prometheus**, not the platform one. If UWM is not enabled, or your `ServiceMonitor` is mis-labelled, or it lives in a namespace not selected by UWM's `namespace-selector`, it is silently ignored. No error. No event. The resource just exists, and nothing scrapes it.

The UWM Prometheus selects ServiceMonitors with an empty label selector across user-workload namespaces (essentially, everything outside `openshift-*` and `kube-*`). The gotcha isn't the ServiceMonitor's own label — it's whether the Service it points at actually carries the labels your selector claims:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  namespace: my-app         # must NOT be openshift-* or kube-*
spec:
  selector:
    matchLabels:
      app: my-app           # <-- this must match the Service's labels
  endpoints:
    - port: metrics         # <-- named port on the Service, not a number
      interval: 30s
      path: /metrics
```

If the port is unnamed on the Service, or the Service labels don't match, the target just won't appear. The prometheus-operator logs this at debug level and is otherwise silent:

```
level=debug component=prometheusoperator msg="skipping servicemonitor" \
  namespace=my-app name=my-app reason="no matching service"
```

You won't see that in the default log level.

The diagnostic I wish I'd known the first time:

```bash
# Is UWM actually enabled? If it is, these pods exist.
oc get pods -n openshift-user-workload-monitoring

# Do the Prometheus instances agree that they see your ServiceMonitor?
oc -n openshift-user-workload-monitoring exec -c prometheus \
  prometheus-user-workload-0 -- \
  wget -qO- http://localhost:9090/api/v1/targets | \
  jq '.data.activeTargets[] | {scrapePool, health, labels}'
```

If your target isn't in that list, the ServiceMonitor isn't being picked up. Check the namespace it's in, the label selectors on the UWM Prometheus CR, and whether the service you're pointing at actually exists with matching labels.

**Federation** is the other thing people reach for — "I'll just run my own Prometheus and federate the platform one." It works, but the platform Prometheus exposes `/federate` on an authenticated endpoint (bearer token for a service account with `cluster-monitoring-view`), and the default rate limits on the federation endpoint will make you sad if you try to pull the full cardinality through it at 15s. Use it for the handful of platform series you actually need, not as a general-purpose scrape source.

The lesson, the one I'd put on a card above my desk if I were going back to OpenShift full time: **do not fight the operator**. If the knob isn't exposed, the answer is UWM or a parallel stack, not a hand-edit that will outlive you by about ninety seconds.

The same pattern applies to **Alertmanager**. Same operator, same reconcile loop, same behavior. You do not edit the `Alertmanager` CR. You provide a secret and CMO reads it:

```bash
oc -n openshift-monitoring create secret generic alertmanager-main \
  --from-file=alertmanager.yaml=./alertmanager.yaml \
  --dry-run=client -o yaml | oc apply -f -
```

Forget this and your receivers get stomped on the next reconcile, which is how PagerDuty goes quiet for six hours and nobody knows why. Same story for the UWM Alertmanager if you've enabled a second one for user-workload alerts.

## Pitfall #2: SCCs versus every Helm chart in the wild

Upstream Helm charts assume containers can run as whatever UID the image wants, usually including root. OpenShift assigns containers a random UID per project and denies root unless an SCC explicitly allows it. This breaks a lot of charts in two specific, confusing ways.

First flavor — the pod never starts, and the event says so:

```
Error creating: pods "my-app-" is forbidden: unable to validate against
any security context constraint: [provider "anyuid": Forbidden: not usable
by user or serviceaccount, provider restricted-v2: .spec.securityContext.runAsUser:
Invalid value: 0: must be in the ranges: [1000680000, 1000689999]]
```

That's the admission controller refusing the pod because nothing in its SCC set allows UID 0. The fix is never to patch the chart to `runAsUser: 1000680000` and hope — the UID range is per-project and will be different on the next namespace.

Second flavor — the pod admits fine under `restricted-v2`, starts as a random UID like `1000680012`, and crashes because `/etc/something` isn't writable by that UID. The image was built assuming root and nobody noticed because it worked on Docker Desktop.

To see which SCC actually admitted a running pod:

```bash
oc get pod my-app-xxx -o yaml | grep openshift.io/scc
# openshift.io/scc: restricted-v2
```

The fix is almost never "give it `privileged`". It's usually one of:

```bash
# Allow a specific service account to run as any UID in the image
oc adm policy add-scc-to-user anyuid -z my-service-account

# Or, better, write a SCC that grants just what's needed
oc get scc anyuid -o yaml > my-scc.yaml
# ... edit, rename, tighten ...
oc apply -f my-scc.yaml
oc adm policy add-scc-to-user my-scc -z my-service-account
```

The `nonroot-v2` SCC is the modern default target. If your chart can run as non-root with a read-only root FS and an emptyDir for scratch, `nonroot-v2` works and you don't need to grant anything. If it can't, fix the chart — don't loosen the SCC across the project.

The trap is that `anyuid` is the quick fix that ships to production and never gets tightened. Six months later you've got eight service accounts with `anyuid` and no one knows which still need it.

## Pitfall #3: Routes and Ingress doing different things

OpenShift has Routes. It also has Ingress, because upstream caught up six years later. The Ingress Operator *translates* Ingress into Route under the hood on the cluster router, so in most cases they behave the same. Having both is fine; mixing them on the same hostname is a speedrun to 503s. Specifically:

- TLS termination defaults differ. A Route defaults to edge termination; an Ingress via the operator may pick re-encrypt depending on the backend service's annotations.
- WebSocket and HTTP/2 behavior can differ per router deployment.
- Wildcard hosts are a Route feature that requires an explicit opt-in flag on the IngressController. If your Helm chart generates wildcard ingresses, they'll silently not route until the operator is told to accept them:

```yaml
apiVersion: operator.openshift.io/v1
kind: IngressController
metadata:
  name: default
  namespace: openshift-ingress-operator
spec:
  routeAdmission:
    wildcardPolicy: WildcardsAllowed
```

If you're porting a chart that uses Ingress, it usually just works. If you're porting something that used Route-specific features (path-based routing with specific priorities, re-encrypt with a destination CA) you may need to keep the Route resource rather than convert.

## Pitfall #4: DeploymentConfig is not Deployment, and you should stop using it

`DeploymentConfig` is the OpenShift-specific pre-cursor to upstream `Deployment`. It has ImageStream triggers and its own lifecycle hooks. It is effectively deprecated — Red Hat has been recommending `Deployment` for new workloads for years — but in 2026 you will still find `kind: DeploymentConfig` in templates in the wild. It behaves subtly differently: rolling updates go through the OpenShift deployer pod, not the kube controller manager, and when something goes wrong you end up debugging a deployer pod instead of a ReplicaSet rollout.

If you inherit a repo that uses `DeploymentConfig`, convert it. It's almost always a one-to-one port plus moving the image-change trigger to something Argo or Flux can see, or replacing the ImageStream with a plain registry reference.

## Pitfall #5: ImageStreams pretend to be images, right up until they don't

The internal registry and ImageStream system are genuinely clever — `oc new-app` on a git URL, S2I builds, image-change triggers that redeploy on new tags. The trap is that `ImageStreamTag` is *not* a container image reference; it's an indirection that resolves to one. Pods that reference `image-registry.openshift-image-registry.svc:5000/myproj/myapp:latest` are talking to the internal registry service directly and skip the ImageStream. Pods with an `image` set to `myapp:latest` plus an image-change trigger on a `DeploymentConfig` go through the ImageStream, which resolves to a digest pinned at import time.

Two failure modes fall out of this:

- **Stale `latest`.** An ImageStream with import policy `scheduled: false` imports the tag once and pins the digest. Push a new `latest` to Quay and the ImageStream *does not update* until you re-import it (`oc import-image myapp:latest --from=quay.io/org/myapp --confirm`). Plain-Kubernetes muscle memory says `imagePullPolicy: Always` fixes this. It does not. The ImageStream is what's stale, not the kubelet cache.
- **Pull secrets that aren't where you think.** Pods pulling from the internal registry need `system:image-puller` on the serviceaccount in the source project. Pods pulling from an external registry need the pull secret linked to the serviceaccount *or* the default `builder`/`default` serviceaccounts, depending on which did the pull. `oc secrets link default <my-pull-secret> --for=pull` is the command that solves 90% of "ImagePullBackOff on a registry I can curl from the node".

The shortest path away from all of this is: use external registry references with plain `kind: Deployment`, skip ImageStreams unless you're actively using S2I or image-change triggers. You lose the scheduled import feature. You gain one less indirection to debug at 2 AM.

## Pitfall #6: the mental model for upgrades is different

On EKS, I upgrade by changing the version number in Terragrunt and watching. I wrote about that process [last year](/tech/2025/04/14/eks-upgrades-across-environments), and the cadence is "one minor version at a time, four environments, couple of weeks of baking". The whole thing is a set of API calls I choose to make.

On OpenShift, you pick a **channel** (`stable-4.17`, `fast-4.17`, `candidate-4.17`) and the Cluster Version Operator tells you what upgrade paths are available. You don't freely pick a version — you get the graph of approved transitions. Which is good: it means Red Hat has tested the path you're taking. It's also different: you're no longer in full control of the sequence. Plan for it.

```bash
oc get clusterversion
oc adm upgrade  # shows what you can move to
oc adm upgrade --to=4.17.12  # or just --to-latest for the channel
```

Mid-upgrade, the ClusterVersion status tells you what's happening at a level of granularity EKS never exposed — per-operator progress, per-node MachineConfig rollout, which ClusterOperator is currently degraded. It's a better experience, honestly. It's also much more opinionated.

## When it's actually better than EKS

I don't want this post to read as anti-OpenShift. The opinions bite when you don't know them, and they're helpful once you do. In particular:

- The monitoring stack "just exists". You don't install kube-prometheus-stack. You don't argue with Helm values. It's there, it works, it's patched with the cluster.
- SCCs are strictly better than PSPs and saner than a half-configured Pod Security Admission. "Your workload needs an SCC" is a clear conversation; "why is PSA in warn mode on this namespace but enforce on that one" is not.
- The Operator ecosystem for databases, message queues, and middleware is genuinely good. OLM handles upgrades. You're not managing Helm values for a distributed system at 11 PM.
- Upgrades are boring in the good sense. Tested paths, clear status, one operator at a time.

The cost is that it is a *platform*, not a toolkit. If your team's mental model is "Kubernetes is a set of primitives I compose", OpenShift will feel like it's taking your toys away. If your team's mental model is "I want a supported, opinionated, upgradable thing my devs can ship on", OpenShift is closer to what you want than vanilla EKS with twenty Helm charts duct-taped together.

## When NOT to use OpenShift

A few cases where I'd push back:

- **You're a small team without a Red Hat subscription budget.** OKD (the upstream) exists but is not what most people mean when they say OpenShift, and supported OpenShift is not cheap. EKS + kube-prometheus-stack + Argo is a fraction of the cost.
- **You need full control of Prometheus scrape targets, remote-write, and exemplars on a single instance.** The platform Prometheus doesn't do it and UWM has limits too. Run your own stack parallel to the platform one — at which point, why are you paying for OpenShift's monitoring?
- **You want to live inside `kubectl` and raw manifests.** `oc` is strictly a superset, but the platform's center of gravity is the web console + Operators. If you're going to fight the opinions, that's friction forever.
- **You're running one app on three nodes.** OpenShift's overhead — CMO, OLM, the router, the monitoring stack, ingress-operator, DNS-operator, etc. — is real. On a tiny cluster it's a tax.

OpenShift earns its keep on clusters with actual breadth: many teams, many services, a platform group that wants *one* supported thing and doesn't want to argue about Helm chart versions every quarter. On those, the pitfalls above are cheap once you've paid them once.

## The tl;dr card I'd tape to a desk

If I had to hand someone a cheat sheet for getting productive on OpenShift in a week, it would be this:

```
1. Don't edit the Prometheus CR. Use cluster-monitoring-config
   and User Workload Monitoring.
2. Don't edit the Alertmanager CR. Provide a secret.
3. Your pod is not root. Find the SCC that fits and bind it to
   the service account. `nonroot-v2` first; `anyuid` is a smell.
4. Prefer Route for Route things, Ingress for portable things,
   don't mix them on the same hostname.
5. Use Deployment, not DeploymentConfig.
6. Skip ImageStreams unless you're actively using S2I. External
   registry + plain Deployment is one less indirection at 2 AM.
7. Upgrade by channel, not by wishing.
8. When something doesn't stick, suspect an operator reconciling
   it away. Watch: `oc get <cr> -w` and the operator's own logs,
   not just the resource you edited.
```

The theme across all of them: **operators own their scope, and you work with them, not through them**. Once that clicks, OpenShift stops being "Kubernetes with a weird web console" and starts being the thing it's actually designed to be — a platform where the expensive decisions are already made.

Know what you are doing and have fun!

3h4x
