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
mesos I got a task to create [cassandra](http://cassandra.apache.org/) cluster which will be scalable.

3h4x
