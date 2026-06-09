# The Morning Fox — Website Launch (SP1) Handoff

**Branch:** `dev` (feature commits cut from `17f23d1`, the current `origin/dev`)
**Date:** 2026-06-08
**Plan:** `docs/superpowers/plans/2026-06-05-themorningfox-launch.md`

---

## TL;DR

The code portion (Plan Tasks 1–3) is **complete, reviewed, and committed** on `dev` (4 commits, `6105706`..`8a3fca3`) — purely additive, **zero existing files modified** (verified `A`-only across the range). A **live pipeline E2E ran successfully**: `run_web --edition=morning` printed the real paper (`brother-108`), wrote `briefings/2026-06-07-morning.json` (validates as a `Briefing`), and `briefings/index.json` with that edition as entry `[0]`. The static page was visually verified by the user against the real edition over a local server.

**Two things are in-flight, not finished:** (1) an **uncommitted** `web/style.css` tweak — the markets row was changed from wrapping flex (5+1 orphan) to an even grid (3 cols wide / 2 cols narrow) per user feedback; the user has not yet confirmed the visual after hard-refresh. (2) **Plan Task 4 (ops on fox: nginx + basic-auth + TLS + cron switch) has not been started** — it needs the user (sudo/DNS/crontab).

User constraint still in force this session: **"no merges or pushes yet."** Also the plan's hard constraint: **"Do not modify any existing code. New files only."**

---

## What was done this session

- **Task 1** — `jina_clone/briefing/web.py` (JSON + newest-first `index.json` writer + `make_render_and_publish` wrapper that swallows web-publish failures so the paper is never blocked) + `tests/test_briefing_web.py` (5 tests). Commit `6105706`. Passed spec + code-quality review.
- **Task 2** — `jina_clone/briefing/run_web.py` (publish-aware entry point reusing `run_briefing` verbatim, injecting the wrapper at the `render=` seam). All 24 `run_briefing` kwargs verified against the real signature in `jina_clone/jobs/briefing.py`. Commit `6d11317`. Passed spec + code-quality review.
- **Task 3** — `web/index.html`, `web/app.js`, `web/style.css`, `web/fonts/BodoniModa-{Regular,Medium}.ttf` (font copies, byte-identical to `jina_clone/briefing/static/fonts/`). Commit `8e5c3b6`. Code-quality review raised two items, fixed in commit `8a3fca3` (explicit `response.ok` checks in `app.js::main`; removed a no-op `Object.assign` wrapper in `showStatus`).
- **Live E2E (Plan Task 2 Step 5)** — `./.venv/bin/python -m jina_clone.briefing.run_web --edition=morning` ran clean: 152 articles fetched, weather+markets pulled, 6 `claude -p` calls, rendered `briefings/2026-06-07-morning.pdf` (38972 bytes), printed `brother-108`, logged `news_summaries` row `40841`. Web outputs confirmed: JSON validates as `Briefing` (title "The Morning Fox"), `index.json` has today-morning as `[0]`.
- **Visual check (Plan Task 3 Step 5)** — served `web/` via `python -m http.server 8099`, with `web/editions` symlinked to `../briefings` to mirror the production nginx `/editions/` alias. All assets + the real edition return 200. User reviewed in browser.
- **Markets layout fix (in response to user feedback "markets row has 5 tickers on the first row and 1 on the second. they should be evenly spaced")** — edited `web/style.css` lines 34–36: markets section is now `display: grid; grid-template-columns: repeat(2, 1fr)` with a `@media (min-width: 620px)` bump to `repeat(3, 1fr)`, and `.market` got `justify-content: center`. **This edit is uncommitted.**

---

## What is NOT done

1. **Confirm the markets tweak visually.** User must hard-refresh (CSS is cached) and confirm the row now shows an even 3+3 (wide) / 2+2+2 (narrow). If approved, **commit `web/style.css`** (message e.g. `style(web): even markets grid`, with the `Co-Authored-By: Claude Opus 4.8 (1M context)` trailer). If not approved, iterate before committing.
2. **Plan Task 4 — ops on fox (NOT STARTED).** Needs the user for privileged steps. In order: (a) DNS A record `themorningfox.com` → fox public IP + `www`; (b) `/etc/nginx/.htpasswd-morningfox` via `openssl passwd -apr1` (user picks username/password); (c) `/etc/nginx/sites-available/themorningfox.com` HTTP server block with `root /home/elucia/dev/jina-clone/web` and `location /editions/ { alias /home/elucia/dev/jina-clone/briefings/; ... }`; (d) enable symlink + `nginx -t` + reload; (e) `certbot --nginx -d themorningfox.com -d www.themorningfox.com` (choose HTTP→HTTPS redirect); (f) verify `www-data` can read `web/` and `briefings/` (may need `chmod o+x` on the home-dir path); (g) switch host crontab's two briefing lines from `python -m jina_clone briefing run` to `python -m jina_clone.briefing.run_web`. Exact commands are in the plan, Task 4.
3. **No merge / no push** — the user explicitly deferred both this session.

---

## Working-tree state at handoff

- Branch `dev` at HEAD `8a3fca3ca012ef1a38e606875b51fb5ab072fa78`.
- **Ahead of `origin/dev` by 4 commits** (`origin/dev` = `17f23d1`; branch's feature commits never pushed).
- **Modified, uncommitted:** `web/style.css` (markets grid tweak, +3 −2).
- **Untracked (intentional, do NOT blindly `git add .`):**
  - `briefings/2026-06-07-morning.json`, `briefings/index.json` — live-E2E artifacts. Plan leaves `briefings/*.json` untracked (not gitignored) by design; they are served at runtime, not committed.
  - `web/editions` — **temporary symlink → `../briefings`** created only for the local visual check. **MUST be removed before any commit and must never be committed** (`rm web/editions`). In production nginx provides `/editions/` via `alias`, so the symlink is local-only.

---

## Live / runtime state

| Item | Value |
|---|---|
| Local preview server | `python -m http.server 8099` in `web/`, **still running**, pid `1404567`, bound `0.0.0.0:8099` |
| Preview URLs | `http://localhost:8099/` (on fox) · `http://192.168.0.89:8099/` (LAN) |
| Print job from E2E | `brother-108` |
| DB row from E2E | `news_summaries` id `40841` |
| Edition served | `briefings/2026-06-07-morning.{json,pdf}` |

Note: curling the loopback from a sandboxed Bash call intermittently returns `000`; pass `dangerouslyDisableSandbox: true` (or just trust the on-disk file — `http.server` reads per-request, no caching).

---

## How to resume

1. **Sanity check first (no edits):** `cd /home/elucia/dev/jina-clone && git status && git log --oneline 17f23d1..HEAD`. Confirm HEAD is `8a3fca3`, `web/style.css` modified, `web/editions` symlink + two `briefings/*.json` untracked.
2. Check whether the preview server (pid `1404567`, `:8099`) is still up: `ss -ltnp | grep 8099`. If resuming the visual review, reuse it; otherwise stop it: `kill 1404567`.
3. **Get the user's verdict on the markets grid** (item 1 above). On approval: `rm web/editions` (kill the temp symlink) → `git add web/style.css` → commit with the Co-Authored-By trailer. **Do not** `git add .` (would capture the symlink and E2E JSON).
4. When the user is ready, walk Task 4 (ops). Hand them each privileged command to run via the `! <cmd>` prompt prefix so the output lands in-session.
5. **Do not push or merge** unless the user lifts the "no merges or pushes yet" hold.

---

## Out-of-scope noticed (NOT touched)

- Code-quality review flagged that `app.js`'s `Callable`-style robustness is fine but the page relies on exceptions-as-control-flow for non-200s — addressed by the `response.ok` checks in `8a3fca3`; no further action.
- SP2/SP3 items (source click-through, section reordering, edition toggle/archive) are explicitly out of scope per the plan.
