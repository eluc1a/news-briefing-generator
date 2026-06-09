# Briefing AI-Feed Rebalance — Handoff

**Branch:** `dev` (working branch; `main` is the PR base)
**Date:** 2026-06-08
**Plan:** none (low-ceremony, per CLAUDE.md right-sizing — direct commits + checkpoints)

---

## TL;DR

The AI panel was skewing toward arXiv academic papers. Root cause was **timing,
not the per-source cap**: arXiv cs.AI dumps its full ~140-paper batch at ~04:00
UTC, and the morning edition's 12h window (≈00–12 UTC) catches that dump while
missing the US-daytime news cycle (TechCrunch/404/AWS publish 12–24 UTC). Two
fixes shipped and committed (`decf7b4`, `ab14105`), full suite green (139
passed): a config-driven `source_caps` override (arXiv clamped to 2) and two new
builder-ecosystem sources (GitHub Trending + HN Show HN), both validated
end-to-end from this host.

**Pending decisions for the user** (work is paused here, nothing blocking):
(1) whether to build *feed-content passthrough* to unlock the three subreddits
the user wanted; (2) whether to run a live `fetch` now to seed the new sources
vs. wait for hourly cron. **Also flag:** `decf7b4` accidentally swept in
unrelated pre-existing changes via `git add -A` (see Working-tree state).

User's stated interest, verbatim: *"I'm more interested in learning about new
harnesses, new and interesting github repos from githubawesome, the most popular
page on github, newest skills and agents, new agent techniques, things like
that."*

---

## What was done this session

- **Diagnosed feed ingestion** (read-only first): of 23 configured AI feeds, ~11
  actively land rows; 3 produce zero (Karpathy, The Gradient, Language Models &
  Co.) because their newest posts are months old and `fetch.py:49` drops items
  older than the 24h window; Anthropic Engineering's third-party mirror is
  frozen at 2024-09-19. Feeds reach the briefing via Postgres `entries`
  (`run_web.py:69` → `fetch_section_articles`), NOT directly.
- **Root-caused the arXiv skew**: morning window vs. arXiv 04:00-UTC batch
  timing (evidence: arXiv 2871 papers in 00–12 UTC vs 0 in 12–24 UTC over 14d;
  news sources inverted). The per-source cap was already working; arXiv does not
  bubble to the top by timestamp.
- **Commit `decf7b4`** — config-driven `source_caps` override:
  - `jina_clone/storage/db.py`: `fetch_section_articles` gained
    `source_caps: dict[str,int] | None`; applied via `COALESCE` subquery on
    `unnest($5,$6)` in the ranking SQL.
  - `jina_clone/briefing/config.py`: `BriefingConfig.source_caps`
    (`Mapping[str,int]`, `MappingProxyType`, optional/defaults empty).
  - `config/briefing_categories.yaml`: `source_caps: {"arXiv cs.AI": 2}`.
  - `jina_clone/jobs/briefing.py`: threads `source_caps=dict(config.source_caps)`
    into both fetch calls.
  - Tests: `test_storage.py::test_fetch_section_articles_per_source_cap_override`,
    `test_briefing_config.py::test_source_caps_loaded` + `_optional`; updated 10
    `fetch` fake signatures in `test_jobs_briefing.py` to accept `source_caps`.
- **Commit `ab14105`** — added GitHub Trending (scrape,
  `link_selector: "article.Box-row h2 a"`) + HN Show HN (`hnrss.org/show`) to
  `config/sources.yaml`, both `category: ai`. Validated end-to-end: discovery →
  `extract_article` yields real 4000-char content.
- **Memory written**: `memory/project_briefing_feed_ingestion.md` (+ MEMORY.md
  index line) capturing the two-layer path, timing skew, and unfetchable feeds.

---

## What is NOT done

1. **Feed-content passthrough (the meaty follow-up).** Needed to use the three
   subreddits the user selected (r/LocalLLaMA, r/ClaudeAI, r/MachineLearning).
   Their RSS carries the post body, but `run_fetch` re-extracts the link URL and
   hits Reddit's bot-verification wall → empty content (verified: extractor
   returned `title='Reddit - Please wait for verification'`, textlen=0). Reddit
   also intermittently 403s this host's IP. **Fix:** have `DiscoveredItem` carry
   optional title/content from the feed entry; `run_fetch` uses it when present
   instead of calling `extract`. Touches `jina_clone/sources/rss.py`,
   `jina_clone/jobs/fetch.py`, + tests. Would also unlock any full-content RSS
   (Substack/newsletters) and cut redundant extraction. **Decision pending:**
   user asked whether to build this — do not start without a yes.
2. **The Sequence** (`thesequence.substack.com/feed`): Cloudflare "Just a
   moment" challenge 403s httpx even with a browser UA. Lower value; needs a
   separate Cloudflare workaround. Left out with an inline note in sources.yaml.
3. **Seed the new sources into the DB.** GitHub Trending + HN Show HN are in
   config but have no `entries` rows yet. Hourly `fetch` cron will pick them up;
   or run a live fetch to populate now. **Decision pending** — a live fetch
   writes to the real `mcp_news` DB.
4. **Optionally tune caps on the new community sources.** They fold into the AI
   panel at the default cap (5). If GitHub Trending / Show HN start crowding
   curated news, add entries to `source_caps` (mechanism already shipped).

---

## Working-tree state at handoff

- Branch `dev` at `ab14105` (HEAD). Clean working tree (`git status -s` empty).
- Branch is **6 commits ahead of `origin/dev`, 0 behind — none pushed** (incl.
  the 4 pre-session commits + this session's 2).
- **GOTCHA — `git add -A` sweep:** commit `decf7b4` (arXiv cap) unintentionally
  included pre-existing changes that were uncommitted at session start and are
  NOT part of this work:
  - `briefings/2026-06-07-morning.json` (was untracked)
  - `briefings/index.json` (was untracked)
  - `web/editions` (was untracked)
  - `web/style.css` (was modified)
  Provenance unknown to this session. Since `decf7b4` is unpushed, it can be
  amended/split if the user wants those separated — **do not rewrite history
  without asking.**

---

## How to resume

1. **Sanity check first:** `git status`, `git log --oneline 8a3fca3..HEAD`,
   `./.venv/bin/pytest -q` (expect 139 passed).
2. Read `memory/project_briefing_feed_ingestion.md` for the ingestion model and
   blocked-feed details.
3. **Surface the two pending decisions to the user** (feed-content passthrough;
   live-fetch-now vs cron) before doing either — both were explicitly teed up
   and left for the user.
4. If building feed-content passthrough: start at `jina_clone/sources/rss.py`
   (`DiscoveredItem` + `parse_feed`), then `jina_clone/jobs/fetch.py` (the
   `extract` call at ~line 61); write a failing test first (TDD). Reddit will
   still be IP-flaky from fox even after the fix — verify with a live fetch.
5. Raise the `decf7b4` accidental-sweep with the user; decide whether to leave,
   amend, or split before any push to `main`.

---

## Decision rationale (non-obvious)

- **Cap, not remove, arXiv** — user chose "Hard-cap arXiv per panel" over moving
  it to a separate research track. Kept arXiv in `ai` at cap 2.
- **Fold builder content into the AI panel** — user chose this over a dedicated
  "Builder" brief or a new 5th section. So new sources are `category: ai`.
- **Left the dead/stale feeds alone** — user chose "Leave feeds alone for now";
  Karpathy/Gradient/Language Models/Anthropic-mirror untouched by design.

---

## Useful commands

```bash
# Tests
./.venv/bin/pytest -q
./.venv/bin/pytest tests/test_storage.py::test_fetch_section_articles_per_source_cap_override -v

# Live fetch (WRITES TO PRODUCTION mcp_news) — only with user go-ahead
./.venv/bin/python -m jina_clone fetch

# Re-audit which AI feeds land rows (ad-hoc script pattern used this session)
#   query entries WHERE category='ai' GROUP BY source, counts over 24h/7d + max(uploaded_at)
```
