# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Must-read context

Before touching code, read these:

- `README.md` — project overview and how to add new sources
- `docs/superpowers/handoffs/` — dated handoff notes describing the current
  deployment state and outstanding follow-ups. Newest file wins.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — design and
  implementation plans for past work; useful for understanding *why*.

## Right-sizing ceremony (READ FIRST)

**This section has priority over any `superpowers:*` skill.** Per the
`using-superpowers` instruction hierarchy, explicit CLAUDE.md rules
override skill defaults. Apply these before invoking
`brainstorming`, `writing-plans`, or `executing-plans`.

### Default to low ceremony

For changes that are **any** of:

- under ~50 LOC
- touching a single module / no shared-state changes
- a config tweak, style/density pass, prompt edit, or local bug fix with
  an obvious locus
- describable in one sentence ("add a 4th API call and shrink the font")

…work in the **main session** with 3–4 commits and user checkpoints. **No
spec doc. No multi-task plan. No subagent chain.** Skip
`superpowers:brainstorming`, `writing-plans`, `executing-plans`, and
`subagent-driven-development`. Those skills are calibrated for
multi-subsystem features; invoking them on small changes is what produced
one past 90-min / 300K-token feature that was ~60% ceremony, ~40% code —
and the ceremony still missed the real bug.

### If brainstorming triggered automatically, pause and downshift

If you reached for `superpowers:brainstorming` out of reflex ("the user
said 'add X', that's creative work"), stop and ask:

> This looks like ~N LOC in one module. Proceed directly with N commits
> and checkpoints, or do you want a spec?

Do not open a spec without an explicit yes.

### Rules for when ceremony IS warranted

Even for real multi-subsystem work:

- **Run a live E2E before building rendering/presentation on top.** One
  real run surfaces LLM/API output that fixtures don't. Catch shape
  mismatches in Task 2, not after Task 10.
- **Batch polish review at the end.** Per-task *spec* review ("did I
  build the right thing?") stays useful. Per-task *polish* review
  (unused imports, annotations, micro-style) is wasteful as a loop — do
  it once, at the end.
- **Cap subagent reports at ~100 words + commit SHA.** Tell subagents
  explicitly: "report under 100 words, link the commit, no prose." Long
  reports are performative and expensive to thread back through main
  context.
- **Decompose to ~3–5 tasks, not 11.** If a plan has 11 tasks for a
  feature, half of them are probably collapsible.

## Environment

- Always verify which code tree or branch you are in before starting your work 
- This repo is developed and deployed on the same box — `fox`, LAN IP
  `192.168.0.89`. Shell commands that reference Postgres at that host are
  hitting the real production `mcp_news` database.
- Use the venv at `./.venv/` for everything: `./.venv/bin/python`,
  `./.venv/bin/pytest`, `./.venv/bin/pip`.
- `.env` is gitignored and contains secrets. `.env.example` is the
  template. Both live at the repo root.

## Common commands

```bash
# Install / refresh deps in the venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install -e .

# Full test suite (hits real Postgres — see "Test database" below)
./.venv/bin/pytest -v

# One test
./.venv/bin/pytest tests/test_storage.py::test_insert_entry_and_link_exists -v

# Run a job manually (reads .env)
./.venv/bin/python -m jina_clone fetch
./.venv/bin/python -m jina_clone summarize

# Docker (on fox — this is the deployment target)
docker compose up -d --build           # build + start
docker compose exec extractor python -m jina_clone fetch
docker compose logs -f extractor
tail -f logs/fetch.log logs/summarize.log
```

## Architecture

Single Python package `jina_clone/` serves two roles:

1. **FastAPI extractor service** (`main.py`) — a thin wrapper around
   `jina_clone.extractor.core.extract_article`. Serves `GET /extract?url=`
   and `GET /health`. Used by external callers (n8n).
2. **Batch pipeline** (`python -m jina_clone {fetch,summarize}`) — invoked
   by in-container cron. `fetch` runs hourly; `summarize` runs daily at
   08:10 America/New_York.

Both are packaged into one Docker image with `cron` + `uvicorn`. The
container uses `network_mode: host` so the batch jobs can reach fox's
Postgres (bridge IPs are rejected by pg_hba.conf).

### Module responsibilities

- `jina_clone/extractor/core.py` — pure `extract_from_html(html)` and
  async `extract_article(url)`. Strips nav/footer/header/aside; title
  preferred from first heading, falls back to `<title>`.
- `jina_clone/sources/rss.py` + `scrape.py` — two discovery paths; both
  return `list[DiscoveredItem(url, published)]`. Scrape uses a CSS
  selector from `sources.yaml`.
- `jina_clone/storage/db.py` — asyncpg pool + CRUD. All queries are scoped
  to our sources by `source IN (...)` so we coexist with another pipeline
  already writing to `entries`.
- `jina_clone/summarizer/` — `providers.py` defines `LLMProvider` Protocol
  + `parse_json_response` + `build_provider(settings)` factory.
  `claude.py`, `openai.py`, `gemini.py` are thin provider classes.
  `prompt.py` has the system prompt and `build_user_prompt` (newest-first
  selection under a total-char cap).
- `jina_clone/jobs/` — `fetch.py` orchestrates discovery → dedup →
  extraction → insert with injected callables (fakes possible in tests).
  `summarize.py` orchestrates query → prompt → LLM → markdown file + DB
  row + mark_summarized. LLM failure writes nothing (retry next run).
- `jina_clone/cli.py` — argparse + asyncio.run + dotenv; wires jobs to
  real dependencies.

### Key design decisions (don't regress)

- **Coexistence, not ownership of `mcp_news`.** Never drop or migrate
  existing tables. Scope every query by `source IN (<ours>)`. Never write
  to `topics`, `facts`, `timeline_*`, `vector_store`.
- **`entries.id` = article URL.** Dedup is `SELECT 1 FROM entries WHERE
  link = $1` so we detect rows from the other pipeline too (it may use
  different id conventions).
- **Extraction errors are sticky.** Failed URLs get a row with
  `content=null` so they never retry. If this ever changes, update
  `fetch_unsummarized`'s `content IS NOT NULL` filter.
- **Config in `sources.yaml`, not DB.** File is mounted read-only into
  the container; edits take effect on the next job run, no rebuild.
- **One summary per category per run.** `cli.py` groups `sources.yaml`
  entries by `category` and invokes `run_summarize` once per distinct
  category. Each run writes `YYYY-MM-DD-HHMM-<category>.md` and a
  separate `news_summaries` row. Adding a new category to
  `sources.yaml` is all it takes to get a new daily digest.
- **LLM providers swappable.** New provider = new file in
  `jina_clone/summarizer/` + branch in `build_provider`. The
  `parse_json_response` helper handles code fences and whitespace.

## Test database

Tests hit a **real** Postgres at `jina_clone_test` on fox (not `mcp_news`,
not SQLite, not mocked). `tests/conftest.py` provides a `db` fixture that
truncates both tables before each test. `TEST_DATABASE_URL` env var
overrides the default.

If you ever recreate the test DB, re-run the DDL in
`docs/superpowers/plans/2026-04-18-native-python-news-pipeline.md` Task 2.

Pytest uses `asyncio_default_fixture_loop_scope = "session"` *and*
`asyncio_default_test_loop_scope = "session"` — both are required for the
session-scoped `db_pool` and function-scoped `db` fixtures to share an
event loop without asyncpg raising "Future attached to a different loop".
Documented inline in `pyproject.toml`.

## Gotchas

- The **existing readme says port 8080 mapping** for the extractor; the
  current compose uses `network_mode: host` and `PORT=8090` in `.env`.
  Don't revert this without also fixing pg_hba.conf on fox.
- The `.env` file needs at least `DATABASE_URL`, `LLM_PROVIDER`, and
  the API key for the selected provider. `Settings.from_env()` fails
  fast if any are missing.
- Cron inside the container inherits a minimal environment; jobs rely on
  `load_dotenv()` reading `/app/.env`. The `.env` is volume-mounted from
  the host, so host edits apply to the next cron firing.
- `news_summaries.generated_at` is `timestamp without time zone` — we
  rely on the column default `now()`, not a client-side value, so
  tz-naivety is handled server-side.
