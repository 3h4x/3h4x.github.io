---
layout: post
title:  "Prometheus on ECS - Proof of Concept"
categories: observability
tags: [ecs, prometheus, monitoring, aws, terraform, cloudwatch]
comments: True
---

Two companies that I worked for recently used [ECS (Elastic Container Service)](https://aws.amazon.com/ecs/) as container orchestration tool.  
If you have ever used it you know that it has somewhat limited observability out of the box.  
You have two options to spin containers on ECS:
- `Fargate` which is serveless container engine 
- `EC2` instances managed by you and your team

With `Fargate` you don't really need to have insights into infrastructure spinning containers, it's serveless.  
More robust and less expensive solution is to host your own fleet of `EC2` instances that join `ECS` cluster. With
that approach you need to manage them and know what's going on there.

In this blog post I will outline possible `prometheus` integration with `ECS` using `terraform`. 
My main goal was to improve observability by introducing node monitoring with `node-exporter` + `cadvisor` and ingesting application metrics exposed by ephemeral containers.

<!-- readmore -->

## Rationale

As much as I love `AWS`, I'm not really a fan of `CloudWatch`. Using it as a monitoring system just for the sake of being Cloud 
Native doesn't make much sense to me as it has issues and limitations. I guess some people think that `CloudWatch` is 
good because it's made by AWS and works right off the bat.  
Observabilty that it gives is not the best and the more you use it, the more problems you encounter. 
Let me just point out a couple of major issues for me: 
1. `CloudWatch Alarms` can't monitor ephemeral things like EBS volumes
Imagine an `ASG` which spins new instance that use EBS. You want to keep your alarms in `terraform`? No can do. 
Easiest approach would be `Lambda` triggered by `CloudWatch Events` that creates new alarms automatically. 
One can add alarm during bootstrapping but what about removing an alarm when instance dies? Lifecycle policy? 
What would be source of truth if somehow alarms get out of sync with what's in AWS?
One though cookie.
1. Derivattive of 1. - `CloudWatch` alarm **must** monitor exactly one and only one metric. Not two, not three, not `*` wildcard, not regex.
1. Dashboards are not easy to create, edit and don't provide way for customization like `grafana` does with variables, 
annotations and other great features.
1. [Metrics Math](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/using-metric-math.html) looks pale in 
comparison with `PromQL` or `NRQL`
1. Data is kept for limited amount of time and you cannot change that.
1. Full observability with `CloudWatch` is expensive! It seems to be free but try to understand the pricing and you'll 
see that cost quickly adds up.
1. Containaers insights were added recently and I haven't yet used them. If you did you can share in comments how does
 it compare to `prometheus` oriented observability.


### Prometheus
I haven't yet written about using `prometheus` as monitoring system and I definitely should. I have used it extensively
 during my work in Voxnes/Spreaker. It's a great tool! **Powerful, robust, scalable and really resilient.**
 
Requirements for collecting metrics with `prometheus` in this PoC were to:  
- no changes to any existing application 
- infrastructure changes introduced by this PoC must be easy to revert 
- service discovery for `ECS` task that supports `awsvpc` network mode  
If you don't know what `awsvpc` is then please refer to [docs](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-networking.html)

First step for me was to enable [`node-exporter`](https://github.com/prometheus/node_exporter) and [`cadvisor`](https://github.com/google/cadvisor) to collect metrics from the host. `node-exporter`
gives a lot of insight into what's happening on the host and `cadvisor` gives insight into containers layer. This duo 
greatly improves observability of infrastructure, especially in conjunction with `grafana` and `alertmanager`.
 
Second step would be adding side car containers exporting metrics for applications that somehow expose it's metrics 
(API, files, etc). Such step don't require any application changes so would be harmless and also easily revertible.
 
Third step would be modifying applications, wheter they're written in Python, JavaScript or any other lanuage, to 
export metrics and ingesting them with `prometheus`. This is the step that requires indepth knowledge of applications 
and monitoring practices. If you have troubles with pinpointing best metrics to observe then start from golden signals 
and read Site Reliability Engineering in meanwhile.
 
I will write a blog post about how I use `prometheus` in my private K8S cluster, where it fits, best practices, 
some caveats and additional tools in ecosystem.  

## Configuration

**Disclaimer:**
Don't expect `prometheus` with `ECS SD` to work in all types of environments. 
https://github.com/prometheus/prometheus/tree/master/discovery
> Some SD mechanisms have rate limits that make them challenging to use. As an example we have unfortunately had to reject Amazon ECS service discovery due to the rate limits being so low that it would not be usable for anything beyond small setups.

### Terraform

Right, so let's get to the point, `terraform` was used to easily setup PoC and tear it down when tests are finished. 
To separate `prometheus` from existing infrastructure it has it's own `ASG` and `ECS` cluster. I configured module in 
a way to provide resiliency and setup `prometheus` in multiple AZs.

As it was PoC it's not highly adjustible, some things like VPC subnets are actually hardcoded but hey, it's not my fault :)
```hcl-terraform
module "prometheus_us_west_2a" {
  source = "git::git@github.com:3h4x/terraform-prometheus-ecs.git//services/prometheus?ref=v0.0.1"

  name = "prometheus-us-west-2a"

  availability_zone                     = "us-west-2a"
  cloudmap_internal_id                  = aws_service_discovery_private_dns_namespace.internal.id
  domain                                = "domain"
  ecs_cluster_id                        = module.ecs_cluster.cluster_id
  ecs_cluster_private_security_group_id = aws_security_group.ecs_cluster.id
  instance_profile_name                 = module.ecs_profile_prometheus_us_west_2.instance_profile_name
  instance_role_name                    = module.ecs_profile_prometheus_us_west_2.instance_role_name
  region                                = "us-west-2"
  security_group_id_jump_host           = aws_security_group.jump.id
  vpc_id                                = module.vpc.vpc_id
  vpc_subnets                           = module.vpc.private_subnets
}
```

There are multiple things that this module abstracts away. Let me iterate over them:
- IAM permissions for EBS volumes so `grafana` and `prometheus` have persistent data
- IAM permissions for S3 bucket in which config is stored
- IAM permissions for ECS and EC2 service discovery
- IAM permissions to register containers in CloudMap (this can be improved as now it's `AmazonRoute53FullAccess`)
- EBS volumes
- ASG + LC with userdata file
- ECS cluster + ECS service
- SG
- Configuration files on S3

### Prometheus ECS task

Let me explain what's deployed as our `prometheus` task.

```json
[
  {
    "image": "prom/prometheus:v2.14.0",
    "name": "prometheus",
    "portMappings": [
      {
        "containerPort": 9090,
        "hostPort": 9090,
        "protocol": "tcp"
      }
    ]
  },
  {
    "command": [
      "--directory",
      "/etc/prometheus/"
    ],
    "image": "3h4x/prometheus-ecs-sd:v0.0.1",
    "name": "prometheus-ecs-discovery"
  },
  {
    "portMappings": [
      {
        "containerPort": 3000,
        "hostPort": 3000,
        "protocol": "tcp"
      }
    ],
    "image": "grafana/grafana:6.4.4"
  },
  {
    "portMappings": [
      {
        "containerPort": 9093,
        "hostPort": 9093,
        "protocol": "tcp"
      }
    ],
    "image": "prom/alertmanager:v0.19.0",
    "name": "alertmanager"
  }
]
```
[Click to see whole json](https://github.com/3h4x/terraform-prometheus-ecs/blob/master/services/prometheus/files/prometheus_task.json)

As you can see we deploy: 
- prometheus
- alertmanager
- grafana
- prometheus-ecs-discovery

If you're familiar with `prometheus` then there is nothing to explain with first three. Last one [`prometheus-ecs-discovery`](https://github.com/3h4x/prometheus-ecs-sd) is
key component for this setup. It's an application (just few hundreds line of `python` code) that gets information about containers running in ECS and provide it in
formats that `prometheus` is able to read. 
Additionally we need to configure `prometheus` so it know about this `sd` configuration with:
```yaml
  - job_name: 'ecs'
    scrape_interval: 20s
    file_sd_configs:
      - files:
          # scrape tasks that are discovered every minute (default)
          - /etc/prometheus/1m-tasks.json
    relabel_configs:
      - source_labels: [metrics_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
```
If you want to know how the `json` looks like you can either try this setup or refer to docs.

**Note:**
There are a couple of `ecs-discovery` apps but they didn't support `awsvpc` network mode which was one of main 
requirements.

### Ingesting metrics from node-exporter and cadvisor

For every `ECS` cluster that we want to monitor we have to deploy `node-exporter` and `cadvisor`.
Because `scheduling_strategy` is set to `DAEMON` every node in a cluster will be monitored.
 
```hcl-terraform
module "node_exporter" {
  source = "git::git@github.com:3h4x/terraform-prometheus-ecs.git//services/prometheus_node_exporter?ref=v0.0.1"

  ecs_cluster_name   = module.ecs_cluster.cluster_name
  ecs_security_group = module.ecs_cluster.security_group_id
}
```

```hcl-terraform
module "cadvisor_exporter" {
  source = "git::git@github.com:3h4x/terraform-prometheus-ecs.git//services/prometheus_cadvisor_exporter?ref=v0.0.1"

  ecs_cluster_name   = module.ecs_cluster.cluster_name
  ecs_security_group = module.ecs_cluster.security_group_id
}
```

### Enable scraping container metrics
Additionally we need to configure `node-exporter`, `cadvisor` and any other application task variables so `ecs-discovery` 
will know that we want to scrape it with `prometheus`.
```json
    "environment": [
      {
        "name": "PROMETHEUS",
        "value": "true"
      },
      {
        "name": "PROMETHEUS_PORT",
        "value": "${port}"
      }
    ]
```
`PROMETHEUS_PORT` must be the same as port on which containers expose `prometheus` metrics.

## Recap

Goal was to have `prometheus` on `ECS` and start collecting infrastructure and app metrics and I'm happy that my effort
resulted in fully working PoC!

During this work I had a feeling that I'm reinventing the wheel. Deploying `prometheus` and it's exporters on 
`kubernetes` is so much easier. I guess sometimes we have to deal with what we have even though better technology exist.

There are some things that could/should be improved like:
- config shouldn't be in S3 but because it's in `terraform` I felt it was better to have it in one place. 
- some IAM permissions could be more strict
- the bigger infrastructure on `ECS` is the more problems this setup would have **but** it's PoC (_wontfix_)

[Modules used in this blog posts are in repo publicly available](https://github.com/3h4x/terraform-prometheus-ecs/tree/f7da2fd53f91e9e8206b535359f6c24ff5acbca2)  
Feel free to use it but keep in mind that I won't be developing it any more. 

3h4x