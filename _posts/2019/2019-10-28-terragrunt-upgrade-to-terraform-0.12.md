---
layout: post
title:  "Terragrunt upgrade to terraform 0.12"
categories: tech
tags: [terraform, terragrunt, infrastructure as code]
comments: True
---

For past six months I've been working with [`terragrunt`](https://www.gruntwork.io) which is a thin wrapper for `terraform` that provides extra tools for working with multiple `terraform` modules.  
Idea behind is awesome - make repository of modules which follows best practices and show how to write IaC properly.
In this post I will outline upgrading and write some commands that helped me to automate this process.

<!-- readmore -->

## Terraform 0.12

It's all fun and games until new, backward incompatible `terraform` version is out.   
If you haven't already read [upgrading to Terraform v0.12](https://www.terraform.io/upgrade-guides/0-12.html) I definitely encourage you to read it. There are **a lot** of changes which you should be aware of.  
Next in line would be document from `terragrunt` [Upgrading your Reference Architecture Deployment to Terraform 0.12.x and Terragrunt 0.19.x](https://docs.gruntwork.io/guides/upgrading-to-tf12-tg19/).  
It does say what should be done but it does not specify how. This you must come up with yourself. As I already did it I can share some of my thoughts about that.  

## Plan

### Prerequisite

- Upgrade `terragrunt` to most recent `terragrunt18`
- Upgrade `terraform` to latest `tf11` version
- Upgrade all `terragrunt` modules to latest `tf11` compatible. 
You can look `tf11`/`tf12` compatibility in [terragrunt terraform version compatibility chart](https://docs.gruntwork.io/reference/version-compatibility/).  


### Infrastructure live

I'm the type of guy that don't want to do the same job twice. With `terragrunt` upgrade it would be just silly to make same changes over and over again for every module.  
That's why I have focused on automatization of this task as amount of manual work can be overwhelming.  

First I've create helper commands migrating envs in infra-live to `terragrunt19`:  
- renaming `terraform.tfvars` to `terragrunt.hcl`:  
{% highlight shell %}
find . -name 'terraform.tfvars' | 
xargs rename 's/terraform.tfvars/terragrunt.hcl/' -v
{% endhighlight %}
- adjusting file format:  
{% highlight shell %}
find . -name 'terragrunt.hcl' -exec sed -i.bak \
-e '/terragrunt =/d' -e 's/^}$/inputs = {/' -e '$s#$#}#' 
-e 's/include =/include/' -e 's/dependencies =/dependencies/' {} \;
{% endhighlight %}
- validating hcl:   
{% highlight shell %}
terragrunt hclfmt
{% endhighlight %}
- repeat validating hcl until all is good
- rename `env.tfvars`:  
{% highlight shell %}
find . -name 'env.tfvars' | xargs rename 's/env.tfvars/env.yaml/' -v
{% endhighlight %}
- yaml it:  
{% highlight shell %}
find . -name 'env.yaml' -exec sed -i.bak -e 's/ =/:/' {} \;
{% endhighlight %}
- rename `region.tfvars`:  
{% highlight shell %}
find . -name 'region.tfvars' | xargs rename 's/region.tfvars/region.yaml/' -v
{% endhighlight %}
- yaml it:  
{% highlight shell %}
find . -name 'region.yaml' -exec sed -i.bak -e 's/ =/:/' {} \;
{% endhighlight %}
- clean temp files:  
{% highlight shell %}
git clean -e '*.hcl' -e '*.yaml' -f
{% endhighlight %}
    
### Infrastructure modules

- find modules to upgrade and do the upgrade: 
{% highlight shell %}
for dir in $(find . -type d | grep -v -e '.git\|.terraform\|^.$'); do 
    echo $dir; cd $dir; 
    if [ -f main.tf ]; then 
        sed -i.bak -e 's/0.11.7/0.12.10/g' main.tf; 
        terraform init --backend=false; terraform 0.12upgrade  --yes; 
    fi; 
    cd $REPO_BASE; 
done
{% endhighlight %}
- clean temp files: 
{% highlight shell %}
git clean -fd
{% endhighlight %}
    
Finding and updating modules is toil. In case of any errors you should investigate yourself.  

### Upgrading modules

Here we have two options:  
1. You have clean repository that is a mirror of `terragrunt`.  
If that is the case you can just copy `main.tf`, `outputs.tf` and `vars.tf` (and any other additional files if module has them)
2. You've either have own logic in modules, modified variables or made any other changes which are not in `terragrunt`.  
Bummer. You need to upgrade it on your own and make sure it works in the same way as it was before.  

When it's done you can revisit [terragrunt terraform version compatibility chart](https://docs.gruntwork.io/reference/version-compatibility/) 
and upgrade `terragrunt` modules used in module to first release after `tf12` upgrade.
  
### terragrunt plan

Now you can run `terragrunt plan` and check if there are any changes or errors. 
If plan is clean try to upgrade `terragrunt` modules to more recent or most recent version maybe it will stay clean.  

 
**Note:** Be vary of applying because `tf12` has incompatible state with `tf11`.

## Disclaimer

Know what you are doing and have fun!

3h4x
