---
layout: post
title:  "Infrastructure continuous deployment with terraform and atlantis"
categories: tech
tags: [cicd, terraform, aws, k8s, ecs]
comments: True
---

`Atlantis` is a self-hosted golang application that listens for `Terraform` pull request events via webhooks. I've 
incorporated it in my recent engagement in [CriticalStart](https://www.criticalstart.com/) but also I use it in my private infrastructure. 

I think the idea is great for making `terraform` workflow more easy for infrastructure teams.
With `atlantis` every `terraform` change need to go through review process. When PR is created it automatically run `plan`
displaying its output as a comment. Applying is also done by adding a comment. It's highly configurable. 

Using `atlantis` allows to closing whole `terraform` workflow on PR page!
I always had the feeling that checking out branch and running `terraform` locally is a waste of time. 
Now you can just look at `plan` in PR, do the review and continue with other work.   
Sounds good? Let's dig it!

<!-- readmore -->

## How atlantis works?

In a nutshell when repository webhook is triggered by according action (like create PR or comment), `atlantis` receives 
it and starts workflow. When workflow is finished then `atlantis` comment on PR with result.

**Note:** This implies that your repo provider need to have access to `atlantis` endpoint and vice versa. 

You **can** use `atlantis` with git providers like:
- GitHub 
- GitLab
- Bitbucket
- Stash
- Azure DevOps

**Note:** `atlantis` **must** work with remote `terraform` state.  

With [custom workflows](https://www.runatlantis.io/docs/custom-workflows.html) it's possible to define exactly how 
`terraform` will be executed - flags, additional commands or even running `terragrunt`.

I will write here just about two topics which I think are crucial to understand `atlantis` - apply requirements and 
checkout strategy.

### [Apply Requirements](https://www.runatlantis.io/docs/apply-requirements.html)

Atlantis allows you to require certain conditions be satisfied before an atlantis apply command can be run:  
- Approved – requires pull requests to be approved by at least one user
- Mergeable – requires pull requests to be able to be merged

If you decide to use apply requirements then be sure to understand what they mean for your git provider.
`atlantis` communicate with git providers via API calls and every git provider has it's own unique API.

Apply requirements are used to limit possibility of a failure due to human error. Doing apply where there are git 
conflicts is silly and if your team consist of more than one person then it would be best practice to also require 
PR being approved before applying.

Difference between approved condition for different providers as an example:
  - GitHub – Any user with read permissions to the repo can approve a pull request
  - GitLab – You can set who is allowed to approve
  - Bitbucket – A user can approve their own pull request but Atlantis does not count that as an approval and requires an approval from at least one user that is not the author of the pull request
  - Azure DevOps – All builtin groups include the "Contribute to pull requests" permission and can approve a pull request

Also each VCS provider has a different concept of "mergeability", be sure to check it out in docs as well.

### [Checkout strategy](https://www.runatlantis.io/docs/checkout-strategy.html)

There are two strategies available:
- branch [_default_]
- merge

Both of them have some valid usage. 
`Branch` strategy will checkout code on latest branch commit and run `terraform`. It
assumes that there was no `terraform` changes on `master` in the meantime. If there were changes you will get 
unexpexted diff in your plan. To mitigate it you should assure that your branch is on top of them master by either 
`rebase` or master `merge` to your branch.  
`Merge` strategy will create merge commit with master and run plan there.  

I use `branch` strategy because my repo force to be on top of the master. It saves time on failed plans.

## Deployment 

### [Webhook](https://www.runatlantis.io/docs/configuring-webhooks.html)

For `atlantis` to be functional a webhook is needed. Webhook and the git provider API are main communication channels.

In my case I did `github` webhook with 
[CloudPosse module](https://github.com/cloudposse/terraform-github-repository-webhooks) but for `gitlab` I had to create 
it manually. With `atlantis` documentation it was piece of cake:
> If you're using GitLab, navigate to your project's home page in GitLab

> - Click Settings > Integrations in the sidebar  
> - set URL to http://$URL/events (or https://$URL/events if you're using SSL) where $URL is where Atlantis is hosted. Be sure to add /events  
> - double-check you added /events to the end of your URL.  
> - set Secret Token to the Webhook Secret you generated previously  
> -- NOTE If you're adding a webhook to multiple repositories, each repository will need to use the same secret.  
> - check the boxes  
> -- Push events  
> -- Comments  
> -- Merge Request events  
> -- leave Enable SSL verification checked  
> - click Add webhook

### Deployment on ECS

Setup in CriticalStart was based on [atlantis provider](https://github.com/terraform-aws-modules/terraform-aws-atlantis)
which consist of such resources:
- Virtual Private Cloud (VPC)
- SSL certificate using Amazon Certificate Manager (ACM)
- Application Load Balancer (ALB)
- Domain name using AWS Route53 which points to ALB
- AWS Elastic Cloud Service (ECS) and AWS Fargate running Atlantis Docker image
- AWS Parameter Store to keep secrets and access them in ECS task natively

Main resource here would be ECS Fargate task running `atlantis` which is exposed by ALB.

There is a bit overhead to create additional VPC and ALB and so on but it gives 
better isolation, which at the end of the day gives us more secure environment.

Enabling it with `terraform`:
{% highlight terraform %}
data "github_ip_ranges" "current" {}

module "atlantis" {
  source  = "terraform-aws-modules/atlantis/aws"
  version = "~> 2.4"

  name                    = "Atlantis"
  alb_ingress_cidr_blocks = concat(var.developer_ips, data.github_ip_ranges.current.hooks)
  cidr                    = var.cidr
  azs                     = ["us-west-2a", "us-west-2b", "us-west-2c"]
  private_subnets         = var.private_subnets
  public_subnets          = var.public_subnets

  create_route53_record = true
  route53_zone_name     = var.zone_name
  certificate_arn       = data.aws_acm_certificate.atlantis.arn

  # Atlantis
  atlantis_github_user         = var.atlantis_github_user
  atlantis_github_user_token   = var.atlantis_github_user_token
  atlantis_repo_whitelist      = [var.atlantis_repo_whitelist]
  custom_environment_variables = [
    // Neded so terraform can download private terraform modules
    {
      name  = "ATLANTIS_WRITE_GIT_CREDS"
      value = "true"
    }
  ]
}
{% endhighlight %}

Additionally we used [CloudPosse module](https://github.com/cloudposse/terraform-github-repository-webhooks) to create github webhook for `atlantis`
{% highlight terraform %}
module "github_webhooks" {
  source              = "git::https://github.com/cloudposse/terraform-github-repository-webhooks.git?ref=0.5.0"
  github_organization = var.organization
  github_token        = var.github_token_admin
  github_repositories = [
    var.repository
  ]
  webhook_url          = module.atlantis.atlantis_url_events
  webhook_content_type = "application/json"
  events               = ["pull_request_review", "push", "issue_comment", "pull_request"]
  webhook_secret       = module.atlantis.webhook_secret
}
{% endhighlight %}

### Deployment on Kubernetes

In my private `k8s` cluster I use `helm` to deploy `atlantis`. It has it's own namespace where only `atlantis` is deployed.

Here is `helm` configuration:
{% highlight yaml %}
orgWhitelist: 'org'
defaultTFVersion: 0.12.20
gitlab:
   user: 3h4x
vcsSecretName: 'atlantis-gitlab-access'
awsSecretName: 'atlantis'
image:
  repository: runatlantis/atlantis
  tag: v0.8.2
  pullPolicy: IfNotPresent
repoConfig: |
 ---
 repos:
 - id: /.*/
   apply_requirements: []
   workflow: default
   allowed_overrides: []
   allow_custom_workflows: false
 workflows:
   default:
     plan:
       steps: [init, plan]
     apply:
       steps: [apply]
allowForkPRs: false
disableApplyAll: false
{% endhighlight %}

To prevent commiting credentials to repository where helm configuration is we need to create two secrets:
- `vcsSecretName` contains `gitlab_secret` and `gitlab_token`
- `awsSecretName` contains AWS CLI credentials file.   

To keep such secrets in repository I use [sealed secrets](https://github.com/bitnami-labs/sealed-secrets), which 
basically create encrypted Secret in SealedSecret resource. Such resources can only be encrypted with access to k8s so 
it's safe to have them even in public repository although I would advice against that. 

Deploying process:  
{% highlight console %}
# Create secrets
kubectl apply -f kubernetes/secrets/atlantis.yaml
# Update helm
helm repo add stable https://kubernetes-charts.storage.googleapis.com
helm repo update
# Upgrade deployment
helm upgrade -n atlantis -f kubernetes/atlantis.yaml atlantis stable/atlantis
{% endhighlight %}


## [Security](https://www.runatlantis.io/docs/security.html)

Securing `atlantis` is complicated topic as there are multiple ways to exploit it.  
- Communication `atlantis` <-> `git provider` should use secure channel - precisely `atlantis` shouldn't be exposed as 
HTTP, webhooks should hit HTTPS endpoints.
- Webhooks should have webhook secret so it's possible to validate it and reject if it's not legitimate.
- Restrict access to `atlantis` application - people should not have permission to exec a shell and run commands.
- Provide `atlantis` credentials (API keys, ssh credentials, etc) to appliacation in secure way.
- Restrict access to repository which triggers `atlantis` just to people that should do infrastructure changes, anyone
with access to repository can possibly exploit `atlantis`. 
- Use `--repo-whitelist` flag to define which repositories can trigger `atlantis`.
- Watch out for PRs created by `forks`. It's possible to trigger `atlantis` with them.
- Run `atlantis` in isolated environment - separate k8s namespace, different ECS cluster, dedicated EC2 instance, etc
- Allow communication to `atlantis` only from specific `git provider` IPs.

## Conclusions

I love it!  
Working with `terraform` has never been easier for me.  
It needs a lot of love in the beginning to get everything right but after that it's smooth ride.  

Main issue for me is security. A lot of privileges for `atlantis` means blast radius is gigantic. 
Anyone that can access `atlantis` app, send `webhooks`, comment in PR, etc can break whole infrastructure to which
`atlantis` have access.  
The risk is not just internal, `atlantis` is exposed so additionally it's another large surface attack vector.  

At the end of the day if you can "afford" `atlantis` it's definitely worth the effort!
![atlantis]({{ site.url }}/assets/2020-terraform-atlantis.png)
