---
layout: post
title: "GitHub Actions replacing Jenkins — what actually got better"
categories: tech
tags: [github-actions, cicd, devtools]
comments: True
---

I finally killed my Jenkins server last month. It had been running on a tiny VPS for three years, eating 512MB of RAM just to exist, and breaking every time I forgot to update a plugin. GitHub Actions has been around long enough now that I gave it a real shot — not just for toy projects, but for the stuff Jenkins was actually doing.

<!-- readmore -->

## What Jenkins was doing

Nothing fancy. Build a Node.js app, run tests, deploy via `rsync` + `PM2` restart over SSH. Maybe 5 pipelines total. But Jenkins made this feel like operating a space shuttle:

- `Jenkinsfile` syntax that looks like Groovy but isn't quite Groovy
- Plugin hell — every update risks breaking something unrelated
- The UI is from 2008 and it shows
- Credentials management that's somehow both complex and insecure

It worked. But the maintenance cost was disproportionate to what it was doing. I spent more time keeping Jenkins alive than I spent on the actual projects it was deploying.

There's also the "it worked on Jenkins" phenomenon — your pipeline is subtly coupled to the state of that specific Jenkins instance. The installed plugins, the JVM version, the environment variables some past-you set three years ago. You can't easily reproduce it anywhere else.

## The migration

Here's what a typical deploy pipeline looks like in GitHub Actions:

```yaml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: 18
          cache: 'npm'

      - run: npm ci
      - run: npm test
      - run: npm run build

      - name: Deploy
        run: rsync -avz --delete dist/ $DEPLOY_USER@$DEPLOY_HOST:~/app/
        env:
          DEPLOY_USER: {% raw %}${{ secrets.DEPLOY_USER }}{% endraw %}
          DEPLOY_HOST: {% raw %}${{ secrets.DEPLOY_HOST }}{% endraw %}
```

That's it. The entire pipeline in one file, version-controlled alongside the code, no external server to maintain.

Compare this to the equivalent `Jenkinsfile`. You're looking at a `pipeline {}` block, a `stages {}` block, nested `stage {}` and `steps {}` blocks, and probably a dozen plugin-specific DSL calls you had to look up. It's not unreadable — but it's not *this* readable either.

One thing I appreciated immediately: the workflow file lives in `.github/workflows/`. Anyone cloning the repo can see exactly how the CI works. With Jenkins, that knowledge lived partly in the `Jenkinsfile` and partly in the Jenkins UI where someone configured credentials and build triggers years ago.

## SSH deploy without an action

One pattern I use everywhere now — deploying over SSH without pulling in a third-party action:

```yaml
- name: Setup SSH
  run: |
    mkdir -p ~/.ssh
    echo "${{ secrets.SSH_PRIVATE_KEY }}" > ~/.ssh/id_ed25519
    chmod 600 ~/.ssh/id_ed25519
    ssh-keyscan -H ${{ secrets.DEPLOY_HOST }} >> ~/.ssh/known_hosts

- name: Deploy
  run: |
    rsync -avz --delete dist/ deploy@${{ secrets.DEPLOY_HOST }}:~/app/
    ssh deploy@${{ secrets.DEPLOY_HOST }} "pm2 restart app"
```

No third-party action needed, no black box, easy to audit. I trust my own `ssh-keyscan` more than I trust some random `appleboy/ssh-action@v0.1.x` I found on the marketplace.

## What actually got better

**No server to maintain.** This is the big one. Jenkins needs a JVM, needs disk space for builds, needs security updates, needs backup. GitHub Actions runs on ephemeral containers that someone else manages. When Ubuntu 22.04 runners got a security patch, I didn't have to do anything.

**Secrets management.** Repository secrets are scoped, encrypted, and you never see the value again after setting it. Jenkins credentials were a constant source of anxiety — I genuinely wasn't sure which pipelines were using which credentials, or if some old one-off token was still floating around.

**Caching.** `actions/cache` and built-in caching in `setup-node` cut my build times significantly. Jenkins had caching too, but configuring it felt like a second job. With Actions, the `cache: 'npm'` flag in `setup-node` just works.

**Matrix builds.** Testing across Node 16/18/20 is three lines of YAML:

```yaml
strategy:
  matrix:
    node-version: [16, 18, 20]
```

In Jenkins, this was either three separate pipelines or a `matrix` configuration that took an hour to get right and looked nothing like the Node versions matrix you actually wanted.

**Dependency between jobs.** The `needs:` keyword is clean and obvious:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps: [...]

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps: [...]
```

Jenkins parallel stages with join conditions were… not this.

**Environments and protection rules.** GitHub lets you define environments (staging, production) with required reviewers and deployment protection rules. So your pipeline can automatically deploy to staging, then gate on a human approval before hitting production. This was theoretically possible in Jenkins but required plugins and setup I never got around to doing properly.

## What didn't get better

**Debugging.** When a GitHub Actions workflow fails, you're reading logs in a web UI with no ability to SSH into the runner and poke around. Jenkins let you do that (messily, but it was possible). With Actions, you're stuck adding `run: ls -la` lines and re-running until you figure out what's wrong.

There's `tmate` as a workaround — a step that opens an SSH tunnel to the runner when a job fails. It works, but it's a hack and it holds the runner for up to an hour. I've used it exactly twice, both times while desperately debugging something at 1am.

**Complex pipelines.** If you need fan-out/fan-in across many dynamic jobs, conditional stages based on previous outputs, or dynamic pipeline generation from a matrix that isn't known at write time — Jenkins is more expressive. GitHub Actions can do it, but you start hitting YAML complexity that makes you miss declarative DSLs.

**Cost at scale.** Free tier is generous for open source. For private repos with heavy CI, the minutes add up fast. Jenkins on a $5 VPS was effectively free once it was running. If you're running 50 builds a day with 10-minute jobs, do the math before committing to Actions.

**Reusable steps.** Jenkins shared libraries let you define reusable Groovy functions and call them across pipelines. GitHub Actions has reusable workflows and composite actions, which cover most cases — but they're more ceremony than Jenkins shared libraries. You end up copy-pasting more than you'd like.

## The self-hosted runner escape hatch

Worth knowing: you can run GitHub Actions on your own infrastructure with `self-hosted` runners. This solves the cost and debugging problems simultaneously — you get the nice workflow syntax, but jobs run on a machine you control where you can SSH in and inspect things.

```yaml
jobs:
  deploy:
    runs-on: self-hosted
```

The runner agent is a small binary that registers with GitHub and polls for jobs. I set one up on the same VPS that hosts my apps — takes about 10 minutes. The runner runs jobs as a local user, has access to the filesystem between runs (useful for build caches), and you can SSH into the machine while a job is running to debug it.

The downside: you're back to maintaining a server. But it's one lightweight binary rather than a full Jenkins installation. For me, the VPS is already there doing other things, so the marginal cost is basically zero.

## Marketplace anxiety

One thing I want to flag: the GitHub Actions marketplace is full of community actions, and you should be careful about which ones you use. `actions/checkout`, `actions/setup-node`, `actions/cache` — these are maintained by GitHub, pin them to a major version and trust them.

Community actions are different. The supply chain risk is real. Someone's `some-random-deploy-action@v2` has full access to your runner environment, including your secrets (which Actions automatically redact from logs but not from process memory). I stick to official actions and plain `run:` steps for anything security-sensitive.

Always pin by commit SHA for third-party actions if you use them:

```yaml
- uses: some-org/some-action@a1b2c3d4  # specific commit, not a tag
```

Tags are mutable. Commit SHAs aren't.

## The verdict

For my use case — small projects, simple build/test/deploy — GitHub Actions is a clear win. The operational overhead of Jenkins wasn't worth it. I'm not running a platform team, I'm shipping side projects.

The workflow files being version-controlled alongside the code is bigger than it sounds. I can `git blame` a workflow change, I can see in PRs when someone's proposing a CI change, I can roll back a broken pipeline with `git revert`. None of that was natural with Jenkins.

If you're still running Jenkins for simple pipelines because "it works," it probably does. But the question isn't whether it works — it's whether the maintenance cost is justified. For me, it wasn't.

One more thing: ephemeral runners are underrated. Every build gets a clean environment. No mysterious failures because someone installed something globally on the Jenkins agent last Tuesday. That alone would have sold me.

3h4x
