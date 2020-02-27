---
layout: post
title:  "Free git repository for private projects - GitHub vs GitLab vs BitBucket"
categories: tech
tags: [git, cost reduction]
comments: True
---

Choosing provider for private git repositories back in the day was though. 

`GitHub` is most known and I'd even say iconic. [They started to offer unlimited private repos for paid plans 
in 2016.](https://github.blog/2016-05-11-introducing-unlimited-private-repositories/)  
`GitLab` and `BitBucket`  at that time offered unlimited private repositories. Wow! They got me.  
Currently also `GitHub` provides unlimited private repositories and with recent introduction of `GitHub actions` I think 
it's good time to do the comparison between them and see who provide best services in free plan.

**Note:**  
In this post I'm focusing on free plans but you are free to explore paid option.

<!-- readmore -->

## Feature comparison

{% assign t = ":heavy_check_mark:" %}
{% assign f = ":white_check_mark:" %}
{% assign i = ":information_source:" %}
| | [GitLab](https://about.gitlab.com/pricing/gitlab-com/feature-comparison/) | [GitHub](https://github.com/pricing#feature-comparison) | [BitBucket](https://bitbucket.org/product/pricing)
|-|:-:| :-:| :-:|
Unlimited private repos |{{t}} | {{t}} | {{t}}
Private repo user limit | None | Up to 3 users | Up to 5 users
Builtin CICD | {{t}}[{{i}}](https://docs.gitlab.com/ee/ci/) | {{t}}[{{i}}](https://help.github.com/en/actions) | {{t}}[{{i}}](https://confluence.atlassian.com/bitbucket/build-test-and-deploy-with-pipelines-792496469.html)
CICD free minutes | 2k | 2k | 50
CICD self hosted worker | {{t}} | {{t}} | {{f}}
Issues | {{t}} | {{t}} | {{t}}   
Wiki | {{t}} | {{f}} | {{t}}
Protected branches | {{t}} | {{t}} | {{t}}
Enforced PR checks | {{t}} | {{t}} | {{f}}[{{i}}](https://confluence.atlassian.com/bitbucket/suggest-or-require-checks-before-a-merge-856691474.html)
Required PR review | {{f}}[{{i}}](https://docs.gitlab.com/ee/user/project/merge_requests/merge_request_approvals.html) | {{f}}[{{i}}](https://help.github.com/en/github/administering-a-repository/about-required-reviews-for-pull-requests) | {{t}}
Security alerts | {{f}} | {{t}}[{{i}}](https://help.github.com/en/github/managing-security-vulnerabilities/about-security-alerts-for-vulnerable-dependencies) | {{f}}
Require MFA | {{t}} | {{f}} | {{f}}

_Unlimited private repos_  
How many private repositories can you create.

_Private repo user limit_  
How many users can you add in private repository.

_Builtin CICD_  
Is there a form of CICD builtin.

_CICD free minutes_  
How many free minutes of worker time you get in builtin CICD.

_Issues_  
Can issues be created.

_Wiki_  
Can wiki be created.

_Protected branches_  
Is there protected branches feature avaiable.

_Enforced PR checks_  
Merge checks are in every provider but for `BitBucket` it's only optional in free plan.

_Required PR review_  
Not accepted PRs can't be merged. Only `Bitbucket` allows to enforce this in free plan. 

_Security alerts_  
GitHub sends security alerts when we detect vulnerabilities affecting your repository.

_Require MFA_  
Owner of a group in `GitLab` can enforce usage of MFA for all users in group.


## My perspective

I use all three of them.  

`GitHub` was used by most companies that have hired me but I use it also for public repos.  
`BitBucket` and `GitLab` are hosting my private repos.  

Because `GitLab CI` was introduced first I have all my pipelines
there, and because I have lots of pipelines most of my repos are also there. There's really no point in 
migration just for sake of migration, especially that I use also _require MFA_ feature.
My self hosted CI worker deployed by Helm on Kubernetes a robust and efficient approach to CICD.
 
`GitHub actions` are also great. It's taking industry by storm as number of templates and easiness of use is outstanding.
You can also setup your own worker but keep in mind that every worker is per repo, where in `GitLab` you can have
per repo but also per group. In documentation it states that it is upcoming feature. Additional points for `GitLab`.

To be fair I haven't tried `BitBuckt CI`. It offers only 50 minutes a month for free and combined with no self hosted
worker it's a deal breaker for me.

**For me `GitLab` is current winner.** Competition is not far away though. 

3h4x
