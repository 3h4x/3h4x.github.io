---
layout: post
title: "Terraform state management — best practices I follow religiously"
categories: tech
tags: [terraform, aws, infrastructure as code, devtools]
comments: True
---

State is Terraform's Achilles heel and nobody really talks about it until something goes wrong. I've been using S3 backend with DynamoDB locking from day one — I've seen enough horror stories from teams that didn't. Here's what I do and why.

<!-- readmore -->

## What state actually is

Quick refresher for context. Terraform doesn't query your cloud provider to figure out what exists — it maintains a local record of what *it* created. That record is the state file (`terraform.tfstate`). When you run `plan`, Terraform compares your `.tf` files to the state file, then queries the provider only to reconcile differences.

This design is fast and provider-agnostic, but it means the state file is a source of truth. If it gets out of sync with reality — whether because someone made a manual change in the AWS console, or two people applied at the same time, or the file got corrupted — you're in trouble.

The default behavior stores state locally. That works fine for one person on one machine. The moment you have a second person or a second machine, you need remote state.

## The S3 backend

This is the standard solution for AWS shops. Configure it in your root module:

```hcl
terraform {
  backend "s3" {
    bucket         = "my-terraform-state"
    key            = "production/terraform.tfstate"
    region         = "eu-west-1"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}
```

A few things worth calling out here. `encrypt = true` is not optional — your state file contains secrets. Database passwords, API keys, anything Terraform manages that has sensitive outputs ends up in plaintext in the state file. Encrypt it at rest with a KMS key if you're serious about it:

```hcl
kms_key_id = "arn:aws:kms:eu-west-1:123456789:key/your-key-id"
```

Bucket versioning is also not optional. Turn it on. You want to be able to roll back to a previous state version when things go sideways. I've done this. It works. But only if you turned versioning on *before* things went sideways.

```bash
aws s3api put-bucket-versioning \
  --bucket my-terraform-state \
  --versioning-configuration Status=Enabled
```

## State locking with DynamoDB

The `dynamodb_table` line in the backend config is what prevents two `apply` runs from stepping on each other. When Terraform starts a plan or apply, it writes a lock entry to the DynamoDB table. If another process tries to do the same, it sees the lock and refuses to proceed.

The table needs a `LockID` string primary key, that's it:

```hcl
resource "aws_dynamodb_table" "terraform_state_lock" {
  name         = "terraform-state-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
```

Yes, I see the chicken-and-egg problem: you need Terraform to create the locking table, but you need the locking table before you can safely use Terraform. The solution is to create the S3 bucket and DynamoDB table manually (or with a separate, simpler Terraform config that uses local state) before bootstrapping your main config.

**The time I skipped locking.** CI system was running `terraform apply` on every merge to main. Local developer also ran `terraform apply` to hotfix something. Both ran simultaneously. The state file ended up in a partially-applied state, with resources that existed in AWS but weren't recorded in state, and resources recorded in state that had actually been destroyed. Fun afternoon.

## Workspaces vs separate backends

`terraform workspace` lets you maintain multiple state files from the same configuration. Sounds appealing — one codebase, multiple environments:

```bash
terraform workspace new staging
terraform workspace new production
terraform workspace select staging
terraform apply
```

I used this approach for about six months before abandoning it. The problem is that workspaces share the same backend config. Your `staging` and `production` state files both live in the same S3 bucket, in the same key prefix. That's fine until you accidentally `select production` when you meant `select staging`. The workspace name is just a string — there's no blast-radius isolation.

The approach I use now: separate state files, separate backend configurations, sometimes separate AWS accounts for production. Each environment is a separate Terraform root module with its own backend block:

```
infrastructure/
  staging/
    main.tf
    backend.tf    # bucket key: staging/terraform.tfstate
  production/
    main.tf
    backend.tf    # bucket key: production/terraform.tfstate
```

More ceremony to set up, but you can't accidentally apply to production when you meant staging because you're literally in a different directory with a different backend. This matters more than you'd think when you're moving fast at 11pm.

## When state gets corrupted

It happens. A failed apply mid-way through, a network blip while writing the state file back to S3, a manual `terraform state rm` that removed more than intended. You need to know how to recover.

**First, don't panic and run `apply` again.** That's how you make it worse.

**Pull the current state:**

```bash
terraform state pull > current.tfstate
```

Look at it. Actually read it. The state file is JSON — it has a `resources` array with every managed resource, its type, name, and the provider-side attributes Terraform knows about. Find out what's wrong before you try to fix it.

**Re-import a resource that fell out of state:**

```bash
terraform import aws_instance.web i-0a1b2c3d4e5f
```

This tells Terraform "this existing resource belongs to this resource address." After import, a `plan` should show no changes for that resource if everything matches your config.

**Remove a resource from state without destroying it:**

```bash
terraform state rm aws_instance.web
```

Useful when you want to stop managing a resource with Terraform, or when you've manually fixed something and want Terraform to forget it and re-import it cleanly.

**Roll back to a previous state version from S3:**

```bash
# List versions
aws s3api list-object-versions \
  --bucket my-terraform-state \
  --prefix production/terraform.tfstate

# Get a specific version
aws s3api get-object \
  --bucket my-terraform-state \
  --key production/terraform.tfstate \
  --version-id YOUR_VERSION_ID \
  recovered.tfstate

# Push it back
terraform state push recovered.tfstate
```

I've used this. The bucket versioning saved me. The previous good state was 6 minutes old and got me back to a clean `plan` with no diff.

## The `-target` flag is a trap

When state is partially broken and plan shows a mess of unexpected changes, the tempting fix is `terraform apply -target=resource.name` to apply only one specific resource. Resist this.

`-target` skips dependency resolution. You can end up in a state where a resource was applied without its dependencies being correct, and now your state is inconsistent in a different way. It's useful for bootstrapping or for very carefully scoped fixes, but using it to work around a messy plan is usually kicking the can.

Fix the state, fix the config, then run a full `plan` and verify it shows only what you expect before applying.

## Sensitive values in state

I mentioned this above but it deserves its own section. Anything marked `sensitive = true` in your Terraform config is still stored in plaintext in the state file. The `sensitive` flag only controls whether the value is redacted in CLI output — it doesn't encrypt it in state.

```hcl
output "db_password" {
  value     = random_password.db.result
  sensitive = true  # redacted in output, NOT encrypted in state
}
```

This means everyone with access to the state file can read every secret your infrastructure manages. S3 bucket encryption helps. IAM policies restricting who can read the state bucket help more. And ideally, you're not storing secrets in Terraform state at all — you're using `aws_secretsmanager_secret` to create the secret container and storing the actual value out-of-band.

## Practical habits

A few things I do consistently now that I didn't do before:

Always run `plan` before `apply`, and actually read the output. "5 to add, 0 to change, 0 to destroy" vs "2 to add, 1 to change, 3 to destroy" should trigger different levels of scrutiny.

Use `-out` to save the plan and apply from the file:

```bash
terraform plan -out=tfplan
terraform apply tfplan
```

This guarantees what you reviewed is what gets applied, even if someone else modified the config between your `plan` and `apply`.

Run `terraform fmt` and `terraform validate` in CI. Catch syntax errors before they become failed applies.

And `state list` is your friend when you're not sure what Terraform is managing:

```bash
terraform state list
```

Returns every resource address in state. Good sanity check before destructive operations.

State management isn't glamorous. It's the plumbing of Terraform. But getting it right — remote backend, locking, versioning, separate environments — is what separates "it works on my machine" from infrastructure you can confidently run in production.

3h4x
