# Slack AI/ML Digest — Source Links Shipped, Slack Poll Stalled

**Branch:** `dev` (HEAD `6377840`)
**Date:** 2026-06-11
**Predecessor:** `docs/superpowers/handoffs/2026-06-10-slack-feed-fetch-failure-debug.md`
**Plan:** `docs/superpowers/plans/2026-06-09-ai-digest-rss-feed.md`

---

## TL;DR

Two things resolved since the predecessor handoff: (1) the Slack `/feed`
fetch failure was **client/workspace-specific** — it works from the user's
personal machine (subscription confirmed still pointing at
`https://feeds.elucia.com/ai-digest/feed.xml`). (2) The "no source links in
Slack" gap is **fixed and shipped** (commit `6377840`): the feed
`<description>` now flattens to `<p>` blocks with each source URL as bare
text, which Slack auto-links. Full suite green (161 passed). Live `feed.xml`
already serves the new format and today's morning entry.

**The one open item is entirely Slack-side and not actionable from this
repo:** Slack has **not polled the feed since 23:59 ET on Jun 10**. The
morning digest published fine at 08:45 Jun 11 and is live + valid in the
feed (confirmed via external WebFetch), but Slack hasn't fetched it, so no
new channel message has appeared. Nothing on the server is broken — every
fetch returns 200. This is Slack's RSS poll cadence (erratic/slow), to be
waited out or nudged by re-subscribing. **No code change is pending.**

---

## What was done this session

- **Diagnosed "no links in Slack":** the source URLs were always in the feed
  but lived inside `<ul>/<li><a>` markup that Slack's `/feed` unfurl strips.
  Same root cause as the missing bullets from the predecessor handoff.
- **Fixed it — commit `6377840`** "feat(digest): flatten feed description so
  source links survive Slack":
  - `jina_clone/briefing/feed.py`: added `_digest_feed_html`,
    `_fallback_feed_html`, `_record_feed_html`. `render_feed_xml` now calls
    `_record_feed_html` for the `<description>` (flat `<p>` blocks, each
    source URL printed as bare text). `render_page_html` still uses
    `_record_body_html` — **the HTML page keeps its rich linked `<ul>`**.
  - `tests/test_briefing_feed.py`: +2 tests
    (`test_feed_description_flattens_with_bare_source_urls`,
    `test_fallback_feed_description_has_bare_urls`). Full suite **161
    passed** (was 159 baseline + 2).
- **Refreshed the live feed in place** by calling `rebuild_feed()` on
  `feeds/ai-digest/` (no LLM call, no content change — re-rendered existing
  records). Live `feed.xml` now has 0 `<ul>` and bare `<br>https://…` lines.
  Feed grew 7640→9198 bytes; Slack's 23:xx polls fetched the larger
  (new-format) body, so Slack saw the change before going quiet.
- **Confirmed the pipeline ran today:** `logs/slack-digest.log` shows
  `2026-06-11 08:45:29 … published feeds/ai-digest/2026-06-11-morning.html
  (26 candidates, degraded=False)`. External WebFetch confirms the feed's
  first item is "AI/ML Morning Digest — Thu Jun 11", pubDate
  `Thu, 11 Jun 2026 08:45:02 -0400`, valid RSS 2.0.
- **Read the nginx access logs:** Slack polled every ~20 min from 22:21 to
  23:59 ET on Jun 10 (post-subscribe burst, all 200), then **zero polls on
  Jun 11** (`grep -c '11/Jun/2026.*Slackbot.*ai-digest/feed.xml'
  /var/log/nginx/access.log` → 0).
- Updated memory `project_slack_digest_rss_delivery.md` with the fix +
  pending-verification note.

---

## What is NOT done

1. **Slack has not displayed the new digest / not polled today.** Open, but
   **not a code or server problem** — the feed is healthy and serving 200s.
   Resolution is Slack-side only:
   - Wait for Slack's next poll (cadence is slow/erratic, can be hours).
   - Or in the channel, re-run `/feed subscribe
     https://feeds.elucia.com/ai-digest/feed.xml` — a fresh subscribe makes
     Slack poll within minutes, which also serves as the live test of the
     source-links fix.
   - `/feed list` already confirmed the subscription still points at the
     correct URL, so it did not silently drop.
2. **Source-links fix not yet visually verified in Slack.** The format is
   correct in the feed XML and unit-tested, but how Slack renders the bare
   URLs (clickable, not truncated after the lead) is unverifiable from fox —
   needs one real Slack render. If Slack truncates after the first block,
   the next lever is adding `<content:encoded>` alongside `<description>`
   (noted, not built).

---

## Working-tree state at handoff

- Branch `dev` at `6377840` (HEAD). **24 commits ahead of `origin/dev`, 0
  behind** — never pushed (pre-existing; not introduced here).
- Modified, uncommitted: `CLAUDE.md` (pre-existing before these sessions;
  not touched by this work).
- Untracked (intentional, do NOT `git add`):
  - `briefings/2026-06-08-test-morning.json` — runtime artifact.
  - `docs/superpowers/handoffs/2026-06-10-slack-feed-fetch-failure-debug.md`
    — predecessor handoff (also untracked).
  - This file.
- Live deployment: `feeds/ai-digest/feed.xml` regenerated in new format
  (commit `6377840`'s renderer); served by nginx at
  `https://feeds.elucia.com/ai-digest/feed.xml`.

---

## How to resume

1. **Sanity check, no changes:** `tail logs/slack-digest.log` (expect the
   08:45 / 16:30 publish lines), and
   `sudo grep -hE '1[12]/Jun/2026.*Slackbot.*ai-digest/feed.xml'
   /var/log/nginx/access.log | tail` — **if Slack has resumed polling, the
   problem self-resolved** and the digest should be in-channel.
2. **Ask the user whether the digest appeared in Slack.** If yes → done; do
   the visual check in item 2 of "What is NOT done" (links clickable?).
3. If Slack still hasn't polled and the user wants it now, have them re-run
   `/feed subscribe https://feeds.elucia.com/ai-digest/feed.xml` in the
   channel (forces a near-immediate poll).
4. Only if Slack renders the digest but the source links are missing/cut:
   build the `<content:encoded>` fallback in `jina_clone/briefing/feed.py`
   (add it next to `<description>` in `render_feed_xml`; reuse
   `_record_body_html` — the rich version — as its payload). TDD as before.

---

## Useful commands

```bash
# Verify the live feed format + today's entry (read-only)
grep -c '<ul>' feeds/ai-digest/feed.xml            # expect 0
grep -m1 '<link>https://feeds.elucia.com/ai-digest/2026' feeds/ai-digest/feed.xml

# Re-render live feed.xml from existing records (no LLM, no content change)
./.venv/bin/python - <<'PY'
import os; from pathlib import Path
from dotenv import load_dotenv
from jina_clone.briefing.feed import rebuild_feed
load_dotenv("/home/elucia/dev/jina-clone/.env")
print(rebuild_feed(Path(os.environ.get("FEED_OUTPUT_DIR") or "feeds/ai-digest"),
                   base_url=os.environ["FEED_BASE_URL"]))
PY

# See what Slack last fetched (time + bytes)
sudo grep -hE 'Slackbot.*GET /ai-digest/feed.xml' /var/log/nginx/access.log* | tail

./.venv/bin/pytest tests/test_briefing_feed.py -q   # 8 passed
```

---

## Process notes

- The server side is exhaustively confirmed healthy (local + external
  WebFetch + nginx 200s). **Do not keep debugging the feed** — every
  remaining lever is in Slack's UI or Slack's poll scheduler, which this
  repo cannot drive.
- User constraint this session: **"write a handoff doc"** — pausing here.
- The HTML page (`{date}-{edition}.html`) deliberately keeps the rich
  `<ul>` list; only the RSS `<description>` was flattened. Don't "simplify"
  by collapsing the two renderers back together.
