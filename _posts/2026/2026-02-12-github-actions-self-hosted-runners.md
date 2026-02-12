---
layout: post
title: "Self-hosted GitHub Actions runners — setup, gotchas, and when it's worth it"
categories: tech
tags: [github-actions, cicd, devtools, deployment]
comments: True
---

GitHub-hosted runners are convenient until you look at the bill, or until you need something they don't offer — a specific OS version, access to internal services, a macOS runner for iOS builds. Self-hosted runners solve all of that at the cost of running your own infrastructure. I've got both Linux (on a VPS) and macOS runners running now, and the setup is simpler than I expected. The gotchas, less so.

<!-- readmore -->

## How it works

GitHub Actions' runner binary registers with GitHub, polls for jobs, executes them, and sends results back. It's a pull model — your runner contacts GitHub, not the other way around. This means no firewall rules for inbound connections, which is nice.

The runner binary is open-source (`actions/runner`). You download it, configure it, run it as a service, and GitHub sees a new runner in your repo or org settings.

## Setting up a Linux runner on a VPS

GitHub's official docs cover this, but here's the condensed version. First, download and configure:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner

# Get the latest runner version from GitHub
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-linux-x64-2.321.0.tar.gz
tar xzf actions-runner-linux-x64.tar.gz

# Configure with your repo token
./config.sh \
  --url https://github.com/your-org/your-repo \
  --token <RUNNER_TOKEN> \
  --name vps-runner-1 \
  --labels linux,vps,x64 \
  --work /tmp/runner-work \
  --unattended
```

Get the `RUNNER_TOKEN` from your repo settings: Settings → Actions → Runners → New self-hosted runner. The token expires after an hour, so configure immediately after generating it.

Then install as a system service:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

The service runs as the current user by default. If you want it to run as a dedicated `gh-runner` user (recommended), create the user first and run the install from that account.

## Running multiple runners on one box

One runner handles one job at a time. If your workflows trigger multiple parallel jobs, a single runner creates a bottleneck. The fix is simple — install multiple runners on the same machine, each in its own directory:

```bash
for i in 1 2 3 4; do
  mkdir -p ~/actions-runner-$i && cd ~/actions-runner-$i
  # Extract runner binary
  tar xzf ~/actions-runner-linux-x64.tar.gz
  # Configure each with a unique name
  ./config.sh \
    --url https://github.com/your-org/your-repo \
    --token <TOKEN> \
    --name vps-runner-$i \
    --labels linux,vps,x64 \
    --work /tmp/runner-work-$i \
    --unattended
  sudo ./svc.sh install
  sudo ./svc.sh start
  cd ~
done
```

Be realistic about CPU/RAM. Each runner that's actively building uses real resources. On a 4-core VPS, 4 parallel runners doing light work (linting, unit tests) is fine. 4 runners doing Docker builds simultaneously will saturate your box. Size accordingly.

## Labels — how to target your runners

Labels are how workflows route to specific runners. In your workflow:

```yaml
jobs:
  build:
    runs-on: [self-hosted, linux, vps]
```

This matches any runner with all three labels. You can be as specific or broad as you want. I use:

- `linux` — any Linux runner
- `vps` — specifically the VPS runners (vs macOS)
- `x64` — architecture (important when you have mixed ARM/x86)
- `docker` — runners with Docker installed and ready

In workflow files, `runs-on: self-hosted` matches any self-hosted runner. `runs-on: [self-hosted, linux]` is more specific. Use specific labels — if you later add runners with different capabilities, broad labels will route jobs to wrong runners.

## macOS runners — for iOS builds or macOS-specific tasks

GitHub-hosted macOS runners exist but they're expensive — 10x the per-minute rate of Linux runners. For a small team doing frequent iOS builds, the costs add up fast. A Mac Mini or Mac Studio in the office (or an M-series Mac you already have) makes a much better CI machine.

Setup is identical to Linux:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-osx-arm64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-osx-arm64-2.321.0.tar.gz
tar xzf actions-runner-osx-arm64.tar.gz

./config.sh \
  --url https://github.com/your-org/your-repo \
  --token <TOKEN> \
  --name mac-runner-1 \
  --labels macos,arm64,apple-silicon \
  --unattended
```

For service mode on macOS, the runner installs a launchd plist:

```bash
./svc.sh install
./svc.sh start
```

It runs as a launch daemon under your user. One thing to watch: macOS runners need the Xcode command-line tools and potentially a full Xcode install if you're doing iOS builds. Xcode installs can be 10-15GB and need accepting Apple's license agreement — do this manually before running jobs.

```bash
xcode-select --install
sudo xcodebuild -license accept
```

Also: macOS runners don't run headless well if they need to launch a Simulator. You may need the machine logged in with an active desktop session, not just SSH. For CI, configure "automatic login" on the Mac and let it stay unlocked. Not ideal from a security standpoint, so treat this machine accordingly — dedicated CI hardware, not your personal machine.

## Security considerations

This is the big one. The GitHub docs say it clearly: **don't run self-hosted runners on public repositories**. If you do, anyone can open a PR and run arbitrary code on your machine. Even with some protection, a malicious PR can exfiltrate credentials, install malware, or use your runner for cryptomining.

For private repos, the risk is lower — only people with repo access can trigger workflows. But still:

- Run runners under a dedicated, unprivileged user account
- Don't give the runner user `sudo` access (or scope it tightly)
- Keep secrets out of environment variables when possible — use GitHub's encrypted secrets instead
- Set up job isolation: the `--work` directory gets cleaned between jobs, but any installed tools persist across runs. Consider Docker-based runners for stronger isolation
- Regularly update the runner binary — security fixes ship regularly

```bash
# Check runner version
./run.sh --version

# Update: stop service, download new binary, reconfigure, restart
sudo ./svc.sh stop
# ... download and extract new version ...
./config.sh --url ... --token ... --replace
sudo ./svc.sh start
```

## Cost comparison

GitHub-hosted runners (public/free tier):
- Linux: free for public repos, 2,000 min/month for private repos
- macOS: 10x the Linux minute rate — 2,000 minutes becomes effectively 200 macOS minutes
- Beyond that: $0.008/min Linux, $0.08/min macOS, $0.16/min Windows

Self-hosted runners cost what your infrastructure costs. If you're on a €34/month Hetzner box that's already running other services, adding 4 runners costs roughly nothing extra in hardware. The break-even against GitHub-hosted for just Linux minutes is a few hundred pipeline minutes per month. macOS is even faster ROI given the 10x per-minute cost.

The real cost of self-hosted is your time: setup (a few hours), maintenance (patching, monitoring), and debugging runner-specific issues (environment differences from GitHub-hosted). Budget for that honestly.

## Monitoring runner health

The runner binary doesn't expose Prometheus metrics natively. But you can get useful signals from GitHub's API:

```bash
# List runners and their status for an org
gh api /orgs/your-org/actions/runners | jq '.runners[] | {name, status, busy}'
```

For VPS-based runners, monitor the underlying VM: CPU, RAM, disk usage during build spikes. If builds are slow, check if you're saturating CPU or if Docker image pulls are eating time.

I keep a simple shell script that pings the runner service status and alerts if it's not running:

```bash
#!/bin/bash
for i in 1 2 3 4; do
  STATUS=$(cd ~/actions-runner-$i && ./svc.sh status 2>&1)
  if ! echo "$STATUS" | grep -q "active (running)"; then
    echo "Runner $i is DOWN: $STATUS"
    # alert via curl to webhook, email, whatever
  fi
done
```

Run it via cron every 5 minutes. Not sophisticated, but it catches the runner binary crashing or the service stopping after a system reboot (which happens if you forget `--start-on-boot`).

## When it's worth it

Self-hosted runners pay off when:
- You have consistent CI usage that would exceed GitHub's free tier
- You need macOS runners and don't want the 10x per-minute cost
- Your builds need access to internal services (databases, private registries, internal APIs) that aren't reachable from GitHub's cloud
- You need more RAM/CPU than GitHub-hosted standard runners offer (they're 2-core, 7GB RAM)
- You need a specific OS version or pre-installed toolchain that's painful to set up fresh every run

Stick with GitHub-hosted when:
- Your CI usage is light or infrequent
- You don't want the operational overhead
- You run public repositories (security — don't do self-hosted on public repos)
- Your workflows are simple and the free tier covers it

The setup genuinely takes an afternoon. The maintenance is low once it's running. For any team with regular CI usage and an existing VPS, it's an easy call.

3h4x
