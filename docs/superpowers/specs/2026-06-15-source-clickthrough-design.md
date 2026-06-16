# Click-through to sources (web UI/UX #3) — design

Captured 2026-06-15. Implements suggestion #3 from
`docs/web-ui-ux-suggestions.md`: the panels/briefs JSON carries no URLs,
so themorningfox.com is a dead-end — a reader who wants to go deeper
can't. This adds per-item source links so each synthesized item becomes a
doorway to the article(s) it came from.

## Goal

Every synthesized item on the web edition links out to its source:

- the lead story
- each of the 4 panel ledes
- each of the 16 panel `also` items (4 panels × 4)
- each of the 6 briefs

Scope is **web only**. The print PDF is unchanged (links are dead on
paper, and it is a print-first product).

## Key insight: the data is already there

`fetch_section_articles` already returns `link` for every article
(`storage/db.py:139`), and `_format_article` already feeds `Link:` into
every prompt (`generator.py:318-325`). The LLM already *sees* the URLs;
it just doesn't echo them into its output. So **no DB change and no
prompt-input change** is needed — only output schema, output validation,
and rendering.

The codebase also already has a **proven anti-hallucination pattern** for
exactly this:

- `FrontMatter.lead_source_url` — the LLM echoes back one input article's
  `Link`; `generate_front_matter`'s `parse` rejects it (and retries) if it
  is not in the real input set (`generator.py:617-625`).
- `DigestItem.url` + `source` — the LLM returns the URL; the outlet
  `source` is resolved *deterministically* from the input article via
  `source_by_url`, never trusted from the LLM (`generator.py:693-711`).

This feature is essentially "replicate that pattern per item, then render
the result as links."

## Attribution-fidelity constraint (why we phase)

URL validation can catch a **hallucinated** URL (one not in the input
set). It **cannot** catch "this source did not actually contribute to
this sentence." Asking the LLM to enumerate *all* contributing sources
for a synthesized blurb introduces two failure modes validation can't
police: under-reporting (lists only the obvious source) and
over-reporting (staples on loosely-related articles). Multi-source
attribution is therefore inherently lower-fidelity than the
single-source pattern we know works.

**Decision:** the schema is multi-source-ready from day one
(`sources: list[Source]`), and the web renders 1 vs 2+ differently from
day one, but the **generator emits exactly one validated primary source
per item** in this build. Multi-source generation is a follow-up, gated
on eyeballing real attribution quality first (see "Phasing").

## Touch points

| Layer | File | Change |
|---|---|---|
| Schema | `briefing/schema.py` | `Source` model + `sources` on lead, panel lede, `also`, briefs |
| Generation | `briefing/generator.py` | echo-and-validate one `source_url` per item; resolve URL→outlet |
| Web | `web/app.js`, `web/style.css` | render 0→plain, 1→inline link, 2+→popover |
| Tests | `tests/` | validation + resolution + legacy-compat |

**Untouched:** `renderer.py` (PDF), `storage/db.py`, `jobs/briefing.py`
(`assemble_briefing` just passes models through), `briefing/web.py` (it
serializes via `briefing.model_dump_json()`, so new fields ride along
automatically).

## Schema design

```python
class Source(BaseModel):
    url: str
    source: str   # outlet name, resolved from the input article — never from the LLM
```

`sources: list[Source] = Field(default_factory=list)` is added to the
public models: `LeadStory`, `Panel` (as `lede_sources`), `PanelItem`, and
`Brief`. The empty default means **old published editions in
`briefings/*.json` (which have no `sources`) still validate and render as
plain text** — backward compatible.

### Two-layer models (chosen approach)

The LLM echoes a *URL*; we resolve the outlet name ourselves. To keep the
LLM-facing field out of the published JSON, use internal "draft" models
for the LLM output and public models for the final/serialized object —
mirroring the existing `FrontMatter` (internal) → `LeadStory` (public)
split already in this codebase.

- Internal draft models carry `source_url: str` (phase 1) per item.
- Public models carry `sources: list[Source]`.
- The generator's `parse` validates `source_url` and maps draft → public.

Concretely:

- **Lead:** `FrontMatter.lead_source_url` already exists and is already
  validated. `generate_front_matter`'s `parse` additionally resolves it
  and sets `fm.lead.sources = [Source(url, source_by_url[url])]`. (Add a
  `source_by_url` map alongside the existing `valid_urls`.)
- **Panels:** a `PanelDraft` whose lede has `lede_source_url` and whose
  `also` items (`PanelItemDraft`) each have `source_url`. `parse`
  validates all of them and builds the public `Panel` with `lede_sources`
  and per-`also` `sources`.
- **Briefs:** a `BriefDraft` with `source_url` per brief; `parse` builds
  public `Brief`s with `sources`.

Rejected alternative — a single model holding both a transient
`source_url` and the resolved `sources`: simpler but leaks the LLM-facing
field into published JSON. Not chosen.

The phase-1 → multi-source upgrade is then localized: relax the draft
field from `source_url: str` to `source_urls: list[str]` and adjust the
prompt. The public schema and the web renderer do not change.

## Generation (phase 1 = one validated primary per item)

For each of `generate_front_matter` (lead), `generate_panel` (lede + 4
`also`), and `generate_briefs` (6 briefs):

1. **Prompt addition:** "for this item, `source_url` = the verbatim
   `Link` of the input article it is primarily based on. It must match
   one of the input `Link` values exactly; a hallucinated URL will be
   rejected." (Same wording family as the existing `lead_source_url` /
   `DigestItem.url` rules.)
2. **`parse`:** build `valid_urls` and `source_by_url` from the
   function's article pool (panels/briefs already receive their pool;
   front matter already builds `valid_urls`). Validate every `source_url
   ∈ valid_urls` → raise `ValueError` on miss, which drives the existing
   two-attempt retry loop (`_call_with_retry`); on the second miss it
   surfaces as `GeneratorFailure` → emergency-edition fallback (existing
   behavior, unchanged). Then build the public model with
   `sources=[Source(url, source_by_url[url])]`.

This keeps **the generator as the single attribution locus** — no other
module learns about source resolution.

## Web rendering

A single shared helper in `app.js`, e.g. `sourceAffordance(sources)`,
returns the right DOM and is reused across all linkable items:

- **0 sources** (legacy editions): nothing rendered; item unchanged.
- **1 source:** an `<a href=url>` with a small muted outlet credit
  (`— Reuters ↗`).
- **2+ sources:** a superscript count; **tap is the canonical trigger**
  and toggles a small anchored popover listing each `outlet — ↗`.
  **Hover** opens it on desktop as a progressive enhancement only. The
  popover is dismissed on outside-click and Esc, anchored and small so it
  does not bury adjacent broadsheet columns.

Attachment point differs by item, because briefs have no standalone
headline:

- **Lead, panel lede, `also`:** each has a headline (`headline` /
  `lede_headline`, ≤ 8–14 words). For the 1-source case the headline text
  itself becomes the `<a>`; for 2+ the count/popover sits immediately
  after it.
- **Briefs:** a brief is `topic` (a 1–3 word category label) + `body`,
  with no headline to link. So the affordance is **appended after the
  brief body** (`— Reuters ↗`, or the count/popover) rather than wrapping
  the topic label.

Rationale for tap-canonical: the site is read mostly on touch devices
(no hover), and hover-only also fails keyboard / screen-reader users.

`style.css` additions: restrained newsprint link styling, the
superscript count, and the popover tile. No layout reflow for the
0/1-source common cases.

## Backward compatibility

- Legacy `briefings/*.json` lack `sources`; the `default_factory=list`
  makes them validate, and the web renderer treats `[]` as "plain text."
- The PDF template never references `sources`, so existing rendering and
  the emergency-fixture path are unaffected.

## Testing

- **Generator (panels):** fake `call_llm` returns a draft with a valid
  `source_url` per item → assert public `Panel` has `lede_sources` and
  per-`also` `sources` resolved to the correct outlet via
  `source_by_url`.
- **Generator (briefs):** same for the 6 briefs.
- **Generator (lead):** valid `lead_source_url` → `lead.sources`
  populated with correct outlet.
- **Anti-hallucination:** a `source_url` not in the input set → retry,
  then `GeneratorFailure` on the second miss.
- **Schema legacy-compat:** a `Briefing` JSON without any `sources`
  fields validates and yields empty lists.

These follow the existing generator-test idiom (inject `call_llm`; no
network).

## Phasing / definition of done

**Phase 1 (this build):** schema + single validated primary per item +
web rendering (0/1/2+ all handled) + tests. **Done when** a live
`./.venv/bin/python -m jina_clone.briefing.run_web --edition=morning`
produces an edition whose web view has working single-source
click-through on the lead, every panel lede, every `also`, and every
brief — and the attribution has been eyeballed for plausibility on a real
run.

**Phase 2 (follow-up, not this build):** relax the draft field to
`source_urls: list[str]`, adjust prompts to enumerate genuine
contributing sources, and rely on the popover the web already renders.
Gated on Phase 1's attribution eyeball showing the single-source mapping
is trustworthy.

## Non-goals

- No PDF link changes.
- No DB schema or query changes.
- No change to article fetch/ingestion.
- No multi-source *generation* in this build (schema/web are ready; the
  generator stays single-source).
