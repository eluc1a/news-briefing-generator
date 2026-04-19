from datetime import datetime
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
    # Should be at least a few KB — empty PDFs are smaller.
    assert len(data) > 4096


def test_render_pdf_two_pages(tmp_path):
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    out = tmp_path / "briefing.pdf"
    render_pdf(briefing, out, generated_at="08:11 ET", iso_date="2026-04-18")
    # WeasyPrint 68.1 uses FlateDecode compressed streams, so raw byte
    # patterns like "/Type /Page" are not present in plain text. Use pypdf
    # to reliably count pages regardless of compression settings.
    import pypdf
    reader = pypdf.PdfReader(str(out))
    page_count = len(reader.pages)
    # The template enforces page-break-after on the first .page div, so
    # a 2-page PDF should appear when content fits as designed.
    assert page_count >= 2
