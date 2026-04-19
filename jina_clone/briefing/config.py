from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SectionDef:
    key: str                      # "national", "economy", "ai", "international"
    title: str                    # human-readable section title
    categories: tuple[str, ...]
    limit: int                    # max articles fetched for this section


@dataclass(frozen=True)
class BriefsDef:
    categories: tuple[str, ...]
    limit: int


@dataclass(frozen=True)
class BriefingConfig:
    sections: tuple[SectionDef, ...]
    briefs: BriefsDef
    per_source_cap: int
    front_matter_top_per_section: int
    min_articles_total: int

    def section_for_category(self, category: str) -> str | None:
        for s in self.sections:
            if category in s.categories:
                return s.key
        return None


def _require(data: dict, key: str, path: Path):
    if key not in data:
        raise KeyError(f"{path}: missing required key {key!r}")
    return data[key]


def load_briefing_config(path: Path) -> BriefingConfig:
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be a mapping")

    raw_sections = _require(data, "sections", path)
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError(f"{path}: 'sections' must be a non-empty list")

    sections: list[SectionDef] = []
    for i, item in enumerate(raw_sections):
        try:
            sections.append(
                SectionDef(
                    key=item["key"],
                    title=item["title"],
                    categories=tuple(item["categories"]),
                    limit=int(item["limit"]),
                )
            )
        except KeyError as e:
            raise ValueError(f"{path}: section {i} missing required key {e}")

    raw_briefs = _require(data, "briefs", path)
    try:
        briefs = BriefsDef(
            categories=tuple(raw_briefs["categories"]),
            limit=int(raw_briefs["limit"]),
        )
    except KeyError as e:
        raise ValueError(f"{path}: briefs missing required key {e}")

    return BriefingConfig(
        sections=tuple(sections),
        briefs=briefs,
        per_source_cap=int(_require(data, "per_source_cap", path)),
        front_matter_top_per_section=int(
            _require(data, "front_matter_top_per_section", path)
        ),
        min_articles_total=int(_require(data, "min_articles_total", path)),
    )
