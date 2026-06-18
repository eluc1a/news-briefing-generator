# The Morning Fox — Web Mirror + Digest Button — Completion

**Branch:** `dev` (ahead of `origin/dev` by 33 commits; never pushed this session)
**Date:** 2026-06-15
**Plan:** `docs/superpowers/plans/2026-06-15-themorningfox-web-mirror-and-digest-button.md`
**Spec:** `docs/superpowers/specs/2026-06-15-themorningfox-web-launch-design.md`

---

## TL;DR

All five plan tasks are implemented and deployed. Code (Tasks 1–3) is committed on `dev`
(`5d8dbd9`, `3b3a22a`, `d7f1b1c`); full suite **173 passed**. Ops (Tasks 4–5) are live on `fox`:
nginx vhost for `themorningfox.com` enabled, Let's Encrypt cert issued (expires 2026-09-13),
HTTP basic auth enforced (`401` confirmed without creds, `200` confirmed with real creds), and
two `briefing publish-web` cron lines added at 8:45/20:45 alongside the untouched 8:10/20:10
print lines.

**The one open item is verification, not work:** the live web mirror has not yet shown a *fresh*
edition. The JSON-drop render wrapper only began dropping edition JSON as of this afternoon's
deploy (~17:47 ET), which is *after* today's 8:10 morning print run — so no print run has yet
exercised the wrapper end-to-end. `editions/index.json` currently lists only `2026-06-07-morning`
(a leftover from earlier web spec/plan testing). User chose to **wait for tonight's 20:10 evening
print run** to prove the mirror automatically (20:10 `briefing run` drops JSON → 20:45
`publish-web` rebuilds index → site "latest" = tonight's evening edition). Verbatim: "i'll wait."

---

## What was done this session

Executed the plan via subagent-driven development (per-task spec review; one batched
code-quality review at the end, per CLAUDE.md right-sizing).

**Code (committed on `dev`):**
- `5d8dbd9` — `make_render_and_save_json` in `jina_clone/briefing/web.py` + 3 tests in
  `tests/test_briefing_web.py`. Drops the edition JSON only; deliberately does NOT call
  `rebuild_index` (the decoupling the spec required). Write is log-and-swallowed; render
  exceptions still propagate.
- `3b3a22a` — `jina_clone/cli.py`: wrapped `_briefing_run`'s `render=` dep with
  `make_render_and_save_json(...)`; added synchronous `_briefing_publish_web` +
  `briefing publish-web` subparser + dispatch (no `asyncio.run`).
- `d7f1b1c` — `jina_clone/briefing/feed.py`: `.broadsheet-link` CSS + masthead `<a>` →
  `https://themorningfox.com`; new `tests/test_feed_page.py`. Backfilled 12 existing
  `feeds/ai-digest/*.html` pages (runtime artifacts, intentionally NOT committed).
- Batched code-quality review over all three: **✅ approved, no issues; 173 passed in 4.48s.**

**Ops on `fox` (not in git — state lives on the box):**
- nginx vhost `/etc/nginx/sites-available/themorningfox.com` written + symlinked into
  `sites-enabled`. Listens `8080` (plain) + `443 ssl`; basic auth via
  `/etc/nginx/.htpasswd-morningfox`; `location /editions/` aliases
  `/home/elucia/dev/jina-clone/briefings/`. (nginx already owns :443/:8080 server-wide,
  SNI-multiplexed with other vhosts; Apache owns :80 — hence webroot certbot.)
- Cert issued: `certbot certonly --webroot -w /var/www/html -d themorningfox.com -d www.themorningfox.com`
  → `/etc/letsencrypt/live/themorningfox.com/` (notAfter Sep 13 2026, auto-renew scheduled).
- `nginx -t` clean, reloaded. Verified: `401` (no creds), `401` (wrong creds), cert CN correct.
  User ran authenticated curl → `200` + valid `editions/index.json`.
- Two cron lines appended (host crontab, user `elucia`); print lines untouched.

---

## What is NOT done

1. **Live mirror E2E (verification only — code/ops are done).** No print run has exercised the
   JSON-drop wrapper yet. Resolution: tonight's 20:10 evening `briefing run` will drop
   `2026-06-15-evening.json`; the 20:45 `publish-web` cron rebuilds the index. Confirm afterward
   that `editions/index.json`'s top entry is `2026-06-15` / `evening`. (To force early instead of
   waiting: `briefing run --edition=evening && briefing publish-web` — **prints a paper + spends
   LLM quota**; user declined for now.)
2. **Digest button visual check (Task 5 Step 5).** Open `https://feed.themorningfox.com/ai-digest/`
   → newest page → confirm the "Read the full broadsheet" button shows and links to
   `https://themorningfox.com`. Backfill ran (12 pages), so the markup is present on disk;
   only the human eyeball check remains.

---

## Working-tree state at handoff

- Branch `dev` at HEAD `d7f1b1c`; **ahead of `origin/dev` by 33** (not pushed this session;
  user has not asked to push).
- This session's three commits sit on top of the pre-existing plan/spec doc commits
  (`c1a5546`, `f1e7af7`).
- Modified, uncommitted (pre-existing, NOT from this work — left untouched):
  `.env.example`, `CLAUDE.md`.
- Untracked (pre-existing, NOT from this work): `assets/`,
  `briefings/2026-06-08-test-morning.json`, three prior handoff docs under
  `docs/superpowers/handoffs/`.
- This handoff doc is a new untracked file.
- Regenerated `feeds/ai-digest/*.html` (12 pages) are untracked by design — do NOT `git add`.

---

## Live state

| Thing | Value |
|---|---|
| Web mirror URL | `https://themorningfox.com` (basic auth, user `elucia`) |
| Editions alias | `https://themorningfox.com/editions/` → `briefings/` |
| Digest/feed host (separate, pre-existing) | `https://feed.themorningfox.com/ai-digest/` |
| nginx vhost | `/etc/nginx/sites-available/themorningfox.com` (enabled) |
| Cert | `/etc/letsencrypt/live/themorningfox.com/` (exp 2026-09-13, auto-renew) |
| htpasswd | `/etc/nginx/.htpasswd-morningfox` (user `elucia`) |
| Print cron | `briefing run` morning 8:10 / evening 20:10 ET |
| Publish cron | `briefing publish-web` 8:45 / 20:45 ET |

---

## How to resume

1. **Sanity check:** `git status`; `git log --oneline -3` (expect HEAD `d7f1b1c`);
   `crontab -l | grep "briefing"` (expect 4 lines: 8:10/20:10 run, 8:45/20:45 publish-web,
   all with the `cd /home/elucia/dev/jina-clone &&` prefix).
2. **Confirm the mirror went fresh after 20:10:** `tail logs/briefing.log` for tonight's
   evening run; `ls -l briefings/2026-06-15-evening.json` should exist; then
   `./.venv/bin/python -c "import json; print(json.load(open('briefings/index.json'))[0])"`
   — top entry should be `2026-06-15` / `evening`. If the 20:45 cron has not fired yet, run
   `./.venv/bin/python -m jina_clone briefing publish-web` manually.
3. **If the mirror is fresh:** the feature is fully verified — nothing else to do but the
   button eyeball check (item 2 in "What is NOT done").
4. **If `git push` is wanted:** branch is `dev`, 33 ahead of origin. Confirm with user first
   (not requested this session).

---

## Process / gotchas worth carrying

- **Cron typo caught:** the first two attempts at the 8:45 `publish-web` line dropped the
  `cd /home/elucia/dev/jina-clone &&` prefix (would have run from `$HOME`, where `./.venv/`
  doesn't exist, and written `logs/` to the wrong place). Fixed by editing a dumped crontab
  file rather than re-typing the `echo`. Final `crontab -l` verified all 4 lines carry the
  `cd` prefix. If editing this crontab again, dump→edit→reinstall; don't hand-type the line.
- **Why index.json was stale (not a bug):** the JSON-drop wrapper deployed ~17:47, after the
  8:10 morning run, so today's morning print produced a PDF (`2026-06-15-morning.pdf`) but no
  JSON. Older `briefings/*.pdf` go back to April and never had companion JSON. First JSON drop
  is tonight's 20:10 evening run.
- **Decoupling invariant (don't regress):** `make_render_and_save_json` must NOT call
  `rebuild_index` — index rebuild belongs solely to `briefing publish-web`. Asserted in
  `tests/test_briefing_web.py::test_save_json_wrapper_writes_edition_json_only`
  (`not (tmp_path / "index.json").exists()`).
- **Never `git add -A`/`git add .`** in this repo — it sweeps runtime artifacts
  (`feeds/ai-digest/*.html`, `briefings/*.json`). All three commits staged only named files.
