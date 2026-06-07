import json
import logging
import re
from pathlib import Path
from typing import Callable

from jina_clone.briefing.schema import Briefing

log = logging.getLogger(__name__)

EDITION_TITLES = {"morning": "The Morning Fox", "evening": "The Evening Fox"}

# Evening prints after morning, so it is "newer" within a day.
_EDITION_ORDER = {"morning": 0, "evening": 1}
_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(morning|evening)\.json$")


def write_edition_json(
    briefing: Briefing, *, briefings_dir: Path, iso_date: str, edition: str
) -> Path:
    briefings_dir = Path(briefings_dir)
    briefings_dir.mkdir(parents=True, exist_ok=True)
    out = briefings_dir / f"{iso_date}-{edition}.json"
    out.write_text(briefing.model_dump_json(indent=2))
    return out


def rebuild_index(briefings_dir: Path) -> Path:
    """Scan the briefings dir and write a newest-first index.json.

    Rebuild-by-scan (not append) so the manifest self-heals when files
    are deleted or backfilled. Only files matching {date}-{edition}.json
    are included; index.json and anything else are ignored.
    """
    briefings_dir = Path(briefings_dir)
    entries = []
    for p in sorted(briefings_dir.glob("*.json")):
        m = _NAME_RE.match(p.name)
        if not m:
            continue
        d, edition = m.group(1), m.group(2)
        entries.append({
            "date": d,
            "edition": edition,
            "title": EDITION_TITLES[edition],
            "json": p.name,
            "pdf": f"{d}-{edition}.pdf",
        })
    entries.sort(key=lambda e: (e["date"], _EDITION_ORDER[e["edition"]]), reverse=True)
    index_path = briefings_dir / "index.json"
    index_path.write_text(json.dumps(entries, indent=2))
    return index_path


def publish_web_outputs(
    briefing: Briefing, *, briefings_dir: Path, iso_date: str, edition: str
) -> None:
    write_edition_json(briefing, briefings_dir=briefings_dir, iso_date=iso_date, edition=edition)
    rebuild_index(briefings_dir)


def make_render_and_publish(
    render_pdf: Callable[..., Path],
    *,
    briefings_dir: Path,
    edition: str,
) -> Callable[..., Path]:
    """Wrap an existing render_pdf callable so it ALSO writes the web
    JSON + manifest from the same Briefing. Web-publish failures are
    logged and swallowed — the printed paper is the primary product and
    must never be blocked by a website write.

    The returned callable matches the signature run_briefing expects for
    its `render` dependency: (briefing, pdf_path, *, generated_at, iso_date).
    """
    def render_and_publish(briefing, pdf_path, *, generated_at, iso_date):
        result = render_pdf(briefing, pdf_path, generated_at=generated_at, iso_date=iso_date)
        try:
            publish_web_outputs(
                briefing, briefings_dir=briefings_dir, iso_date=iso_date, edition=edition
            )
        except Exception as e:  # noqa: BLE001 — paper is primary; never abort on web failure
            log.warning("web publish failed (paper unaffected): %s", e)
        return result

    return render_and_publish
