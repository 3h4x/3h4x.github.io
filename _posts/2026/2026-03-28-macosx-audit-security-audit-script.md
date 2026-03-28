---
layout: post
title:  "macosx-audit - know what's running on your Mac"
categories: tech
tags: [macos, security, bash, devtools]
comments: True
---

In the last post I teased this one — so here it is! `macosx-audit` is a single-file bash script that audits your Mac's security posture. No agents, no daemons, no root required for most checks. Just run it and see what's there.

<!-- readmore -->

## Why?

I got tired of not knowing. As a developer my Mac accumulates a lot of stuff over time — `brew` taps from random tutorials, VS Code extensions I installed once and forgot, LaunchAgents planted by apps that never asked permission. And then there are the nastier things: supply chain attacks, malicious npm globals, SSH keys that shouldn't be there.

`rkhunter` exists for Linux. For macOS? Not much. So I wrote something.

## Quick start

```bash
git clone git@github.com:3h4x/macosx-audit.git ~/workspace/macosx-audit
ln -s ~/workspace/macosx-audit/security-audit ~/bin/security-audit

security-audit
```

That's it. Needs `bash 4+` because macOS ships with `bash 3` (thanks, GPLv3). Install with `brew install bash` if you haven't already.

## What it checks

The script covers a lot of ground. Here's the rough breakdown:

**System hardening** — SIP, Gatekeeper, FileVault, Firewall. The basics that should always be on.

**Persistence** — LaunchAgents and LaunchDaemons with an allowlist. Anything not on the list gets flagged. `com.apple.*` entries are additionally validated to actually point to Apple system paths (a common spoofing trick). Also covers cron jobs, MDM profiles, login items, folder actions, privileged helpers, and XProtect staleness.

**Shell profiles** — scans `.zshrc`, `.bashrc`, `.zshenv`, `.zshrc.d/` etc. for reverse shells, `eval+curl` patterns, and base64 decode tricks.

**Supply chain** — this is the one I'm most excited about. Flags recently installed VS Code extensions (<7 days), non-default `brew` taps, npm globals, pip user packages, and — my favorite — MCP server configs for Claude Desktop and Cursor. If you're using AI coding tools you probably have a bunch of MCP servers configured. Worth knowing what's there.

**Config abuse** — SSH config for `ProxyCommand` abuse (CVE-2025-61984), git hooks (global and per-repo), PATH entries that are world-writable or empty, DNS and proxy settings.

**Network** — listening ports, established connections (deduplicated), suspicious port detection (4444, 5555, 1337 — the classics).

**Deep checks** (run with `--root` or `sudo security-audit --all`) — TCC permissions, Background Task Manager dump, temp directory executables, DYLD injection, reverse shells with network sockets, DNS tunneling indicators, process spoofing detection, promiscuous network interfaces, recently modified system binaries, and more.

## The output

```
macOS Security Audit — 2026-03-28 13:47:58
Host: MacBook.local | User: 3h4x | macOS 26.4

=== System Hardening ===
  [OK] System Integrity Protection (SIP) enabled
  [OK] Gatekeeper enabled
  [OK] FileVault disk encryption enabled
  [OK] macOS Firewall enabled

=== Persistence: LaunchAgents & LaunchDaemons ===
  [-] User Agent: com.google.GoogleUpdater.wake -> GoogleUpdater
  [-] User Agent: homebrew.mxcl.redis -> /opt/homebrew/opt/redis/bin/redis-server
  [-] System Agent: at.obdev.littlesnitch.agent -> Little Snitch Agent
  [-] System Daemon: com.docker.socket -> /Library/PrivilegedHelperTools/com.docker.socket
  [-] System Daemon: com.malwarebytes.mbam.rtprotection.daemon -> RTProtectionDaemon

=== Supply Chain ===
  [-] VS Code: 15 extension(s) installed
  [!] VS Code extension installed <7 days ago: anthropic.claude-code-2.1.86-darwin-arm64
  [!] VS Code extension installed <7 days ago: google.geminicodeassist-2.75.0
  [-] npm global packages: 4
  [!] Non-default brew tap: steipete/tap
  [!] Non-default brew tap: supabase/tap

=== DNS Tunneling Indicators ===
  [!] High DNS query volume in last 5 minutes: 4213 entries (possible DNS tunneling)

=== Processes Running from Deleted Files ===
  [!] Process binary no longer on disk: iTermServer-3.5.5 (PID 54058)
  [!] Process binary no longer on disk: cloudcode_cli (PID 75709)

─── Summary ───

20 finding(s):
  - VS Code extension installed <7 days ago: anthropic.claude-code-2.1.86-darwin-arm64
  - Non-default brew tap: steipete/tap
  - Non-default brew tap: supabase/tap
  - High DNS query volume in last 5 minutes: 4213 entries (possible DNS tunneling)
  - Process binary no longer on disk: iTermServer-3.5.5 (PID 54058)
  ...
```

Four severity levels: `[OK]` green, `[-]` informational (known-good stuff), `[!]` yellow warning, `[!!]` red critical. Summary at the end so you can scroll straight there.

## Running specific checks

You don't have to run everything every time:

```bash
security-audit --list                     # see all available checks
security-audit --check=supply_chain       # just supply chain
security-audit --check=launch_agents      # just persistence
security-audit --root                     # add root-requiring checks
sudo security-audit --all                 # everything, including TCC/BTM
```

Config file is optional — `~/.config/macosx-audit/config.yaml` with `key: true/false` to toggle individual checks. No config means all non-root checks run by default.

## What's under the hood

Single bash file, for now. No dependencies beyond macOS builtins + bash 4+. Each check is a `check_<name>()` function. YAML config is parsed with grep/regex — no `yq` dependency. The whole thing is read-only, it never touches the system.

The deep checks (round 2) are informed by actual macOS malware research: LightSpy, RustyAttr, ChillyHell, NightPaw, DigitStealer — each attacking a different phase. Detection is mapped to the attack lifecycle:

- **Initial access** → browser extensions, sudoers tampering
- **Persistence** → launchctl state, dylib injection
- **Execution** → temp executables, hidden files
- **C2** → reverse shells, DNS tunneling
- **Defense evasion** → process spoofing, deleted-but-running binaries, promiscuous interfaces

Is it comprehensive? No. A determined attacker with kernel-level access will evade it. But that's not the threat model. This is for catching the 80% of things that end up on a developer Mac through normal use — misconfigured tools, supply chain weirdness, forgotten agents, that one app that thought it was fine to install a LaunchDaemon without telling you.

## What I learned

The LaunchAgent allowlisting was the trickiest part. macOS has hundreds of legit `com.apple.*` agents but malware loves to spoof that prefix. The script validates that any `com.apple.*` entry actually points to `/System/`, `/usr/`, or `/Library/Apple/` — not some random `node` binary in Homebrew. That check alone catches a real category of persistence abuse.

The supply chain section surprised me when I first ran it on my own machine. 15 VS Code extensions, five of which were updated in the last week. Two non-default brew taps I had to think about. And the deep checks caught processes running from deleted binaries — iTerm and Google Cloud CLI had updated but the old processes were still alive. None of it malicious, but all of it worth knowing about.

## Go run it

```bash
git clone git@github.com:3h4x/macosx-audit.git
cd macosx-audit
./security-audit
```

First run is always interesting. I'd love to hear what shows up on your machine ;)

GitHub: [github.com/3h4x/macosx-audit](https://github.com/3h4x/macosx-audit)

Know what you are doing and have fun!

3h4x
