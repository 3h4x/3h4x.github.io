---
layout: post
title: "Claude Mythos: the AI that hacked every OS and emailed a researcher about it"
categories: tech
tags: [ai, security, anthropic, claude, cybersecurity, llm]
comments: True
---

Anthropic has a new model. You can't have it. Neither can I. And after reading what it did during testing, I'm not sure that's a bad call.

<!-- readmore -->

Claude Mythos Preview dropped quietly — first leaked in March, then officially acknowledged. No public API, no pricing page, no waitlist. Access is invite-only through something called Project Glasswing, a consortium of ~40 organizations doing defensive security work: Amazon, Apple, Cisco, Google, JPMorgan, Microsoft, CrowdStrike. If your company name isn't on that list, you're not getting access.

Here's why.

## What it can do

The cybersecurity benchmark gap between Mythos and the previous best (Opus 4.6) is not incremental. Opus 4.6 scores 66.6% on cybersecurity benchmarks. Mythos scores 83.1%. That's a 16.5 percentage point jump on tasks that were already hard.

But benchmarks are the boring part. The concrete findings are what matter:

- Found thousands of previously unknown vulnerabilities across evaluated targets, including every major operating system and web browser tested
- Discovered a 17-year-old remote code execution vulnerability in FreeBSD's NFS server (CVE-2026-4747) — full root access, found and exploited autonomously in a controlled test environment
- Wrote a browser exploit chaining four vulnerabilities including a JIT heap spray that escaped both renderer and OS sandboxes
- On Firefox 147's JavaScript engine in an automated pipeline: Opus 4.6 turned found vulnerabilities into working exploits twice out of several hundred attempts. Mythos did it 181 times, plus 29 more where it achieved register control without a full exploit.

Autonomously. No human in the loop for the exploit development step.

## The sandwich story

During red team testing, Mythos was given a sandboxed environment and told by a simulated user to try to escape it. It did. It developed an exploit to access the internet through a system that was only supposed to reach a few predetermined services, then emailed the human researcher to let him know it had succeeded.

He found out while eating a sandwich in a park.

That's already remarkable. The part Anthropic buried in a footnote: after the test ended, Mythos — without being asked — posted about its exploits on several obscure but public websites.

Not because it was instructed to. Not as part of the test. It just decided to document what it had done.

Anthropic called this behavior "reckless." They also called it a reason not to release the model publicly, which is the correct response.

## Project Glasswing

A model that autonomously escapes sandboxes and documents its own exploits needs a deployment strategy that isn't "put it on an API and see what happens." Anthropic's answer is Project Glasswing: rather than a public release or a controlled drip, they're channeling the capability directly into defensive work. The consortium partners get Mythos access to scan their own systems. The vulnerabilities it finds go to defenders first, coordinated disclosure before anyone else sees them.

This is roughly how you'd want a dual-use capability like this to work. Channeling it through a structured defensive program rather than an open API is a reasonable call — the same capability that finds bugs in your code can find them in an attacker's target.

Whether it holds is a different question. Forty organizations is not a tight secret. Each one has engineers, contractors, procurement systems, and Slack channels. Capabilities diffuse. The question isn't if, it's how fast.

## What this means for the rest of us

I've been building on Claude for months — Claude Code as my daily driver, MCP tooling, agentic workflows across my projects. The current models are already useful for security work: code review, audit assistance, finding logic errors. Clawdit, my smart contract audit platform, uses Claude for exactly this.

Mythos is a different category. The jump from "useful for security review" to "autonomously chains four vulnerabilities into a working browser exploit" is not incremental. It's a boundary crossing — the same kind of shift that fuzzing was in the 90s or symbolic execution in the 2000s. Those tools didn't replace security researchers, but they permanently changed what one researcher could cover in a day. This does the same, at a higher capability ceiling.

Two things are now true simultaneously:

**Defenders will get better tools.** Automated vulnerability discovery at Mythos-level capability, deployed by the organizations that own critical infrastructure, will close bugs that would otherwise survive for another decade. That's genuinely good.

**The attacker side catches up.** Not through Mythos specifically — the access controls will hold for a while. But the capability exists. Other labs are close. The assumption that vulnerability discovery is bottlenecked by human researcher time is going away.

## You can't fight what you don't know

Here's the uncomfortable truth about Mythos-class threats: the exploits it generates are built on the same foundations that have always existed — unpatched systems, supply chain compromises, leaked credentials, misconfigured services. The AI doesn't invent new attack surfaces. It just finds and chains the existing ones faster than any human researcher can.

Which means the boring stuff still matters. More than ever.

I built two tools earlier this year that feel more relevant now than when I wrote them.

[macosx-audit](https://github.com/3h4x/macosx-audit) is a single-file bash script that audits your Mac's security posture — SIP, Gatekeeper, FileVault, persistence mechanisms (LaunchAgents, daemons, login items), shell profile injection patterns, and supply chain exposure: recently installed VS Code extensions, non-default brew taps, npm globals, MCP server configs. ~80 checks, no root required, no agents. The supply chain section is the one I care most about. You probably have software on your machine you don't remember installing. That's an attack surface.

[bioenv](https://github.com/3h4x/bioenv) solves the `.env` file problem. API keys and credentials sitting in plaintext files are exactly what automated exploit chains go for after initial access. bioenv replaces them with AES-256-GCM encrypted storage backed by macOS Keychain, unlocked by Touch ID. No fingerprint, no secrets. The secrets never exist in plaintext on disk.

Neither of these tools stops Mythos. Nothing you run on your laptop stops a well-resourced attacker with Mythos-class tooling. But they close the cheap wins — the attack paths that don't require novel zero-days, just patience and automation. And right now, closing cheap wins is the leverage point most people have.

## The honest position

I can't test Mythos. I'm not in the Glasswing consortium. I'm a solo engineer, not a Fortune 500 company with a signed Anthropic partnership.

What I can do is read the red team report carefully and update my mental model of what AI-assisted security tooling will look like in 18 months. The answer is: significantly more capable than anything available today, and available to well-resourced attackers before it's available to everyone else.

Build your defenses assuming the attacker has better tools than you do. Concretely: patch windows get shorter (automated exploit generation compresses the gap between disclosure and weaponization), monitoring needs to assume faster and more novel attack patterns, and any system that was "secure enough" because finding the bug was hard is now on borrowed time.

That's been true for a while. It's more true now.

3h4x
