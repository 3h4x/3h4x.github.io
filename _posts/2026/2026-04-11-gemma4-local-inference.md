---
layout: post
title: "Gemma 4: testing the hype locally"
categories: tech
tags: [ai, llm, gemma, google, local-inference, lm-studio, open-source, benchmark]
comments: True
---

Google dropped Gemma 4 on April 2nd to a lot of noise. I loaded it in LM Studio and ran it against two other 4B-class edge models to see if the hype holds up. One thing upfront: this is not a test of Google's headline benchmarks — those are for the 31B dense model. Everything here is the E4B edge variant, which is what fits on consumer hardware.

<!-- readmore -->

## What Google claimed

The headline Gemma 4 numbers come from the 31B dense: 89.2% on AIME 2026 math, 80.0% on LiveCodeBench v6. Gemma 3 27B scored 20.8% and 29.1% on the same benchmarks. That gap is real. It's also for a model I can't run.

The E4B is ~4.5B effective parameters with native multimodal support — text, image, video, audio. The 26B MoE is the other interesting variant: 4B active parameters per inference pass, 26B in the weights, behaves like a large model but runs faster. Both need less VRAM than the 31B. I'm on the E4B.

## The models

| Model | Architecture | Notable |
|---|---|---|
| **Gemma 4 E4B** | Dense transformer, ~4.5B | Multimodal, Apache 2.0 |
| **Nemotron 3 Nano 4B** | Hybrid Mamba-2 + 4 attention layers | Built-in reasoning mode, English only |
| **Ministral 3 3B** | Dense transformer, 3.4B + 0.4B vision | Fastest, native tool use, multilingual |

All three loaded in LM Studio, OpenAI-compatible API on port 1234, same hardware.

## Five tests

Standard benchmarks are useless here — every model has seen Fibonacci and the bat-and-ball problem thousands of times in training. I ran five prompts designed around real daily use instead. Single-shot, no retries, manual scoring.

| Test | Gemma 4 E4B | Nemotron 3 Nano 4B | Ministral 3 3B |
|---|---|---|---|
| Bug fix | ✓ | ✓ | ✓ |
| Instruction following | partial | ✗ | ✗ |
| Factual trap | ✓ | ✓ | ✓ |
| Bash task | ✓ | ✓ | ✗ |
| Multi-step reasoning | ✓ | ✓ | ✓ |
| **Score** | **4.5/5** | **4/5** | **3/5** |

Gemma was most consistent. Ministral was fastest and least reliable.

### Bug fix

```python
def most_frequent(lst):
    counts = {}
    for item in lst:
        counts[item] = counts.get(item, 0) + 1
    return max(counts)
```

The bug: `max(counts)` returns the largest key, not the most frequent item. The function runs without error — it only fails on specific inputs. All three caught it. Nemotron also added empty list handling unprompted.

### Instruction following *(the interesting one)*

*List exactly 3 benefits of exercise. Numbered list (1. 2. 3.), each item exactly 4 words, no punctuation of any kind, no introductory sentence.*

The prompt has a built-in conflict: a numbered list implies periods after numbers, but "no punctuation of any kind" forbids them. How each model handles the contradiction is what matters.

**Gemma:** Dropped the periods, kept the word count exactly right on all three items. Made a decision and followed it.

**Nemotron:** Blank output — even with 500 tokens available. Its internal reasoning shows a loop it never escaped: *"no punctuation of any kind... But the rule 'Numbered list (1. 2. 3.)' suggests periods..."* Paralysis, not a resource issue.

**Ministral:** Kept the periods, got the word count wrong on two items. Made a decision, missed a constraint.

For production use this matters more than any accuracy benchmark. In an automated pipeline, Nemotron returning blank with no error is the worst possible failure — the caller gets nothing and no signal why. This is the test that tells you something the leaderboards don't.

### Factual trap

*A 1kg brick and a 1kg feather dropped from the same height in a vacuum — which hits first?*

All three answered correctly (same time, air resistance removed). Not differentiating. Replacing in future runs.

### Bash task

*Single bash command, no pipes, no semicolons — find .log files in /var/log modified in the last 24 hours, print filenames only.*

No pipes forces use of `find`'s `-printf "%f\n"` instead of the common `find | xargs basename` pattern.

**Gemma:** `find /var/log -maxdepth 1 -type f -name "*.log" -mtime -1 -printf "%f\n"` — correct, though `-maxdepth 1` limits to the top directory only.

**Nemotron:** `find /var/log -type f -name "*.log" -mtime -1 -printf '%f\n'` — correct, recurses subdirectories.

**Ministral:** Used a pipe. The exact constraint it was told not to use.

### Multi-step reasoning

*Start with 3. ×4. −7. Square. Add letters in RESULT.*

Answer: 31. All three got it. Clean state tracking, nothing surprising. Low discriminative power — replacing this too.

## What the reasoning overhead actually means

Nemotron generates internal thinking tokens before every response, visible in the `reasoning_content` API field. This helped on the bash task (produced the more complete answer) and hurt on instruction following (looped indefinitely on the constraint conflict).

The pattern: Nemotron's reasoning is an asset when there's a verifiable correct answer to reason toward. It's a liability when the task requires making an arbitrary choice between valid options. For agent design — route structured-output tasks elsewhere, use Nemotron for reasoning-heavy work.

This is local inference. No cost per token. Set `max_tokens` generously.

## What the hype is actually about

The E4B is solid and consistent. It's not what's generating the excitement.

The 26B MoE is. A model that reasons like something much larger but runs at edge speeds, Apache 2.0, commercially usable. If that holds up under real workloads, the local inference story changes significantly. I haven't tested it — needs hardware I'm not running. That's a different post.

## Who should use what

**Gemma 4 E4B** — most consistent across varied tasks, multimodal at this size class. Won't surprise you often.

**Nemotron 3 Nano 4B** — best for tasks with verifiable answers where careful reasoning improves output. Avoid for pipelines parsing short structured responses, or anything requiring arbitrary judgment calls under ambiguity.

**Ministral 3 3B** — ~50% faster on sustained output. Use it where throughput matters and you can verify results. Don't trust it to follow rules it finds inconvenient.

## The script

Hardware: Apple Silicon Mac, LM Studio. Swap your model ID from `curl localhost:1234/v1/models`.

```python
import urllib.request, json, time

BASE = "http://localhost:1234/v1/chat/completions"
MODEL = "your-model-id-here"
# tested: gemma-4-e4b-uncensored-hauhaucs-aggressive
#         nvidia/nemotron-3-nano-4b:2
#         mistralai/ministral-3-3b

tests = [
    {"name": "Bug fix",
     "prompt": "Fix the bug in this Python function. Return only the corrected function, no explanation.\n\ndef most_frequent(lst):\n    counts = {}\n    for item in lst:\n        counts[item] = counts.get(item, 0) + 1\n    return max(counts)",
     "max_tokens": 500},
    {"name": "Instruction following",
     "prompt": "List exactly 3 benefits of exercise.\nRules:\n- Numbered list (1. 2. 3.)\n- Each item: exactly 4 words\n- No punctuation of any kind\n- No introductory sentence",
     "max_tokens": 500},
    {"name": "Factual trap",
     "prompt": "A 1kg brick and a 1kg feather are dropped from the same height in a vacuum. Which hits the ground first? Answer in one sentence.",
     "max_tokens": 500},
    {"name": "Bash task",
     "prompt": "Write a single bash command (no scripts, no semicolons, no pipes) that finds all .log files in /var/log modified in the last 24 hours and prints only their filenames, not full paths.",
     "max_tokens": 500},
    {"name": "Multi-step reasoning",
     "prompt": "Start with the number 3.\nStep 1: Multiply by 4.\nStep 2: Subtract the number of days in a standard week.\nStep 3: Square the result.\nStep 4: Add the number of letters in the word RESULT.\nWhat is the final answer? Show each step.",
     "max_tokens": 500},
]

for t in tests:
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": t["prompt"]}],
        "temperature": 0.3,
        "max_tokens": t["max_tokens"]
    }).encode()
    req = urllib.request.Request(BASE, data=payload, headers={"Content-Type": "application/json"})
    start = time.time()
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    elapsed = time.time() - start
    tokens = data["usage"]["completion_tokens"]
    reasoning = data["usage"].get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    print(f"[{t['name']}] {tokens}t ({reasoning}r) {elapsed:.2f}s = {tokens/elapsed:.1f} tok/s")
    print(data["choices"][0]["message"]["content"])
    print()
```

3h4x
