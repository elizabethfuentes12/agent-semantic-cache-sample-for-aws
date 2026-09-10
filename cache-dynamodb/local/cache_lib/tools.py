"""Travel research tools backed by real public APIs.

Four tools the agent can call:
- geocode_destination: destination name to coordinates (Open-Meteo, no key).
- climate_summary: last year's monthly climate for coordinates (Open-Meteo, no key).
- wikipedia_summary: a Wikipedia article summary (Wikipedia REST, no key).
- search_flights: one-way flight offers with live prices (Duffel sandbox, key).

Each tool's docstring and type hints are the whole contract the model sees:
Strands turns the first docstring line into the tool description and the Args
section into the parameter descriptions. The descriptions say only what a tool
does and what its inputs are. They do not mention other tools, call order, or
anything about caching or TTLs. The model decides the order on its own from the
parameter types (a step that needs latitude/longitude will call the tool that
produces them first), and the cache is invisible to the model: it lives in the
hooks, not in the tools.

The Duffel key is read from the DUFFEL_API_KEY environment variable, or from
Secrets Manager if DUFFEL_SECRET_NAME is set. The other three tools need no key.
"""

import datetime
import json
import os
import urllib.parse
import urllib.request

from strands import tool

_UA = {"User-Agent": "semantic-cache-local/1.0"}


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


@tool
def geocode_destination(place: str) -> str:
    """Look up the geographic coordinates and country of a place.

    Args:
        place: A city or country name, for example 'Tokyo' or 'Japan'.
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
    """Get the monthly average temperature and rainfall over the last year at a
    location, to judge the best season to visit.

    Args:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
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
    """Get the summary of a Wikipedia article, for facts like visa policies or a
    country overview.

    Args:
        topic: A Wikipedia article title, for example 'Visa policy of Japan'.
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
    """Read the Duffel API key from the environment or Secrets Manager."""
    global _duffel_key
    if _duffel_key is not None:
        return _duffel_key

    env_key = os.environ.get("DUFFEL_API_KEY", "").strip()
    if env_key:
        _duffel_key = env_key
        return _duffel_key

    secret_name = os.environ.get("DUFFEL_SECRET_NAME", "").strip()
    if secret_name:
        import boto3

        response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_name)
        _duffel_key = response["SecretString"]
        return _duffel_key

    raise RuntimeError(
        "No Duffel API key. Set DUFFEL_API_KEY (free sandbox key from "
        "duffel.com) or DUFFEL_SECRET_NAME. The other three tools work "
        "without it."
    )


@tool
def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    cabin_class: str = "economy",
) -> str:
    """Search one-way flight offers with current prices between two airports.

    Args:
        origin: Origin airport IATA code (3 letters, for example 'JFK').
        destination: Destination airport IATA code (3 letters, for example 'NRT').
        departure_date: Departure date in YYYY-MM-DD format.
        cabin_class: One of economy, premium_economy, business, or first.
    """
    try:
        key = _get_duffel_key()
    except RuntimeError as exc:
        return str(exc)

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
            "Authorization": f"Bearer {key}",
            "Duffel-Version": "v2",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.load(response)

    offers = data.get("data", {}).get("offers", [])
    if not offers:
        return f"No flight offers found for {origin}->{destination} on {departure_date}."

    offers.sort(key=lambda o: float(o["total_amount"]))
    lines = []
    for offer in offers[:5]:
        segments = offer["slices"][0]["segments"]
        lines.append(
            f"{offer['total_amount']} {offer['total_currency']}, "
            f"{offer['owner']['name']}, departs {segments[0]['departing_at']}, "
            f"arrives {segments[-1]['arriving_at']}, {len(segments)} segment(s)"
        )
    return "Cheapest offers (sandbox data):\n" + "\n".join(lines)


ALL_TOOLS = [geocode_destination, climate_summary, wikipedia_summary, search_flights]
