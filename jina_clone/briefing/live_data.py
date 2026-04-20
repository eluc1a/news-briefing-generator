import json
import logging
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import httpx


_log = logging.getLogger(__name__)


# -------- Arlington, VA coordinates (matches Briefing.location default) --------

ARLINGTON_LAT = 38.8816
ARLINGTON_LON = -77.0910
LOCAL_TZ = ZoneInfo("America/New_York")


# -------- Weathercode → monochrome glyph --------
# Text-style unicode codepoints (no U+FE0F selector) render as grayscale
# in the existing serif font stack, not as color emoji.

_WEATHER_GLYPH: dict[int, str] = {
    200: "⚡",   # thunderstorm
    300: "☂",   # drizzle
    500: "☂",   # rain
    600: "❄",   # snow
    700: "☁",   # atmosphere (mist/fog/haze) — fallback to cloud
    800: "☀",   # clear
    801: "⛅",  # few clouds
    802: "☁",   # scattered clouds
    803: "☁",   # broken clouds
    804: "☁",   # overcast
}


def weather_glyph(code: int) -> str:
    """Map an OpenWeatherMap weathercode to a monochrome unicode glyph.

    Direct match first, then 100-range bucket, then default ☀.
    """
    if code in _WEATHER_GLYPH:
        return _WEATHER_GLYPH[code]
    bucket = (code // 100) * 100
    return _WEATHER_GLYPH.get(bucket, "☀")


# -------- Cache helper --------

_CACHE_STALE_SECONDS = 36 * 3600


def _cache_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < _CACHE_STALE_SECONDS


# -------- HTTP indirection (monkeypatched in tests) --------

async def _http_get_json(
    client: httpx.AsyncClient, url: str, params: dict,
) -> httpx.Response:
    return await client.get(url, params=params, timeout=10.0)


# -------- Weather fetch --------

_OWM_CURRENT = "https://api.openweathermap.org/data/2.5/weather"
_OWM_FORECAST = "https://api.openweathermap.org/data/2.5/forecast"


def _fmt_clock(epoch: int) -> str:
    """Epoch UTC → local ET clock string like '6:24' (no leading zero)."""
    dt = datetime.fromtimestamp(epoch, tz=LOCAL_TZ)
    return dt.strftime("%-I:%M")


def _fmt_daylight(sunrise_epoch: int, sunset_epoch: int) -> str:
    seconds = sunset_epoch - sunrise_epoch
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m"


def _fmt_hour_label(epoch: int) -> str:
    """Epoch UTC → lowercase 12-hour label like '11am', '2pm'. Noon = '12pm'."""
    dt = datetime.fromtimestamp(epoch, tz=LOCAL_TZ)
    return dt.strftime("%-I%p").lower()


def _round(v: float) -> int:
    """Round half-up. Python's builtin round() uses banker's rounding
    (round-half-to-even), so round(62.5) == 62 — surprising for
    temperatures, prices, and yields. Use this instead throughout
    live_data.
    """
    return math.floor(v + 0.5)


def _parse_owm(current: dict, forecast: dict) -> dict:
    slots = []
    for entry in forecast["list"][:4]:
        slots.append({
            "time_label": _fmt_hour_label(entry["dt"]),
            "temp_f": _round(entry["main"]["temp"]),
            "precip_pct": _round(entry.get("pop", 0) * 100),
            "code": entry["weather"][0]["id"],
        })
    return {
        "temp_high": _round(current["main"]["temp_max"]),
        "temp_low": _round(current["main"]["temp_min"]),
        "conditions": current["weather"][0]["description"],
        "sunrise": _fmt_clock(current["sys"]["sunrise"]),
        "sunset": _fmt_clock(current["sys"]["sunset"]),
        "daylight": _fmt_daylight(
            current["sys"]["sunrise"], current["sys"]["sunset"],
        ),
        "hourly": {"slots": slots},
    }


async def fetch_weather(
    *,
    cache_path: Path,
    owm_api_key: str,
    stub: Callable[[], dict],
) -> dict:
    """Fetch current weather + 4 × 3h forecast slots for Arlington, VA.

    On HTTP failure, fall back to the on-disk cache at `cache_path` if it
    exists and is < 36 h old. If the cache is missing or stale, fall
    through to `stub()` and log a warning.

    An empty `owm_api_key` short-circuits to `stub()` — useful for dev
    machines without a key.
    """
    if not owm_api_key:
        _log.warning("WEATHER_API_KEY unset; using stub weather")
        return stub()

    params_common = {
        "lat": ARLINGTON_LAT, "lon": ARLINGTON_LON,
        "units": "imperial", "appid": owm_api_key,
    }
    try:
        async with httpx.AsyncClient() as client:
            cur_resp = await _http_get_json(client, _OWM_CURRENT, params_common)
            # The gate exists because bare httpx.Response(200, ...) constructed in
            # tests lacks an associated Request object, so calling raise_for_status()
            # on a 2xx in-test raises RuntimeError. Production responses always carry
            # a request; 4xx/5xx still raises normally.
            if cur_resp.status_code >= 400:
                cur_resp.raise_for_status()
            fcst_resp = await _http_get_json(
                client, _OWM_FORECAST, {**params_common, "cnt": 4},
            )
            if fcst_resp.status_code >= 400:
                fcst_resp.raise_for_status()
        parsed = _parse_owm(cur_resp.json(), fcst_resp.json())
    except Exception as exc:
        _log.warning("OWM fetch failed (%s); trying cache", exc)
        if _cache_is_fresh(cache_path):
            _log.warning("falling back to cached weather (%s)", cache_path)
            return json.loads(cache_path.read_text())
        _log.warning(
            "stale weather cache at %s (or missing); using stub", cache_path,
        )
        return stub()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(parsed))
    return parsed
