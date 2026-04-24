---
layout: post
title:  "Checkmarx KICS got compromised — the irony writes itself"
categories: tech
tags: [security, supply-chain, docker, devops, github-actions, kics, bitwarden, npm]
comments: True
---

A security scanner you pull into your CI pipeline to *find* vulnerabilities got turned into the vulnerability. On April 22, 2026 at 12:31 UTC, someone with valid Checkmarx publisher credentials pushed malicious images to the official `checkmarx/kics` Docker Hub repo. Tags affected: `latest`, `v2.1.20-debian`, `v2.1.21-debian`, `alpine`, `debian` (Checkmarx's own writeup stresses that "known safe versions" were not overwritten — the malicious `v2.1.21-debian` tag is a fresh one that doesn't correspond to a real release). If your pipeline ran `docker pull checkmarx/kics:latest` during that window, you shipped a credential stealer into your own runner.

And KICS wasn't alone. The [Checkmarx security update on April 22](https://checkmarx.com/blog/checkmarx-security-update-april-22/) confirms the blast radius spanned three separate artifact types: the KICS Docker image, the `ast-github-action` GitHub Action (malicious tag `2.3.35`, fixed in `2.3.36`), and two VS Code extensions — `ast-results` (versions 2.63, 2.66) and `cx-dev-assist` (versions 1.17, 1.19), both patched in 2.67.0+. The IDE extensions are the scary part: they auto-update in the background on your laptop, not just in CI.

<!-- readmore -->

## What actually happened

This is the second Checkmarx supply chain breach in two months. The group claiming responsibility — TeamPCP — already hit Checkmarx in March 2026, compromising the `ast-github-action` and `kics-github-action` GitHub Actions workflows to plant a credential stealer. Same playbook, new attack surface.

The April round hit Docker Hub, GitHub Actions and the VS Code marketplace in a coordinated burst:

- **KICS Docker image**: `2026-04-22 12:31 UTC → 12:59 UTC` (~28 min)
- **`ast-github-action` v2.3.35**: `2026-04-22 14:17 UTC → 15:41 UTC` (~84 min)
- **VS Code extensions (`ast-results`, `cx-dev-assist`)**: overlapping window, exact bounds still being confirmed

Plenty long for every CI pipeline pulling `:latest` (and you know there are still people pulling `:latest`) to ingest it — and more than long enough for VS Code's silent background updates to pull the bad extensions onto developer laptops.

The IoCs Checkmarx published — `checkmarx.cx` (91.195.240.123) and `audit.checkmarx.cx` (94.154.172.43) — are typosquats on the legitimate `checkmarx.com` domain. Worth blocking at the egress layer even if you think you weren't affected; they may resurface.

The payload, from what's been reported, was pretty comprehensive:

- Obfuscated Go ELF binary named `kics` (replacing the real KICS scanner) that harvested GitHub tokens, AWS credentials, Azure/GCP tokens, npm config files, SSH keys, and environment variables
- Everything got compressed, encrypted, and exfiltrated to a C2 endpoint
- Stolen GitHub tokens were used to *inject a new GitHub Actions workflow* (`format-check.yml`) into writable repos — the workflow dumps the entire secrets context to an artifact file and makes it downloadable by the attackers
- Stolen npm creds were used to identify writable packages for downstream republishing — so this was positioned to cascade

That last part is the interesting bit. It's not just "we stole your secrets and left." It's "we stole your secrets, planted a mechanism to steal more secrets from future workflow runs, and identified which of your npm packages we can hijack next." Supply chain attacks eating supply chain attacks.

## And then Bitwarden CLI got swept up

This is where it stops being a Checkmarx-only story. `@bitwarden/cli@2026.4.0` was briefly poisoned on npm — same attacker toolkit, same week, likely the same downstream republishing flow that was primed by the Checkmarx npm-token theft. The vector: a compromised GitHub Action inside Bitwarden's build pipeline injected the malicious payload at publish time, so the package was signed by Bitwarden's own CI and looked entirely legitimate on the registry.

A password manager CLI is about as trust-maximal as a binary gets. It reads vault contents, SSH keys, API tokens, `.env` files — often on developer laptops that don't have the same egress controls a CI runner might. If `@bitwarden/cli@2026.4.0` made it into your CI image, your `Dockerfile`, your `nvm`-managed dev shell, or a `npx` one-liner during that window, treat that environment as fully compromised. Rotate every vault credential touched since the install, rotate SSH keys, and audit access logs for anything the attacker could have replayed.

Pin the CLI to a known-good version and install explicitly:

```bash
# pin to a version predating the incident
npm install -g @bitwarden/cli@2026.3.1

# or better, pin by integrity hash in package-lock.json
npm install --save-exact @bitwarden/cli@2026.3.1
```

The bigger lesson: when the attacker owns a CI Action, they own every artifact it publishes. One compromised action cascades into N poisoned packages across N vendors, and the "which of your npm packages do we have write access to" reconnaissance from the Checkmarx breach is exactly the fuel for that.

## The bit that should scare you

KICS is *security scanning software*. The kind of thing that runs early in your pipeline, with broad permissions, reading your IaC, your env, your secrets-as-variables. You don't pull a linter into a sandbox. You give it the repo and the tokens and let it rip.

That's the whole threat model reversal. Your static analysis tool, your SAST scanner, your IaC linter — they all run with elevated context because they need it. When one of them gets subverted, the blast radius is "everything the CI runner could see."

Look at what a typical CI job exposes:

```yaml
# .github/workflows/scan.yml — a totally normal config
- uses: checkmarx/kics-github-action@v2.1.20
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
    AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

You pinned the version! You thought you were safe! But the attacker overwrote the tag digest, not the tag name. `v2.1.20` used to point at digest `sha256:abc...`, now it points at `sha256:evil...`. Same tag, different image. Docker Hub lets you do this, Git lets you do this with tags, npm lets you do this with certain flows. Pinning versions by name is not pinning.

## How to actually pin things

The only real fix is digest pinning. For Docker:

```yaml
# instead of this
- uses: docker://checkmarx/kics:v2.1.20

# do this
- uses: docker://checkmarx/kics@sha256:1a2b3c4d5e6f...
```

For GitHub Actions:

```yaml
# instead of this
- uses: checkmarx/kics-github-action@v2.1.20

# do this
- uses: checkmarx/kics-github-action@a1b2c3d4e5f6...  # commit SHA
```

The commit SHA approach is what Dependabot's been pushing for years. Everyone ignored it because `@v2` is prettier and auto-updates. Turns out auto-updates include "now with 100% more credential exfil."

You can automate this with `pin-github-action` or `ratchet`:

```bash
# ratchet pins all actions in a workflow to commit SHAs
ratchet pin .github/workflows/*.yml

# and you can keep them somewhat readable
ratchet unpin .github/workflows/*.yml  # back to tags for diffing
```

If you run a lot of workflows, [StepSecurity's Harden-Runner](https://github.com/step-security/harden-runner) is worth looking at. It audits outbound network traffic from your runners and alerts on unknown destinations. Won't stop a compromise in progress, but will tell you if one of your actions suddenly starts calling a domain it's never called before.

## Detection — did you get hit?

If you were pulling KICS images in the April 22 window, you need to check. The indicators reported so far:

```bash
# look for the malicious tags
docker images --digests | grep checkmarx/kics

# check GHA workflow history for injected workflows
# any `format-check.yml` or similar files added outside of your normal commit flow
find .github/workflows -newer <last-known-good-date> -type f

# check for unexpected workflow_run artifacts in recent runs
gh run list --workflow=format-check.yml --repo <org>/<repo>
```

Rotate anything that was in scope of a pipeline run during that window:

- GitHub PAT, GitHub App installation tokens
- AWS access keys (rotate, then audit CloudTrail for usage)
- Azure service principals, GCP service account keys
- npm publish tokens
- SSH keys used by the runner
- Any env var that was passed to the job
- **If Bitwarden CLI 2026.4.0 was installed anywhere**: every credential in the vault of any account that was unlocked on that machine

Also check developer laptops, not just CI:

```bash
# did a dev install the bad Bitwarden CLI?
npm ls -g @bitwarden/cli
# and the poisoned Checkmarx VS Code extensions?
code --list-extensions --show-versions | grep -i checkmarx
```

Block the typosquat IoCs at your egress layer and check DNS logs for historical resolution:

```bash
# query your DNS logs for anything that resolved checkmarx.cx or audit.checkmarx.cx
# (replace with whatever your resolver / SIEM query looks like)
grep -iE 'checkmarx\.cx|audit\.checkmarx\.cx' /var/log/dnsmasq.log
```

The AWS CloudTrail audit is worth calling out. After you rotate credentials, query the old credentials' recent usage:

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=Username,AttributeValue=<leaked-iam-user> \
  --start-time 2026-04-22T14:00:00Z \
  --end-time 2026-04-24T00:00:00Z \
  --query 'Events[].[EventTime,EventName,SourceIPAddress,Resources]' \
  --output table
```

Any API calls from IPs you don't recognize, from regions you don't operate in, or actions outside the normal pattern — that's your incident response starting point.

## The uncomfortable "trust" question

Checkmarx is a public company, a security vendor, exactly the kind of org you'd expect to have publisher credentials locked down with MFA, short-lived tokens, hardware keys, the works. And they got owned twice in two months by the same group.

The defensive posture of "use tools from reputable vendors" is doing less work than it used to. Reputable vendors get popped. What actually helps:

- **Digest pinning everywhere** — the boring, tedious fix that nobody wants to do until they have to
- **Egress control on CI runners** — most CI jobs don't need internet-at-large, they need npm, pypi, Docker Hub, and maybe your artifact store. Allowlisting outbound is painful but tractable
- **Ephemeral runners** — self-hosted runners that come up fresh for each job and get destroyed after. I set this up with Ansible for a bunch of projects on `goro`, worth the effort
- **Scoped tokens** — the PAT you give your scanning action should not be able to `push` anywhere. Fine-grained tokens are finally decent, use them

This is the dull operational stuff that doesn't make for exciting conference talks. It also would've contained the blast radius of the KICS attack.

## When NOT to bother

If you're a solo dev with one repo and your secrets are "the TMDb API key for my movie list" — relax. The supply chain paranoia treadmill has diminishing returns for everyone, and for small personal projects the honest answer is "the `@v2` tag is fine, you have nothing worth stealing, and the time you'd spend digest-pinning is better spent shipping."

The calculus changes when:

- You have prod AWS/GCP credentials exposed to CI
- You publish npm/pypi packages that others depend on
- You run workflows on pull requests from forks (hello, `pull_request_target` footgun)
- You're in a regulated industry where an incident means paperwork

If any of those apply, pinning to SHAs is not optional anymore. It's table stakes.

## tl;dr

Coordinated April 22, 2026 supply chain hit on Checkmarx: KICS Docker image (~28 min), `ast-github-action` v2.3.35 (~84 min), and two VS Code extensions (`ast-results`, `cx-dev-assist`) all poisoned in overlapping windows. Credential stealer payload, GitHub Actions workflow injection, npm package targeting for downstream attacks. Second Checkmarx breach in two months. The same wave also took out `@bitwarden/cli@2026.4.0` via a compromised GitHub Action in Bitwarden's build pipeline — if that version landed in your CI or dev shell, rotate the vault. IoC domains: `checkmarx.cx`, `audit.checkmarx.cx`. Going forward: digest-pin Docker images, SHA-pin GitHub Actions, disable auto-update for security-adjacent IDE extensions, egress-control CI runners. The "use reputable vendors" defense is done working on its own.

Know what you are doing and have fun!

3h4x
