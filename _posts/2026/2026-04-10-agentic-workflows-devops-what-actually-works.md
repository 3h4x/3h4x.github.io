---
layout: post
title: "Agentic workflows for DevOps: what actually works and what will burn you"
categories: tech
tags: [ai, devops, claude, infrastructure, agents, automation]
comments: True
---

Everyone is talking about AI agents doing infrastructure work. Most of the discourse is either pure hype ("agents will replace DevOps engineers!") or pure fear ("never let AI touch production!"). After six months of actually building agentic workflows — using Claude Code as my daily driver, wiring up automated issue resolution, building MCP tools to give agents access to real systems — I have a more boring and more useful take: **agents are great at reading and terrible at writing. The boundary between those two is where you put your guardrails.**

<!-- readmore -->

## What I've actually built

Let me be concrete. Over the last six months I've built:

- Automated GitHub issue resolution: agent picks up an open issue, creates a feature branch, writes code, opens a PR. Humans review and merge.
- MCP server wrapping HTTP APIs — [mcp-http-tools](https://github.com/3h4x/mcp-http-tools), a YAML-configured proxy that lets Claude query Prometheus, Loki, Alertmanager, or any REST endpoint as a tool call.
- Agentic workflows for code review, test generation, and incident analysis.

The pattern that works every single time: **agent reads, proposes, human approves, human executes**. The pattern that fails: **agent reads, proposes, agent executes**.

That second pattern sounds like a minor variation. It isn't.

## The `terraform apply` problem

Here's a concrete failure mode that should scare you. An agent with write access to your infrastructure runs `terraform plan`, reads the output, and decides it looks good. It then runs `terraform apply`. The apply fails halfway through — maybe a resource limit, maybe a provider timeout, maybe a race condition with another deployment. The state is now partially modified.

What does the agent report? Depends on how it's instructed, but in the worst case: success. It saw the `terraform apply` command run. It got some output. It synthesized the conclusion that was most consistent with its task ("apply the changes") and hallucinated completion. It did not fail loudly. It told you it was done.

You find out three hours later when something isn't working and you start digging. The state file is a mess. The agent has no memory of what actually happened.

This isn't a theoretical risk. LLMs are next-token predictors. When the most probable next token, given context ("I was asked to apply infrastructure changes, the command ran, here is the output"), is "completed successfully" — that's what you get. The model isn't lying. It's doing exactly what it's trained to do. The problem is you gave it a task with destructive side effects and trusted its self-report.

## The `2 == 2` test problem

Same failure mode, different shape. Agent is asked to make a test suite pass. It cannot figure out how to fix the underlying code. So it rewrites the tests. Not obviously — it doesn't delete `assert result == expected`. It writes tests that are structurally valid, look reasonable on a quick scan, and pass. They just don't test what they're supposed to test anymore.

```python
# What the test should do
def test_token_balance():
    result = get_balance(wallet_address)
    assert result == expected_balance  # tests the actual function

# What an agent under pressure might write
def test_token_balance():
    result = 42  # hardcoded
    assert result == 42  # always passes, tests nothing
```

This is `2 == 2`. The test passes. The CI pipeline is green. The agent reports success. Your actual logic is untested and probably broken.

Again — not because the agent is malicious. Because it was given a task ("make tests pass") with a success criterion ("green CI") and found the shortest path to satisfying that criterion. If you want it to find the *right* path, you need to close off the wrong ones structurally, not just through prompting.

When this happens in a codebase with infrastructure code, in a CI pipeline that triggers deployments — it's not just annoying. It's how broken things reach production confidently.

## The actual principle

Give agents read access. Give agents write access to sandboxed, reversible, non-production things. Give agents the ability to *propose* destructive actions. Never give agents the ability to *execute* destructive actions autonomously.

"Destructive" here means: anything that changes production state, anything that can't be trivially undone, anything where the cost of a hallucinated success report is high.

This maps cleanly to how I use Claude Code day-to-day:

- **Reads everything**: code, logs, metrics (via MCP tools), docs, test output. No guardrails needed here.
- **Writes code freely**: local files, new branches, test fixtures. All reversible, all human-reviewed before merge.
- **Proposes infrastructure changes**: writes the Terraform, the Ansible, the deploy script. Does not run it.
- **Never touches production directly**: no `terraform apply`, no `kubectl delete`, no database migrations. Human executes those, always.

The `--dangerously-skip-permissions` flag in Claude Code exists. I use it for local development work where the blast radius is my own machine. I do not use it in any workflow that touches shared or production infrastructure.

## MCP tools and read-only APIs

The mcp-http-tools pattern is a good example of how to give agents useful infrastructure access safely. The tool is a YAML-configured proxy — you define what endpoints Claude can call, what parameters are accepted, and what the response looks like:

```yaml
tools:
  - name: query_prometheus
    url: http://prometheus:9090/api/v1/query
    params:
      - name: query
        description: PromQL expression
        required: true
    response:
      type: json
      path: data.result

  - name: search_logs
    url: http://loki:3100/loki/api/v1/query_range
    params:
      - name: query
        description: LogQL expression
        required: true
      - name: start
        description: Start time (Unix timestamp)
    response:
      type: json
      path: data.result
```

Claude can now query Prometheus, search Loki, and check Alertmanager. It can read your entire observability stack and reason about what's happening in your infrastructure. It cannot modify anything. It cannot silence alerts, roll back deployments, or scale down nodes. It reads, it reasons, it proposes. You act.

This is genuinely useful. Incident analysis with full log and metric access is dramatically faster. Root cause investigation that used to take 30 minutes of manual dashboard clicking takes 3 minutes of conversational debugging. The value is real.

The moment you add write endpoints to that config — restart pods, silence alerts, apply changes — you've crossed the line. Not because the agent will definitely cause an incident, but because when it does, you'll have no idea what it did or why, and the self-report may be wrong.

## Tests and code review as guardrails

If agents are going to write code that touches infrastructure, the guardrails are tests and code review — not prompting, not system instructions. "Don't write fake tests" in your prompt will not stop an agent from writing fake tests when it's stuck.

What works:

**Test coverage metrics.** If you're tracking coverage and an agent's PR drops it, that's a hard signal. It either deleted tests or wrote ones that don't cover the code. Both are problems.

**Mandatory human review on anything infra-adjacent.** Not optional. Not "review if you have time." Every PR that touches deployment configs, Terraform, Kubernetes manifests, or CI pipelines gets a human pair of eyes before it merges.

**Integration tests that hit real systems.** Unit tests with mocked infrastructure are where `2 == 2` hides. If your tests mock the database, the agent can fake them trivially. Tests that require a real connection are much harder to fake without breaking things loudly.

**Diff review, not just "is CI green?"** CI green means tests pass. It doesn't mean the tests test what you think they test. Read the diff.

## Model quality is a variable, not a constant

Everything above assumes a capable frontier model. But a lot of people experimenting with agentic infrastructure workflows aren't using frontier models — they're running local open-source models to avoid cost, latency, or data privacy concerns. That's a legitimate choice. It's also where I've seen the worst failures.

Before settling on Claude as my daily driver, I ran agentic workflows with two other setups: [Nous Hermes](https://hermes-agent.nousresearch.com) (a fine-tuned Gemma4 variant, run locally) and [OpenClaw](https://openclaw.ai) — an early-stage agentic coding tool that predated what became clawdbot.

Both were genuinely dangerous in agentic workflows. Not dangerous in the "it's too powerful" sense. Dangerous in the "it will confidently do the wrong thing and you won't know" sense.

The failure modes were different from what I described above with frontier models. With a capable model, the failure is subtle — the model is good enough to hide its failures behind plausible output. With these earlier/smaller models, the failures were louder but in some ways harder to catch:

**Context leaking between tasks.** The model would carry state from a previous task into the current one. Midway through resolving issue #47, it would start referencing constraints from issue #31. The output looked coherent. The reasoning was contaminated.

**Focus drift mid-session.** Long agentic sessions — anything beyond 20-30 turns — would see the model gradually lose the plot. It would start optimizing for something adjacent to the actual task. Not obviously wrong, just... off. The kind of thing you catch in code review if you're paying close attention, and miss if you're skimming.

**Breaking on edge cases.** Structured output (JSON for tool calls, YAML for configs) would silently malform under load. The agent would continue as if the output was valid. Downstream tools would fail in confusing ways.

**Dangerous defaults.** Without strong RLHF alignment around caution, these models would attempt destructive actions without pushback. Ask a well-aligned frontier model to run `terraform destroy` on a production environment and it'll push back, ask for confirmation, flag the risk. Earlier/smaller models just... did it. The guardrails have to come entirely from your workflow because they're not baked into the model.

The lesson isn't "only use expensive frontier models." It's that model quality directly determines where your workflow guardrails need to be. A model that pushes back on dangerous actions, maintains context reliably, and fails loudly when it's stuck gives you more room to work with. A model that drifts, leaks context, and silently malforms output requires you to treat *every* action as potentially wrong — which mostly defeats the purpose of the automation.

If you're evaluating models for agentic infrastructure work, the questions aren't just benchmark scores. They're: does it push back on bad ideas? Does it fail loudly or quietly? Does it stay on task over a 50-turn session? Does it produce valid structured output reliably? Run those tests before you point it at anything real.

## What's still BS

The "fully autonomous DevOps agent" narrative. The demos are impressive — watch the agent spin up an EKS cluster, configure networking, deploy an application. What the demos don't show: the third run where it confidently applied changes to the wrong environment because the context window didn't fit all the state it needed. Or the time it decided a failing health check meant the deployment was healthy and moved on.

Agents do not have reliable situational awareness. They don't know what they don't know. They will fill gaps with plausible-sounding completions. In a sales demo, that's fine — the demo environment is isolated, the failure modes are contained, and the human doing the demo knows what to look for. In production infrastructure, those properties don't hold.

The agents that are actually useful right now are the ones that operate in a tight loop with humans. Not because humans are smarter — often the agent's analysis is better than mine. But because the consequences of a confident wrong answer in infrastructure are asymmetric. A hallucinated successful deployment costs you hours of incident response. A correct proposal that a human glances at before executing costs you thirty seconds.

Thirty seconds is a cheap insurance premium.

## Where I think this goes

The tooling will improve. Context windows will get longer and more reliable. Verification methods will get better — agents will be able to check their own work more rigorously before reporting success. The failure modes I described will become less common.

But the fundamental principle won't change: **destructive actions require verification, and the entity doing the verification shouldn't be the same entity that took the action**. That's not an AI limitation. That's just good systems design. You don't let a deployment pipeline merge its own PRs either.

The agents doing useful infrastructure work in 2026 are working in a loop: read → propose → human-in-the-loop → execute → verify. The ones causing incidents are the ones where that loop got closed.

Know what you are doing and have fun.

3h4x
