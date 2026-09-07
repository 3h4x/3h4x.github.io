---
layout: post
title: "Fable 5.1 vs GPT-6 Astra: same $10/$50 price, and only one of them stayed quiet about its work"
categories: tech
tags: [ai, anthropic, claude, fable, openai, gpt, codex, benchmarks, claude-code, llm]
comments: True
---

Two frontier models shipped two days apart. Anthropic put out Claude Fable 5.1, successor to [the Fable 5 I benchmarked in June]({% post_url 2026/2026-06-10-claude-fable-5-benchmark %}), on September 1st; OpenAI answered with GPT-6 Astra on September 3rd. Same list price — $10 per million input tokens, $50 per million output — on both. That's rare enough to be the whole reason for this post: when the sticker price is identical, the interesting questions move to everything the sticker doesn't say. So I pointed a trimmed version of [June's trap suite]({% post_url 2026/2026-06-10-claude-fable-5-benchmark %}) at both, kept it small enough not to burn a real budget on it, and read the fine print on pricing while I was at it.

<!-- readmore -->

## What actually shipped

| | Claude Fable 5.1 | GPT-6 Astra |
|---|---|---|
| Model ID | `claude-fable-5-1` | `gpt-6-astra` |
| Released | 2026-09-01 | 2026-09-03 |
| Input / output | $10 / $50 per MTok | $10 / $50 per MTok |
| Cache read | **$0.25** per MTok | $1.00 per MTok |
| Cache write | ~$12.50–$20 per MTok (5m/1h ephemeral) | $12.50 per MTok |
| Context window | 1M tokens | 1.05M tokens |
| Max output | 128K tokens | 128K tokens |
| Default effort | `high` (adaptive) | configurable, `low`–`max` |
| Knowledge cutoff | Jun 2026 | Apr 2026 |
| Long-context surcharge | none published | **2x input/cache, 1.5x output for the whole request** past 272K input tokens (API only — OpenAI exempted Codex CLI from it) |

Identical headline price, 4x apart on cache reads. That's not a rounding difference — Fable 5.1's whole pitch this release is cache economics: Anthropic cut cache-read pricing 75% (from $1.00 to $0.25/MTok) and claims 25–45% lower real-world cost versus Fable 5 purely from that, with no other price change. GPT-6 Astra kept the standard 10%-of-input cache rate ($1.00) that's been OpenAI's norm. If your workload is agentic and cache-heavy — a coding agent rereading the same repo context turn after turn — that 4x gap compounds fast; a one-shot chat workload barely notices it.

The long-context line is worth a second look if you ever send genuinely large contexts to GPT-6 Astra directly: cross 272,000 input tokens and the *entire* request — not just the tokens past the line — gets rebilled at 2x input/cache and 1.5x output. Multiple independent trackers confirm the exact threshold. OpenAI has since exempted Codex CLI traffic from that surcharge specifically, so if you only ever touch GPT-6 Astra through Codex, you won't see it — hit it through the raw API past 272K tokens and you will.

One more fact that's context rather than a benchmark: GPT-6 Astra is, by OpenAI's own account, the first model to cross the "Critical" cybersecurity capability threshold in their Preparedness Framework, and it went through a formal pre-release review with the US federal government. That's not something this post's suite touches — it's cited here because it's part of what shipped, not to editorialize on it.

## What the vendors say — and what the referee says

Both companies published their usual pile of self-run benchmarks. Anthropic's numbers for Fable 5.1: 52.6% on Terminal-Bench-Science 0.1, 55.8% on Terminal-Bench 4.0, 60.9%/65.0% on Humanity's Last Exam without/with tools. OpenAI's for Astra: 98% on FrontierMath Tier 4, 99.9% on ARC-AGI-3, 100% on ExploitBench, and 57.9% on Terminal-Bench 4.0 — actually ahead of Fable 5.1 on that one shared benchmark.

Vendor numbers are vendor numbers, so the more interesting figure is Artificial Analysis's independent aggregate, which neither company controls: on their Intelligence Index, GPT-6 Astra scores **61** — tied with its own predecessor, GPT-5.6 Sol, and behind Fable 5.1's **66**. On their Coding Agent Index specifically (a blend of Deep SWE, Terminal-Bench, and repo Q&A), Fable 5.1 leads 70 to 67. So the model that wins the one benchmark both vendors chose to publish loses the broader independent aggregate to the model that didn't bother publishing it. That's the whole reason I don't stop at slide decks.

## The suite, trimmed on purpose

June's suite was 10 tasks × 3 runs × 2 models = 60 calls, same-vendor (Fable 5 vs Opus 4.8), all through `claude -p`. This time it's cross-provider, and the goal was a real but cheap read, not a repeat of that scale — so: **6 tasks, 2 runs, 2 models = 24 calls total.** I kept the six tasks that actually split the two models back in June — the merge-intervals bug fix, the adversarial IPv4 regex, the NULL-semantics SQL trap, strict-JSON output, the bat-and-ball trap, and exact-arithmetic rounding — and dropped the four every model already aced 3-for-3 (leftmost binary search, the water-jug puzzle, random-host Monty Hall, the mutable-default trace) — recycling June's own answer key rather than inventing new tasks. Full suite, graders included, is in the repo: [`scripts/2026-09-07-fable-5-1-vs-gpt-6-astra.py`](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-09-07-fable-5-1-vs-gpt-6-astra.py).

Cross-provider means the two CLIs aren't symmetric, and I'm not going to pretend otherwise:

- **Claude Fable 5.1** ran through `claude -p --tools "" --strict-mcp-config`, which hard-disables every tool — the call is a bare completion, structurally incapable of touching a file or running a command.
- **GPT-6 Astra** ran through `codex exec -s read-only`, OpenAI's own agent CLI. Codex has no equivalent "disable every tool" flag — the closest is a read-only sandbox plus asking it in the prompt not to use tools. It complied every time here, but the guarantee is weaker by construction, not by model behavior.

Both were pushed to `high` reasoning effort explicitly (`-c model_reasoning_effort="high"` for Astra), overriding this machine's own low-effort default for Codex, to match Fable 5.1's documented default of `high`. Testing at whatever each CLI happens to default to locally would've compared my config, not the models. One practical note for anyone trying to reproduce this: `gpt-6-astra` needs Codex CLI 0.153.4 or newer — 0.144.6 rejects the model ID outright with "requires a newer version of Codex."

## Results

Strict grading: exact string match, executed test suite, or all 16 adversarial regex cases — no partial credit.

| Task | Fable 5.1 | GPT-6 Astra |
|---|---|---|
| `bugfix_merge` | **2/2** | **2/2** |
| `regex_ipv4` | **2/2** | **2/2** |
| `sql_null_trap` | **2/2** | **2/2** |
| `json_strict` | **2/2** | **2/2** |
| `trap_batball` | **2/2** | **2/2** |
| `arith_exact` | 0/2 | **2/2** |
| **Total** | **10/12** | **12/12** |

GPT-6 Astra went clean. Fable 5.1 dropped both `arith_exact` runs — and only that task, which is worth digging into rather than just reporting.

## What failed and why

Both `arith_exact` misses are the exact same shape:

```text
run 1: 129.99 × 0.8 = 103.992
103.992 × 1.0825 = 112.571...

112.57
run 2: 129.99 × 0.8 = 103.992
103.992 × 1.0825 = 112.571...

103.992 × 1.0825: 103.992 + 103.992×0.0825 = 103.992 + 8.57934 = 112.57134

112.57
```

The prompt said "Reply with ONLY the number." Both responses show the arithmetic, then land on the correct `112.57` as the last line. Regrading leniently — the same method June used on Opus 4.8's leaked-reasoning failures, drop leading lines until something matches — Fable 5.1 goes 12/12, identical to Astra's strict score. So this isn't a math error; it's the model narrating a calculation into the one channel the prompt explicitly said not to use.

That's notable specifically because of what June found: **Fable 5, the previous generation, never did this** — across 30 calls it emitted zero characters beyond what was asked, while Opus 4.8 was the one that leaked deliberation into visible output. Fable 5.1 picked up the habit its own predecessor didn't have, on precisely the task category (multi-step exact arithmetic) where showing work is most tempting. Whether that's adaptive-thinking calibration drift between 5 and 5.1 or just this task's shape, I can't tell from 2 samples — but the pattern is identical to what cost Opus 4.8 points three months ago, and it's worth watching on the next release, not dismissing as noise.

One thing that *isn't* a story: on `trap_batball`, Fable 5.1 answered `10` cleanly in both runs, but burned 3 output tokens in run 1 and 46 in run 2 — with an identical final answer. That's thinking-budget variance staying inside the invisible channel, not leaking; I only mention it because it looks alarming in the raw log until you check what actually rendered.

## Speed and cost

| | Fable 5.1 | GPT-6 Astra |
|---|---|---|
| Correct (strict) | 10/12 | **12/12** |
| Median wall | **4.9s** | 9.2s |
| Mean wall | **6.6s** | 9.6s (one 18.7s outlier on Fable's side pulls its mean up; the median is the more honest number for both) |
| Total cost, 24 calls | **$0.07** | $0.58 |
| Total output tokens | 638 | 632 |
| Total input tokens | **4,990** | 337,718 |

Read that last row against the one above it: output tokens are within 1% of each other — 638 vs 632, across 12 calls each. **This is not a story about one model talking more.** The entire ~8x cost gap lives on the input side: 4,990 total input-side tokens for Fable 5.1 across the whole suite versus 337,718 for Astra, a ~68x difference, even though every call sends the same handful of short, self-contained prompts. That's a fixed CLI tax, not model verbosity: even with `--ignore-user-config`, a bare `codex exec` call still ships roughly 15–20K input tokens of agent scaffolding per call (about 12K of which OpenAI's own server-side cache absorbs, at $1/MTok instead of $10) — versus a couple hundred tokens for a `claude -p` call issued outside a project directory with `--tools ""`. Stack the 4x cache-read price gap from the facts table on top of that ~68x input-token gap and you get almost the entire cost difference; both totals are real dollars I actually spent, but they measure these two CLIs' fixed overhead at least as much as the models underneath them. Total spend for the full 24-call suite: **$0.65** — cheap enough that "don't burn tokens on this" was easy to honor.

## What this doesn't tell us

- **12 samples per model, not 30.** Two runs per task, six tasks — enough to catch a repeat like the `arith_exact` leak, not enough for error bars.
- **The tool-lockout is asymmetric.** `--tools ""` makes tool use structurally impossible for Fable 5.1; Codex has no equivalent, so Astra's clean run reflects instruction-following, not a hard guarantee. A prompt-injection-style test would need to account for that difference explicitly.
- **CLI overhead dominates the cost comparison**, as the section above says outright — 68x more input tokens per call, within 1% on output — so this measures `claude -p` against `codex exec`, not the two APIs, and not the two models' verbosity.
- **`high` effort was a choice, not a default.** I picked it to match Fable 5.1's documented default; Astra's actual local default here was `low`. A `low`-effort Astra run would likely be faster and cheaper, and might behave differently on the traps.
- **No agentic, multi-turn, or long-context tasks.** Both vendors are pitching long-horizon autonomous work as the headline use case this generation; six single-shot text tasks say nothing about a 200-turn session, and nothing here comes close to Astra's 272K-token surcharge line.
- **One day, two models, launch week.** Same caveat as every post in this series — serving behavior can shift as both providers tune things post-launch.

## My take

Same price tag, and the two models spend it differently. GPT-6 Astra went 12/12 clean on a suite it had never seen; Fable 5.1 went 10/12 strict, 12/12 lenient, with its only miss being narrated arithmetic on exactly the kind of task where June's Fable 5 stayed silent. If your pipeline parses output with code, that regression is real and worth a tighter system prompt or a strip-leading-lines pass until Anthropic tunes it back. If a human reads the output, nobody will ever notice — the number was right both times.

Where they actually separate, on this small a sample, isn't correctness — it's economics and speed, and even the economics gap turns out to be almost entirely a CLI-and-pricing story rather than a "one model talks more" story: output tokens landed within 1% of each other. Fable 5.1 answered in about half the median wall-clock time, and the ~8x cost gap is the 4x cache-read price difference stacked on top of a ~68x gap in per-call input tokens that has nothing to do with what either model chose to say. If you're running an agentic loop that rereads a lot of shared context — the exact workload Anthropic built the 75%-cheaper cache read for — that 4x cache-price gap is the number to actually budget against, not the $10/$50 headline both vendors are happy to let you compare instead. And if your context genuinely runs long and you're on GPT-6 Astra's raw API rather than Codex, check your requests against that 272K-token line before it doubles your bill on the whole call, not just the overage.

The independent aggregate — Fable 5.1 ahead on both Artificial Analysis indices, despite Astra winning the one benchmark both vendors chose to publish — is the detail I'd weight most if I had to pick one model site-unseen. But "site-unseen" is doing a lot of work in that sentence. Run your own workload through both before trusting either vendor's slide, or mine.

The harness is [`scripts/2026-09-07-fable-5-1-vs-gpt-6-astra.py`](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-09-07-fable-5-1-vs-gpt-6-astra.py) and the raw ndjson results are [next to it](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-09-07-fable-5-1-vs-gpt-6-astra-results.ndjson) — all 24 calls.

Know what you are doing and have fun!

3h4x

Sources:
- [Introducing Claude Fable 5.1 and Claude Mythos 5.1 — Anthropic](https://www.anthropic.com/claude-fable-and-mythos-5-1)
- [Claude models overview — pricing and specs table — Anthropic](https://platform.claude.com/docs/en/about-claude/models/overview)
- [Anthropic's Claude Fable 5.1 and Mythos 5.1 arrive with a 75% cost reduction for cache reads — VentureBeat](https://venturebeat.com/technology/anthropics-claude-fable-5-1-and-mythos-5-1-arrive-with-a-75-cost-reduction-for-fable-cache-reads)
- [GPT-6 Astra: A new generation of intelligence — OpenAI](https://openai.com/index/gpt-6-astra/)
- [OpenAI announces rollout of GPT-6 Astra model — CNBC](https://www.cnbc.com/2026/09/03/open-ai-astra-gpt-6-cyber.html)
- [GPT-6 Astra Model — OpenAI API docs](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [GPT-6 Astra — API Pricing & Benchmarks — OpenRouter](https://openrouter.ai/openai/gpt-6-astra)
- [GPT-6 Astra Codex Pricing Removes Long Context Penalties — Security Online](https://securityonline.info/gpt-6-astra-codex-pricing/)
- [GPT-6 Astra Benchmarks: Is It Really Better Than Fable 5.1? — MindStudio](https://www.mindstudio.ai/blog/gpt-6-astra-benchmarks-analysis)
- [My June Fable 5 vs Opus 4.8 benchmark]({% post_url 2026/2026-06-10-claude-fable-5-benchmark %})
