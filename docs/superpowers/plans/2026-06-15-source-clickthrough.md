# Click-through to Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-item source links to the themorningfox.com web edition so the lead, every panel lede, every panel `also` item, and every brief link out to the article(s) they were synthesized from.

**Architecture:** The article URLs are already fed into every LLM prompt (`_format_article` emits `Link:`). We extend the existing "echo a URL, validate it against the real input set, resolve the outlet name ourselves" pattern (already used by `FrontMatter.lead_source_url` and `DigestItem`) to every synthesized item. The public schema carries a `sources: list[Source]` field (multi-source-ready), but in this build the generator emits exactly one validated primary source per item. The web frontend renders 0 sources as plain text, 1 as a link, 2+ as a tap-to-open popover. PDF, DB, and job orchestration are untouched.

**Tech Stack:** Python 3 / pydantic / pytest (real Postgres `jina_clone_test`), vanilla JS + CSS for `web/`. Use the venv: `./.venv/bin/python`, `./.venv/bin/pytest`.

**Spec:** `docs/superpowers/specs/2026-06-15-source-clickthrough-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `jina_clone/briefing/schema.py` | public/serialized models | add `Source`; add `sources`/`lede_sources` to `LeadStory`, `PanelItem`, `Panel`, `Brief` |
| `jina_clone/briefing/generator.py` | LLM calls + validation | internal draft models, prompt rules, URL validation, outlet resolution |
| `web/app.js` | web rendering | `sourcePopover`/`linkifyHeadline`/`trailingAffordance` helpers + wiring + dismissal |
| `web/style.css` | web styling | link, count, and popover styles |
| `tests/test_briefing_schema.py` | schema tests | legacy-compat (no `sources`) test |
| `tests/test_briefing_generator.py` | generator tests | resolution + anti-hallucination tests |

Untouched: `renderer.py`, `storage/db.py`, `jobs/briefing.py`, `briefing/web.py`.

---

## Task 1: Schema — `Source` model and `sources` fields

**Files:**
- Modify: `jina_clone/briefing/schema.py`
- Test: `tests/test_briefing_schema.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_briefing_schema.py`:

```python
def test_legacy_briefing_without_sources_validates():
    # Editions published before this feature have no `sources` keys.
    # They must still validate and default to empty lists.
    from pathlib import Path
    import json
    from jina_clone.briefing.schema import Briefing

    data = json.loads(Path("jina_clone/briefing/fixtures/sample_briefing.json").read_text())
    # Ensure the fixture truly lacks sources (defensive — strip if present).
    data["lead"].pop("sources", None)
    for p in data["panels"]:
        p.pop("lede_sources", None)
        for a in p["also"]:
            a.pop("sources", None)
    for b in data["briefs"]:
        b.pop("sources", None)

    briefing = Briefing.model_validate(data)
    assert briefing.lead.sources == []
    assert briefing.panels[0].lede_sources == []
    assert briefing.panels[0].also[0].sources == []
    assert briefing.briefs[0].sources == []


def test_source_model_roundtrips():
    from jina_clone.briefing.schema import Source
    s = Source(url="https://example.com/a", source="Reuters")
    assert s.model_dump() == {"url": "https://example.com/a", "source": "Reuters"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_briefing_schema.py::test_source_model_roundtrips -v`
Expected: FAIL with `ImportError: cannot import name 'Source'`

- [ ] **Step 3: Add the `Source` model and `sources` fields**

In `jina_clone/briefing/schema.py`, add the `Source` model above `LeadStory`:

```python
class Source(BaseModel):
    url: str
    source: str   # outlet name, resolved from the input article — never from the LLM
```

Then add the field to four existing models (use `default_factory=list` so legacy JSON validates):

```python
class LeadStory(BaseModel):
    headline: str
    deck: str
    body: str
    at_a_glance: list[str] = Field(min_length=3, max_length=4)
    sources: list[Source] = Field(default_factory=list)


class PanelItem(BaseModel):
    headline: str
    body: str
    sources: list[Source] = Field(default_factory=list)


class Panel(BaseModel):
    section: Literal[
        "AI & Technology",
        "National",
        "Economy & Markets",
        "International",
    ]
    lede_headline: str
    lede_body: str
    lede_sources: list[Source] = Field(default_factory=list)
    also: list[PanelItem] = Field(min_length=PANEL_ALSO_COUNT, max_length=PANEL_ALSO_COUNT)


class Brief(BaseModel):
    topic: str
    body: str
    sources: list[Source] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_briefing_schema.py -v`
Expected: PASS (all, including the two new tests)

- [ ] **Step 5: Commit**

```bash
git add jina_clone/briefing/schema.py tests/test_briefing_schema.py
git commit -m "feat(briefing): add Source model and sources fields to schema

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Generator — resolve the lead's source

The lead already echoes and validates `lead_source_url` (`generator.py:617-625`). We only need to resolve it to an outlet and attach it as `lead.sources`. No prompt change, no draft model.

**Files:**
- Modify: `jina_clone/briefing/generator.py` (`generate_front_matter`, ~line 600-631; imports ~line 13)
- Test: `tests/test_briefing_generator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_briefing_generator.py` (the `_articles()` helper there already gives `https://a` → source `S1`):

```python
async def test_front_matter_resolves_lead_source():
    async def fake(client, prompt: str) -> str:
        return _front_matter_payload("https://a")

    fm = await generate_front_matter(
        articles=_articles(), weather=WEATHER,
        today="Sat", volume="Vol", title="The Morning Fox",
        call_llm=fake, client=None,
    )
    assert len(fm.lead.sources) == 1
    assert fm.lead.sources[0].url == "https://a"
    assert fm.lead.sources[0].source == "S1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_briefing_generator.py::test_front_matter_resolves_lead_source -v`
Expected: FAIL — `assert len(fm.lead.sources) == 1` (it is 0)

- [ ] **Step 3: Resolve and attach in `generate_front_matter`**

In `jina_clone/briefing/generator.py`, add `Source` to the schema import (line 13-15):

```python
from jina_clone.briefing.schema import (
    Brief, BRIEFS_COUNT_MAX, BRIEFS_COUNT_MIN, FrontMatter, Panel,
    SlackDigest, Source,
)
```

In `generate_front_matter`, after `valid_urls = {a.get("link") for a in articles}` add a resolution map, and set the lead's sources inside `parse`:

```python
    valid_urls = {a.get("link") for a in articles}
    source_by_url = {a.get("link"): a.get("source") for a in articles}

    def parse(raw: str) -> FrontMatter:
        fm = FrontMatter.model_validate_json(raw)
        if fm.lead_source_url not in valid_urls:
            raise ValueError(
                f"lead_source_url {fm.lead_source_url!r} not in input article links"
            )
        fm.lead.sources = [
            Source(url=fm.lead_source_url,
                   source=source_by_url.get(fm.lead_source_url) or "?")
        ]
        return fm
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_briefing_generator.py -k front_matter -v`
Expected: PASS (new test plus all existing front-matter tests)

- [ ] **Step 5: Commit**

```bash
git add jina_clone/briefing/generator.py tests/test_briefing_generator.py
git commit -m "feat(briefing): resolve lead source url to outlet on the lead

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Generator — panel and brief source attribution

Panels and briefs currently validate straight into the public `Panel` / `Brief` models. Introduce internal draft models that carry a `source_url` per item, instruct the LLM to emit it, validate every URL against the input set (driving the existing retry loop), and map drafts → public models with resolved outlets.

**Files:**
- Modify: `jina_clone/briefing/generator.py` — `PANEL_STRUCTURE_RULES` (~143), `BRIEFS_STRUCTURE_RULES` (~206), `_build_panel_user_msg` (~355), `_BriefsResponse` (~372), `_build_briefs_user_msg` (~378), `generate_panel` (~634), `generate_briefs` (~656)
- Test: `tests/test_briefing_generator.py`

- [ ] **Step 1: Update the shared payload helpers, then write the failing tests**

First update the two existing helpers (lines 43-49) so they emit draft-shaped JSON with `source_url`. Default the URLs to `"https://b"` (the article that survives the `exclude_urls={"https://a"}` filter test), and parameterize them for the resolution tests:

```python
def _panel_payload(section: str = "National",
                   lede_url: str = "https://b", also_url: str = "https://b") -> str:
    panel = next(p for p in GOOD_BRIEFING["panels"] if p["section"] == section)
    out = {
        "section": panel["section"],
        "lede_headline": panel["lede_headline"],
        "lede_body": panel["lede_body"],
        "lede_source_url": lede_url,
        "also": [
            {"headline": a["headline"], "body": a["body"], "source_url": also_url}
            for a in panel["also"]
        ],
    }
    return json.dumps(out)


def _briefs_payload(url: str = "https://b") -> str:
    out = {"briefs": [
        {"topic": b["topic"], "body": b["body"], "source_url": url}
        for b in GOOD_BRIEFING["briefs"]
    ]}
    return json.dumps(out)
```

(The existing `test_generate_panel_happy_path`, `test_generate_panel_filters_exclude_urls`,
and `test_generate_briefs_happy_path` call these with no args; defaulting to
`https://b` keeps them valid — `https://b` is always in the input and survives the
exclude-`https://a` filter test.)

Then add the new resolution + rejection tests. Reuse the module-level
`NATIONAL_SECTION` constant already defined in this file (do **not** build a new
`SectionDef` — it requires `limit=` and a tuple `categories`):

```python
async def test_panel_resolves_sources():
    async def fake(client, prompt: str) -> str:
        return _panel_payload(lede_url="https://a", also_url="https://b")

    panel = await generate_panel(
        section=NATIONAL_SECTION, articles=_articles(), exclude_urls=set(),
        title="The Morning Fox", call_llm=fake, client=None,
    )
    assert panel.lede_sources[0].url == "https://a"
    assert panel.lede_sources[0].source == "S1"
    assert all(it.sources[0].url == "https://b" for it in panel.also)
    assert all(it.sources[0].source == "S2" for it in panel.also)


async def test_panel_rejects_unknown_source_url():
    async def fake(client, prompt: str) -> str:
        return _panel_payload(lede_url="https://not-in-input")

    with pytest.raises(GeneratorFailure):
        await generate_panel(
            section=NATIONAL_SECTION, articles=_articles(), exclude_urls=set(),
            title="The Morning Fox", call_llm=fake, client=None,
        )


async def test_briefs_resolves_sources():
    async def fake(client, prompt: str) -> str:
        return _briefs_payload("https://b")

    briefs = await generate_briefs(
        articles=_articles(), exclude_urls=set(),
        title="The Morning Fox", call_llm=fake, client=None,
    )
    assert all(b.sources[0].url == "https://b" for b in briefs)
    assert all(b.sources[0].source == "S2" for b in briefs)


async def test_briefs_rejects_unknown_source_url():
    async def fake(client, prompt: str) -> str:
        return _briefs_payload("https://not-in-input")

    with pytest.raises(GeneratorFailure):
        await generate_briefs(
            articles=_articles(), exclude_urls=set(),
            title="The Morning Fox", call_llm=fake, client=None,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_briefing_generator.py -k "panel_resolves or briefs_resolves" -v`
Expected: FAIL — `_panel_payload`/`_briefs_payload` now carry `source_url`, but `generate_panel`/`generate_briefs` still parse into the public models and ignore it, so `sources`/`lede_sources` are empty.

- [ ] **Step 3a: Add draft models and update the briefs response model**

In `jina_clone/briefing/generator.py`, add draft models (near `_BriefsResponse`, ~line 372). The draft `section` is a plain `str`; the public `Panel` re-validates the Literal when constructed:

```python
class _PanelItemDraft(BaseModel):
    headline: str
    body: str
    source_url: str


class _PanelDraft(BaseModel):
    section: str
    lede_headline: str
    lede_body: str
    lede_source_url: str
    also: list[_PanelItemDraft] = Field(
        min_length=PANEL_ALSO_COUNT, max_length=PANEL_ALSO_COUNT,
    )


class _BriefDraft(BaseModel):
    topic: str
    body: str
    source_url: str
```

Add `PANEL_ALSO_COUNT` to the schema import (line 13-15):

```python
from jina_clone.briefing.schema import (
    Brief, BRIEFS_COUNT_MAX, BRIEFS_COUNT_MIN, FrontMatter, Panel, PanelItem,
    PANEL_ALSO_COUNT, SlackDigest, Source,
)
```

Replace the existing `_BriefsResponse` (currently `briefs: list[Brief]`) with the draft version:

```python
class _BriefsResponse(BaseModel):
    briefs: list[_BriefDraft] = Field(
        min_length=BRIEFS_COUNT_MIN, max_length=BRIEFS_COUNT_MAX,
    )
```

- [ ] **Step 3b: Add the `source_url` prompt rules**

In `PANEL_STRUCTURE_RULES`, change the `also` body bullet to also require a `source_url`, and add a `lede_source_url` rule. Append these lines to the structure block (after the `also` description, before the "Never fabricate" line):

```python
# Inserted into PANEL_STRUCTURE_RULES:
- lede_source_url: EXACTLY the `Link` value of the input article the lede
  is based on. It MUST match one of the input `Link` values verbatim — a
  hallucinated or altered URL will cause the panel to be rejected.
- Each `also` item additionally has:
    - source_url: EXACTLY the `Link` of the input article that item is
      primarily based on, verbatim. Same rule — must match an input Link.
```

In `BRIEFS_STRUCTURE_RULES`, add a `source_url` field to each entry. Change the entry description to include:

```python
# Inserted into BRIEFS_STRUCTURE_RULES (per-entry):
  - source_url: EXACTLY the `Link` of the input article this brief is
    based on, verbatim. It MUST match one of the input `Link` values — a
    hallucinated URL will cause the briefs to be rejected.
```

- [ ] **Step 3c: Show the draft schema to the LLM**

In `_build_panel_user_msg`, change the dumped schema from `Panel` to `_PanelDraft`:

```python
    parts.append(json.dumps(_PanelDraft.model_json_schema(), indent=2))
```

`_build_briefs_user_msg` already dumps `_BriefsResponse.model_json_schema()`, which now includes `source_url` automatically — no change needed there.

- [ ] **Step 3d: Validate and resolve in `generate_panel`**

Replace the body of `generate_panel` (from `filtered = ...` onward) with:

```python
    filtered = _filter_excluded(articles, exclude_urls)
    user_msg = _build_panel_user_msg(section=section, articles=filtered)
    valid_urls = {a.get("link") for a in filtered}
    source_by_url = {a.get("link"): a.get("source") for a in filtered}

    def _src(url: str) -> list[Source]:
        return [Source(url=url, source=source_by_url.get(url) or "?")]

    def parse(raw: str) -> Panel:
        draft = _PanelDraft.model_validate_json(raw)
        urls = [draft.lede_source_url] + [it.source_url for it in draft.also]
        for u in urls:
            if u not in valid_urls:
                raise ValueError(f"source_url {u!r} not in input article links")
        return Panel(
            section=draft.section,
            lede_headline=draft.lede_headline,
            lede_body=draft.lede_body,
            lede_sources=_src(draft.lede_source_url),
            also=[
                PanelItem(headline=it.headline, body=it.body,
                          sources=_src(it.source_url))
                for it in draft.also
            ],
        )

    return await _call_with_retry(
        call_llm=call_llm, client=client,
        user_msg=user_msg,
        parse=parse,
    )
```

- [ ] **Step 3e: Validate and resolve in `generate_briefs`**

Replace the `parse` in `generate_briefs` (and add the resolution maps from `filtered`):

```python
    filtered = _filter_excluded(articles, exclude_urls)
    user_msg = _build_briefs_user_msg(articles=filtered)
    valid_urls = {a.get("link") for a in filtered}
    source_by_url = {a.get("link"): a.get("source") for a in filtered}

    def parse(raw: str) -> list[Brief]:
        resp = _BriefsResponse.model_validate_json(raw)
        out: list[Brief] = []
        for d in resp.briefs:
            if d.source_url not in valid_urls:
                raise ValueError(
                    f"source_url {d.source_url!r} not in input article links"
                )
            out.append(Brief(
                topic=d.topic, body=d.body,
                sources=[Source(url=d.source_url,
                                source=source_by_url.get(d.source_url) or "?")],
            ))
        return out

    return await _call_with_retry(
        call_llm=call_llm, client=client,
        user_msg=user_msg,
        parse=parse,
    )
```

- [ ] **Step 4: Run the full generator suite**

Run: `./.venv/bin/pytest tests/test_briefing_generator.py -v`
Expected: PASS (new resolution + rejection tests, and all existing tests). If an existing panel/briefs test fed a payload without `source_url`, update that payload to use the `_panel_draft_payload`/`_briefs_draft_payload` helpers.

- [ ] **Step 5: Commit**

```bash
git add jina_clone/briefing/generator.py tests/test_briefing_generator.py
git commit -m "feat(briefing): validate and resolve per-item source urls for panels and briefs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Live E2E verification (checkpoint — no code)

Per CLAUDE.md: run a real generation before building the web rendering on top of it. This confirms the live LLM actually emits matching `source_url`s (not just fixtures) and that attribution is plausible. **Do not start Task 5 until this passes.**

**Files:** none (verification only).

- [ ] **Step 1: Generate a real edition (no print, no DB row)**

Run: `./.venv/bin/python -m jina_clone briefing generate --out /tmp/src-check.json`
Expected: exits 0; writes `/tmp/src-check.json`. (If it fails on too-few-articles, retry at a busier hour or widen the window — this is environmental, not a code defect.)

- [ ] **Step 2: Confirm every item has a resolved source**

Run:

```bash
./.venv/bin/python - <<'PY'
import json
b = json.load(open("/tmp/src-check.json"))
def show(label, srcs):
    print(label, "->", [(s["source"], s["url"][:60]) for s in srcs])
show("lead", b["lead"]["sources"])
for p in b["panels"]:
    show(f"panel[{p['section']}].lede", p["lede_sources"])
    for i, a in enumerate(p["also"]):
        show(f"  also[{i}] {a['headline'][:30]!r}", a["sources"])
for i, br in enumerate(b["briefs"]):
    show(f"brief[{i}] {br['topic']}", br["sources"])
PY
```

Expected: every line shows exactly one `(outlet, url)` pair; no empty lists; no `?` outlets.

- [ ] **Step 3: Eyeball attribution plausibility**

For 3-4 spot-checked items, open the printed URL and confirm the article actually matches the synthesized headline/body. This is the gate for whether multi-source generation (Phase 2) is worth pursuing later. Note findings in the commit message of Task 5 or a handoff; no code change here.

- [ ] **Step 4: Decision checkpoint**

If single-source attribution is accurate → proceed to Task 5. If URLs are systematically mismatched (LLM picking wrong articles), stop and revisit prompts in Task 3 before building the UI.

---

## Task 5: Web rendering — links and popover

Render the resolved sources: 0 → plain, 1 → link, 2+ → tap-to-open popover (hover as a desktop-only enhancement). Headline items (lead, panel lede, `also`) get the headline linkified; briefs (no headline) get a trailing affordance after the body.

**Files:**
- Modify: `web/app.js` — add helpers; wire into `renderLead`, `renderPanels`, `renderBriefs`; add dismissal in `main`
- Modify: `web/style.css` — link, count, popover styles

There is no JS test harness in this repo; verification is manual in a browser (Step 4).

- [ ] **Step 1: Add the source helpers to `web/app.js`**

Add after the `el` helper (top of file):

```javascript
function srcAnchor(s, text) {
  const a = el("a", "src-link", text);
  a.href = s.url;
  a.target = "_blank";
  a.rel = "noopener";
  return a;
}

// Count chip + popover listing each source. Tap toggles; hover opens on
// desktop via CSS. Returns a <span class="src-multi">.
function sourcePopover(sources) {
  const wrap = el("span", "src-multi");
  const count = el("button", "src-count", String(sources.length));
  count.type = "button";
  count.setAttribute("aria-label", `${sources.length} sources`);
  const pop = el("div", "src-popover");
  for (const s of sources) pop.append(srcAnchor(s, `${s.source} ↗`));
  count.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    wrap.classList.toggle("open");
  });
  wrap.append(count, pop);
  return wrap;
}

// Headline items: make the headline the link (1 src) or append the
// popover (2+). Mutates and returns headlineEl.
function linkifyHeadline(headlineEl, sources) {
  if (!sources || sources.length === 0) return headlineEl;
  if (sources.length === 1) {
    const text = headlineEl.textContent;
    headlineEl.textContent = "";
    headlineEl.append(srcAnchor(sources[0], text));
    const credit = el("span", "src-credit", ` ${sources[0].source}`);
    headlineEl.append(credit);
    return headlineEl;
  }
  headlineEl.append(document.createTextNode(" "));
  headlineEl.append(sourcePopover(sources));
  return headlineEl;
}

// Briefs (no headline): an element to append after the body.
function trailingAffordance(sources) {
  if (!sources || sources.length === 0) return null;
  if (sources.length === 1) return srcAnchor(sources[0], ` — ${sources[0].source} ↗`);
  const span = el("span", null, " ");
  span.append(sourcePopover(sources));
  return span;
}
```

- [ ] **Step 2: Wire into `renderLead`**

In `renderLead`, replace the headline append:

```javascript
function renderLead(b) {
  const s = section("lead");
  const h = el("h2", "lead-headline", b.lead.headline);
  linkifyHeadline(h, b.lead.sources);
  s.append(h);
  s.append(el("p", "lead-deck", b.lead.deck));
  s.append(el("p", "lead-body", b.lead.body));
  const ul = el("ul", "at-a-glance");
  for (const g of b.lead.at_a_glance) ul.append(el("li", null, g));
  s.append(ul);
  return s;
}
```

- [ ] **Step 3: Wire into `renderPanels`**

In `renderPanels`, linkify the lede headline and each `also` headline:

```javascript
function renderPanels(b) {
  const wrap = section("panels");
  for (const p of b.panels) {
    const panel = el("article", "panel");
    panel.dataset.panel = p.section;
    panel.append(el("h3", "panel-section", p.section));
    const lede = el("h4", "panel-lede-headline", p.lede_headline);
    linkifyHeadline(lede, p.lede_sources);
    panel.append(lede);
    panel.append(el("p", "panel-lede-body", p.lede_body));
    for (const a of p.also) {
      const item = el("div", "panel-also");
      const head = el("strong", null, a.headline);
      linkifyHeadline(head, a.sources);
      item.append(head, el("span", null, ` ${a.body}`));
      panel.append(item);
    }
    wrap.append(panel);
  }
  return wrap;
}
```

- [ ] **Step 4: Wire into `renderBriefs`**

In `renderBriefs`, append the trailing affordance after each brief body:

```javascript
function renderBriefs(b) {
  const s = section("briefs");
  s.append(el("h3", "briefs-title", "In Brief"));
  for (const br of b.briefs) {
    const item = el("div", "brief");
    item.append(el("strong", null, br.topic), el("span", null, ` ${br.body}`));
    const aff = trailingAffordance(br.sources);
    if (aff) item.append(aff);
    s.append(item);
  }
  return s;
}
```

- [ ] **Step 5: Add popover dismissal (outside-click + Esc)**

In `web/app.js`, register global listeners once at the bottom, just before `main();`:

```javascript
document.addEventListener("click", (e) => {
  for (const w of document.querySelectorAll(".src-multi.open")) {
    if (!w.contains(e.target)) w.classList.remove("open");
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    for (const w of document.querySelectorAll(".src-multi.open")) {
      w.classList.remove("open");
    }
  }
});

main();
```

- [ ] **Step 6: Add styles to `web/style.css`**

Append (uses existing `--ink`/`--muted` tokens and the `#fffdf8` paper background):

```css
/* source click-through (#3) */
.src-link { color: var(--ink); text-decoration: none;
  border-bottom: 1px solid rgba(26,26,26,0.35); }
.src-link:hover { border-bottom-color: var(--ink); }
.src-credit { color: var(--muted); font-size: 0.72em; font-style: italic; }
.brief .src-link, .panel-also .src-link { font-size: 0.92em; }

.src-multi { position: relative; display: inline-block; }
.src-count { font: inherit; font-size: 0.62em; vertical-align: super;
  color: var(--muted); background: none; border: none; cursor: pointer;
  padding: 0 2px; line-height: 1; }
.src-count:hover { color: var(--ink); }
.src-popover { display: none; position: absolute; left: 0; top: 1.4em; z-index: 10;
  min-width: 160px; background: #fffdf8; border: 1px solid #ccc;
  box-shadow: 0 2px 8px rgba(0,0,0,0.18); padding: 6px 8px; }
.src-popover .src-link { display: block; font-size: 13px; padding: 3px 0;
  border-bottom: none; }
.src-multi.open .src-popover { display: block; }
@media (hover: hover) {
  .src-multi:hover .src-popover { display: block; }
}
```

- [ ] **Step 7: Verify in a browser**

Generate an edition into the web dir (or copy `/tmp/src-check.json` to the served `briefings/` path with the correct `{date}-{edition}.json` name and rebuild the index — easiest:
`./.venv/bin/python -m jina_clone.briefing.run_web --edition=morning`), then load themorningfox.com (or serve `web/` locally) and confirm:

Expected, by hand:
- Lead headline is a link; clicking opens the source in a new tab.
- Each panel lede and each `also` headline links out.
- Each brief shows a trailing `— <outlet> ↗` link.
- A legacy edition (no `sources`) still renders cleanly with no links and no errors (check the console).
- On a narrow/mobile viewport, a 2+ source chip opens its popover on **tap** and closes on outside-tap/Esc.

- [ ] **Step 8: Commit**

```bash
git add web/app.js web/style.css
git commit -m "feat(web): render click-through source links and multi-source popover

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run the full suite: `./.venv/bin/pytest -v` — expected all pass.
- [ ] Confirm `web/` renders both a new edition (with links) and a legacy edition (plain) without console errors.
- [ ] Update `docs/web-ui-ux-suggestions.md` to mark #3 as implemented (single-source; multi-source generation deferred), in the Task 5 commit or a follow-up doc commit.

## Out of scope (do not implement here)

- Multi-source *generation* (the generator stays single-source; schema/web are already multi-source-ready — relax `source_url` → `source_urls: list[str]` + prompt change in a later build, gated on Task 4's attribution eyeball).
- Any PDF/`renderer.py` link changes.
- DB/query/fetch changes.
