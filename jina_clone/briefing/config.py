from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PanelDef:
    key: str
    title: str
    categories: tuple[str, ...]


@dataclass(frozen=True)
class BriefingCategories:
    panels: tuple[PanelDef, ...]
    briefs_categories: tuple[str, ...]
    min_articles_total: int

    def panel_for_category(self, category: str) -> str | None:
        for p in self.panels:
            if category in p.categories:
                return p.key
        return None

    def all_categories(self) -> list[str]:
        out: list[str] = []
        for p in self.panels:
            out.extend(p.categories)
        out.extend(self.briefs_categories)
        return out


def load_briefing_categories(path: Path) -> BriefingCategories:
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be a mapping")
    raw_panels = data.get("panels")
    if not isinstance(raw_panels, list) or not raw_panels:
        raise ValueError(f"{path}: 'panels' must be a non-empty list")
    panels: list[PanelDef] = []
    for i, item in enumerate(raw_panels):
        try:
            panels.append(
                PanelDef(
                    key=item["key"],
                    title=item["title"],
                    categories=tuple(item["categories"]),
                )
            )
        except KeyError as e:
            raise ValueError(f"{path}: panel {i} missing required key {e}")
    briefs_raw = data.get("briefs", {})
    briefs_categories = tuple(briefs_raw.get("categories", ()))
    if "min_articles_total" not in data:
        raise KeyError("min_articles_total")
    return BriefingCategories(
        panels=tuple(panels),
        briefs_categories=briefs_categories,
        min_articles_total=int(data["min_articles_total"]),
    )
