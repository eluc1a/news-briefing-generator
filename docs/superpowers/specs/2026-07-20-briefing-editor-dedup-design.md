# Editor-in-chief dedup pass for the briefing — Design

**Date:** 2026-07-20
**Status:** Approved (design); implementation pending
**Scope:** `jina_clone/briefing/schema.py`, `generator.py`, `jina_clone/jobs/briefing.py`, wiring in `cli.py` + `briefing/run_web.py`, tests. No renderer, web, or config changes.

## Problem

Duplicate stories appear in published briefings. In the 2026-07-20
morning edition the front-page lead and the National panel's lede were
the same story; duplicates also recur between panels and the briefs
rundown.

Root cause: the only dedup today is exact-URL matching.

- `_dedupe_by_link` (`jobs/briefing.py:39`) dedups the front-matter
  candidate pool by link.
- After the front-matter call, `exclude = {front.lead_source_url}`
  (`jobs/briefing.py:143`) filters that one URL out of panel/brief
  inputs (`generator.py:361`).

Three gaps:

1. **Same story, different URL.** Two outlets covering one event have
   different links; URL exclusion is blind to this. (Today's
   lead-vs-National-lede case.)
2. **Panels and briefs are mutually blind.** The 4 panel calls and the
   briefs call run in parallel (`asyncio.gather`,
   `jobs/briefing.py:161`), each seeing only its own pool. Overlapping
   pools mean the same story can appear in a panel and a brief.
3. **`lead_source_url` is model-reported.** It is validated to be *an*
   input link, but if the model picks the wrong one the single
   exclusion we have silently no-ops.

## Goals

- No two items in a published briefing cover the same underlying event
  (lead, panel ledes, panel `also` items, briefs).
- No blank slots: dedup must never shrink a section below its current
  published size (4 `also` per panel, 6 briefs).
- The paper always prints: the new machinery can only improve the
  briefing, never block or fail it.

## Non-goals

- Dedup across editions (yesterday's paper vs today's).
- The Slack digest call (has its own URL-level dedup; cross-product
  dedup with the paper is not wanted).
- Deduping the *article pools* before generation (DB-level clustering).

## Design

Four layers, applied in pipeline order.

### 1. Prevention: pass the lead headline into panel/brief prompts

Front matter already runs before panels. In addition to the existing
URL exclusion, `assemble_briefing` passes
`lead_headline=front.lead.headline` to `generate_panel` and
`generate_briefs` (new keyword argument). The user-message builders
append:

> Already covered as the front-page lead — do NOT cover this story:
> «headline»

Semantic "don't cover X" works where URL matching fails. This alone
should eliminate most lead-vs-lede duplicates, making layer 4 rare.

### 2. Over-provisioning: generate spares to cut from

| Call | Today | Generate | Publish | New constant |
|---|---|---|---|---|
| Panel `also` | exactly 4 | ask for exactly 6, accept 4–6 | exactly 4 | `PANEL_ALSO_GEN_COUNT = 6` |
| Briefs | exactly 6 | ask for exactly 8, accept 6–8 | exactly 6 | `BRIEFS_GEN_COUNT = 8` |

- `PANEL_ALSO_COUNT = 4` and `BRIEFS_COUNT_MIN/MAX = 6` remain the
  published counts.
- Draft models (`_PanelDraft`, `_BriefsResponse`) and the STRUCTURE
  prompt rules move to the generate counts. Accepting the (final, gen)
  range means a sparse-input day still validates.
- `Panel.also` and `Briefing.briefs` field bounds relax to
  (final, gen) ranges; the trim step guarantees exact final counts
  before render/publish, so the renderer, web JSON, markdown export,
  and emergency fixture see unchanged shapes.

### 3. The editor-in-chief call (7th LLM call)

New `generate_editor_cuts(...)` in `generator.py`, invoked in
`assemble_briefing` after panels + briefs return. Same
`_call_with_retry` machinery (2 attempts) and backend selection as the
other six calls.

**Input** (user message): a numbered manifest of the whole paper —
headlines only, so this is the cheapest call in the pipeline:

- front lead headline (fixed, cannot be cut)
- per panel: lede headline (fixed) + numbered `also` headlines
- numbered brief topics/bodies

The required cuts are computed in code and stated explicitly, e.g.:
"Cut exactly 2 items from national.also (indices 0–5), exactly 2 from
briefs (indices 0–7), … Cut items duplicating a story that appears
anywhere else in the paper first; if no duplicates remain, cut the
least consequential."

**Output** schema:

```json
{
  "cuts": [
    {"section": "national", "index": 3, "duplicate_of": "brief 2"}
  ],
  "lede_dupes": [
    {"section": "economy", "duplicate_of": "front lead"}
  ]
}
```

`section` ∈ {panel keys} ∪ {"briefs"}; `duplicate_of` is a short
free-text pointer (null when cutting for weakness). `lede_dupes` may
be empty and is advisory input to layer 4.

**Parse-time validation** (raises → retry, like the other calls):
indices in range and unique per section; per-section cut count exactly
equals that section's overage (generated − final). Cuts apply only to
`also` items and briefs — never the lead, never panel ledes.

**Apply**: code deletes the cut indices, yielding exactly 4 `also` per
panel and 6 briefs.

### 4. Lede duplicates: one targeted panel rerun

If `lede_dupes` names a panel whose lede duplicates the front lead or
another panel's lede, that panel is regenerated once with the
duplicated story excluded (its URL added to `exclude_urls` **and** a
"do NOT cover: «headline»" line). The rerun's `also` list is trimmed
positionally to 4 — no second editor pass. At most one rerun round per
briefing; if the rerun fails or still duplicates, keep the original
panel, dupe and all. Layer 1 should make this path rare.

When two panels lede the same story (no front-lead involvement), the
editor names one of them in `lede_dupes`; that one reruns.

### Failure handling — the paper always prints

| Failure | Behavior |
|---|---|
| Editor call fails after retries | log warning, trim positionally (keep first 4 `also`, first 6 briefs), continue |
| Panel rerun fails | keep the original panel unchanged |
| Panel generates only 4–5 `also` (sparse day) | overage for that section is smaller or zero; editor cut counts adjust; zero-overage sections need no cuts |
| Everything upstream of the editor fails | existing `GeneratorFailure` → emergency edition path, unchanged |

The editor is strictly additive: no new failure can reach the
render/print/publish path.

### Wiring

`assemble_briefing` gains one injected callable
(`generate_editor_cuts`), typed like the existing six and wired in
`cli.py` (`_briefing_run`, `briefing generate`) and
`briefing/run_web.py`. Tests inject fakes as today.

## Cost / latency

Two extra ~20-word items per panel call, two per briefs call, plus one
headline-only editor call, plus a serial dependency (editor after
panels). On the default `claude -p` backend this is latency only —
roughly +30 s on a twice-daily cron job. A rare lede rerun adds one
panel call more.

## Testing

Fake-LLM unit tests (existing style in `tests/test_jobs_briefing.py` /
generator tests):

- editor cuts applied → exact final counts, correct items removed
- wrong cut count / out-of-range index → retry, then positional-trim
  fallback on second failure
- editor `GeneratorFailure` → positional trim, briefing still returned
- `lede_dupes` → exactly one rerun of the named panel with the story
  excluded; rerun failure keeps the original panel
- zero-overage section (panel returned 4 `also`) → no cuts required
  for it
- existing panel/brief tests updated for gen counts and the
  `lead_headline` kwarg

Before completion: one live `./.venv/bin/python -m jina_clone briefing
generate --out /tmp/b.json` E2E run to catch real-LLM shape drift
(per CLAUDE.md: live E2E before building on top).
