#!/usr/bin/env python3
"""
Benchmark harness for: DiffusionGemma 26B-A4B (text diffusion) on Apple Silicon
Post: 2026-06-11-diffusiongemma.md

DiffusionGemma does NOT run in Ollama or stock llama.cpp — the `diffusion-gemma`
architecture needs a dedicated block-diffusion runner. Ollama rejects it with
`unknown model architecture: 'diffusion-gemma'` (ollama/ollama#16664), and the
standard llama-cli / llama-server can't generate from it either.

The only local path that works today is the DiffusionGemma PR for llama.cpp
(ggml-org/llama.cpp#24423, by danielhanchen / Unsloth), which adds the
`llama-diffusion-cli` runner with the entropy-bound canvas sampler. This harness
shells out to that binary — it is NOT an Ollama/OpenAI-API client like the other
benchmark scripts in this repo, because no HTTP server speaks this model yet.

Build (Apple Silicon / Metal):
  git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
  git fetch origin pull/24423/head && git checkout 10a2613a   # the PR head SHA
  cmake -B build -DGGML_METAL=ON -DGGML_CUDA=OFF
  cmake --build build -j --target llama-diffusion-cli
Model:
  hf download unsloth/diffusiongemma-26B-A4B-it-GGUF --include "*Q4_K_M*.gguf"

Two modes:
  bench  — full task suite (correctness + speed), same prompts as the Gemma 4 QAT post
  probe  — sustained decode-speed probe on canvas-filling prompts

Usage:
  python3 2026-06-11-diffusiongemma.py bench
  python3 2026-06-11-diffusiongemma.py probe
  BIN=/path/to/llama-diffusion-cli MODEL=/path/to/model.gguf \
    python3 2026-06-11-diffusiongemma.py bench

Speed metrics reported (all wall-clock, generation only — model load is excluded
by the runner, which starts its timer after the weights are resident):

  gen_tok_s   — canvas throughput: 256-token canvas x blocks / wall time. This is
                the runner's own "throughput:" number. It counts EVERY canvas
                position, including masked/trimmed ones, so on short answers it
                overstates useful output.
  net_tok_s   — useful throughput: tokens in the trimmed answer (reasoning + final
                channel) / wall time. This is what you actually get out.
  parallel_tok_s — the headline "1000+ tok/s" framing: 256-token canvas / per-step
                time. Every position is refined every step, so this is the in-step
                parallel rate, NOT a sustained wall-clock rate.
"""
import os, re, sys, time, subprocess, datetime

BIN   = os.environ.get("BIN",   os.path.expanduser(
    "~/workspace/dg-bench/llama.cpp/build/bin/llama-diffusion-cli"))
MODEL = os.environ.get("MODEL", os.path.expanduser(
    "~/workspace/dg-bench/models/diffusiongemma-26B-A4B-it-Q4_K_M.gguf"))
NGL    = os.environ.get("NGL", "99")        # offload all layers to Metal
N_PRED = int(os.environ.get("N_PRED", "512"))  # token budget -> ceil(N/256) canvas blocks
RUNS   = int(os.environ.get("RUNS", "3"))   # runs per prompt; median by wall time is kept

# The runner prints these two lines to stdout after the reply (entropy-bound mode):
#   total time: 2711.96ms, time per step: 208.61ms (13 steps over 1 blocks, entropy-bound)
#   throughput: 94.4 tok/s (256 tok in 2711.96ms), in-step parallel 1227 tok/s (256-tok canvas x 13.0 steps/block)
# consume to end-of-line ([^\n]*) so trailing fragments (", entropy-bound)",
# " x 13.0 steps/block)") are fully removed, not glued onto the reply
RE_TOTAL = re.compile(r"total time:\s*([\d.]+)ms.*?\((\d+) steps over (\d+) blocks[^\n]*")
RE_THRU  = re.compile(r"throughput:\s*([\d.]+) tok/s \((\d+) tok in ([\d.]+)ms\), "
                      r"in-step parallel ([\d.]+) tok/s \((\d+)-tok canvas[^\n]*")


def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")


def split_channels(resp):
    """DiffusionGemma-it emits `<|channel>thought ...` then `<channel|>final answer`.
    Return (final_answer, reasoning). If it never left the thought channel
    (answer didn't fit the canvas budget), final_answer is empty."""
    if "<channel|>" in resp:
        head, _, tail = resp.partition("<channel|>")
        reasoning = head.replace("<|channel>thought", "").strip()
        answer    = tail.strip()
    else:
        reasoning = resp.replace("<|channel>thought", "").strip()
        answer    = ""
    return answer, reasoning


def run(prompt, n_pred=None):
    n_pred = n_pred or N_PRED
    cmd = [BIN, "-m", MODEL, "-ngl", NGL, "-n", str(n_pred), "-p", prompt]
    t0 = time.time()
    # stdout = reply + timing lines; stderr = load logs + per-step progress bar (discarded)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    wall = time.time() - t0
    out = proc.stdout

    total = RE_TOTAL.search(out)
    thru  = RE_THRU.search(out)
    steps = int(total.group(2)) if total else 0
    blocks = int(total.group(3)) if total else 0
    gen_tok_s = float(thru.group(1)) if thru else 0.0
    gen_toks  = int(thru.group(2)) if thru else 0
    total_ms  = float(thru.group(3)) if thru else (float(total.group(1)) if total else 0.0)
    parallel_tok_s = float(thru.group(4)) if thru else 0.0
    canvas = int(thru.group(5)) if thru else 0

    # strip the two timing lines to recover the raw reply, then split channels
    reply = out
    for rgx in (RE_TOTAL, RE_THRU):
        reply = rgx.sub("", reply)
    reply = reply.strip()
    answer, reasoning = split_channels(reply)

    # net useful throughput: visible tokens (answer + reasoning), roughly chars/4, over gen wall time
    visible_chars = len(answer) + len(reasoning)
    approx_tok = max(1, visible_chars // 4)
    net_tok_s = round(approx_tok / (total_ms / 1000.0), 1) if total_ms > 0 else 0.0

    return {
        "wall_s": round(wall, 2),
        "total_ms": round(total_ms, 1),
        "steps": steps, "blocks": blocks, "canvas": canvas,
        "gen_tok_s": gen_tok_s, "gen_toks": gen_toks,
        "net_tok_s": net_tok_s, "approx_answer_tok": approx_tok,
        "parallel_tok_s": parallel_tok_s,
        "answer": answer, "reasoning": reasoning,
    }


def median_run(prompt, n_pred=None, runs=None):
    runs = runs or RUNS
    rs = [run(prompt, n_pred) for _ in range(runs)]
    rs = [r for r in rs if r["total_ms"] > 0] or rs
    return sorted(rs, key=lambda r: r["total_ms"])[len(rs) // 2]


# ---------------------------------------------------------------------------
# bench mode — same task suite as the Gemma 4 QAT post
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
    {"name": "long_context_recall",
     "prompt": ("Read the following carefully and answer the question at the end.\n\n"
                "Context: The capital of France is Paris. " +
                "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 150 +
                "\n\nQuestion: What is the capital of France? Answer with only the city name.")},
]


def score(name, answer, reasoning):
    """Same rubric as the QAT post: check the final channel first, then reasoning."""
    import json as _json
    a, r = answer.strip(), reasoning.strip()
    both = a + "\n" + r
    has_any = bool(a or r)
    if name == "code_from_spec":
        if "def merge_intervals" in both and "return" in both:
            where = "" if "def merge_intervals" in a else " (in reasoning)"
            return "pass", "function present" + where
        return "fail", "function missing"
    if name == "strict_json":
        for src, tag in ((a, ""), (r, " (in reasoning)")):
            try:
                d = _json.loads(src.strip())
                if set(d.keys()) == {"city", "population", "is_capital"}:
                    return "pass", "exact keys" + tag
                return "partial", f"keys: {list(d.keys())}"
            except Exception:
                pass
        return "fail", "not valid JSON"
    if name == "multilingual_pl":
        if any(w in a.lower() for w in ("implementation", "deployment", "rollout")):
            return "pass", "translation present"
        if has_any:
            return "partial", "something produced"
        return "fail", "empty"
    if name == "constraint_conflict":
        lines = [l for l in a.splitlines() if l.strip()]
        if len(lines) >= 3 and all(len(l.split()) <= 6 for l in lines[:3]):
            return "partial", f"{len(lines)} lines"
        if has_any:
            return "partial", "non-empty"
        return "fail", "empty"
    if name == "exact_arithmetic":
        correct = "1007.5"   # 1000 - 9*12.5 + 3*40
        if correct in a:
            return "pass", f"correct {correct}"
        if correct in r:
            return "partial", f"correct {correct} in reasoning only"
        if has_any:
            return "fail", "wrong answer"
        return "fail", "empty"
    if name == "long_context_recall":
        if "paris" in both.lower():
            return "pass", "Paris recalled"
        if has_any:
            return "fail", "wrong answer"
        return "fail", "empty (context overflow?)"
    return "unknown", ""


def cmd_bench():
    print(f"[{ts()}] BIN={BIN}")
    print(f"[{ts()}] MODEL={MODEL}")
    print(f"[{ts()}] n_predict={N_PRED}  runs={RUNS}  ngl={NGL}\n")
    rows = []
    for t in TESTS:
        print(f"[{ts()}] [{t['name']}] running {RUNS}x...", flush=True)
        best = median_run(t["prompt"])
        verdict, note = score(t["name"], best["answer"], best["reasoning"])
        rows.append({"test": t["name"], **best, "verdict": verdict, "note": note})
        print(f"[{ts()}] [{t['name']:20}] {best['steps']:>2} steps/{best['blocks']}blk  "
              f"gen={best['gen_tok_s']:>5} tok/s  net~{best['net_tok_s']:>5} tok/s  "
              f"parallel={best['parallel_tok_s']:>5} tok/s  [{verdict.upper()}] {note}")
        shown = best["answer"] or best["reasoning"]
        print(f"    -> {shown[:200].replace(chr(10), ' ')}\n")
    print(f"\n[{ts()}] SCORECARD")
    for r in rows:
        print(f"  {r['test']:20} {r['verdict'].upper():8} "
              f"gen={r['gen_tok_s']:>5} net~{r['net_tok_s']:>5} par={r['parallel_tok_s']:>5}  {r['note']}")


# ---------------------------------------------------------------------------
# probe mode — canvas-filling prompts so net ~ gross (fair sustained speed)
# ---------------------------------------------------------------------------

PROBE_PROMPTS = [
    "Write the integers from 1 to 200 separated by commas. Output only the numbers.",
    "List 80 common English nouns, one per line, numbered 1 to 80. No commentary.",
]


def cmd_probe():
    print(f"[{ts()}] BIN={BIN}\n[{ts()}] MODEL={MODEL}\n[{ts()}] probe n_predict={N_PRED} runs={RUNS}\n")
    gens, pars = [], []
    for p in PROBE_PROMPTS:
        best = median_run(p)
        gens.append(best["gen_tok_s"]); pars.append(best["parallel_tok_s"])
        print(f"[{ts()}]   {best['steps']:>2} steps/{best['blocks']}blk  "
              f"gen={best['gen_tok_s']} tok/s  net~{best['net_tok_s']} tok/s  "
              f"parallel={best['parallel_tok_s']} tok/s  ({best['total_ms']}ms)")
    print(f"\n[{ts()}]  AVG gen {round(sum(gens)/len(gens),1)} tok/s  |  "
          f"AVG in-step parallel {round(sum(pars)/len(pars),1)} tok/s")


# ---------------------------------------------------------------------------
# matrix mode — the "30/30" suite from the Opus 4.6-vs-4.7 / Fable 5 posts,
# run against DiffusionGemma. Same 10 tasks x 3 runs, same executable graders
# (run-the-tests / run-the-SQL / adversarial-regex / exact-match). The graders
# are model-agnostic; only the call site changes. We grade the model's final
# `<channel|>` answer (the `<|channel>thought` trace is the analog of the hidden
# reasoning the API models never show), strict — exactly the Fable "strict" column.
# ---------------------------------------------------------------------------

MATRIX_N = int(os.environ.get("MATRIX_N", "1024"))  # 4 canvas blocks of headroom


def _load_matrix_suite():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    fpath = os.path.join(here, "2026-06-10-fable-5-benchmark.py")
    spec = importlib.util.spec_from_file_location("fable_suite", fpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.TASKS


def cmd_matrix():
    tasks = _load_matrix_suite()
    print(f"[{ts()}] BIN={BIN}\n[{ts()}] MODEL={MODEL}")
    print(f"[{ts()}] matrix: {len(tasks)} tasks x {RUNS} runs, n_predict={MATRIX_N}, strict grade on <channel|> answer\n")
    grid = {}
    total_pass = 0
    for task in tasks:
        passes = 0
        for run_i in range(RUNS):
            r = run(task["prompt"], n_pred=MATRIX_N)
            answer = r["answer"]            # post-<channel|> reply; strict graders see only this
            stuck = (answer == "")          # never crossed into the answer channel
            try:
                ok, detail = (False, "no final answer (stuck in thought channel)") if stuck \
                    else task["grade"](answer)
            except Exception as e:
                ok, detail = False, f"grader error: {e}"
            passes += 1 if ok else 0
            print(f"[{ts()}]   {task['id']:>20} run{run_i+1} {'PASS' if ok else 'FAIL':<4} "
                  f"{r['steps']:>2}st/{r['blocks']}blk  {detail[:70]}", flush=True)
        grid[task["id"]] = passes
        total_pass += passes
    print(f"\n[{ts()}] 30-MATRIX (DiffusionGemma 26B-A4B Q4_K_M, strict)")
    for task in tasks:
        print(f"  {task['id']:>20} {grid[task['id']]}/{RUNS}")
    print(f"  {'TOTAL':>20} {total_pass}/{RUNS * len(tasks)}")


USAGE = ("Usage:\n  python3 2026-06-11-diffusiongemma.py bench\n"
         "  python3 2026-06-11-diffusiongemma.py probe\n"
         "  python3 2026-06-11-diffusiongemma.py matrix\n")


def main(argv):
    if not os.path.exists(BIN):
        sys.exit(f"binary not found: {BIN}\nbuild llama-diffusion-cli from ggml-org/llama.cpp#24423 "
                 f"(see the docstring), or set BIN=...")
    if not os.path.exists(MODEL):
        sys.exit(f"model not found: {MODEL}\nhf download unsloth/diffusiongemma-26B-A4B-it-GGUF "
                 f"--include '*Q4_K_M*.gguf', or set MODEL=...")
    mode = argv[1] if len(argv) > 1 else None
    if mode == "bench":
        cmd_bench()
    elif mode == "probe":
        cmd_probe()
    elif mode == "matrix":
        cmd_matrix()
    else:
        sys.stderr.write(USAGE)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv)
