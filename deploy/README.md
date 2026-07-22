# deploy/ — checked-in copies of everything that defines "deployed" on fox

Captured 2026-07-22 from the live system. These are the source of truth;
if you change the live config, update the copy here (and vice versa).

| File | Live location | Apply with |
|---|---|---|
| `systemd/news-mcp.service` | `/etc/systemd/system/` | `sudo cp … && sudo systemctl daemon-reload && sudo systemctl restart news-mcp` |
| `systemd/news-gatherer.service` | `/etc/systemd/system/` | same + `systemctl restart news-gatherer.timer` |
| `systemd/news-gatherer.timer` | `/etc/systemd/system/` | same |
| `crontab.host` | elucia's host crontab (`crontab -l`) | merge by hand — these are only the jina-clone lines; the live crontab has unrelated entries (mounts, news-rag) |
| `nginx/*` | `/etc/nginx/sites-available/` (+ symlink in `sites-enabled/`) | `sudo cp … && sudo nginx -t && sudo systemctl reload nginx` |
| `nginx/snippets/*` | `/etc/nginx/snippets/` | same |
| `env/prod.env.example` | `.env` in the prod checkout (this one) | copy + fill secrets |
| `env/dev.env.example` | `.env` in the dev checkout | copy + fill secrets |

Notes:

- The briefing cron jobs run on the **host** (subscription-authed `claude`
  CLI lives in `~/.npm-global/bin`, not in the container) — see CLAUDE.md
  "Two crontabs".
- news-mcp units belong to `~/dev/news-mcp` but are checked in here so one
  repo holds the whole fox deployment picture.
- `news-mcp.service` binds 127.0.0.1:4820 (changed 2026-07-22 from
  0.0.0.0 — journal showed zero LAN consumers) and serves the SSE app
  (`news_mcp_server:app`).
- TLS certs/dhparams referenced by the vhosts come from certbot and are
  not in git.
