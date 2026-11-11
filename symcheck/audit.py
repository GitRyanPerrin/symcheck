"""Audit a final answer against the symcheck log.

Every number in the answer must be traceable to a tool *result* in the log
(or be given in TASK.md, or be explicitly allowed). Numbers that are not are
reported as UNTRACED -- likely mental math. A number whose magnitude matches a
logged value but whose sign does not is reported as SIGN_MISMATCH.

This is an honesty check, not a proof: a model can still print() a literal.

usage: python audit.py ANSWER.md --log symcheck_log.jsonl [--task TASK.md]
                       [--since 2026-11-10T14:00:00] [--ignore-int 10]
                       [--allow 300 4.2] [--json]
exit code 1 if any UNTRACED or SIGN_MISMATCH.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

_NUM = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
_SCI = re.compile(r"(?<![\w.])(" + _NUM + r")\s*(?:×|\\times|\\cdot|\*|x)\s*10\s*\^\s*\{?\s*([-+]?\d+)\s*\}?")
_PLAIN = re.compile(r"(?<![\w.])" + _NUM)


def _sigfigs(mantissa: str) -> int:
    m = mantissa.lstrip("+-").split("e")[0].split("E")[0].replace(".", "").lstrip("0")
    return max(1, len(m))


def extract(text: str) -> list[tuple[float, int, str]]:
    """Return (value, significant figures, original text) for each number."""
    text = text.replace("−", "-")
    out = []
    masked = list(text)
    for mt in _SCI.finditer(text):
        v = float(mt.group(1)) * 10 ** int(mt.group(2))
        out.append((v, _sigfigs(mt.group(1)), mt.group(0)))
        for i in range(mt.start(), mt.end()):
            masked[i] = " "
    for mt in _PLAIN.finditer("".join(masked)):
        s = mt.group(0)
        try:
            out.append((float(s), _sigfigs(s), s))
        except ValueError:
            pass
    return out


def _walk(obj, pool: list[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            pool.append(float(obj))
    elif isinstance(obj, str):
        pool.extend(v for v, _, _ in extract(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, pool)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, pool)


def logged_values(log: Path, since: str | None) -> list[float]:
    pool: list[float] = []
    for line in log.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if since and rec.get("ts", "") < since:
            continue
        _walk(rec.get("result"), pool)   # results only: inputs are model-supplied
    return pool


def _matches(a: float, sig: int, pool: list[float]) -> bool:
    if a == 0:
        return any(b == 0 for b in pool)
    tol = 10 ** (math.floor(math.log10(abs(a))) - sig + 1)   # one unit in last shown digit
    return any(abs(a - b) <= tol * (1 + 1e-9) for b in pool)


def audit(answer: str, pool: list[float], task_vals: list[float],
          allow: list[float], ignore_int: int) -> list[dict]:
    rows = []
    for v, sig, s in extract(answer):
        if float(v).is_integer() and abs(v) <= ignore_int:
            status = "IGNORED"
        elif _matches(v, sig, pool):
            status = "TRACED"
        elif _matches(v, sig, task_vals) or _matches(v, sig, allow):
            status = "GIVEN"
        elif _matches(-v, sig, pool):
            status = "SIGN_MISMATCH"
        else:
            status = "UNTRACED"
        rows.append({"text": s, "value": v, "sigfigs": sig, "status": status})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("answer", type=Path)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--task", type=Path)
    ap.add_argument("--since", help="only log records with ts >= this (YYYY-MM-DDTHH:MM:SS)")
    ap.add_argument("--ignore-int", type=int, default=10,
                    help="ignore integers with |x| <= N (indices, exponents); default 10")
    ap.add_argument("--allow", type=float, nargs="*", default=[])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    pool = logged_values(a.log, a.since)
    task_vals = [v for v, _, _ in extract(a.task.read_text())] if a.task else []
    rows = audit(a.answer.read_text(), pool, task_vals, a.allow, a.ignore_int)
    bad = [r for r in rows if r["status"] in ("UNTRACED", "SIGN_MISMATCH")]

    if a.json:
        print(json.dumps({"rows": rows, "n_bad": len(bad)}, indent=1))
    else:
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(f"{len(rows)} numbers in answer; {len(pool)} values in log")
        print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        for r in bad:
            print(f"  {r['status']:14s} {r['text']}")
        print("AUDIT FAIL" if bad else "AUDIT PASS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
