from typing import Literal

from pydantic import BaseModel, Field

# Shared with generator.py — keep both files in sync by importing
# these constants rather than duplicating the bounds.
PANEL_ALSO_COUNT = 3   # will bump to 4 in the density phase (Task 9)
BRIEFS_COUNT_MIN = 5   # will tighten to 6-exact in Task 9
BRIEFS_COUNT_MAX = 6


class WeatherStrip(BaseModel):
    temp_high: int
    temp_low: int
    conditions: str
    sunrise: str
    sunset: str
    daylight: str   # e.g. "13h 24m"; replaces the former `pollen` field


class HourlySlot(BaseModel):
    time_label: str   # e.g. "11am", "2pm"
    temp_f: int
    precip_pct: int   # 0-100
    code: int         # OpenWeatherMap weathercode (see live_data._WEATHER_GLYPH)


class HourlyForecast(BaseModel):
    slots: list[HourlySlot] = Field(min_length=4, max_length=4)


class LeadStory(BaseModel):
    headline: str
    deck: str
    body: str
    at_a_glance: list[str] = Field(min_length=3, max_length=4)


class PanelItem(BaseModel):
    headline: str
    body: str


class Panel(BaseModel):
    section: Literal[
        "AI & Technology",
        "National",
        "Economy & Markets",
        "International",
    ]
    lede_headline: str
    lede_body: str
    also: list[PanelItem] = Field(min_length=PANEL_ALSO_COUNT, max_length=PANEL_ALSO_COUNT)


class Brief(BaseModel):
    topic: str
    body: str


class DataPoint(BaseModel):
    value: str
    context: str


class OnThisDay(BaseModel):
    year_and_title: str
    body: str


class Briefing(BaseModel):
    title: str
    date: str
    volume: str
    location: str = "Arlington, VA"
    weather: WeatherStrip
    hourly: HourlyForecast
    lead: LeadStory
    panels: list[Panel] = Field(min_length=4, max_length=4)
    pull_quote: str
    briefs: list[Brief] = Field(min_length=BRIEFS_COUNT_MIN, max_length=BRIEFS_COUNT_MAX)
    data_point: DataPoint
    on_this_day: OnThisDay


class FrontMatter(BaseModel):
    """Internal: output of the front-matter Gemini call.

    `lead_source_url` is the `link` field of the input article the
    model chose as the lead. Used to dedupe panel/briefs calls.
    """
    lead: LeadStory
    lead_source_url: str
    pull_quote: str
    data_point: DataPoint
    on_this_day: OnThisDay
