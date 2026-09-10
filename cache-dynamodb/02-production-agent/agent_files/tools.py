"""Travel research tools backed by real APIs.

- Open-Meteo Geocoding: resolve a destination name to coordinates (no key).
- Open-Meteo Archive: last year's real monthly temperature/precipitation,
  summarized so the model can reason about the best season (no key).
- Wikipedia REST API: visa requirements and country overview summaries (no key).
- Duffel sandbox: real flight offers with prices — the volatile-data case
  for the freshness policy (prices cache for minutes, not days). Flight tool
  adapted from Ricardo Ceci's Strands course (ricardoceci/curso-strands-
  agentcore-2026). API key read from AWS Secrets Manager.

Deliberately SEQUENTIAL: geocode_destination runs first and its output
(lat/lon) feeds climate_summary. A cold agent needs an extra event-loop
cycle to discover that; the cached plan hint carries the resolved arguments,
letting a warm agent skip the discovery cycle — that is the reasoning saving.
These are real network calls, so the tool cache also saves real I/O.
"""

import datetime
import json
import os
import urllib.parse
import urllib.request

from strands import tool

_UA = {"User-Agent": "semantic-cache-sample/1.0"}

# Freshness policy: each tool declares how volatile its data is, and the
# tool cache derives the TTL from it instead of using one global value.
# Bump a tool's CACHE_VERSIONS entry to invalidate all its cached results
# at once (e.g. when the upstream source changes its schema or semantics).
TOOL_TTL_SECONDS = {
    "geocode_destination": 30 * 24 * 3600,  # coordinates: effectively immutable
    "climate_summary": 7 * 24 * 3600,       # historical climate: monthly refresh
    "wikipedia_summary": 24 * 3600,         # policies change without notice
    "search_flights": 300,                  # prices: volatile, minutes only
}
DEFAULT_TOOL_TTL = 3600  # unknown tools: assume volatile

CACHE_VERSIONS = {
    "geocode_destination": "v1",
    "climate_summary": "v1",
    "wikipedia_summary": "v1",
    "search_flights": "v1",
}


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=10) as response:  # nosemgrep: dynamic-urllib-use-detected  # nosec B310 - URL built from a fixed public API base, not user-controlled
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


_duffel_key = None


def _get_duffel_key() -> str:
    """Read the Duffel API key from Secrets Manager once per container."""
    global _duffel_key
    if _duffel_key is None:
        import boto3

        secret_arn = os.environ["DUFFEL_SECRET_ARN"]
        response = boto3.client("secretsmanager").get_secret_value(
            SecretId=secret_arn
        )
        _duffel_key = response["SecretString"]
    return _duffel_key


@tool
def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    cabin_class: str = "economy",
) -> str:
    """Search one-way flight offers with real prices (Duffel sandbox).
    Prices change constantly — results are only valid for minutes.

    Args:
        origin: Origin airport IATA code (3 letters, e.g. 'JFK', 'EZE').
        destination: Destination airport IATA code (3 letters, e.g. 'NRT').
        departure_date: Departure date in YYYY-MM-DD format.
        cabin_class: economy, premium_economy, business, or first.
    """
    payload = json.dumps({
        "data": {
            "slices": [{
                "origin": origin.strip().upper(),
                "destination": destination.strip().upper(),
                "departure_date": departure_date,
            }],
            "passengers": [{"type": "adult"}],
            "cabin_class": cabin_class,
        }
    }).encode()

    request = urllib.request.Request(
        "https://api.duffel.com/air/offer_requests?return_offers=true",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {_get_duffel_key()}",
            "Duffel-Version": "v2",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:  # nosemgrep: dynamic-urllib-use-detected  # nosec B310 - URL built from a fixed public API base (Duffel), not user-controlled
        data = json.load(response)

    offers = data.get("data", {}).get("offers", [])
    if not offers:
        return f"No flight offers found for {origin}->{destination} on {departure_date}."

    offers.sort(key=lambda o: float(o["total_amount"]))
    lines = []
    for offer in offers[:5]:
        segments = offer["slices"][0]["segments"]
        lines.append(
            f"{offer['total_amount']} {offer['total_currency']} — "
            f"{offer['owner']['name']}, departs {segments[0]['departing_at']}, "
            f"arrives {segments[-1]['arriving_at']}, {len(segments)} segment(s)"
        )
    return "Cheapest offers (sandbox data):\n" + "\n".join(lines)


ALL_TOOLS = [geocode_destination, climate_summary, wikipedia_summary, search_flights]
