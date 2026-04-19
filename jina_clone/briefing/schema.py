from typing import Literal

from pydantic import BaseModel, Field


class WeatherStrip(BaseModel):
    temp_high: int
    temp_low: int
    conditions: str
    sunrise: str
    sunset: str
    pollen: str


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
    also: list[PanelItem] = Field(min_length=3, max_length=4)


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
    date: str
    volume: str
    location: str = "Arlington, VA"
    weather: WeatherStrip
    lead: LeadStory
    panels: list[Panel] = Field(min_length=4, max_length=4)
    pull_quote: str
    briefs: list[Brief] = Field(min_length=5, max_length=7)
    data_point: DataPoint
    on_this_day: OnThisDay
