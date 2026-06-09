# Briefing `claude -p` CLI Backend — Handoff

**Branch:** `dev` (merged into `main`; both at `71e9fc4`)
**Date:** 2026-05-29
**Plan:** `docs/superpowers/plans/2026-05-28-briefing-claude-cli-provider.md`
**Spec:** `docs/superpowers/specs/2026-05-28-briefing-claude-cli-provider-design.md`

---

## TL;DR

The plan (drive briefing LLM generation through `claude -p` subscription auth instead of the Anthropic API) is fully implemented, reviewed, tested (128 passing), merged to `main`, and deployed: scheduling moved from the container crontab to elucia's host crontab (08:10 / 20:10 ET). The live E2E uncovered and fixed two root causes (extended-thinking timeout; project-context contamination) plus an anti-agentic guard.

**BUT the backend is NOT yet reliable in production.** Three real cron runs since deploy: 28 May evening (brother-87, 38912 bytes) = real ✓; 29 May **morning (brother-88, 26623 bytes) = EMERGENCY edition** ✗. The morning failure is a *new third failure mode*: `generator failed — using emergency edition: claude -p exited 1:` (empty stderr) on a concurrent panel call. Root cause NOT yet determined — suspected subscription rate/usage limit under concurrency (semaphore=3), or a transient. This is the #1 open item; do not consider the project done until it's diagnosed.

---

## What was done this session

8 commits, `f185d3e..71e9fc4` (4 files: `crontab`, `docs/ops/host-briefing.cron`, `jina_clone/briefing/generator.py`, `tests/test_briefing_cli_backend.py`; +289/-14):

- `3b5dc48` + `8c114aa` — `_cli_call_llm`: subprocess backend shelling to `claude -p --output-format json`, strips `ANTHROPIC_API_KEY` from child env, semaphore cap, timeout+kill+reap, usage/cost capture. 4 unit tests.
- `14ab966` + `a5e69dc` — `_build_default_call_llm` + `BRIEFING_LLM_BACKEND` switch (default `cli`, `api` fallback). Replaced 3 duplicated wrapper blocks. +2 routing tests.
- `278b136` — removed the 2 `briefing run` lines from container `crontab`; added documented host fragment `docs/ops/host-briefing.cron`.
- `7d19b07` — **fix: disable extended thinking.** `claude -p` enables it by default → ~14k thinking tokens, **162s/call > 120s timeout**. Set `MAX_THINKING_TOKENS=0` in child env → ~10s/call. (Evidence: `duration_ms:162319`, `output_tokens:14104`, `result` only 2160 chars.)
- `0edd556` — **fix: isolate from project context.** Run from neutral cwd (`tempfile.gettempdir()`) + `--setting-sources ""`, else `claude` auto-discovers repo CLAUDE.md + `.claude/` hooks (superpowers SessionStart) and the model emits "I'm a subagent dispatched…" instead of JSON. Also cut per-call cost ~0.05→0.005.
- `71e9fc4` — **fix: anti-agentic guard.** Appended `_CLI_SYSTEM_GUARD` (headless, no tools/network) to the system prompt on the CLI path only — `claude -p`'s agent persona otherwise tried to "authenticate"/"fetch current data".

Deployment actions (system state, not in git):
- Host crontab installed (idempotent append; preserved existing entries). `crontab -l | grep -c "jina_clone briefing"` = 2.
- Container rebuilt (`docker compose up -d --build`); container crontab now only runs `fetch`.
- `logs/briefing.log` chowned root→elucia (`sudo -n chown elucia:elucia`) so the host-cron `>>` redirect works.

Verification done this session (all passed at the time): 128-test suite; 9/9 faithful `assemble_briefing` rounds; `briefing generate` real content read via `pdftotext`; one real `briefing run` printed brother-86 (39936 bytes, real); simulated minimal cron-env `briefing generate` produced real content.

Memory written: `~/.claude/projects/-home-elucia-dev-jina-clone/memory/project_claude_cli_backend_gotchas.md` (indexed in MEMORY.md).

---

## What is NOT done

1. **`claude -p exited 1` (empty stderr) on concurrent panel calls — INTERMITTENT, UNRESOLVED.** 29 May 08:10 cron printed the emergency edition (brother-88, 26623 bytes). Log (`logs/briefing.log` ~line 31279-31283): front_matter call succeeded (output=657), then `generator failed — using emergency edition: claude -p exited 1:` with empty stderr; `calls=1`. **Diagnostic gap:** `_cli_call_llm` builds the nonzero-exit error from STDERR only; `claude -p --output-format json` likely emits its error in STDOUT, which is discarded on nonzero exit — so the actual cause was lost. **Start here:** (a) include `stdout[:500]` in the `returncode != 0` `GeneratorFailure` message; (b) consider whether semaphore=3 trips a subscription concurrency/usage limit — test `BRIEFING_CLI_CONCURRENCY=1`; (c) consider a retry/backoff on transient exit-1. Reproduce with the cron-env simulation (see Useful commands) run repeatedly, or wait for the next cron firing.
2. **No alerting actually fires.** `notify_failure` exists but confirm ntfy is configured; the only signal today was the printed emergency sheet. The emergency edition headline routes to "journalctl + ntfy".
3. **Retry count is 2 and does not help agentic/exit-1 failures.** `_call_with_retry` appends a pydantic JSON error to the prompt — unhelpful when the failure is a process exit or a refusal. Consider failure-type-aware retry.

---

## Working-tree state at handoff

- Branch `dev` at `71e9fc4` (HEAD); `main` also at `71e9fc4` (fast-forwarded).
- No git remote configured — nothing pushed, nowhere to push.
- Uncommitted, modified (PRE-EXISTING, unrelated to this work — left untouched all session): `jina_clone/briefing/live_data.py`, `tests/test_live_data.py`.
- Deployed = local: host cron runs the committed code at `71e9fc4` directly from this working tree (`cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone briefing run`).

---

## How to resume

1. **Sanity check:** `git -C /home/elucia/dev/jina-clone status`; `git log --oneline -3`; confirm HEAD = `71e9fc4`.
2. **Read the failure:** `grep -nE "2026-05-29|claude -p exited|emergency|llm totals" logs/briefing.log | tail -40`. Check whether later cron runs (next 08:10/20:10) also failed: `lpstat -W completed -o brother | head` (real ≈ 38-40KB; emergency ≈ 26.6KB).
3. **Improve diagnostics first (item 1a):** in `_cli_call_llm`, add stdout to the nonzero-exit `GeneratorFailure` so the next failure is legible. Add/adjust a unit test in `tests/test_briefing_cli_backend.py`.
4. **Reproduce under load:** run the cron-env simulation (below) in a loop; if exit-1 recurs, test `BRIEFING_CLI_CONCURRENCY=1`.
5. Do NOT print to iterate — use `briefing generate --out /tmp/x.json` (no print) and read the JSON/PDF. User constraint this session: *"generate the files and read the files yourself before printing."*
6. Full suite before any commit: `./.venv/bin/pytest -q` (hits real Postgres per CLAUDE.md).

---

## Useful commands

```bash
cd /home/elucia/dev/jina-clone
# Generate only (NO print), read result:
./.venv/bin/python -m jina_clone briefing generate --out /tmp/b.json
python3 -c "import json;d=json.load(open('/tmp/b.json'));print(d['lead']['headline']);print(len(d['panels']),'panels',len(d['briefs']),'briefs')"
# Render + inspect as text (NO print):
./.venv/bin/python -m jina_clone briefing render /tmp/b.json --out /tmp/b.pdf && pdftotext -layout /tmp/b.pdf - | head -60
# Simulate the host-cron environment (minimal env), generate only:
env -i HOME=/home/elucia LOGNAME=elucia SHELL=/bin/bash \
  PATH=/home/elucia/.npm-global/bin:/home/elucia/dev/jina-clone/.venv/bin:/usr/bin:/bin \
  bash -c 'cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone briefing generate --out /tmp/cronsim.json'
# Tunables (generator.py module constants / env): BRIEFING_LLM_BACKEND, BRIEFING_CLI_TIMEOUT(120),
# BRIEFING_CLI_CONCURRENCY(3), CLAUDE_BIN. Backend "api" reverts to the Anthropic API path.
crontab -l | grep briefing   # host schedule (08:10 / 20:10 ET)
```

---

## Out-of-scope noticed (NOT touched)

- The pre-existing APITimeoutError tracebacks in `logs/briefing.log` before 2026-05-28 20:10 are from the old API path / container runs prior to deploy — not the new CLI backend.
- `jina_clone/briefing/live_data.py` + `tests/test_live_data.py` carry uncommitted edits from prior work; out of scope here.
