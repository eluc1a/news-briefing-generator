"""RSS feed + HTML page publishing for the AI/ML digest.

Delivery is a public RSS 2.0 feed polled by Slack's first-party /feed
app (the work workspace allows no app installs, so webhooks and bot
tokens are out). One feed entry per edition, linking to a standalone
HTML page. feed.xml is rebuilt by scanning {date}-{edition}.json
records — rebuild-by-scan self-heals, same pattern as
web.rebuild_index. See
docs/superpowers/specs/2026-06-09-ai-digest-rss-feed-design.md.
"""
import json
import re
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from jina_clone.briefing.schema import SlackDigest

FALLBACK_MAX_ITEMS = 10
FEED_MAX_ENTRIES = 20
FEED_TITLE = "AI/ML Digest"
FEED_DESCRIPTION = "Twice-daily LLM digest of AI/ML news, papers, and tools."

# Afternoon publishes after morning, so it is "newer" within a day.
_EDITION_ORDER = {"morning": 0, "afternoon": 1}
_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(morning|afternoon)\.json$")


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _entry_title(edition_label: str, date_label: str) -> str:
    return f"AI/ML {edition_label} Digest — {date_label}"


def _digest_body_html(digest: SlackDigest) -> str:
    lines = [f'<p class="lead">{escape(digest.lead)}</p>', "<ul>"]
    for item in digest.items:
        lines.append(
            f'<li><a href="{_attr(item.url)}">{escape(item.title)}</a>'
            f" — {escape(item.blurb)}</li>"
        )
    lines.append("</ul>")
    return "\n".join(lines)


def _fallback_body_html(headlines: list[dict]) -> str:
    """Degraded variant for LLM failure: linked headlines, newest-first
    (input order from fetch_section_articles), capped at 10."""
    lines = [
        '<p class="degraded">LLM digest unavailable — headlines only.</p>',
        "<ul>",
    ]
    for art in headlines[:FALLBACK_MAX_ITEMS]:
        link = art.get("link")
        if not link:
            continue
        title = art.get("title") or link
        lines.append(f'<li><a href="{_attr(link)}">{escape(title)}</a></li>')
    lines.append("</ul>")
    return "\n".join(lines)


def _record_body_html(record: dict) -> str:
    if record["degraded"]:
        return _fallback_body_html(record["headlines"])
    return _digest_body_html(SlackDigest.model_validate(record["digest"]))


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: Georgia, serif; max-width: 42rem; margin: 2rem auto;
       padding: 0 1rem; color: #1a1a1a; }}
h1 {{ font-size: 1.4rem; border-bottom: 2px solid #1a1a1a;
     padding-bottom: .4rem; }}
.lead {{ font-size: 1.05rem; }}
li {{ margin: .6rem 0; }}
.degraded {{ color: #8a6d3b; font-style: italic; }}
footer {{ margin-top: 2rem; font-size: .8rem; color: #777; }}
</style>
</head>
<body>
<h1>{title}</h1>
{body}
<footer>Generated {generated_at}</footer>
</body>
</html>
"""


def render_page_html(record: dict) -> str:
    generated = datetime.fromisoformat(record["generated_at"])
    return _PAGE_TEMPLATE.format(
        title=escape(_entry_title(record["edition_label"], record["date_label"])),
        body=_record_body_html(record),
        generated_at=generated.strftime("%Y-%m-%d %H:%M %Z"),
    )


def _cdata(html: str) -> str:
    # Body text is already XML-escaped, so "]]>" can't occur — this is
    # a guard against future markup changes, not a live path.
    return "<![CDATA[" + html.replace("]]>", "]]&gt;") + "]]>"


def render_feed_xml(records: list[dict], *, base_url: str) -> str:
    """records must be newest-first and already capped."""
    items = []
    for rec in records:
        page_url = f"{base_url}/{rec['date']}-{rec['edition']}.html"
        pub = format_datetime(datetime.fromisoformat(rec["generated_at"]))
        items.append(
            "<item>\n"
            f"<title>{escape(_entry_title(rec['edition_label'], rec['date_label']))}</title>\n"
            f"<link>{escape(page_url)}</link>\n"
            f'<guid isPermaLink="true">{escape(page_url)}</guid>\n'
            f"<pubDate>{pub}</pubDate>\n"
            f"<description>{_cdata(_record_body_html(rec))}</description>\n"
            "</item>"
        )
    joined = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "<channel>\n"
        f"<title>{escape(FEED_TITLE)}</title>\n"
        f"<link>{escape(base_url)}/</link>\n"
        f"<description>{escape(FEED_DESCRIPTION)}</description>\n"
        f"{joined}\n"
        "</channel>\n"
        "</rss>\n"
    )


def rebuild_feed(out_dir: Path, *, base_url: str) -> Path:
    """Scan the output dir and rewrite feed.xml, newest-first, capped
    at FEED_MAX_ENTRIES. Only {date}-{edition}.json records count;
    feed.xml, HTML pages, and anything else are ignored."""
    out_dir = Path(out_dir)
    records = []
    for p in sorted(out_dir.glob("*.json")):
        if not _NAME_RE.match(p.name):
            continue
        records.append(json.loads(p.read_text()))
    records.sort(
        key=lambda r: (r["date"], _EDITION_ORDER[r["edition"]]), reverse=True
    )
    records = records[:FEED_MAX_ENTRIES]
    feed_path = out_dir / "feed.xml"
    feed_path.write_text(render_feed_xml(records, base_url=base_url.rstrip("/")))
    return feed_path


def _make_record(
    *, iso_date: str, edition: str, edition_label: str, date_label: str,
    generated_at: datetime, digest: SlackDigest | None = None,
    headlines: list[dict] | None = None,
) -> dict:
    return {
        "date": iso_date,
        "edition": edition,
        "edition_label": edition_label,
        "date_label": date_label,
        "generated_at": generated_at.isoformat(),
        "degraded": digest is None,
        "digest": digest.model_dump() if digest else None,
        "headlines": headlines,
    }


def _publish_record(record: dict, *, out_dir: Path, base_url: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{record['date']}-{record['edition']}"
    (out_dir / f"{stem}.json").write_text(json.dumps(record, indent=2))
    page_path = out_dir / f"{stem}.html"
    page_path.write_text(render_page_html(record))
    rebuild_feed(out_dir, base_url=base_url)
    return page_path


def publish_digest(
    digest: SlackDigest, *, out_dir: Path, base_url: str, iso_date: str,
    edition: str, edition_label: str, date_label: str,
    generated_at: datetime,
) -> Path:
    record = _make_record(
        iso_date=iso_date, edition=edition, edition_label=edition_label,
        date_label=date_label, generated_at=generated_at, digest=digest,
    )
    return _publish_record(record, out_dir=out_dir, base_url=base_url)


def publish_fallback(
    articles: list[dict], *, out_dir: Path, base_url: str, iso_date: str,
    edition: str, edition_label: str, date_label: str,
    generated_at: datetime,
) -> Path:
    headlines = [
        {"link": a.get("link"), "title": a.get("title")} for a in articles
    ]
    record = _make_record(
        iso_date=iso_date, edition=edition, edition_label=edition_label,
        date_label=date_label, generated_at=generated_at,
        headlines=headlines,
    )
    return _publish_record(record, out_dir=out_dir, base_url=base_url)
