"""symcheck core: run model-written SymPy/NumPy code in a separate process and
provide verification checks (cross-check, limits, units). Every call is
appended to a JSONL log so the final answer can be audited afterwards.

Isolation is *process* isolation (separate interpreter in isolated mode, temp
working dir, stripped environment, timeout, low priority, 1 BLAS thread,
memory cap on Linux). It is NOT a security sandbox: the code can still read
and write files the user can. Run under a separate user/container if that
matters.

Configuration (environment variables):
    SYMCHECK_LOG       path of the JSONL log      (default ./symcheck_log.jsonl)
    SYMCHECK_TIMEOUT   default timeout, seconds   (default 120)
    SYMCHECK_MEM_MB    address-space cap, Linux   (default 4096)
    SYMCHECK_THREADS   BLAS/OpenMP threads        (default 1)
    SYMCHECK_NICE      niceness increment         (default 10)
    SYMCHECK_WORKDIR   persistent working dir for run_python (default: temp dir)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

MARKER = "__SYMCHECK_JSON__"
MAX_OUT = int(os.environ.get("SYMCHECK_MAX_OUTPUT", "20000"))


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------
def log_path() -> Path:
    return Path(os.environ.get("SYMCHECK_LOG", "symcheck_log.jsonl")).expanduser()


def _log(tool: str, inputs: dict, result: dict) -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool,
           "inputs": inputs, "result": result}
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


# --------------------------------------------------------------------------
# process runner
# --------------------------------------------------------------------------
def _truncate(s: str) -> str:
    if len(s) <= MAX_OUT:
        return s
    half = MAX_OUT // 2
    return s[:half] + f"\n...[truncated {len(s) - MAX_OUT} chars]...\n" + s[-half:]


def _as_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, bytes):
        return x.decode(errors="replace")
    return x


def _make_preexec():
    nice = int(os.environ.get("SYMCHECK_NICE", "10"))
    mem = int(os.environ.get("SYMCHECK_MEM_MB", "4096")) * 1024 * 1024
    linux = sys.platform.startswith("linux")

    def fn():
        try:
            os.nice(nice)
        except OSError:
            pass
        if linux:
            try:
                import resource
                resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            except (ValueError, OSError):
                pass
    return fn


def _run(code: str, timeout: float | None, workdir: str | None = None) -> dict:
    timeout = float(timeout or os.environ.get("SYMCHECK_TIMEOUT", "120"))
    th = os.environ.get("SYMCHECK_THREADS", "1")
    t0 = time.time()
    tmp = tempfile.TemporaryDirectory(prefix="symcheck_")
    try:
        d = Path(workdir).expanduser() if workdir else Path(tmp.name)
        d.mkdir(parents=True, exist_ok=True)
        script = Path(tmp.name) / "job.py"
        script.write_text(code)
        env = {
            "PATH": os.environ.get("PATH", ""), "HOME": tmp.name, "TMPDIR": tmp.name,
            "OMP_NUM_THREADS": th, "OPENBLAS_NUM_THREADS": th, "MKL_NUM_THREADS": th,
            "VECLIB_MAXIMUM_THREADS": th, "NUMEXPR_NUM_THREADS": th,
            "MPLBACKEND": "Agg", "PYTHONHASHSEED": "0",
        }
        try:
            cp = subprocess.run([sys.executable, "-I", str(script)], cwd=d, env=env,
                                capture_output=True, text=True, timeout=timeout,
                                preexec_fn=_make_preexec())
            rc, out, err, timed_out = cp.returncode, cp.stdout, cp.stderr, False
        except subprocess.TimeoutExpired as e:
            rc, out, err, timed_out = None, _as_text(e.stdout), _as_text(e.stderr), True
    finally:
        tmp.cleanup()
    return {"ok": rc == 0 and not timed_out, "returncode": rc, "timed_out": timed_out,
            "elapsed_s": round(time.time() - t0, 3),
            "stdout": _truncate(out), "stderr": _truncate(err)}


def _run_json(script: str, timeout: float | None) -> dict:
    """Run a generated checker script; parse the MARKER-prefixed JSON line."""
    res = _run(script, timeout)
    for line in reversed(res["stdout"].splitlines()):
        if line.startswith(MARKER):
            out = json.loads(line[len(MARKER):])
            out["elapsed_s"] = res["elapsed_s"]
            return out
    return {"status": "ERROR",
            "error": "checker produced no result" + (" (timed out)" if res["timed_out"] else ""),
            "stderr": res["stderr"][-4000:], "elapsed_s": res["elapsed_s"]}


# shared header for generated checker scripts
_HEADER = r'''
import json, traceback
def emit(d):
    print("__SYMCHECK_JSON__" + json.dumps(d, default=str))
def cfmt(z):
    z = complex(z)
    if abs(z.imag) <= 1e-15 * max(1.0, abs(z.real)):
        return z.real
    return [z.real, z.imag]
P = json.loads(%r)
'''


# --------------------------------------------------------------------------
# tool 1: run arbitrary python
# --------------------------------------------------------------------------
def run_python(code: str, timeout_s: float | None = None) -> dict:
    res = _run(code, timeout_s, os.environ.get("SYMCHECK_WORKDIR"))
    _log("run_python", {"code": code, "timeout_s": timeout_s}, res)
    return res


# --------------------------------------------------------------------------
# tool 2: SymPy expression vs independent NumPy implementation
# --------------------------------------------------------------------------
_CROSSCHECK = _HEADER + r'''
try:
    import numpy as np, sympy as sp
    names = list(P["variables"]) + [k for k in P["params"] if k not in P["variables"]]
    syms = {n: sp.Symbol(n) for n in names}
    expr = sp.sympify(P["sympy_expr"], locals=syms)
    extra = sorted(str(s) for s in expr.free_symbols if s not in set(syms.values()))
    if extra:
        emit({"status": "ERROR", "error": "sympy_expr contains symbols with no range or value: "
              + ", ".join(extra)})
        raise SystemExit
    g = sp.lambdify([syms[n] for n in names], expr, modules=["numpy"])
    ns = {"np": np, "numpy": np}
    exec(P["numpy_code"], ns)
    f = ns.get("f")
    if not callable(f):
        emit({"status": "ERROR", "error": "numpy_code must define a function f(**kwargs)"})
        raise SystemExit
    rng = np.random.default_rng(P["seed"])
    rtol, atol = P["rtol"], P["atol"]
    n_fail = n_nonfinite = n_eval = 0
    max_abs = max_rel = 0.0
    worst = None
    samples = []
    for i in range(P["n"]):
        pt = {v: float(rng.uniform(lo, hi)) for v, (lo, hi) in P["variables"].items()}
        for k, val in P["params"].items():
            pt.setdefault(k, val)
        a = complex(np.asarray(g(*[pt[n] for n in names])).item())
        b = complex(np.asarray(f(**pt)).item())
        if not (np.isfinite(a) and np.isfinite(b)):
            n_nonfinite += 1
            continue
        n_eval += 1
        d = abs(a - b)
        scale = max(abs(a), abs(b))
        rel = d / scale if scale > 0 else 0.0
        if d > atol + rtol * scale:
            n_fail += 1
        max_abs = max(max_abs, d)
        if worst is None or rel > max_rel:
            max_rel = rel
            worst = {"point": pt, "sympy": cfmt(a), "numpy": cfmt(b)}
        if len(samples) < 3:
            samples.append({"point": pt, "sympy": cfmt(a), "numpy": cfmt(b)})
    ok = n_eval > 0 and n_fail == 0 and n_nonfinite == 0
    emit({"status": "PASS" if ok else "FAIL", "n_points": P["n"], "n_evaluated": n_eval,
          "n_fail": n_fail, "n_nonfinite": n_nonfinite, "max_abs_err": max_abs,
          "max_rel_err": max_rel, "rtol": rtol, "atol": atol,
          "worst_point": worst, "samples": samples})
except SystemExit:
    pass
except Exception:
    emit({"status": "ERROR", "error": traceback.format_exc(limit=4)})
'''


def crosscheck(sympy_expr: str, numpy_code: str, variables: dict[str, list[float]],
               params: dict[str, float] | None = None, n: int = 50,
               rtol: float = 1e-9, atol: float = 0.0, seed: int = 0,
               timeout_s: float | None = None) -> dict:
    payload = {"sympy_expr": sympy_expr, "numpy_code": numpy_code,
               "variables": variables, "params": params or {}, "n": int(n),
               "rtol": float(rtol), "atol": float(atol), "seed": int(seed)}
    res = _run_json(_CROSSCHECK % json.dumps(payload), timeout_s)
    _log("crosscheck", payload, res)
    return res


# --------------------------------------------------------------------------
# tool 3: limits
# --------------------------------------------------------------------------
_LIMIT = _HEADER + r'''
try:
    import random, sympy as sp
    loc = {}
    for nm in P["positive"]:
        loc[nm] = sp.Symbol(nm, positive=True)
    for nm in P["real"]:
        loc.setdefault(nm, sp.Symbol(nm, real=True))
    loc.setdefault(P["var"], sp.Symbol(P["var"]))
    expr = sp.sympify(P["expr"], locals=loc)
    var = loc[P["var"]]
    point = sp.sympify(P["point"], locals=loc)
    expected = sp.sympify(P["expected"], locals=loc)
    lim = sp.limit(expr, var, point, dir=P["direction"])
    out = {"limit": str(lim), "expected": str(expected)}
    if lim.has(sp.Limit):
        out["status"] = "UNDETERMINED"
    else:
        diff = sp.simplify(lim - expected)
        out["difference"] = str(diff)
        if diff == 0:
            out["status"] = "PASS"
        else:
            rnd = random.Random(0)
            fs = sorted(diff.free_symbols, key=str)
            vals = []
            for _ in range(5):
                sub = {s: rnd.uniform(0.5, 2.0) for s in fs}
                vals.append(abs(complex(diff.subs(sub).evalf(30))))
            out["status"] = "PASS_NUMERIC" if max(vals) < 1e-12 else "FAIL"
    if P["params"] and point.is_number:
        e2 = expr.subs({sp.Symbol(k): v for k, v in P["params"].items()})
        e2 = e2.subs({loc[k]: v for k, v in P["params"].items() if k in loc})
        approach = []
        sgn = -1 if P["direction"] == "-" else 1
        for k in (2, 4, 6, 8):
            x = 10**k if point == sp.oo else (-10**k if point == -sp.oo
                 else point + sgn * sp.Rational(1, 10**k))
            approach.append({"x": str(sp.N(x, 12)), "value": cfmt(e2.subs(var, x).evalf(30))})
        out["numeric_approach"] = approach
    emit(out)
except Exception:
    emit({"status": "ERROR", "error": traceback.format_exc(limit=4)})
'''


def check_limit(expr: str, var: str, point: str, expected: str, direction: str = "+",
                positive: list[str] | None = None, real: list[str] | None = None,
                params: dict[str, float] | None = None,
                timeout_s: float | None = None) -> dict:
    payload = {"expr": expr, "var": var, "point": str(point), "expected": str(expected),
               "direction": direction, "positive": positive or [], "real": real or [],
               "params": params or {}}
    res = _run_json(_LIMIT % json.dumps(payload), timeout_s)
    _log("check_limit", payload, res)
    return res


# --------------------------------------------------------------------------
# tool 4: units / dimensions
# --------------------------------------------------------------------------
_UNITS = _HEADER + r'''
try:
    import sympy as sp
    from sympy.physics import units as u
    from sympy.physics.units.systems.si import SI
    ns = {k: getattr(u, k) for k in dir(u) if isinstance(getattr(u, k), u.Quantity)}
    ns.update({
        "eV": u.electronvolt, "meV": u.electronvolt / 1000, "nm": u.nanometer,
        "angstrom": u.angstrom, "AA": u.angstrom, "hbar": u.hbar,
        "m_e": u.electron_rest_mass, "m0": u.electron_rest_mass,
        "e_charge": u.elementary_charge, "q_e": u.elementary_charge,
        "eps0": u.vacuum_permittivity, "k_B": u.boltzmann_constant,
        "mu_B": u.elementary_charge * u.hbar / (2 * u.electron_rest_mass),
    })
    expr = sp.sympify(P["expr"], locals=ns)
    target = sp.sympify(P["target"], locals=ns)
    unknown = sorted(str(s) for s in (expr.free_symbols | target.free_symbols))
    if unknown:
        emit({"status": "ERROR", "error": "unknown names (not units/constants): "
              + ", ".join(unknown) + ". Note: m = metre, s = second, g = gram, "
              "T = tesla, h = hour; use m_e/m0 for the electron mass."})
        raise SystemExit
    conv = u.convert_to(expr, sorted(target.atoms(u.Quantity), key=str))
    ratio = sp.simplify(conv / target)
    out = {"converted": str(conv), "ratio_to_target": str(ratio)}
    try:
        out["dim_expr"] = str(SI.get_dimensional_expr(expr))
        out["dim_target"] = str(SI.get_dimensional_expr(target))
    except Exception:
        pass
    if ratio.has(u.Quantity) or not ratio.is_number:
        out["status"] = "INCONSISTENT"
        if u.meter in expr.atoms(u.Quantity):
            out["hint"] = "expr contains 'm' = metre; use m_e or m0 for the electron mass"
    else:
        out["status"] = "CONSISTENT"
        out["value_in_target"] = cfmt(sp.N(ratio, 15))
    emit(out)
except SystemExit:
    pass
except Exception:
    emit({"status": "ERROR", "error": traceback.format_exc(limit=4)})
'''


def check_units(expr: str, target: str, timeout_s: float | None = None) -> dict:
    payload = {"expr": expr, "target": target}
    res = _run_json(_UNITS % json.dumps(payload), timeout_s)
    _log("check_units", payload, res)
    return res
