---
layout: post
title: "Bedrock in 2026: where AWS owns your agents, and where the open protocols save you"
categories: tech
tags: [aws, bedrock, agentcore, ai-agents, mcp, a2a, guardrails, governance, observability, lock-in, cedar, devops, infrastructure]
comments: True
---

I took six months off the infra treadmill to live inside the agentic stack — Claude Code as a daily driver, building automated issue-resolution workflows, reading MCP and A2A specs at 1am like they were RFCs. Then I came back to AWS and realized Bedrock isn't "a model API behind IAM" anymore. Somewhere between re:Invent 2024 and re:Invent 2025 it quietly turned into a full agent platform, and nobody on my old DevOps channels seemed to have clocked how much of it is a **one-way door**.

So I did what I always do: I stood up the thing, read the control-plane APIs, and asked the only question an infra person should ask about a managed platform — *what's portable, and what am I never getting back out?*

<!-- readmore -->

## What "Bedrock AI" even means now

Two years ago Bedrock was: pick a model, call `InvokeModel`, pay per token. That part still exists and it's fine. The new surface area is everything wrapped around it:

- **Guardrails** — content filters and PII redaction (GA since 2024), plus the interesting one: Automated Reasoning checks, GA since August 2025.
- **AgentCore** — went GA on 13 October 2025. This is the actual platform: a managed **Runtime**, a **Gateway** (MCP), **Memory**, **Identity**, **Observability**, plus Code Interpreter and a headless Browser. Then in December 2025 they bolted on **Policy** and **Evaluations** (both still preview as I write this).

The mental model that helped me: Bedrock is now AWS's answer to "I have an agent that works on my laptop, how do I run it in production without rebuilding identity, memory, tool plumbing, and audit from scratch." That's a real problem. The question is the price — and I don't mean dollars.

## The Gateway is the genuinely good part

The thing every agent project hits is the M×N problem: N agents, M tools, and you end up hand-writing MCP servers and auth for every pair. AgentCore Gateway is a managed MCP server that turns your existing Lambdas, OpenAPI specs, and Smithy models into MCP tools with zero tool-server code.

Spin one up (inbound auth via your OIDC provider — Cognito, Okta, Auth0, whatever):

```python
import boto3

gw = boto3.client("bedrock-agentcore-control")

auth_config = {
    "customJWTAuthorizer": {
        "allowedClients": ["<cognito_client_id>"],
        "discoveryUrl": "<oidc_discovery_url>",
    }
}

gateway = gw.create_gateway(
    name="my-tools",
    roleArn="<gateway_iam_role>",
    protocolType="MCP",
    authorizerType="CUSTOM_JWT",
    authorizerConfiguration=auth_config,
    exceptionLevel="DEBUG",   # granular tool errors during bring-up
)
```

Then point a target at an existing Lambda — note you describe the tool schema inline, and outbound auth to the Lambda is just IAM, the same IAM you already write:

```python
lambda_target = {
    "mcp": {
        "lambda": {
            "lambdaArn": "<your_lambda_arn>",
            "toolSchema": {
                "inlinePayload": [{
                    "name": "get_order",
                    "description": "Fetch an order by id",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"orderId": {"type": "string"}},
                        "required": ["orderId"],
                    },
                }]
            },
        }
    }
}

gw.create_gateway_target(
    gatewayIdentifier=gateway["gatewayId"],
    name="orders",
    targetConfiguration=lambda_target,
    credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
)
```

Here's the part I actually like, and it's the part that's *portable*: the agent side speaks plain MCP. Your framework doesn't know or care it's talking to a Gateway. Strands, LangGraph, CrewAI, LlamaIndex — all of them just see a streamable-HTTP MCP endpoint:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "my-tools": {
        "url": gateway_endpoint,
        "transport": "streamable_http",
        "headers": {"Authorization": f"Bearer {jwt}"},
    }
})
```

If you decide to rip the Gateway out and run your own MCP server on a box you control next month, your agent code doesn't change. **That's the whole value of building on an open protocol instead of a proprietary SDK.** AWS gets this right here — they bet on MCP and A2A instead of inventing a Bedrock-only tool format. The semantic tool-search feature (`x_amz_bedrock_agentcore_search`, so your agent doesn't drown in 400 tool definitions) is AWS-flavored, but it's an *optional* MCP tool, not a fork of the protocol.

A2A is the same story: AgentCore Runtime added Agent-to-Agent protocol support in November 2025, with broader coverage rolling across the other services. Again — open spec, so a remote agent on your infra and an agent on Runtime can talk without an AWS-specific shim.

## Guardrails + Automated Reasoning: the AWS-only thing worth paying for

Most "guardrails" products are a regex and a vibe. The piece that's genuinely hard to replicate yourself is **Automated Reasoning checks** — formal verification of model output against policies you write in natural language, which AWS compiles into logic rules. AWS quotes up to 99% accuracy at confirming whether a response actually satisfies your stated policy. That's not a content filter, that's a soundness check, and rolling your own SMT-backed version is a PhD, not a sprint.

```python
brt = boto3.client("bedrock-runtime")

resp = brt.converse(
    modelId="us.anthropic.claude-...",   # swap freely (Bedrock wants the inference-profile id)
    guardrailConfig={
        "guardrailIdentifier": "<id>",
        "guardrailVersion": "DRAFT",
    },
    messages=[{"role": "user", "content": [{"text": user_input}]}],
)
```

The catch, and it's the recurring catch with all of this: the `guardrailIdentifier` is a Bedrock resource. The policy enforcement is a Bedrock API. The moment Guardrails sits in your request path, you are calling Bedrock — your portable MCP tools don't help you here.

## Governance and audit: this is where AWS is actually strong

Credit where due. If your problem is "compliance wants to know which agent did what, when, and why it was allowed," AWS has the better story than anything in open source right now, because they already had the boring plumbing:

- **Policy** (preview, Dec 2025) intercepts *every* tool call through the Gateway and evaluates it against rules written in natural language that compile to **Cedar** — AWS's policy language. Every decision is logged: what was allowed, what was blocked, and why. That's an audit trail you didn't have to build.
- **Evaluations** (preview) gives you 13 built-in scorers (helpfulness, tool selection, accuracy…) plus custom model-based ones, so "is the agent regressing" becomes a dashboard instead of a gut feeling.
- **Model Invocation Logging** ships full request/response to CloudWatch Logs or S3, and blocked Guardrails content shows up in plain text there.
- **CloudTrail** captures management and data events for request-level forensics.

Cedar is the redeeming detail: it's open source. So the *policy language* you write your governance in isn't trapped — even if the engine that enforces it is. That's the kind of seam I look for.

## Where AWS isn't, and you reach for open source: lineage

Here's the gap nobody markets. AWS gives you **observability** (CloudWatch metrics, OpenTelemetry-compatible traces — genuinely good, plug it into Datadog or Grafana and move on) and **audit** (CloudTrail, invocation logs). What it does *not* give you is **data lineage** for agent decisions: this output was produced from these retrieved documents, via these tool calls, under this model version and this prompt revision — as a queryable graph, not a pile of logs you grep at incident time.

If you need that — and in a regulated shop you will — you're wiring it yourself. What I'd reach for:

- **OpenLineage + Marquez** to model the agent run as a lineage DAG (run → inputs → tools → outputs).
- **OpenTelemetry** as the transport off AgentCore Observability, fanning out to your own backend so you're not locked to CloudWatch retention/format.
- Prompt and model-version pinning tracked in *your* git/DB, because Bedrock's logs tell you *what* was called, not *which revision of your intent* called it.

I'll publish the OpenLineage emitter from the PoC in a follow-up, once it's cleaned up enough to be worth copying.

The other holes, for completeness: cross-cloud agent identity (AgentCore Identity is great inside AWS; the second you have agents on your own infra and on AWS you're back to SPIFFE/SPIRE territory), and agent-native payments — there is no x402 story in Bedrock, so micropayment-metered tools stay your problem.

## The honest lock-in map

| Layer | Portable? | Reality |
|---|---|---|
| Models | Yes | Swap model IDs; this was always the easy part |
| Tool protocol (MCP) | Yes | Open spec — your agent code survives leaving Gateway |
| Agent-to-agent (A2A) | Yes | Open spec, same deal |
| Agent framework | Yes | Strands/LangGraph/CrewAI/LlamaIndex all run elsewhere |
| Policy *language* (Cedar) | Yes | Open source; the rules move even if the engine doesn't |
| Guardrails / Automated Reasoning | **No** | Bedrock API in your hot path |
| AgentCore Memory | **No** | Proprietary service, proprietary semantics |
| AgentCore Identity vault | **No** | Token vault + identity-aware authz is AWS-shaped |
| Runtime + Gateway control plane | **Mostly no** | `bedrock-agentcore-control` is the moat; the data plane is MCP, the management isn't |
| Lineage | **N/A** | AWS doesn't offer it — you own this regardless |

The pattern: **AWS bet on open protocols for the data plane and kept the control plane proprietary.** Smart, and honestly the right call for everyone — your agents and tools stay portable, while the managed runtime, memory, identity, and policy enforcement are the sticky bits you'd pay to not build. Just go in with your eyes open about which is which.

## When NOT to use this

- **You have one agent and three tools.** AgentCore is enterprise plumbing. Run an MCP server on a box, point your agent at it, done. Don't buy a managed control plane to dodge writing 40 lines.
- **You're multi-cloud or self-host-first** (hi, that's me). Memory and Identity will fight you. Use the open layers — MCP, A2A, Cedar, OTel — and skip the managed services, or you're paying the AWS tax to re-export everything.
- **Your moat is the agent runtime itself.** If *how* your agents execute is the product, don't hand the runtime to a vendor whose roadmap you don't control. Half of what I listed above was still "preview" in December — building your compliance story on a preview API is a choice.
- **You just need a chatbot with a content filter.** Guardrails alone, no AgentCore. You're done by lunch.

Where I've landed: I'll happily use the *open* layers AWS leaned into — they made MCP and A2A first-class, and that's a real gift. Guardrails with Automated Reasoning is worth the lock-in if you're in a regulated flow, because the alternative is building formal verification yourself. Everything else I'd treat as a convenience I can walk away from, and I'd architect so I actually can.

Know what you are doing and have fun!

3h4x

Sources:
- [Amazon Bedrock AgentCore is now generally available (13 Oct 2025) — AWS](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/)
- [AgentCore adds Policy and Evaluations (preview), Dec 2025 — AWS](https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-bedrock-agentcore-policy-evaluations-preview/)
- [Automated Reasoning checks now GA in Bedrock Guardrails (Aug 2025) — AWS](https://aws.amazon.com/about-aws/whats-new/2025/08/automated-reasoning-checks-amazon-bedrock-guardrails/)
- [Agent-to-agent (A2A) protocol support in AgentCore Runtime (Nov 2025) — AWS](https://aws.amazon.com/blogs/machine-learning/introducing-agent-to-agent-protocol-support-in-amazon-bedrock-agentcore-runtime/)
- [Search gateway tools with natural language — `x_amz_bedrock_agentcore_search` (AWS docs)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-semantic-search.html)
- [`create_gateway_target` — boto3 bedrock-agentcore-control](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agentcore-control/client/create_gateway_target.html)
- [Cedar — open-source policy language](https://www.cedarpolicy.com/)
