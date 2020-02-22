---
layout: post
title:  "How to run cheap Kubernetes cluster on AWS? pt1"
categories: [kubernetes, aws]
tags: [aws, cloud, ec2, kubernetes, cost reduction, kops]
comments: True
---
### Kubernetes

After containerization boom started, people realized that scheduling it is not as easy as it should be. That's why I have interest in `mesos`, `docker swarm`, `rancher`, `nomad` and `k8s`. There's a need for a system that will take care of correct scheduling, priorities, eviction, logs, simple cluster scaling, upgrades, deployment methods, permissions and so on... 
My first experience with `prod` grade `k8s` cluster was during time I worked for [Spreaker/Voxnest](https://voxnest.com). When I joined we had `1.4` and throughout the years it was updated to `1.12` (AFAIR). I've learned a lot, our relation (mine and `k8s` :D) had ups and downs but I was mostly satisfied and amazed by it.  

`Kubernetes` is cool technology, really complex but have long list of benefits! 
I don't want to get into details of why I think it's superior technology to run containers today but just to name few generic ones:

- it has massive adoption in big tech companies
- a lot of development is going on, and I mean **a lot**
- big and helpful community  
- enormous ecosystem

Or let `github` stars tell you the truth ;)
1. [`kubernetes`](https://github.com/kubernetes/kubernetes) >57k 
1. [`rancher`](https://github.com/rancher/rancher) >12k
1. [`nomad`](https://github.com/hashicorp/nomad) >5k
1. [`docker swarm`](https://github.com/docker/swarm/) >5k
1. [`mesos`](https://github.com/apache/mesos) >4k   

<!-- readmore -->

## Bill! How low can you go!?

**Important note!**  
**You should be aware that spot instances can be terminated anytime.** For example when it's pricing will go beyond what you expected or when there are insufficient resources for Reserved Instances/On Demand instances in Region/AZ.  
If no downtime is required then spot instances **must not** be used. Period.

### Workable minimum - 2.9$

|resource  |type       |hourly cost|monthly cost|notes  
|---       |---        |---        |---         |---
|EC2       |`t3.micro` | 0.0031$   | 2.31$      |`k8s` master    
|EBS 4GB   |`magnetic` |           | 0.2$       |`etcd-events` and `etcd-main` 
|EBS 8GB   |`magnetic` |           | 0.4$       |volumes attached to `k8s` master and node
|S3        |           |           |            |`kops` files, pricing is negligible
|---       |---        |---        |---         |---
|          |           |           |**2.9$**    |**Sum**

#### EC2

##### Instance type  
From my experiments that I've done, smallest instance capable of running `k8s` is `micro`. `t2` family is more expensive and has lower performance than `t3` so `t3.micro` is obvious choice.

##### Scheduling on kubernetes master  
As we picked cheapest instance type to run `k8s` now it's time to limit nodes. Who needs computation nodes? `k8s master` node is enough ;)  
It's important to understand that scheduling `pods` or `deployments` won't work on `k8s master` out of the box. This is reasonable, you don't want to overwhelm `master` node with your tasks. That's how cluster troubles start and they can be really difficult to investigate.  

To override it and schedule stuff on `k8s master` we have two options:
- remove taint `node-role.kubernetes.io/master:NoSchedule` from `k8s master` node
```bash
kubectl taint node {{node-name}} node-role.kubernetes.io/master:NoSchedule-
```
- adding toleration to `pod`/`deployment`/`daemonset` etc
```yaml
---
apiVersion: extensions/v1beta1
kind: Deployment
metadata:
    name: grafana
spec:
    replicas: 1
    template:
      spec:
        containers:
        - image: grafana/grafana:6.3.4
          name: grafana
        tolerations:
        - effect: NoSchedule
            key: node-role.kubernetes.io/master
```

I have removed almost everything beside `tolerations`. I hope it's readable and understandable.

#### EBS 

##### etcd
My private cluster is using 1GB of `etcd` EBS volumes, where I have ~35 `pods` scheduled. Giving 2GB volume per `etcd`, will give such a small cluster room to growth. _Remember increasing EBS volumes is easy peasy on AWS while trimming volumes is not that quick_ 

##### Root volume
8GB is not much but it's a good starting point.

#### S3

I'm using [`kops`](https://github.com/kubernetes/kops) to spin up/modify/update cluster. It uploads cluster configuration to S3 and use it during bootstrapping, my cluster has 408KB of configuration in ~800 files.  
That's why I think it's easier to round it up to 0 than calculate preceisly how many cents it costs.

### Cluster with computing node and sane EBS defaults

|resource  |type       |hourly cost|monthly cost|notes  
|---       |---        |---        |---         |---
|EC2       |`t3.micro` | 0.0031$   | 2.31$      |`k8s` master    
|EC2       |`m3.medium`| 0.0067$   | 4.82$      |`k8s` node  
|EBS 40GB  |`magnetic` |           | 2$         |`etcd-events` and `etcd-main` 
|EBS 32GB  |`magnetic` |           | 1.6$       |volumes attached to `k8s` master and node
|S3        |           |           |            |`kops` files, pricing is negligible
|---       |---        |---        |---         |---
|          |           |           |**10.13$**  |**Sum**

#### EC2

##### Instance type  
Looking at spot instances I've noticed that best quality/price ratio has `m3.medium`. It's 0.0067$/h with 1vCPU and 3.75GB of RAM, it also has 4GB of instance store! It's spot price has been rock steady in past months.  
Other instance types:
- `t3.medium` - 0.0125$/h
- `t2.medium` - 0.0139$/h
- `c1.medium` - 0.013$/h
- `m3.large` - 0.03$/h
- `t3.large` - 0.025$/h

`m3.medium` rocks!

##### Scheduling on kubernetes master  
Removing taints and adding tolerations is not necessery now. Let's leave master as it is and schedule only on `k8s node`

#### EBS 

##### etcd
Default volumes for `etcd` in `kops` is 20GB each. I'd say it's safe to do it and EBS storage is cheap! Especially `magnetic`!

##### Root volume
16GB is still not much but it will be fine for most small clusters.


### Cluster with world facing services

Because I also want to have world facing services services I add `ALB` and `Route53` resources
 
|resource  |type       |hourly cost|monthly cost|notes  
|---       |---        |---        |---         |---
|EC2       |`t3.micro` | 0.0031$   | 2.31$      |`k8s` master    
|EC2       |`m3.medium`| 0.0067$   | 4.82$      |`k8s` node  
|EBS 40GB  |`magnetic` |           | 2$         |`etcd-events` and `etcd-main` 
|EBS 32GB  |`magnetic` |           | 1.6$       |volumes attached to `k8s` master and node
|S3        |           |           |            |`kops` files, pricing is negligible
|ALB       |`N/A`      |0.0305$    |21.96$      |For low usage ALB. Pricing is also per [LCU](https://aws.amazon.com/elasticloadbalancing/pricing/), keep that in mind  
|Route53   |           |           |1$          |Hosted Zone 
|---       |---        |---        |---         |---
|          |           |           |**33.09**   |**Sum**

#### ALB

I use [AWS ALB Ingress Controller](https://github.com/kubernetes-sigs/aws-alb-ingress-controller). You can use it for your application to expose it through `ALB` via `ingress` resource.    
`Kubernetes` `service` has publishing options like:
- `ClusterIP` - expose service via internal IP
- `NodePort` - expose service on static port
- `LoadBalancer` - provisions new LB for every service
 
So why `ingress` with `ALB` is good? 
- one `ALB` can route to multiple applications thus reducing cost of running multiple CLB or ALB
- `ALB` is giving you healthchecks, loadbalancing and some DDOS protection
- `ACM` certificate - you get certificate right off the bat if you have domain registered in AWS
- exposing services automatically can speed up time to market

Here's example:
```yaml
---
apiVersion: extensions/v1beta1
kind: Ingress
metadata:
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/security-groups: sg-43a43608
    alb.ingress.kubernetes.io/successCodes: 200,404
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/subnets: subnet-5c293c63,subnet-ffe05bb5,subnet-0179f40e
    alb.ingress.kubernetes.io/healthcheck-path: /
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:12345678:certificate/33fdec26-835c-41ce-ba72-4250487aef28
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80,"HTTPS": 443}]'
  name: generic
  namespace: default
spec:
  rules:
    - host: grafana.example.com
      http:
        paths:
          - backend:
              serviceName: grafana
              servicePort: 3001
```


#### Route53

It's needed if you want your cluster to have fully qualified domain name instead of `.local`. It doesn't make sense to have `ALB` and manually pointing DNS records of your services to it.

## Conclusion

`Kubernetes` is great piece of technology. To get a taste of it, it's best to deploy it and play with it, work with it. I think spending 30$ a month for fully functional cluster is a bargain (at least if your spot instances were never terminated like mine!). In comparison you need to pay ~150$/month for EKS cluster and you need to pay for EC2 and EBS resources also. Definitely it's not the cheapest way but it outsource some of the maintenance.   
Please note that I'm not arguing that `k8s` is "the future", in my opinion "the future" will change every couple of years and there will be new hype.  
As of now `k8s` is outclassing containers competition.

In `part 2` I will write how to spin up such cheap cluster.

3h4x
