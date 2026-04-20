import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from jina_clone.briefing.live_data import (
    _WEATHER_GLYPH,
    fetch_weather,
    weather_glyph,
)


# -------- fixtures --------

_OWM_CURRENT = {
    "main": {"temp_max": 71.4, "temp_min": 49.2, "temp": 60.0},
    "weather": [{"description": "partly cloudy", "id": 801}],
    "sys": {
        # 2026-04-20 10:24 UTC → 6:24 ET (standard); pick a date that
        # is unambiguously EDT (DST on in April) so the conversion is 4 h back.
        "sunrise": 1745144640,  # 2026-04-20 06:24:00 EDT (10:24 UTC)
        "sunset":  1745194080,  # 2026-04-20 20:08:00 EDT (00:08 next UTC)
    },
}

_OWM_FORECAST = {
    "list": [
        {"dt": 1745164800, "main": {"temp": 62.5}, "pop": 0.10,
         "weather": [{"id": 800}]},  # 2026-04-20 12:00 EDT → "12pm"
        {"dt": 1745175600, "main": {"temp": 68.1}, "pop": 0.20,
         "weather": [{"id": 801}]},  # 15:00 EDT → "3pm"
        {"dt": 1745186400, "main": {"temp": 71.0}, "pop": 0.40,
         "weather": [{"id": 500}]},  # 18:00 EDT → "6pm"
        {"dt": 1745197200, "main": {"temp": 60.3}, "pop": 0.20,
         "weather": [{"id": 802}]},  # 21:00 EDT → "9pm"
    ],
}


def _stub() -> dict:
    return {
        "temp_high": 0, "temp_low": 0, "conditions": "stub",
        "sunrise": "—", "sunset": "—", "daylight": "—",
        "hourly": {"slots": [
            {"time_label": "—", "temp_f": 0, "precip_pct": 0, "code": 800}
        ] * 4},
    }


# -------- glyph lookup --------

def test_weather_glyph_direct_match():
    assert weather_glyph(800) == "☀"
    assert weather_glyph(802) == "☁"

def test_weather_glyph_range_fallback():
    # 201 falls into the 200s thunderstorm range.
    assert weather_glyph(201) == _WEATHER_GLYPH[200]

def test_weather_glyph_unknown_returns_clear():
    assert weather_glyph(99999) == "☀"


# -------- fetch_weather happy path --------

async def test_fetch_weather_parses_owm(tmp_path):
    cache = tmp_path / "weather.json"

    async def fake_get(client, url, params):
        if "forecast" in url:
            return httpx.Response(200, json=_OWM_FORECAST)
        return httpx.Response(200, json=_OWM_CURRENT)

    with patch(
        "jina_clone.briefing.live_data._http_get_json",
        side_effect=fake_get,
    ):
        result = await fetch_weather(
            cache_path=cache, owm_api_key="test", stub=_stub,
        )

    assert result["temp_high"] == 71
    assert result["temp_low"] == 49
    assert result["conditions"] == "partly cloudy"
    assert result["sunrise"] == "6:24"
    assert result["sunset"] == "8:08"
    assert result["daylight"] == "13h 44m"
    assert len(result["hourly"]["slots"]) == 4
    # time_label is lowercase 12h without leading zero.
    assert result["hourly"]["slots"][0]["time_label"] in {"12pm", "noon"}
    assert result["hourly"]["slots"][0]["temp_f"] == 63  # rounded
    assert result["hourly"]["slots"][0]["precip_pct"] == 10
    assert result["hourly"]["slots"][0]["code"] == 800
    # Cache was written.
    assert cache.exists()
    assert json.loads(cache.read_text())["temp_high"] == 71


# -------- cache fallback --------

async def test_fetch_weather_falls_back_to_cache(tmp_path, caplog):
    cache = tmp_path / "weather.json"
    cached_payload = {
        "temp_high": 55, "temp_low": 33, "conditions": "cached",
        "sunrise": "6:25", "sunset": "7:49", "daylight": "13h 24m",
        "hourly": {"slots": [
            {"time_label": "8am", "temp_f": 40, "precip_pct": 0, "code": 800}
        ] * 4},
    }
    cache.write_text(json.dumps(cached_payload))

    async def fake_fail(client, url, params):
        raise httpx.ConnectError("offline")

    with patch(
        "jina_clone.briefing.live_data._http_get_json",
        side_effect=fake_fail,
    ), caplog.at_level("WARNING"):
        result = await fetch_weather(
            cache_path=cache, owm_api_key="test", stub=_stub,
        )

    assert result == cached_payload
    assert any("falling back to cached weather" in r.message for r in caplog.records)


# -------- stale cache → stub --------

async def test_fetch_weather_stale_cache_falls_through_to_stub(tmp_path, caplog):
    cache = tmp_path / "weather.json"
    cache.write_text(json.dumps({"temp_high": 1}))
    # Backdate mtime > 36h.
    old = time.time() - (40 * 3600)
    import os
    os.utime(cache, (old, old))

    async def fake_fail(client, url, params):
        raise httpx.ConnectError("offline")

    with patch(
        "jina_clone.briefing.live_data._http_get_json",
        side_effect=fake_fail,
    ), caplog.at_level("WARNING"):
        result = await fetch_weather(
            cache_path=cache, owm_api_key="test", stub=_stub,
        )

    assert result["conditions"] == "stub"
    assert any("stale weather cache" in r.message for r in caplog.records)


# -------- missing key → stub --------

async def test_fetch_weather_missing_api_key_uses_stub(tmp_path):
    cache = tmp_path / "weather.json"
    result = await fetch_weather(
        cache_path=cache, owm_api_key="", stub=_stub,
    )
    assert result["conditions"] == "stub"
