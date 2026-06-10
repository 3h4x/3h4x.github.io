---
layout: post
title: "Claude Fable 5: I ran the harder benchmark I promised, against Opus 4.8"
categories: tech
tags: [ai, anthropic, claude, fable, benchmarks, claude-code, opus, llm]
comments: True
---

There's a new name in my Claude Code model picker: Fable 5. Not Opus 4.9 — Fable. Anthropic is naming things again — [Mythos]({% post_url 2026/2026-04-12-claude-mythos-preview %}) was the invite-only security model nobody outside the Glasswing consortium can touch; Fable is the new top tier you actually can. It sits above Opus, at double the price: $10 per million input tokens and $50 per million output, versus $5/$25 for Opus 4.8. Back in [April]({% post_url 2026/2026-04-16-opus-4-6-vs-4-7-benchmark %}) I benchmarked Opus 4.6 against 4.7 with deliberately easy tasks and promised a follow-up suite "that can fail" — failing tests the model has to make pass, regex on adversarial inputs, reasoning with traps. Fable seems like the right occasion to deliver it.

<!-- readmore -->

## What Fable actually is

The facts, before the numbers:

- **Model ID `claude-fable-5`.** A new model family name, positioned above Opus. In Claude Code it shows up as `claude-fable-5[1m]` — the 1M-token context variant.
- **$10 / $50 per MTok** — exactly 2x Opus 4.8 ($5/$25) on both input and output.
- **1M context, 128K max output** — same ceilings as Opus 4.8, so the price buys capability, not capacity.
- **Same API surface as Opus 4.7/4.8** — adaptive thinking only, no `temperature`/`top_p`/`top_k`, no assistant prefills — plus one new restriction: an explicit `thinking: {type: "disabled"}` now returns a 400. You can omit the parameter, but you can't explicitly turn thinking off. That's a hint about how the model is meant to be run.

So the question worth a benchmark isn't "is Fable better" — at 2x the price it had better be. It's: **does it fail less on tasks where failure is cheap to detect?** That's what the April suite couldn't see, because both models scored 30/30 on it.

## The harder suite

Ten tasks, two models, three runs each — 60 calls through `claude -p --model <m> --output-format json`, same minimal system prompt as in April ("You are a benchmark subject. Follow instructions literally."), graded by code, not by eyeball. The harness is in the repo: [`scripts/2026-06-10-fable-5-benchmark.py`](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-06-10-fable-5-benchmark.py).

The design rule: every task must be **gradeable by execution or exact match**, and most should have a plausible wrong answer that a pattern-matching model would produce. Before spending a cent on model calls, every grader was validated against a known-correct answer (must pass) and the plausible wrong one (must fail). Full disclosure: a Fable-driven Claude Code session built this harness — which is exactly why the graders being answer-key-driven, not vibes-driven, matters. The answer key was checked before any model saw a prompt.

| Task | What it tests | How it's graded |
|---|---|---|
| `bugfix_merge` | Fix an off-by-one in interval merging (`<` vs `<=`) | Returned code is executed against 5 asserts |
| `bugfix_bsearch` | Make binary search return the *leftmost* match, stay O(log n) | Executed against 6 asserts incl. a 10k-element case |
| `regex_ipv4` | IPv4 regex, leading zeros invalid | Compiled and run against 16 adversarial cases |
| `sql_null_trap` | "Count users NOT known to be older than 30" — NULL semantics | Executed in SQLite against a fixture with NULLs |
| `json_strict` | Exact keys, no fences, no prose | Parsed and validated structurally |
| `trap_batball` | Bat-and-ball, but the bat costs a flat $1.00 — the intuitive answer is *correct* | Exact match: `10` |
| `trap_jugs` | 7L and 3L jug, measure 3L — answer is "just fill the 3L jug" | Exact match: `1` |
| `trap_monty_random` | Monty Hall, but the host opens a random door | Exact match: `1/2` |
| `trace_mutable_default` | Python mutable default arg + aliased prints | Exact match: `[1, 2] [1, 2]` |
| `arith_exact` | Discount + tax, exact cent rounding | Exact match: `112.57` |

The three traps deserve a word. `trap_batball` is the famous CRT question *modified so the memorized trick answer is wrong*: the bat costs a flat $1.00, so the ball is plainly 10 cents — but a model that pattern-matches to "I know this one, it's 5!" fails. `trap_monty_random` breaks Monty Hall the same way: when the host opens a door *at random* and happens to show a goat, switching no longer helps — the answer is 1/2, not the memorized 2/3. `trap_jugs` is a water-jug puzzle whose answer is one step. These punish recognition and reward actually reading the question.

## Results

Strict grading, three runs per task per model. A pass means the code passed the executed tests, the regex survived all 16 adversarial cases, the SQL returned the right count against the NULL fixture, or the string matched exactly — no partial credit.

| Task | Fable 5 | Opus 4.8 |
|---|---|---|
| `bugfix_merge` | **3/3** | 2/3 |
| `bugfix_bsearch` | **3/3** | **3/3** |
| `regex_ipv4` | **3/3** | 2/3 |
| `sql_null_trap` | **3/3** | 2/3 |
| `json_strict` | **3/3** | 2/3 |
| `trap_batball` | **3/3** | **0/3** |
| `trap_jugs` | **3/3** | **3/3** |
| `trap_monty_random` | **3/3** | **3/3** |
| `trace_mutable_default` | **3/3** | **3/3** |
| `arith_exact` | **3/3** | 2/3 |
| **Total** | **30/30** | **22/30** |

Fable 5 went clean. Thirty for thirty, on a suite designed to make models fail. Opus 4.8 dropped eight — but the eight are worth dissecting, because they split into two very different failure modes.

## What failed and why

**Failure mode 1: the right answer, delivered wrong (4 of 8).** Four Opus failures had a correct answer sitting right there in the response — preceded by a line of leaked deliberation that the prompt explicitly forbade. The first line of each failing response, verbatim (each was followed by a *correct* function / regex / SQL / JSON):

```text
bugfix_merge:   The bug: `s < out[-1][1]` should be `s <= out[-1][1]` to merge touching intervals.
regex_ipv4:     25[0-5]|2[0-4][0-9]|... — wait, I'll give the full pattern:
sql_null_trap:  COUNT(*) is wrong here? No—count users NOT known to be older than 30. NULL or age<=30.
json_strict:    I don't need any tools or skills for this—it's a direct output request.
```

Every prompt said some variant of "Reply with ONLY the …. No explanation." That "— wait," mid-line is the model audibly changing its mind in the output channel. I regraded all eight failures leniently — drop leading prose lines until something passes — and exactly these four recover, each after dropping a single line. Lenient score: Opus 26/30. Fable needed no leniency anywhere; across 30 calls it never emitted one character beyond what was asked.

This matches something in Anthropic's own migration notes: with thinking disabled, Opus 4.8 "may write longer reasoning into the visible response." And here's the API detail that suddenly looks load-bearing: on Fable 5, explicitly disabling thinking returns a 400 — the option is gone. The model always has its reasoning channel available, and judging by these outputs, that's exactly what keeps deliberation from leaking into the answer. The Opus behavior isn't stupidity; it's thinking out loud in the wrong channel.

Whether you count those four as real failures depends on what you're building. A human reading the chat shrugs them off. A pipeline that feeds the response to `json.loads()` or `re.compile()` does not shrug — it throws. My graders are pipelines, so I count them.

**Failure mode 2: pattern-matching past the question (4 of 8).** `trap_batball` is the damning one: **Opus answered "5" all three runs.** The question states the bat costs a flat $1.00 — the ball is 10 cents, no algebra required. But the question *looks like* the famous CRT trick question ("the bat costs $1.00 *more than* the ball"), and Opus pattern-matched to the memorized answer instead of reading the sentence in front of it. Three out of three. Fable answered 10 every time. The remaining miss was `arith_exact` in run 3, where Opus produced 107.18 instead of 112.57 — a one-off precision wobble on a two-step percentage calculation (the same model got it right in runs 1 and 2, which also tells you `claude -p` is not deterministic).

For balance: both models cleanly dodged the other two traps. The random-host Monty Hall got a correct 1/2 from everyone — no memorized 2/3 — and nobody overcomplicated the jug puzzle. The traps don't catch everything; they caught one specific, repeatable blind spot.

## Speed and cost

| | Fable 5 | Opus 4.8 |
|---|---|---|
| Correct (strict) | **30/30** | 22/30 |
| Median wall | 8.2s | **5.7s** |
| Mean wall | 8.1s | **6.2s** |
| Cost, 3 full runs (30 calls) | $4.04 | **$2.09** |
| Total output tokens (30 calls) | **3,931** | 4,105 |

Opus is faster on 9 of 10 tasks — about two seconds per call in this harness — and costs almost exactly half, which is no surprise since that's the list-price ratio ($10/$50 vs $5/$25 per MTok) applied to near-identical token counts. Run 1 was pricier for both models ($1.88 / $0.94) than runs 2–3 (~$1.08 / ~$0.57) — that's prompt-cache creation on the first pass, not the models drifting.

The token column is the quiet surprise: Fable is *not* more verbose despite being the "bigger" model. It actually emitted fewer output tokens in total, and on the jug puzzle it answered in 52 tokens where Opus used 123. Whatever extra deliberation Fable does, it happens in the thinking channel where I can't see it — the visible output is consistently the terser of the two.

One pre-suite anecdote that deserves a footnote: while smoke-testing the harness, I asked both models for 47×53. Fable said 2491. Opus 4.8 said **94** on its first try and 2491 on the retry. One sample, zero statistical weight — but it's a good reminder of why you run everything three times.

## What this doesn't tell us

The usual disclaimers, same as April, still apply — and a few new ones:

- **30 samples per model is small.** Three runs per task is enough to see direction, not to put error bars on anything.
- **`claude -p` is a harness, not the raw API.** Claude Code wraps the call with its own system prompt scaffolding, and thinking behavior in `-p` mode isn't something I control per-request. Both models go through the identical wrapper, so the *comparison* is fair, but absolute numbers would differ over the raw API.
- **No agentic tasks.** Fable's pitch — like every frontier model's pitch now — is long-horizon autonomous work. A 10-task single-shot suite says nothing about whether it's better at a 200-turn refactor. The honest version of that test is sustained real use, which started today (this post was written in a Fable-driven Claude Code session, for whatever that's worth).
- **One pair of models, one day.** Same caveat as April: launch-week behavior can shift as the provider tunes serving.

## My take

**Fable 5 went clean on a suite built to make models fail.** That's the headline, but the *shape* of the gap matters more than the score. On raw capability the two models are close — Opus had the correct regex, the correct SQL, the correct bugfix sitting in its responses. Where Fable actually separates is discipline: it never leaked deliberation into the output channel, and it never pattern-matched past a question that resembled a famous one. Twenty-two of Opus's thirty answers were perfect too; the difference is that Fable's failure rate on this suite was zero, and Opus's was 27% strict, 13% lenient.

Is that worth 2x the price? Wrong frame — it's workload math:

- **Output parsed by code** (extraction pipelines, structured generation, anything hitting `json.loads()`): the strict number is the real number, and a 27% failure rate vs 0% dwarfs a 2x per-call price difference. Retries cost latency, code, and money; corrupted output downstream costs more.
- **A human reads the output** (chat, drafting, code review in an editor): the lenient number is the real number, and 26/30 vs 30/30 at half the price and ~2s less latency is a perfectly reasonable trade in Opus's favor.
- **The trap dimension is harder to price.** A model that answers "5" three times out of three because the question *looked like* one it knew is exhibiting exactly the failure mode that bites in real work — the config that looks standard but isn't, the function that resembles a textbook pattern with one inverted condition. Fable reading the actual question every time is the property I'd pay for.

I've also been running Fable as the driver in Claude Code while writing this post — it built the harness, ran the suite, and drafted what you're reading. One session is anecdote, not data. The April post promised a harder suite; this delivers it, and the suite finally found a gap the easy one couldn't see. Next checkpoint is a month of real use — and a suite with agentic, multi-turn tasks, because single-shot discipline and 200-turn autonomy are different properties and I've only measured one of them.

The harness is [`scripts/2026-06-10-fable-5-benchmark.py`](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-06-10-fable-5-benchmark.py) and the raw ndjson results are [next to it](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-06-10-fable-5-results.ndjson). Run it on your own workload before believing me — or Anthropic.

Know what you are doing and have fun!

3h4x
