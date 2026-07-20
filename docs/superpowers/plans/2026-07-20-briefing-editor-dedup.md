# Briefing Editor-in-Chief Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate duplicate stories in the briefing via over-provisioned sections plus a 7th "editor-in-chief" LLM call that cuts duplicates, with a lead-headline prevention layer and a targeted panel rerun for lede duplicates.

**Architecture:** Panels generate 6 `also` items (publish 4), briefs generate 8 (publish 6). After panels+briefs return, a headline-only editor call names exact cuts per section (validated: exact overage, in-range, unique) and flags panel ledes duplicating the front lead. Cuts are applied in code; a flagged lede triggers one panel rerun with the story excluded. Every failure falls back to positional trim — the paper always prints. Spec: `docs/superpowers/specs/2026-07-20-briefing-editor-dedup-design.md`.

**Tech Stack:** Python 3.11, pydantic v2, asyncio, pytest-asyncio (fake `call_llm` callables, no real LLM in tests).

## Global Constraints

- Published counts unchanged: exactly 4 `also` per panel, exactly 6 briefs. Renderer, web JSON, markdown export, emergency fixture see unchanged shapes.
- New generation counts: `PANEL_ALSO_GEN_COUNT = 6`, `BRIEFS_GEN_COUNT = 8`; drafts accept (final, gen) ranges so sparse days pass.
- The editor is strictly additive: any editor/rerun failure → log warning + positional trim; never a new failure on the render/print path.
- Cuts may target only `also` items and briefs — never the lead, never panel ledes.
- At most ONE panel rerun round per briefing; no second editor pass.
- `generate_editor` is injected like the other six callables; default `None` skips the editor (positional trim), so existing tests stay valid; production wiring always passes it.
- Test DB is real Postgres (`jina_clone_test`); run tests with `./.venv/bin/pytest`.
- Never `git add -A` / `git add .` in this repo — stage files by name.

---

### Task 1: Counts, schema models, prompt text

Over-provisioned draft bounds, relaxed published-model bounds, the `EditorDecision` schema, and the STRUCTURE prompt-rule text.

**Files:**
- Modify: `jina_clone/briefing/schema.py` (constants block lines 7–10, `Panel.also` line 72, `Briefing.briefs` line 127; new models after `Brief`)
- Modify: `jina_clone/briefing/generator.py` (`PANEL_STRUCTURE_RULES` line 164, `BRIEFS_STRUCTURE_RULES` line 233, `_PanelDraft.also` line 413, `_BriefsResponse.briefs` line 425)
- Test: `tests/test_briefing_schema.py` (update 2 ceiling tests, add editor-model test)

**Interfaces:**
- Consumes: existing `Panel`, `Brief`, `Briefing` models.
- Produces: `PANEL_ALSO_GEN_COUNT: int = 6`, `BRIEFS_GEN_COUNT: int = 8`, and pydantic models `EditorCut(section: str, index: int, duplicate_of: str | None)`, `LedeDupe(section: str, duplicate_of: str)`, `EditorDecision(cuts: list[EditorCut], lede_dupes: list[LedeDupe])` — all importable from `jina_clone.briefing.schema`. Tasks 2 and 3 rely on these exact names.

- [ ] **Step 1: Write the failing tests**

In `tests/test_briefing_schema.py`, replace `test_briefs_too_many_rejected` and `test_panel_also_too_many_rejected` bodies with the new ceilings, and add the editor-model test (imports at top of file gain `EditorDecision`):

```python
def test_briefs_too_many_rejected():
    data = _load_fixture()
    # 9 briefs is above the generation ceiling of 8.
    data["briefs"] = (data["briefs"] * 2)[:9]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_briefs_up_to_gen_count_accepted():
    data = _load_fixture()
    # 8 briefs (pre-trim over-provisioned state) must validate.
    data["briefs"] = (data["briefs"] * 2)[:8]
    Briefing.model_validate(data)


def test_panel_also_too_many_rejected():
    data = _load_fixture()
    # 7 `also` items is above the generation ceiling of 6.
    first_item = data["panels"][0]["also"][0]
    data["panels"][0]["also"] = (data["panels"][0]["also"] + [first_item] * 3)[:7]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_panel_also_up_to_gen_count_accepted():
    data = _load_fixture()
    first_item = data["panels"][0]["also"][0]
    data["panels"][0]["also"] = (data["panels"][0]["also"] + [first_item] * 2)[:6]
    Briefing.model_validate(data)


def test_editor_decision_parses():
    decision = EditorDecision.model_validate({
        "cuts": [{"section": "national", "index": 3, "duplicate_of": "briefs[2]"},
                 {"section": "briefs", "index": 0, "duplicate_of": None}],
        "lede_dupes": [{"section": "economy", "duplicate_of": "front lead"}],
    })
    assert decision.cuts[0].section == "national"
    assert decision.cuts[1].duplicate_of is None
    assert decision.lede_dupes[0].duplicate_of == "front lead"


def test_editor_decision_defaults_empty():
    decision = EditorDecision.model_validate({})
    assert decision.cuts == [] and decision.lede_dupes == []
```

Match the fixture-loading helper name actually used in the file (read the existing tests; it may be `_load_fixture` or inline `json.loads`) — reuse the same pattern the neighboring tests use.

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_briefing_schema.py -v`
Expected: new tests FAIL (`ImportError: cannot import name 'EditorDecision'`); the two edited ceiling tests FAIL (7 briefs / 5 also currently rejected at old ceilings, so the new "accepted" tests raise ValidationError).

- [ ] **Step 3: Implement schema changes**

In `jina_clone/briefing/schema.py`:

```python
BRIEFS_COUNT_MAX = 6
BRIEFS_COUNT_MIN = 6   # tightened in Task 9
BRIEFS_GEN_COUNT = 8   # over-provision; editor cuts back to BRIEFS_COUNT_MIN

PANEL_ALSO_COUNT = 4       # published count
PANEL_ALSO_GEN_COUNT = 6   # over-provision; editor cuts back to PANEL_ALSO_COUNT
```

Relax the two field bounds (published exactness is now guaranteed by the trim step in jobs, spec §2):

```python
    also: list[PanelItem] = Field(
        min_length=PANEL_ALSO_COUNT, max_length=PANEL_ALSO_GEN_COUNT,
    )
```

```python
    briefs: list[Brief] = Field(min_length=BRIEFS_COUNT_MIN, max_length=BRIEFS_GEN_COUNT)
```

Add after `class Brief` (docstring notes the contract):

```python
class EditorCut(BaseModel):
    """One item the editor-in-chief removes. `section` is a panel key
    ("national", "economy", "ai", "international") or "briefs"; `index`
    is the 0-based position in that panel's `also` list / the briefs
    list. `duplicate_of` is a short free-text pointer to the surviving
    telling ("front lead", "briefs[2]"), or None when cut for weakness."""
    section: str
    index: int
    duplicate_of: str | None = None


class LedeDupe(BaseModel):
    """A panel whose lede duplicates the front lead or another panel's
    lede. Advisory: triggers one targeted panel rerun, never a cut."""
    section: str
    duplicate_of: str


class EditorDecision(BaseModel):
    cuts: list[EditorCut] = Field(default_factory=list)
    lede_dupes: list[LedeDupe] = Field(default_factory=list)
```

In `jina_clone/briefing/generator.py`, update the two draft models (the import from `.schema` at the top of the file gains `PANEL_ALSO_GEN_COUNT` and `BRIEFS_GEN_COUNT`):

```python
class _PanelDraft(BaseModel):
    section: str
    lede_headline: str
    lede_body: str
    lede_source_url: str
    also: list[_PanelItemDraft] = Field(
        min_length=PANEL_ALSO_COUNT, max_length=PANEL_ALSO_GEN_COUNT,
    )
```

```python
class _BriefsResponse(BaseModel):
    briefs: list[_BriefDraft] = Field(
        min_length=BRIEFS_COUNT_MIN, max_length=BRIEFS_GEN_COUNT,
    )
```

Update the prompt texts. In `PANEL_STRUCTURE_RULES` (line 169), change:

```
- also: EXACTLY 4 PanelItem entries, each a distinct event from this
```
to
```
- also: EXACTLY 6 PanelItem entries, each a distinct event from this
```

and its closing fallback (line 206) from:

```
Never fabricate. If fewer than 4 distinct stories exist in the input,
repeat the strongest adjacent items but do NOT invent facts."""
```
to
```
Never fabricate. If fewer than 6 distinct stories exist in the input,
emit what exists (minimum 4) — repeat the strongest adjacent items to
reach 4 if needed, but do NOT invent facts."""
```

In `BRIEFS_STRUCTURE_RULES` (line 234), change:

```
Output {"briefs": [...]} containing EXACTLY 6 Brief entries. Each entry:
```
to
```
Output {"briefs": [...]} containing EXACTLY 8 Brief entries (minimum 6
if the input pool is too thin). Each entry:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_briefing_schema.py tests/test_briefing_generator.py tests/test_briefing_renderer.py -v`
Expected: all PASS (existing generator tests feed 4-item panels, which the relaxed 4–6 draft still accepts; renderer tests use exactly-4 fixtures, unchanged).

- [ ] **Step 5: Commit**

```bash
git add jina_clone/briefing/schema.py jina_clone/briefing/generator.py tests/test_briefing_schema.py
git commit -m "feat(briefing): over-provision counts + EditorDecision schema"
```

---

### Task 2: Generator — `avoid_headlines` threading and the editor call

**Files:**
- Modify: `jina_clone/briefing/generator.py` (`_build_panel_user_msg` line 385, `_build_briefs_user_msg` line 430, `generate_panel` line 701, `generate_briefs` line 747; new `_editor_system_prompt`, `_build_editor_user_msg`, `generate_editor_cuts` after `generate_briefs`)
- Test: `tests/test_briefing_generator.py`

**Interfaces:**
- Consumes: Task 1's `EditorDecision`, `EditorCut`, `LedeDupe`, `PANEL_ALSO_GEN_COUNT`, `BRIEFS_GEN_COUNT`; existing `_call_with_retry`, `_build_default_call_llm`, `Panel`, `Brief`, `PANEL_ALSO_COUNT`, `BRIEFS_COUNT_MIN`.
- Produces (Task 3 relies on these exact signatures):
  - `generate_panel(..., avoid_headlines: list[str] | None = None)` and `generate_briefs(..., avoid_headlines: list[str] | None = None)` — new optional keyword on both.
  - `async def generate_editor_cuts(*, lead_headline: str, panels: list[tuple[str, Panel]], briefs: list[Brief], title: str, call_llm: CallLLM | None = None, client: AsyncAnthropic | None = None) -> EditorDecision` — `panels` is `(section_key, Panel)` pairs in config order; raises `GeneratorFailure` after 2 failed attempts.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_briefing_generator.py`, following the file's existing fake-`call_llm` style (a fake is `async def fake(client, prompt): return json.dumps(...)`; reuse the file's existing panel/brief fixture builders for `Panel`/`Brief` instances — build panels with 6 `also` items and 8 briefs via the same helpers used by `test_generate_panel_happy_path`):

```python
def _mk_panel(n_also=6):
    return Panel(
        section="National",
        lede_headline="Lede headline",
        lede_body="Lede body " * 8,
        lede_sources=[],
        also=[PanelItem(headline=f"H{i}", body=f"B{i}", sources=[])
              for i in range(n_also)],
    )


def _mk_briefs(n=8):
    return [Brief(topic=f"T{i}", body=f"Body {i}", sources=[]) for i in range(n)]


async def test_panel_prompt_carries_avoid_headlines():
    captured = {}

    async def fake(client, prompt):
        captured["prompt"] = prompt
        return _valid_panel_json()  # reuse the file's existing valid-panel JSON helper

    await generate_panel(
        section=_section(), articles=_articles(), exclude_urls=set(),
        title="T", call_llm=fake,
        avoid_headlines=["Fed cuts rates by 50bp"],
    )
    assert "Fed cuts rates by 50bp" in captured["prompt"]
    assert "do NOT cover" in captured["prompt"]


async def test_briefs_prompt_carries_avoid_headlines():
    captured = {}

    async def fake(client, prompt):
        captured["prompt"] = prompt
        return _valid_briefs_json()  # reuse the file's existing helper

    await generate_briefs(
        articles=_articles(), exclude_urls=set(), title="T", call_llm=fake,
        avoid_headlines=["Fed cuts rates by 50bp"],
    )
    assert "Fed cuts rates by 50bp" in captured["prompt"]


async def test_editor_happy_path():
    panels = [("national", _mk_panel(6)), ("economy", _mk_panel(6))]
    briefs = _mk_briefs(8)

    async def fake(client, prompt):
        return json.dumps({
            "cuts": (
                [{"section": "national", "index": i} for i in (0, 3)]
                + [{"section": "economy", "index": i} for i in (1, 2)]
                + [{"section": "briefs", "index": i, "duplicate_of": "front lead"}
                   for i in (5, 7)]
            ),
            "lede_dupes": [],
        })

    decision = await generate_editor_cuts(
        lead_headline="Lead", panels=panels, briefs=briefs,
        title="T", call_llm=fake,
    )
    assert len(decision.cuts) == 6
    assert decision.lede_dupes == []


async def test_editor_prompt_lists_manifest_and_required_cuts():
    captured = {}
    panels = [("national", _mk_panel(6))]

    async def fake(client, prompt):
        captured["prompt"] = prompt
        return json.dumps({"cuts": [
            {"section": "national", "index": 0},
            {"section": "national", "index": 1},
            {"section": "briefs", "index": 0},
            {"section": "briefs", "index": 1},
        ], "lede_dupes": []})

    await generate_editor_cuts(
        lead_headline="Lead H", panels=panels, briefs=_mk_briefs(8),
        title="T", call_llm=fake,
    )
    p = captured["prompt"]
    assert "Lead H" in p and "Lede headline" in p
    assert "national.also[5]" in p and "briefs[7]" in p
    assert "cut EXACTLY 2" in p


async def test_editor_retries_on_wrong_cut_count():
    calls = {"n": 0}
    good = {"cuts": [{"section": "national", "index": 0},
                     {"section": "national", "index": 1}],
            "lede_dupes": []}

    async def fake(client, prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"cuts": [{"section": "national", "index": 0}],
                               "lede_dupes": []})  # 1 cut, need 2
        return json.dumps(good)

    decision = await generate_editor_cuts(
        lead_headline="L", panels=[("national", _mk_panel(6))], briefs=_mk_briefs(6),
        title="T", call_llm=fake,
    )
    assert calls["n"] == 2 and len(decision.cuts) == 2


async def test_editor_rejects_out_of_range_and_duplicate_indices():
    async def bad_index(client, prompt):
        return json.dumps({"cuts": [{"section": "national", "index": 6},
                                    {"section": "national", "index": 0}],
                           "lede_dupes": []})

    with pytest.raises(GeneratorFailure):
        await generate_editor_cuts(
            lead_headline="L", panels=[("national", _mk_panel(6))],
            briefs=_mk_briefs(6), title="T", call_llm=bad_index,
        )

    async def dup_index(client, prompt):
        return json.dumps({"cuts": [{"section": "national", "index": 2},
                                    {"section": "national", "index": 2}],
                           "lede_dupes": []})

    with pytest.raises(GeneratorFailure):
        await generate_editor_cuts(
            lead_headline="L", panels=[("national", _mk_panel(6))],
            briefs=_mk_briefs(6), title="T", call_llm=dup_index,
        )


async def test_editor_rejects_unknown_section():
    async def fake(client, prompt):
        return json.dumps({"cuts": [{"section": "sports", "index": 0},
                                    {"section": "national", "index": 1}],
                           "lede_dupes": []})

    with pytest.raises(GeneratorFailure):
        await generate_editor_cuts(
            lead_headline="L", panels=[("national", _mk_panel(6))],
            briefs=_mk_briefs(6), title="T", call_llm=fake,
        )


async def test_editor_zero_overage_accepts_empty_cuts():
    async def fake(client, prompt):
        return json.dumps({"cuts": [], "lede_dupes": [
            {"section": "national", "duplicate_of": "front lead"}]})

    decision = await generate_editor_cuts(
        lead_headline="L", panels=[("national", _mk_panel(4))],
        briefs=_mk_briefs(6), title="T", call_llm=fake,
    )
    assert decision.cuts == []
    assert decision.lede_dupes[0].section == "national"


async def test_editor_rejects_lede_dupe_unknown_panel():
    async def fake(client, prompt):
        return json.dumps({"cuts": [], "lede_dupes": [
            {"section": "briefs", "duplicate_of": "front lead"}]})

    with pytest.raises(GeneratorFailure):
        await generate_editor_cuts(
            lead_headline="L", panels=[("national", _mk_panel(4))],
            briefs=_mk_briefs(6), title="T", call_llm=fake,
        )
```

Adjust helper names (`_section()`, `_articles()`, `_valid_panel_json()`) to the file's actual existing helpers — reuse, don't duplicate. Add needed imports (`generate_editor_cuts`, `EditorDecision`, `Panel`, `PanelItem`, `Brief`, `GeneratorFailure`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_briefing_generator.py -v -k "avoid or editor"`
Expected: FAIL — `ImportError: cannot import name 'generate_editor_cuts'` / `TypeError: unexpected keyword argument 'avoid_headlines'`.

- [ ] **Step 3: Implement**

In `jina_clone/briefing/generator.py`.

Import `EditorDecision` in the existing `from jina_clone.briefing.schema import (...)` block.

Shared helper next to `_filter_excluded`:

```python
def _avoid_lines(avoid_headlines: list[str] | None) -> list[str]:
    if not avoid_headlines:
        return []
    return [
        "",
        "Already covered elsewhere in the paper — do NOT cover these "
        "stories, including any other outlet's version of them:",
        *[f"- «{h}»" for h in avoid_headlines],
    ]
```

`_build_panel_user_msg` gains the parameter and inserts the lines right after the header:

```python
def _build_panel_user_msg(
    *, section: SectionDef, articles: list[dict],
    avoid_headlines: list[str] | None = None,
) -> str:
    parts = [
        f"Panel: {section.title} ({len(articles)} articles)",
        *_avoid_lines(avoid_headlines),
    ]
    ...  # rest unchanged
```

`_build_briefs_user_msg` identically:

```python
def _build_briefs_user_msg(
    *, articles: list[dict], avoid_headlines: list[str] | None = None,
) -> str:
    parts = [
        f"Briefs pool ({len(articles)} articles)",
        *_avoid_lines(avoid_headlines),
    ]
    ...  # rest unchanged
```

`generate_panel` and `generate_briefs` each gain `avoid_headlines: list[str] | None = None` and forward it to their user-msg builder. No other changes to those functions.

Editor system prompt, after `_briefs_system_prompt`:

```python
def _editor_system_prompt(title: str) -> str:
    return f"""You are the editor-in-chief of "{title}" daily briefing.
The section editors have filed the full paper, over-provisioned. Your
ONLY task: cut items back to the published counts, removing duplicate
coverage first.

Two items are DUPLICATES when they cover the same underlying event or
announcement — even from different outlets, with different wording, or
from a different angle. A follow-up with genuinely new developments is
NOT a duplicate.

RULES:
- Cut EXACTLY the number of items per section stated in the REQUIRED
  CUTS block — no more, no fewer. Sections absent from that block get
  zero cuts.
- Cut priority: (1) items duplicating the front lead or a panel lede,
  (2) items duplicating another surviving item — keep the stronger
  telling, cut the other, (3) if no duplicates remain, the least
  consequential items.
- Cuts may target ONLY `also` items and briefs. The front lead and the
  panel ledes are fixed and cannot be cut.
- If a panel LEDE duplicates the front lead or another panel's lede,
  report that panel in `lede_dupes` — do not try to cut it. Otherwise
  emit "lede_dupes": [].
- `duplicate_of`: a short pointer to the surviving telling ("front
  lead", "national lede", "briefs[2]", "economy.also[0]"), or null
  when cutting for weakness.

Output: valid JSON matching the EditorDecision schema below. No
preamble. No markdown fence."""
```

User-msg builder, after `_build_briefs_user_msg`:

```python
def _build_editor_user_msg(
    *,
    lead_headline: str,
    panels: list[tuple[str, Panel]],
    briefs: list[Brief],
    overages: dict[str, int],
    sizes: dict[str, int],
) -> str:
    parts = [f"FRONT LEAD (fixed): {lead_headline}", ""]
    for key, panel in panels:
        parts.append(f"PANEL {key} — lede (fixed): {panel.lede_headline}")
        for i, item in enumerate(panel.also):
            parts.append(f"  {key}.also[{i}]: {item.headline} — {item.body}")
        parts.append("")
    parts.append("BRIEFS:")
    for i, b in enumerate(briefs):
        parts.append(f"  briefs[{i}]: {b.topic}: {b.body}")
    parts.append("")
    parts.append("REQUIRED CUTS:")
    any_cuts = False
    for section, need in overages.items():
        if need > 0:
            any_cuts = True
            parts.append(
                f"- {section}: cut EXACTLY {need} "
                f"(valid indices 0-{sizes[section] - 1})"
            )
    if not any_cuts:
        parts.append(
            "- none required; emit \"cuts\": [] and only report lede_dupes"
        )
    parts.append("")
    parts.append("--- Schema ---")
    parts.append(json.dumps(EditorDecision.model_json_schema(), indent=2))
    parts.append("")
    parts.append("Emit the EditorDecision JSON now.")
    return "\n".join(parts)
```

Public function, after `generate_briefs`:

```python
async def generate_editor_cuts(
    *,
    lead_headline: str,
    panels: list[tuple[str, Panel]],
    briefs: list[Brief],
    title: str,
    call_llm: CallLLM | None = None,
    client: AsyncAnthropic | None = None,
) -> EditorDecision:
    """Editor-in-chief pass: given the whole over-provisioned paper
    (headlines only), decide which `also` items / briefs to cut so each
    section lands on its published count, duplicates first. Panel ledes
    duplicating the front lead (or each other) are reported in
    `lede_dupes` for a targeted rerun by the caller."""
    system_prompt = _editor_system_prompt(title)
    if call_llm is None:
        call_llm = _build_default_call_llm(system_prompt, client)

    panel_keys = {key for key, _ in panels}
    sizes = {key: len(p.also) for key, p in panels}
    sizes["briefs"] = len(briefs)
    overages = {key: len(p.also) - PANEL_ALSO_COUNT for key, p in panels}
    overages["briefs"] = len(briefs) - BRIEFS_COUNT_MIN

    user_msg = _build_editor_user_msg(
        lead_headline=lead_headline, panels=panels, briefs=briefs,
        overages=overages, sizes=sizes,
    )

    def parse(raw: str) -> EditorDecision:
        decision = EditorDecision.model_validate_json(raw)
        by_section: dict[str, set[int]] = {}
        for cut in decision.cuts:
            if cut.section not in sizes:
                raise ValueError(f"cut names unknown section {cut.section!r}")
            idxs = by_section.setdefault(cut.section, set())
            if cut.index in idxs:
                raise ValueError(
                    f"duplicate cut index {cut.section}[{cut.index}]")
            if not (0 <= cut.index < sizes[cut.section]):
                raise ValueError(
                    f"cut index {cut.section}[{cut.index}] out of range "
                    f"(size {sizes[cut.section]})")
            idxs.add(cut.index)
        for section, need in overages.items():
            got = len(by_section.get(section, set()))
            if got != need:
                raise ValueError(
                    f"{section}: {got} cuts, need exactly {need}")
        for dupe in decision.lede_dupes:
            if dupe.section not in panel_keys:
                raise ValueError(
                    f"lede_dupes names unknown panel {dupe.section!r}")
        return decision

    return await _call_with_retry(
        call_llm=call_llm, client=client, user_msg=user_msg, parse=parse,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_briefing_generator.py -v`
Expected: all PASS (new and existing).

- [ ] **Step 5: Commit**

```bash
git add jina_clone/briefing/generator.py tests/test_briefing_generator.py
git commit -m "feat(briefing): avoid_headlines threading + editor-in-chief LLM call"
```

---

### Task 3: Jobs integration, lede rerun, entry-point wiring

**Files:**
- Modify: `jina_clone/jobs/briefing.py` (imports, new type alias + helpers after `_dedupe_by_link`, `assemble_briefing` steps 2–3, `run_briefing` signature + forward)
- Modify: `jina_clone/cli.py` (lines ~165 and ~233: add `generate_editor=`)
- Modify: `jina_clone/briefing/run_web.py` (line ~70: add `generate_editor=`)
- Test: `tests/test_jobs_briefing.py`

**Interfaces:**
- Consumes: Task 1's `EditorDecision`, `PANEL_ALSO_COUNT`, `BRIEFS_COUNT_MIN` (from `jina_clone.briefing.schema`); Task 2's `generate_editor_cuts` signature and the `avoid_headlines` kwarg on `generate_panel`/`generate_briefs`.
- Produces: `assemble_briefing(..., generate_editor: EditorFn | None = None)` and `run_briefing(..., generate_editor: EditorFn | None = None)`; module-level `_apply_cuts(decision, keys, panels, briefs)` and `_trim_positional(panels, briefs)` (unit-testable pure helpers). `EditorFn = Callable[..., Awaitable[Any]]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_jobs_briefing.py`, reusing the file's existing fakes pattern (`_row`, `_async_weather`, `_async_markets`, and the kwarg-style fake generators with `**kw`). Build over-provisioned fakes: panels return 6 `also`, briefs return 8.

```python
def _panel6(section_title="National"):
    return Panel(
        section=section_title,
        lede_headline=f"{section_title} lede",
        lede_body="body " * 10,
        lede_sources=[Source(url=f"https://{section_title}-lede", source="s")],
        also=[PanelItem(headline=f"{section_title} H{i}", body=f"B{i}",
                        sources=[]) for i in range(6)],
    )


def _briefs8():
    return [Brief(topic=f"T{i}", body=f"body {i}", sources=[]) for i in range(8)]


async def test_editor_cuts_applied(tmp_path):
    """Editor decision removes the named indices; final counts exact."""
    editor_calls = []

    async def gen_editor(*, lead_headline, panels, briefs, title, **kw):
        editor_calls.append((lead_headline, [k for k, _ in panels], len(briefs)))
        cuts = [{"section": k, "index": i} for k, _ in panels for i in (0, 5)]
        cuts += [{"section": "briefs", "index": 6}, {"section": "briefs", "index": 7}]
        return EditorDecision.model_validate({"cuts": cuts, "lede_dupes": []})

    briefing, _ = await _assemble_with_fakes(   # see note below
        gen_panel_result=_panel6, gen_briefs_result=_briefs8,
        generate_editor=gen_editor,
    )
    for panel in briefing.panels:
        assert len(panel.also) == 4
        # indices 0 and 5 were cut: H0 and H5 gone, H1..H4 remain
        assert [it.headline.split()[-1] for it in panel.also] == ["H1", "H2", "H3", "H4"]
    assert len(briefing.briefs) == 6
    assert [b.topic for b in briefing.briefs] == [f"T{i}" for i in range(6)]
    assert editor_calls  # editor was invoked with lead headline + keys


async def test_editor_failure_falls_back_to_positional_trim(tmp_path):
    async def gen_editor(**kw):
        raise GeneratorFailure("editor exploded")

    briefing, _ = await _assemble_with_fakes(
        gen_panel_result=_panel6, gen_briefs_result=_briefs8,
        generate_editor=gen_editor,
    )
    for panel in briefing.panels:
        assert len(panel.also) == 4
        assert panel.also[0].headline.endswith("H0")  # first 4 kept
    assert len(briefing.briefs) == 6


async def test_no_editor_positional_trim(tmp_path):
    briefing, _ = await _assemble_with_fakes(
        gen_panel_result=_panel6, gen_briefs_result=_briefs8,
        generate_editor=None,
    )
    for panel in briefing.panels:
        assert len(panel.also) == 4
    assert len(briefing.briefs) == 6


async def test_lead_headline_threaded_to_panels_and_briefs(tmp_path):
    seen = {"panel_avoid": [], "briefs_avoid": None}
    # inside the fake gen_panel / gen_briefs, record kw.get("avoid_headlines")
    ...
    assert all(a == ["LEAD HEADLINE"] for a in seen["panel_avoid"])
    assert seen["briefs_avoid"] == ["LEAD HEADLINE"]


async def test_lede_dupe_triggers_single_rerun(tmp_path):
    panel_calls = []

    async def gen_panel(*, section, articles, exclude_urls, title, **kw):
        panel_calls.append((section.key, set(exclude_urls),
                            kw.get("avoid_headlines")))
        return _panel6(section.title)

    async def gen_editor(*, lead_headline, panels, briefs, title, **kw):
        return EditorDecision.model_validate({
            "cuts": <exact-overage cuts as in test_editor_cuts_applied>,
            "lede_dupes": [{"section": "national",
                            "duplicate_of": "front lead"}],
        })

    briefing, _ = await _assemble_with_fakes(
        gen_panel=gen_panel, gen_briefs_result=_briefs8,
        generate_editor=gen_editor,
    )
    national_calls = [c for c in panel_calls if c[0] == "national"]
    assert len(national_calls) == 2                       # initial + one rerun
    rerun = national_calls[1]
    assert "https://National-lede" in rerun[1]            # old lede URL excluded
    assert "National lede" in rerun[2]                    # old lede headline avoided
    # rerun panel trimmed positionally to 4
    nat = [p for p in briefing.panels if p.section == "National"][0]
    assert len(nat.also) == 4


async def test_lede_rerun_failure_keeps_original_panel(tmp_path):
    calls = {"national": 0}

    async def gen_panel(*, section, articles, exclude_urls, title, **kw):
        if section.key == "national":
            calls["national"] += 1
            if calls["national"] > 1:
                raise GeneratorFailure("rerun failed")
        return _panel6(section.title)

    # editor as in test_lede_dupe_triggers_single_rerun
    briefing, _ = await _assemble_with_fakes(...)
    nat = [p for p in briefing.panels if p.section == "National"][0]
    assert nat.lede_headline == "National lede"   # original kept
    assert len(nat.also) == 4                     # still trimmed
```

Note on `_assemble_with_fakes`: the existing tests build the full kwargs to `assemble_briefing` inline each time. Extract a small module-level helper in the test file that wires the standard fakes (fetch returning enough `_row`s, weather, markets, gen_fm) and accepts overrides for `gen_panel`/`gen_briefs`/`generate_editor` — follow the shapes already used by `test_happy_path_fans_out_six_calls` (line 79). Also add two pure-helper tests:

```python
def test_apply_cuts_pure():
    panels = [_panel6("National")]
    briefs = _briefs8()
    decision = EditorDecision.model_validate({
        "cuts": [{"section": "national", "index": 1},
                 {"section": "national", "index": 4},
                 {"section": "briefs", "index": 0},
                 {"section": "briefs", "index": 7}],
        "lede_dupes": [],
    })
    new_panels, new_briefs = _apply_cuts(decision, ["national"], panels, briefs)
    assert [it.headline for it in new_panels[0].also] == \
        ["National H0", "National H2", "National H3", "National H5"]
    assert [b.topic for b in new_briefs] == [f"T{i}" for i in range(1, 7)]


def test_trim_positional_pure():
    panels, briefs = _trim_positional([_panel6("National")], _briefs8())
    assert len(panels[0].also) == 4 and len(briefs) == 6
    # already-final input is a no-op
    panels2, briefs2 = _trim_positional(panels, briefs)
    assert panels2[0].also == panels[0].also and briefs2 == briefs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_jobs_briefing.py -v -k "editor or trim or lede or avoid or threaded"`
Expected: FAIL — `ImportError: cannot import name '_apply_cuts'` / `TypeError: unexpected keyword argument 'generate_editor'`.

- [ ] **Step 3: Implement jobs changes**

In `jina_clone/jobs/briefing.py`.

Extend the schema import (line 10) with `EditorDecision`, `PANEL_ALSO_COUNT`, `BRIEFS_COUNT_MIN`. Add alongside the existing `*Fn` aliases (line 31):

```python
EditorFn = Callable[..., Awaitable[Any]]
```

Helpers after `_dedupe_by_link`:

```python
def _trim_positional(
    panels: list[Panel], briefs: list[Brief],
) -> tuple[list[Panel], list[Brief]]:
    trimmed = [
        p.model_copy(update={"also": list(p.also[:PANEL_ALSO_COUNT])})
        for p in panels
    ]
    return trimmed, list(briefs[:BRIEFS_COUNT_MIN])


def _apply_cuts(
    decision: EditorDecision,
    keys: list[str],
    panels: list[Panel],
    briefs: list[Brief],
) -> tuple[list[Panel], list[Brief]]:
    cut_idx: dict[str, set[int]] = {}
    for c in decision.cuts:
        cut_idx.setdefault(c.section, set()).add(c.index)
    new_panels = [
        p.model_copy(update={"also": [
            it for i, it in enumerate(p.also)
            if i not in cut_idx.get(key, set())
        ]})
        for key, p in zip(keys, panels)
    ]
    new_briefs = [
        b for i, b in enumerate(briefs)
        if i not in cut_idx.get("briefs", set())
    ]
    return new_panels, new_briefs
```

`assemble_briefing`: add `generate_editor: EditorFn | None = None` to the signature (after `generate_briefs`) and update the docstring's "six" call count to "seven". In Step 3, thread the lead headline:

```python
    panel_coros = [
        generate_panel(
            section=s,
            articles=section_pools[s.key],
            exclude_urls=exclude,
            title=title,
            avoid_headlines=[front.lead.headline],
        )
        for s in config.sections
    ]
    briefs_coro = generate_briefs(
        articles=briefs_pool,
        exclude_urls=exclude,
        title=title,
        avoid_headlines=[front.lead.headline],
    )
```

After `panels`/`briefs` are unpacked (line 163), insert the editorial step. Replace the direct `Briefing(...)` construction lead-in with:

```python
    # --- Step 3.5: editor-in-chief dedup (spec 2026-07-20) ---
    keys = [s.key for s in config.sections]
    if generate_editor is not None:
        try:
            decision = await generate_editor(
                lead_headline=front.lead.headline,
                panels=list(zip(keys, panels)),
                briefs=briefs,
                title=title,
            )
            panels, briefs = _apply_cuts(decision, keys, panels, briefs)
            # One targeted rerun round for panel ledes duplicating the
            # lead (or each other). Rerun failure keeps the original —
            # a duplicate lede beats a missing panel.
            for dupe in decision.lede_dupes:
                idx = keys.index(dupe.section)
                old = panels[idx]
                old_url = old.lede_sources[0].url if old.lede_sources else None
                log.info("lede dupe in %s (%s) — rerunning panel",
                         dupe.section, dupe.duplicate_of)
                try:
                    fresh = await generate_panel(
                        section=config.sections[idx],
                        articles=section_pools[dupe.section],
                        exclude_urls=exclude | ({old_url} if old_url else set()),
                        title=title,
                        avoid_headlines=[front.lead.headline,
                                         old.lede_headline],
                    )
                    panels[idx] = fresh
                except GeneratorFailure as e:
                    log.warning("panel rerun failed for %s — keeping "
                                "original: %s", dupe.section, e)
        except GeneratorFailure as e:
            log.warning("editor call failed — positional trim: %s", e)
    # All paths land on exact published counts; no-op when the editor
    # already cut to size.
    panels, briefs = _trim_positional(panels, briefs)
```

`run_briefing`: add `generate_editor: EditorFn | None = None` to the signature (after `generate_briefs`, line 200) and forward `generate_editor=generate_editor` in the `assemble_briefing(...)` call (line 218).

- [ ] **Step 4: Wire the entry points**

`jina_clone/cli.py` — in both the `briefing generate` path (`assemble_briefing` call, after line 167) and the `briefing run` path (`run_briefing` call, after line 235), add:

```python
            generate_editor=briefing_generator.generate_editor_cuts,
```

`jina_clone/briefing/run_web.py` — same line added to the `run_briefing(...)` call after line 72.

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/pytest -v`
Expected: all PASS. Existing `test_jobs_briefing.py` tests pass untouched (their fakes return exactly 4/6, `generate_editor` defaults to `None`, and `_trim_positional` is a no-op at final counts; the new `avoid_headlines` kwarg lands in the fakes' `**kw`).

- [ ] **Step 6: Commit**

```bash
git add jina_clone/jobs/briefing.py jina_clone/cli.py jina_clone/briefing/run_web.py tests/test_jobs_briefing.py
git commit -m "feat(briefing): editor dedup step, lede rerun, entry-point wiring"
```

---

### Task 4: Live E2E and shape-drift fixes

Per CLAUDE.md: one real run before calling it done — real `claude -p` output surfaces drift that fakes don't (e.g. the model refusing to emit exactly 6 `also`, or editor JSON quirks).

**Files:**
- Modify: none expected; whatever the E2E surfaces (most likely prompt text in `generator.py`).

**Interfaces:**
- Consumes: everything above, the real `cli` backend, production DB read path.

- [ ] **Step 1: Run the live generate (no print, no publish, no DB write)**

```bash
./.venv/bin/python -m jina_clone briefing generate --edition=morning --out /tmp/claude-1000/-home-elucia-dev-jina-clone/96c16de8-c1df-4653-ad28-5a89d7b53a22/scratchpad/e2e-briefing.json
```

Expected: exits 0; log lines show 7 LLM calls (front matter, 4 panels, briefs, editor).

- [ ] **Step 2: Inspect the output**

```bash
./.venv/bin/python - <<'EOF'
import json
b = json.load(open("/tmp/claude-1000/-home-elucia-dev-jina-clone/96c16de8-c1df-4653-ad28-5a89d7b53a22/scratchpad/e2e-briefing.json"))
assert all(len(p["also"]) == 4 for p in b["panels"]), [len(p["also"]) for p in b["panels"]]
assert len(b["briefs"]) == 6, len(b["briefs"])
print("lead:", b["lead"]["headline"])
for p in b["panels"]:
    print(p["section"], "lede:", p["lede_headline"])
    for it in p["also"]:
        print("   ", it["headline"])
for br in b["briefs"]:
    print("brief:", br["topic"], "—", br["body"][:60])
EOF
```

Expected: counts exact; eyeball the printed headlines for duplicates — the lead must not reappear as a panel lede or `also`/brief.

- [ ] **Step 3: Check the briefing log for the editor's behavior**

Run: `rtk proxy grep -iE "editor|lede dupe|positional trim|rerun" logs/briefing.log | tail -20` (or the console output of Step 1).
Expected: either a clean editor decision or — if the editor failed — investigate before shipping; a live editor failure on attempt one is exactly the drift this task exists to catch. Fix prompts, rerun Steps 1–3 until clean twice in a row.

- [ ] **Step 4: Commit any drift fixes**

```bash
git add jina_clone/briefing/generator.py
git commit -m "fix(briefing): prompt adjustments from live E2E"
```

(Skip if nothing changed.)

---

## Self-Review

- **Spec coverage:** layer 1 (lead headline prevention) → Task 2 builders + Task 3 threading; layer 2 (over-provisioning) → Task 1; layer 3 (editor call + validation) → Task 2; layer 4 (lede rerun) → Task 3; failure table → Task 3 (fallbacks) with tests; wiring → Task 3 Step 4; live E2E → Task 4. No gaps.
- **Type consistency:** `EditorDecision`/`EditorCut`/`LedeDupe` defined in Task 1, consumed by Tasks 2–3 under the same names; `generate_editor_cuts` keyword signature in Task 2 matches the call in Task 3; `avoid_headlines: list[str] | None` on both generate functions and both builders; `_apply_cuts(decision, keys, panels, briefs)` and `_trim_positional(panels, briefs)` used consistently.
- **Placeholder scan:** the two `...`-elided fake bodies in Task 3 Step 1 tests reference the exact pattern defined in the same step (`test_editor_cuts_applied`'s cut list; recording `kw.get("avoid_headlines")` in the standard fakes); the `_assemble_with_fakes` helper is specified against the concrete existing test at line 79. Everything else is complete code.
