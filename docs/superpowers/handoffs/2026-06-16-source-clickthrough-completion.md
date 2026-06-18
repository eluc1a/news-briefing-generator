# Click-through to Sources — Completion Handoff

**Branch:** `dev` (feature cut from plan commit `40b264d`; base for diffing is `40b264d`)
**Date:** 2026-06-16
**Plan:** `docs/superpowers/plans/2026-06-15-source-clickthrough.md`
**Spec:** `docs/superpowers/specs/2026-06-15-source-clickthrough-design.md`

---

## TL;DR

Feature is **implemented, reviewed, tested (180 passed), committed, and live** on
themorningfox.com. All five plan tasks done via subagent-driven development
(implementer + spec review + code-quality review each), plus an opus final
review that returned READY TO MERGE with zero Critical/Important issues.

The web edition now links every synthesized item out to its source: lead
headline, every panel lede headline, every panel `also` headline, and every
brief (trailing `— <outlet> ↗`). Generation is **single-source** per item; the
schema and frontend are multi-source-ready (2+ → tap-to-open popover) but the
generator emits exactly one validated source per item by design.

The **only** thing not done is a human visual/tap eyeball on the live site —
no headless browser is available on `fox`, so the 2+ popover feel and mobile
tap-to-open could not be automated. The 0-source (legacy) and 1-source paths
WERE verified structurally (DOM-shim render harness) and over HTTPS. User chose
**"Keep dev as-is"** (no merge to `main`, no push) and the **"Lightweight
publish (no print)"** path to surface the feature on the live site.

---

## What was done this session

Four feature commits on `dev` (base `40b264d`):

- `4aacd22` feat(briefing): add `Source` model + `sources`/`lede_sources` fields
  to `schema.py` (`LeadStory`, `PanelItem`, `Panel`, `Brief`; all
  `default_factory=list` so legacy JSON validates). +2 schema tests.
- `24a05ae` feat(briefing): `generate_front_matter` resolves the lead's
  `lead_source_url` to an outlet via `source_by_url` and attaches `lead.sources`.
  +1 generator test.
- `cc3fe13` feat(briefing): internal draft models (`_PanelItemDraft`,
  `_PanelDraft`, `_BriefDraft`) carry a per-item `source_url`; prompt rules added
  to `PANEL_STRUCTURE_RULES` / `BRIEFS_STRUCTURE_RULES`; `generate_panel` /
  `generate_briefs` validate every echoed URL against the input set (raises
  `ValueError` → drives existing `_call_with_retry` → `GeneratorFailure`) and map
  drafts → public `Panel`/`Brief` with outlet resolved from input (never LLM).
  `_BriefsResponse.briefs` is now `list[_BriefDraft]`. +4 generator tests.
- `518d4d5` feat(web): `web/app.js` helpers `srcAnchor`/`sourcePopover`/
  `linkifyHeadline`/`trailingAffordance`, wired into `renderLead`/`renderPanels`/
  `renderBriefs`; outside-click + Esc popover dismissal. `web/style.css`
  `.src-link`/`.src-credit`/`.src-count`/`.src-popover` + `@media (hover:hover)`.

Verification performed:
- Full suite: **180 passed** (`./.venv/bin/pytest -q`).
- Task 4 live E2E: `./.venv/bin/python -m jina_clone briefing generate --out
  /tmp/src-check.json` → all 27 items resolved to exactly one `(outlet, url)`,
  zero empties, zero `?`. URL slugs matched headlines on spot-check. Note: a few
  AI-panel items show the *feed* outlet (e.g. "Hacker News") rather than the
  link's domain (cohere.com) — expected; `source` = the feed that surfaced it.
- Web render structural check (no browser available — `/tmp/render-check.mjs`,
  Node DOM shim): with-sources → 27 `src-link` anchors, lead linked, every brief
  has a trailing link; legacy/no-sources → 0 anchors, no error, text intact.
- Final opus review: READY TO MERGE.

Doc + live publish (post-implementation):
- `docs/web-ui-ux-suggestions.md` #3 marked implemented — **on disk only**; this
  file is **gitignored** (`.gitignore:20` `docs/*`, with `docs/superpowers/`
  negated). No commit exists or should exist for it.
- Lightweight publish: rendered `/tmp/src-check.json` to a PDF **offline (no
  print, no DB row, no ntfy)** and published it as `2026-06-16-morning.json` via
  `jina_clone.briefing.web.publish_web_outputs` (writes JSON + rebuilds
  `index.json`). It is now the newest edition, so the site loads it by default.

---

## What is NOT done

1. **Human visual/tap verification on the live site.** No Chromium/Chrome/
   Playwright on `fox`, so this could not be automated. Open themorningfox.com
   (hard-refresh once — see caveat below) and confirm: lead/panel/`also`
   headlines are links with an outlet credit; each brief has a trailing
   `— <outlet> ↗`; a legacy edition (`?edition=2026-06-07-morning`) renders plain
   with no console errors. The **2+ source popover** (tap-to-open on mobile,
   hover on desktop) is **untested in a real browser** — but it is dormant in
   production because generation emits exactly one source per item.

2. **(Follow-up, non-blocking) `srcAnchor` href scheme guard.** `web/app.js`
   `srcAnchor` sets `a.href = s.url` with no `http(s)`-only check. Safe today
   (URLs come only from the validated input set, never raw LLM text). Worth
   hardening only if multi-source *generation* later admits LLM-supplied URLs.

3. **(Out of scope, deferred) Multi-source generation.** Generator stays
   single-source. Relaxing `source_url` → `source_urls: list[str]` + a prompt
   change is gated on Task 4's attribution eyeball (which passed). Schema/web are
   already multi-source-ready. PDF/`renderer.py`/DB/fetch were intentionally not
   touched.

---

## Working-tree state at handoff

- Branch `dev` at HEAD `518d4d5`.
- `dev` is **42 commits ahead of `origin/dev`** — branch effectively never
  pushed (user chose Keep-as-is; do NOT push without explicit go).
- Feature commits vs base: `git log --oneline 40b264d..518d4d5` →
  `518d4d5 cc3fe13 24a05ae 4aacd22`.
- `git diff --stat 40b264d..518d4d5`: 6 files, +298/−12 (schema.py, generator.py,
  app.js, style.css, test_briefing_schema.py, test_briefing_generator.py).
- Modified, uncommitted (NONE are this feature's source — pre-existing or
  runtime): `.env.example`, `CLAUDE.md`, `jina_clone/briefing/feed.py`,
  `briefings/index.json` (rebuilt by the lightweight publish).
- Untracked: `briefings/2026-06-16-morning.json` (+ its `.pdf`),
  `briefings/2026-06-08-test-morning.json`, `briefings/2026-06-15-evening.json`,
  `assets/`, `jina_clone/briefing/static/morningfox.png`, several prior handoff
  docs. `briefings/*.json` are intentionally untracked per CLAUDE.md.
- **Deployed = local:** nginx `root /home/elucia/dev/jina-clone/web` serves the
  live site directly from this checkout; `/editions/` aliases to `briefings/`.
  Served `app.js`/`style.css` confirmed byte-for-byte identical to disk over
  HTTPS. No deploy step exists — committing the file IS deploying it.

---

## How to resume

1. **Sanity check:** `git status` and `git log --oneline 40b264d..HEAD`; run
   `./.venv/bin/pytest -q` (expect `180 passed`).
2. Confirm the live edition: `curl -s --resolve themorningfox.com:443:127.0.0.1
   https://themorningfox.com/editions/index.json` — newest should be
   `2026-06-16-morning.json`.
3. Do item #1 above (human browser eyeball). Hard-refresh first.
4. If multi-source generation is wanted next, start from the plan's
   "Out of scope" section and the spec; it's a generator + prompt change, schema/
   web already support it.
5. **Do not push `dev` or merge to `main`** without explicit user instruction —
   user chose "Keep dev as-is" this session.

---

## Process / decisions

- User constraint, verbatim choices this session: finish = **"Keep dev as-is"**;
  publish = **"Lightweight publish (no print)"**.
- Why the user "saw no change" initially: the feature code was already deployed
  (nginx serves the checkout), but every published edition predated the feature
  and carried no `sources`, so the frontend correctly rendered them link-free.
  Fixed by publishing a new edition (`2026-06-16-morning`) that carries sources.
- A `curl … | grep -c` reported `0` for `linkifyHeadline` in the served app.js —
  this was a **pipe/buffering artifact**; `curl -o file` + `diff` proved the
  served file is identical to disk and contains the feature. Not a real problem.

---

## Useful commands

```bash
# Re-publish the preview edition (offline, NO print/DB/ntfy):
./.venv/bin/python - <<'PY'
from pathlib import Path; from datetime import datetime
from jina_clone.briefing.schema import Briefing
from jina_clone.briefing import renderer as r
from jina_clone.briefing.web import publish_web_outputs
b = Briefing.model_validate_json(Path("/tmp/src-check.json").read_text())
r.render_pdf(b, Path("briefings/2026-06-16-morning.pdf"),
             generated_at=datetime.now().strftime("%H:%M ET"), iso_date="2026-06-16")
publish_web_outputs(b, briefings_dir=Path("briefings"), iso_date="2026-06-16", edition="morning")
PY

# Verify served assets match disk:
curl -s --resolve themorningfox.com:443:127.0.0.1 https://themorningfox.com/app.js -o /tmp/served.js
diff web/app.js /tmp/served.js && echo IDENTICAL
```
