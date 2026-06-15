# The Morning Fox — Web Launch (decoupled mirror) + digest button

**Date:** 2026-06-15
**Branch:** `dev`
**Predecessor:** `docs/superpowers/specs/2026-06-05-themorningfox-launch.md`
(SP1 built the `web/` frontend + `run_web` pipeline; this supersedes its
Task 4 ops with a decoupled design and adds the digest button.)

---

## Goal

1. Make `https://themorningfox.com` (the broadsheet static site in `web/`)
   live on fox, behind HTTP basic auth, auto-updating twice daily.
2. The website must show the **exact edition that was printed** — a
   mirror of the paper, not an independent generation.
3. Web publishing must be a **separate, downstream step** from the print
   briefing. The existing print cron lines must NOT be modified, and a
   web failure must never affect printing.
4. Add a button on the Slack AI/ML **digest** HTML pages linking to
   `https://themorningfox.com`.

## Constraints / decisions (user-confirmed)

- **Mirror the paper**, not independent generation. (No second LLM pass.)
- **Basic auth** on the whole site (page + `/editions/`), so local
  weather/markets stay private. The digest button therefore leads to a
  login prompt — accepted.
- **Do not touch the existing print cron lines** (`briefing run` at
  08:10 / 20:10). The only change to the print path is an additive,
  failure-swallowing JSON write.
- Keep web-publish logic out of the print job; it is its own cron step.

---

## Architecture & data flow

nginx serves `briefings/` directly via the `/editions/` alias, so an
edition JSON is *reachable* the moment it is written, but only becomes the
site's *listed/latest* edition once `index.json` is rebuilt. That gives a
clean split:

```
print cron (08:10) → `briefing run` → prints paper
                                    └ (NEW) drops briefings/<date>-<edition>.json
                                                                  │
publish cron (08:45) → `briefing publish-web` → rebuild_index() → index.json
                                                                  │
                                              site lists + shows the edition
```

1. **Print run persists its edition (mirror source).** `briefing run` is
   changed minimally: its `render` callable is wrapped so that, after the
   PDF is rendered, it also writes `briefings/<date>-<edition>.json` — the
   exact `Briefing` that printed. The write is wrapped in try/except and
   logged-and-swallowed: it can never block or fail the print. The cron
   line is unchanged.

2. **Separate downstream publish step.** A new `briefing publish-web`
   subcommand does exactly one thing: `rebuild_index(briefings_dir)` —
   scan `briefings/` and regenerate the newest-first `index.json` the page
   reads. No LLM, no DB, no print. Runs on its own new cron lines ~35 min
   after the print runs.

**Rejected alternatives:** switching the print cron to `run_web` (couples
print + publish in one line); an independent second generation (would not
mirror the paper).

---

## Code changes (all in existing modules; additive)

- **`jina_clone/briefing/web.py`** — add a thin wrapper
  `make_render_and_save_json(render_pdf, *, briefings_dir, edition)` that
  returns a callable matching `run_briefing`'s `render` signature
  `(briefing, pdf_path, *, generated_at, iso_date)`. It calls the real
  `render_pdf`, then `write_edition_json(...)` in a swallowed try/except.
  (Distinct from the existing `make_render_and_publish`, which also
  rebuilds the index — we deliberately keep index-rebuild OUT of the print
  job.) `write_edition_json` and `rebuild_index` already exist and are
  reused unchanged.

- **`jina_clone/cli.py`** —
  - In the `briefing run` path, wrap the render dependency with
    `make_render_and_save_json(...)` so every print run drops the edition
    JSON. No other behavior changes.
  - Add a `briefing publish-web` subcommand that loads `Settings`, calls
    `rebuild_index(settings.briefings_dir)`, and logs the result.

- **`jina_clone/briefing/feed.py`** — add the button to `_PAGE_TEMPLATE`
  (in the masthead/header), e.g. a styled `<a>` reading "Read the full
  broadsheet → themorningfox.com" → `https://themorningfox.com`. The
  target URL is a literal constant (the digest and broadsheet are separate
  products on separate hosts). After the change, rebuild the digest pages
  + `feed.xml` so existing pages get the button.

No change to `run_briefing`, `renderer.py`, `assemble_briefing`,
`run_web.py`, or the print cron lines.

---

## Ops on fox

DNS and basic auth are already done:
- **DNS (done):** grey-cloud CNAMEs `themorningfox.com` and `www` →
  `elucia.tplinkdns.com`; both resolve to `68.84.4.134`.
- **Basic auth (done):** `/etc/nginx/.htpasswd-morningfox`, one user
  `elucia`.

Remaining (done by the assistant via passwordless sudo):
- **nginx vhost** `/etc/nginx/sites-available/themorningfox.com`, mirroring
  the `feed.themorningfox.com` vhost (`listen 8080` + `listen 443 ssl`),
  but: `root /home/elucia/dev/jina-clone/web`; `autoindex off`;
  `location /editions/ { alias /home/elucia/dev/jina-clone/briefings/; }`;
  `auth_basic` + `auth_basic_user_file /etc/nginx/.htpasswd-morningfox` at
  the server level (covers page + `/editions/`). Symlink into
  `sites-enabled/`, `nginx -t`, reload.
- **TLS:** `certbot certonly --webroot -w /var/www/html -d
  themorningfox.com -d www.themorningfox.com` (webroot method — port 80 on
  fox is Apache, same as the feed cert). Wire cert paths into the vhost,
  reload.
- **Permissions:** confirm `www-data` can read `web/` and `briefings/`
  (`web/` is world-readable; `/home/elucia` has `o+x`).

---

## Cron (host crontab, user elucia)

Add **two new lines** (do NOT modify the existing two print lines):

```
45 8  * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone briefing publish-web >> logs/briefing.log 2>&1
45 20 * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone briefing publish-web >> logs/briefing.log 2>&1
```

35-min offset after the 08:10 / 20:10 print runs so the edition JSON is on
disk before the index rebuild. `publish-web` is idempotent (rebuild-by-
scan), so a stale/missed run self-heals on the next firing.

---

## Testing & verification

- **Unit:** `make_render_and_save_json` writes the edition JSON and
  returns the render result; a raising `render_pdf` still propagates while
  a raising `write_edition_json` is swallowed. `briefing publish-web`
  rebuilds `index.json` from on-disk files. (Add to
  `tests/test_briefing_web.py`.)
- **Live E2E (mirror proof):** run `briefing run` once → confirm both the
  PDF and `briefings/<date>-<edition>.json` are written, and the JSON
  matches the printed edition. Then `briefing publish-web` → confirm
  `index.json` lists it first.
- **Site:** curl the page + `/editions/index.json` over HTTPS with the
  `elucia` basic-auth creds → 200 with valid cert; without creds → 401.
- **Button:** rebuild digest pages → confirm the button renders and points
  at `https://themorningfox.com`.

---

## Out of scope

- No merge/push decision (separate, per branch state).
- No changes to the digest feed delivery, the print pipeline content, or
  `run_web.py`.
- Edition archive/toggle UI on the site (SP2/SP3).
