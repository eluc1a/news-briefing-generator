# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Must-read context

Before touching code, read these:

- `docs/architecture-components.md` — reference map of the three
  components (jina extractor, RSS/fetch job, briefing generator): what
  each does, where the code lives (`file:line`), how they differ, and how
  they integrate through the shared `entries` table. Read this first for
  any "how does X work / where is X" question.
- `README.md` — project overview and how to add new sources. Parts
  predate later work: sources now live at `config/sources.yaml` (not the
  repo root) and the daily summarize cron it describes no longer runs.
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

# Briefing — runs on the HOST, not in Docker (needs the subscription-authed
# `claude` CLI; see Gotchas). `run` = generate + render + print + DB row.
./.venv/bin/python -m jina_clone briefing run --edition=morning   # or evening
./.venv/bin/python -m jina_clone briefing generate --out /tmp/b.json  # fetch+LLM only
./.venv/bin/python -m jina_clone briefing render /tmp/b.json          # JSON → PDF, offline
./.venv/bin/python -m jina_clone briefing print path/to.pdf           # submit to CUPS
./.venv/bin/python -m jina_clone.briefing.run_web --edition=morning   # run + web JSON publish

# Fetch manually (hourly in-container cron normally does this; reads .env)
./.venv/bin/python -m jina_clone fetch

# Docker (on fox — runs the extractor HTTP service + hourly fetch cron)
docker compose up -d --build           # build + start
docker compose exec extractor python -m jina_clone fetch
docker compose logs -f extractor
tail -f logs/fetch.log logs/briefing.log
```

## Architecture

Single Python package `jina_clone/` serves three roles:

1. **FastAPI extractor service** (`main.py`) — a thin wrapper around
   `jina_clone.extractor.core.extract_article`. Serves `GET /extract?url=`
   and `GET /health`. Used by external callers (n8n).
2. **Fetch job** (`python -m jina_clone fetch`) — invoked hourly by
   in-container cron. Discovers articles from `config/sources.yaml`
   (RSS or CSS-selector scrape), extracts, inserts into `entries`.
3. **Briefing pipeline** (`python -m jina_clone briefing run`) — invoked
   twice daily by **host** cron (08:10 / 20:10 ET, see Gotchas). Pulls a
   12h window of articles from `entries`, makes six per-section LLM calls
   (front matter + 4 panels + briefs), renders a 2-page broadsheet PDF
   with WeasyPrint, prints it duplex to the `brother` CUPS queue, sends an
   ntfy notification, and logs a `news_summaries` row. The
   `run_web` variant additionally publishes JSON for themorningfox.com.

There is also a legacy **summarize job** (`python -m jina_clone summarize`,
`jina_clone/summarizer/`). It is **deprecated** — no cron runs it; the
briefing has its own built-in summarization. Don't build on it.

The extractor + fetch are packaged into one Docker image with `cron` +
`uvicorn`. The container uses `network_mode: host` so the batch jobs can
reach fox's Postgres (bridge IPs are rejected by pg_hba.conf). The
briefing runs directly on the host out of this checkout's venv.

### Module responsibilities

- `jina_clone/extractor/core.py` — pure `extract_from_html(html)` and
  async `extract_article(url)`. Strips nav/footer/header/aside; title
  preferred from first heading, falls back to `<title>`.
- `jina_clone/sources/rss.py` + `scrape.py` — two discovery paths; both
  return `list[DiscoveredItem(url, published)]`. Scrape uses a CSS
  selector from `config/sources.yaml`.
- `jina_clone/storage/db.py` — asyncpg pool + CRUD. All queries are scoped
  to our sources by `source IN (...)` so we coexist with another pipeline
  already writing to `entries`. `fetch_section_articles` is the briefing's
  ranked query: per-source cap (default 5) with per-source `source_caps`
  overrides applied via COALESCE.
- `jina_clone/jobs/` — orchestrators with injected callables (fakes
  possible in tests). `fetch.py`: discovery → dedup → extraction → insert.
  `briefing.py`: `assemble_briefing` + `run_briefing` — fetch sections →
  LLM calls → render → print → notify → `insert_summary`, with an
  emergency-fixture fallback so a paper always prints.
- `jina_clone/briefing/` — the active product. `config.py` loads
  `config/briefing_categories.yaml` (sections, limits, per-source caps).
  `generator.py` makes the per-section LLM calls; backend selected by
  `BRIEFING_LLM_BACKEND` — default `cli` shells out to `claude -p`
  (subscription auth), `api` uses `AsyncAnthropic`. `schema.py` is the
  pydantic `Briefing` model. `renderer.py` (WeasyPrint + `templates/` +
  `static/`), `printer.py` (lp duplex), `notify.py` (ntfy),
  `live_data.py` (weather/markets with stub fallbacks, caches in
  `cache/`). `web.py` + `run_web.py` publish edition JSON + `index.json`
  into `briefings/` for the static site in `web/`.
- `web/` — static frontend for themorningfox.com (vanilla JS, served by
  nginx with `/editions/` aliased to `briefings/`). Purely additive on
  top of the pipeline.
- `jina_clone/summarizer/` — **deprecated** provider abstraction
  (`LLMProvider` Protocol, `claude.py`/`openai.py`/`gemini.py`,
  `build_provider`). Only the legacy summarize job uses it.
- `jina_clone/cli.py` — argparse + asyncio.run + dotenv; wires jobs to
  real dependencies. Subcommands: `fetch`, `summarize`, `briefing
  {generate,render,print,run}`.

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
- **Config in YAML under `config/`, not DB.** `config/sources.yaml`
  (feeds) and `config/briefing_categories.yaml` (sections, caps) are
  mounted read-only into the container; edits take effect on the next
  job run, no rebuild.
- **Per-section LLM fan-out in the briefing.** Six separate calls (front
  matter, one per panel, briefs), each fed only its section's articles,
  with a per-source cap (default 5) plus `source_caps` overrides (e.g.
  arXiv clamped to 2). This fixed single-source skew — do not collapse
  back to one big prompt.
- **Briefing failures still print.** `run_briefing` falls back to
  `briefing/fixtures/emergency.json` and notifies via ntfy on failure;
  LLM failure never leaves the printer silent.
- **`run_web` is additive.** It reuses `run_briefing` unchanged and only
  injects a render wrapper that also writes web JSON; web-publish
  failures are swallowed so the paper is never blocked.

## Test database

Tests hit a **real** Postgres at `jina_clone_test` on fox (not `mcp_news`,
not SQLite, not mocked). `tests/conftest.py` provides a `db` fixture that
truncates both tables before each test. `TEST_DATABASE_URL` env var
overrides the default.

If you ever recreate the test DB, derive the DDL from production:
`pg_dump --schema-only -t entries -t news_summaries` against `mcp_news`
(the original plan doc with the DDL was lost).

Pytest uses `asyncio_default_fixture_loop_scope = "session"` *and*
`asyncio_default_test_loop_scope = "session"` — both are required for the
session-scoped `db_pool` and function-scoped `db` fixtures to share an
event loop without asyncpg raising "Future attached to a different loop".
Documented inline in `pyproject.toml`.

## Gotchas

- **Two crontabs.** The in-container crontab (`crontab` file in the repo)
  runs only the hourly `fetch`. The briefing lines live in the **host**
  crontab (`crontab -l` as elucia) because the default LLM backend shells
  out to the subscription-authed `claude` binary in
  `~/.npm-global/bin`, which doesn't exist in the container.
- The compose file uses `network_mode: host` and `PORT=8090` in `.env`.
  Don't revert to bridge/port-mapping without also fixing pg_hba.conf on
  fox.
- The `.env` file needs at least `DATABASE_URL` and a valid
  `LLM_PROVIDER` — `Settings.from_env()` fails fast on those. Provider
  API keys are only needed by what you run: the briefing's default
  `cli` backend needs none (subscription auth via the `claude` binary).
  Briefing live-data keys (`WEATHER_API_KEY`, `STOCK_API_KEY`,
  `FRED_API_KEY`) and `NTFY_TOPIC` are optional — each falls back to
  stubs/no-ops.
- Cron inside the container inherits a minimal environment; jobs rely on
  `load_dotenv()` reading `/app/.env`. The `.env` is volume-mounted from
  the host, so host edits apply to the next cron firing.
- A briefing cron run that executed as root can leave a root-owned PDF
  at the target path in `briefings/`; a manual run then fails to
  overwrite it — `rm` it first.
- `briefings/*.json` and `web/editions` (a local-preview symlink) are
  intentionally untracked. Never `git add -A` / `git add .` in this repo
  — it has already swept runtime artifacts into a feature commit once.
- `news_summaries.generated_at` is `timestamp without time zone` — we
  rely on the column default `now()`, not a client-side value, so
  tz-naivety is handled server-side.
