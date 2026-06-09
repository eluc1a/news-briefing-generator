# Slack AI/ML Digest — Design

**Date:** 2026-06-09
**Status:** Approved (brainstorming session 2026-06-09)
**Approach:** New lightweight `slack_digest` job (Approach A); `run_briefing` untouched.

## Goal

Post a twice-daily AI/ML digest to a work Slack channel: 9:00 AM and
4:45 PM America/New_York. Each update is an LLM-written 2–3 sentence
lead plus 6–10 linked items with one-line blurbs, drawn from the same
`category='ai'` articles the briefing's AI panel already uses.

## Requirements settled during brainstorming

- **Content source:** reuse existing AI-category `entries` rows in
  Postgres (the hourly fetch pipeline). No new sources, no literal
  RSS/Atom output.
- **Delivery:** Slack **incoming webhook** for v1. The user chose to
  defer the full Slack app (bot token).
- **Voting is deferred.** The original idea — 👍/👎 reactions feeding
  source weighting — requires a bot token (webhooks can't read
  reactions or learn their own message `ts`, so threading is also
  impossible). v1 keeps the poster behind a one-function seam so a
  bot-token implementation is a drop-in replacement later.
- **Format:** LLM digest + linked items (chosen over headlines-only and
  over a single narrative paragraph). Links go in the main message —
  threaded link-comments are not possible via webhook.

## Architecture

Four small additions; no existing behavior changes.

### 1. `generate_slack_digest` in `jina_clone/briefing/generator.py`

Fourth public generate function alongside `generate_front_matter`,
`generate_panel`, `generate_briefs`. Reuses the module's existing
backend resolution (`_build_default_call_llm` — `claude -p` CLI path
with the anti-agentic guard) and `_call_with_retry` (2 attempts,
error-appended re-prompt).

- Input: `articles: list[dict]`, edition name, optional
  `call_llm`/`client` injection (test seam, same as siblings).
- One LLM call. Prompt instructs: pick the best 6–10 of up to 40
  candidates, one-line blurb each, 2–3 sentence lead on the day's big
  story/theme. JSON-only output.
- Output: `SlackDigest` model (see schema below).
- Parse step validates every returned URL against the input article
  set; unknown URLs raise and trigger the standard retry. Hallucinated
  links cannot reach the channel.

### 2. `SlackDigest` / `DigestItem` models in `jina_clone/briefing/schema.py`

```python
class DigestItem(BaseModel):
    url: str
    title: str
    blurb: str

class SlackDigest(BaseModel):
    lead: str
    items: list[DigestItem]
```

### 3. `jina_clone/briefing/slack.py`

Two functions, pure formatting split from I/O:

- `format_digest(digest, *, edition_label) -> dict` — builds the
  webhook payload: mrkdwn `text` with a bold dated header
  (e.g. `*🤖 AI/ML Morning Digest — Tue Jun 9*`), the lead, then one
  bullet per item as `<url|title> — blurb`. Sets
  `unfurl_links: false` / `unfurl_media: false` so a 10-link message
  doesn't explode with previews.
- `format_headlines_fallback(articles, *, edition_label) -> dict` —
  degraded variant: linked headlines by recency, no lead/blurbs, with a
  brief "(headline fallback)" note.
- `post_webhook(url, payload) -> None` — httpx POST; raises on non-2xx.

### 4. `run_slack_digest` in `jina_clone/jobs/slack_digest.py`

Orchestrator with injected callables (same pattern as `fetch.py` /
`summarize.py` / `briefing.py`):

```
fetch_articles → generate_digest → format → post
```

Injected: `fetch_articles`, `generate_digest`, `format_digest`,
`format_fallback`, `post`, `notify_failure`.

### CLI + cron

- New subcommand: `python -m jina_clone slack-digest
  --edition=morning|afternoon`.
- Two **host-crontab** lines (where the briefing crons live, venv
  python), `TZ=America/New_York` semantics:
  - `0 9 * * *` → `--edition=morning`
  - `45 16 * * *` → `--edition=afternoon`

## Selection & windows

- Query: `fetch_section_articles(pool, categories=["ai"],
  since_hours=W, limit=40, source_caps=<from briefing config>)` — the
  exact query feeding the briefing's AI panel, including the arXiv
  clamp (`arXiv cs.AI: 2`) so the 04:00 UTC paper dump doesn't own the
  morning edition.
- **Non-overlapping windows instead of posted-URL state:**
  - morning: `W = 16.25` (covers since yesterday 16:45)
  - afternoon: `W = 7.75` (covers since 9:00 today)
  No duplicates across editions; no bookkeeping. Trade-off accepted: if
  one run fails outright, its window's articles are skipped, not
  carried forward.
- **No DB writes in v1.** No `news_summaries` row, no message records.
  When voting arrives (bot token), message-record storage is added
  alongside the poster swap.

## Configuration

- `.env`: `SLACK_WEBHOOK_URL` (secret). Added to `.env.example`.
  Validated only when the `slack-digest` subcommand runs — `fetch`,
  `summarize`, and `briefing` do not require it.
- Category is fixed to `ai`; per-source caps come from the existing
  `config/briefing_categories.yaml` `source_caps`.

## Failure handling

| Failure | Behavior |
|---|---|
| LLM fails after 2 attempts | Post `format_headlines_fallback` instead (channel still gets links) + ntfy alert noting degraded run |
| Webhook POST fails (non-2xx / network) | ntfy alert via existing `notify_failure`, same topic as briefing |
| Zero articles in window | Skip the post entirely; log; **no** ntfy (quiet afternoons are normal) |

## Testing

Existing patterns; no new DB fixtures needed.

- `generate_slack_digest`: fake `call_llm` — happy path; bad-JSON
  retry; hallucinated-URL rejection.
- `format_digest` / `format_headlines_fallback`: payload structure,
  edition labels, unfurl flags.
- `post_webhook`: httpx `MockTransport` — 200 OK, non-2xx raises.
- `run_slack_digest`: injected fakes — happy path; LLM failure →
  fallback posted + notify; zero articles → no post, no notify;
  webhook failure → notify.

Per CLAUDE.md: the implementation plan front-loads a **live E2E**
(real DB + real `claude -p` + a throwaway/test webhook) before polish.

## Out of scope (explicit)

- **Voting & feedback loop** — requires a Slack app with
  `chat:write`, `reactions:read`, `channels:history`; would add
  reaction polling before each run and a per-source weighting input to
  selection. The poster seam and (future) message records are the
  prepared integration points.
- Threaded source comments (same bot-token dependency).
- A literal RSS/Atom feed output.
- Any change to the briefing/print/web pipelines.

## User setup required

- Create the incoming webhook in the work Slack workspace, pointed at
  the team channel; put the URL in `.env` as `SLACK_WEBHOOK_URL`.
- Add the two host-crontab lines (privileged step, like the briefing
  cron switch).
