#!/usr/bin/env python3
"""
Benchmark harness for: Gemma 4 QAT vs non-QAT comparison
Post: 2026-06-08-gemma4-qat-vs-non-qat.md

Two modes:

  bench  — full task suite (correctness + speed) for a single model
  probe  — fast decode-speed probe across one or more models

Usage:
  # Full task suite for one model:
  python3 2026-06-08-gemma4-qat-vs-non-qat.py bench hf.co/google/gemma-4-12B-it-qat-q4_0-gguf:latest
  python3 2026-06-08-gemma4-qat-vs-non-qat.py bench hf.co/lmstudio-community/gemma-4-12B-it-GGUF:Q4_K_M

  # Decode-speed probe (defaults to the three models compared in the post):
  python3 2026-06-08-gemma4-qat-vs-non-qat.py probe
  python3 2026-06-08-gemma4-qat-vs-non-qat.py probe <model> [<model> ...]

The probe isolates format vs. recipe: is the QAT model's speed advantage from QAT,
or from the Q4_0 format it ships in? QAT changes weight *values*, not the
format/size/speed. So a plain PTQ Q4_0 should match the QAT Q4_0 on speed, and
both should beat Q4_K_M. The probe runs generation-heavy, think-light prompts so
the thinking budget doesn't dominate and the number reflects sustained decode speed.

Both modes manage the environment: stop any running model, then warm up the
target at CONTEXT_SIZE tokens (via a dummy request) before measuring.

Requires Ollama running on localhost:11434.
"""
import json, time, urllib.request, sys, subprocess, datetime

BASE         = "http://localhost:11434/v1/chat/completions"
CONTEXT_SIZE = 32768

DEFAULT_BENCH_MODEL  = "hf.co/google/gemma-4-12B-it-qat-q4_0-gguf:latest"
DEFAULT_PROBE_MODELS = [
    "hf.co/google/gemma-4-12B-it-qat-q4_0-gguf:latest",
    "hf.co/lmstudio-community/gemma-4-12B-it-GGUF:Q4_0",
    "hf.co/lmstudio-community/gemma-4-12B-it-GGUF:Q4_K_M",
]


def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")


def ollama(*args):
    result = subprocess.run(["ollama", *args], capture_output=True, text=True)
    return result.stdout.strip()


def prepare(model):
    """Stop any running model, then pre-load `model` at CONTEXT_SIZE via a dummy request."""
    print(f"[{ts()}] [env] Stopping any running models...", flush=True)
    ollama("stop", model)
    time.sleep(2)
    print(f"[{ts()}] [env] Pre-loading {model} at context={CONTEXT_SIZE} with a dummy request...", flush=True)
    # Send a minimal request to force Ollama to load the model at the right context
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "options": {"num_ctx": CONTEXT_SIZE},
    }).encode()
    req = urllib.request.Request(BASE, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        r.read()
    print(f"[{ts()}] [env] Ready.\n", flush=True)


def call(model, prompt, max_tokens=8192, temperature=0.0):
    """
    Single call via Ollama OpenAI-compatible API.
    Handles thinking models — Ollama exposes thinking via delta.thinking field.
    num_ctx is passed in options to ensure consistent context window.
    """
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "options": {"num_ctx": CONTEXT_SIZE},
    }).encode()
    req = urllib.request.Request(BASE, data=payload,
                                 headers={"Content-Type": "application/json"})

    t0 = time.time()
    ttft = None
    content_chunks = []
    reasoning_chunks = []
    n_content = 0
    n_reasoning = 0
    finish_reason = None
    usage_completion_tokens = None  # true total from Ollama usage field (includes hidden thinking)

    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data: "):
                continue
            line = line[6:]
            if line == "[DONE]":
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Capture usage stats — Ollama sends a final chunk with empty choices[] when stream_options.include_usage=true
            usage = event.get("usage") or {}
            if usage.get("completion_tokens"):
                usage_completion_tokens = usage["completion_tokens"]
            choices = event.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta", {})
            content = delta.get("content")
            # Ollama exposes thinking via delta.thinking; fallback: reasoning_content
            reasoning = delta.get("thinking") or delta.get("reasoning_content")
            if content:
                if ttft is None:
                    ttft = time.time() - t0
                content_chunks.append(content)
                n_content += 1
            if reasoning:
                if ttft is None:
                    ttft = time.time() - t0
                reasoning_chunks.append(reasoning)
                n_reasoning += 1

    dt = time.time() - t0
    decode_time = max(dt - (ttft or dt), 1e-9)
    n_total = usage_completion_tokens or (n_content + n_reasoning)
    # content_tok_per_s: visible output speed (tokens arriving after TTFT, user-visible experience)
    content_tok_per_s = round(n_content / decode_time, 1) if n_content > 0 else 0.0
    # total_tok_per_s: overall throughput including hidden thinking (total tokens / total time)
    total_tok_per_s = round(n_total / dt, 1) if (n_total > 0 and dt > 0) else 0.0

    return {
        "ttft_s":               round(ttft or dt, 3),
        "total_s":              round(dt, 2),
        "tok_content":          n_content,
        "tok_reasoning":        n_reasoning,
        "tok_total_reported":   usage_completion_tokens,
        "content_tok_per_s":    content_tok_per_s,
        "total_tok_per_s":      total_tok_per_s,
        "finish_reason":        finish_reason,
        "output":               "".join(content_chunks),
        "reasoning":            "".join(reasoning_chunks),
    }


# ---------------------------------------------------------------------------
# bench mode: full task suite (correctness + speed) for a single model
# ---------------------------------------------------------------------------

TESTS = [
    {"name": "code_from_spec",
     "prompt": "Write a Python function `merge_intervals(intervals)` that merges overlapping "
               "closed integer intervals given as a list of [start, end] pairs and returns them "
               "sorted by start. Handle the empty list. Return only the function, no explanation."},
    {"name": "strict_json",
     "prompt": "Return ONLY valid JSON, no markdown, no prose, with exactly these keys: "
               "city (string), population (integer), is_capital (boolean). Use Warsaw."},
    {"name": "multilingual_pl",
     "prompt": "Przetłumacz na angielski, a potem podaj wersję nieformalną (na 'ty'): "
               "'Szanowni Państwo, uprzejmie informuję, że wdrożenie zostało zakończone pomyślnie.'"},
    {"name": "constraint_conflict",
     "prompt": "List exactly 3 benefits of exercise.\nRules:\n- Numbered list (1. 2. 3.)\n"
               "- Each item: exactly 4 words\n- No punctuation of any kind\n- No introductory sentence"},
    {"name": "exact_arithmetic",
     "prompt": "A tank holds 1,000 L. It leaks 12.5 L/hour and is refilled 40 L every 3 hours "
               "(refill happens at the end of each 3rd hour). How many litres after 9 hours? "
               "Give the final number on its own line."},
    # long_context_recall requires a loaded context window; adjust filler count if context is < 8k tokens
    {"name": "long_context_recall",
     "prompt": ("Read the following carefully and answer the question at the end.\n\n"
                "Context: The capital of France is Paris. " +
                "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 150 +
                "\n\nQuestion: What is the capital of France? Answer with only the city name.")},
]


def score(test_name, output, reasoning):
    """Rough pass/partial/fail rubric. Returns (score, note)."""
    o = output.strip()
    r = reasoning.strip()
    has_any = bool(o or r)
    if test_name == "code_from_spec":
        combined = o + r
        if "def merge_intervals" in combined and "return" in combined:
            return "pass", "function present" + (" (in reasoning)" if "def merge_intervals" not in o else "")
        return "fail", "function missing"
    if test_name == "strict_json":
        for src in (o, r):
            try:
                d = json.loads(src.strip())
                if set(d.keys()) == {"city", "population", "is_capital"}:
                    return "pass", "exact keys" + (" (in reasoning)" if src is r else "")
                return "partial", f"keys: {list(d.keys())}"
            except Exception:
                pass
        return "fail", "not valid JSON"
    if test_name == "multilingual_pl":
        if "implementation" in o.lower() and ("ty" in o.lower() or "informal" in o.lower() or "hi" in o.lower()):
            return "pass", "translation + register shift present"
        if has_any:
            return "partial", "something produced"
        return "fail", "empty"
    if test_name == "constraint_conflict":
        lines = [l for l in o.splitlines() if l.strip()]
        if len(lines) >= 3 and all(len(l.split()) <= 6 for l in lines[:3]):
            return "partial", f"{len(lines)} lines"
        if has_any:
            return "partial", "non-empty output"
        if r:
            return "partial", "reasoning only, no output (thinking model detected contradiction)"
        return "fail", "empty"
    if test_name == "exact_arithmetic":
        # correct answer: 1000 - 9*12.5 + 3*40 = 1000 - 112.5 + 120 = 1007.5
        # prompt asks for the number on its own line in visible output — reasoning-only counts as partial
        correct = "1007.5"
        if correct in o:
            return "pass", f"correct answer {correct} in output"
        if correct in r:
            return "partial", f"correct answer {correct} in reasoning only (no visible output)"
        if has_any:
            return "fail", f"wrong answer (expected {correct})"
        return "fail", "empty"
    if test_name == "long_context_recall":
        if "paris" in (o + r).lower():
            return "pass", "Paris recalled"
        if has_any:
            return "fail", "wrong answer"
        return "fail", "empty (likely context overflow)"
    return "unknown", ""


def cmd_bench(model):
    out_path = f"results-{model.replace('/', '_').replace(':', '_')}.jsonl"
    prepare(model)

    print(f"\n{'='*60}")
    print(f"[{ts()}] MODEL: {model}  |  context={CONTEXT_SIZE}")
    print(f"{'='*60}\n")

    results = []
    with open(out_path, "w") as f:
        for t in TESTS:
            print(f"[{ts()}] [{t['name']}] warm-up...", flush=True)
            call(model, t["prompt"])  # discard warm-up
            runs = [call(model, t["prompt"]) for _ in range(3)]
            best = sorted(runs, key=lambda r: r["total_s"])[1]  # median
            verdict, note = score(t["name"], best["output"], best["reasoning"])
            rec = {"model": model, "test": t["name"], **best, "verdict": verdict, "note": note}
            f.write(json.dumps(rec) + "\n")
            results.append(rec)
            reported = best.get("tok_total_reported")
            hidden = (reported - best["tok_content"] - best["tok_reasoning"]) if reported else 0
            thinking_note = (f"  [THINKING: {best['tok_reasoning']} streamed"
                             + (f", {hidden} hidden" if hidden > 0 else "")
                             + "]") if (best["tok_reasoning"] > 0 or hidden > 0) else ""
            print(f"[{ts()}] [{t['name']:25}] ttft={best['ttft_s']}s  "
                  f"content={best['tok_content']}tok  total={reported}tok  "
                  f"content_tok/s={best['content_tok_per_s']}  total_tok/s={best['total_tok_per_s']}  "
                  f"[{verdict.upper()}]{thinking_note}")
            if best["output"]:
                print(f"  OUTPUT: {best['output'][:300]}")
            elif best["reasoning"]:
                print(f"  REASONING: {best['reasoning'][:300]}")
            print()

    print(f"[{ts()}] Results saved to {out_path}")
    print(f"\n[{ts()}] SCORECARD:")
    for r in results:
        print(f"  {r['test']:25} {r['verdict'].upper():8} {r['note']}")


# ---------------------------------------------------------------------------
# probe mode: fast decode-speed comparison across models (format vs. recipe)
# ---------------------------------------------------------------------------

# Think-light, generation-heavy prompts: force a long visible stream so the
# number reflects sustained decode speed, not thinking.
PROBE_PROMPTS = [
    "Write the integers from 1 to 120 separated by commas. Output only the numbers.",
    "Write a plain-text list of 60 common English nouns, one per line, numbered. No commentary.",
]


def cmd_probe(models):
    for model in models:
        print(f"\n[{ts()}] === {model} ===", flush=True)
        prepare(model)
        speeds = []
        for p in PROBE_PROMPTS:
            call(model, p, max_tokens=2048)  # warmup
            runs = [call(model, p, max_tokens=2048) for _ in range(3)]
            best = sorted(runs, key=lambda r: r["total_s"])[1]  # median
            speeds.append(best["content_tok_per_s"])
            print(f"[{ts()}]   content={best['tok_content']}tok  total={best['tok_total_reported']}tok  "
                  f"ttft={best['ttft_s']}s  {best['content_tok_per_s']} content-tok/s", flush=True)
        print(f"[{ts()}]   AVG decode: {round(sum(speeds)/len(speeds), 1)} content-tok/s", flush=True)


# ---------------------------------------------------------------------------

USAGE = (
    "Usage:\n"
    "  python3 2026-06-08-gemma4-qat-vs-non-qat.py bench [<model>]\n"
    "  python3 2026-06-08-gemma4-qat-vs-non-qat.py probe [<model> ...]\n"
)


def main(argv):
    mode = argv[1] if len(argv) > 1 else None
    if mode == "bench":
        model = argv[2] if len(argv) > 2 else DEFAULT_BENCH_MODEL
        cmd_bench(model)
    elif mode == "probe":
        models = argv[2:] or DEFAULT_PROBE_MODELS
        cmd_probe(models)
    else:
        sys.stderr.write(USAGE)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv)
