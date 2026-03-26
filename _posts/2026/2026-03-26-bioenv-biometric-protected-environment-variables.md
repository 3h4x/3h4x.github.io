---
layout: post
title:  "bioenv - Touch ID for your environment variables"
categories: tech
tags: [macos, security, swift, devtools]
comments: True
---

I haven't been around here for quite some time. 6 years to be exact! Life got busy, work got busy, everything got busy. But I'm back and I have something cool to share. Let's get to the point.

<!-- readmore -->

## The problem

If you're a developer you probably have `.env` files scattered across your projects. Database credentials, API keys, cloud tokens — all sitting there in plaintext. We all know it's not great but we do it anyway because it's convenient.

I've been thinking about this for a while. We have `Touch ID` on our Macs, we have `Keychain`, we have hardware-backed encryption. Why are we still storing secrets in plain text files? There has to be a better way!

## bioenv

So I built `bioenv` — a CLI tool that replaces `.env` files with biometric-protected encrypted storage. One fingerprint tap and your secrets are loaded into the shell. No fingerprint, no secrets. Simple as that.

It's written in `Swift` with zero external dependencies. Just macOS frameworks — `Security`, `LocalAuthentication`, and `CryptoKit`. The whole thing is ~500 lines of code.

## How it works

Each project gets its own AES-256-GCM encryption key stored in macOS `Keychain`. The project identity is a SHA-256 hash of the absolute directory path, so everything is isolated. Every time you want to access secrets, `Touch ID` kicks in.

```
~/workspace/my-app/     -->  key in Keychain: "com.bioenv.a1b2c3d4..."
                        -->  secrets in:     ~/.bioenv/a1b2c3d4....enc
```

No master password, no config files, no subscriptions. Just your fingerprint and the Mac's hardware.

## Quick start

Grab the binary from the [latest release](https://github.com/3h4x/bioenv/releases/latest) and you're good to go:

```bash
curl -L https://github.com/3h4x/bioenv/releases/download/v0.1.0/bioenv-arm64 -o ~/bin/bioenv
chmod +x ~/bin/bioenv
```

Or if you prefer to build from source:

```bash
git clone https://github.com/3h4x/bioenv
cd bioenv
swift build -c release
codesign -s - -f .build/release/bioenv
cp .build/release/bioenv ~/bin/
```

Either way, piece of cake. Now let's use it:

```bash
cd ~/workspace/my-app

# Initialize for this project
bioenv init

# Add secrets (Touch ID prompt)
bioenv set DATABASE_URL "postgres://user:pass@localhost/mydb"
bioenv set API_KEY "sk-abc123"

# Load them into your shell
eval "$(bioenv load)"
```

That's it! Your secrets are encrypted at rest and `Touch ID` is required every time you access them.

## direnv integration

This is where it gets really nice. If you use `direnv` (and you should ;)) just add this to your `.envrc`:

```bash
eval "$(bioenv load)"
```

Now when you `cd` into the project, `direnv` triggers `bioenv load`, Touch ID prompts once, and all secrets are in your shell. Leave the directory and they're gone. It's exactly like having `.env` files but encrypted and biometric-protected.

## Migrating from .env files

Already have a project full of `.env.local` secrets? Migration takes 30 seconds:

```bash
cd ~/workspace/my-app
bioenv init
bioenv import .env.local
bioenv list # verify everything is there

# Switch direnv to use bioenv
echo 'eval "$(bioenv load)"' > .envrc
direnv allow

# Test it, then nuke the plaintext
rm .env.local
```

Done. Everything works exactly the same, the only difference is a Touch ID prompt. Your secrets are no longer sitting in plaintext waiting for someone (or something) to read them.

## What's inside

The architecture is dead simple — 5 files, each doing one thing:

| File | What it does |
|------|-------------|
| `main.swift` | CLI entry, argument parsing, command dispatch |
| `Keychain.swift` | Keychain CRUD + Touch ID auth via `LAContext` |
| `Crypto.swift` | AES-256-GCM encrypt/decrypt with `CryptoKit` |
| `Store.swift` | Encrypted JSON file operations, `.env` parsing |
| `Config.swift` | Configuration management |

No `ArgumentParser`, no package dependencies. I wanted this to be self-contained and easy to audit. You can read the whole codebase in 10 minutes.

## Limitations

I want to be honest about what this is and what it isn't:

- **macOS only** — it needs Keychain and LocalAuthentication framework, so no Linux, sorry
- **Device-bound keys** — by default your encryption keys don't leave your Mac. If you get a new one you'll need to re-import
- **No team sharing** — this is for personal developer secrets. For teams use Vault or 1Password
- **iCloud sync needs Apple Developer cert** — ad-hoc signing works for everything else but iCloud Keychain requires the $99/yr certificate

## Why Swift?

I wanted native macOS integration without any FFI or bridging hacks. `Swift` gives direct access to `Security.framework`, `LocalAuthentication.framework`, and `CryptoKit`. The binary is small, starts instantly, and there's no runtime to worry about. For a tool that wraps macOS system APIs, it was the obvious choice.

## What's next

I'm thinking about adding shell completions and maybe a `brew` formula to make installation easier. If there's interest I might look into supporting multiple profiles per project (dev/staging/prod secrets).

Speaking of macOS security — `bioenv` protects your secrets but what about the rest of your system? I've been working on `macosx-audit`, a tool to audit your Mac's security configuration. That's going to be the next post, stay tuned!

Check it out on GitHub: [github.com/3h4x/bioenv](https://github.com/3h4x/bioenv)

Know what you are doing and have fun!

3h4x
