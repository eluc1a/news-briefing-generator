# AI Digest `/ai` Link + Web Styling Pass — Handoff

**Branch:** `dev` (HEAD `518d4d5`; this session's work is all **uncommitted** on top)
**Date:** 2026-06-16
**Predecessor:** `docs/superpowers/handoffs/2026-06-16-source-clickthrough-completion.md`

---

## TL;DR

A batch of small UI/styling changes plus a new `themorningfox.com/ai` → latest-AI-digest
redirect. **Everything is implemented, live on disk, and verified working — but nothing is
committed.** The Python change (`feed.py` + tests) and web assets are uncommitted on `dev`;
the nginx changes are live system config (backed up, reloaded) and not version-controlled.

`dev` is **42 commits ahead of `origin/dev` and has never been pushed**. The predecessor's
user constraint **"Keep dev as-is"** (no push, no merge to `main` without explicit go) is
still in force — this session did not push. The only pending decision is whether to commit
this session's code changes; the user moved past two commit offers without answering, so do
not assume yes.

All structural verification passed (16 feed tests; `/ai` → 302 → `latest.html` → 200 over
HTTPS; `node --check web/app.js` clean). The one thing not done is a **human browser eyeball
with a hard-refresh** — no headless browser exists on `fox`.

---

## What was done this session

All edits below are uncommitted. Files under `feeds/ai-digest/` are gitignored runtime
output (live on disk, served by nginx, not in `git status`).

**1. Source-link styling + headline font (main site — `web/app.js`, `web/style.css`)**
- Removed the persistent underline on `.src-link` (now `border-bottom: none`; underline only
  on `:hover`).
- Removed the outlet **credit text** that used to follow single-source headlines (dropped the
  `.src-credit` span in `linkifyHeadline` and the CSS rule).
- Briefs no longer get a trailing `— <outlet> ↗`; instead the **brief topic itself** is the
  link (`renderBriefs` now calls `linkifyHeadline(topic, br.sources)`). Removed the now-unused
  `trailingAffordance` helper.
- `.lead-headline` and `blockquote` (pull-quote) font: Bodoni Moda → **Libre Baskerville**
  (headline weight 700; pull-quote italic). Masthead wordmark intentionally **stays Bodoni**
  (brand) per user.
- Bundled fonts: `web/fonts/LibreBaskerville-{Regular,Bold,Italic}.woff2` (fetched from
  gstatic; jsDelivr/GitHub raw both failed — see Process notes).

**2. "AI & Technology" heading → `/ai` link (`web/app.js`, `web/style.css`)**
- In `renderPanels`, the panel whose `section === "AI & Technology"` renders its `<h3>` text
  as `<a href="/ai">`. Other three panel headings stay plain text. Added `.section-link`
  (inherit color, no underline, underline on hover).

**3. nginx — `/ai` redirect (LIVE system config, NOT in repo)**
- `/etc/nginx/sites-available/themorningfox.com`: added to **both** the `:8080` and `:443`
  server blocks:
  `location = /ai  { return 302 https://feed.themorningfox.com/ai-digest/latest.html; }`
  and the same for `location = /ai/`.
- `/etc/nginx/sites-available/feed.themorningfox.com`: added
  `location = /ai-digest/latest.html { add_header Cache-Control "no-store" always; try_files $uri =404; }`
  to both blocks so the "latest" endpoint never serves stale.
- Backups written: `themorningfox.com.bak-20260616-ai`, `feed.themorningfox.com.bak-20260616-ai`.
- `sudo nginx -t` clean; `sudo systemctl reload nginx` done.

**4. Self-updating "latest" pointer (`jina_clone/briefing/feed.py` + tests)**
- Added `update_latest(out_dir)`: scans `{date}-{edition}.json` records (same ordering as
  `rebuild_feed` — afternoon outranks morning), atomically points `latest.html` (a symlink) at
  the newest page. Wired into `_publish_record` after `rebuild_feed`, so every future digest
  refreshes it automatically.
- Created the live symlink now: `feeds/ai-digest/latest.html -> 2026-06-15-afternoon.html`.
- +3 tests in `tests/test_briefing_feed.py` (points-at-newest, newest+swap idempotency +
  no temp-file residue, empty-dir no-op).

**5. AI digest page styling (`jina_clone/briefing/feed.py` `_PAGE_TEMPLATE`)**
- `.broadsheet-link` ("READ THE FULL BROADSHEET → themorningfox.com"): font Bodoni → **Libre
  Baskerville** (added `@font-face`); added `LibreBaskerville-Regular.woff2` to `_FONT_FILES`
  and bundled it at `jina_clone/briefing/static/fonts/LibreBaskerville-Regular.woff2` so
  `_ensure_fonts` copies it next to every page.
- Same block: **centered** (`display: block; width: fit-content; margin: .8rem auto 0`) and
  restyled from the aggressive **black box** to a subtle parchment chip
  (`background: #efe9dd; color: #1a1a1a; border: 1px solid #b5b0a4`; hover darkens fill +
  border to ink, replacing the old red-flash hover).
- **Re-rendered all 12 existing `feeds/ai-digest/*.html`** from their JSON records so the
  font/centering/chip changes are live now; copied the woff2 into `feeds/ai-digest/fonts/`.

**Verification performed**
- `./.venv/bin/pytest tests/test_briefing_feed.py -q` → **16 passed**.
- `curl` (with `--resolve` to 127.0.0.1): `https://themorningfox.com/ai` → `302` →
  `https://feed.themorningfox.com/ai-digest/latest.html` → `200`; `latest.html` body
  byte-identical to `2026-06-15-afternoon.html`; `Cache-Control: no-store` present;
  `fonts/LibreBaskerville-Regular.woff2` → `200 font/woff2 20108 bytes`.
- Served `latest.html` confirmed to contain the Libre Baskerville `@font-face` + the new
  centered/parchment `.broadsheet-link` rule.
- `node --check web/app.js` clean; structural DOM-shim render confirmed only the AI panel
  heading links to `/ai`, 27 source links present, 0 `src-credit` nodes.

---

## What is NOT done

1. **Nothing committed.** All of this session's code (`web/app.js`, `web/style.css`,
   `feed.py`, `tests/test_briefing_feed.py`) and the new font files are uncommitted on `dev`.
   The commit decision is **the user's** — they passed over two commit offers without a yes.
   Ask before committing.
2. **nginx changes are not in version control.** They are live system config under
   `/etc/nginx/sites-available/` (backed up as `*.bak-20260616-ai`). No repo artifact records
   them — note this if the box is ever rebuilt.
3. **Human browser eyeball.** No Chromium/Playwright on `fox`. Open themorningfox.com and the
   AI digest page (`/ai`) and **hard-refresh** to bust cached CSS/JS/fonts; confirm: headlines
   are Libre Baskerville links with no underline/credit, "AI & Technology" heading links to
   `/ai`, and the digest's broadsheet button is centered + subtle parchment (not black).
4. **Expected overwrite (not a bug):** the test edition `briefings/2026-06-16-morning.json`
   (+`.pdf`) shares a filename with today's 08:10 ET morning cron output and **will be cleanly
   overwritten** by the real run (same owner `elucia`, `write_text` overwrite). User said of
   it: **"That's fine the way it is."** The real run regenerates from `dev` code, so it carries
   sources and renders with this session's frontend.

---

## Working-tree state at handoff

- Branch `dev` at HEAD `518d4d5` (`feat(web): render click-through source links...`).
- **42 commits ahead of `origin/dev`; branch never pushed.**
- Modified, uncommitted (7): `.env.example`, `CLAUDE.md`, `briefings/index.json`,
  `jina_clone/briefing/feed.py`, `tests/test_briefing_feed.py`, `web/app.js`, `web/style.css`.
  - `git diff --stat` (uncommitted): 7 files, +246 / −71. **This session's source changes are
    `feed.py` (+67/−), `tests/test_briefing_feed.py` (+33), `web/app.js`, `web/style.css`.**
    `.env.example` / `CLAUDE.md` / `briefings/index.json` are **pre-existing** modifications
    not from this session.
- Untracked relevant to this session:
  - `web/fonts/LibreBaskerville-Regular.woff2`, `-Bold.woff2`, `-Italic.woff2`
  - `jina_clone/briefing/static/fonts/LibreBaskerville-Regular.woff2`
  - `briefings/2026-06-16-morning.json` (the test edition; see NOT-done #4)
- Gitignored runtime, live on disk (not in `git status`): `feeds/ai-digest/latest.html`
  (symlink), `feeds/ai-digest/fonts/LibreBaskerville-Regular.woff2`, the 12 re-rendered
  `feeds/ai-digest/*.html`.
- **Deployed = local:** nginx serves the checkout (`web/`) and `feeds/` directly; editing a
  file IS deploying it (static assets need a browser hard-refresh; nginx config needed a
  reload, already done).

---

## How to resume

1. **Sanity check:** `git status`; `git log --oneline -1` (expect `518d4d5`);
   `./.venv/bin/pytest tests/test_briefing_feed.py -q` (expect `16 passed`).
2. Confirm the redirect still serves:
   `curl -sL -o /dev/null -w "%{url_effective} %{http_code}\n" --resolve themorningfox.com:443:127.0.0.1 --resolve feed.themorningfox.com:443:127.0.0.1 https://themorningfox.com/ai`
   (expect `.../ai-digest/latest.html 200`).
3. Do NOT-done #3 (human hard-refresh eyeball) on both pages.
4. **Decide commit with the user before committing.** If yes, stage **only** this session's
   files explicitly — `feed.py`, `tests/test_briefing_feed.py`, `web/app.js`, `web/style.css`,
   and the `web/fonts/` + `static/fonts/` woff2s. **Never `git add -A`** (repo has swept
   runtime artifacts into a feature commit before — see CLAUDE.md Gotchas). Leave
   `.env.example` / `CLAUDE.md` / `briefings/*` out unless the user asks.
5. **Do not push `dev` or merge to `main`** without explicit instruction — "Keep dev as-is" is
   still in force.

---

## Process notes

- User constraints, verbatim: **"That's fine the way it is."** (re: the `/ai` redirect URL
  landing on `feed.themorningfox.com` rather than masking under `themorningfox.com`) and
  **"Keep dev as-is"** (carried from predecessor; no push/merge).
- Font fetch gotcha: GitHub raw and jsDelivr both failed for the google/fonts repo (HTML
  redirect pages / 50 MB repo-size block). The working source was the Google Fonts CSS2 API
  with a desktop UA → gstatic `.woff2` URLs (one CSS request per weight/style to disambiguate).
- The `/ai` redirect target is intentionally stable (`latest.html`); the symlink underneath is
  what moves. `latest.html` carries `Cache-Control: no-store` so "latest" is never cached stale.
- Right-sizing: every change this session was low-ceremony (CSS/JS tweaks + ~15 LOC + one new
  function + 3 tests), worked directly in the main session per CLAUDE.md — no spec/plan/subagents.

---

## Useful commands

```bash
# Re-render all AI digest pages from their JSON (after a feed.py template edit):
cd /home/elucia/dev/jina-clone && ./.venv/bin/python - <<'PY'
import json
from pathlib import Path
from jina_clone.briefing import feed
out = Path("feeds/ai-digest")
feed._ensure_fonts(out); feed._ensure_logo(out)
for p in sorted(out.glob("*.json")):
    if feed._NAME_RE.match(p.name):
        rec = json.loads(p.read_text())
        (out / f"{rec['date']}-{rec['edition']}.html").write_text(feed.render_page_html(rec))
feed.update_latest(out)
PY

# Refresh just the latest.html pointer:
./.venv/bin/python -c "from jina_clone.briefing.feed import update_latest; print(update_latest('feeds/ai-digest'))"

# nginx (changes are live; to re-validate / reload):
sudo nginx -t && sudo systemctl reload nginx
```
