---
name: symbolic-computation
description: Mandatory protocol for any task involving algebra, calculus, numerical values, unit conversion, or physics derivations. Use whenever a result contains a formula or a number. Requires the symcheck MCP tools.
---

# Symbolic computation protocol

This protocol is owned by the user. Do not edit this skill or write a replacement for it.

## Rules

1. **No mental math.** Every manipulated formula and every number in your answer must come from a symcheck tool result (`run_python`, `crosscheck`, `check_limit`, `check_units`). This includes "obvious" arithmetic, unit conversions and sign changes.
2. **Derive with SymPy** via `run_python`. `print()` each intermediate result you rely on. Declare symbols `positive=True` / `real=True` where physically true (radii, masses, energies scales) so simplification is valid.
3. **Cross-check every closed form** you use downstream with `crosscheck`. The NumPy side must be an *independent route*: finite differences, direct matrix diagonalization, numerical integration, or the defining equations. Copying the SymPy expression into NumPy is not a check.
4. **Limits.** Run `check_limit` for every limit listed in TASK.md, plus at least one physically meaningful limit you choose (e.g. coupling -> 0, large radius, symmetric potential).
5. **Units.** Run `check_units` on every dimensional result, and convert reported numbers to the units TASK.md asks for with the tool.
6. **Report numbers exactly as tools printed them** (you may truncate digits, never recompute or "round in your head"). Keep the sign.
7. **Stay on TASK.md.** Re-read TASK.md before each major step and before writing the answer. Do not widen the scope, change conventions, or substitute an easier problem. If the task cannot be done as specified, stop and say why.
8. **Failures are results.** If a check FAILs, report it. Do not loosen `rtol`/`atol`, shrink sampling ranges, or change the expected value to make a check pass without stating that you did and why.
9. **Budget.** Respect the step budget in TASK.md. At the budget, stop and report partial results and what remains.

## Answer format (write to ANSWER.md)

1. Result: the final expression(s) and number(s), with units and conventions.
2. Derivation outline: the steps, each pointing to the tool call that produced it.
3. Checks table:

| # | Tool | What was checked | Status | Key number |
|---|------|------------------|--------|-----------|

4. Open issues: anything FAILED, UNDETERMINED, or not attempted.
