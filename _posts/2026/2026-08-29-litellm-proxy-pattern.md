---
layout: post
title:  "One door in front of every model you self-host"
categories: tech
tags: [litellm, self-hosted, llm-proxy, kubernetes, networkpolicy, mlops, infrastructure, security, supply-chain]
comments: True
---

Every project that self-hosts inference ends up with the same shape of mess. Someone ships a feature that needs a model, writes the shortest path that works — a plain HTTP call straight to whatever's serving it — and ships it. Six months later you've got four services each calling three different backends directly, with four different half-remembered auth conventions (one has a bearer token, one checks an IP allowlist that stopped being accurate two deploys ago, one has nothing because "it's internal"). Nobody planned this. It's just what happens when "call the model" is cheaper to write than "call the model through the thing that knows how to call models."

I hit this cleaning up an image-generation path that was still calling its backend directly with no auth at all — a leftover from before the underlying model got swapped out, when "internal-only" was still true. It wasn't true anymore. That's the fix I want to talk about: **put one proxy in front of everything, and make going around it the hard path instead of the easy one.**

<!-- readmore -->

## Why this keeps happening

Self-hosted inference — a local LLM, a diffusion or image-gen model, an OCR model, whatever you're running instead of paying an API per token — starts out as one service, one caller, no auth story needed because it's not reachable from anywhere that matters. Then it grows callers. Each new caller is a small PR that doesn't feel like it deserves an auth-architecture conversation, so it doesn't get one. The backend accumulates trust relationships nobody wrote down.

The fix people reach for first is "add an API key check to the backend." That's better than nothing, but it means every caller now needs to know the backend's specific auth scheme, and every backend swap (new model, new serving stack, new framework) means updating every caller. You've distributed a decision that should live in one place.

## LiteLLM as the chokepoint

[LiteLLM](https://github.com/BerriAI/litellm)'s proxy mode gives you an OpenAI-compatible interface in front of anything — hosted APIs, local text models, image-gen backends, whatever speaks HTTP. The point isn't the OpenAI-shaped API specifically; it's that **every caller now authenticates the same way, against the same thing, regardless of what's actually running behind it.**

```yaml
# litellm config.yaml — model aliasing decouples the caller-facing
# name from whatever's actually serving it this month
model_list:
  - model_name: token-logo
    litellm_params:
      model: openai/sana-1.6b        # today's backend
      api_base: http://image-gen-internal:8000/v1
      api_key: os.environ/BACKEND_KEY

general_settings:
  master_key: os.environ/LITELLM_API_KEY
```

Callers never see `sana-1.6b`, or whatever replaces it next quarter. They ask for `token-logo` and get a `Bearer` token checked once, in one place. Swap the backend, edit one YAML file, no caller changes.

Migrating a caller looks like this — nothing exotic, which is the point:

```js
const resp = await fetch(`${IMAGE_GEN_URL}/v1/images/generations`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...(LITELLM_API_KEY && { Authorization: `Bearer ${LITELLM_API_KEY}` }),
  },
  body: JSON.stringify({ model: IMAGE_GEN_MODEL, prompt }),
});

if (!resp.ok) {
  if (resp.status === 401 || resp.status === 403) {
    throw new Error(`image-gen auth failed (check LITELLM_API_KEY): ${resp.status}`);
  }
  throw new Error(`image-gen request failed: ${resp.status}`);
}
```

Small diff. The value isn't in this one call, it's that now every caller looks like this.

## Don't fold "configured" and "authenticated" into one flag

Here's the gotcha that actually cost me some thought. There were two orthogonal questions about this feature:

1. Is image generation configured at all? (Is `IMAGE_GEN_URL` set?)
2. Is *this* request authenticated? (Is `LITELLM_API_KEY` set and valid?)

It's tempting to collapse these into one "is the feature on" check. Don't — they answer different questions, and you need both answers separately. `IMAGE_GEN_URL` can legitimately point straight at a backend with no key needed at all (a documented rollback path, useful when the proxy itself is the thing that's broken). If you fold the key into the "is this feature enabled" gate, that gate starts lying the moment someone uses the keyless rollback: the feature *is* configured, correctly, and the gate says no.

Keep the gates separate: one flag answers "should the UI show this button / should the worker dequeue this job," a second, independent check answers "does this specific outbound call need a header." Neither one should infer the other.

## Fail open where you have a fallback, fail closed where you don't

The other asymmetry worth being deliberate about: not every call behind the proxy deserves the same failure behavior on a bad or missing token.

- A background enrichment step that has a reasonable fallback (skip the enrichment, ship the plain version) can fail *open* — log it, move on, don't block the user on an internal auth hiccup.
- A user-triggered action with no fallback (they clicked "generate," there's nothing to silently degrade to) should fail *closed* and say so clearly. A generic 500 here just means someone spends twenty minutes rediscovering that the key env var wasn't set in this environment. A named error — "check `LITELLM_API_KEY`" — turns a debugging session into a `kubectl get secret` check.

Neither is more "correct" in the abstract. The rule is: does this call have somewhere safe to degrade to? If yes, log and continue. If no, fail loud and specific.

## The auth header is a courtesy until the network agrees

A bearer token check on the proxy stops accidental direct callers — the ones who didn't know better. It does nothing about a compromised pod on the same network deciding to skip the proxy and hit the backend directly, because the backend still has an open listener. The header is a policy statement; enforcing it against a hostile actor already inside your cluster needs the network to back it up.

That's a `NetworkPolicy`, scoped so the backend pod only accepts ingress from the proxy:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: image-gen-ingress
  namespace: inference
spec:
  podSelector:
    matchLabels:
      app: image-gen-backend
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: litellm-proxy
      ports:
        - port: 8000
```

Once this is live, every legitimate caller has to go through the proxy, full stop — including any keyless rollback path you documented earlier. Sequencing matters here: land the policy *after* you've confirmed every real caller is already going through the proxy, or you'll spend an afternoon debugging a rollback runbook that quietly stopped being reachable months ago. Grep your fleet for direct references to the backend's internal address before you lock the door; a rollback rung nobody can reach is worse than no rollback rung, because it still reads as one in the runbook.

## The category is thinning out, and the survivor got popped

Worth being honest about the state of this market before you bet a rollout on it. Two direct category-mates didn't make it to the second half of 2026:

- **TensorZero** — an open-source LLMOps stack covering gateway, observability, evaluation, optimization and experimentation in one system — archived its GitHub repo on June 12, 2026. No acquirer, no pivot: the founders returned unused capital to investors and shut it down. The category it was betting on got squeezed from both sides — commoditized by the hyperscalers, rolled up by analytics platforms — before it found a commercial footing.
- **Helicone** — one of the more established LLM observability/proxy tools, 16,000+ organizations, 14.2 trillion tokens processed — was acquired by Mintlify on March 3, 2026. The acquirer's own messaging is direct about what that means: active feature development has ended, and what's left is security patches, bug fixes, and new-model support. Services stay live "for the foreseeable future," no roadmap, no shutdown date. That's not dead in the outage sense. It's dead in the sense that matters for a bet you're making today.

And LiteLLM itself isn't a clean pick either. In March 2026, malicious versions (`1.82.7`, `1.82.8`) sat on PyPI for roughly 40 minutes — long enough. The attacker, TeamPCP, didn't hit LiteLLM directly: they compromised the **Trivy security scanner** first, via an automation token that had been "rotated" but stayed functionally live for a 20-day window, and rode Trivy's legitimate CI access straight into LiteLLM's release pipeline to steal PyPI publishing credentials. The payload chained credential harvesting, lateral movement across Kubernetes clusters, and a persistent systemd backdoor. Reported blast radius: 2,500+ organizations, 430,000+ CI/CD pipelines.

If that playbook sounds familiar, it should — it's the same shape as the Checkmarx/KICS breach I wrote up back in April: poison the *scanner* your CI already trusts, then ride its access into the thing you actually care about. Same attacker group, third confirmed target this year. The lesson from that post applies here without modification: pin the LiteLLM image or package to a digest or known-good version, don't float on `latest` or a bare version tag, and don't assume "it's the security tooling, it must be locked down" — the tooling is exactly what's been getting hit.

None of this changes the architecture argument above — a chokepoint you can audit and lock down beats N direct callers regardless of which proxy sits in that slot. It does mean "which proxy" is a decision to keep revisiting, not one to make once and forget, and that pinning the proxy itself isn't optional just because it's the thing enforcing your security posture.

## When not to bother

- **One backend, one caller.** You don't need a proxy in front of a thing only one service ever talks to. Add the auth check directly and move on.
- **You're not going to add a second backend or a second caller.** The whole value is in decoupling N callers from M backends. If N and M are both permanently 1, this is ceremony.
- **You don't control the network layer.** The auth header still helps against accidental misuse, but if you can't eventually add the NetworkPolicy (or your equivalent — security groups, service mesh authz), you're only getting half the pattern. Still worth doing, just know which half you're skipping.

Where I've landed: the proxy is worth standing up the moment you have more than one caller or you can see a second backend coming, because retrofitting it later means touching every caller at once instead of one at a time. The NetworkPolicy is the part that actually matters for the "no one can go around this" property — the header alone is just manners.

Know what you are doing and have fun!

3h4x

Sources:
- [LiteLLM Proxy Server docs](https://docs.litellm.ai/docs/proxy/quick_start)
- [LiteLLM model alias / `litellm_params` config reference](https://docs.litellm.ai/docs/proxy/configs)
- [Kubernetes NetworkPolicy docs](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [LiteLLM: Security Update — Suspected Supply Chain Incident (official, March 2026)](https://docs.litellm.ai/blog/security-update-march-2026)
- [Over 2,500 Organizations Impacted by LiteLLM Supply Chain Attack — SecurityWeek](https://www.securityweek.com/over-2500-organizations-impacted-by-litellm-supply-chain-attack/)
- [Shedding The Lite: the LiteLLM Compromise — Cycode](https://cycode.com/blog/lite-llm-supply-chain-attack/)
- [How a Poisoned Security Scanner Became the Key to Backdooring LiteLLM — Snyk](https://snyk.io/blog/poisoned-security-scanner-backdooring-litellm/)
- [TensorZero Shuts Down: What OSS LLMOps Can't Survive — byteiota](https://byteiota.com/tensorzero-shuts-down-what-oss-llmops-cant-survive/)
- [What the Helicone acquisition tells us about LLM observability in 2026 — AgentPing](https://agentping.io/blog/helicone-acquisition-what-it-means)
