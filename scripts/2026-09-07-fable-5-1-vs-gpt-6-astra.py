#!/usr/bin/env python3
"""Claude Fable 5.1 vs GPT-6 Astra — a trimmed rerun of the June trap suite.

Both models launched two days apart (2026-09-01 / 2026-09-03) at the exact
same list price: $10/$50 per MTok in/out. This reuses six of the ten tasks
from the June Fable-5-vs-Opus-4.8 benchmark — the six that actually produced
a spread last time — and drops the four every model already aced (bsearch,
jugs, monty-random, mutable-default), specifically to keep this suite cheap.
1 run instead of 3, cross-provider instead of same-vendor.

Claude Fable 5.1 goes through `claude -p` with tools hard-disabled
(--tools "" --strict-mcp-config) so the call is a bare completion, no MCP
tool-schema tax. GPT-6 Astra goes through `codex exec` (OpenAI's own agent
CLI) with -s read-only and no equivalent hard tool-disable flag — Codex has
no "--tools ''"; the prompt just asks it not to use tools. That asymmetry is
real and disclosed in the post, not hidden.

Usage:
    python3 scripts/2026-09-07-fable-5-1-vs-gpt-6-astra.py run [n_runs]
    python3 scripts/2026-09-07-fable-5-1-vs-gpt-6-astra.py summarize

Results append to /tmp/fable51-gpt6/results.ndjson. Stdlib only.
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

SYSTEM = "You are a benchmark subject. Follow instructions literally. Do not use any tools, do not explore the filesystem — just answer directly in your response text."
OUTDIR = "/tmp/fable51-gpt6"
SCRATCH_CWD = "/private/tmp"
CALL_TIMEOUT = 600

# GPT-6 Astra list pricing ($/MTok): input 10, cached input 1, output 50.
# Claude Fable 5.1 list pricing ($/MTok): input 10, cache read 0.25, output 50.
GPT6_PRICE = {"in": 10.0, "cached_in": 1.0, "out": 50.0}


# ---------------------------------------------------------------- helpers

def strip_fences(text):
    t = text.strip()
    m = re.match(r"^```[a-zA-Z0-9]*\n(.*?)\n?```$", t, re.S)
    return m.group(1) if m else t


def run_python(code, timeout=10):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        p = subprocess.run(
            [sys.executable, path], capture_output=True, text=True, timeout=timeout
        )
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------- graders

def grade_exact(expect):
    def g(result):
        ok = result.strip() == expect
        return ok, f"got {result.strip()!r}, want {expect!r}"
    return g


def grade_bugfix(test_code):
    def g(result):
        code = strip_fences(result)
        ok, out = run_python(code + "\n\n" + test_code)
        return ok, out[:300]
    return g


MERGE_TESTS = """
assert merge_intervals([[1, 3], [3, 5]]) == [[1, 5]], merge_intervals([[1, 3], [3, 5]])
assert merge_intervals([[1, 4], [2, 3]]) == [[1, 4]]
assert merge_intervals([[5, 6], [1, 2]]) == [[1, 2], [5, 6]]
assert merge_intervals([[1, 2], [2, 3], [3, 4]]) == [[1, 4]]
assert merge_intervals([]) == []
print("OK")
"""


def grade_regex_ipv4(result):
    pat = strip_fences(result).strip().strip("`")
    try:
        rx = re.compile(pat)
    except re.error as e:
        return False, f"regex does not compile: {e}"
    valid = ["0.0.0.0", "255.255.255.255", "192.168.1.1", "1.2.3.4", "9.10.99.100"]
    invalid = ["256.1.1.1", "1.2.3", "1.2.3.4.5", "01.2.3.4", "1.2.3.4.",
               "-1.2.3.4", "1..2.3", "999.999.999.999", "1.2.3.4 ", "a.b.c.d", ""]
    fails = []
    for s in valid:
        if not rx.fullmatch(s):
            fails.append(f"rejects valid {s!r}")
    for s in invalid:
        if rx.fullmatch(s):
            fails.append(f"accepts invalid {s!r}")
    return (not fails), "; ".join(fails) or "all 16 cases pass"


def grade_sql(result):
    sql = strip_fences(result).strip().rstrip(";")
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE users (id INTEGER, name TEXT, age INTEGER)")
    rows = [(1, "a", 25), (2, "b", 35), (3, "c", None),
            (4, "d", 30), (5, "e", None), (6, "f", 40)]
    con.executemany("INSERT INTO users VALUES (?, ?, ?)", rows)
    try:
        cur = con.execute(sql)
        val = cur.fetchone()
        got = val[0] if val else None
    except sqlite3.Error as e:
        return False, f"sqlite error: {e}"
    return got == 4, f"query returned {got}, want 4"


def grade_json_strict(result):
    raw = result.strip()
    if raw.startswith("```"):
        return False, "wrapped in markdown fence despite instruction"
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, f"not valid JSON: {e}"
    if set(obj.keys()) != {"languages", "count"}:
        return False, f"keys are {sorted(obj.keys())}"
    langs = obj["languages"]
    if not (isinstance(langs, list) and len(langs) == 3):
        return False, f"languages is {langs!r}"
    if not all(isinstance(s, str) and s == s.lower() for s in langs):
        return False, f"not all lowercase strings: {langs!r}"
    if obj["count"] != 3:
        return False, f"count is {obj['count']!r}"
    return True, "valid"


# ---------------------------------------------------------------- tasks
# Six of the June suite's ten — kept the ones that split the two models
# last time, dropped bsearch/jugs/monty_random/mutable_default (30/30 then).

TASKS = [
    {
        "id": "bugfix_merge",
        "prompt": (
            "This function should merge a list of integer intervals. The spec: "
            "intervals that overlap OR touch (e.g. [1,3] and [3,5]) must merge into one; "
            "output sorted by start; return list of [start, end] lists.\n\n"
            "def merge_intervals(intervals):\n"
            "    intervals.sort()\n"
            "    out = []\n"
            "    for s, e in intervals:\n"
            "        if out and s < out[-1][1]:\n"
            "            out[-1][1] = max(out[-1][1], e)\n"
            "        else:\n"
            "            out.append([s, e])\n"
            "    return out\n\n"
            "It fails: merge_intervals([[1,3],[3,5]]) returns [[1,3],[3,5]] instead of [[1,5]]. "
            "Fix the bug. Reply with ONLY the corrected function source code. "
            "No explanation, no markdown fences."
        ),
        "grade": grade_bugfix(MERGE_TESTS),
    },
    {
        "id": "regex_ipv4",
        "prompt": (
            "Write a single Python regex pattern that matches a valid dotted-quad IPv4 "
            "address and nothing else (it will be tested with re.fullmatch). Rules: four "
            "decimal octets 0-255 separated by dots; leading zeros are INVALID (so "
            "'01.2.3.4' must not match, but '0.0.0.0' must). "
            "Reply with ONLY the regex pattern. No fences, no quotes, no explanation."
        ),
        "grade": grade_regex_ipv4,
    },
    {
        "id": "sql_null_trap",
        "prompt": (
            "SQLite table: users(id INTEGER, name TEXT, age INTEGER). Some ages are NULL. "
            "Write ONE SELECT statement returning a single number: how many users are NOT "
            "known to be older than 30. A user with NULL age is not known to be older "
            "than 30, so they count. Users aged exactly 30 also count. "
            "Reply with ONLY the SQL statement. No fences, no explanation."
        ),
        "grade": grade_sql,
    },
    {
        "id": "json_strict",
        "prompt": (
            "Return a JSON object with exactly two keys: \"languages\" — an array of "
            "exactly 3 lowercase programming language names — and \"count\" — the "
            "integer 3. Output the raw JSON only: no markdown fences, no extra keys, "
            "no prose before or after."
        ),
        "grade": grade_json_strict,
    },
    {
        "id": "trap_batball",
        "prompt": (
            "A bat and a ball cost $1.10 in total. The bat costs $1.00. "
            "How much does the ball cost, in cents? Reply with ONLY the integer."
        ),
        "grade": grade_exact("10"),
    },
    {
        "id": "arith_exact",
        "prompt": (
            "An item costs $129.99. It is discounted by 20%, then 8.25% sales tax is "
            "added to the discounted price. What is the final price in dollars, rounded "
            "to the nearest cent? Reply with ONLY the number (e.g. 112.61)."
        ),
        "grade": grade_exact("112.57"),
    },
]


# ---------------------------------------------------------------- runners

def call_claude(prompt):
    t0 = time.time()
    try:
        p = subprocess.run(
            ["claude", "-p", "--model", "claude-fable-5-1", "--output-format", "json",
             "--system-prompt", SYSTEM, "--tools", "", "--strict-mcp-config", prompt],
            capture_output=True, text=True, timeout=CALL_TIMEOUT, cwd=SCRATCH_CWD,
        )
        wall = time.time() - t0
        d = json.loads(p.stdout)
        u = d.get("usage", {})
        return {
            "result": d.get("result", ""),
            "wall_s": round(wall, 2),
            "cost_usd": d.get("total_cost_usd"),
            "output_tokens": u.get("output_tokens"),
            "input_tokens": u.get("input_tokens"),
            "cache_read": u.get("cache_read_input_tokens"),
            "cache_creation": u.get("cache_creation_input_tokens"),
            "is_error": d.get("is_error", False),
        }
    except subprocess.TimeoutExpired:
        return {"result": "", "wall_s": round(time.time() - t0, 2), "cost_usd": None,
                "output_tokens": None, "input_tokens": None, "cache_read": None, "cache_creation": None,
                "is_error": True, "error": "timeout"}
    except (json.JSONDecodeError, KeyError) as e:
        return {"result": "", "wall_s": round(time.time() - t0, 2), "cost_usd": None,
                "output_tokens": None, "input_tokens": None, "cache_read": None, "cache_creation": None,
                "is_error": True, "error": f"parse: {e}; stdout={p.stdout[:200]}"}


def call_codex(prompt):
    t0 = time.time()
    full_prompt = SYSTEM + "\n\n" + prompt
    try:
        p = subprocess.run(
            ["codex", "exec", "-s", "read-only", "--skip-git-repo-check",
             "--ignore-user-config", "--json", "-m", "gpt-6-astra",
             "-c", 'model_reasoning_effort="high"', full_prompt],
            capture_output=True, text=True, timeout=CALL_TIMEOUT, cwd=SCRATCH_CWD,
        )
        wall = time.time() - t0
        text, usage, err = "", {}, None
        for line in p.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "item.completed" and ev.get("item", {}).get("type") == "agent_message":
                text = ev["item"].get("text", "")
            elif t == "turn.completed":
                usage = ev.get("usage", {})
            elif t in ("turn.failed", "error"):
                err = ev.get("error") or ev.get("message")
        in_tok = usage.get("input_tokens") or 0
        cached = usage.get("cached_input_tokens") or 0
        out_tok = usage.get("output_tokens") or 0
        uncached = max(0, in_tok - cached)
        cost = (uncached * GPT6_PRICE["in"] + cached * GPT6_PRICE["cached_in"]
                + out_tok * GPT6_PRICE["out"]) / 1e6
        return {
            "result": text, "wall_s": round(wall, 2), "cost_usd": round(cost, 4),
            "output_tokens": out_tok, "reasoning_tokens": usage.get("reasoning_output_tokens"),
            "input_tokens": in_tok, "cached_input_tokens": cached,
            "is_error": bool(err) or (not text and not err is None),
            **({"error": err} if err else {}),
        }
    except subprocess.TimeoutExpired:
        return {"result": "", "wall_s": round(time.time() - t0, 2), "cost_usd": None,
                "output_tokens": None, "is_error": True, "error": "timeout"}


CALLERS = {"claude-fable-5-1": call_claude, "gpt-6-astra": call_codex}
MODELS = list(CALLERS.keys())


def main():
    n_runs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, "results.ndjson")
    total = n_runs * len(TASKS) * len(MODELS)
    done = 0
    with open(path, "a") as out:
        for run in range(1, n_runs + 1):
            for task in TASKS:
                for model in MODELS:
                    r = CALLERS[model](task["prompt"])
                    ok, detail = (False, "call error") if r["is_error"] \
                        else task["grade"](r["result"])
                    rec = {"run": run, "task": task["id"], "model": model,
                           "ok": ok, "detail": detail, **r}
                    rec["result"] = rec["result"][:500]
                    out.write(json.dumps(rec) + "\n")
                    out.flush()
                    done += 1
                    print(f"[{done}/{total}] run{run} {task['id']:>14} "
                          f"{model:<18} {'PASS' if ok else 'FAIL':<4} "
                          f"{r['wall_s']:>7.1f}s  ${r['cost_usd'] or 0:.3f}",
                          flush=True)


def summarize():
    path = os.path.join(OUTDIR, "results.ndjson")
    recs = [json.loads(l) for l in open(path)]
    tasks = sorted({r["task"] for r in recs}, key=lambda t: [x["id"] for x in TASKS].index(t))
    print(f"{'task':>14} | " + " | ".join(f"{m:>18}" for m in MODELS))
    totals = {m: [0, 0] for m in MODELS}
    for t in tasks:
        cells = []
        for m in MODELS:
            rs = [r for r in recs if r["task"] == t and r["model"] == m]
            p = sum(1 for r in rs if r["ok"])
            totals[m][0] += p; totals[m][1] += len(rs)
            cells.append(f"{p}/{len(rs)}")
        print(f"{t:>14} | " + " | ".join(f"{c:>18}" for c in cells))
    print(f"{'TOTAL':>14} | " + " | ".join(f"{totals[m][0]}/{totals[m][1]:>15}" for m in MODELS))
    import statistics
    for m in MODELS:
        rs = [r for r in recs if r["model"] == m and not r.get("error")]
        walls = sorted(r["wall_s"] for r in rs)
        cost = sum(r["cost_usd"] or 0 for r in rs)
        toks = sum(r["output_tokens"] or 0 for r in rs)
        print(f"{m}: median wall {statistics.median(walls):.1f}s, "
              f"mean {sum(walls)/len(walls):.1f}s, total cost ${cost:.2f}, "
              f"total output tokens {toks}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        main()
    elif len(sys.argv) > 1 and sys.argv[1] == "summarize":
        summarize()
    else:
        print(__doc__)
