"""Travel research tools backed by real public APIs (no API keys).

- Open-Meteo Geocoding: resolve a destination name to coordinates.
- Open-Meteo Archive: last year's real monthly temperature/precipitation,
  summarized so the model can reason about the best season.
- Wikipedia REST API: visa requirements and country overview summaries.

Deliberately SEQUENTIAL: geocode_destination runs first and its output
(lat/lon) feeds climate_summary. A cold agent needs an extra event-loop
cycle to discover that; the cached plan hint carries the resolved arguments,
letting a warm agent skip the discovery cycle — that is the reasoning saving.
These are real network calls, so the tool cache also saves real I/O.
"""

import datetime
import json
import urllib.parse
import urllib.request

from strands import tool

_UA = {"User-Agent": "semantic-cache-sample/1.0"}


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


@tool
def geocode_destination(place: str) -> str:
    """Resolve a destination (city or country) to coordinates and country
    info. Required first step before calling climate_summary.

    Args:
        place: Destination name, e.g. 'Tokyo' or 'Japan'.
    """
    url = (
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urllib.parse.urlencode({"name": place, "count": 1})
    )
    results = _get_json(url).get("results")
    if not results:
        return f"No location found for '{place}'."
    r = results[0]
    return json.dumps({
        "name": r.get("name"),
        "country": r.get("country"),
        "country_code": r.get("country_code"),
        "latitude": r.get("latitude"),
        "longitude": r.get("longitude"),
    })


@tool
def climate_summary(latitude: float, longitude: float) -> str:
    """Get last year's real monthly climate (temperature and rainfall) for
    coordinates, to judge the best season to visit.

    Args:
        latitude: From geocode_destination.
        longitude: From geocode_destination.
    """
    end = datetime.date.today().replace(day=1) - datetime.timedelta(days=1)
    start = end.replace(month=1, day=1) - datetime.timedelta(days=365)
    url = (
        "https://archive-api.open-meteo.com/v1/archive?"
        + urllib.parse.urlencode({
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_mean,precipitation_sum",
            "timezone": "UTC",
        })
    )
    daily = _get_json(url)["daily"]

    monthly: dict[str, dict] = {}
    for day, temp, rain in zip(
        daily["time"], daily["temperature_2m_mean"], daily["precipitation_sum"]
    ):
        month = day[:7]
        bucket = monthly.setdefault(month, {"temps": [], "rain": 0.0})
        if temp is not None:
            bucket["temps"].append(temp)
        if rain is not None:
            bucket["rain"] += rain

    lines = []
    for month in sorted(monthly)[-12:]:
        temps = monthly[month]["temps"]
        if not temps:
            continue
        avg = sum(temps) / len(temps)
        lines.append(
            f"{month}: avg {avg:.1f}C, total rain {monthly[month]['rain']:.0f}mm"
        )
    return "\n".join(lines) if lines else "No climate data available."


@tool
def wikipedia_summary(topic: str) -> str:
    """Get the Wikipedia summary for a topic. Useful for visa requirements
    (e.g. 'Visa policy of Japan') or a country overview (e.g. 'Japan').

    Args:
        topic: Wikipedia article title, e.g. 'Visa policy of Japan'.
    """
    encoded = urllib.parse.quote(topic.replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    try:
        data = _get_json(url)
    except Exception:
        return f"No Wikipedia article found for '{topic}'."
    extract = data.get("extract")
    if not extract:
        return f"No summary available for '{topic}'."
    return f"{data.get('title', topic)}: {extract}"


ALL_TOOLS = [geocode_destination, climate_summary, wikipedia_summary]
