# Jina Clone — Article Pipeline

A native Python pipeline that discovers articles from RSS feeds and scraped
index pages, extracts their content, stores them in the existing `mcp_news`
Postgres database, and generates daily LLM summaries. Runs as a single
Docker container on `fox` (192.168.0.89) with in-container cron.

Originally just an HTTP extractor service (still present, still serves
`/extract` for n8n and other callers), now extended with a batch pipeline.

## What it does

```
sources.yaml ──► fetch  ──► extract ──► Postgres (entries)
                   ▲                        │
                   │ hourly                 │ daily 08:10 ET
                   │                        ▼
                 cron ────────────────► summarize ──► LLM ──► summaries/*.md
                                                          └─► Postgres (news_summaries)
```

- **Fetch job** (hourly): walks every source in `sources.yaml`, discovers article
  URLs (RSS feed parsing or CSS-selector index scraping), dedups against
  `entries.link`, extracts each new article via Readability, and inserts rows
  into `entries`. Extraction failures are stored with `content=null` so the
  URL is "seen" and never retried.
- **Summarize job** (daily 08:10 America/New_York): selects unsummarized
  articles for our sources, builds a single prompt (newest-first, capped at
  200k chars), sends it to the configured LLM provider, writes the result to
  `summaries/YYYY-MM-DD-HHMM.md`, inserts a `news_summaries` row, and marks
  the included articles `summarized_at`. On LLM failure nothing is written —
  the next run retries.
- **Extractor HTTP service** (always-on): `GET /extract?url=...` returns
  clean plain text, same as before. Used by n8n and other external callers.
  Port 8090 on `fox`.

## LLM providers

Swappable via `LLM_PROVIDER` env var:

| Provider | Default model                    | API key env var      |
|----------|----------------------------------|----------------------|
| `claude` | `claude-sonnet-4-6`              | `ANTHROPIC_API_KEY`  |
| `openai` | `gpt-4o`                         | `OPENAI_API_KEY`     |
| `gemini` | `gemini-3.1-flash-lite-preview`  | `GEMINI_API_KEY`     |

Override any default with `LLM_MODEL=...`. Only the selected provider's key
is required at startup.

Currently running with `LLM_PROVIDER=gemini`.

## Deployment

Deployed on `fox` in this directory. The container uses **host networking**
(not bridge) because fox's `pg_hba.conf` only allows LAN source IPs, not
the Docker bridge subnet.

```bash
# On fox, from this directory:
docker compose up -d --build
```

`restart: always` is set so the container comes back up after reboots or
crashes. Cron runs inside the container with `TZ=America/New_York`.

### Verify it's up

```bash
curl http://192.168.0.89:8090/health
# → {"status":"ok"}
```

### Run jobs manually

```bash
docker compose exec extractor python -m jina_clone fetch
docker compose exec extractor python -m jina_clone summarize
```

### Tail cron logs

```bash
tail -f logs/fetch.log logs/summarize.log
```

(Host directory `logs/` is mounted to `/var/log/jina-clone` inside the
container.)

### Find generated summaries

```bash
ls summaries/
cat summaries/$(ls -t summaries/ | head -1)
```

## Running a briefing manually

The briefing is a separate pipeline from `summarize`: it generates a
2-page broadsheet-style PDF (4 panels + pull-quote + briefs), renders it
with WeasyPrint, and sends it to the `brother` CUPS queue duplex
long-edge. Cron fires it twice daily (08:10 ET morning, 20:10 ET
evening). To kick one off by hand — for example, if you ask Claude to
print "the latest news as of now":

```bash
./.venv/bin/python -m jina_clone briefing run --edition=evening
# or --edition=morning
```

Pick the edition to match the time of day. Output: `briefings/YYYY-MM-DD-<edition>.pdf`, a `brother-N` print job, and a `news_summaries` row.

Requires `GEMINI_API_KEY` in `.env` and that `lpstat -p brother` reports
the printer idle + enabled. If a previous cron run left a root-owned
PDF at the target path, `rm` it first.

### Re-print the last rendered PDF

If the print jams or you just want another copy, skip the LLM and reuse
the existing PDF:

```bash
lp -d brother -o sides=two-sided-long-edge briefings/2026-04-19-evening.pdf
```

Same flag the job uses internally (`jina_clone/briefing/printer.py`).

### Subcommands

`briefing run` is the all-in-one. The individual stages are also
exposed if you want to iterate on one without re-running the others:

| Command                                    | What it does                                                |
|--------------------------------------------|-------------------------------------------------------------|
| `briefing generate [--out path.json]`      | Fetch + LLM only. Writes the briefing JSON.                 |
| `briefing render <input.json> [--out …]`   | JSON → PDF via WeasyPrint. No network, no print.            |
| `briefing print <file.pdf>`                | Submit an existing PDF to `brother` with the duplex flag.   |
| `briefing run --edition=morning\|evening`  | All of the above, plus logs a `news_summaries` row.         |

## Slack AI/ML digest

Twice-daily digest of `category: ai` articles, published as a public
RSS 2.0 feed + per-edition HTML pages (the work Slack workspace allows
no app installs, so the channel subscribes with
`/feed subscribe <FEED_BASE_URL>/feed.xml` instead of a webhook).
`FEED_BASE_URL` and `FEED_OUTPUT_DIR` live in `.env`; nginx serves the
output dir at the base URL. Each run writes a JSON record + HTML page
and rebuilds `feed.xml` (newest 20 entries, rebuild-by-scan).

```bash
./.venv/bin/python -m jina_clone slack-digest --edition=morning    # 8:45 ET cron
./.venv/bin/python -m jina_clone slack-digest --edition=afternoon  # 16:30 ET cron
./.venv/bin/python -m jina_clone slack-digest --edition=afternoon --dry-run  # print, don't write
```

Editions use non-overlapping windows (morning 16.25h, afternoon 7.75h),
so no article appears twice. On LLM failure the feed entry degrades to
headlines-only and sends an ntfy alert. Design:
`docs/superpowers/specs/2026-06-09-ai-digest-rss-feed-design.md`.

## Adding new sources

Every source is an entry in `sources.yaml` at the repo root. The file is
mounted read-only into the container, so edits take effect on the next job
run — **no rebuild, no restart**.

### RSS feeds

```yaml
- name: Simon Willison
  type: rss
  url: https://simonwillison.net/atom/everything/
  category: ai
```

Fields:
- `name` — human-readable, written to `entries.source`. Must be unique.
- `type: rss` — the feed is parsed with `feedparser`.
- `url` — the feed URL (Atom or RSS).
- `category` — written to `entries.category` (and used for the daily
  summary's `news_summaries.category`). Default `"ai"`.

### Index pages scraped via CSS selector

```yaml
- name: Hacker News
  type: scrape
  url: https://news.ycombinator.com/
  link_selector: ".titleline > a"
  category: ai
```

Fields:
- `name`, `url`, `category` — as above.
- `type: scrape` — the URL is fetched, parsed with BeautifulSoup, and
  `link_selector` is applied with `soup.select(selector)`.
- `link_selector` — a CSS selector that resolves to `<a>` elements whose
  `href` is an article URL. Relative hrefs are resolved against `url`.

### Finding the right selector for a scrape source

1. Open the index page in your browser.
2. Right-click an article link → Inspect.
3. Look at the `<a>` tag's classes and parents. Pick a selector that matches
   **article links only**, not nav or sidebar links. Good patterns:
   - `article h2 > a` (post listings on many blogs)
   - `.post-title > a`
   - `.entry-title a`
4. Test locally against a saved copy of the page:

   ```bash
   docker compose exec extractor python -c "
   from bs4 import BeautifulSoup
   import httpx
   html = httpx.get('https://example.com/blog', follow_redirects=True).text
   print([a.get('href') for a in BeautifulSoup(html, 'html.parser').select('YOUR_SELECTOR')])
   "
   ```

### Adding the source

1. Edit `sources.yaml`, append the new entry.
2. (Optional, for immediate pickup) Run the fetch job manually:

   ```bash
   docker compose exec extractor python -m jina_clone fetch
   ```

   Otherwise, the next hourly cron tick picks it up.
3. Verify rows landed:

   ```bash
   PGPASSWORD='REDACTED' psql -h 192.168.0.89 -U postgres -d mcp_news \
     -c "SELECT source, COUNT(*) FROM entries WHERE source='YOUR NAME' GROUP BY source;"
   ```

### Caveats for new sources

- **Unique names**: `name` is used to scope our queries against `entries`
  (which is shared with another pipeline). Don't reuse a name that the other
  pipeline already writes.
- **JS-rendered pages**: Readability works on static HTML only. Sites that
  hydrate content client-side will produce empty `content`. The URL is still
  stored (with `content=null`), but won't appear in summaries.
- **Paywalls / login walls / Cloudflare challenges**: the extractor sees the
  challenge page, not the article. Same failure mode as above.
- **Feed-with-summaries sources**: some RSS feeds include only titles and
  excerpts. The extractor follows the `link` and fetches the full article
  anyway, so this usually Just Works.
- **Rate limits**: `FETCH_DELAY_SECONDS=1` means ~1s between article fetches
  per source. Bump it in `.env` for polite scraping of smaller sites.

## Configuration (`.env`)

`.env` is **not committed** (contains secrets). Copy `.env.example` to `.env`
and fill in your values.

| Variable             | Default                                    | Description                                                    |
|----------------------|--------------------------------------------|----------------------------------------------------------------|
| `PORT`               | `8090`                                     | Port the HTTP extractor binds on fox                           |
| `MAX_TEXT_LENGTH`    | `4000`                                     | Max characters returned in `text` / stored in `entries.content` |
| `REQUEST_TIMEOUT`    | `15`                                       | Seconds before HTTP fetch times out                            |
| `DATABASE_URL`       | _(required)_                               | `postgresql://postgres:…@192.168.0.89:5432/mcp_news`           |
| `SOURCES_FILE`       | `sources.yaml`                             | Path to YAML inside the container                              |
| `SUMMARIES_DIR`      | `summaries`                                | Where markdown summaries are written                           |
| `FETCH_CONCURRENCY`  | `4`                                        | Reserved for future concurrency work (currently sequential)    |
| `FETCH_DELAY_SECONDS`| `1`                                        | Delay between article fetches within a source                  |
| `LLM_PROVIDER`       | `gemini`                                   | One of `claude`, `openai`, `gemini`                            |
| `LLM_MODEL`          | _(provider default)_                       | Optional model ID override                                     |
| `ANTHROPIC_API_KEY`  | —                                          | Required if `LLM_PROVIDER=claude`                              |
| `OPENAI_API_KEY`     | —                                          | Required if `LLM_PROVIDER=openai`                              |
| `GEMINI_API_KEY`     | —                                          | Required if `LLM_PROVIDER=gemini`                              |
| `LOG_LEVEL`          | `INFO`                                     | Python logging level                                           |

Restart the container after editing `.env` (cron inside re-reads it on each
job invocation, but the long-running HTTP service reads it on boot):

```bash
docker compose restart extractor
```

## Database schema

Existing tables (not managed by this repo; shared with another pipeline):

- `entries`: one row per article. `id` = article URL, `source` = from
  `sources.yaml`, `category` = from `sources.yaml`, `content` = extracted
  plain text (null on failure), `summarized_at` = null until included in a
  daily summary.
- `news_summaries`: one row per run of the summarize job. `headline` and
  `facts` contain the LLM output.

All queries are scoped to our sources by `source IN (<names from
sources.yaml>)`. The other pipeline's rows are untouched.

## Extractor HTTP API (unchanged)

`GET /extract?url=<url>` — fetch and extract a single article.

```bash
curl "http://192.168.0.89:8090/extract?url=https://example.com/article"
```

Response:

```json
{
  "url": "https://example.com/article",
  "title": "Article Title",
  "text": "Plain text body...",
  "error": null
}
```

On failure (unreachable URL, timeout, unsupported content type), returns
HTTP 200 with `error` populated and `text`/`title` as `null`. Keeps n8n
happy.

`GET /health` — returns `{"status":"ok"}`.

## Running the test suite

Unit + integration tests (real Postgres against a `jina_clone_test`
database on fox):

```bash
./.venv/bin/pytest -v
```

27 tests cover: extraction from saved HTML, RSS parsing, scrape selector,
storage CRUD, fetch orchestration, summarize orchestration, LLM response
parser.

## Troubleshooting

**`/health` refuses connection**
- `docker compose ps` — is the container running?
- `docker compose logs extractor` — crash loop?

**Fetch logs show `InvalidAuthorizationSpecificationError`**
- pg_hba.conf on fox isn't allowing the container's source IP. Confirm
  `docker-compose.yml` has `network_mode: host`.

**A source produces zero results**
- Check the discovered items in isolation. For RSS:
  `docker compose exec extractor python -c "import feedparser; print([e.link for e in feedparser.parse('URL').entries[:5]])"`
- For scrape: see "Finding the right selector" above.

**A specific site always extracts empty text**
- JS-rendered or gated content. Readability can't help; would need a
  headless browser. No fix planned here.

**Summarize job crashes**
- Check `logs/summarize.log`. Most common: expired or misconfigured API
  key — errors include `401` or `PERMISSION_DENIED`. Update `.env` and
  `docker compose restart extractor`.

## Wiring into n8n (unchanged)

n8n can still call `GET /extract?url=...` on the extractor service as
before. Use the LAN IP (`192.168.0.89`) rather than the hostname since n8n
runs inside Docker and may not resolve `fox`.
