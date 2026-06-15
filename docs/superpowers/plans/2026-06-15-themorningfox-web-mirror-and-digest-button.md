# The Morning Fox — Web Mirror + Digest Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `https://themorningfox.com` live behind basic auth, mirroring each printed edition via a decoupled downstream publish step, and add a button on the AI/ML digest pages linking to it.

**Architecture:** The print run (`briefing run`) drops the exact `Briefing` it printed to `briefings/<date>-<edition>.json` via a failure-swallowing render wrapper (print is never blocked, cron line unchanged). A separate `briefing publish-web` subcommand rebuilds `index.json` from those files and runs on its own cron lines ~35 min later. nginx serves `web/` (static site) + `briefings/` (via `/editions/` alias) behind HTTP basic auth with a Let's Encrypt cert.

**Tech Stack:** Python 3 / asyncpg / argparse CLI, WeasyPrint (unchanged), nginx + certbot (webroot), host cron.

**Spec:** `docs/superpowers/specs/2026-06-15-themorningfox-web-launch-design.md`

---

## File structure

- `jina_clone/briefing/web.py` — **modify**: add `make_render_and_save_json` (JSON-only render wrapper, no index rebuild). Reuses existing `write_edition_json` / `rebuild_index`.
- `jina_clone/cli.py` — **modify**: wrap the `briefing run` render dep; add `publish-web` subcommand + `_briefing_publish_web`.
- `jina_clone/briefing/feed.py` — **modify**: add the broadsheet button to `_PAGE_TEMPLATE`.
- `tests/test_briefing_web.py` — **modify**: tests for the JSON-only wrapper.
- `tests/test_feed_page.py` — **create**: test the button renders.
- nginx vhost / cron — **ops**, not committed code.

---

## Task 1: JSON-only render wrapper in web.py

**Files:**
- Modify: `jina_clone/briefing/web.py` (add function after `make_render_and_publish`, ~line 87)
- Test: `tests/test_briefing_web.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_briefing_web.py`:

```python
from jina_clone.briefing.web import make_render_and_save_json


def test_save_json_wrapper_writes_edition_json_only(tmp_path):
    b = _briefing()
    calls = {}

    def fake_render(briefing, pdf_path, *, generated_at, iso_date):
        calls["pdf_path"] = pdf_path
        return pdf_path

    wrapper = make_render_and_save_json(fake_render, briefings_dir=tmp_path, edition="morning")
    pdf = tmp_path / "2026-06-05-morning.pdf"
    result = wrapper(b, pdf, generated_at="08:10 ET", iso_date="2026-06-05")

    assert result == pdf
    assert calls["pdf_path"] == pdf
    # Edition JSON IS written; index.json is NOT (that is the publish step's job).
    assert (tmp_path / "2026-06-05-morning.json").exists()
    assert not (tmp_path / "index.json").exists()


def test_save_json_wrapper_swallows_write_failure(tmp_path):
    b = _briefing()
    sentinel = tmp_path / "out.pdf"

    def fake_render(briefing, pdf_path, *, generated_at, iso_date):
        return sentinel

    bad = tmp_path / "afile"   # a file used as a dir → write_edition_json raises
    bad.write_text("x")
    wrapper = make_render_and_save_json(fake_render, briefings_dir=bad, edition="morning")

    result = wrapper(b, sentinel, generated_at="08:10 ET", iso_date="2026-06-05")
    assert result == sentinel   # must NOT raise; render result still returned


def test_save_json_wrapper_propagates_render_failure(tmp_path):
    b = _briefing()

    def boom(briefing, pdf_path, *, generated_at, iso_date):
        raise RuntimeError("render exploded")

    wrapper = make_render_and_save_json(boom, briefings_dir=tmp_path, edition="morning")
    pdf = tmp_path / "x.pdf"
    try:
        wrapper(b, pdf, generated_at="08:10 ET", iso_date="2026-06-05")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "render exploded" in str(e)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_briefing_web.py -k save_json -v`
Expected: FAIL — `ImportError: cannot import name 'make_render_and_save_json'`

- [ ] **Step 3: Implement the wrapper**

In `jina_clone/briefing/web.py`, after `make_render_and_publish` (ends ~line 87), add:

```python
def make_render_and_save_json(
    render_pdf: Callable[..., Path],
    *,
    briefings_dir: Path,
    edition: str,
) -> Callable[..., Path]:
    """Wrap render_pdf so the print run ALSO drops the edition JSON — the
    exact Briefing that printed — to briefings_dir. Unlike
    make_render_and_publish this does NOT rebuild index.json: making the
    edition the site's "latest" is the separate `briefing publish-web`
    step's job. The JSON write is logged-and-swallowed so it can never
    block the printed paper.

    Returned callable matches run_briefing's render signature:
    (briefing, pdf_path, *, generated_at, iso_date).
    """
    def render_and_save(briefing, pdf_path, *, generated_at, iso_date):
        result = render_pdf(briefing, pdf_path, generated_at=generated_at, iso_date=iso_date)
        try:
            write_edition_json(
                briefing, briefings_dir=briefings_dir, iso_date=iso_date, edition=edition
            )
        except Exception as e:  # noqa: BLE001 — paper is primary; never abort on web write
            log.warning("edition-json write failed (paper unaffected): %s", e)
        return result

    return render_and_save
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_briefing_web.py -v`
Expected: PASS (all, including the three new `save_json` tests)

- [ ] **Step 5: Commit**

```bash
git add jina_clone/briefing/web.py tests/test_briefing_web.py
git commit -m "feat(web): JSON-only render wrapper so print run drops its edition

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire the wrapper into `briefing run` + add `publish-web` subcommand

**Files:**
- Modify: `jina_clone/cli.py` (import ~line 26 area; `_briefing_run` 206-252; subparsers 335-356; dispatch 375-383)

This is CLI glue — verified by the live E2E in Task 5, not a unit test.

- [ ] **Step 1: Add imports**

In `jina_clone/cli.py`, find the existing web import (none yet) and add near the other `jina_clone.briefing` imports:

```python
from jina_clone.briefing.web import make_render_and_save_json, rebuild_index
```

- [ ] **Step 2: Wrap the render dependency in `_briefing_run`**

In `jina_clone/cli.py`, inside `_briefing_run`, replace the single line at ~235:

```python
            render=briefing_renderer.render_pdf,
```

with:

```python
            render=make_render_and_save_json(
                briefing_renderer.render_pdf,
                briefings_dir=settings.briefings_dir,
                edition=edition,
            ),
```

(Nothing else in `_briefing_run` changes.)

- [ ] **Step 3: Add the `publish-web` subcommand handler**

In `jina_clone/cli.py`, after `_briefing_run` (ends ~252), add a new function:

```python
def _briefing_publish_web(settings: Settings) -> None:
    """Downstream web-publish step: rebuild index.json from the edition
    JSONs the print run dropped. No LLM, no print, no DB — safe to run on
    its own cron, decoupled from the print briefing."""
    index_path = rebuild_index(settings.briefings_dir)
    logging.info("rebuilt web index: %s", index_path)
```

- [ ] **Step 4: Register the subparser**

In `jina_clone/cli.py`, after the `run_p` block (ends ~356) and before `slack_p`, add:

```python
    briefing_sub.add_parser(
        "publish-web",
        help="Rebuild briefings/index.json from on-disk editions (downstream web publish).",
    )
```

- [ ] **Step 5: Add dispatch**

In `jina_clone/cli.py`, in the `briefing` action chain (375-383), after the `run` branch add:

```python
        elif args.action == "publish-web":
            _briefing_publish_web(settings)
```

(Note: `_briefing_publish_web` is synchronous — no `asyncio.run`.)

- [ ] **Step 6: Smoke-test the CLI wiring**

Run: `./.venv/bin/python -m jina_clone briefing publish-web`
Expected: exits 0, logs `rebuilt web index: .../briefings/index.json`, and `briefings/index.json` exists and is valid JSON. Confirm:

Run: `./.venv/bin/python -c "import json; print(len(json.load(open('briefings/index.json'))))"`
Expected: prints an integer (count of existing editions; may be small).

- [ ] **Step 7: Run the full suite (no regressions)**

Run: `./.venv/bin/pytest -q`
Expected: PASS (same as before; CLI import resolves).

- [ ] **Step 8: Commit**

```bash
git add jina_clone/cli.py
git commit -m "feat(cli): print run drops edition JSON; add briefing publish-web

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Broadsheet button on the digest page

**Files:**
- Modify: `jina_clone/briefing/feed.py` (`_PAGE_TEMPLATE` style block ~193 and header ~199-203)
- Test: `tests/test_feed_page.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_feed_page.py`:

```python
from jina_clone.briefing.feed import render_page_html


def _record() -> dict:
    # Degraded record renders without a digest fixture; the button is in
    # the masthead, independent of the body.
    return {
        "date": "2026-06-15",
        "edition": "morning",
        "edition_label": "Morning",
        "date_label": "Sun Jun 15",
        "generated_at": "2026-06-15T08:45:00-04:00",
        "degraded": True,
        "digest": None,
        "headlines": [],
    }


def test_page_has_broadsheet_button():
    html = render_page_html(_record())
    assert "https://themorningfox.com" in html
    assert 'class="broadsheet-link"' in html
    # Button lives in the masthead header, before the body content.
    assert html.index("broadsheet-link") < html.index("</header>")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_feed_page.py -v`
Expected: FAIL — `assert "https://themorningfox.com" in html`

- [ ] **Step 3: Add the button CSS**

In `jina_clone/briefing/feed.py`, in `_PAGE_TEMPLATE`'s `<style>` block, immediately after the `.masthead-meta {{ ... }}` rule (ends ~line 170), add (note doubled braces — this is a `.format()` string):

```css
.broadsheet-link {{ display: inline-block; margin-top: .6rem;
        font-family: 'Bodoni Moda', Georgia, serif; font-size: .7rem;
        text-transform: uppercase; letter-spacing: 1.5px;
        text-decoration: none; color: #faf8f3; background: #1a1a1a;
        padding: .34rem .75rem; border-radius: 2px; }}
.broadsheet-link:hover {{ background: #8b2e2e; }}
```

- [ ] **Step 4: Add the button markup in the header**

In `jina_clone/briefing/feed.py`, in `_PAGE_TEMPLATE`, change the header block from:

```html
<header class="masthead">
<h1 class="masthead-title">{masthead}</h1>
<div class="masthead-meta"><span>{edition_label} Edition</span>
<span>{date_label}</span></div>
</header>
```

to (add one line before `</header>`; the URL has no braces so it is safe in `.format()`):

```html
<header class="masthead">
<h1 class="masthead-title">{masthead}</h1>
<div class="masthead-meta"><span>{edition_label} Edition</span>
<span>{date_label}</span></div>
<a class="broadsheet-link" href="https://themorningfox.com">Read the full broadsheet → themorningfox.com</a>
</header>
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_feed_page.py -v`
Expected: PASS

- [ ] **Step 6: Backfill existing digest pages**

New pages get the button automatically; existing pages must be re-rendered from their stored records. Run (reads `FEED_OUTPUT_DIR` from `.env`):

```bash
./.venv/bin/python -c "
import json, glob, os
from dotenv import load_dotenv; load_dotenv()
from jina_clone.config import Settings
from jina_clone.briefing.feed import render_page_html, _NAME_RE
d = str(Settings.from_env().feed_output_dir)
for p in glob.glob(d + '/*.json'):
    name = os.path.basename(p)
    if not _NAME_RE.match(name): continue
    rec = json.load(open(p))
    html_path = p[:-5] + '.html'
    open(html_path, 'w').write(render_page_html(rec))
    print('rebuilt', html_path)
"
```

Expected: prints `rebuilt .../<date>-<edition>.html` for each existing record.

- [ ] **Step 7: Verify a backfilled page contains the button**

Run: `rtk proxy sh -c "grep -l broadsheet-link feeds/ai-digest/*.html | head"`
Expected: lists at least one page.

- [ ] **Step 8: Commit**

```bash
git add jina_clone/briefing/feed.py tests/test_feed_page.py
git commit -m "feat(digest): broadsheet button linking to themorningfox.com

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(Do NOT `git add` the regenerated `feeds/ai-digest/*.html` — runtime artifacts, untracked by design.)

---

## Task 4: Deploy on fox — nginx vhost + basic auth + TLS

Ops, run as the assistant via passwordless sudo (wrap privileged commands as `sudo sh -c '…'` to avoid the RTK rewrite). DNS and `/etc/nginx/.htpasswd-morningfox` (user `elucia`) are already done.

- [ ] **Step 1: Confirm www-data can read the content roots**

```bash
sudo sh -c 'namei -l /home/elucia/dev/jina-clone/web/index.html | tail -6; echo ---; ls -ld /home/elucia/dev/jina-clone/briefings'
```
Expected: every path component has `o+x` (traverse) and `web/`, `briefings/` are `o+r`/`o+x`. If `briefings/` lacks world-traverse, run `sudo sh -c 'chmod o+rx /home/elucia/dev/jina-clone/briefings'`.

- [ ] **Step 2: Write the nginx vhost**

```bash
sudo sh -c 'cat > /etc/nginx/sites-available/themorningfox.com <<"EOF"
server {
    listen 8080;
    server_name themorningfox.com www.themorningfox.com;
    root /home/elucia/dev/jina-clone/web;
    index index.html;
    autoindex off;

    auth_basic "The Morning Fox";
    auth_basic_user_file /etc/nginx/.htpasswd-morningfox;

    location / { try_files $uri $uri/ =404; }
    location /editions/ { alias /home/elucia/dev/jina-clone/briefings/; }
}

server {
    listen 443 ssl;
    server_name themorningfox.com www.themorningfox.com;
    root /home/elucia/dev/jina-clone/web;
    index index.html;
    autoindex off;

    auth_basic "The Morning Fox";
    auth_basic_user_file /etc/nginx/.htpasswd-morningfox;

    location / { try_files $uri $uri/ =404; }
    location /editions/ { alias /home/elucia/dev/jina-clone/briefings/; }

    ssl_certificate /etc/letsencrypt/live/themorningfox.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/themorningfox.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
EOF'
```

- [ ] **Step 3: Issue the cert (webroot — port 80 on fox is Apache)**

The 443 server above references a cert that does not exist yet, so issue it BEFORE enabling the vhost / reloading nginx.

```bash
sudo sh -c 'certbot certonly --webroot -w /var/www/html -d themorningfox.com -d www.themorningfox.com --non-interactive --agree-tos -m ikhruschev@gmail.com'
```
Expected: "Successfully received certificate", files under `/etc/letsencrypt/live/themorningfox.com/`.

- [ ] **Step 4: Enable the vhost and reload**

```bash
sudo sh -c 'ln -sf /etc/nginx/sites-available/themorningfox.com /etc/nginx/sites-enabled/themorningfox.com && nginx -t && systemctl reload nginx'
```
Expected: `nginx: configuration file ... test is successful`, reload clean.

- [ ] **Step 5: Verify the live site (auth enforced, cert valid)**

```bash
echo "no creds (expect 401):"; curl -s -o /dev/null -w "%{http_code}\n" https://themorningfox.com/
echo "with creds (expect 200):"; curl -s -o /dev/null -w "%{http_code}\n" -u elucia:WRONG https://themorningfox.com/
```
Expected: first → `401`. Second with the REAL password (ask the user to run it via `! ` so the password is not in this transcript) → `200`. Also check the editions alias:
```bash
# user runs with real creds:
# ! curl -s -o /dev/null -w "%{http_code}\n" -u elucia:REALPASS https://themorningfox.com/editions/index.json
```
Expected: `200`.

(No commit — ops state lives on the box, not in git.)

---

## Task 5: Cron + live mirror E2E

**Files:** host crontab (user `elucia`), no git changes.

- [ ] **Step 1: Add the two publish-web cron lines (existing print lines untouched)**

Append to the host crontab without editing existing lines:

```bash
( crontab -l; \
  echo '45 8  * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone briefing publish-web >> logs/briefing.log 2>&1'; \
  echo '45 20 * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone briefing publish-web >> logs/briefing.log 2>&1' \
) | crontab -
```

- [ ] **Step 2: Confirm the crontab now has 4 briefing lines (2 print + 2 publish), print lines unchanged**

Run: `crontab -l | grep -nE "briefing (run|publish-web)"`
Expected: the two original `briefing run` lines at 8:10/20:10 verbatim, plus the two new `briefing publish-web` lines at 8:45/20:45.

- [ ] **Step 3: Live mirror E2E (proves the print run drops JSON)**

NOTE: this runs the real pipeline and PRINTS a paper + uses LLM quota. Either run it manually now, or let the next scheduled run prove it. To run now:

```bash
./.venv/bin/python -m jina_clone briefing run --edition=evening
```
Expected: prints, and `briefings/$(date +%F)-evening.json` now exists. Confirm:
```bash
rtk proxy sh -c 'ls -la briefings/$(date +%F)-evening.json'
```

- [ ] **Step 4: Publish + verify it becomes the site's latest**

```bash
./.venv/bin/python -m jina_clone briefing publish-web
```
Then (user runs with real creds via `! `):
```bash
# ! curl -s -u elucia:REALPASS https://themorningfox.com/editions/index.json | ./.venv/bin/python -c "import sys,json; e=json.load(sys.stdin)[0]; print(e['date'], e['edition'])"
```
Expected: prints today's date + `evening` (the edition just run) — i.e. the site lists the edition that printed. Open `https://themorningfox.com/` in a browser (with creds) and confirm the broadsheet renders.

- [ ] **Step 5: Verify the digest button end-to-end**

Open any backfilled page, e.g. `https://feed.themorningfox.com/ai-digest/` → newest page → confirm the "Read the full broadsheet" button shows and links to `https://themorningfox.com` (clicking prompts for the site login).

---

## Self-review notes

- **Spec coverage:** mirror-the-paper (Task 1+2 JSON drop), separate downstream publish (Task 2 subcommand + Task 5 cron), print path untouched except swallowed write (Task 1 wrapper, Task 2 wiring), nginx+auth+TLS+`/editions/` alias (Task 4), button (Task 3), cron offset (Task 5). All covered.
- **No double-publish:** `make_render_and_save_json` deliberately omits `rebuild_index` (asserted in Task 1 test `not (tmp_path / "index.json").exists()`), keeping index-rebuild solely in the `publish-web` step — the decoupling the user required.
- **Names consistent:** `make_render_and_save_json`, `_briefing_publish_web`, `rebuild_index`, `write_edition_json`, `broadsheet-link` used identically across tasks.
- **Secrets:** the basic-auth password never appears in this plan or transcript — auth'd curls are delegated to the user via the `! ` prefix.
```
