# Branded nginx error pages across the static sites — Design

**Date:** 2026-06-21
**Status:** Approved (design); implementation pending
**Scope:** Live nginx config on host `fox` + static HTML in this repo (`web/`, `feeds/`). No application code.

## Problem

Visitors who explore non-existent or non-servable URLs on the Morning Fox
sites get the bare default nginx error page (`404 Not Found` / `nginx`,
or `403 Forbidden`). This looks broken and unbranded, and it leaked the
"nginx" string. An earlier ad-hoc pass added a custom 404 to
`themorningfox.com` and the feed hosts, but it was applied per-host by
hand and missed cases:

- **`https://feed.themorningfox.com/ai-digest/` returns 403, not 404.**
  Root cause: `/ai-digest/` is a real directory with no `index.html`, and
  `autoindex` is off, so nginx returns **403 Forbidden** — and
  `error_page 404` does not catch a 403. The custom 404 never applied
  there.
- The per-host, per-status hand-editing is what caused the drift. The fix
  must make that failure mode structurally hard to repeat.

## Goals

- Every error surface on the three static sites shows a branded page.
- No per-host drift: the same handling is applied to every static vhost by
  construction, not by remembering to edit each one.
- `/ai-digest/` lands a curious visitor on the latest digest.
- Forbidden / index-less directories do not reveal that something exists
  there (status hardening).

## Non-goals

- The reverse-proxied vhosts (`movies.elucia.com`, `n8n.elucia.com`,
  `track.elucia.com`). Their errors originate in the upstream apps; nginx
  can't cleanly brand them.
- Any HTTPS `default_server` catch-all for direct-IP / unknown-host
  probes.
- A generated index/listing page for `/ai-digest/`.

## In-scope vhosts

`themorningfox.com`, `feed.themorningfox.com`, `feeds.elucia.com`.

`themorningfox.com` root = `web/`. Both feed hosts share root = `feeds/`.

## Behavior

| Condition | Result |
|---|---|
| Missing path | branded **404** |
| Existing directory, no index (generic) | branded **404**, status rewritten from 403 |
| `/ai-digest/` specifically | **302 → /ai-digest/latest.html** (feed hosts only) |
| Server error (5xx) | branded **50x** |
| Dotfiles (`/.`…) | unchanged — already 404 via existing `deny-dotfiles.conf` |

Decision on 403: rewrite to 404 (`error_page 403 =404 …`) rather than a
distinct branded 403 page. A probe then cannot distinguish "forbidden
directory exists here" from "nothing here." (This reverses an earlier
in-discussion choice of an honest 403 page.)

## Approach: one shared snippet, included per vhost

Mirror the existing pattern (`snippets/security-headers.conf`,
`snippets/deny-dotfiles.conf`). Create:

`/etc/nginx/snippets/error-pages.conf`
```nginx
error_page 403 =404 /404.html;
error_page 404 /404.html;
error_page 500 502 503 504 /50x.html;
```

Each static vhost adds one line: `include snippets/error-pages.conf;`.
Because `error_page` targets a URI, it resolves against each vhost's own
root, so `web/` serves `web/404.html` and the feed hosts serve
`feeds/404.html` automatically — one snippet, no per-host divergence. The
only invariant: the referenced page files must exist in **both** roots.

Rejected alternatives:
- Inline `error_page` lines per vhost — the duplicated form that caused
  the original drift.
- http-level / `default_server` error pages — the two roots differ and
  `error_page` resolves per-vhost; doesn't fit.

## Files

New:
- `/etc/nginx/snippets/error-pages.conf` (live host config, not in repo).
- `feeds/50x.html` — branded server-error page for the feed hosts, so they
  match `themorningfox.com` (which already has `web/50x.html`). Styled to
  match the digest pages (self-contained, fonts from `/ai-digest/fonts/`).

Existing, kept as-is:
- `web/404.html`, `web/50x.html`, `feeds/404.html`.

Removed from earlier plan:
- No `403.html` pages (403 is rewritten to 404).

## Config changes (three vhost files)

For all three (`themorningfox.com`, `feed.themorningfox.com`,
`feeds.elucia.com`):
- Replace the inline `error_page` lines added in the earlier ad-hoc pass
  with a single `include snippets/error-pages.conf;`.

For the two feed hosts only:
- Add `location = /ai-digest/ { return 302 /ai-digest/latest.html; }`.
  Both `feed.themorningfox.com` and `feeds.elucia.com` must get this —
  they share the `feeds/` root.

Process: back up every file touched (`.bak-<timestamp>-errorpages`),
`sudo nginx -t`, `sudo systemctl reload nginx`.

## Verification

After applying, run the full status matrix across all three hosts and
confirm:

| Request | Expected |
|---|---|
| `…/<nonexistent>` (each host) | 404, branded body |
| `feed.themorningfox.com/ai-digest/` | 302 → latest.html |
| `feeds.elucia.com/ai-digest/` | 302 → latest.html |
| `…/ai-digest/fonts/` (real dir, no index) | **404** (rewritten from 403) |
| `themorningfox.com/` , `/ai-digest/latest.html` | 200 (no regression) |
| `themorningfox.com/stats/` | 401 (auth intact) |
| `movies / n8n / track .elucia.com` | unchanged (proxied apps untouched) |

`nginx -t` clean and `nginx` active are preconditions for "done."

## Rollback

Restore the relevant `/etc/nginx/**.bak-*-errorpages` file(s) and
`sudo systemctl reload nginx`. The repo HTML files are inert if unused.

## Notes / repo hygiene

- `web/404.html`, `web/50x.html`, `feeds/404.html`, and the new
  `feeds/50x.html` are tracked repo files under `web/`/`feeds/` source
  dirs (not runtime artifacts). They can be committed.
- The nginx snippet and vhost configs live only on the host, not in the
  repo (consistent with prior security-hardening work).
