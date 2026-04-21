---
layout: post
title:  "kubernetes networking - how it actually works"
categories: tech
tags: [kubernetes, networking, cni, ebpf]
comments: True
---

Kubernetes networking has a reputation for being black magic. And honestly? When it first clicked for me I realized it's not magic at all — it's just a lot of clever layering. Let me walk you through it from the ground up.

<!-- readmore -->

## The golden rule

Three rules Kubernetes enforces unconditionally: every Pod gets its own IP, all Pods can reach each other without NAT, and node agents can talk to all Pods on their node. That's it. Everything else is built on top of this flat model. Pods behave like VMs on a LAN — no port mapping gymnastics, no `docker run -p` nonsense.

## Pod networking and the pause container

Here's something most people don't know — every Pod has a hidden `pause` container running inside it. It holds the network namespace. All your actual containers join that namespace, which means they share one IP and talk to each other over `localhost`. Pretty elegant.

The actual plumbing is done by a **CNI plugin** (Container Network Interface). When a Pod spawns, Kubernetes hands off to the CNI which:

1. Assigns a Pod IP from a subnet
2. Creates a `veth` pair — one end in the Pod's network namespace, one on the host
3. Wires the host end to a bridge or tunnel
4. Programs routes

Your choice of CNI defines almost everything about your cluster's network characteristics. **Flannel** wraps traffic in VXLAN tunnels — simple, overlay, boring in a good way. **Calico** uses BGP to program real routes between nodes — no encapsulation, native performance, feels like cheating. **Cilium** goes full eBPF and bypasses iptables entirely because iptables at scale is a crime. **AWS VPC CNI** hands Pods real VPC IPs so your security groups Just Work. Pick your poison.

## Services — virtual IPs and kube-proxy

Pods are ephemeral, their IPs change. **Services** give you a stable ClusterIP that load-balances to a set of Pods. But here's the thing: that ClusterIP doesn't exist on any interface anywhere. It's virtual. The magic is in **kube-proxy**.

kube-proxy watches the API server and programs the host networking layer. Three modes:

- **iptables** (default) — `DNAT` rules redirect ClusterIP traffic to a random Pod IP. Simple, works everywhere, falls over at scale (10k+ services = a rule table that makes kernels weep)
- **IPVS** — kernel's IP Virtual Server with hash tables. Much better at scale, more LB algorithms, fewer tears
- **eBPF (Cilium)** — no iptables, no kube-proxy at all. It rewrites the destination at `connect()` time, so there's no per-packet DNAT to do later. Fast and kind of beautiful.

When you create a Service, Kubernetes also creates **EndpointSlices** — lists of Pod IPs matching the selector. kube-proxy watches these and keeps rules in sync. Change a Pod, EndpointSlice updates, rules update. Continuously. Never stops.

## Ingress and the Gateway API

LoadBalancer Services are fine for one thing, but if you want host/path routing, TLS termination, or anything resembling a real frontdoor, you want an **Ingress**. An Ingress is a spec; the thing doing the work is an **Ingress Controller** — nginx, Traefik, HAProxy, Envoy, whatever you like. It runs as a Pod, sits behind a single LoadBalancer, and fans traffic out to Services based on rules you write.

The new hotness is the **Gateway API**, which is basically "Ingress, but this time we thought about it." Split roles (cluster operator owns the Gateway, app team owns the Routes), proper typed route kinds (`HTTPRoute`, `TCPRoute`, `GRPCRoute`), cross-namespace references that don't require YAML gymnastics. If you're starting today, skip Ingress and go Gateway API. If you're already on Ingress, don't rush — it's not going anywhere soon.

## DNS with CoreDNS

Every Pod's `/etc/resolv.conf` points at **CoreDNS** running inside the cluster. It watches the API server and serves live DNS for Services and Pods. No restarts, no reloads, just the truth as of about a second ago.

`my-service` resolves inside your namespace. `my-service.my-namespace.svc.cluster.local` is the full FQDN. You'll almost never type the long one — until you're three hours into a cross-namespace debugging session and it saves your life.

## The full journey of a request

Say a browser hits your app via a LoadBalancer:

1. Cloud LB forwards to a **NodePort** on any node — doesn't care which, they're all equivalent
2. That node's iptables/IPVS/eBPF rules `DNAT` the packet to a Pod IP (which may live on a completely different node, surprise)
3. CNI routes or tunnels the packet cross-node if needed
4. Packet arrives at the Pod's `veth`, enters the container's netns
5. App responds, reply is `SNAT`'d back so the client sees the Service IP and none of the mess behind it

Five layers of translation, all invisible to your app. That's the whole trick — every layer is boring on its own, and together they behave like a cloud.

## NetworkPolicy and Cilium going deeper

By default everything talks to everything — zero isolation, wide open, have fun. **NetworkPolicy** objects let you write firewall rules using label selectors, which is great, except: enforcement is the CNI's job. If your CNI doesn't implement it (vanilla Flannel, looking at you), your carefully crafted policies are silently ignored. No warning, no error, just vibes. Calico and Cilium actually honor them.

Cilium takes it further with **CiliumNetworkPolicy** — L7 filtering. Block specific HTTP paths, gRPC methods, Kafka topics, whatever. And **Hubble** gives you per-flow observability at basically zero performance cost. I'll be honest, the first time I watched live flows in Hubble I stared at it like a kid at a fish tank.

## tl;dr

pause container → CNI assigns IP + veth → kube-proxy programs DNAT rules → CoreDNS serves names → Ingress/Gateway handles the frontdoor → NetworkPolicy enforces isolation. Each layer is swappable, and every one of them is doing something clever you can ignore 99% of the time. Pick your CNI carefully though — it decides what "the other 1%" looks like.

Know what you are doing and have fun!

3h4x
