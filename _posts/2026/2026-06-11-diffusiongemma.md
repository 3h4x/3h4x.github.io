---
layout: post
title: "DiffusionGemma: Google ships a text diffusion model and bets the future of local LLMs isn't autoregressive"
categories: tech
tags: [ai, llm, gemma, google, diffusion, text-diffusion, mixture-of-experts, local-inference, open-source, gpu, apache-2-0]
comments: True
---

Google DeepMind dropped **DiffusionGemma** yesterday — a 26B MoE open-weights model that doesn't decode tokens one at a time. It generates **256-token blocks in parallel** via text diffusion, and on an H100 they're quoting **1000+ tokens per second**. The download is Apache 2.0, the architecture is built on the Gemma 4 backbone (the same 26B-A4B that scored well on the [Gemma 4 12B benchmarks]({% post_url 2026/2026-06-08-gemma4-qat-vs-non-qat %}) — though with a very different decoding head), and quantized it fits in **18 GB of VRAM**. So a 5090 runs it locally at 700+ tok/s. That's the speed pitch.

<!-- readmore -->

The whole thing is being marketed as "4× faster text generation," which is true and also slightly the wrong framing — what's actually happening is more interesting than a speed bump. Worth working through carefully, because the speed–quality tradeoff here is *not* like quantization, and confusing the two will lead you to use it wrong.

## What text diffusion actually is

Every LLM you've used — GPT, Gemma, Llama, Claude — is **autoregressive**. It picks one token, appends it to the context, then picks the next one conditioned on everything so far. The whole reason streaming works is that the model literally hasn't decided what it's going to say next until it's said the previous word. Decoding latency is fundamentally sequential: 100 tokens = 100 forward passes through the network.

Image diffusion models (Stable Diffusion, Imagen, DALL·E) don't work that way. They start with pure noise across the *entire* image at once and iteratively denoise it, refining all pixels in parallel. You don't generate pixel 1, then pixel 2 — every pixel is being decided about every step.

Text diffusion is that idea applied to language. Instead of emitting one token then the next, the model emits a **block of 256 tokens of pure noise** (or masked tokens), then iteratively denoises that whole block in parallel over a fixed number of steps. Every position in the block is being decided every step, conditioned on every other position. Then the next block. Then the next.

The decode loop changes shape:

```
Autoregressive (standard):
  pos 1 → forward pass → token 1
  pos 2 → forward pass → token 2
  pos 3 → forward pass → token 3
  ...
  N tokens = N forward passes

Diffusion (DiffusionGemma):
  positions 1–256 = noise
    forward pass → denoise step 1 (all 256 positions, in parallel)
    forward pass → denoise step 2 (all 256 positions, in parallel)
    ...
    forward pass → denoise step K (typically 8–32)
  → 256 tokens out in K passes
```

If K is, say, 16 — you got 256 tokens from 16 forward passes instead of 256. **That's where the 4× comes from, and where it caps.** It is not a free-lunch architecture improvement; it's a different time/quality knob. Fewer denoising steps = faster but lower quality. More steps = closer to autoregressive quality but you give the speed advantage back. Google's published 4× picks a K that gives a quality they're willing to ship; turn K up and you can claw back quality at the cost of throughput.

## The architecture and the asterisk

The backbone is Gemma 4 26B-A4B — a **mixture-of-experts** layout with about **3.8B parameters active** during any given forward pass. So the weights footprint is 26B (loaded in VRAM) but the compute per token is closer to a 4B model. That matters: dense 26B at 4-bit barely fits in 18 GB (it'd be ~13 GB for weights plus several GB of KV cache and you're tight); MoE at the same nominal size *runs* like a much smaller model on the GPU. The 18 GB number squares because most of those 26B weights are idle most of the time.

The new piece — and it's the only piece that's actually new architecturally — is the **diffusion decoding head** sitting on top of the Gemma 4 transformer. The transformer body is the same kind of thing the existing Gemma 4 family ships with. What changed is what comes out of the last layer and how it gets sampled into tokens.

That's worth being precise about because it means two things you might want to do are not the same project:

- **Fine-tune the body.** Standard Gemma 4 tooling probably applies — LoRA, full fine-tune, the existing infrastructure. The body is the body.
- **Mess with the decoder.** You're now in diffusion-research land — different sampling schedules, classifier-free guidance, the whole bag of tricks the image-diffusion world has been developing for three years. Most of that hasn't been adapted to text yet. That's where the experimental energy is going to be.

## What the speed number really means

**What Google quotes:** **1000+ tok/s on a single H100** and **700+ tok/s on an RTX 5090** — both *generation* throughput under best-case conditions (clean single-stream, optimal denoising-step count, the trained block size), not end-to-end pipeline, arbitrary context, or batched serving. On memory, the quantized model wants ~18 GB:

| Component | Memory budget |
|---|---|
| Weights (26B MoE, INT4 quantized) | ~13 GB |
| KV cache (block-based, smaller than autoregressive) | ~2–3 GB |
| Activations / scratch | ~2 GB |
| **Total** | **~18 GB** |

That fits an **RTX 5090 (32 GB)** comfortably, a **24 GB card** tight, and **a 16 GB card not at all** — a 26B model at 700+ tok/s on one consumer card is the whole local-AI pitch.

**What an M5 Max actually provides:** I ran the Q4_K_M (16.8 GB) on an **Apple M5 Max** — it holds the model comfortably. The headline "1000 tok/s" is the *in-step-parallel* rate (every one of the 256 canvas positions refined each step), and the laptop reproduces it — **~580–1330 tok/s, peaking 1328**. But that is not a wall-clock rate: the *useful* tokens-out-per-second lands at **20–80 tok/s**, the same ballpark as autoregressive Gemma 4 on the same silicon. The headline and the felt speed are different claims — full breakdown (gross vs net vs in-step-parallel, and where the gap goes) is [further down](#i-ran-it-locally-ollama-cant-llamacpp-can).

## The quality asterisk

Google's own announcement is unusually candid about the catch: **quality is lower than standard Gemma 4 at the same parameter count**. They're shipping it as experimental, not as a replacement for the autoregressive Gemma 4 series. That's the right framing.

The reason quality drops is intuitive once you see the shape: autoregressive lets the model reconsider every later token in light of every earlier one — the "I said X, so now I have to be consistent with X" effect emerges naturally because every token is a fresh forward pass over the full prior context. Diffusion has to make all 256 decisions inside one block in parallel. The model can correct itself between denoising steps, but only within the block; it can't condition step 17's noise estimate at position 200 on the actual final value of position 5 the way an autoregressive decoder conditions every later token on every earlier one. You trade decoding sequentiality for compute sequentiality, and the bits you give up tend to show up in long-range coherence: passable on short generations, drift on long ones.

This is *not* the same tradeoff as 4-bit quantization. Quantization keeps the decoding algorithm intact and approximates the weights. Diffusion keeps the weights intact and approximates the decoding algorithm. Two completely different sources of error, and a behavioural test suite tuned to catch quantization damage isn't going to catch diffusion damage — you need different probes. (I think the right probe is something like "ask for a 2000-token explanation with a callback to a fact established in the first sentence," and see if the callback is still there at the end.)

## Who this is actually for

The launch post hedges on use cases and they're right to — this isn't a drop-in Gemma 4 replacement. It's a *different shape of model* that fits a different shape of problem. Where it makes sense:

- **Interactive coding tools.** Inline completion, refactor-on-keystroke, "fix this function and show me the next four candidates" — anything where you're going to throw away most of what gets generated and wall-clock latency dominates. The quality bar for "is this completion useful" is low; the speed bar is everything.
- **Constrained-format generation.** JSON, SQL, function calls, structured outputs. The output is short, the schema is the long-range coherence (the model doesn't need to write a coherent paragraph; it needs to fill a struct), and block-parallel generation is genuinely faster end-to-end.
- **Multi-candidate exploration.** Generating 10 variations of a short text in parallel for the user to pick from. Diffusion gives you the speed budget; autoregressive at the same throughput would force you to pick a smaller model.
- **Research on text diffusion itself.** This is the first credible open-weights text diffusion model from a major lab. If you've been doing research on this and using closed APIs or hacky small open models, today is your day.

Where it doesn't:

- **Long-form generation.** The drift I mentioned above bites worst on essays, articles, multi-paragraph reasoning chains. If the task is "write me a 3000-word post about X," use autoregressive Gemma 4.
- **Reasoning-heavy chain-of-thought.** Diffusion doesn't have an obvious way to incrementally build a chain of thought the way autoregressive `<think>` blocks do. Quality on multi-step reasoning is going to be the first thing to test, and I'd expect it to lose to standard Gemma 4 there.
- **Anything where you'd reach for a 12B-class model.** The autoregressive Gemma 4 12B QAT I [tested three days ago]({% post_url 2026/2026-06-08-gemma4-qat-vs-non-qat %}) hits 39 tok/s on Apple Silicon with much better quality. If you don't have an RTX 5090 / H100 and you don't need 1000 tok/s, the 12B QAT is the safer pick today.
- **Production deployments with batched serving.** Autoregressive batches across users with grouped attention; the speed gap mostly closes. Diffusion's "faster" only really shines per-request.

## When NOT to use this

Spelling it out because experience says someone is going to read "4× faster" and reach for it for the wrong job:

- **You're already serving Gemma 4 at scale and it works.** Don't rebuild your serving stack on an experimental model to chase a single-request speed number that gets eaten by batching.
- **Your task is long-form and quality-sensitive.** Diffusion isn't the right shape for it. The quality gap is real and Google is being honest about it.
- **You don't have ≥20 GB of VRAM.** This is the same trap people fall into with 70B models — "I'll just quantize harder." With diffusion you can't quantize away the 256-token block context; the model wants what it wants.
- **You need deterministic output for testing.** Diffusion sampling has more sources of stochasticity than autoregressive temperature=0, and the determinism story for these models is still being worked out by the research community. If reproducibility matters, stay on autoregressive.

## My take

This is the most interesting open release of the month, and not because of the speed number. The speed number is fine — it's exactly the constant factor you'd predict from the architecture, and the marketing 4× is on the optimistic end of a real range. The interesting thing is that Google chose to ship a credibly-scoped diffusion text model **as an open-weights experiment**, with the honest caveats included, instead of either burying it as a research paper or wrapping it in a hosted API behind a quality story.

What I think actually happened: someone at DeepMind has been working on text diffusion for two years, the team got it to a point where it's *good enough to be useful for a narrow set of things*, and the question was whether to ship now under an experimental flag or to keep going until it's quality-competitive with autoregressive. Shipping now lets them learn from how people actually use it — which schedulers people prefer, which sampling tricks help, what tasks it's actually good at vs. their predictions. The local-inference community is going to push this in directions Google can't predict from inside the building. That's a good reason to ship.

What I'd want to see in a month:
1. **Independent benchmarks** that aren't "tok/s on a clean H100" — actual task quality measurements, ideally including long-context coherence probes, against the same parameter-count autoregressive Gemma 4.
2. **Better sampling schedules.** Image diffusion got 10–100× faster over three years by improving schedulers (DDPM → DDIM → DPM-Solver → Flow Matching). Text diffusion is going to follow the same curve and the first few months are where it moves fastest.
3. **A clear answer on chain-of-thought.** Can you do reasoning in a 256-token block? Or do you need multiple blocks and lose the parallelism benefit? Nobody knows yet.
4. **vLLM / llama.cpp support.** Right now this is a research-tooling model. Until it lands in the local-inference stacks people actually use, it's a paper with weights attached. I'd bet on llama.cpp first — the gerganov community is fast on stuff like this — but the diffusion decoding loop is a real surgery on the inference engine, not a config flag.

I'm not switching anything from Gemma 4 12B QAT to this. I am downloading it, running it through the same task suite I used for the QAT comparison, and writing up what breaks. The quality-vs-speed knob this introduces is the actual story; the headline number is the smallest interesting thing about the release.

## I ran it locally: Ollama can't, llama.cpp can

So I did exactly that. The weights are on disk and running, and the short version is: **the "research-tooling model" paragraph above held up, and the one number I was loosest about — throughput — is the one the hands-on data corrects.**

**First, the thing this started as: it does not run in Ollama.** `ollama run hf.co/unsloth/diffusiongemma-26B-A4B-it-GGUF:Q4_K_M` pulls the 16.8 GB GGUF and then dies at load with:

```
Error: unknown model architecture: 'diffusion-gemma'
```

That's [ollama#16664](https://github.com/ollama/ollama/issues/16664), still open. Stock `llama-cli` / `llama-server` reject it for the same reason — the block-diffusion decode loop isn't a sampler flag, it's a different runner. The path that works today is the DiffusionGemma PR for llama.cpp ([ggml-org/llama.cpp#24423](https://github.com/ggml-org/llama.cpp/pull/24423), by Daniel Han / Unsloth — the same people who quantized the GGUF), which adds a dedicated `llama-diffusion-cli` with the entropy-bound canvas sampler. I built it against the official repo's PR ref, pinned to head `10a2613a`, Metal on:

```
git fetch origin pull/24423/head && git checkout 10a2613a
cmake -B build -DGGML_METAL=ON -DGGML_CUDA=OFF
cmake --build build -j --target llama-diffusion-cli
```

Hardware: **Apple M5 Max**, the Unsloth **Q4_K_M (16.8 GB)**, all layers on Metal (`-ngl 99`). One caveat the runner prints up front: `on-device sampling unsupported on this backend; using host sampling` — the transformer forward passes run on the GPU, but the diffusion sampler itself falls back to the CPU. So these are *not* best-case numbers; a CUDA box does that part on-device.

### Speed: the 1000 tok/s number is real, and it's the wrong number

The marketing collapses three different throughputs into one. On my desk they differ by ~20×:

| Metric | What it counts | Mac Q4_K_M |
|---|---|---|
| **In-step parallel** | 256-canvas ÷ per-step time | **580–1330 tok/s** |
| **Gross canvas** | 256 × blocks ÷ wall time | 45–150 tok/s |
| **Net useful** | trimmed answer tokens ÷ wall time | **20–80 tok/s** |

The **in-step-parallel** rate is the "1000+ tok/s on an H100" framing — and a **laptop reproduces it** (peak 1328 tok/s on the JSON task, ~920 average on the canvas-filling probe). That's legitimate: all 256 canvas positions really are refined every step. It's just not a wall-clock rate. The **net useful** rate — actual tokens out per second of waiting — lands at **20–80 tok/s**, the *same ballpark as the autoregressive Gemma 4 12B QAT I clocked at 39 tok/s* on the same kind of silicon.

The trap is reading that in-step-parallel number as a wall-clock rate: the "order of magnitude more throughput on identical silicon" you'd infer from it is true for canvas positions and false for useful tokens. On short answers the 256-token canvas is mostly masked and trimmed, the thinking channel (below) burns the rest, and the wall-clock edge over autoregressive **evaporates**. The 4× is real only when the output actually fills the canvas — long, dense, low-entropy generation (the "1–200" probe hit 146 gross tok/s in 6 steps/block). It is *not* real for the short structured outputs I'd actually reach for this model to do. And it's context-sensitive exactly like autoregressive: a ~1.5k-token recall prompt dragged in-step-parallel from ~1250 down to **583 tok/s**, because every denoising step is a full forward pass over `[prompt | canvas]`.

### Quality: the thinking channel is the whole story

DiffusionGemma-it doesn't just emit an answer. It writes a reasoning trace in a `<|channel>thought` block, then the answer after a `<channel|>` delimiter — *all inside the same 256-token canvas*. When it fits, it's clean. The JSON task, verbatim:

```
<|channel>thought
*   Target: Warsaw. Keys: city, population, is_capital...
<channel|>{"city": "Warsaw", "population": 1793000, "is_capital": true}
```

Same task suite as the [QAT post]({% post_url 2026/2026-06-08-gemma4-qat-vs-non-qat %}), median of 3, `-n 1024` (four canvas blocks of headroom):

| Task | Verdict | Net tok/s | Notes |
|---|---|---|---|
| code_from_spec | ✅ pass | 81 | correct `merge_intervals` |
| strict_json | ✅ pass | 69 | exact keys, valid JSON |
| multilingual_pl | ✅ pass | 49 | PL→EN + register shift |
| long_context_recall | ✅ pass | 20 | "Paris" |
| constraint_conflict | ⚠️ partial | 38 | **stuck in `thought`, never reached the answer** |
| exact_arithmetic | ❌ fail | 30 | **stuck in `thought`, no final number** |

The two non-passes are the same failure, and it's the one I flagged as the thing to test: **multi-step reasoning doesn't fit the block.** On the arithmetic and the counting-constraint tasks the model spends the entire canvas — all four blocks, 78–94 denoising steps — *thinking*, and the denoise hits the block budget before it ever crosses the `<channel|>` delimiter into a final answer. It's not that it reasons and gets the wrong number; it never finishes reasoning. An autoregressive `<think>` block grows until it's done; a fixed 256-token canvas does not. That's the architectural wall, and you can literally watch it hit with `--diffusion-visual`.

### The 30-matrix: 21/30 — a discipline score, not a capability score

The task suite above is my own rubric. The fairer test you'd want: run DiffusionGemma on the **same 30-cell matrix** I put Fable 5 and Opus 4.8 through in the [Fable post]({% post_url 2026/2026-06-10-claude-fable-5-benchmark %}) — ten adversarial tasks (bug fixes graded by *executing the tests*, a regex graded against 16 trick inputs, SQL run against a NULL-trap fixture, reasoning traps where the pattern-matched answer is wrong), three runs each, strict grading. Same `TASKS`, same graders, imported straight from that harness; the only thing swapped is the model call. I grade DiffusionGemma's final `<channel|>` answer — the `thought` trace is the analog of the hidden reasoning the API models never expose.

| Task | Fable 5 | Opus 4.8 | **DiffusionGemma 26B** |
|---|---|---|---|
| bugfix_merge | 3/3 | 2/3 | **3/3** |
| bugfix_bsearch | 3/3 | 3/3 | **3/3** |
| regex_ipv4 | 3/3 | 2/3 | **0/3** |
| sql_null_trap | 3/3 | 2/3 | **3/3** |
| json_strict | 3/3 | 2/3 | **3/3** |
| trap_batball | 3/3 | 0/3 | **3/3** |
| trap_jugs | 3/3 | 3/3 | **3/3** |
| trap_monty_random | 3/3 | 3/3 | **0/3** |
| trace_mutable_default | 3/3 | 3/3 | **0/3** |
| arith_exact | 3/3 | 2/3 | **3/3** |
| **Total (strict)** | **30/30** | **22/30** | **21/30** |

Read that table the wrong way and it says a 4-bit 26B model on a laptop ties Opus 4.8. It doesn't — and it's worth being blunt about why. **This suite scores instruction-discipline and a few reasoning traps; it does not score capability.** Ten single-shot, strict-format prompts say nothing about what Opus is actually for — multi-step reasoning, long-context coherence, tool use, holding a 200-turn task together — and on every one of those axes Opus 4.8 is in a different class entirely. The 21-vs-22 reflects two narrow things only: who obeys "reply with ONLY the answer" to the letter, and who walks into a trick question.

Start with Opus, because 22/30 badly *understates* it. Most of its eight misses weren't wrong answers — they were the **right answer ruined by a forbidden line of deliberation**: a correct regex/SQL/bugfix preceded by a "the bug is…" sentence the strict grader throws out. Graded leniently it's **26/30**, and on raw capability it had the correct solution in nearly all thirty (the Fable post spelled this out). Opus's whole gap is *discipline*, not smarts. DiffusionGemma's two 0/3s are the mirror image — the right answer stranded in the **thought** channel, never delivered: on `regex_ipv4` it derives a correct IPv4 pattern, writes "*Wait, the user asked for ONLY the regex pattern*," then keeps deliberating until the 4-block canvas runs out 83 steps in. Same root cause (a separate reasoning channel), opposite spill — Opus leaks reasoning *into* the answer, DiffusionGemma buries the answer *behind* it.

`trap_monty_random` is the same starvation (stuck thinking through the random-host variant, 64 steps, no delivery). Exactly **one** failure is a genuine wrong answer: `trace_mutable_default`, where it printed `[1] [1, 2]` instead of `[1, 2] [1, 2]` — it missed that both calls return the *same* aliased list, so the first print should already show the second append. A real conceptual miss, not a plumbing one.

The one that made me sit up: **`trap_batball` — DiffusionGemma 3/3, Opus 0/3.** The local model read "the bat costs $1.00" literally; Opus pattern-matched the famous "$1.00 *more than*" riddle and answered 5 all three runs. Fun, and a fair point about reading the question in front of you — but it's *one* trap in *one* ten-task suite, not evidence the local model reasons better. Where the suite has teeth, DiffusionGemma is genuinely competent on **short, well-specified work**: both bug fixes executed clean against their test suites, the SQL handled the NULL trap, the discount-then-tax arithmetic landed 112.57 to the cent. That's the whole honest claim — a quantized 26B you can run on your own machine is *usable* on this narrow slice — and it falls apart the moment a task needs sustained reasoning or long output (its two 0/3s here, and the constraint and arithmetic tasks left stuck mid-thought earlier). It is not, in any way that matters for real work, a substitute for Opus 4.8. (`matrix` mode in the [script](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-06-11-diffusiongemma.py) reproduces it; it imports the Fable suite so there's one source of truth for the tasks.)

### Grading my predictions

- ✅ **"Constrained-format generation… genuinely faster end-to-end."** JSON, code, short translation: pass and clean, and the in-step-parallel rate is real on these.
- ✅ **"Reasoning-heavy chain-of-thought… going to lose to standard Gemma 4."** Worse than I guessed — it doesn't reason *badly*, it runs out of canvas *mid-reasoning*.
- ✅ **"llama.cpp first… a real surgery on the inference engine, not a config flag."** Exactly: a separate binary, a separate sampler, pinned to an unmerged PR.
- ❌ **The "order of magnitude faster" framing.** Real only if you count canvas positions; useful-token throughput is autoregressive-parity for the short outputs this model is actually for.

The harness shells out to `llama-diffusion-cli`, parses the three throughput numbers, and scores the same rubric — it's in [`scripts/2026-06-11-diffusiongemma.py`](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-06-11-diffusiongemma.py) (`bench` and `probe` modes). Build recipe above; `hf download unsloth/diffusiongemma-26B-A4B-it-GGUF --include "*Q4_K_M*.gguf"` for the weights.

**Bottom line, now with the weights on disk:** it's a real, runnable, genuinely-different model — and the thing to internalize is that "1000 tok/s" and "the answer arrives sooner" are *different claims*. The first is true on a laptop. The second is true only when your output is long and low-entropy. For the short structured jobs where I'd want the speed, the thinking channel eats it. Still not switching off 12B QAT — but now I can tell you exactly why, and it isn't the reason the launch post implies.

Know what you are doing and have fun!

3h4x

Sources:
- [DiffusionGemma: 4x faster text generation — Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/diffusion-gemma-faster-text-generation/)
- [unsloth/diffusiongemma-26B-A4B-it-GGUF — Hugging Face](https://huggingface.co/unsloth/diffusiongemma-26B-A4B-it-GGUF) (the GGUF I tested)
- [DiffusionGemma llama.cpp runner — ggml-org/llama.cpp#24423](https://github.com/ggml-org/llama.cpp/pull/24423) (`llama-diffusion-cli`, by Daniel Han / Unsloth)
- [Support GGUF models with diffusion-gemma architecture — ollama#16664](https://github.com/ollama/ollama/issues/16664) (why `ollama run` fails)
- [Benchmark harness for this post — scripts/2026-06-11-diffusiongemma.py](https://github.com/3h4x/3h4x.github.io/blob/master/scripts/2026-06-11-diffusiongemma.py)
- [The 30-matrix it's scored against — Fable 5 vs Opus 4.8]({% post_url 2026/2026-06-10-claude-fable-5-benchmark %})
- [Google AI Releases DiffusionGemma — MarkTechPost](https://www.marktechpost.com/2026/06/10/google-ai-releases-diffusiongemma-a-26b-moe-open-model-using-text-diffusion-for-up-to-4x-faster-generation/)
- [Google DeepMind releases DiffusionGemma — Digg](https://digg.com/tech/z4mvl1gb)
- [DiffusionGemma: Diffusion-Based Open Model for Faster Text Generation — Analytics Vidhya](https://www.analyticsvidhya.com/blog/2026/06/diffusiongemma-diffusion-based-open-model-for-faster-text-generation/)
- [DiffusionGemma Brings Faster Text Generation To Local AI Workflows — Open Data Science](https://opendatascience.com/diffusiongemma-brings-faster-text-generation-to-local-ai-workflows/)
- [Google bets parallel text generation can upend the economics of local AI — Startup Fortune](https://startupfortune.com/google-releases-diffusiongemma-and-bets-that-parallel-text-generation-can-upend-the-economics-of-local-ai/)
- [DiffusionGemma Complete Guide — AI Made Tools (2026)](https://www.aimadetools.com/blog/diffusiongemma-complete-guide/)
