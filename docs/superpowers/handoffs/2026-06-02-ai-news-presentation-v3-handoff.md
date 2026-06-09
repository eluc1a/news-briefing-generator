# AI-News Journey Presentation — Copy + Visual Revision Handoff

**Branch:** `dev` (no `origin/dev`; never pushed)
**Date:** 2026-06-02
**Predecessor:** `docs/superpowers/handoffs/2026-06-02-ai-news-presentation-handoff.md`
**Deck (out-of-repo):** `~/.agent/diagrams/2026-06-02-ai-news-journey.html` (6.3 MB, self-contained)
**Outline/spec (in-repo, untracked):** `presentations/2026-06-02-ai-news-journey-outline.md`

---

## TL;DR

The 24-slide deck was revised in two passes this session: (1) a **copy/voice rewrite** of both the outline and the rendered deck — complete sentences, depersonalized "it can be done" voice instead of first-person "I", and a de-vagued close slide; (2) a **visual/structural pass** addressing six user-reported issues. All changes were applied **in place** to the existing rendered HTML via Python string-replacement scripts (the file is 6.3 MB of base64; never edited with the Edit tool). The deck is **served and user-confirmed-good as of the last interaction** — the user verified slide 6 renders and approved the look. No headless browser exists on this box, so changes were verified structurally (24 sections balanced, JS syntax-checked with `node --check`) and by **user eyeball over an HTTP server**, not by automated screenshot QA.

State is stable and presentable. The one outstanding micro-decision (offered, not answered): whether to also change the takeaways-slide phase label "Cover · the Jina scraper" to match the just-renamed slide-14 title "The Jina Scraper Clone". No code/work is mid-flight or broken.

---

## What was done this session

**Pass 1 — copy/voice (outline + deck):**
- Rewrote `presentations/2026-06-02-ai-news-journey-outline.md` slide-facing copy: complete sentences, impersonal voice, broadened the abstract Capture/Pull/Cover/Push close (each phase now a full sentence with the gap it left). Citations/code/diagram specs left intact.
- Applied 20 matching copy edits to the rendered deck via `/tmp/deck_update.py` + one follow-up (slide-18 statement "I wanted" → "The goal was"). Key user-requested example: slide 23 "one page I read in 3 minutes" → **"one page that can be read in 3 minutes."** Title card "How do I" → "How do you". Slide 24 rebuilt from four bare KPI words into a 2×2 `knob-grid` of full explanatory sentences.

**Pass 2 — six visual/structural fixes (`/tmp/deck_v3.py`, 16 replacements + payoff + CSS block):**
1. **"The Vault" → "The Obsidian Vault"** (slide 3 roadmap card, slide 4 divider, slide 24 label). Added an authentic in-slide **Obsidian reading-view mock** on slide 5 (`.note-card`), content drawn from the real `~/life/wiki/resources/ai/prompting.md` (H1, tags, wikilinks, "Why This Matters to Me" callout) — a vector mock, **not** a screenshot (no headless browser to render one).
2. **Slide 6 diagram fit + zoom-out** — replaced broken CSS-`zoom` with `transform: scale()` (`_applyZoom` helper); capped diagram via `max-height:60vh`.
3. **Slide 20 "briefs poo" clipping** — root cause was a Mermaid web-font measurement race; gated `mermaid.run` on `document.fonts.ready` and shortened the node label to `(4 sections + briefs)`.
4. **Pipeline whitespace** — removed `.pipeline { flex:1; ... max-height:62vh }` so pipeline slides (3, 10, 12) are content-height and centered.
5. **Both real briefing pages** — rendered `briefings/2026-06-02-morning.pdf` (today's, 2 pages) to PNG via `pdftoppm`, resized to 1000px (`/tmp/brief-opt-{1,2}.png`), embedded base64 side-by-side on slide 23 in a `.payoff` layout borrowed from v2. Removed the old dashed placeholder + its bleed-bg image.
6. **Borrowed animations from v2** — count-up on slide-9 KPIs (234/16), hand-drawn circle stroke around "AI" on the title (`.circle-word`/`.circle-mark`), pulsing pipeline arrows (`arrowpulse`). All reduced-motion guarded.

**Post-fixes:**
- **Slide 6 went blank** after pass 2 (autoFit stripped the SVG `width`/`height`, collapsing it to zero). Fixed by setting intrinsic size from `viewBox` then letting CSS max-width/max-height scale it (patched autoFit). **User confirmed slide 6 now renders correctly.**
- **Slide 14 divider** renamed "The Jina Scraper" → **"The Jina Scraper Clone"** (last user request, applied).

---

## What is NOT done

1. **Open micro-decision (user's):** the takeaways slide (24) phase card still reads "Cover · **the Jina scraper**" (lowercase, no "Clone"). User was asked whether to align it with the new slide-14 "The Jina Scraper Clone" title; **not yet answered.** Trivial one-line change in `~/.agent/diagrams/2026-06-02-ai-news-journey.html` if yes.
2. **No automated visual QA ever performed.** No headless browser on this box (`chromium`/`chrome`/`mmdc` all absent; `playwright`/`selenium` Python import but browser-binary availability was being checked when the user interrupted — `~/.cache/ms-playwright` status unknown). All verification was structural + user eyeball. Dense slides worth a human re-check on any future edit: 5 (note-card height), 23 (two portrait pages side-by-side), 24 (knob-grid).
3. **Commit decision (user's standing rule):** `presentations/` and the deck remain untracked/uncommitted. Predecessor handoff records: *"Commit or push only when the user asks."* Not asked this session. Do not `git add presentations/` without explicit go.
4. **Outline ↔ deck drift:** the outline (`presentations/...outline.md`) got Pass-1 copy edits but **not** the Pass-2 visual changes (Obsidian rename, Jina "Clone", the note-card, the payoff). If the deck is ever re-rendered from the outline, these would regress — see "Known follow-ups".

---

## Working-tree state at handoff

- Branch `dev` at `71e9fc4` (HEAD). No `origin/dev`; never pushed.
- Modified, uncommitted, **pre-existing (NOT this session — do not touch):** `jina_clone/briefing/generator.py`, `jina_clone/briefing/live_data.py`, `tests/test_briefing_cli_backend.py`, `tests/test_briefing_generator.py`, `tests/test_live_data.py`.
- Untracked: `presentations/` (outline + old outline), `docs/superpowers/handoffs/2026-05-29-...md`, `docs/superpowers/handoffs/2026-06-02-ai-news-presentation-handoff.md` (predecessor), and this file.
- **Out-of-repo artifacts:** deck `~/.agent/diagrams/2026-06-02-ai-news-journey.html` (6.3 MB). Backups: `/tmp/deck-backup.html` (pre-Pass-1), `/tmp/deck-backup-v2.html` (pre-Pass-2), `/tmp/deck-backup-v3.html` (pre slide-6-blank-fix). Edit scripts: `/tmp/deck_update.py`, `/tmp/deck_v3.py`. Briefing PNGs: `/tmp/brief-opt-{1,2}.png` (ephemeral — re-render via `pdftoppm -png -r 150 briefings/2026-06-02-morning.pdf` then `convert -resize 1000x`).
- **Reference deck (different skill, not mine):** `~/.agent/diagrams/2026-06-02-ai-news-journey-v2.html` (1.3 MB) — source of the payoff layout + animation concepts borrowed in Pass 2.

---

## Live state

| Item | Value |
|---|---|
| Local HTTP server | `python3 -m http.server 8777 --bind 0.0.0.0`, cwd `~/.agent/diagrams/`, **running in background** (task `bj3m0g57u`) |
| Deck URL (user's LAN) | `http://192.168.0.89:8777/2026-06-02-ai-news-journey.html` |
| User access | SSH'd into `fox`; views deck over LAN IP. Hard-refresh (Cmd/Ctrl-Shift-R) needed after edits — server serves fresh bytes but browser caches. |

---

## How to resume

1. `git status` — confirm tree matches snapshot above (the 5 modified `jina_clone`/`tests` files are pre-existing, NOT this session's; leave them).
2. Confirm the deck still serves: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8777/2026-06-02-ai-news-journey.html` (expect 200). If the background server died, restart: `cd ~/.agent/diagrams && python3 -m http.server 8777 --bind 0.0.0.0 &`.
3. For any deck edit: **do not Edit the 6.3 MB HTML directly** (base64 lines blow up context). Use a Python string-replace script with a single-match assertion (pattern in `/tmp/deck_v3.py`); back up first (`cp ... /tmp/deck-backup-vN.html`). To inspect markup, dump a base64-truncated copy: `python3 -c "import re;s=open('...').read();open('/tmp/t.html','w').write(re.sub(r'(base64,)[A-Za-z0-9+/=]+',r'\1__B64__',s))"`.
4. If the pending decision (item 1) is answered "yes": replace `<div class="k">Cover · the Jina scraper</div>` → `...the Jina Scraper Clone`.
5. **Do not commit `presentations/` or the deck until the user explicitly says so.**

---

## Known follow-ups (non-blocking)

- The outline and deck have drifted (see "What is NOT done" #4). If a future ask is "re-render the deck," reconcile the outline first (Obsidian Vault, Jina "Clone", note-card intent, real payoff pages) or the in-place deck edits will be lost. The deck is currently the source of truth, not the outline.
- `briefings/2026-06-02-evening.pdf` did not exist at handoff time (only morning); payoff uses the morning edition, captioned "2 June 2026 morning edition."
