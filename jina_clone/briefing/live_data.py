import asyncio
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


# ==================================================================
# Markets: Finnhub (equities + crypto) + FRED (yields + CPI)
# ==================================================================

_FINNHUB_URL = "https://finnhub.io/api/v1/quote"
_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


def _fmt_equity(price: float, dp: float | None) -> tuple[str, str | None]:
    # Under $10k: two decimals ("583.12", "1,234.56"). $10k and above:
    # whole dollars with commas ("68,241"). The threshold is chosen so
    # ETFs and equities (SPY, QQQ, TQQQ, individual stocks) keep cents
    # while crypto-scale prices drop them.
    if price < 10000:
        value = f"{price:,.2f}"
    else:
        value = f"{_round(price):,}"
    if dp is None:
        return value, None
    arrow = "▲" if dp > 0 else ("▼" if dp < 0 else "—")
    change = f"{arrow}{abs(dp):.2f}%" if arrow in "▲▼" else "—"
    return value, change


def _fmt_yield(latest_str: str, prior_str: str) -> tuple[str, str]:
    latest = float(latest_str)
    prior = float(prior_str)
    bp = _round((latest - prior) * 100)
    arrow = "▲" if bp > 0 else ("▼" if bp < 0 else "—")
    change = f"{arrow}{abs(bp)}bp" if arrow in "▲▼" else "—"
    return f"{latest:.2f}%", change


def _compute_cpi_yoy(observations: list[dict]) -> str:
    """Observations come newest-first from FRED (sort_order=desc).
    YoY = (latest - month_12_ago) / month_12_ago * 100."""
    latest = float(observations[0]["value"])
    year_ago = float(observations[12]["value"])
    yoy = (latest - year_ago) / year_ago * 100
    return f"{yoy:.1f}%"


async def _fetch_finnhub(client, api_key: str, symbol: str) -> dict:
    resp = await _http_get_json(
        client, _FINNHUB_URL,
        {"symbol": symbol, "token": api_key},
    )
    if resp.status_code >= 400:
        resp.raise_for_status()
    return resp.json()


async def _fetch_fred(
    client, api_key: str, series_id: str, limit: int,
    sort_order: str = "desc",
) -> dict:
    resp = await _http_get_json(
        client, _FRED_URL,
        {
            "series_id": series_id, "api_key": api_key,
            "file_type": "json", "limit": limit, "sort_order": sort_order,
        },
    )
    if resp.status_code >= 400:
        resp.raise_for_status()
    return resp.json()


def _dash_item(symbol: str) -> dict:
    return {"symbol": symbol, "value": "—", "change": None}


async def fetch_markets(
    *, finnhub_api_key: str, fred_api_key: str,
) -> dict:
    """Fetch SPY/QQQ/TQQQ/BTC via Finnhub + 10Y/CPI via FRED in parallel.

    Any per-symbol failure isolates to a single dashed cell. Returns a
    dict matching MarketsBlock.model_dump() with items of length 6.
    Empty keys short-circuit the corresponding cells to dashes.
    """
    async def _equity(client, sym: str) -> dict:
        display = "BTC" if sym == "BINANCE:BTCUSDT" else sym
        if not finnhub_api_key:
            return _dash_item(display)
        try:
            data = await _fetch_finnhub(client, finnhub_api_key, sym)
            value, change = _fmt_equity(data["c"], data.get("dp"))
            return {"symbol": display, "value": value, "change": change}
        except Exception as exc:
            _log.warning("finnhub %s failed: %s", sym, exc)
            return _dash_item(display)

    async def _yield10(client) -> dict:
        if not fred_api_key:
            return _dash_item("10Y")
        try:
            data = await _fetch_fred(client, fred_api_key, "DGS10", 2)
            obs = data["observations"]
            value, change = _fmt_yield(obs[0]["value"], obs[1]["value"])
            return {"symbol": "10Y", "value": value, "change": change}
        except Exception as exc:
            _log.warning("fred DGS10 failed: %s", exc)
            return _dash_item("10Y")

    async def _cpi(client) -> dict:
        if not fred_api_key:
            return _dash_item("CPI")
        try:
            data = await _fetch_fred(client, fred_api_key, "CPIAUCSL", 13)
            value = _compute_cpi_yoy(data["observations"])
            return {"symbol": "CPI", "value": value, "change": "YoY"}
        except Exception as exc:
            _log.warning("fred CPIAUCSL failed: %s", exc)
            return _dash_item("CPI")

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            _equity(client, "SPY"),
            _equity(client, "QQQ"),
            _equity(client, "TQQQ"),
            _equity(client, "BINANCE:BTCUSDT"),
            _yield10(client),
            _cpi(client),
        )
    return {"items": list(results)}
