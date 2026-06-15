import json
from pathlib import Path

from jina_clone.briefing.schema import Briefing
from jina_clone.briefing.web import publish_web_outputs, rebuild_index

FIXTURE = Path(__file__).parent.parent / "jina_clone" / "briefing" / "fixtures" / "sample_briefing.json"


def _briefing() -> Briefing:
    return Briefing.model_validate_json(FIXTURE.read_text())


def test_publish_writes_edition_json(tmp_path):
    b = _briefing()
    publish_web_outputs(b, briefings_dir=tmp_path, iso_date="2026-06-05", edition="morning")

    out = tmp_path / "2026-06-05-morning.json"
    assert out.exists()
    # Round-trips back into a Briefing (byte-for-byte structured, not lossy).
    assert Briefing.model_validate_json(out.read_text()).title == b.title


def test_index_is_newest_first(tmp_path):
    b = _briefing()
    publish_web_outputs(b, briefings_dir=tmp_path, iso_date="2026-06-04", edition="morning")
    publish_web_outputs(b, briefings_dir=tmp_path, iso_date="2026-06-05", edition="morning")
    publish_web_outputs(b, briefings_dir=tmp_path, iso_date="2026-06-05", edition="evening")

    index = json.loads((tmp_path / "index.json").read_text())
    assert [(e["date"], e["edition"]) for e in index] == [
        ("2026-06-05", "evening"),
        ("2026-06-05", "morning"),
        ("2026-06-04", "morning"),
    ]
    top = index[0]
    assert top["json"] == "2026-06-05-evening.json"
    assert top["pdf"] == "2026-06-05-evening.pdf"
    assert top["title"] == "The Evening Fox"


def test_rebuild_index_ignores_unrelated_and_self(tmp_path):
    (tmp_path / "index.json").write_text("[]")
    (tmp_path / "notes.json").write_text("{}")
    (tmp_path / "2026-06-05-morning.json").write_text("{}")
    rebuild_index(tmp_path)

    index = json.loads((tmp_path / "index.json").read_text())
    assert [e["json"] for e in index] == ["2026-06-05-morning.json"]


from jina_clone.briefing.web import make_render_and_publish


def test_render_wrapper_publishes_and_returns_pdf(tmp_path):
    b = _briefing()
    calls = {}

    def fake_render(briefing, pdf_path, *, generated_at, iso_date):
        calls["pdf_path"] = pdf_path
        return pdf_path

    wrapper = make_render_and_publish(fake_render, briefings_dir=tmp_path, edition="morning")
    pdf = tmp_path / "2026-06-05-morning.pdf"
    result = wrapper(b, pdf, generated_at="08:10 ET", iso_date="2026-06-05")

    assert result == pdf
    assert calls["pdf_path"] == pdf
    assert (tmp_path / "2026-06-05-morning.json").exists()
    assert (tmp_path / "index.json").exists()


def test_render_wrapper_swallows_publish_failure(tmp_path):
    b = _briefing()
    sentinel = tmp_path / "out.pdf"

    def fake_render(briefing, pdf_path, *, generated_at, iso_date):
        return sentinel

    # Point publish at a path that cannot be created (a file used as a dir).
    bad = tmp_path / "afile"
    bad.write_text("x")
    wrapper = make_render_and_publish(fake_render, briefings_dir=bad, edition="morning")

    # Must NOT raise — returns the render result regardless.
    result = wrapper(b, sentinel, generated_at="08:10 ET", iso_date="2026-06-05")
    assert result == sentinel


from jina_clone.briefing.web import make_render_and_save_json


def test_save_json_wrapper_writes_edition_json_only(tmp_path):
    b = _briefing()
    calls = {}

    def fake_render(briefing, pdf_path, *, generated_at, iso_date):
        calls["pdf_path"] = pdf_path
        return pdf_path

    wrapper = make_render_and_save_json(fake_render, briefings_dir=tmp_path, edition="morning")
    pdf = tmp_path / "2026-06-05-morning.pdf"
    result = wrapper(b, pdf, generated_at="08:10 ET", iso_date="2026-06-05")

    assert result == pdf
    assert calls["pdf_path"] == pdf
    # Edition JSON IS written; index.json is NOT (that is the publish step's job).
    assert (tmp_path / "2026-06-05-morning.json").exists()
    assert not (tmp_path / "index.json").exists()


def test_save_json_wrapper_swallows_write_failure(tmp_path):
    b = _briefing()
    sentinel = tmp_path / "out.pdf"

    def fake_render(briefing, pdf_path, *, generated_at, iso_date):
        return sentinel

    bad = tmp_path / "afile"   # a file used as a dir → write_edition_json raises
    bad.write_text("x")
    wrapper = make_render_and_save_json(fake_render, briefings_dir=bad, edition="morning")

    result = wrapper(b, sentinel, generated_at="08:10 ET", iso_date="2026-06-05")
    assert result == sentinel   # must NOT raise; render result still returned


def test_save_json_wrapper_propagates_render_failure(tmp_path):
    b = _briefing()

    def boom(briefing, pdf_path, *, generated_at, iso_date):
        raise RuntimeError("render exploded")

    wrapper = make_render_and_save_json(boom, briefings_dir=tmp_path, edition="morning")
    pdf = tmp_path / "x.pdf"
    try:
        wrapper(b, pdf, generated_at="08:10 ET", iso_date="2026-06-05")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "render exploded" in str(e)
