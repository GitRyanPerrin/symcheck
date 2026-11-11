"""symcheck MCP server (stdio). Launch: <venv>/bin/python /path/to/symcheck/symcheck/server.py

Tool docstrings below are what the model sees; keep them precise.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from symcheck import core  # noqa: E402

mcp = FastMCP("symcheck")


@mcp.tool()
def run_python(code: str, timeout_s: float = 120) -> dict:
    """Run a Python script (SymPy, NumPy, SciPy available) in a fresh process and
    return its stdout/stderr. Use this for ALL algebra, calculus and arithmetic:
    never compute anything in your head. print() every result you will use.
    Each call is a new process: re-import and re-define what you need."""
    return core.run_python(code, timeout_s)


@mcp.tool()
def crosscheck(sympy_expr: str, numpy_code: str, variables: dict[str, list[float]],
               params: dict[str, float] | None = None, n: int = 50,
               rtol: float = 1e-9, atol: float = 0.0, seed: int = 0) -> dict:
    """Check a closed-form SymPy expression against an INDEPENDENT NumPy
    implementation at n random points.

    sympy_expr: expression string, e.g. "hbar**2*k**2/(2*m) + alpha*k".
    numpy_code: Python source defining f(**kw) that computes the same quantity
        by a different route (finite differences, matrix diagonalization,
        numerical integration, the defining equations) -- NOT a copy of
        sympy_expr. f receives every variable and param by keyword.
    variables: {name: [lo, hi]} sampled uniformly. params: {name: value} fixed.
    Returns status PASS/FAIL/ERROR, max_abs_err, max_rel_err, worst_point.
    Do not loosen rtol/atol to make a FAIL pass without reporting it."""
    return core.crosscheck(sympy_expr, numpy_code, variables, params, n, rtol, atol, seed)


@mcp.tool()
def check_limit(expr: str, var: str, point: str, expected: str, direction: str = "+",
                positive: list[str] | None = None, real: list[str] | None = None,
                params: dict[str, float] | None = None) -> dict:
    """Verify that limit(expr, var -> point) equals expected, using SymPy.
    point/expected are SymPy strings ("0", "oo", "hbar**2/(2*m)").
    direction: "+", "-" or "+-". positive/real: symbol names to declare
    positive/real (often needed, e.g. radii, masses). params: optional numeric
    values for the other symbols; adds a numeric approach sequence.
    Returns status PASS / PASS_NUMERIC / FAIL / UNDETERMINED / ERROR."""
    return core.check_limit(expr, var, point, expected, direction, positive, real, params)


@mcp.tool()
def check_units(expr: str, target: str) -> dict:
    """Check that a physical expression built from units/constants has the
    dimensions of target, and give its value in target units.
    Names: SI units (meter, second, kilogram, joule, volt, tesla, ...), plus
    eV, meV, nm, angstrom, hbar, m_e (= m0), e_charge, eps0, k_B, mu_B.
    WARNING: m = metre, s = second, T = tesla, h = hour.
    Example: check_units("hbar**2/(2*m_e*nm**2)", "meV") -> CONSISTENT, 38.0998.
    Returns status CONSISTENT / INCONSISTENT / ERROR and value_in_target."""
    return core.check_units(expr, target)


if __name__ == "__main__":
    mcp.run()
