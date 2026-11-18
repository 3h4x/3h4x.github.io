---
layout: post
title: "Autonomous software delivery: issue in, verified deploy out, and the next bottleneck"
categories: tech
tags: [ai, claude, claude-code, codex, gemini, litellm, agents, autonomous-agents, human-in-the-loop, kubernetes, k3s, kueue, argocd, sandbox, automation, ci-cd, datacrash]
comments: True
---

In April I wrote about [tamtam](/tech/2026/04/17/tamtam.html), a dashboard that drove Claude CLI across my workspace from PM2 on one box. Seven months later the same idea has grown into something I'm starting to show in public under [datacrash.io](https://datacrash.io): a system where the only thing a human is supposed to do is open an issue. Planning, the code, the pull request, review, CI, merge, deploy and the check that the thing actually works afterwards are all done by agents: Claude Code, Codex, Antigravity, or an agent driving any model behind LiteLLM, each one locked in its own sandbox on a k3s cluster.

datacrash.io is building an autonomous software delivery platform: model-agnostic, zero-trust by design and closed-loop, with a human in the loop only for the decisions that need one. A change only counts once it is verified in production.

This post is how that sandbox works, what the pipeline looks like end to end, some numbers from the last month, and the one thing that limits all of it today: tokens. The next post is about the optimizations that came out of hitting that limit.

<!-- readmore -->

## The problem

Behind datacrash.io there are about twenty repositories. Most of the work in them isn't hard, it's just *there*: a flaky test, a dependency bump, an alert that needs a fix, a small feature I already know how to describe in three sentences. A coding agent can do almost all of it. What it can't do on its own is the part around the code: notice the work, take it, keep the credentials away from the model, open a PR, wait for CI, react to a review, merge when it's green, deploy, and then come back and check that the issue is really closed in production and not just on GitHub.

That surrounding loop is what I kept doing by hand, and that loop is what TamTam (the control plane behind datacrash.io) now does. The goal is blunt:

> A human writes the issue. Everything after that is automated, and the human is only pulled in when the system can't decide on its own.

## The flow

Every issue is a card on a board with a handful of states. A card moves forward by itself and only stops when it needs me.

{% include diagrams/card-flow.html %}

- **Plan.** An agent reads the issue and the repo and writes a plan plus a concrete *Definition of done* into the issue body. Read-only checkout, no tests, no build.
- **Work.** A second agent implements the plan, runs the tests, and its output is turned into a branch and a PR. It never pushes itself (more on that below).
- **Review + CI.** Every PR gets an automated model review and the repo's CI. Findings, a red check or a conflict send the card back to Work with the failing logs attached, on the same PR. After a couple of rounds without progress it goes to Blocked instead of looping forever.
- **Merge.** A PR that fits the automatic approval rules (what it may touch and how big it may be) merges on its own once CI is green and the review is clean. Everything else, for example anything that changes CI workflows, waits for one click from me.
- **Deploy.** A merge to the default branch triggers the build inside the cluster and a rollout; the platform itself is reconciled by Argo CD, so the cluster state is always what's in git.
- **Verify.** After the deploy a read-only agent checks each item of the Definition of done against the live system (a real HTTP request to an approved host, an end-to-end test result from CI) and either closes the issue or sends it back to Work with what failed.

The part I care most about is Verify: closed-loop delivery. "Merged" is not "done". A card only closes itself when the thing it promised is observably true after the deploy.

The human-in-the-loop (HITL) part is deliberately narrow. A person is asked only for what an agent shouldn't decide alone: an answer when a card is Blocked (one concrete question in the issue, and the card waits for it), and approval of a merge outside the automatic rules. Everything else flows without anyone watching it.

## A zero-trust sandbox: one agent run, four Pods

Every agent run is a set of Kubernetes Jobs in a dedicated namespace. Each phase is its own Pod, they share a per-run volume, and they run one after another, with the proxy running next to the model:

{% include diagrams/agent-run.html %}

The split exists for one reason: **the model never holds a credential that can change anything outside its own run.**

- **prepare** is trusted code, no model. It has a git token, clones the repo, gathers the context the agent needs (the issue, the plan, CI failure logs, unresolved review threads, "this may already be fixed by commit X" hints) and writes it as files onto the run volume.
- **model** is the coding agent itself: Claude Code, Codex, Antigravity, or an agent talking to LiteLLM. The only secret it gets is that provider's login. No GitHub token, no cluster token (`automountServiceAccountToken: false`), non-root, no privilege escalation, all capabilities dropped, a seccomp profile, a hard deadline. Its only network route is its own run's proxy: no DNS, no direct egress.
- **proxy** is a tiny egress proxy with an allow-list per run type: the model API, the package registry cache, and for a Verify run only the hosts named in the Definition of done. Anything else is refused at connect time, including private addresses.
- **publish** is trusted code again. It reads what the agent wrote into an *outbox* (a diff, a comment, "move this card to Review", a risk assessment) and performs those actions with its own token after validating them. The agent can ask for a PR; it can't create one.

The consequence I like most: a prompt injection inside an issue or a dependency's README can make the model write nonsense into its outbox, but it can't push to `main`, read another repo's secrets or talk to the rest of the cluster. The worst case is a bad PR that still has to get through CI, review and the merge rules.

Two more pieces keep it running smoothly:

- **Kueue** admits agent Jobs. A run is created suspended and starts as soon as the cluster has room for it, so a burst of new cards becomes an orderly queue and the nodes stay busy without being overloaded.
- **CI runs in the same cluster** with the same idea: Jobs with no internet, no DNS and no secrets, only a package cache. Tools are baked into the image, never downloaded at run time.

## Model-agnostic by design

The sandbox doesn't care which agent runs inside it. Prepare, the proxy, the outbox and publish are the same for every run; only the image's agent CLI, its login and the proxy's allow-list for its API change. Today four kinds of agent take cards:

- **Claude Code**, Anthropic's agent,
- **Codex**, OpenAI's agent,
- **Antigravity**, Google's agent, with Gemini and other models,
- **LiteLLM**, which puts [anything with an OpenAI-compatible API](/tech/2026/08/29/litellm-proxy-pattern.html) behind one endpoint, including self-hosted open models.

Every stage can be routed to a different one: a plan, a review or a Verify check doesn't need the same model as a hard refactor. Every run records which provider and model did it, how many turns it took and whether the card moved forward, so a per-model scorecard shows where each one is worth sending and where it keeps failing. No provider is a single point of failure or a lock-in: when one has an outage or changes its terms, the same cards can go to the others. And because every provider has its own limits, more providers simply means more work done per week. That matters a lot, as the last section shows.

## Some numbers

The short version: **~2,400 merged pull requests in the last 30 days, and ~89% of the control plane's commits written by agents.** Rough figures from the system's own records:

| | |
|---|---|
| Agent runs since mid-October | ~12,800, of which ~3,000 were deterministic steps (merges, syncs, checks) that never called a model |
| Merged PRs, last 30 days, across all repositories | ~2,400 |
| Non-merge commits to the control plane in its first month written by an agent | ~89% (~60% by the autonomous pipeline, ~30% in interactive Claude Code sessions) |
| Median agent cost of a tiny PR (< 50 lines) | about $0.06 |
| Tokens read from cache vs tokens written, since June | ~48 billion vs ~175 million |

To be clear about who does what: the agents type most of the code, including most of the control plane's own. What TamTam is, how the flow works, what an agent may and may not touch, and what "done" means are my decisions, written down as issues. The control plane's own repository is the pipeline's busiest "customer" by far, which makes it both the best test and the most expensive one.

## The bottleneck: tokens

The bottleneck is no longer capability, it's unit economics: the cost of one verified change. The board is never empty: there are always hundreds of cards in Todo and planned cards waiting for Work. There is no shortage of work, of cluster capacity, or of ideas. What decides whether the next card starts is the token budget.

Every provider has a usage limit that resets on a schedule. So the scheduler does what a sane scheduler should: it spreads the runs across providers so each budget lasts until its reset, and parks everything else in the queue. Adding a provider raises the ceiling; it doesn't remove it.

And the numbers above show where those tokens go. For every output token the agents *write*, roughly **270 tokens are read from cache**: the system prompt, the skill, the repo context, the conversation so far, re-read on every turn of a long agentic session. Writing code is cheap. Re-reading the world to write it is not.

So the limit isn't "the model can't do it". The model can do most of it. The limit is how many full context reloads I can afford per week, and the system, as built, was spending them generously.

## What's next

The next post is about what I'm doing about it: cutting what each run has to read, routing cheap stages to cheaper models, making review rounds incremental instead of a fresh start, and measuring cost per *successful* card rather than per run, so a cheap run that fails stops looking like a win.

If you're investing in or building in this space, running agents against your own infrastructure, or just want to compare notes on keeping a model away from your credentials, write to me at [3h4x@datacrash.io](mailto:3h4x@datacrash.io).
