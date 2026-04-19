from pathlib import Path

from jina_clone.briefing.renderer import render_pdf
from jina_clone.briefing.schema import Briefing


FIXTURE = Path("jina_clone/briefing/fixtures/sample_briefing.json")


def test_render_pdf_writes_valid_pdf(tmp_path):
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    out = tmp_path / "briefing.pdf"
    render_pdf(
        briefing,
        out,
        generated_at="08:11 ET",
        iso_date="2026-04-18",
    )
    assert out.exists()
    data = out.read_bytes()
    assert data.startswith(b"%PDF-")
    assert len(data) > 4096


def test_render_pdf_is_exactly_two_pages(tmp_path):
    """The briefing must render as exactly 2 letter pages, no more."""
    import pypdf
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    out = tmp_path / "briefing.pdf"
    render_pdf(briefing, out, generated_at="08:11 ET", iso_date="2026-04-18")
    reader = pypdf.PdfReader(str(out))
    assert len(reader.pages) == 2


def test_rendered_html_contains_panel_item(tmp_path):
    """The template must render each panel's `also` entries as .panel-item blocks."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    tmpl_dir = Path("jina_clone/briefing/templates")
    env = Environment(
        loader=FileSystemLoader(str(tmpl_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tmpl = env.get_template("briefing.html.j2")
    html_str = tmpl.render(
        **briefing.model_dump(),
        generated_at="08:11 ET",
        iso_date="2026-04-18",
    )
    # 4 panels × at least 3 also items = ≥ 12 .panel-item occurrences.
    assert html_str.count('class="panel-item"') >= 12
    # Ink-wasting cream background must be gone.
    assert "#fcfaf4" not in html_str


def test_rendered_html_has_no_forced_page_break(tmp_path):
    """The template must not force a page break between main content and briefs."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    tmpl_dir = Path("jina_clone/briefing/templates")
    env = Environment(
        loader=FileSystemLoader(str(tmpl_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tmpl = env.get_template("briefing.html.j2")
    html_str = tmpl.render(
        **briefing.model_dump(),
        generated_at="08:11 ET",
        iso_date="2026-04-18",
    )
    assert "page-break-after: always" not in html_str
