import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from jina_clone.briefing.schema import Briefing


TEMPLATE_DIR = Path(__file__).parent / "templates"
_log = logging.getLogger(__name__)


def render_pdf(
    briefing: Briefing,
    out_path: Path,
    *,
    generated_at: str,
    iso_date: str,
) -> Path:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tmpl = env.get_template("briefing.html.j2")
    payload = briefing.model_dump()

    def _render(include_extras: bool):
        html_str = tmpl.render(
            **payload,
            generated_at=generated_at,
            iso_date=iso_date,
            include_extras=include_extras,
        )
        return HTML(string=html_str, base_url=str(TEMPLATE_DIR)).render()

    doc = _render(include_extras=True)
    if len(doc.pages) > 2:
        _log.warning(
            "briefing overflowed to %d pages with extras; re-rendering "
            "without data_point and on_this_day",
            len(doc.pages),
        )
        doc = _render(include_extras=False)
        if len(doc.pages) > 2:
            _log.warning(
                "briefing still %d pages after dropping extras; writing as-is",
                len(doc.pages),
            )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.write_pdf(str(out_path))
    return out_path
