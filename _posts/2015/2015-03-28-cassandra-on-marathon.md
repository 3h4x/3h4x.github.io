---
layout: post
title:  "Cassandra on Marathon"
categories: tech
tags: [cassandra, marathon, docker, mesos]
comments: True
---
Recently all I talk about is [mesos](https://mesos.apache.org/) and mesos on mesos ;)

> Apache Mesos abstracts CPU, memory, storage, and other compute
> resources away from machines (physical or virtual), enabling
> fault-tolerant and elastic distributed systems to easily be built and
> run effectively.

Sounds fantastic and because I'm true fan of docker I went with
[marathon](https://mesosphere.github.io/marathon/)

> which is a cluster-wide init and control system for
> services in cgroups or Docker containers

<!-- readmore -->
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
mesos I got a task to create [cassandra](https://cassandra.apache.org/) cluster which will be easily scalable. Let's get to it!

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

{% highlight shell %}
SEED=`echo $(dig +short $SEED) | tr ' ' ','`
{% endhighlight %}

This will extract ip's of cassandra seed from mesos-dns.

#### json config

At first glance I wasn't quite sure how to deploy it but then I sunk my teeth in and figured it all out. [Marathon API](https://mesosphere.github.io/marathon/docs/rest-api.html) and [Cassandra documentation](http://docs.datastax.com/en/cassandra/2.1/cassandra/gettingStartedCassandraIntro.html) was very helpful

{% highlight shell %}
{
    "id": "/ctrlpkw/db",
    "apps": [
        {
            "id": "/ctrlpkw/db",
            "apps": [
                {
                    "id": "/ctrlpkw/db/cassandra-seed",
                    "constraints": [
                        [
                            "hostname",
                            "UNIQUE"
                        ]
                    ],
                    "ports": [
                        7199,
                        7000,
                        7001,
                        9160,
                        9042
                    ],
                    "requirePorts": true,
                    "container": {
                        "type": "DOCKER",
                        "docker": {
                            "image": "docker.touk.pl/cassandra",
                            "network": "HOST",
                            "privileged": true
                        }
                    },
                    "env": {
                        "SEED": "cassandra-seed.db.ctrlpkw.marathon.mesos"
                    },
                    "cpus": 4,
                    "mem": 4096,
                    "instances": 2,
                    "backoffSeconds": 1,
                    "backoffFactor": 1.15,
                    "maxLaunchDelaySeconds": 3600,
                    "healthChecks": [
                        {
                            "protocol": "TCP",
                            "gracePeriodSeconds": 30,
                            "intervalSeconds": 30,
                            "portIndex": 4,
                            "timeoutSeconds": 60,
                            "maxConsecutiveFailures": 30
                        }
                    ],
                    "upgradeStrategy": {
                        "minimumHealthCapacity": 0.5,
                        "maximumOverCapacity": 0.2
                    }
                },
                {
                    "id": "/ctrlpkw/db/cassandra",
                    "constraints": [
                        [
                            "hostname",
                            "UNIQUE"
                        ]
                    ],
                    "ports": [
                        7199,
                        7000,
                        7001,
                        9160,
                        9042
                    ],
                    "requirePorts": true,
                    "container": {
                        "type": "DOCKER",
                        "docker": {
                            "image": "docker.touk.pl/cassandra",
                            "network": "HOST",
                            "privileged": true
                        }
                    },
                    "env": {
                        "SEED": "cassandra-seed.db.ctrlpkw.marathon.mesos"
                    },
                    "cpus": 4,
                    "mem": 4096,
                    "instances": 1,
                    "backoffSeconds": 1,
                    "backoffFactor": 1.15,
                    "maxLaunchDelaySeconds": 3600,
                    "healthChecks": [
                        {
                            "protocol": "TCP",
                            "gracePeriodSeconds": 30,
                            "intervalSeconds": 30,
                            "portIndex": 4,
                            "timeoutSeconds": 60,
                            "maxConsecutiveFailures": 30
                        }
                    ],
                    "upgradeStrategy": {
                        "minimumHealthCapacity": 0.5,
                        "maximumOverCapacity": 0.2
                    }
                }
            ]
        }
    ]
}
{% endhighlight %}
Most important stuff in this cluster config is constraint on mesos to use unique hosts, otherwise it will try to deploy on hosts where ports are already occupied and it will fail.

Cassandra needs ports open for it's own [gossip](https://www.datastax.com/documentation/cassandra/2.1/cassandra/architecture/architectureGossipAbout_c.html) configuration and they must be avaliable on mesos-slave ip. There is no chance right now to reconfigure cassandra.yaml in a way to use different ports for internode communication.

{% highlight json %}
"ports": [
    7199,
    7000,
    7001,
    9160,
    9042
],
{% endhighlight %}

This is why additional configuration of docker is needed

{% highlight json %}
"network": "HOST",
"privileged": true
{% endhighlight %}

It allows to bind ports on mesos-slave instead of ip that was given by docker.

Last but not least there is SEED environment which will be given to docker container

{% highlight json %}
"env": {
    "SEED": "cassandra-seed.db.ctrlpkw.marathon.mesos"
},
{% endhighlight %}

If your rename the cluster be sure to change this dns address too, moreover every mesos slave needs to have mesos-dns configured.

#### Scale up!

This is the moment that I've been waiting on. We can modify cassandra app configuration on marathon and add additional nodes using scale or instances parameter

{% highlight shell %}
curl -L -H "Content-Type: application/json" -X PUT -d '{ "instances": 6 }' http://marathon/v2/apps/ctrlpkw/db/cassandra
{% endhighlight %}

I have tried to use parameter "scaleBy" which is in [marathon API](https://mesosphere.github.io/marathon/docs/rest-api.html). Well, better luck next time.

### Full cluster with application

We are just one step away from deploying our application with cassandra database on mesos using docker containers! Awesome :D

And here is json to deploy cluster with cassandra and app on marathon

{% highlight json %}
{
  "id": "/ctrlpkw",
  "groups": [
    {
      "id": "/ctrlpkw/db",
      "apps": [
          {
              "id": "/ctrlpkw/db/cassandra-seed",
              "constraints": [["hostname", "UNIQUE"]],
              "ports": [7199, 7000, 7001, 9160, 9042],
              "requirePorts": true,
              "container": {
                  "type": "DOCKER",
                  "docker": {
                      "image": "docker.touk.pl/cassandra",
                      "network": "HOST",
                      "privileged": true
                  }
              },
              "env": {
                  "SEED": "cassandra-seed.db.ctrlpkw.marathon.mesos"
              },
              "cpus": 4,
              "mem": 4096.0,
              "instances": 2,
              "backoffSeconds": 1,
              "backoffFactor": 1.15,
              "maxLaunchDelaySeconds": 3600,
              "healthChecks": [
                  {
                      "protocol": "TCP",
                      "gracePeriodSeconds": 30,
                      "intervalSeconds": 30,
                      "portIndex": 4,
                      "timeoutSeconds": 60,
                      "maxConsecutiveFailures": 30
                  }
              ],
              "upgradeStrategy": {
                  "minimumHealthCapacity": 0.5,
                  "maximumOverCapacity": 0.2
              }
          },
          {
              "id": "/ctrlpkw/db/cassandra",
              "constraints": [["hostname", "UNIQUE"]],
              "ports": [7199, 7000, 7001, 9160, 9042],
              "requirePorts": true,
              "container": {
                  "type": "DOCKER",
                  "docker": {
                      "image": "docker.touk.pl/cassandra",
                      "network": "HOST",
                      "privileged": true
                  }
              },
              "env": {
                  "SEED": "cassandra-seed.db.ctrlpkw.marathon.mesos"
              },
              "cpus": 4,
              "mem": 4096.0,
              "instances": 1,
              "backoffSeconds": 1,
              "backoffFactor": 1.15,
              "maxLaunchDelaySeconds": 3600,
              "healthChecks": [
                  {
                      "protocol": "TCP",
                      "gracePeriodSeconds": 30,
                      "intervalSeconds": 30,
                      "portIndex": 4,
                      "timeoutSeconds": 60,
                      "maxConsecutiveFailures": 30
                  }
              ],
              "upgradeStrategy": {
                  "minimumHealthCapacity": 0.5,
                  "maximumOverCapacity": 0.2
              }
          }
       ]
    },
    {
      "id": "/ctrlpkw/app",
      "apps": [
          {
              "id": "/ctrlpkw/app/ctrlpkw",
              "container": {
                  "type": "DOCKER",
                  "docker": {
                      "image": "trombka/ctrl-pkw:latest",
                      "network": "BRIDGE",
                      "portMappings": [
                          {
                              "containerPort": 8080,
                              "servicePort": 8000,
                              "protocol": "tcp"
                          }
                        ]
                 }
              },
              "env": {
                  "CASSANDRA_CONTACT_POINT":
                  "cassandra-seed.db.ctrlpkw.marathon.mesos",
              },
              "cpus": 1,
              "mem": 512.0,
              "instances": 1,
              "backoffSeconds": 1,
              "backoffFactor": 1.15,
              "maxLaunchDelaySeconds": 3600,
              "healthChecks": [
                  {
                      "protocol": "HTTP",
                      "portIndex": 0,
                      "timeoutSeconds": 60,
                      "maxConsecutiveFailures": 3
                  }
              ],
              "upgradeStrategy": {
                  "minimumHealthCapacity": 0.5,
                  "maximumOverCapacity": 0.2
              },
              "version": "2015-03-20T15:21Z"
          }
      ]
    }
  ]

}
{% endhighlight %}

Let's do it!

{% highlight shell %}
curl -L -H "Content-Type: application/json" -X POST -d@ctrlpkw_cluster.json http://marathon/v2/groups
{% endhighlight %}

And here it is

![cassandra-cluster]({{ site.url }}/assets/cassandra-cluster.png)

> Bye bye, see you real soon!

3h4x
