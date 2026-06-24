---
layout: post
title: "Cedar vs OPA: which policy engine, where it fits, and who owns you afterward"
categories: tech
tags: [cedar, opa, rego, authorization, policy-as-code, aws, cncf, kubernetes, governance, lock-in, devops, infrastructure, security]
comments: True
---

In the [Bedrock lock-in post](/tech/2026/06/13/bedrock-agentcore-lock-in.html) I called Cedar "the redeeming detail" — the one layer of AWS's agent stack whose *language* you keep even when the engine enforcing it is proprietary. A few people pushed back: why reach for Cedar at all when OPA has been the policy-as-code default for years and runs in basically every Kubernetes cluster on earth?

Fair. So I did the usual: stood both up, wrote the same authorization policy in each, ran them, and read enough of the internals to answer the only three questions that matter for an infra decision — *where does each one actually fit, how fast is it, and what am I signing up to never get back out of?*

<!-- readmore -->

## The split is bigger than "two policy languages"

The first thing that trips people up: Cedar and OPA are not the same *kind* of thing, and comparing them like-for-like hides the real decision.

- **OPA** is a general-purpose **policy engine**. You feed it arbitrary JSON (`input`), it evaluates Rego, it returns a decision document. It does not care whether that JSON is a Kubernetes admission request, a Terraform plan, an HTTP API call, or a CI gate. It's a daemon you run — sidecar, host-level, or library — and you ask it questions over a network or FFI boundary.
- **Cedar** is a domain-specific **authorization language plus a library**. It models exactly one thing: *can this **principal** do this **action** on this **resource** in this **context**?* (PARC). You embed the Rust/JVM/WASM library in-process and call `is_authorized()` as a function.

So the honest framing isn't "Cedar vs OPA," it's "a focused in-process authz library vs a general policy-evaluation service." That difference drives everything below.

## The same policy, in both

Here's a tiny but realistic rule set: owners can do anything to their document, anyone can view a public document, and suspended users get nothing — ever.

Cedar:

```cedar
// owners get full access to their own docs
permit (
    principal,
    action,
    resource
) when {
    resource.owner == principal
};

// anyone may view a public doc
permit (
    principal,
    action == Action::"view",
    resource
) when {
    resource.public == true
};

// suspended users get nothing — forbid always wins
forbid (
    principal in Group::"suspended",
    action,
    resource
);
```

The same intent in Rego:

```rego
package authz
# OPA 1.0+ — if/contains/in are built in, no `import rego.v1` needed

default allow := false

allow if {
    not is_suspended
    can_access
}

is_suspended if "suspended" in input.user.groups

can_access if input.resource.owner == input.user.id
can_access if {
    input.action == "view"
    input.resource.public == true
}
```

And running them — same request, a suspended user trying to view a public doc — both correctly say no:

```bash
# OPA  (-f raw to print the bare value instead of the JSON result envelope)
$ opa eval -f raw -d authz.rego -i input.json 'data.authz.allow'
# => false        (is_suspended short-circuits the allow rule)

# Cedar
$ cedar authorize --policies policy.cedar --entities entities.json \
    --principal 'User::"alice"' --action 'Action::"view"' --resource 'Document::"q3"'
# => DENY         (the forbid wins over both permits)
```

Look at what the `forbid` block buys you. In Cedar, **deny overrides allow** is a language guarantee — that `forbid` cannot be out-prioritized by any `permit`, no matter how the policy set grows. In Rego there's no built-in precedence; I had to thread `not is_suspended` into the allow rule myself. That's not a knock on Rego — it's the direct consequence of generality. Rego doesn't know it's doing authorization, so *you* own conflict resolution. Cedar knows, so it ships the resolution semantics for free. Multiply that across fifty policies written by five teams and the difference stops being cosmetic.

## Cedar's real superpower: you can prove things about your policies

This is the part that made me sit up — I fed the analyzer two versions of a policy set expecting "probably equivalent" and got back a concrete counterexample input instead of a shrug. It's why I'd trust Cedar in a regulated flow over hand-rolled Rego.

Because Cedar deliberately is **not** Turing-complete — no unbounded loops, no arbitrary recursion, a constrained type system with a schema — its policies are *analyzable*. In June 2025 AWS open-sourced [Cedar Analysis](https://aws.amazon.com/blogs/opensource/introducing-cedar-analysis-open-source-tools-for-verifying-authorization-policies/): a symbolic compiler that translates Cedar policies into SMT-lib and hands them to an SMT solver. The compiler itself is written and *proven correct* in Lean (the proof assistant). The encoding is sound, complete, and decidable.

In plain terms, you can ask questions like:

- "Are these two versions of my policy set equivalent?" (refactor with confidence)
- "Is there *any* principal outside the admins group who can ever reach this resource?" (prove the absence of a hole)
- "Does this new policy grant strictly more than the old one?" (catch privilege creep in code review)

And get a mathematical answer that holds for **all possible inputs**, not "the 200 test cases I remembered to write." You cannot do this with Rego. Rego's generality is exactly what makes it un-analyzable in this way — once a language can express arbitrary computation, "does any input reach this branch" becomes undecidable. Pick your trade: expressiveness or provability. Cedar chose provability on purpose.

## Where OPA fits

OPA's generality isn't a weakness, it's the entire point — and there's a whole category where nothing else comes close:

- **Kubernetes admission control.** Via Gatekeeper, OPA is the de-facto way to enforce "no privileged containers," "images must come from our registry," "every namespace needs an owner label." This is OPA's home turf and Cedar isn't even in the conversation.
- **Infra/config validation.** Terraform plans, CI/CD gates, Docker configs, API gateway rules — anything that's JSON-in, decision-out. One engine, one language, across the whole platform.
- **Complex, multi-source logic.** When a decision needs to join data from three systems, do set math, and walk nested structures, Rego's expressiveness earns its keep.
- **You already run it.** If OPA is in your cluster, adding an authz use case to it is near-zero marginal ops. Don't add a second engine to save 40 lines.

How I hold it: **OPA is platform guardrails.** Broad surface, infra-shaped, "is this *thing* allowed to exist / happen."

## Where Cedar fits

- **In-app, fine-grained authorization.** The "can user U do action A on resource R" check that runs on every API request. PARC is exactly this shape, and the in-process library call is microseconds with no network hop.
- **ABAC/ReBAC at app scale.** Attribute- and relationship-based rules (`resource.owner == principal`, group hierarchies via `in`) are first-class and readable enough to put in front of an auditor.
- **You need to *prove* properties.** Regulated flows where "we tested it" isn't good enough and "we formally verified no cross-tenant access is reachable" is.
- **Multi-language footprint.** Same Cedar policies evaluate identically from Rust, Java, Python, or WASM in the browser — author once, enforce everywhere.

How I hold it: **Cedar is application authorization.** Narrow surface, request-shaped, "can this *actor* touch this *object*."

They overlap in the middle (both can gate an API call), but the centers of gravity are different enough that on most real systems you'd happily run *both* — OPA at the platform edge, Cedar in the app.

## Performance: ignore the headline multiplier

You'll see "Cedar is tens of times faster than Rego" thrown around. It's not invented — Cedar's own [peer-reviewed paper](https://arxiv.org/abs/2403.04651) clocks the authorizer at 42.8×–80.8× over Rego. But read it for what it is: the authors' own benchmark, comparing two different operations — Cedar evaluating a single local ABAC request versus Rego running Datalog-style queries over a document model. That's nearer to comparing a SQL point-lookup to a graph traversal than a fair head-to-head. Real signal, not a number to architect around.

What's actually true from poking both: both resolve a single decision fast enough that for most apps it's not your bottleneck. Cedar, being compiled Rust over a constrained language, is *predictable* — there's no policy you can write that explodes eval time, because the language won't let you. Rego is fast when written well and can get slow when written badly (deep iteration, big cross products), which is why OPA ships partial evaluation to pre-compute the static parts. The real difference isn't the average, it's the **tail**: Cedar's worst case is bounded by design; Rego's worst case is whatever you wrote.

If latency matters to you, the empiricist move is the same as always — benchmark *your* policy on *your* inputs. A half-hour with your real authz shape beats any vendor multiplier.

## The lock-in question — the reason I started this

This is what I actually care about, and it's where the two diverge most.

**Cedar:** Apache-2.0, the language spec is open, the reference engine is open, and now the verification tooling is open too. AWS uses it inside Amazon Verified Permissions and Bedrock AgentCore Policy — but the policies you write are *not* AWS artifacts. You can run the exact same Cedar engine on a box you control, embed it in your own service, or evaluate it in a browser. As I said about Bedrock: the managed *engine* can be a one-way door while the *language* is a wide-open one. If you write your authz in Cedar via AVP and later want out, your policies come with you and you swap `is_authorized()` implementations. That's a seam, not a wall.

**OPA:** CNCF-graduated, Apache-2.0, genuinely vendor-neutral at the project level. But 2025 added an asterisk worth knowing. In August 2025 Apple [acquihired the OPA/Styra core team](https://www.osohq.com/post/opa-maintainers-join-apple-oss-community-to-maintain-styra-products) — the three original creators and much of the team — and Styra's commercial product (Styra DAS / Enterprise OPA) is being wound down. The nuance matters: **the OPA project is fine.** CNCF still owns governance, the maintainer list is intact, and Apple is actually *open-sourcing* previously-commercial pieces (EOPA, SDKs, the Regal linter). So this isn't lock-in in the AWS sense — nobody can take Rego away from you. It's a different risk: if you were paying Styra for the enterprise management plane, that roadmap just changed owners, and "the commercial backer got absorbed into a hyperscaler" is exactly the kind of thing an infra person should clock before standing the paid tier up.

So the lock-in scorecard:

| | Cedar | OPA |
|---|---|---|
| Language open? | Yes (Apache-2.0) | Yes (Apache-2.0) |
| Engine open / self-hostable? | Yes — embed anywhere | Yes — daemon or library |
| Verification tooling open? | Yes (Cedar Analysis, June 2025) | N/A — not analyzable |
| Governance | AWS-led, open spec | CNCF-graduated, vendor-neutral |
| The asterisk | Managed *engines* (AVP/AgentCore) are proprietary; the policies aren't | Project healthy; commercial backer (Styra) absorbed by Apple, paid tier sunsetting |
| Walk-away cost | Low — policies + swap engine | Low for OSS OPA; re-plan if you bought Styra |

Both score well on the thing that actually matters: **your policies are portable in either.** The difference is *which* surrounding piece carries the risk — for Cedar it's the managed enforcement plane, for OPA it's the (now orphaned) commercial management plane.

## When NOT to use each

**Don't reach for Cedar when:**

- Your problem is platform guardrails (admission control, config validation). Cedar models PARC; it doesn't model "this Terraform plan is non-compliant." Wrong shape.
- You already run OPA and the new use case is just one more API authz check that fits your existing Rego cleanly. Two engines is ops you have to justify.
- You need to join arbitrary external data mid-decision in ways Cedar's entity model doesn't express. Rego will be less of a fight.

**Don't reach for OPA when:**

- You need to *prove* an authorization property, not test it. Rego can't give you that; Cedar can.
- It's pure in-app, per-request authz and you don't want a policy *service* in the hot path — embed Cedar and skip the network hop and the daemon to operate.
- Your team will hand-roll deny/allow precedence across dozens of policies. Cedar's built-in forbid-overrides-permit is one fewer footgun.

## tl;dr

Not really competitors. **OPA** is a general policy engine — Kubernetes admission control, infra/config validation, anything JSON-in/decision-out — and Rego's expressiveness is the point. **Cedar** is a focused, embeddable authorization library for per-request "can principal do action on resource," and because it's deliberately not Turing-complete you can *formally verify* it (Cedar Analysis, open-sourced June 2025, Lean-proven SMT compiler). On most systems you'd run both: OPA at the platform edge, Cedar in the app. Lock-in: both languages are Apache-2.0 and self-hostable, so your *policies* travel either way. The asterisks differ — Cedar's managed engines (AVP, AgentCore Policy) are proprietary while the language is open; OPA the project is healthy under CNCF, but Apple acquihired the Styra team in Aug 2025 and the commercial tier is sunsetting. Pick by *shape of the problem* first, ecosystem second, and benchmark your own policy instead of trusting any "Nx faster" headline.

Know what you are doing and have fun!

3h4x

Sources:
- [Introducing Cedar Analysis: Open Source Tools for Verifying Authorization Policies (16 Jun 2025) — AWS Open Source Blog](https://aws.amazon.com/blogs/opensource/introducing-cedar-analysis-open-source-tools-for-verifying-authorization-policies/)
- [Cedar: A New Language for Expressive, Fast, Safe, and Analyzable Authorization (PACMPL / arXiv)](https://arxiv.org/pdf/2403.04651)
- [How We Built Cedar: A Verification-Guided Approach (arXiv)](https://arxiv.org/html/2407.01688v1)
- [Cedar — open-source policy language](https://www.cedarpolicy.com/)
- [Open Policy Agent — docs](https://www.openpolicyagent.org/docs/latest/)
- [OPA maintainers join Apple; OSS community to maintain Styra products (Aug 2025) — Oso](https://www.osohq.com/post/opa-maintainers-join-apple-oss-community-to-maintain-styra-products)
- [Migrating from Open Policy Agent to Amazon Verified Permissions — AWS Security Blog](https://aws.amazon.com/blogs/security/migrating-from-open-policy-agent-to-amazon-verified-permissions/)
- [Benchmarking authorization policy engines (Rego, Cedar, OpenFGA) — Teleport](https://goteleport.com/blog/benchmarking-policy-languages/)
</content>
</invoke>
