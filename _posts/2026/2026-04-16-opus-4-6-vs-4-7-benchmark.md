---
layout: post
title: "Opus 4.6 vs 4.7: I ran my own benchmark through the Claude CLI"
categories: tech
tags: [ai, anthropic, claude, benchmarks, claude-code, opus, llm]
comments: True
---

Opus 4.7 dropped yesterday. I don't have a real opinion yet — a day isn't enough — but I did have a few hours and some curiosity, so I wrote a tiny benchmark and ran both models through it. Instead of citing Anthropic's launch numbers, I wanted to see what I'd get on my own laptop.

<!-- readmore -->

## The setup

Ten tasks, each one designed to have a verifiable answer — arithmetic, word-problem reasoning, Python trace execution, factual recall, regex, SQL, and an instruction-following format task. Every task gets run through `claude -p --model <model> --output-format json` with a minimal system prompt. I record the wall-clock time, the API time reported by the CLI, output tokens, and the result string. Then a Python script grades each result against the expected answer.

The tasks file looks like this:

```json
[
  {"id": "math1", "prompt": "Compute 47 * 53. Reply with ONLY the integer.", "expect": "2491"},
  {"id": "math2", "prompt": "What is 2^16 - 1? Reply with ONLY the integer.", "expect": "65535"},
  {"id": "word1", "prompt": "I have 3 apples. I eat 2. My friend gives me 5. I eat 1 more. How many do I have?", "expect": "5"},
  {"id": "code1", "prompt": "x=[1,2,3]; y=x; y.append(4); print(x) — what prints?", "expect": "[1, 2, 3, 4]"},
  {"id": "format1", "prompt": "List exactly 5 Linux process tools. No numbering. No preamble.", "expect_lines": 5},
  ...
]
```

And the runner does exactly this for each task, for each model:

```bash
claude -p --model "$MODEL" --output-format json \
    --system-prompt "You are a benchmark subject. Follow instructions literally." \
    "$PROMPT"
```

Nothing fancy. Same machine, same network, sequential execution, one shot per (task, model) pair.

## The numbers

I ran the full suite three times over a couple of hours. Both models scored **10/10 correct on every run — 30/30 total** — the tasks are deliberately easy enough to get a clean latency comparison before poking at anything harder.

Across all three runs each side had exactly one multi-hundred-second hang (4.6 on `math1` in run 2, 4.7 on `math2` in run 1). The fact that it switched models between runs tells me these are network/rate-limit hiccups in the `claude` CLI harness, not a model property. I dropped them from the numbers below.

| | Opus 4.6 | Opus 4.7 |
|---|---|---|
| Correct | 30/30 | 30/30 |
| Median wall (n=29 each) | 6.62s | **5.52s** |
| Mean wall | 6.77s | 5.95s |
| Mean cost per run | $0.54 | $0.74 |

### Per-task averages (3 runs, outliers dropped)

```
task         4.6 avg    4.7 avg    delta
math1          6.38s      5.28s    -1.10s
math2          7.49s      5.01s    -2.48s
word1          6.11s      5.53s    -0.58s
code1          6.30s      5.67s    -0.63s
code2          5.94s      5.58s    -0.36s
fact1          5.66s      5.45s    -0.21s
fact2          7.27s      6.90s    -0.37s
format1        8.38s      5.51s    -2.87s
regex1         6.70s      6.27s    -0.43s
sql1           7.35s      7.95s    +0.59s
```

4.7 was faster on the average across 9 of 10 tasks. The one task where 4.6 wins — SQL — is also the one task where 4.7 consistently emits more output tokens (52 tokens vs 28 for 4.6, both wrapping the query in `` ```sql `` fences despite being told "no explanation"). More tokens → more wall time. Everywhere else the direction is the same: 4.7 is a bit faster, reliably.

### On determinism

I expected `claude -p` outputs to be bit-for-bit identical across runs — temperature-0-ish behavior. Mostly they were, but not always:

- 4.6 `format1` changed only on run 3: earlier runs emitted `ps/top/htop/strace/lsof` in 59 tokens; run 3 emitted the same five tools in a different order using only 16 tokens.
- 4.7 `regex1` produced three distinct regex forms across the three runs (different anchor choices, different octet patterns — all functionally correct).

So content-side variance exists, it's just small. For this suite it didn't affect correctness, but it's worth noting that "run it once through `claude -p`" is not a deterministic oracle.

### Verbosity

The instruction-following format task — "List exactly 5 distinct command-line tools for inspecting Linux processes. One per line. No numbering. No preamble. No trailing text." — is where verbosity showed up most clearly:

- 4.6 token counts across 3 runs: **59, 59, 16**
- 4.7 token counts across 3 runs: **20, 20, 20**

4.7 is boringly consistent at 20 tokens. 4.6 added a big chunk of whitespace or trailing block on the first two runs (59 tokens for the same five-tool list) before producing something tight on run 3. On the SQL task the direction flipped — 4.7 used 52 tokens where 4.6 used 28, both wrapping the query in `` ```sql `` fences despite being told "no explanation." Neither model obeyed the "no fences" instruction, but 4.7 chose the more ceremonial format every time.

## What this actually tells us

A ten-task suite run three times doesn't prove much. What it does do is anchor the conversation in real measurements from my environment:

- **Both models get the easy stuff right.** 30/30 correct for both, across three runs. On trivial factual, arithmetic, and trace questions there's no correctness gap.
- **4.7 is ~1 second faster per call in this harness.** Median wall 5.52s vs 6.62s. Small, consistent, directional on 9 of 10 tasks.
- **4.7 costs about 35% more per run.** Mean $0.74 vs $0.54. Stable across runs since token counts barely move. If you're not reaching for capability 4.7 provides, `/fast` (4.6) is genuinely cheaper.
- **CLI wall time is dominated by harness overhead.** Non-outlier API times were 1.5–3 seconds on both models; wall times were 5–8 seconds. That gap is Claude Code doing whatever it does (auth, settings, cache creation, session setup) before and after the call. For single-shot `claude -p` invocations the overhead dominates. In interactive chat you don't pay it per turn, but pipelines calling `claude -p` in a loop will.

## What this doesn't tell us

The tasks are too easy. I did not measure:

- Multi-step reasoning chains where 4.7 is supposed to pull ahead
- Code generation that actually has to pass tests
- Tool-use accuracy in agentic contexts
- Any task where context length matters (4.7 has the 1M context window, 4.6 has 200k)
- More than 3 repetitions per task — 30 samples per model isn't enough to say anything strong about the tail

Anything marketed as a "capability jump" will only show up on tasks that can fail. I plan to build out a harder suite — failing tests that the model has to make pass, multi-file refactors, regex correctness on adversarial inputs, reasoning with traps — and run both models against it with multiple trials per task. That's the post where the real gap (if any) shows up.

## The takeaway for now

From this tiny but real data: on trivial tasks 4.7 is about a second faster per call, more consistent in terse-output mode, and costs about a third more per run. Those are the only claims I'll make after one day. The published numbers from Anthropic claim much bigger gaps on agentic and coding benchmarks — those gaps didn't surface here because the suite can't see them. Next step is a suite that can, and running it again after a week of real use rather than a day.

The benchmark scripts and raw ndjson results are in `/tmp/opus-bench/` if I decide to turn this into a proper repo. Until then: measure your own workload, don't trust launch-day benchmark tables, and treat any number on a marketing page as the best case the vendor could find.

3h4x
