---
layout: post
title:  "Cassandra on Marathon"
date:   2015-03-28 10:21:38
categories: cassandra marathon docker mesos
comments: True
published: false
---
## Mesos

### Mesos & Marathon
Recently all I talk about is [mesos](http://mesos.apache.org/) and mesos on mesos ;)

> Apache Mesos abstracts CPU, memory, storage, and other compute
> resources away from machines (physical or virtual), enabling
> fault-tolerant and elastic distributed systems to easily be built and
> run effectively.

Sounds fantastic and because I'm true fan of docker I went with
[marathon](https://mesosphere.github.io/marathon/)

> which is a cluster-wide init and control system for
> services in cgroups or Docker containers

In combination wiht some effort mesos can replace existing
infrastructure making it more:
* manageble
* efficient
* easier to access
* fault-tolerant
* scalable

After some quick test on my computer creating mesos cluster with
docker-compose i gave it a big go and installed it
[TouK](https://touk.pl)

## First use case!

TouK is developing an application [ctrl-pkw](https://github.com/TouK/ctrl-pkw) to collect protocols from poll stations and check if election results were not tampered.

So beside my plan to move most of the virtual machines from KVM to
mesos I got a task to create [cassandra](http://cassandra.apache.org/) cluster which will be easily scalable. Let's get to it!

## Cassandra on docker

### 3h4x/cassandra

No magic here, run `docker run -it 3h4x/cassandra` to start playing with
cassandra node.
But what we want to do is get cluster!

### Cluster

Cassandra use gossip protocol to communicate. Each node need to connect
to seed node and from there it will get all nodes of cassandra in
cluster eventually.

So I have configured two cassandra type of nodes, seed and normal node
which I can scale up or scale down.

To get what we need I used service discovery via [mesos-dns](http://mesosphere.github.io/mesos-dns/) so cassandra nodes can see cassandra seed never mind on which mesos slave they will be. To do it I just used simple bash script
```
SEED=`echo $(dig +short $SEED) | tr ' ' ','`
```
This will extract ip's of cassandra seed from mesos-dns.

3h4x
