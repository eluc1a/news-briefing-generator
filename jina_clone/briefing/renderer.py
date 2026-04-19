from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from jina_clone.briefing.schema import Briefing


TEMPLATE_DIR = Path(__file__).parent / "templates"


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
    html_str = tmpl.render(
        **briefing.model_dump(),
        generated_at=generated_at,
        iso_date=iso_date,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_str, base_url=str(TEMPLATE_DIR)).write_pdf(str(out_path))
    return out_path
