"""Lightweight tests (a few seconds, single-threaded). Run: python -m pytest tests -q"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from symcheck import audit, core  # noqa: E402

RASHBA = "hbar**2*k**2/(2*m) + alpha*k"
P = {"hbar": 1.0, "m": 0.023, "alpha": 0.3}


@pytest.fixture(autouse=True)
def _log(tmp_path, monkeypatch):
    monkeypatch.setenv("SYMCHECK_LOG", str(tmp_path / "log.jsonl"))
    yield tmp_path / "log.jsonl"


def test_run_python_and_log(_log):
    r = core.run_python("print(2+2)")
    assert r["ok"] and r["stdout"].strip() == "4"
    rec = json.loads(_log.read_text().splitlines()[-1])
    assert rec["tool"] == "run_python" and rec["result"]["stdout"].strip() == "4"


def test_run_python_timeout():
    r = core.run_python("import time; time.sleep(5)", timeout_s=1)
    assert r["timed_out"] and not r["ok"]


def test_crosscheck_pass_with_independent_route():
    # numpy side: energy from 2x2 diagonalization-free finite form is trivial here;
    # use central finite difference of the integral of dE/dk as an independent route
    code = (
        "import numpy as np\n"
        "def f(k, hbar, m, alpha):\n"
        "    ks = np.linspace(0, k, 2001)\n"
        "    dE = hbar**2*ks/m + alpha\n"
        "    return np.trapezoid(dE, ks)\n"
    )
    r = core.crosscheck(RASHBA, code, {"k": [-1, 1]}, P, rtol=1e-6)
    assert r["status"] == "PASS", r


def test_crosscheck_catches_sign_error():
    code = "def f(k, hbar, m, alpha): return hbar**2*k**2/(2*m) - alpha*k"
    r = core.crosscheck(RASHBA, code, {"k": [-1, 1]}, P)
    assert r["status"] == "FAIL" and r["n_fail"] > 0


def test_crosscheck_reports_missing_symbol():
    r = core.crosscheck(RASHBA, "def f(**kw): return 0", {"k": [-1, 1]}, {"hbar": 1.0})
    assert r["status"] == "ERROR" and "alpha" in r["error"] and "m" in r["error"]


def test_limits():
    assert core.check_limit("sin(x)/x", "x", "0", "1")["status"] == "PASS"
    assert core.check_limit("sin(x)/x", "x", "0", "0")["status"] == "FAIL"
    r = core.check_limit("sqrt(a**2 + x)/a", "x", "0", "1", positive=["a"], params={"a": 2.0})
    assert r["status"] == "PASS" and len(r["numeric_approach"]) == 4


def test_units():
    r = core.check_units("hbar**2/(2*m_e*nm**2)", "meV")
    assert r["status"] == "CONSISTENT" and abs(r["value_in_target"] - 38.0998) < 1e-3
    assert core.check_units("hbar**2/(2*m_e*nm)", "meV")["status"] == "INCONSISTENT"
    r = core.check_units("hbar**2/(2*m*nm**2)", "meV")   # m is metre
    assert r["status"] == "INCONSISTENT" and "hint" in r
    assert core.check_units("hbar**2/(2*mass*nm**2)", "meV")["status"] == "ERROR"


def test_extract_numbers():
    vals = [v for v, _, _ in audit.extract("alpha = 1.23 \\times 10^{-3} and 4.5e2, P1, x2, −0.7")]
    assert vals == pytest.approx([1.23e-3, 450.0, -0.7])


def test_audit(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"ts": "2026-11-10T10:00:00", "tool": "run_python",
                               "inputs": {"code": "print(99.9)"},
                               "result": {"stdout": "alpha = 0.123456\nE = 38.0998\n"}}) + "\n")
    task = tmp_path / "TASK.md"
    task.write_text("R = 50 nm")
    ans = tmp_path / "ANSWER.md"
    ans.write_text("alpha = 0.1235 meV nm at R = 50 nm; E = 38.10 meV; "
                   "also -0.1235; and 7.77 from nowhere; index 3")
    rows = audit.audit(ans.read_text(), audit.logged_values(log, None),
                       [50.0], [], 10)
    st = {r["text"]: r["status"] for r in rows}
    assert st["0.1235"] == "TRACED"
    assert st["38.10"] == "TRACED"
    assert st["50"] == "GIVEN"
    assert st["-0.1235"] == "SIGN_MISMATCH"
    assert st["7.77"] == "UNTRACED"
    assert st["3"] == "IGNORED"
    # inputs (model-supplied code) must not count as provenance
    assert audit.audit("99.9", audit.logged_values(log, None), [], [], 10)[0]["status"] == "UNTRACED"
    assert audit.main([str(ans), "--log", str(log), "--task", str(task)]) == 1
