# symcheck

Tool-enforced "no mental math" for a local agent (Hermes Agent on top of Strata / Qwen3.8-Flash-Next).
The idea: put the discipline in the tools and in an external audit, not only in the prompt.

| Piece | Where | Role |
|---|---|---|
| MCP server | `symcheck/server.py` | Tools: `run_python`, `crosscheck`, `check_limit`, `check_units`. Every call is logged to JSONL. |
| Core | `symcheck/core.py` | Runs model code in a separate low-priority, single-thread process with a timeout. |
| Protocol skill | `skills/symbolic-computation/SKILL.md` | The rules the agent follows. **Lock it** (read-only), since Hermes edits its own skills. |
| Task template | `templates/TASK.md` | Goal, conventions, acceptance criteria written *before* the run, scope, budget. |
| Audit | `symcheck/audit.py` | Every number in ANSWER.md must appear in a logged tool *result* (or TASK.md). Flags untraced numbers and sign flips. |
| Verifier prompt | `templates/VERIFY_PROMPT.md` | For a fresh session that sees only TASK.md + ANSWER.md and re-runs checks. |

## Status

- Core tools and audit: tested locally (`python -m pytest tests -q`, 9 tests, ~4 s, single-threaded).
- MCP server wrapper: compiles, **not yet exercised against the `mcp` package or Hermes** (not installed on the Mac). First thing to do on the desktop.
- Hermes config keys below are from the Hermes docs (`mcp_servers` in `~/.hermes/config.yaml`); check against your installed version.

## Install

```bash
python3 -m venv ~/.venvs/symcheck
~/.venvs/symcheck/bin/pip install -r requirements.txt
~/.venvs/symcheck/bin/python -m pytest tests -q
```

The server's Python is also the Python that runs the model's code (`sys.executable`), so sympy/numpy/scipy must be in this venv.

`~/.hermes/config.yaml`:

```yaml
mcp_servers:
  symcheck:
    command: /home/<you>/.venvs/symcheck/bin/python
    args: ["/path/to/symcheck/symcheck/server.py"]
    env:
      SYMCHECK_LOG: /path/to/agent_runs/symcheck_log.jsonl
      SYMCHECK_THREADS: "1"
      SYMCHECK_NICE: "10"
      SYMCHECK_TIMEOUT: "120"
```

Then `/reload-mcp` in a Hermes chat (or restart Hermes) and confirm the four tools are listed.

Skill: copy `skills/symbolic-computation/` into your Hermes skills directory, then make it read-only
(`chmod -R a-w <skills dir>/symbolic-computation`). Keep the master copy here under version control and
diff it occasionally.

Hermes hygiene for math tasks:
- Restrict toolsets to symcheck + file access (`hermes tools`); fewer tools, less wandering.
- Start research tasks without carried-over memory.
- Make sure no OpenRouter key is configured, so nothing (e.g. vision/web summarization) leaves the machine.

## Per-task workflow

```bash
mkdir -p ~/agent_runs/2026-11-xx_alpha_planar && cd $_
cp /path/to/symcheck/templates/TASK.md . && $EDITOR TASK.md     # acceptance criteria BEFORE the run
date +%Y-%m-%dT%H:%M:%S > started_at
```

In Hermes: *"Read TASK.md in ~/agent_runs/... and follow the symbolic-computation skill."*

Afterwards:

```bash
python /path/to/symcheck/symcheck/audit.py ANSWER.md --log /path/to/agent_runs/symcheck_log.jsonl --task TASK.md --since "$(cat started_at)"
```

Then open a fresh Hermes session (or call Strata's API directly) with `templates/VERIFY_PROMPT.md`.

## Limits of this setup

- Process isolation only; model code can read/write your files. Use a separate user or container if that matters.
- The audit proves provenance, not correctness: a model can `print(0.4)`. The crosscheck (independent route) and the verifier are what catch wrong physics.
- `check_units`: `m` is metre, `s` second, `T` tesla, `h` hour. Use `m_e`/`m0` for the electron mass.
- Memory cap (`SYMCHECK_MEM_MB`) is enforced on Linux only.

## Next: benchmark

3–5 problems with answers you already know (e.g. planar Rashba alpha from a known k·p formula, a Kane-model limit,
a value from a previous sp_fem run), each as a TASK.md. Run with and without the skill/tools and score with the audit
and verifier, so you measure whether the protocol helps.
