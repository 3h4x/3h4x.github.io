---
layout: post
title:  "Cassandra on Marathon"
date:   2015-03-28 10:21:38
categories: cassandra marathon docker mesos
comments: True
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

*TouK* is developing an application [ctrl-pkw](https://github.com/TouK/ctrl-pkw) to collect protocols from poll stations and check if election results were not tampered.

So beside my plan to move most of the virtual machines from KVM to
mesos I got a task to create [cassandra](http://cassandra.apache.org/) cluster which will be easily scalable. Let's get to it!

## Cassandra on docker

### 3h4x/cassandra

No magic here, run `docker run -it 3h4x/cassandra` to start playing with
cassandra node.
It works but we want more!

### Cassandra cluster

Cassandra use [gossip protocol](http://en.wikipedia.org/wiki/Gossip_protocol) to communicate. Each node need to connect to seed node and from there it will get all nodes of cassandra in cluster eventually.

So I have configured two cassandra type of nodes, seed - just few of them
to bootstrap cluster and normal node which I can scale up or scale down.

To get what we need I used service discovery via [mesos-dns](http://mesosphere.github.io/mesos-dns/) so cassandra nodes can see cassandra seed never mind on which mesos slave they will be. To do it I just used simple bash script

```
SEED=`echo $(dig +short $SEED) | tr ' ' ','`
```

This will extract ip's of cassandra seed from mesos-dns.

#### json config

Take a look at posted gist. At first glance I wasn't quite sure how to
deploy it but then I sunk my teeth in and figured it all out.

[gist with json to deploy cassandra cluster on
marathon](https://gist.github.com/3h4x/f97c9387e5874686c2ce)

Most important stuff in this cluster config is constraint on mesos to use unique hosts, otherwise it will try to deploy on hosts where ports are already occupied and it will fail.

Cassandra needs ports open for it's own [gossip](https://www.datastax.com/documentation/cassandra/2.1/cassandra/architecture/architectureGossipAbout_c.html) configuration and they must be avaliable on mesos-slave ip. There is no chance right now to reconfigure cassandra.yaml in a way to use different ports for internode communication.

```
"ports": [
    7199,
    7000,
    7001,
    9160,
    9042
],
```

This is why additional configuration of docker is needed

```
"network": "HOST",
"privileged": true
```

It allows to bind ports on mesos-slave instead of ip that was given by docker.

Last but not least there is SEED environment which will be given to docker container

```
"env": {
    "SEED": "cassandra-seed.db.ctrlpkw.marathon.mesos"
},
```

If your rename the cluster be sure to change this dns address too, moreover every mesos slave needs to have mesos-dns configured.

#### Scale up!

This is the moment that I've been waiting on. We can modify cassandra app configuration on marathon and add additional nodes using scale or instances parameter

```
curl -L -H "Content-Type: application/json" -X PUT -d '{ "instances": 6 }' http://marathon/v2/apps/ctrlpkw/db/cassandra
```

I have tried to use parameter "scaleBy" which is in [marathon API](https://mesosphere.github.io/marathon/docs/rest-api.html). Well, better luck next time.

### Full cluster with application

We are just one step away from deploying our application with cassandra database on mesos using docker containers! Awesome :D

And here is [gist with json to deploy cluster with cassandra and app on
marathon](https://gist.github.com/3h4x/e12d80471602e17adb9a)

Let's do it!

```
curl -L -H "Content-Type: application/json" -X POST -d@ctrlpkw_cluster.json http://marathon/v2/groups
```

And here it is

![cassandra-cluster]({{ site.url }}/assets/cassandra-cluster.png)

> Bye bye, see you real soon!

3h4x
