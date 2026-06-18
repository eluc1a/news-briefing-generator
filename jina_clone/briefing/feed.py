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
import shutil
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

# Edition-manifest read by the page footer's "Past editions" picker.
_INDEX_NAME = "index.json"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _entry_title(edition_label: str, date_label: str) -> str:
    return f"AI/ML {edition_label} Digest — {date_label}"


def _label_html(category: str | None) -> str:
    """Colored category chip, or "" for records predating categories.
    Category values are schema-constrained (DigestCategory), so they are
    safe to embed in the class attribute."""
    if not category:
        return ""
    return f'<span class="label label-{category}">{escape(category)}</span>'


def _source_html(source: str | None) -> str:
    if not source:
        return ""
    return f' <span class="story-source">— {escape(source)}</span>'


def _digest_body_html(digest: SlackDigest) -> str:
    lines = [f'<p class="lead">{escape(digest.lead)}</p>']
    for item in digest.items:
        lines.append(
            '<article class="story">\n'
            f'<h2 class="story-title">{_label_html(item.category)}'
            f'<a href="{_attr(item.url)}">'
            f"{escape(item.title)}</a></h2>\n"
            f'<p class="story-blurb">{escape(item.blurb)}'
            f"{_source_html(item.source)}</p>\n"
            "</article>"
        )
    return "\n".join(lines)


def _fallback_body_html(headlines: list[dict]) -> str:
    """Degraded variant for LLM failure: linked headlines, newest-first
    (input order from fetch_section_articles), capped at 10."""
    lines = ['<p class="degraded">LLM digest unavailable — headlines only.</p>']
    for art in headlines[:FALLBACK_MAX_ITEMS]:
        link = art.get("link")
        if not link:
            continue
        title = art.get("title") or link
        lines.append(
            '<article class="story">\n'
            f'<h2 class="story-title"><a href="{_attr(link)}">'
            f"{escape(title)}</a>{_source_html(art.get('source'))}</h2>\n"
            "</article>"
        )
    return "\n".join(lines)


def _record_body_html(record: dict) -> str:
    if record["degraded"]:
        return _fallback_body_html(record["headlines"])
    return _digest_body_html(SlackDigest.model_validate(record["digest"]))


# --- Feed-description rendering (Slack-friendly) -------------------------
# Slack's /feed unfurl strips list/heading markup and <a> from the
# description, so the rich markup above never reaches the channel. The
# feed body below flattens to <p> blocks and prints each source URL as
# bare text — Slack auto-links bare URLs, so the source links survive
# the strip. The HTML page keeps the rich linked markup
# (render_page_html still uses _record_body_html).


def _digest_feed_html(digest: SlackDigest) -> str:
    parts = [f"<p>{escape(digest.lead)}</p>"]
    for item in digest.items:
        # Category and source ride along as plain text — Slack strips
        # span/i markup, so [category] brackets and a plain em-dash
        # source are all that survive the unfurl.
        prefix = f"[{escape(item.category)}] " if item.category else ""
        source = f" <i>({escape(item.source)})</i>" if item.source else ""
        parts.append(
            f'<p>{prefix}<a href="{_attr(item.url)}">{escape(item.title)}</a>'
            f" — {escape(item.blurb)}{source}<br>{escape(item.url)}</p>"
        )
    return "\n".join(parts)


def _fallback_feed_html(headlines: list[dict]) -> str:
    parts = ["<p>LLM digest unavailable — headlines only.</p>"]
    for art in headlines[:FALLBACK_MAX_ITEMS]:
        link = art.get("link")
        if not link:
            continue
        title = art.get("title") or link
        source = f" <i>({escape(art['source'])})</i>" if art.get("source") else ""
        parts.append(
            f'<p><a href="{_attr(link)}">{escape(title)}</a>{source}'
            f"<br>{escape(link)}</p>"
        )
    return "\n".join(parts)


def _record_feed_html(record: dict) -> str:
    if record["degraded"]:
        return _fallback_feed_html(record["headlines"])
    return _digest_feed_html(SlackDigest.model_validate(record["digest"]))


# House style mirrors the print broadsheet (templates/briefing.html.j2):
# Bodoni Moda masthead over a double rule, uppercase letter-spaced
# dateline, Georgia body, thin rules between stories. Fonts are served
# from fonts/ next to the pages (copied at publish time); Georgia is the
# fallback if they are missing.
_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{title}</title>
<script>
// Apply the saved/system theme before first paint to avoid a flash.
(function () {{
  try {{
    var saved = localStorage.getItem("theme");
    var dark = saved
      ? saved === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (dark) document.documentElement.dataset.theme = "dark";
  }} catch (e) {{}}
}})();
</script>
<style>
@font-face {{
  font-family: 'Bodoni Moda';
  src: url('fonts/BodoniModa-Regular.ttf') format('truetype');
  font-weight: 400;
}}
@font-face {{
  font-family: 'Bodoni Moda';
  src: url('fonts/BodoniModa-Medium.ttf') format('truetype');
  font-weight: 500;
}}
@font-face {{
  font-family: 'Libre Baskerville';
  src: url('fonts/LibreBaskerville-Regular.woff2') format('woff2');
  font-weight: 400;
}}
/* Cream broadsheet palette, mirrored to a warm dark theme — same values
   as the main site (web/style.css) so the two pages match. */
:root {{
  --ink: #1a1a1a;          /* primary text + heavy rules */
  --ink-soft: #333;        /* lead/blurb secondary text */
  --muted: #777;           /* source, archive, footer */
  --meta: #555;            /* masthead dateline */
  --rule: #1a1a1a;         /* masthead double rule */
  --rule-soft: #b5b0a4;    /* story/footer hairlines, borders */
  --underline: #b5b0a4;    /* story-link underline */
  --bg: #faf8f3;           /* page backdrop */
  --paper: #faf8f3;        /* toggle + select surface */
  --btn-bg: #efe9dd;       /* broadsheet-link chip */
  --btn-bg-hover: #e7e0d2;
  --shadow: rgba(0, 0, 0, .18);
}}
:root[data-theme="dark"] {{
  --ink: #d6cfbf;
  --ink-soft: #cac4b6;
  --muted: #968f7d;
  --meta: #968f7d;
  --rule: #bcb5a4;
  --rule-soft: #3a352c;
  --underline: rgba(231, 226, 214, .4);
  --bg: #16140f;
  --paper: #1e1b15;
  --btn-bg: #26221a;
  --btn-bg-hover: #2f2a20;
  --shadow: rgba(0, 0, 0, .5);
}}
body {{ font-family: Georgia, 'Times New Roman', serif; max-width: 40rem;
       margin: 2rem auto 3rem; padding: 0 1.2rem; color: var(--ink);
       background: var(--bg); line-height: 1.45;
       transition: background-color .2s ease, color .2s ease; }}
#theme-toggle {{ position: fixed; top: 12px; right: 12px; z-index: 20;
  width: 34px; height: 34px; border-radius: 50%;
  border: 1px solid var(--rule-soft); background: var(--paper); color: var(--ink);
  font-size: 15px; line-height: 1; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 1px 3px var(--shadow);
  transition: background-color .2s ease, color .2s ease, border-color .2s ease; }}
#theme-toggle:hover {{ border-color: var(--ink); }}
.masthead {{ border-bottom: 3px double var(--rule); padding-bottom: .6rem;
            margin-bottom: 1.1rem; }}
.masthead-logo-link {{ display: block; width: fit-content;
                      margin: 0 auto .5rem; }}
.masthead-logo {{ display: block; height: 5rem; width: auto; }}
.masthead-title {{ font-family: 'Bodoni Moda', Georgia, serif;
                  font-size: 2.3rem; font-weight: 500; letter-spacing: 1px;
                  text-align: center; margin: 0; line-height: 1.1; }}
.masthead-meta {{ display: flex; justify-content: space-between;
                 font-size: .72rem; text-transform: uppercase;
                 letter-spacing: 1.2px; margin-top: .6rem; color: var(--meta); }}
.broadsheet-link {{ display: block; width: fit-content; margin: 2rem auto 0;
        font-family: 'Libre Baskerville', Georgia, serif; font-size: .7rem;
        text-transform: uppercase; letter-spacing: 1.5px;
        text-decoration: none; color: var(--ink); background: var(--btn-bg);
        border: 1px solid var(--rule-soft); padding: .34rem .8rem; border-radius: 2px; }}
.broadsheet-link:hover {{ background: var(--btn-bg-hover); border-color: var(--ink); }}
.lead {{ font-size: 1.08rem; font-style: italic; color: var(--ink-soft);
        margin: 0 0 1rem; }}
.story {{ border-top: 1px solid var(--rule-soft); padding-top: .75rem;
         margin-top: .75rem; }}
.story-title {{ font-size: 1.05rem; font-weight: 500; margin: 0 0 .25rem;
               line-height: 1.3; }}
.story-title a {{ color: inherit; text-decoration: underline;
                 text-decoration-color: var(--underline);
                 text-underline-offset: 3px; }}
.story-title a:hover {{ text-decoration-color: var(--ink); }}
.story-blurb {{ font-size: .95rem; color: var(--ink-soft); margin: 0; }}
.story-source {{ font-style: italic; font-size: .85rem; color: var(--muted); }}
.label {{ font-size: .6rem; font-weight: 400; text-transform: uppercase;
         letter-spacing: 1.2px; color: #faf8f3; border-radius: 2px;
         padding: .12rem .45rem; margin-right: .55rem;
         vertical-align: .2rem; white-space: nowrap; }}
.label-news {{ background: #8b2e2e; }}
.label-model {{ background: #2e4a8b; }}
.label-tool {{ background: #2e6b3e; }}
.label-paper {{ background: #8a6d3b; }}
.label-technique {{ background: #6b3e8b; }}
.degraded {{ color: #8a6d3b; font-style: italic; margin: 0 0 1rem; }}
.archive {{ text-align: center; margin-top: 1.6rem; color: var(--muted); }}
.archive[hidden] {{ display: none; }}
.archive-label {{ text-transform: uppercase; letter-spacing: 1px;
                 font-size: .68rem; margin-right: .5rem; }}
.archive-select {{ font-family: Georgia, 'Times New Roman', serif;
                  font-size: .8rem; color: var(--ink); background: var(--paper);
                  border: 1px solid var(--rule-soft); border-radius: 0;
                  padding: .2rem .4rem; }}
footer {{ margin-top: 2rem; font-size: .68rem; color: var(--muted);
         text-transform: uppercase; letter-spacing: 1px;
         border-top: 1px solid var(--rule-soft); padding-top: .5rem; }}
</style>
</head>
<body>
<button id="theme-toggle" type="button" aria-label="Toggle dark mode"></button>
<header class="masthead">
<a class="masthead-logo-link" href="https://themorningfox.com"><img class="masthead-logo" src="morningfox.png" alt="The Morning Fox"></a>
<h1 class="masthead-title">{masthead}</h1>
<div class="masthead-meta"><span>{edition_label} Edition</span>
<span>{date_label}</span></div>
</header>
{body}
<a class="broadsheet-link" href="https://themorningfox.com">Read the full broadsheet → themorningfox.com</a>
<nav class="archive" hidden>
<label class="archive-label" for="archive-select">Past editions</label>
<select id="archive-select" aria-label="Choose an edition"></select>
</nav>
<footer>Generated {generated_at}</footer>
<script>
(function () {{
  var current = "{current}";
  var nav = document.querySelector(".archive");
  var sel = document.getElementById("archive-select");
  fetch("index.json", {{ cache: "no-store" }})
    .then(function (r) {{ return r.ok ? r.json() : []; }})
    .then(function (list) {{
      if (!Array.isArray(list) || list.length < 2) return;
      list.forEach(function (e) {{
        var opt = document.createElement("option");
        opt.value = e.file;
        opt.textContent = e.label;
        if (e.date + "-" + e.edition === current) opt.selected = true;
        sel.appendChild(opt);
      }});
      sel.addEventListener("change", function () {{
        if (sel.value) window.location.href = sel.value;
      }});
      nav.hidden = false;
    }})
    .catch(function () {{}});
}})();
// Dark-mode toggle — the pre-paint script sets the initial theme; here we
// sync the button label and persist the reader's choice on click.
(function () {{
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  var root = document.documentElement;
  function sync(dark) {{
    btn.textContent = dark ? "☀" : "☾";   // icon of the mode a click switches TO
    btn.setAttribute("aria-pressed", String(dark));
  }}
  sync(root.dataset.theme === "dark");
  btn.addEventListener("click", function () {{
    var dark = root.dataset.theme !== "dark";
    if (dark) root.dataset.theme = "dark";
    else delete root.dataset.theme;
    try {{ localStorage.setItem("theme", dark ? "dark" : "light"); }} catch (e) {{}}
    sync(dark);
  }});
}})();
</script>
</body>
</html>
"""


def render_page_html(record: dict) -> str:
    generated = datetime.fromisoformat(record["generated_at"])
    return _PAGE_TEMPLATE.format(
        title=escape(_entry_title(record["edition_label"], record["date_label"])),
        masthead=escape(FEED_TITLE),
        edition_label=escape(record["edition_label"]),
        date_label=escape(record["date_label"]),
        body=_record_body_html(record),
        generated_at=generated.strftime("%Y-%m-%d %H:%M %Z"),
        current=f"{record['date']}-{record['edition']}",
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
            f"<description>{_cdata(_record_feed_html(rec))}</description>\n"
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
    for p in out_dir.glob("*.json"):
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


def _archive_label(record: dict) -> str:
    # "Jun 18, 2026 · Morning" — parsed from the iso date rather than
    # date_label (which omits the year), matching the main site's picker.
    y, m, d = record["date"].split("-")
    return f"{_MONTHS[int(m) - 1]} {int(d)}, {y} · {record['edition_label']}"


def rebuild_index(out_dir: Path) -> Path:
    """Scan the output dir and rewrite index.json, newest-first — the
    edition manifest the page footer's "Past editions" picker fetches.
    Rebuild-by-scan and self-healing, same pattern as rebuild_feed; only
    {date}-{edition}.json records count, so index.json/feed.xml/pages are
    ignored."""
    out_dir = Path(out_dir)
    records = []
    for p in out_dir.glob("*.json"):
        if not _NAME_RE.match(p.name):
            continue
        records.append(json.loads(p.read_text()))
    records.sort(
        key=lambda r: (r["date"], _EDITION_ORDER[r["edition"]]), reverse=True
    )
    entries = [
        {
            "file": f"{r['date']}-{r['edition']}.html",
            "date": r["date"],
            "edition": r["edition"],
            "label": _archive_label(r),
        }
        for r in records
    ]
    index_path = out_dir / _INDEX_NAME
    index_path.write_text(json.dumps(entries, indent=2))
    return index_path


def update_latest(out_dir: Path) -> Path | None:
    """Point ``latest.html`` at the newest published digest page.

    Gives a stable URL (themorningfox.com/ai → .../ai-digest/latest.html)
    that always resolves to the most recent edition. Scan-based and
    self-healing like ``rebuild_feed`` — newest by (date, edition). The
    symlink target is a bare basename so it resolves inside out_dir, and
    the swap is atomic (write temp link, then rename over). Returns the
    symlink path, or None when no digest pages exist yet."""
    out_dir = Path(out_dir)
    records = []
    for p in out_dir.glob("*.json"):
        if not _NAME_RE.match(p.name):
            continue
        records.append(json.loads(p.read_text()))
    if not records:
        return None
    records.sort(
        key=lambda r: (r["date"], _EDITION_ORDER[r["edition"]]), reverse=True
    )
    newest = records[0]
    target = f"{newest['date']}-{newest['edition']}.html"
    link = out_dir / "latest.html"
    tmp = out_dir / ".latest.html.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(target)  # relative → resolves within out_dir
    tmp.replace(link)       # atomic; no window where latest.html is missing
    return link


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


_STATIC_DIR = Path(__file__).parent / "static"
_FONT_SOURCE_DIR = _STATIC_DIR / "fonts"
_FONT_FILES = ("BodoniModa-Regular.ttf", "BodoniModa-Medium.ttf",
               "LibreBaskerville-Regular.woff2")
_LOGO_FILE = "morningfox.png"


def _ensure_fonts(out_dir: Path) -> None:
    """Copy the masthead fonts next to the pages if absent — self-healing
    like rebuild_feed, so a fresh FEED_OUTPUT_DIR works without setup.
    Missing source fonts are skipped; the page falls back to Georgia."""
    font_dir = out_dir / "fonts"
    for name in _FONT_FILES:
        src = _FONT_SOURCE_DIR / name
        dst = font_dir / name
        if src.exists() and not dst.exists():
            font_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)


def _ensure_logo(out_dir: Path) -> None:
    """Copy the masthead logo next to the pages if absent — self-healing
    like _ensure_fonts. The <img> falls back to its empty alt if missing."""
    src = _STATIC_DIR / _LOGO_FILE
    dst = out_dir / _LOGO_FILE
    if src.exists() and not dst.exists():
        shutil.copy(src, dst)


def _publish_record(record: dict, *, out_dir: Path, base_url: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _ensure_fonts(out_dir)
    _ensure_logo(out_dir)
    stem = f"{record['date']}-{record['edition']}"
    (out_dir / f"{stem}.json").write_text(json.dumps(record, indent=2))
    page_path = out_dir / f"{stem}.html"
    page_path.write_text(render_page_html(record))
    rebuild_feed(out_dir, base_url=base_url)
    rebuild_index(out_dir)
    update_latest(out_dir)
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
        {"link": a.get("link"), "title": a.get("title"),
         "source": a.get("source")}
        for a in articles
    ]
    record = _make_record(
        iso_date=iso_date, edition=edition, edition_label=edition_label,
        date_label=date_label, generated_at=generated_at,
        headlines=headlines,
    )
    return _publish_record(record, out_dir=out_dir, base_url=base_url)
