# Branded nginx Error Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every error surface on the three static Morning Fox sites shows a branded page, applied uniformly via one shared nginx snippet so no host can drift.

**Architecture:** A single `/etc/nginx/snippets/error-pages.conf` maps 403→404 (status-rewritten), 404, and 5xx to branded pages; each static vhost `include`s it, resolving the page URIs against its own root. The two feed hosts also gain a `location = /ai-digest/` → latest-digest redirect. One new HTML file (`feeds/50x.html`) is added so the feed root has the full page set; all other pages already exist.

**Tech Stack:** nginx (static file serving + `error_page`), static HTML/CSS. No application code, no Python.

## Global Constraints

- **In-scope vhosts only:** `themorningfox.com`, `feed.themorningfox.com`, `feeds.elucia.com`. Do NOT touch `movies.elucia.com`, `n8n.elucia.com`, `track.elucia.com`, or the `default` server.
- **403 is rewritten to 404** (`error_page 403 =404 /404.html;`). No `403.html` page exists or is created.
- **Roots:** `themorningfox.com` → `/home/elucia/dev/jina-clone/web`; both feed hosts → `/home/elucia/dev/jina-clone/feeds`.
- **Host-config files are root-owned:** edit via a temp file + `sudo install -m 644 -o root -g root`. Never edit `/etc/nginx/**` in place as a non-root user.
- **Every host-config file touched gets a timestamped backup** `*.bak-<YYYYMMDD-HHMMSS>-errorpages` before being overwritten (matches the existing `.bak-*` convention in `sites-available/`).
- **Repo hygiene:** only `git add` explicit paths. NEVER `git add -A`/`git add .` (this repo has swept runtime artifacts into commits before). nginx config lives on the host only — it is NOT committed.
- **Commit trailers** on every git commit:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HCc126dfmJqrSVrn3p4JNa
  ```
- **Verification is the gate:** the task is not "done" until `sudo nginx -t` is clean, `nginx` is active, and the curl matrix in Task 2 matches expected.

---

### Task 1: Add the branded `feeds/50x.html` server-error page

The feed hosts (root `feeds/`) have `404.html` but no `50x.html`. `themorningfox.com` already has `web/50x.html`. Add the feed-root equivalent, styled to match the digest pages (self-contained, dark-mode aware, fonts pulled from `/ai-digest/fonts/`, same palette as `feeds/404.html`).

**Files:**
- Create: `/home/elucia/dev/jina-clone/feeds/50x.html`

**Interfaces:**
- Consumes: nothing.
- Produces: a static file `feeds/50x.html` reachable at URI `/50x.html` on both feed hosts; referenced later by the `error_page 500 ...` line in Task 2's snippet.

- [ ] **Step 1: Write the page**

Create `/home/elucia/dev/jina-clone/feeds/50x.html` with exactly this content:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Something broke — The Morning Fox</title>
<script>
// Apply the saved/system theme before first paint to avoid a flash.
(function () {
  try {
    var saved = localStorage.getItem("theme");
    var dark = saved
      ? saved === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (dark) document.documentElement.dataset.theme = "dark";
  } catch (e) {}
})();
</script>
<style>
@font-face {
  font-family: 'Bodoni Moda';
  src: url('/ai-digest/fonts/BodoniModa-Medium.ttf') format('truetype');
  font-weight: 500;
}
@font-face {
  font-family: 'Libre Baskerville';
  src: url('/ai-digest/fonts/LibreBaskerville-Regular.woff2') format('woff2');
  font-weight: 400;
}
:root {
  color-scheme: light;
  --ink: #1a1a1a; --ink-soft: #333; --muted: #777; --rule: #1a1a1a;
  --underline: #b5b0a4; --bg: #faf8f3;
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ink: #d6cfbf; --ink-soft: #cac4b6; --muted: #968f7d; --rule: #bcb5a4;
  --underline: rgba(231, 226, 214, .4); --bg: #16140f;
}
body { font-family: Georgia, 'Times New Roman', serif; max-width: 40rem;
  margin: 0 auto; min-height: 100vh; padding: 0 1.2rem; color: var(--ink);
  background: var(--bg); display: flex; flex-direction: column;
  align-items: center; justify-content: center; text-align: center; }
.kicker { font-family: 'Bodoni Moda', Georgia, serif; font-weight: 500;
  text-transform: uppercase; letter-spacing: 3px; font-size: .85rem;
  color: var(--muted); margin: 0 0 .4rem; }
.code { font-family: 'Bodoni Moda', Georgia, serif; font-weight: 500;
  font-size: clamp(40px, 12vw, 76px); line-height: 1.05; margin: 0; }
.rule { border: 0; border-top: 3px double var(--rule);
  width: 18rem; max-width: 80%; margin: 1.1rem auto; }
.headline { font-family: 'Libre Baskerville', Georgia, serif;
  font-size: clamp(20px, 6vw, 30px); margin: 0 0 .6rem; }
.deck { font-style: italic; color: var(--ink-soft); max-width: 28rem;
  margin: 0 auto 1.6rem; line-height: 1.5; }
a.home { color: var(--ink); text-decoration: none;
  border-bottom: 1px solid var(--underline); padding-bottom: 1px;
  font-size: 1.05rem; }
a.home:hover { border-bottom-color: var(--ink); }
</style>
</head>
<body>
  <p class="kicker">The Morning Fox</p>
  <p class="code">Hold the press</p>
  <hr class="rule">
  <h1 class="headline">The presses jammed.</h1>
  <p class="deck">Something on our end went wrong while setting today's page.
    It's not you. Give it a moment and try again.</p>
  <a class="home" href="/ai-digest/latest.html">Read the latest digest &rarr;</a>
</body>
</html>
```

- [ ] **Step 2: Verify it renders standalone (sanity, pre-nginx)**

Run: `grep -c 'The presses jammed' /home/elucia/dev/jina-clone/feeds/50x.html`
Expected: `1`

- [ ] **Step 3: Commit (repo file only)**

```bash
git add feeds/50x.html
git commit -m "feat(web): branded 50x error page for the feed hosts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HCc126dfmJqrSVrn3p4JNa"
```

---

### Task 2: Create the shared snippet, wire it into all three vhosts, add `/ai-digest/` redirect, verify

**Files (host only — none committed):**
- Create: `/etc/nginx/snippets/error-pages.conf`
- Modify: `/etc/nginx/sites-available/themorningfox.com`
- Modify: `/etc/nginx/sites-available/feed.themorningfox.com`
- Modify: `/etc/nginx/sites-available/feeds.elucia.com`

**Interfaces:**
- Consumes: `web/404.html`, `web/50x.html` (already exist); `feeds/404.html` (exists), `feeds/50x.html` (Task 1).
- Produces: uniform 403→404 / 404 / 5xx handling on all three static hosts; 302 `/ai-digest/` → `/ai-digest/latest.html` on the two feed hosts.

- [ ] **Step 1: Define the expected behavior (the "failing test" — run BEFORE changes)**

Run this matrix and record current (pre-change) codes; the FAIL we are fixing is the two `403`s:

```bash
for u in \
  "https://feed.themorningfox.com/ai-digest/" \
  "https://feeds.elucia.com/ai-digest/" \
  "https://feed.themorningfox.com/ai-digest/fonts/" ; do
  printf '%-50s %s\n' "$u" "$(curl -sS -k -o /dev/null -w '%{http_code}' "$u")"
done
```
Expected NOW (the bug): all three print `403`.
Expected AFTER Task 2: first two `302`, third `404`.

- [ ] **Step 2: Create the shared snippet**

Write to a temp file then install as root:

```bash
cat > /tmp/error-pages.conf <<'EOF'
# Branded error pages, shared by the static Morning Fox vhosts.
# error_page targets a URI, so each page resolves against the
# including vhost's own root (web/ or feeds/), which must contain
# 404.html and 50x.html. 403 is rewritten to 404 to avoid revealing
# that a forbidden/index-less path exists.
error_page 403 =404 /404.html;
error_page 404 /404.html;
error_page 500 502 503 504 /50x.html;
EOF
sudo install -m 644 -o root -g root /tmp/error-pages.conf /etc/nginx/snippets/error-pages.conf
```

- [ ] **Step 3: Back up the three vhost files**

```bash
ts=$(date +%Y%m%d-%H%M%S)
for h in themorningfox.com feed.themorningfox.com feeds.elucia.com; do
  sudo cp -a /etc/nginx/sites-available/$h /etc/nginx/sites-available/$h.bak-${ts}-errorpages
done
echo "backups stamped: $ts"
```

- [ ] **Step 4: Install the new `themorningfox.com` vhost**

This replaces the two inline `error_page 404`/`50x` lines (added in the earlier ad-hoc pass) with the shared `include`. Write to temp and install:

```bash
cat > /tmp/themorningfox.com <<'EOF'
server {
    listen 8080;
    server_name themorningfox.com www.themorningfox.com;
    root /home/elucia/dev/jina-clone/web;
    index index.html;
    access_log /var/log/morningfox/access.log;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = /ai  { return 302 https://feed.themorningfox.com/ai-digest/latest.html; }
    location = /ai/ { return 302 https://feed.themorningfox.com/ai-digest/latest.html; }
    location = /stats { return 301 https://$host/stats/; }
    location / { try_files $uri $uri/ =404; }
    location /editions/ { alias /home/elucia/dev/jina-clone/briefings/; }
}

server {
    listen 443 ssl;
    server_name themorningfox.com www.themorningfox.com;
    root /home/elucia/dev/jina-clone/web;
    index index.html;
    access_log /var/log/morningfox/access.log;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = /ai  { return 302 https://feed.themorningfox.com/ai-digest/latest.html; }
    location = /ai/ { return 302 https://feed.themorningfox.com/ai-digest/latest.html; }
    location / { try_files $uri $uri/ =404; }
    location /editions/ { alias /home/elucia/dev/jina-clone/briefings/; }

    # Visitor stats dashboard (GoAccess) — password-protected, HTTPS only.
    location = /stats { return 301 /stats/; }
    location /stats/ {
        alias /var/www/morningfox-stats/;
        access_log off;
        index index.html;
        auth_basic "Morning Fox Stats";
        auth_basic_user_file /etc/nginx/.htpasswd-stats;
    }

    ssl_certificate /etc/letsencrypt/live/themorningfox.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/themorningfox.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
EOF
sudo install -m 644 -o root -g root /tmp/themorningfox.com /etc/nginx/sites-available/themorningfox.com
```

- [ ] **Step 5: Install the new `feed.themorningfox.com` vhost**

Replaces inline `error_page` with the `include`, and adds `location = /ai-digest/` redirect to both server blocks:

```bash
cat > /tmp/feed.themorningfox.com <<'EOF'
server {
    listen 8080;
    server_name feed.themorningfox.com;
    root /home/elucia/dev/jina-clone/feeds;
    access_log /var/log/morningfox/access.log;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = / { return 302 /ai-digest/latest.html; }
    location = /ai-digest/ { return 302 /ai-digest/latest.html; }
    location = /ai-digest/latest.html {
        add_header Cache-Control "no-store" always;
        include snippets/security-headers.conf;
        try_files $uri =404;
    }
    location / { try_files $uri $uri/ =404; }
}

server {
    listen 443 ssl;
    server_name feed.themorningfox.com;
    root /home/elucia/dev/jina-clone/feeds;
    access_log /var/log/morningfox/access.log;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = / { return 302 /ai-digest/latest.html; }
    location = /ai-digest/ { return 302 /ai-digest/latest.html; }
    location = /ai-digest/latest.html {
        add_header Cache-Control "no-store" always;
        include snippets/security-headers.conf;
        try_files $uri =404;
    }
    location / { try_files $uri $uri/ =404; }

    ssl_certificate /etc/letsencrypt/live/feed.themorningfox.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/feed.themorningfox.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
EOF
sudo install -m 644 -o root -g root /tmp/feed.themorningfox.com /etc/nginx/sites-available/feed.themorningfox.com
```

- [ ] **Step 6: Install the new `feeds.elucia.com` vhost**

```bash
cat > /tmp/feeds.elucia.com <<'EOF'
server {
    listen 8080;
    server_name feeds.elucia.com;
    root /home/elucia/dev/jina-clone/feeds;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = /ai-digest/ { return 302 /ai-digest/latest.html; }
    location / { try_files $uri $uri/ =404; }
}

server {
    listen 443 ssl;
    server_name feeds.elucia.com;
    root /home/elucia/dev/jina-clone/feeds;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = /ai-digest/ { return 302 /ai-digest/latest.html; }
    location / { try_files $uri $uri/ =404; }

    ssl_certificate /etc/letsencrypt/live/feeds.elucia.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/feeds.elucia.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
EOF
sudo install -m 644 -o root -g root /tmp/feeds.elucia.com /etc/nginx/sites-available/feeds.elucia.com
```

- [ ] **Step 7: Validate config syntax**

Run: `sudo nginx -t`
Expected: `syntax is ok` and `test is successful`.
If it FAILS: do not reload. Restore from the `.bak-${ts}-errorpages` files and stop.

- [ ] **Step 8: Reload nginx**

Run: `sudo systemctl reload nginx && systemctl is-active nginx`
Expected: `active`.

- [ ] **Step 9: Run the full verification matrix (the passing test)**

```bash
for row in \
  "https://themorningfox.com/nonexistent-xyz|404" \
  "https://feed.themorningfox.com/nonexistent-xyz|404" \
  "https://feeds.elucia.com/nonexistent-xyz|404" \
  "https://feed.themorningfox.com/ai-digest/|302" \
  "https://feeds.elucia.com/ai-digest/|302" \
  "https://feed.themorningfox.com/ai-digest/fonts/|404" \
  "https://themorningfox.com/|200" \
  "https://feed.themorningfox.com/ai-digest/latest.html|200" \
  "https://themorningfox.com/stats/|401" \
  "https://movies.elucia.com/nope|307" \
  "https://n8n.elucia.com/nope|200" ; do
  url="${row%|*}"; want="${row#*|}"
  got=$(curl -sS -k -o /dev/null -w '%{http_code}' "$url")
  [ "$got" = "$want" ] && ok="PASS" || ok="FAIL"
  printf '%-50s want=%s got=%s %s\n' "$url" "$want" "$got" "$ok"
done
```
Expected: every row `PASS`. The two `/ai-digest/` rows now `302` (were `403`); the `/ai-digest/fonts/` row now `404` (was `403`); proxied apps unchanged.

- [ ] **Step 10: Confirm branded body actually serves on a 404**

Run: `curl -sS -k https://feed.themorningfox.com/nonexistent-xyz | grep -c 'wandered off'`
Expected: `1` (the branded 404 body, not bare nginx).

- [ ] **Step 11: Confirm the redirect target resolves**

Run: `curl -sS -k -o /dev/null -w '%{http_code}\n' -L https://feed.themorningfox.com/ai-digest/`
Expected: `200` (follows the 302 to a real `latest.html`).

There is no git commit in this task — all changes are live host config, not repo files. Record the backup timestamp from Step 3 in the handoff for rollback.

---

## Rollback

Restore any/all of the four host files from their `*.bak-<ts>-errorpages` backups and `sudo systemctl reload nginx`. Removing `/etc/nginx/snippets/error-pages.conf` requires also removing the `include` lines, so prefer restoring the vhost backups wholesale. The repo file `feeds/50x.html` is inert if unused.

## Self-Review

- **Spec coverage:** missing-path 404 (Task 2 matrix) ✓; generic dir→404 via `error_page 403 =404` (snippet, Step 2; matrix `/ai-digest/fonts/`) ✓; `/ai-digest/`→latest on both feed hosts (Steps 5–6) ✓; 5xx branded incl. new `feeds/50x.html` (Task 1, snippet) ✓; dotfiles unchanged (untouched `deny-dotfiles.conf` include) ✓; shared-snippet approach / no per-host drift (Task 2) ✓; scope = 3 static hosts, proxied apps untouched (matrix asserts movies/n8n unchanged) ✓; backups + nginx -t + reload ✓.
- **Placeholder scan:** none — every file has full content, every command is concrete with expected output.
- **Type/name consistency:** snippet references `/404.html` + `/50x.html`; both roots contain both after Task 1; redirect target `/ai-digest/latest.html` matches the existing special location block; vhost contents match the live configs plus the three include/redirect edits.
