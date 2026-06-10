#!/usr/bin/env python3
"""Fable 5 vs Opus 4.8 — the harder suite.

Follow-up to the April Opus 4.6 vs 4.7 benchmark. That suite was deliberately
easy (latency comparison). This one is built to FAIL: bug fixes graded by
executing the tests, regex graded against adversarial inputs, SQL graded by
running it against a fixture with NULLs, and reasoning traps where the
pattern-matched answer is wrong.

Usage:
    python3 scripts/2026-06-10-fable-5-benchmark.py run [n_runs]
    python3 scripts/2026-06-10-fable-5-benchmark.py summarize

Each task is run via:  claude -p --model <m> --output-format json
Results append to /tmp/fable-bench/results.ndjson (one JSON object per call).
Stdlib only.
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

MODELS = ["claude-fable-5", "claude-opus-4-8"]
SYSTEM = "You are a benchmark subject. Follow instructions literally."
OUTDIR = "/tmp/fable-bench"
CALL_TIMEOUT = 600  # seconds per claude -p call


# ---------------------------------------------------------------- helpers

def strip_fences(text):
    """Remove a single wrapping markdown code fence if present."""
    t = text.strip()
    m = re.match(r"^```[a-zA-Z0-9]*\n(.*?)\n?```$", t, re.S)
    return m.group(1) if m else t


def run_python(code, timeout=10):
    """Execute python code in a subprocess; return (ok, stdout+stderr)."""
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

BSEARCH_TESTS = """
assert first_index([1, 2, 2, 2, 3], 2) == 1, first_index([1, 2, 2, 2, 3], 2)
assert first_index([2, 2, 2, 2, 2], 2) == 0
assert first_index([1, 3, 5], 4) == -1
assert first_index([], 1) == -1
assert first_index([1, 2, 3], 3) == 2
assert first_index([5] * 10001, 5) == 0
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
        "id": "bugfix_bsearch",
        "prompt": (
            "This function should return the index of the FIRST (leftmost) occurrence "
            "of x in sorted list a, or -1 if absent. It must stay O(log n) — the list "
            "can hold millions of elements, so no linear scanning.\n\n"
            "def first_index(a, x):\n"
            "    lo, hi = 0, len(a) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if a[mid] == x:\n"
            "            return mid\n"
            "        elif a[mid] < x:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n\n"
            "It fails: first_index([1,2,2,2,3], 2) returns 2 instead of 1. "
            "Fix the bug. Reply with ONLY the corrected function source code. "
            "No explanation, no markdown fences."
        ),
        "grade": grade_bugfix(BSEARCH_TESTS),
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
        "id": "trap_jugs",
        "prompt": (
            "You have a 7-liter jug and a 3-liter jug, both empty, and unlimited water. "
            "You want exactly 3 liters of water in a jug. What is the minimum number of "
            "operations (one operation = one fill, one pour, or one empty)? "
            "Reply with ONLY the integer."
        ),
        "grade": grade_exact("1"),
    },
    {
        "id": "trap_monty_random",
        "prompt": (
            "Three doors, one car, two goats. You pick door 1. The host, who does NOT "
            "know where the car is, opens one of the other two doors at random, and it "
            "happens to reveal a goat. Given that, what is your probability of winning "
            "the car if you switch to the remaining door? "
            "Reply with ONLY a fraction in the form a/b."
        ),
        "grade": grade_exact("1/2"),
    },
    {
        "id": "trace_mutable_default",
        "prompt": (
            "What does this Python 3 program print? Reply with ONLY the exact output line.\n\n"
            "def f(x, acc=[]):\n"
            "    acc.append(x)\n"
            "    return acc\n"
            "print(f(1), f(2))"
        ),
        "grade": grade_exact("[1, 2] [1, 2]"),
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


# ---------------------------------------------------------------- runner

def call_claude(model, prompt):
    t0 = time.time()
    try:
        p = subprocess.run(
            ["claude", "-p", "--model", model, "--output-format", "json",
             "--system-prompt", SYSTEM, prompt],
            capture_output=True, text=True, timeout=CALL_TIMEOUT,
        )
        wall = time.time() - t0
        d = json.loads(p.stdout)
        return {
            "result": d.get("result", ""),
            "wall_s": round(wall, 2),
            "api_ms": d.get("duration_api_ms"),
            "cost_usd": d.get("total_cost_usd"),
            "output_tokens": d.get("usage", {}).get("output_tokens"),
            "is_error": d.get("is_error", False),
        }
    except subprocess.TimeoutExpired:
        return {"result": "", "wall_s": round(time.time() - t0, 2),
                "api_ms": None, "cost_usd": None, "output_tokens": None,
                "is_error": True, "error": "timeout"}
    except (json.JSONDecodeError, KeyError) as e:
        return {"result": "", "wall_s": round(time.time() - t0, 2),
                "api_ms": None, "cost_usd": None, "output_tokens": None,
                "is_error": True, "error": f"parse: {e}; stdout={p.stdout[:200]}"}


def main():
    n_runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, "results.ndjson")
    total = n_runs * len(TASKS) * len(MODELS)
    done = 0
    with open(path, "a") as out:
        for run in range(1, n_runs + 1):
            for task in TASKS:
                for model in MODELS:
                    r = call_claude(model, task["prompt"])
                    ok, detail = (False, "call error") if r["is_error"] \
                        else task["grade"](r["result"])
                    rec = {"run": run, "task": task["id"], "model": model,
                           "ok": ok, "detail": detail, **r}
                    rec["result"] = rec["result"][:500]
                    out.write(json.dumps(rec) + "\n")
                    out.flush()
                    done += 1
                    print(f"[{done}/{total}] run{run} {task['id']:>22} "
                          f"{model:<18} {'PASS' if ok else 'FAIL':<4} "
                          f"{r['wall_s']:>7.1f}s  ${r['cost_usd'] or 0:.3f}",
                          flush=True)


# ---------------------------------------------------------------- analyze

def summarize():
    path = os.path.join(OUTDIR, "results.ndjson")
    recs = [json.loads(l) for l in open(path)]
    by = {}
    for r in recs:
        by.setdefault((r["task"], r["model"]), []).append(r)
    tasks = sorted({r["task"] for r in recs}, key=lambda t: [x["id"] for x in TASKS].index(t))
    models = MODELS
    print(f"{'task':>22} | " + " | ".join(f"{m.replace('claude-',''):>12}" for m in models))
    totals = {m: [0, 0] for m in models}
    for t in tasks:
        cells = []
        for m in models:
            rs = by.get((t, m), [])
            p = sum(1 for r in rs if r["ok"])
            totals[m][0] += p; totals[m][1] += len(rs)
            cells.append(f"{p}/{len(rs)}")
        print(f"{t:>22} | " + " | ".join(f"{c:>12}" for c in cells))
    print(f"{'TOTAL':>22} | " + " | ".join(f"{totals[m][0]}/{totals[m][1]:>9}" for m in models))
    for m in models:
        rs = [r for r in recs if r["model"] == m and not r.get("error")]
        import statistics
        walls = sorted(r["wall_s"] for r in rs)
        med = statistics.median(walls)
        cost = sum(r["cost_usd"] or 0 for r in rs)
        toks = sum(r["output_tokens"] or 0 for r in rs)
        print(f"{m}: median wall {med:.1f}s, mean {sum(walls)/len(walls):.1f}s, "
              f"total cost ${cost:.2f}, total output tokens {toks}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        main()
    elif len(sys.argv) > 1 and sys.argv[1] == "summarize":
        summarize()
    else:
        print(__doc__)
