---
layout: post
title: "SSH config tricks I wish I knew years ago"
categories: tech
tags: [ssh, devtools, security]
comments: True
---

For years I SSH'd into servers by typing the full command every time. `ssh -i ~/.ssh/id_rsa -p 2222 user@192.168.1.100`. Sometimes with a jump host in the middle. It worked, but it was tedious and error-prone. Then I actually read the `ssh_config` man page and felt mildly embarrassed about all the time I'd wasted.

<!-- readmore -->

## The basics you probably know

`~/.ssh/config` lets you define named aliases for SSH connections:

```
Host myserver
    HostName 192.168.1.100
    User deploy
    Port 2222
    IdentityFile ~/.ssh/id_ed25519_myserver
```

Now `ssh myserver` works. You probably already knew this. But there's a lot more.

## ProxyJump — the right way to do bastion hosts

Before `ProxyJump` existed, people used `ProxyCommand` with `ssh -W %h:%p` or `nc`. It worked but it was ugly. `ProxyJump` is clean:

```
Host bastion
    HostName bastion.example.com
    User ec2-user
    IdentityFile ~/.ssh/id_ed25519

Host private-server
    HostName 10.0.1.50
    User ubuntu
    ProxyJump bastion
    IdentityFile ~/.ssh/id_ed25519
```

Now `ssh private-server` automatically connects through the bastion. No typing. No remembering the internal IP. You can chain multiple hops too — `ProxyJump bastion1,bastion2` if your network is that layered.

This also works with `rsync`, `scp`, and anything else that goes over SSH. `rsync -avz private-server:/data/backups ./` works transparently through the jump host.

The SSH agent is key here. Your private key needs to be available to authenticate both hops. Which brings me to the next point.

## Agent forwarding — but carefully

`ForwardAgent yes` lets the remote server use your local SSH agent to authenticate to further servers. This is how you hop from bastion to private server without copying your private key to the bastion.

```
Host bastion
    HostName bastion.example.com
    User ec2-user
    ForwardAgent yes
```

But be careful. When you forward your agent, any process on the remote server with access to the agent socket can use your keys. If the bastion is compromised, your keys are compromised. The rule I follow: only forward the agent to machines you fully trust and control. Not shared bastion hosts used by other teams, not rented cloud instances you don't own exclusively.

For jump hosts you don't fully trust, `ProxyJump` is safer than `ForwardAgent` — the connection happens client-side and the intermediate host never sees your key.

## Multiplexing — one TCP connection, many sessions

Every `ssh` invocation opens a new TCP connection and does a full handshake. On high-latency connections or servers with slow auth, this adds up. Multiplexing reuses an existing connection:

```
Host *
    ControlMaster auto
    ControlPath ~/.ssh/cm/%r@%h:%p
    ControlPersist 10m
```

First connection to a host creates the control socket. Subsequent connections reuse it — they're nearly instant. `ControlPersist 10m` keeps the master connection alive for 10 minutes after you close the last session.

Create the directory first:

```bash
mkdir -p ~/.ssh/cm
chmod 700 ~/.ssh/cm
```

The practical benefit is noticeable. Running `git pull` over SSH, `rsync`, multiple terminal sessions to the same host — all share one connection. On a remote VPS over a mediocre connection, this makes a real difference.

To check if a multiplexed connection exists:

```bash
ssh -O check myserver
```

To cleanly close it:

```bash
ssh -O exit myserver
```

## Per-host keys — stop using the same key everywhere

I used to have one `id_rsa` key for everything. That's a mistake. If that key is compromised, everything is compromised.

A better pattern: a key per context (personal, work, per-project), referenced explicitly in the config:

```
Host github.com
    IdentityFile ~/.ssh/id_ed25519_github
    IdentitiesOnly yes

Host work-server
    HostName 10.50.0.1
    User admin
    IdentityFile ~/.ssh/id_ed25519_work
    IdentitiesOnly yes

Host personal-vps
    HostName 65.108.x.x
    User deploy
    IdentityFile ~/.ssh/id_ed25519_personal
    IdentitiesOnly yes
```

`IdentitiesOnly yes` is important — it tells SSH to *only* try the key you specified, and not try every key in the agent. Without it, SSH will try all keys the agent knows about, which can trigger "Too many authentication failures" errors on servers with low `MaxAuthTries`.

Generate `ed25519` keys, not `rsa`. They're shorter, faster, and more secure:

```bash
ssh-keygen -t ed25519 -C "deploy key for personal-vps" -f ~/.ssh/id_ed25519_personal
```

## Match blocks — conditional config

`Match` lets you apply settings conditionally. Useful when behavior should change based on context:

```
Match Host *.internal User admin
    ProxyJump bastion
    ForwardAgent yes

Match Host github.com gitlab.com
    IdentitiesOnly yes
    AddKeysToAgent yes
```

You can match on `Host`, `User`, `LocalUser`, `Network`, and more. I use this for VPN-dependent hosts — if I'm connected to the office VPN, certain hosts should route directly; otherwise they need the jump host. You can approximate this by keeping a separate config file per network and symlinking, but `Match` handles simpler cases cleanly.

## ServerAliveInterval — stop getting dropped

On connections that go idle, some firewalls and NAT devices close the session. You come back to a frozen terminal and have to open a new one.

```
Host *
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

Sends a keepalive packet every 60 seconds. If 3 go unanswered, the SSH client terminates the connection. Cleaner than a frozen terminal that never times out.

## AddKeysToAgent — automatic key loading

```
Host *
    AddKeysToAgent yes
    IdentityFile ~/.ssh/id_ed25519
```

When SSH uses a key, it automatically adds it to the running `ssh-agent`. So you only need to enter the passphrase once per session, and subsequent connections reuse the cached key. Combine this with macOS Keychain integration (`UseKeychain yes` on macOS) and you enter the passphrase exactly once ever:

```
Host *
    AddKeysToAgent yes
    UseKeychain yes
    IdentityFile ~/.ssh/id_ed25519
```

## HashKnownHosts — a privacy setting worth knowing

By default, `~/.ssh/known_hosts` stores hostnames in plaintext. If someone gets access to your known_hosts file, they can see a list of every host you've connected to. `HashKnownHosts yes` stores SHA1 hashes instead:

```
Host *
    HashKnownHosts yes
```

The tradeoff: you can't grep known_hosts for a hostname anymore. `ssh-keygen -F hostname` still works to look up a specific host. And `ssh-keygen -R hostname` still removes it. But you lose human-readable browsing of the file. For most people the privacy benefit outweighs this.

## A full config example

Here's roughly what mine looks like, sanitized:

```
# Global defaults
Host *
    ServerAliveInterval 60
    ServerAliveCountMax 3
    ControlMaster auto
    ControlPath ~/.ssh/cm/%r@%h:%p
    ControlPersist 10m
    AddKeysToAgent yes
    UseKeychain yes
    HashKnownHosts yes

# GitHub
Host github.com
    IdentityFile ~/.ssh/id_ed25519_github
    IdentitiesOnly yes

# Bastion / jump host
Host bastion
    HostName bastion.example.com
    User ec2-user
    IdentityFile ~/.ssh/id_ed25519_work
    IdentitiesOnly yes

# Private servers behind bastion
Host *.internal
    ProxyJump bastion
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519_work
    IdentitiesOnly yes

# Personal VPS
Host vps
    HostName 65.108.x.x
    User deploy
    IdentityFile ~/.ssh/id_ed25519_personal
    IdentitiesOnly yes
```

The `Host *` block at the top sets defaults. More specific blocks below it override what they need to. The order matters — SSH reads top to bottom and first match wins for each directive, so put specific hosts before catch-all patterns.

## Debugging SSH connection issues

When something's not working, `-vvv` is your friend:

```bash
ssh -vvv myserver
```

The output is verbose, but you can see exactly which keys are being tried, which config directives are being applied, and where the handshake is failing. Saves a lot of guessing.

SSH config is one of those tools where learning it properly pays dividends every single day. I probably type 50% fewer characters in my terminal now compared to before I set mine up properly.

3h4x
