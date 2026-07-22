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

## Dev environment (stood up 2026-07-22)

- `~/dev/jina-clone-dev` — second checkout on `dev`, own venv, `.env` from
  `env/dev.env.example` (`mcp_news_dev`, PORT 8091, no ntfy). Briefing
  runs are **manual only** — no dev cron, no doubled LLM spend. The dev
  extractor container is not started; if needed:
  `docker compose -p jina-clone-dev up -d --build` in the dev checkout.
- `news-mcp-dev.service` — same news-mcp checkout, `EnvironmentFile=.env.dev`
  (`mcp_news_dev`), 127.0.0.1:4821.
- `nginx/morningfox-dev` — LAN-only dev site at `http://192.168.0.89:8081`
  serving the dev checkout's `web/` + `briefings/`.
- `mcp_news_dev` database created from `schema.sql`.

## Promotion flow (dev → prod)

1. Merge: `git checkout main && git merge --ff-only dev && git push`
   (or `git fetch . dev:main && git push origin main` without switching).
2. jina-clone prod: `scripts/deploy.sh` in this checkout (pull, deps,
   compose rebuild). Host-cron briefing picks up new code next firing.
3. news-mcp: `./deploy.sh` in `~/dev/news-mcp` (pull, `uv sync`,
   `systemctl restart news-mcp`).
4. Config changes (units/vhosts/crontab): apply per the table above,
   then update the copy in `deploy/`.
