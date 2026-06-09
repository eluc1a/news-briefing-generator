"""Slack webhook formatting + posting for the AI/ML digest.

v1 is webhook-only: no threads, no reactions (webhooks can't read
reactions or learn their own message ts). `post_webhook` is the single
seam to swap for a bot-token client (chat.postMessage) when voting lands
— see the 2026-06-09 spec.
"""
import httpx

from jina_clone.briefing.schema import SlackDigest

FALLBACK_MAX_ITEMS = 10

# Order matters: & first, or we double-escape the entities we just made.
_MRKDWN_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))


def _escape(text: str) -> str:
    for ch, rep in _MRKDWN_ESCAPES:
        text = text.replace(ch, rep)
    return text


def _header(edition_label: str, date_label: str) -> str:
    return f"*🤖 AI/ML {edition_label} Digest — {date_label}*"


def format_digest(
    digest: SlackDigest, *, edition_label: str, date_label: str,
) -> dict:
    lines = [_header(edition_label, date_label), "", _escape(digest.lead), ""]
    for item in digest.items:
        lines.append(
            f"• <{_escape(item.url)}|{_escape(item.title)}>"
            f" — {_escape(item.blurb)}"
        )
    return {
        "text": "\n".join(lines),
        "unfurl_links": False,
        "unfurl_media": False,
    }


def format_headlines_fallback(
    articles: list[dict], *, edition_label: str, date_label: str,
) -> dict:
    """Degraded variant for LLM failure: linked headlines, newest-first
    (input order from fetch_section_articles), capped at 10."""
    lines = [
        _header(edition_label, date_label),
        "",
        "_LLM digest unavailable — headlines only._",
        "",
    ]
    for art in articles[:FALLBACK_MAX_ITEMS]:
        link = art.get("link")
        if not link:
            continue
        title = art.get("title") or link
        lines.append(f"• <{_escape(link)}|{_escape(title)}>")
    return {
        "text": "\n".join(lines),
        "unfurl_links": False,
        "unfurl_media": False,
    }


def post_webhook(url: str, payload: dict) -> None:
    response = httpx.post(url, json=payload, timeout=15)
    response.raise_for_status()
