# AI/ML Digest — RSS Feed Delivery (supersedes webhook delivery)

**Status:** Approved (brainstorming session 2026-06-09, evening)
**Supersedes:** the *Delivery* portion of
`2026-06-09-slack-ai-digest-design.md`. Generation, selection, windows,
and notification policy from that spec stand unchanged.

## Why the change

The webhook design assumed the user could install a Slack app in the
work workspace. They cannot (no admin / app-install rights). Slack's
first-party RSS app **is** available there (`/feed` confirmed working),
so delivery inverts: instead of pushing to Slack, we publish a public
RSS feed that Slack polls. This also kills the deferred bot-token
voting idea — it needed app installation too.

## Hard constraint

**The existing briefing pipeline is unaffected.** No changes to
`run_briefing`, `renderer.py`, `printer.py`, `web.py`, `run_web.py`,
the briefing crontab lines, or anything under `templates/`/`static/`.
Only the digest delivery layer changes.

## Decisions (user-confirmed)

- **One feed entry per edition.** Each run adds one `<item>`; one Slack
  message per run. Entry title `AI/ML Morning Digest — Tue Jun 9`
  links to a hosted HTML digest page; the entry description carries
  the same content so Slack's snippet shows the lead.
- **Served from a new subdomain: `feeds.elucia.com`** (nginx static
  server block on fox + DNS A record + certbot, same pattern as the
  four existing elucia.com subdomains). No basic-auth on this vhost —
  Slack's poller must reach it anonymously.
- **Webhook code is removed**, not flagged off: `post_webhook`, the
  mrkdwn formatters, `SLACK_WEBHOOK_URL` (settings + `.env.example` +
  tests). Git history preserves it.
- **CLI name stays `slack-digest`** (it is still the digest Slack
  reads); flags stay `--edition` and `--dry-run`.

## Architecture

```
slack-digest --edition=morning
  └─ fetch_section_articles(ai, window)   [unchanged]
     └─ generate_slack_digest(...)        [unchanged]
        └─ publish_digest(...)            [new: feed.py]
             writes {date}-{edition}.json   (SlackDigest dump; source of truth)
             writes {date}-{edition}.html   (standalone page)
             rebuilds feed.xml              (scan JSON files, newest-first, cap 20)
```

### `jina_clone/briefing/feed.py` (replaces `slack.py`)

Pure rendering + local file publishing; no network.

- `render_digest_html(digest, *, edition_label, date_label) -> str` —
  minimal standalone HTML (inline CSS, no JS): header, lead, bulleted
  linked items with blurbs, generated-at footer.
- `render_feed_xml(entries, *, base_url) -> str` — RSS 2.0 built with
  stdlib only (`xml.sax.saxutils.escape`,
  `email.utils.format_datetime` for RFC-822 dates). Per `<item>`:
  - `title`: `AI/ML {Edition} Digest — {date_label}`
  - `link` + `guid isPermaLink="true"`: `{base_url}/{date}-{edition}.html`
  - `description`: the digest HTML body in CDATA (Slack snippet source)
  - `pubDate`: generation time
- `publish_digest(digest, *, out_dir, base_url, iso_date, edition,
  edition_label, date_label) -> Path` — writes the JSON + HTML, then
  rebuilds `feed.xml` by scanning `{date}-{edition}.json` files
  (rebuild-by-scan self-heals, same pattern as `web.rebuild_index`),
  newest 20 entries. Old HTML pages are never pruned.
- `publish_fallback(articles, *, …same kwargs) -> Path` — degraded
  variant for LLM failure: headlines-only page/entry (linked titles,
  capped at 10, "_LLM digest unavailable_" note). Same fallback policy
  as the webhook design, new rendering. Both share one internal
  write-outputs + rebuild helper.

### `jina_clone/jobs/slack_digest.py` (adapted)

Same orchestrator shape and failure policy, with the
`format_digest`/`format_fallback`/`post` callables replaced by an
injected `publish`/`publish_fallback` pair (mirroring the old
format pair; no separate post step — publishing *is* delivery):

| Failure | Behavior |
|---|---|
| LLM (`GeneratorFailure`) | publish headlines-only page/entry, then ntfy (degraded, not silent) |
| Publish (file write) fails | ntfy, then re-raise so the cron log records it |
| Zero articles in window | no entry, no ntfy (quiet windows are normal) |

### Settings (`config.py`)

`slack_webhook_url` is removed. Added, both optional at load and
validated only when `slack-digest` runs without `--dry-run`:

- `FEED_BASE_URL` — e.g. `https://feeds.elucia.com/ai-digest`
  (absolute links in the feed require it)
- `FEED_OUTPUT_DIR` — default `feeds/ai-digest/` under the repo root;
  gitignored (same policy as `briefings/`)

`--dry-run` prints the rendered feed XML + page HTML to stdout and
writes nothing.

## Timing

Slack polls feeds with a typical 10–30 min lag. Cron runs shift 15
minutes earlier — **8:45 and 16:30 ET** — so messages land near the
original 9:00 / 16:45 targets. Window *durations* are unchanged
(morning 16.25 h, afternoon 7.75 h), preserving non-overlap.

## Ops (manual, user)

1. DNS A record `feeds.elucia.com` → fox public IP.
2. nginx static server block, `root` at the feed output dir (or a
   `location /ai-digest/ { alias …; }`), `nginx -t`, reload.
3. `certbot --nginx -d feeds.elucia.com`.
4. Verify `www-data` can read the output dir (`o+x` on the home-dir
   path — known gotcha from the morningfox launch plan).
5. Host crontab: two `slack-digest` lines at 8:45 / 16:30 ET, output
   to a log elucia owns (`logs/` is root-owned on fox — known gotcha).
6. In the work Slack channel: `/feed subscribe
   https://feeds.elucia.com/ai-digest/feed.xml`.

## Testing

- `tests/test_briefing_slack.py` → `tests/test_briefing_feed.py`:
  HTML escaping, feed XML structure (CDATA, guid, RFC-822 pubDate),
  rebuild-scan ordering + 20-entry cap, degraded/missing-title
  fallback — all against `tmp_path`. No DB, no network.
- `tests/test_jobs_slack_digest.py`: swap post/format fakes for a
  publish fake; same five scenarios.
- `tests/test_config.py`: replace the webhook test with the two new
  settings.
- Live E2E (per CLAUDE.md, before polish): real DB + real `claude -p`
  via `--dry-run`; after nginx is up, one real write + `curl` of
  `feed.xml`; final verification is the actual Slack message after
  `/feed subscribe`.

## Known risk

Slack's rendering of the entry description (snippet length, link
clickability) is not verifiable until a real `/feed subscribe`. Hedge:
the hosted HTML page is the canonical full view; worst case the Slack
message is a linked title + lead text.

## Out of scope

- Voting/reactions/threading (dead with the bot-token path).
- Any change to the briefing pipeline (hard constraint above).
- Pruning old HTML pages; feed auth; multiple categories/feeds.
