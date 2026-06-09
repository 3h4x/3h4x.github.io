---
layout: post
title: "Gemma 4 QAT vs non-QAT: is quantization-aware training actually better?"
categories: tech
tags: [ai, llm, gemma, google, quantization, qat, local-inference, ollama, llama-cpp, benchmark, open-source]
comments: True
---

I've got two Gemma 4 12B files sitting on my disk: the official QAT Q4_0 checkpoint Google shipped on June 5th, and a plain non-QAT GGUF. Same model, same parameter count, roughly the same size on disk. One says "QAT" in the name and one doesn't. The obvious question — which one do I keep, and is the QAT label worth anything or is it marketing — turns out to be more interesting than I expected, because "QAT 12B vs non-QAT 12B" isn't actually one comparison. It's three.

<!-- readmore -->

This is a follow-up to the [Gemma 4 edge-model shootout]({% post_url 2026/2026-04-11-gemma4-local-inference %}) from April. That post was about *which 4B-class model* to run. This one is about *which quantization of the same model* to run, which is the question you hit the moment you go up to the 12B that [Google released on June 3rd](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12b/) and your VRAM starts to matter.

**Short answer, then the working.** If you want a 4-bit Gemma 4 12B, keep the QAT one — it's the smallest file, it's the fastest to respond, and across six tasks it never lost to a strong community K-quant. But be precise about *why* it's faster: that's the **Q4_0 format** Google ships it in, not the QAT recipe. QAT changes what the weights *are*, not how fast they decode — a plain non-QAT Q4_0 with zero QAT in it still leaves the K-quant in the dust (I measured it). The speed is the format. What QAT actually buys is quality insurance: a Q4_0 that isn't dumber for being Q4_0. My behavioural suite couldn't separate the two on quality — they tie — because pass/fail prompts are the wrong instrument for it. That gap is real; it just lives in perplexity, not in whether the model emits valid JSON. The rest of this post is me showing my work.

## What QAT actually is

Quantization is compression for model weights. A model is trained in 16-bit floats (BF16). Every weight is a 16-bit number. Quantizing to int4 means storing each weight in 4 bits instead — a 4x reduction in size. Think of it like dropping an image from 16-bit color down to a 16-colour palette: smaller file, and if you do it naively, visible banding.

There are two ways to do it.

**Post-Training Quantization (PTQ)** is the naive way: train the model in full precision, then round all the weights down to 4-bit afterwards. Fast, free, and it's what 95% of the GGUFs on Hugging Face are — bartowski, unsloth, the GGML org, all the community quants. It works surprisingly well, but rounding millions of weights *does* lose information, and that loss shows up as the model getting subtly dumber.

**Quantization-Aware Training (QAT)** bakes the rounding into training. Instead of quantizing at the end, you simulate the low-precision math *during* a fine-tuning pass, so the weights learn to land on values that survive being rounded to 4-bit. Google's recipe, from the [Gemma 3 QAT writeup](https://developers.googleblog.com/en/gemma-3-quantized-aware-trained-state-of-the-art-ai-to-consumer-gpus/) and carried into Gemma 4: about 5,000 fine-tuning steps, using the probability distribution from the original non-quantized checkpoint as the training target. It's basically the full-precision model teaching its own compressed copy not to drift.

The headline number Google publishes: QAT **reduces the perplexity drop by 54%** (measured with llama.cpp's perplexity eval) when going down to Q4_0, versus standard PTQ to the same format. The [Gemma 4 QAT release](https://blog.google/innovation-and-ai/technology/developers-tools/quantization-aware-training-gemma-4/) restates the same claim qualitatively — "our QAT results yield even higher overall quality compared to standard PTQ baselines." So at the same 4-bit size, QAT keeps roughly half the quality you'd otherwise lose. That's the entire pitch.

## Acronym cheat sheet

- **Q4 / Q6 / Q8** — bits per weight. Q4 = 4 bits, Q8 = 8 bits, BF16 = 16 bits (full precision). Lower = smaller file, more compression loss.
- **_0** (e.g. Q4_0) — flat scheme: every block of 32 weights shares one scale factor. Simple, fast, crudest option at a given bit width.
- **_K** (e.g. Q4_K_M) — "K-quants": smarter scheme from llama.cpp. Uses larger super-blocks and mixes precision across tensors — some layers get more bits, others less, based on what matters. More accurate than _0 at the same average size.
- **_M / _S / _L** — size/quality variants of K-quants. M = Medium (best balance), S = Small, L = Large.
- **imatrix** — importance matrix. Calibration data that tells the quantizer which weights matter most so they get preserved more carefully. A Q4_K_M with a good imatrix is noticeably better than one without.
- **QAT** — Quantization-Aware Training. Rounding is simulated during a fine-tuning pass so the weights learn to survive 4-bit compression. Google's thing here.
- **PTQ** — Post-Training Quantization. Train in full precision, compress afterwards. What 95% of community GGUFs are.

## The trap in the question

Here's the thing that took me a minute to see. "Is the QAT 12B better than the non-QAT 12B?" depends entirely on *what precision the non-QAT one is*, and that's a thing I control when I download it. There are three honest comparisons hiding in one question:

1. **QAT Q4_0 vs a non-QAT Q4_0 — same format, same size.** This is the genuinely apples-to-apples fight: same bits per weight, same decode kernel, the *only* variable is the QAT recipe. This is where the 54% number applies and where QAT is supposed to win. (It's also the comparison my speed probe uses later to prove the format, not the recipe, owns the speed.) A community `Q4_K_M` is a slightly bigger, mixed-precision cousin — a *tougher* same-rough-budget baseline, and the one I actually benchmark below.
2. **QAT Q4_0 vs a non-QAT Q8_0 or Q6_K — non-QAT is bigger.** Here the non-QAT model has 2x the precision and 2x the memory footprint. It will almost certainly score higher on raw quality. QAT isn't beating that; it's not trying to. QAT's win here is that it gets *close* at half the RAM.
3. **QAT Q4_0 vs the full BF16 — the ceiling.** What did you actually give up versus the uncompressed model? This is the number that tells you whether 4-bit is "good enough" for your use case at all.

So the answer to "is QAT better" depends entirely on what you're comparing it to. At the same bit width, QAT is *supposed* to win — that's the claim, and comparison 1 is the one worth actually testing (the rest of this post does). Against a higher-precision quant that uses more RAM — obviously not, but that's not a fair fight. The question that actually matters is: **given my VRAM, what's the best model I can run?** If the answer is 4-bit, the QAT Q4_0 is the 4-bit I'd reach for — and below I dig into whether that's QAT earning it or just the format it ships in.

One caveat I want to be fair about: the 54% figure is QAT measured against *flat* PTQ. The good community quants aren't flat. A `Q4_K_M` from bartowski uses mixed precision (some tensors kept at higher bits) plus an importance matrix calibrated on real text to decide which weights to protect. That's a much stronger baseline than naive Q4_0 — don't assume QAT auto-wins every 4-bit matchup just because it beats flat PTQ. The lmstudio-community Q4_K_M I ran against is a mixed-precision K-quant of just this sort (whether its build used an imatrix I couldn't confirm from the GGUF metadata, so I won't claim it did) — still a much tougher baseline than a flat Q4_0, which is what makes the comparison interesting.

## The memory reality

Both models measured on Apple Silicon / macOS 26.5 / Ollama, loaded at 32768-token context. Resident size from Ollama's `api/ps`. Averages across five scoreable tasks (exact_arithmetic excluded — both models produced no visible output on that test).

| Model | Bits/weight | GGUF size | Resident (32k ctx) | Avg tok/s | Avg response time |
|---|---|---|---|---|---|
| Q4_K_M (lmstudio-community) | ~4.8 | 7.60 GB | ~8.43 GB | 30.9 | ~54s |
| **Q4_0 QAT (Google official)** | ~4.5 | **7.20 GB** | **~8.02 GB** | **39.4** | **~37s** |

The practical consequence: at ~8 GB resident both need a bit more than an 8 GB GPU — a 16 GB card runs them comfortably. A Q8_0 of the same model would need ~12.5 GB just for weights — different hardware class entirely.

Two asterisks that the marketing charts leave off:

- **That's weights only.** The KV cache — the model's working memory for the current conversation — is on top, and it scales with context length, *not* with weight precision. At 12B with a long context the KV cache can run to several GB. So the gap between a Q4_0 and a Q8_0 is real but it's not the whole memory story; both still need headroom for the cache. If you're memory-bound, quantizing the KV cache (a separate knob in Ollama / llama.cpp) often buys you more than agonizing over Q4 vs Q6.
- **Smaller also means faster — but that's the format, not QAT.** Fewer bits to move from memory per token means higher decode throughput, and Q4_0 also uses a simpler dequantization kernel than the K-quants. The QAT Q4_0 runs +27% faster than the Q4_K_M baseline (see Results) — but so does a *plain* PTQ Q4_0 with no QAT in it (I measured one); the speed is the format, not the recipe. QAT changes the weight values, not how fast they decode. Keep that attribution straight; it's the whole subtlety of the verdict.

## Test setup

Everything below was run on Apple Silicon / macOS 26.5. Inference and API calls go through **Ollama** (llama.cpp backend, OpenAI-compatible API on localhost:11434). The harness is plain Python 3 — no extra dependencies — and lives alongside this post in [`scripts/2026-06-08-gemma4-qat-vs-non-qat.py`](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-06-08-gemma4-qat-vs-non-qat.py).

Two things to handle before running anything:

Both models are **thinking models** — they generate reasoning tokens internally before producing visible output. Ollama does not stream the thinking content; it only surfaces the final visible response. The thinking happens, it just isn't accessible via the API. TTFT (time to first visible token) is the only indirect signal: a 145-second TTFT on a simple prompt means ~4,800 tokens of hidden reasoning happened first.

Ollama's default context window for these models is 4096 tokens, which isn't enough — at that limit the reasoning tokens fill the context before the model can produce a visible answer. Pass `options: {num_ctx: 32768}` on every request. All results in this post used 32768-token context.

## How to actually test this locally

This is the part I care about. Don't trust a label and don't trust a vendor chart — both models are sitting right there, so measure them.

### Pin the variables first

A benchmark where you changed two things at once tells you nothing. Hold all of these constant across both models:

- **One model loaded at a time.** Don't keep both resident — memory pressure tanks tok/s and poisons the timing numbers.
- **Identical context length** on load. Pass `num_ctx` explicitly on every request — don't rely on model defaults.
- **Greedy decoding for quality** (`temperature: 0`, fixed seed). For an A/B on the *model*, you don't want the *sampler* adding variance. Use Gemma's recommended sampling settings only for a separate "real feel" pass.
- **Same chat template.** Mismatched templates are the single most common reason a quant "looks broken." Verify both use the Gemma 4 template.
- **Warm up, then median-of-3.** The first call includes model load and a cold cache. Throw it away. Run each timing test three times, take the median.
- **Same KV cache setting** (cache quantization off for the quality runs).

### A task suite that stresses where quantization hurts

The five-test battery from [April]({% post_url 2026/2026-04-11-gemma4-local-inference %}) was built to separate *models*. Two of those tests (the feather/brick factual trap, the multi-step arithmetic) had low discriminative power even between different architectures — they'll be useless for separating two quants of the *same* model. Quantization damage doesn't show up on easy, high-frequency tasks; it shows up in the tail. So the suite is rebuilt to target the tail:

- **Code generation from spec.** Subtle logic, not boilerplate. Quant damage shows as off-by-one errors and dropped edge cases.
- **Strict structured output.** "Return JSON with exactly these keys, no prose." Degraded models drift — extra keys, markdown fences, a chatty preamble.
- **Multilingual.** I'm Polish, so this one's free and it's a genuinely good probe: multilingual ability is disproportionately fragile under quantization because those tokens are rarer in training. Ask for a translation *and* a register shift (formal → casual) and check the grammar, not just the gist.
- **Conflicting-constraint instruction following.** The punctuation-paradox prompt from April is a known discriminator — keep it.
- **Long-context recall.** Bury a specific fact in the middle of a ~12k-token log and ask for it. This stresses the quant *and* the KV cache together (load the model with enough context to hold it).
- **Exact arithmetic in a word problem.** Not "reason step by step" — a single number that has to be exactly right. Precision reasoning is where low-bit models quietly fall down.

Score each pass/partial/fail, single-shot, no retries, like before. The interesting cases are the ones where QAT and the community PTQ *diverge*, not the ones they both pass.

**Run — see Results section below.**

### The harness

The actual script used for these results is in the repo: [`scripts/2026-06-08-gemma4-qat-vs-non-qat.py`](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-06-08-gemma4-qat-vs-non-qat.py). Run it as:

```bash
python3 scripts/2026-06-08-gemma4-qat-vs-non-qat.py bench hf.co/google/gemma-4-12B-it-qat-q4_0-gguf:latest
python3 scripts/2026-06-08-gemma4-qat-vs-non-qat.py bench hf.co/lmstudio-community/gemma-4-12B-it-GGUF:Q4_K_M
```

The script uses `stream_options: {include_usage: true}` to get true `completion_tokens` (including hidden thinking) from Ollama, and handles the empty `choices[]` chunk Ollama sends with the final usage payload.

## Results

Both models ran on the same harness at `temperature=0`, `max_tokens=8192`, median of 3 runs per test, Apple Silicon / macOS 26.5 / Ollama, both loaded with a **32768-token context window** via `options: {num_ctx: 32768}`.

The non-QAT model is `lmstudio-community/gemma-4-12B-it-Q4_K_M.gguf` — mixed precision, not flat Q4_0. That makes this a harder fight for QAT than a naive Q4_0 matchup would be.

Note on `max_tokens` and hidden thinking: Ollama doesn't stream thinking tokens; they count against `max_tokens` invisibly. At `max_tokens=8192`, a test that triggers heavy reasoning can burn the entire budget internally and produce no visible output. That's exactly what happened on `exact_arithmetic` — both models hit 8,192 tokens and had nothing left for content. Whether the right answer (`1007.5`) was sitting in those hidden tokens, I can't tell: Ollama doesn't expose them, and the `completion_tokens` count (8,192, via `stream_options: {include_usage: true}`) confirms the budget was *spent*, not that it was spent well.

### Task suite

| Test | QAT Q4_0 (Google) | Q4_K_M (lmstudio-community) | Notes |
|---|---|---|---|
| code_from_spec | **PASS** | **PASS** | Both correct; QAT 199 vs Q4_K_M 170 content tokens |
| strict_json | **PASS** | **PASS** | Exact keys; population estimate differs (1.86M vs 1.795M) |
| multilingual_pl | **PASS** | **PASS** | Q4_K_M wordier (378 vs 172 content tokens) |
| constraint_conflict | PARTIAL | PARTIAL | Both committed; QAT used 4,797 total tokens, Q4_K_M used 5,900 |
| exact_arithmetic | FAIL | FAIL | Both burned full 8,192 token budget internally, no visible output |
| long_context_recall | **PASS** | **PASS** | Both returned "Paris" |
| **Score** | **4.5/6** | **4.5/6** | Tied (PARTIAL = 0.5, FAIL = 0) |

The `constraint_conflict` result is the clearest window into hidden thinking. The prompt is a genuine contradiction: "numbered list (1. 2. 3.)" requires a period after each number, "no punctuation of any kind" forbids it. Both models identified the paradox, chose a pragmatic interpretation, and committed to an answer. What differs is the cost: QAT resolved it in 4,797 total tokens (145s TTFT); Q4_K_M needed 5,900 tokens (192s TTFT) to reach the same conclusion.

The `exact_arithmetic` FAIL is really "unscoreable," not "wrong." Both models spent the entire 8,192-token budget on hidden reasoning and emitted nothing visible — `completion_tokens` confirms the budget was burned, but Ollama hides the thinking, so I can't see whether `1007.5` was in there. It might have solved it and run out of room to say so; it might have spiralled. Either way it's the *cap* that produced the blank, not a demonstrated capability gap — raise `max_tokens` and the answer, if it exists, gets room to surface. Don't read this row as a quality failure for either quant; read it as the hidden-token problem biting.

### Speed

Two fair objections to a "+27% tok/s" headline. First: maybe the QAT model just *thinks* longer, so a faster stream still adds up to a slower answer. Second, and deeper: maybe the speed has nothing to do with QAT at all. Both deserve a real answer. Start with the data, three ways:

**Visible tok/s and total tokens generated** (`completion_tokens` from Ollama, includes hidden thinking). Both *adv* columns are QAT-relative and same-signed: **positive = QAT wins** — faster decode, or fewer tokens spent to get there.

| Test | QAT tok/s | Q4_K_M tok/s | speed adv | QAT tot tok | Q4_K_M tot tok | token adv |
|---|---|---|---|---|---|---|
| code_from_spec | 45.2 | 32.2 | +40% | 703 | 966 | +27% |
| strict_json | 43.9 | 33.5 | +31% | 246 | 339 | +27% |
| multilingual_pl | 39.3 | 32.0 | +23% | 628 | 986 | +36% |
| constraint_conflict | 33.1 | 29.8 | +11% | 4,797 | 5,900 | +19% |
| exact_arithmetic | — | — | — | 8,192 | 8,192 | 0% |
| long_context_recall | 35.5 | 27.1 | +31% | 125 | 108 | **−16%** |
| **Avg (5 tests)** | **39.4** | **30.9** | **+27%** | — | — | — |

So the first objection is answered: the QAT model doesn't pay back its speed in extra thinking. The **token adv** column shows it reaching the same answer with 19–36% *fewer* total tokens on four of the five scoreable tasks. The honest exception is `long_context_recall` — QAT spent 16% more (125 vs 108), though both are tiny there (it's a one-word answer, so a handful of extra thinking tokens swings the percentage). Net: QAT is both faster per token and, mostly, more frugal with tokens — the speed gain isn't being clawed back by extra thinking. (That frugality is a property of these two specific checkpoints, not something one model-each can pin on the QAT recipe — but whatever the cause, it mostly cuts in QAT's favour.)

**Wall-clock time to complete response** (TTFT + full decode, seconds):

| Test | QAT | Q4_K_M | QAT advantage |
|---|---|---|---|
| code_from_spec | 15.4s | 29.9s | +48% |
| strict_json | 5.9s | 10.5s | +44% |
| multilingual_pl | 15.8s | 30.7s | +48% |
| constraint_conflict | 145.9s | 193.3s | +24% |
| exact_arithmetic | 223.2s | 287.6s | +22% |
| long_context_recall | 3.6s | 4.0s | +9% |
| **Average (5 tests)** | **~37s** | **~54s** | **+32%** |

The QAT model finishes faster on every test. On simple tasks (code, JSON, translation) the Q4_K_M takes nearly twice as long. On the heavy-thinking tests the gap narrows but the Q4_0 still wins. First objection settled: the speed is real end-to-end, not a streaming illusion.

#### So where does the speed come from?

Now the deeper objection — is this even QAT? Here's the thing it's easy to get wrong: **QAT can't make inference faster.** It's a training recipe; it changes what the weight values are, not the format, the bit-width, or the number of weights. Two GGUFs of the same format and size decode at the same speed no matter how the weights were derived. So the speed has to be coming from somewhere else, and it is: the QAT model ships as **Q4_0**, the baseline is **Q4_K_M**. Q4_0 is smaller (7.20 vs 7.60 GB) *and* uses a simpler dequant kernel than the K-quants — it's just a faster format on this hardware.

To check it rather than assert it, I pulled a third model — a plain PTQ Q4_0 (non-QAT, community quant) — and ran all three on a short probe (the `probe` mode of [`scripts/2026-06-08-gemma4-qat-vs-non-qat.py`](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-06-08-gemma4-qat-vs-non-qat.py)): an identical generation prompt (the integers 1–120) that every model completed with the same 490 visible tokens, so the tok/s is a clean decode-rate comparison. (These run a touch higher than the task-suite averages above — pure sustained generation, no task-switching — but the *ratios* between models are what matter here.)

| Model (490-token generation) | Format | Recipe | Decode tok/s |
|---|---|---|---|
| google | **Q4_0** | QAT | **42.9** |
| unsloth | **Q4_0** | PTQ | 38.4 |
| lmstudio-community | Q4_K_M | PTQ | 33.2 |

The shape of it: **both Q4_0 builds beat the Q4_K_M.** Even the PTQ Q4_0 — zero QAT anywhere in it — is +16% faster than the K-quant. That margin is the *format*: Q4_0 moves fewer bytes per token and dequantizes with a simpler kernel. The two Q4_0s aren't identical to each other (the QAT build edged the PTQ one by ~12%), but that's a *build* difference — they're different files with different tensor-type mixes, 7.2 vs 6.9 GB on disk — not a recipe difference. A training recipe can't change how many bytes the GPU reads per token, so QAT can't move this column at all.

So most of the headline +27% is the **Q4_0 format**, the rest is **google's particular build**, and *none* of it is QAT the recipe. Quantize this model to Q4_0 yourself and you'd land in the same neighbourhood — miles ahead of the K-quant — with no QAT involved. That's fine, because speed was never what QAT was selling.

(The probe caught one more thing worth a grin: on the second prompt the PTQ Q4_0 did the exact `exact_arithmetic` move — burned all 2,048 tokens on hidden thinking and emitted nothing visible. Same `max_tokens` trap, different model. It's everywhere once you start counting hidden tokens.)

### What the predicted direction said vs what happened

Predicted: QAT wins the 4-bit bracket on quality, and a strong mixed-precision Q4_K_M makes it earn that win. Actual: the behavioural suite **couldn't separate them** — both land 4.5/6, committing to an answer on every scoreable test. That's not QAT failing the test; it's the test being too coarse to ask the question. Two competent 4-bit quants of the same 12B don't diverge on "is this valid JSON" or "what's the capital of France" — they both just get it right. Quantization damage at this level is a shift in the probability distribution, not a flipped pass/fail.

Where they *visibly* differ is speed and size — and as the speed probe showed, that's the Q4_0 format the QAT model ships in, not the QAT recipe. So neither axis I could measure behaviourally actually isolates QAT's contribution. The instrument that does is perplexity / KL-divergence against the BF16 original; Google's 54% number lives there. I didn't reproduce it (a 23 GB download for a figure Google already published), so treat the quality claim as trusted, not verified here. What I *can* say from the behavioural side: on five scoreable tasks neither quant failed because of quantization, and the QAT one never stumbled.

## When NOT to bother with QAT

To keep myself honest, the cases where reaching for the QAT checkpoint is the wrong move:

- **You have the VRAM for Q8_0 or BF16.** Then run that. QAT exists to make 4-bit good; if you're not memory-bound, you don't need 4-bit, and a higher-precision non-QAT quant is simply better. Don't quantize for the sake of it.
- **Your task lives entirely in easy, high-frequency territory.** Short English chat, simple classification, basic summarization — the quality gap between any of these quants is below your ability to notice. Pick the smallest one and move on.
- **You're comparing across model families, not quants.** A QAT 12B vs a non-QAT 12B is the same brain at different compression. If the real question is "Gemma vs Qwen vs Mistral," the quantization choice is noise next to the architecture choice — that's the [April shootout]({% post_url 2026/2026-04-11-gemma4-local-inference %}), not this one.
- **You only ever hit it through a hosted API.** Then you're not choosing the quant at all; the provider is. This whole post is a local-inference concern.

## My take

**"Is QAT better?" turns out to be two questions with two different answers.**

*"Which of these should I actually run?"* — the QAT Q4_0, easily. Smallest file (7.20 GB), fastest response (~37s avg vs ~54s), and across six tasks it never once lost to a strong, mixed-precision community K-quant. If you want a 4-bit Gemma 4 12B on a memory budget, keep this one. That part is unambiguous, and it's the answer most people actually need.

*"Did the QAT recipe produce a better model than plain PTQ?"* — that I could not confirm, and the honest version of this post has to say why instead of pretending the speed numbers settled it. Two things are easy to mis-credit:

- **The speed is the format, not the recipe.** Google ships QAT as Q4_0 — smaller, simpler kernel, faster on this hardware. I measured a non-QAT PTQ Q4_0 with zero QAT in it: still beats the K-quant by double digits. QAT contributes nothing to throughput, because a training recipe *can't* change decode speed — the format does.
- **The behavioural suite is blind to what QAT changes.** Both quants tie at 4.5/6 because two good 4-bit quants of the same model don't diverge on valid-JSON or capital-of-France. QAT's claimed win — 54% less perplexity drop — is a distribution-level shift that pass/fail prompts can't resolve.

So the honest verdict: **the QAT checkpoint is the best 4-bit Gemma 4 12B you can run today — smallest, fastest, no behavioural regressions — but "fastest" is the Q4_0 format talking, and QAT's real contribution is exactly the part a behavioural suite can't see.** What QAT sells is insurance: the speed and size of a flat Q4_0 *without* the quality hit a flat Q4_0 usually brings. Nothing in my tests argues against that, and the model never stumbled — but to actually price the insurance you measure perplexity and KL-divergence of QAT-Q4_0 vs PTQ-Q4_0 against the BF16 original. That's the experiment that settles it, and it's the one I'd run next. Until then: run the QAT one, and credit the format for the speed.

One practical note from the testing: `max_tokens` is the only lever you have over total generation length under Ollama — thinking tokens count against it silently. If a task triggers heavy reasoning, raise it or the answer may never surface (that's what sank `exact_arithmetic` for both models). I've been bitten by this exact trap before — back in [April]({% post_url 2026/2026-04-29-nemotron-3-nano-omni %}) I called a blank Nemotron output "paralysis" before realising it was just a starved reasoning budget, and had to correct the post. Raise the cap *before* you conclude a model failed.

Know what you are doing and have fun!

3h4x

Sources:
- [Gemma 4 QAT models — Google (Jun 5, 2026)](https://blog.google/innovation-and-ai/technology/developers-tools/quantization-aware-training-gemma-4/)
- [Introducing Gemma 4 12B — Google (Jun 3, 2026)](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12b/)
- [Gemma 3 QAT Models: Bringing state-of-the-art AI to consumer GPUs — Google Developers Blog](https://developers.googleblog.com/en/gemma-3-quantized-aware-trained-state-of-the-art-ai-to-consumer-gpus/)
- [google/gemma-3-12b-it-qat-q4_0-gguf — Hugging Face](https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-gguf)
- [Gemma 4 QAT collection (Q4_0) — Hugging Face](https://huggingface.co/collections/google/gemma-4-qat-q4-0)
- [Gemma 4 12B: Specs, Benchmarks & How to Run It Locally — buildfastwithai](https://www.buildfastwithai.com/blogs/gemma-4-12b-guide)
- [llama.cpp perplexity / KL-divergence tooling](https://github.com/ggml-org/llama.cpp/tree/master/examples/perplexity)
