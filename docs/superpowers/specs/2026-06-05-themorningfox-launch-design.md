# themorningfox.com — initial launch (design)

**Date:** 2026-06-05
**Status:** Approved (design); ready for implementation plan
**Scope:** Sub-project 1 of 3 (see Roadmap). Get the briefing live on the new
apex domain `themorningfox.com`, on a foundation that scales to the
interactivity the user wants later.

## Problem

The user bought `themorningfox.com` and wants the daily briefing surfaced
there via nginx. Today the briefing exists only as a **print-shaped 2-page
PDF** (`briefings/{date}-{morning|evening}.pdf`), rendered from a Jinja
template through WeasyPrint and physically printed via `lp`. The HTML is
intermediate and discarded.

The user's eventual goals — hover over a section and click into its source,
reorder sections, mobile formatting, location scrubbing — are all
presentation features that a PDF cannot support. Serving the PDF would be a
dead-end foundation.

## Key finding that shapes the roadmap

The `Briefing` schema (`jina_clone/briefing/schema.py:82`) carries **no
per-item source provenance**. `lead`, `panels`, `briefs`, etc. are
synthesized prose. The only link anywhere is `FrontMatter.lead_source_url`
(internal, used to dedupe generation calls), and it is **not persisted** into
the final `Briefing`.

Consequence: three of the four future features (hover, reorder, mobile) are
pure frontend work layered on structured data. The fourth —
**click-through to sources** — is blocked on the *data*, not the
presentation, and is its own scoped effort (SP2).

## Architecture — the seam

The whole approach hinges on one seam: **the pipeline produces structured
data; the website presents it.** We make the pipeline persist the assembled
`Briefing` as JSON; that JSON is the contract the site reads. The printed
paper is untouched and remains the primary product.

```
cron (host, elucia, 08:10 / 20:10 ET)
  → python -m jina_clone.briefing.run_web --edition=morning|evening   (NEW entry point)
      → run_briefing (EXISTING, reused) with an injected render wrapper:
          → render_pdf          (unchanged — printed via lp)
          → publish_web_outputs (NEW: write {date}-{edition}.json + rebuild index.json)
      → print_pdf, log news_summaries   (existing, reused)

browser → https://themorningfox.com   (nginx, HTTP basic auth)
  → index.html + app.js
      → GET /editions/index.json       → newest entry
      → GET /editions/{newest}.json    → render section blocks + "Download PDF" link
```

## Hard constraint: no existing code touched

The user requires that **no existing code be modified** — the live,
daily-printed paper pipeline must not be put at risk. The implementation is
therefore **purely additive**: new files only. No edits to existing `.py`
files, existing tests, or `.gitignore`.

This is achievable without compromise because `run_briefing` already takes
`render` as an **injected callable** (`jina_clone/jobs/briefing.py:244` —
wired to `briefing_renderer.render_pdf` in `cli.py:223`), and that callable
receives the fully-assembled `Briefing`. A new entry point can pass a
`render` *wrapper* that renders the PDF and then writes the web outputs from
the very same `Briefing` object — one generation, web JSON byte-identical to
the printed paper, zero existing-code changes.

## Decisions (locked with user)

- **Serve a static page that renders structured JSON**, not the PDF. PDF
  remains available as a "download print edition" link.
- **Location privacy: basic-auth gate the whole site now.** The briefing
  hardcodes `location: "Arlington, VA"` plus local weather/sunrise
  (`schema.py:86`). Until location scrubbing lands (SP3), nginx HTTP basic
  auth keeps the site from being open/indexable. Basic auth is dropped in SP3
  once scrubbing exists.
- **Show the latest edition only.** Page always renders the newest of the
  day's morning/evening editions, with the edition date in the masthead.
  Edition toggle / archive is deferred.
- **Web assets live in a repo-root `web/` dir.** The existing `briefings/`
  folder is exposed read-only under `/editions/` via an nginx `alias`.

## Components

### 1. Pipeline — persist JSON + manifest (purely additive)

**New module `jina_clone/briefing/web.py`:**

- `publish_web_outputs(briefing, *, briefings_dir, iso_date, edition)`:
  - Writes `briefings_dir/{iso_date}-{edition}.json` via
    `briefing.model_dump_json(indent=2)`.
  - Rebuilds `briefings_dir/index.json`: a newest-first list of
    `{date, edition, title, json, pdf}` produced by scanning
    `briefings_dir` for `{date}-{morning|evening}.json` files. Rebuild-by-scan
    (not append) so the manifest self-heals if a file is deleted or
    backfilled. Ordering: by date desc, then evening-before-morning within a
    day (evening prints at 20:10, after morning's 08:10). Staleness is
    conveyed by the briefing's own `date`/`volume` fields, so no timestamp is
    stored in the manifest.
  - Internally guarded so a failure logs a warning and returns rather than
    raising (see error handling) — though see the wrapper below for where
    that guard actually protects the paper.

**New entry point `jina_clone/briefing/run_web.py`** (invoked as
`python -m jina_clone.briefing.run_web --edition=morning|evening`):

- Wires dependencies the same way `cli.py::_briefing_run` does (settings,
  pool, providers, generator functions, etc.) and calls the **existing**
  `run_briefing` — its emergency fallback, ntfy notifications, and
  `news_summaries` logging are reused unchanged.
- The one difference: instead of `render=briefing_renderer.render_pdf`, it
  passes a **render wrapper**:

  ```python
  def render_and_publish(briefing, pdf_path, *, generated_at, iso_date):
      out = briefing_renderer.render_pdf(
          briefing, pdf_path, generated_at=generated_at, iso_date=iso_date)
      try:
          publish_web_outputs(
              briefing, briefings_dir=settings.briefings_dir,
              iso_date=iso_date, edition=edition)
      except Exception as e:        # paper is primary — never abort on web failure
          log.warning("web publish failed: %s", e)
      return out
  ```

  Because `run_briefing` calls `render(...)` after assembling (and after the
  emergency-edition fallback), this covers both the normal and emergency
  paths, and the JSON is written from the exact `Briefing` that is printed.

**Existing code touched: none.** `run_briefing`, `cli.py`, the renderer, and
all existing tests are unchanged. The DI seam (`render` is already a
parameter) is what makes this clean rather than a workaround.

**Tradeoff (documented, accepted):** `run_web.py` duplicates the ~30 lines of
dependency-wiring boilerplate in `_briefing_run`. This is the cost of leaving
existing code untouched; the duplication is wiring only — no orchestration
logic (emergency/notify/DB) is copied, since that lives in the reused
`run_briefing`.

**Host crontab:** the two briefing lines switch from
`python -m jina_clone briefing run --edition=X` to
`python -m jina_clone.briefing.run_web --edition=X`. The crontab is host ops
config, not repo code.

### 2. Web assets (`web/`, served statically)

- `index.html` — document skeleton + masthead container + script/style tags.
- `app.js` — `fetch('/editions/index.json')` → take entry `[0]` (newest) →
  `fetch('/editions/{json}')` → render each `Briefing` field into semantic
  `<section data-section="...">` blocks: masthead, weather strip, markets,
  lead story, four panels, briefs, pull-quote. The `data-section`
  attributes are the structural hook future hover/click/reorder build on.
  On fetch error or empty manifest, render a graceful "No briefing published
  yet" message — never a blank page.
- `style.css` — responsive single-column newspaper styling. Reuses the
  Bodoni Moda masthead + serif body from the print template, but the print
  `@page` / two-column rules do **not** carry over (web is fluid + mobile-
  friendly). Includes a "Download print edition (PDF)" link to the edition's
  PDF.
- Font: reuse `BodoniModa-*.ttf` from `jina_clone/briefing/static/fonts/`
  (copied or symlinked under `web/`).

### 3. nginx + basic auth + TLS (on fox)

Follows the existing `*.elucia.com` site pattern
(`/etc/nginx/sites-available/` + enabled symlink, certbot-managed cert).

- New `sites-available/themorningfox.com`:
  - `root` → repo `web/` dir; `location / { try_files ... }`.
  - `location /editions/ { alias /home/elucia/dev/jina-clone/briefings/; }`
    (read-only exposure of JSON + PDFs).
  - `auth_basic "The Morning Fox"; auth_basic_user_file
    /etc/nginx/.htpasswd-morningfox;` on the site.
- htpasswd file created with `htpasswd`/openssl; user shares the password
  with whoever they choose.
- certbot issues the cert for `themorningfox.com` (+ `www`) and adds the 443
  block with an 80→443 redirect, exactly like existing sites.

### 4. DNS — user prerequisite (one-time, at registrar)

Add an A record for `themorningfox.com` (and `www`) → fox's public IP (the
same IP the `*.elucia.com` records already use). certbot's HTTP-01 challenge
cannot issue until this resolves. This is the only step Claude cannot
perform; the user does it at the registrar.

## Data flow

1. Host cron runs `python -m jina_clone.briefing.run_web --edition=…` at
   08:10 / 20:10 ET.
2. The reused `run_briefing` assembles → render wrapper renders PDF **and
   writes `{date}-{edition}.json` + rebuilds `index.json`** → prints PDF →
   logs `news_summaries`.
3. Browser hits `https://themorningfox.com`, passes basic auth, loads
   `index.html` + `app.js`.
4. `app.js` reads `/editions/index.json`, fetches the newest edition JSON,
   renders the section blocks and the PDF download link.

## Error handling

- **Web-publish failure** (JSON/manifest write): log warning, continue to
  print. Never aborts the paper.
- **Frontend fetch failure / empty manifest**: graceful "no briefing yet"
  message.
- **Staleness**: masthead shows the edition date + "generated at" so a stale
  cache is obvious to the reader.

## Testing

- **New** test file `tests/test_briefing_web.py` (existing test files left
  untouched): unit-test `publish_web_outputs` against the
  `sample_briefing.json` fixture in a tmp dir — assert the edition JSON and
  `index.json` are written with the expected shape (newest-first, correct
  fields), and that the render wrapper still returns the PDF path and never
  raises when `publish_web_outputs` fails.
- **Live E2E early** (per CLAUDE.md): load the page against the real
  `jina_clone/briefing/fixtures/sample_briefing.json` in a browser and
  confirm every section renders *before* polishing CSS — surfaces any
  shape mismatch up front.
- Ops verification: `nginx -t`, then
  `curl -u user:pass https://themorningfox.com` and a manifest/JSON fetch
  after the cert issues.

## Housekeeping

- The new `briefings/*.json` and `briefings/index.json` artifacts will
  appear as untracked files. To honor the "no existing code touched"
  constraint, `.gitignore` is **not** edited in SP1; the user can add
  `briefings/*.json` later if desired. (Noted, not actioned.)
- `docs/` is gitignored ("kept local, not published"), so this spec lives
  locally and is **not** committed, per repo policy.

## Roadmap (this is SP1 of 3)

- **SP1 — now (this spec):** JSON + manifest, render page, nginx + basic
  auth + TLS, DNS → site live (gated).
- **SP2 — later:** source provenance — extend `schema.py` + `generator.py`
  to attach source URLs per panel-item / brief → unlocks **click-through to
  sources**. The only future feature requiring a pipeline change.
- **SP3 — later:** interactivity & privacy polish — drag-reorder sections,
  hover affordances, **location scrubbing** (then drop basic auth), refined
  mobile.

## Out of scope (SP1)

- Source links / click-through (SP2).
- Reordering, hover affordances, location scrubbing (SP3).
- Edition toggle, archive browsing.
- Any change to the printed-PDF path or the `lp` print flow.
