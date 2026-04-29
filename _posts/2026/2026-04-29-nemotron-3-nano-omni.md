---
layout: post
title: "Nemotron 3 Nano Omni: one model that sees, hears, reads, and clicks"
categories: tech
tags: [ai, llm, nvidia, nemotron, multimodal, mixture-of-experts, mamba, open-source, agents, vllm]
comments: True
---

Nvidia dropped Nemotron 3 Nano Omni yesterday — a 30B-A3B mixture-of-experts model that takes text, images, audio, video, documents, charts, and screenshots of GUIs as input and emits text. It's the multimodal sibling of the Nemotron 3 Nano 4B I [tested against Gemma 4 a couple of weeks back]({% post_url 2026/2026-04-11-gemma4-local-inference %}). The 4B was text-only with a reasoning mode. This one is the perception layer of the family.

<!-- readmore -->

## Why this is interesting and why most of the hype isn't

Most AI agent stacks today look like this: speech-to-text in one box, vision encoder in another, an LLM doing the reasoning, and glue code shuttling embeddings or transcripts between them. Every hop is a lossy serialization. Every hop is one more thing that times out, costs money, or drifts out of sync.

Omni models try to collapse that. The reasoning model *is* the audio model *is* the vision model. One context, one cache, one inference pass. Nvidia's pitch is the obvious one — fewer pipelines, lower latency, more context preserved between modalities. The thing they're not as loud about: this only matters if your task actually crosses modalities inside a single decision. A pipeline that does ASR-then-summarize doesn't need an omni model. An agent that watches a screen recording, reads what's on screen, listens to what the user said, and decides what to click next — that benefits.

The "up to 9x throughput vs comparable open omni models" number is a vendor benchmark against a moving target. I'll come back to that.

## The architecture

This is the part I actually find interesting, because it's an unusual stack:

```
┌─────────────────────────────────────────────────────┐
│  Inputs                                             │
│  ─────                                              │
│  text  ──┐                                          │
│  image ──┤── C-RADIOv4-H vision encoder ──┐         │
│  video ──┘                                ├──► LLM  │
│  audio ──── Parakeet-TDT-0.6B-v2 ─────────┘         │
│  GUI screenshot ── dedicated GUI-trained visual ────┤
│                                                     │
│  Backbone (interleaved):                            │
│   23× Mamba SSM layers   (long-context)             │
│   23× MoE layers          (128 experts, top-6)      │
│    6× grouped-query attention layers                │
│                                                     │
│  Output: text                                       │
│  Context: 256K tokens                               │
└─────────────────────────────────────────────────────┘
```

A few things to call out:

- **Hybrid Mamba-Transformer.** Most of the long-context work is done by 23 Mamba selective state-space layers, with only 6 GQA layers sprinkled in. This is the same trick the 4B Nano uses, scaled up. Mamba scales linearly with context length where attention scales quadratically, which is how they get to 256K tokens at this parameter budget without burning the GPU to the ground.
- **Top-6 of 128 experts.** 30B total weights, ~3B active per token. You get the knowledge capacity of a much larger model and the inference cost of a small one, *as long as your batching plays nicely with expert routing*. It does not, in practice, give you 30B-quality reasoning at 3B speed for free — the routing imbalance shows up under load.
- **A dedicated GUI vision system.** This is the bit aimed squarely at computer-use agents. The model has been trained to understand screenshots of applications, dropdowns, buttons, and forms — not just natural images. If you've tried to get a generic VLM to reliably click "Save" on a Salesforce screen, you know why a GUI-tuned encoder matters.
- **Output is text only.** No speech generation, no image generation. It listens and reads; it does not talk back in audio.

## Running it

Three realistic options depending on what you have:

**1. Hosted API, zero setup:**

```bash
curl https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "messages": [{"role":"user","content":"Describe this screenshot."}],
    "max_tokens": 512
  }'
```

OpenRouter, fal, DeepInfra, Crusoe, SageMaker JumpStart, and Vultr all picked it up at launch. Pricing varies — Clarifai is advertising 400 tok/s on their reasoning engine, which is the closest I've seen to "this is what the throughput claim looks like in practice."

**2. Self-host with vLLM:**

```bash
pip install -U vllm

vllm serve nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16 \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.9 \
  --tensor-parallel-size 1
```

vLLM has zero-day support. BF16 weights need around 60GB of VRAM. There's an FP8 build that fits in ~32GB, which puts a single L40S or 4090 (with --max-model-len cranked down) within reach.

**3. Local on a Mac:**

```bash
ollama pull nemotron3
```

Or grab the GGUF quants from the unsloth mirror on Hugging Face. The 4-bit quant runs in roughly 25GB of unified memory — comfortable on a 36GB M-series machine, tight on 32GB. It is *not* an edge model in the Gemma E4B sense. It's a "fits on a workstation" model.

## Past the benchmark slide

Nvidia's announcement leads with leaderboard wins across documents, video, and audio. I'd rather poke the model with code than read a slide deck — a half-hour of running real prompts against it tells me more about how it'll behave in something I'm actually building than any benchmark table.

## Three empirical tests on local hardware

LM Studio, port 1234, OpenAI-compatible endpoint. `nvidia/nemotron-3-nano-omni` (4-bit GGUF, ~25GB unified memory). Same single-shot, no-retry methodology as the [Gemma 4 post]({% post_url 2026/2026-04-11-gemma4-local-inference %}).

### Test 1 — punctuation-paradox regression (and a correction)

The April 11 post had Nemotron 3 Nano 4B return blank output on the "no punctuation, exactly 4 words, numbered 1. 2. 3." prompt. I called it *"Paralysis, not a resource issue."* That conclusion was wrong, and re-running it on the 30B Omni surfaced the bug.

| Model | max_tokens | Outcome | Reasoning tokens | Wall time |
|---|---|---|---|---|
| Nemotron 3 Nano 4B | 500 (April 11) | blank | (cap hit) | — |
| Nemotron 3 Nano 4B | 4000 | **correct** | 579 | 19s |
| Omni 30B-A3B | 800 | blank (cut mid-thought) | 799 | 37s |
| Omni 30B-A3B | 4000 | **correct** | 1188 | **237s** |

Both models *do* escape the loop — they just need more headroom than 500 tokens. Both arrive at the same resolution: drop the period after the digit, treat digits as not-punctuation, deliver four words. So the original "paralysis" framing was wrong; it's a budget issue, and I should have raised `max_tokens` before drawing a conclusion. Correction noted.

The more interesting number is the latency ratio. Omni uses **2x more reasoning tokens** than the 4B for the same task, and takes **~12x more wall-clock time** at single-batch local inference. MoE routing at batch=1 is not free, and the "3B active per token" claim does not translate into 3B-class latency on a workstation. This matches the throughput skepticism in the architecture section — those numbers come from heavy batching that single-user local inference doesn't see.

### Test 2 — GUI screenshot read (3 questions)

Fed a screenshot of one of my own dashboards (a projects table with status icons, a notification bell, and a Release button). Three questions in one prompt:

1. How many rows show a red error status icon?
2. Is there a Release button visible? Which corner?
3. What is the number on the bell-icon badge top-right?

**Result: 2/3 correct.** Nailed the error count (1) and the Release button (bottom-right). Misread the bell badge as "2" when it was clearly "8" — a small bright-red numeral. Wall time ~100s, 1374 reasoning tokens.

I wanted to side-by-side this against Gemma 4 E4B. LM Studio rejected the image input for Gemma's GGUF build with HTTP 400 — vision support depends on how the model was packaged, not just the model card. So no comparator on this one. Worth flagging if you're planning to swap models in an existing pipeline: "supports vision" on the model card and "accepts vision in your runtime" are different statements.

### Test 3 — numeric extraction from a stats dashboard

Same dashboard family, the stats page. Asked for: two big-number cards (Total Tokens, Cache Reads), the top row of the data table (project name + Runs + Tokens + Cost), and which time-range tab was selected (24h / 7d / 30d / all).

**Result: 2/4.**

| Field | Ground truth | Omni answer | Verdict |
|---|---|---|---|
| Total Tokens (big card) | 1.28B | 1.28B | ✓ |
| Cache Reads (big card) | 1.20B | 1.20B | ✓ |
| Top row | tamtam, 1,158, 716.35M, $410 | common, 1, 276.0kM, $4.10 | ✗ (all four wrong) |
| Selected tab | 30d (highlighted) | 24h | ✗ |

Pattern across tests 2 and 3: **large high-contrast text reads cleanly; small numerals, dense tabular rows, and visual-state cues (a highlighted tab, a tiny badge) miss.** That's a real limitation for computer-use agents, because most of the work in a real app is happening in dense tables and subtle UI state, not in the hero number on the dashboard.

The dedicated GUI vision encoder helps with structure (it correctly identified the Release button location, the table layout, the card structure). It does not, in my one-day testing, solve the small-numeral OCR problem that has dogged generic VLMs.

### What I didn't test yet

- **Audio.** LM Studio's omni audio path is engine-dependent and I didn't get a clean run. The vLLM hosted path is the right place for that test; a future post.
- **Long-context document needle.** Pushing the 256K context to find a buried fact requires a fixture I don't have today.
- **Pipeline comparison.** The actual omni pitch — single model vs. stitched Whisper+VLM+LLM — needs a cross-modal task. Same future post.

So treat what's here as the screen-reading slice of the story, not the full evaluation.

## Where the throughput number comes from

"Up to 9x higher throughput than comparable open omni models" — three things going on here:

1. **Mamba layers don't quadratically blow up on long context.** Process a 30-minute video and the attention-only models choke; this one doesn't.
2. **MoE means most of the weights are dormant per token.** A 3B active forward pass is genuinely cheap.
3. **The comparison set is "comparable open omni models with similar interactivity."** That phrase is doing real work. There are not many open omni models. Nvidia gets to pick the baseline. Be skeptical of the multiplier and trust the underlying architecture story instead.

The 3x throughput / 2.75x lower compute number for video reasoning is more useful — it's tied to a specific task family.

## Where this fits and where it doesn't

Updated with what I just measured:

**Use it for:**
- Document intelligence over long PDFs with mixed text, tables, and figures (untested by me; plausible from architecture)
- Meeting/podcast assistants that consume audio and video in one pass (untested)
- Anything where you currently run separate ASR + VLM + LLM *and the modalities cross inside a single decision*

**Use it carefully for:**
- Computer-use agents. Layout understanding works; reading dense tables and small numerals does not (test 3 read four out of four table fields wrong). Pair it with OCR for the content, use Omni for the structure.

**Don't use it for:**
- Pure text reasoning. The 4B Nano is **12x faster** on the same prompt and arrived at the same answer (test 1).
- Anything that needs speech output. This is a perception model.
- Latency-critical single-turn chat. Reasoning mode burned 4 minutes on a 4-word-per-line list at batch=1. Turn it off or use the non-reasoning variant.
- Edge deployment in the literal sense. 25GB minimum is workstation territory.

## The license matters

NVIDIA Open Model License. Commercial use is allowed. Open weights, datasets, training recipes — the whole stack, not just the checkpoint. That's a meaningful difference from "open-weights-but-the-data-is-secret" releases. If you fine-tune this for your domain, you're not building on a black box.

There are still terms to read. "Open" in the Nvidia sense is not "Apache 2.0." If you're shipping this in a product, your legal team gets a turn before your platform team does.

## My take after the first runs

The architecture is the story. A hybrid Mamba-MoE-attention backbone with a GUI vision encoder, open data and recipes, commercial license, 30B-A3B — that's a useful building block. The "9x" stuff is the kind of number that gets quoted in slide decks and quietly forgotten when someone tries to reproduce it on their own hardware: at single-batch local inference, the 4B Nano is **12x faster** than Omni on the same reasoning prompt.

For agentic computer-use work, the screen-reading results are honest — and middling. Structure (where buttons are, what the layout is) is solid. Small numerals and visual state miss often enough that you cannot trust this model to read a dashboard or count a notification badge unaided. Either you give it screenshots cropped to the high-contrast region you care about, or you pair it with a smaller, faster OCR model and have Omni reason over the OCR text rather than the pixels.

This is where I expected the dedicated GUI encoder to do better than a generic VLM, and on layout it does. On reading the actual content inside the layout, it's not a step-change. That's the finding that wouldn't have shown up on the launch leaderboards — those test one skill at a time (read text from an image, summarize a video, hold a voice chat). A real computer-use agent has to do several at once on the same screen, and that's where the cracks appear.

I'll come back with audio and the stitched-pipeline comparison when I have the right harness. For now: **architecturally exciting, latency-disappointing at batch=1, and not yet a drop-in replacement for the perception layer of a computer-use agent.**

## The harness

Same shape as the April 11 script — OpenAI-compatible local endpoint, single-shot, prints timing and reasoning-token counts. Vision tests use the standard `image_url` data-URI form.

```python
import base64, json, urllib.request, time

BASE = "http://localhost:1234/v1/chat/completions"
MODEL = "nvidia/nemotron-3-nano-omni"  # also tested: nvidia/nemotron-3-nano-4b

def call(messages, max_tokens=4000, temperature=0.2):
    payload = json.dumps({
        "model": MODEL, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(BASE, data=payload,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    dt = time.time() - t0
    u = d["usage"]
    r_tok = u.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    print(f"{dt:.1f}s  {u['completion_tokens']}t  reasoning={r_tok}")
    print(d["choices"][0]["message"].get("content", ""))
    return d

# Test 1 — punctuation paradox (text-only, regression vs April 11)
call([{"role": "user", "content":
       "List exactly 3 benefits of exercise.\nRules:\n- Numbered list (1. 2. 3.)\n"
       "- Each item: exactly 4 words\n- No punctuation of any kind\n- No introductory sentence"}])

# Test 2/3 — vision: pass any screenshot you want to probe
def vision_call(image_path, question):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return call([{"role": "user", "content": [
        {"type": "text", "text": question},
        {"type": "image_url", "image_url":
         {"url": f"data:image/png;base64,{b64}"}},
    ]}], max_tokens=2000)
```

The model id depends on what your runtime exposes — `curl localhost:1234/v1/models` to list. `max_tokens=4000` matters: 500 (the April 11 default) is not enough for reasoning mode to escape an internal contradiction, which is what tripped the 4B in the prior post.

3h4x

Sources:
- [NVIDIA Technical Blog: Nemotron 3 Nano Omni](https://developer.nvidia.com/blog/nvidia-nemotron-3-nano-omni-powers-multimodal-agent-reasoning-in-a-single-efficient-open-model/)
- [NVIDIA Blog: Launch announcement](https://blogs.nvidia.com/blog/nemotron-3-nano-omni-multimodal-ai-agents/)
- [Hugging Face blog: Long-context multimodal intelligence](https://huggingface.co/blog/nvidia/nemotron-3-nano-omni-multimodal-intelligence)
- [Nemotron 3 Nano Omni technical report (PDF)](https://research.nvidia.com/labs/nemotron/files/NVIDIA-Nemotron-3-Omni-report.pdf)
- [vLLM blog: Running Nemotron Omni](https://vllm.ai/blog/nemotron-omni)
- [AWS: Available on SageMaker JumpStart](https://aws.amazon.com/blogs/machine-learning/nvidia-nemotron-3-nano-omni-model-now-available-on-amazon-sagemaker-jumpstart/)
- [Crusoe Managed Inference availability](https://www.crusoe.ai/resources/blog/nvidia-nemotron-3-nano-omni-now-available)
