# Per-visitor weather/location on themorningfox.com (deferred option)

**Status:** deferred — captured for future reference, not scheduled.
**Date:** 2026-06-18

## Motivation

The public site shows the briefing's weather and a fixed `Arlington, VA`
location (the author's, where the paper is printed). For other readers on
themorningfox.com that's not their weather. Two ways to address it were
considered: (a) hide the weather + location on the web mirror, or (b)
geolocate per visitor. We chose to **keep both as-is** for now (the paper
is a personal broadsheet and the Arlington dateline is editorially fine),
and write the geolocation option down here in case it's wanted later.

## Why it isn't free

The OpenWeatherMap key (`WEATHER_API_KEY`) already exists, but it runs
**server-side** — the Python briefing job reads it from `.env` at
generation time. themorningfox.com is a **static site** (nginx serving
files from `web/`, no app backend). So a visitor's browser can't reach
OWM with that key without either:

- **(a) exposing the key in client JS** — scrapeable by anyone viewing
  source; invites abuse and burns the rate limit. Not acceptable.
- **(b) a small server-side proxy** that holds the key and forwards
  lat/lon to OWM — the clean approach, but it's **new infrastructure** on
  a currently static-only site.

## Sketch if we build it (option b)

1. **Proxy endpoint** — a minimal `GET /api/weather?lat=&lon=` that calls
   OWM with the server's key and returns the same parsed shape
   `live_data._parse_owm` already produces (temp_high/temp_low,
   conditions, sunrise/sunset, hourly slots). Options for hosting it:
   - a tiny FastAPI route (the extractor service already runs uvicorn),
     reverse-proxied by nginx under `/api/`; or
   - reuse the existing extractor container and add the route there.
   Rate-limit per IP and cache responses by rounded lat/lon for a few
   minutes to protect the OWM quota.
2. **Browser geolocation** — `navigator.geolocation.getCurrentPosition`
   in `web/app.js`, behind a permission prompt. On grant, call the proxy
   and replace `renderWeather`'s data with the visitor's. On denial or
   error, fall back to the published edition's Arlington weather (current
   behavior) — never block the page.
3. **Location label** — reverse-geocode the coords to "City, ST" for the
   masthead. OWM's reverse-geocoding endpoint works, or keep the
   published `location` as the fallback. Note the masthead `location`
   currently comes from `Briefing.location` (schema default
   `"Arlington, VA"`); the web override would be client-side only, leaving
   the print edition untouched.
4. **Privacy** — geolocation is opt-in via the browser prompt; don't
   persist coordinates, and don't send them anywhere but our proxy.

## Cost / tradeoff

Meaningful: a new served endpoint + key custody + permission UX +
reverse-geocode + fallbacks, all for what is essentially a personal
broadsheet mirrored online. The weather is also baked per edition
(twice daily); a live per-visitor path is a different model from the rest
of the site. Revisit only if the site gains a real multi-reader audience.

## Related

- Weather fetch + parse: `jina_clone/briefing/live_data.py`
  (`fetch_weather`, `_parse_owm`). High/low are the max/min across the
  next ~24h of forecast slots — a forward outlook, labeled "Next 24h" in
  the UI as of 2026-06-18 (commit `ae69b34`).
- Web render: `web/app.js` `renderWeather`, masthead `location` in
  `renderMasthead`.
