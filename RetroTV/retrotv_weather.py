"""Location, station observations, and forecasts for RetroTV weather."""

from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from threading import Thread
import time
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOCATION_FILE = "weather-location.txt"
GEO_URL = "https://ipwho.is/?fields=success,city,region_code,country_code,latitude,longitude"
GEOMET_URL = "https://api.weather.gc.ca/collections/swob-realtime/items"
METAR_URL = "https://aviationweather.gov/api/data/metar"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEO_TTL = 24 * 60 * 60

CONDITIONS = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Rain showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorms", 96: "Thunderstorms with hail", 99: "Thunderstorms with hail",
}
SWOB_FIELDS = (
    "obs_date_tm", "stn_nam-value", "air_temp", "rel_hum",
    "avg_wnd_spd_10m_pst2mts", "avg_wnd_dir_10m_pst2mts",
    "avg_wnd_spd_10m_pst10mts", "avg_wnd_dir_10m_pst10mts",
)
DATA_ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError)


def json_at(reader, context, url, **query):
    if query:
        url += "?" + urlencode(query)
    return json.loads(reader(url, context))


def place(lat, lon, label, country, located=0):
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("weather location coordinates out of range")
    return {"lat": lat, "lon": lon, "label": str(label)[:80],
            "country": str(country).upper(), "located": int(located)}


def location_spec(folder):
    try:
        return (folder / LOCATION_FILE).read_text(encoding="utf-8-sig").splitlines()[0].strip() or "auto"
    except (FileNotFoundError, IndexError):
        return "auto"


def locate(spec, previous, reader, context):
    if spec.casefold() != "auto":
        parts = [part.strip() for part in spec.split("|")]
        lat, lon = parts[0].split(",")
        return place(lat, lon, parts[1] if len(parts) > 1 else "Local weather",
                     parts[2] if len(parts) > 2 else "")

    prior = (previous or {}).get("place")
    if prior and 0 <= time.time() - prior["located"] < GEO_TTL:
        return prior
    data = json_at(reader, context, GEO_URL)
    if data.get("success") is not True:
        raise ValueError("IP location service did not return a city")
    city, region = data.get("city"), data.get("region_code")
    label = ", ".join(part for part in (city, region) if part) or data["country_code"]
    return place(data["latitude"], data["longitude"], label, data["country_code"], time.time())


def km_between(location, lat, lon):
    source_lat = math.radians(location["lat"])
    dest_lat = math.radians(lat)
    dl = math.radians(lon - location["lon"])
    part = math.sin((dest_lat - source_lat) / 2)**2 + math.cos(source_lat) * math.cos(dest_lat) * math.sin(dl / 2)**2
    return 12742 * math.asin(math.sqrt(min(1, part)))


def bounds(location, radius_km):
    lat, lon = location["lat"], location["lon"]
    span_lat = radius_km / 110
    south, north = max(-90, lat - span_lat), min(90, lat + span_lat)
    span_lon = min(180, span_lat / max(.001, math.cos(math.radians(max(abs(south), abs(north))))))
    if span_lon >= 180:
        return [(south, -180, north, 180)]
    west, east = lon - span_lon, lon + span_lon
    if west < -180:
        return [(south, -180, north, east), (south, west + 360, north, 180)]
    if east > 180:
        return [(south, west, north, 180), (south, -180, north, east - 360)]
    return [(south, west, north, east)]


def observation(name, source, at, distance, temp, humidity=None, wind=None, direction=None):
    return {"station": name, "source": source, "at": at, "distance": distance, "temp": temp,
            "humidity": humidity, "wind": wind, "direction": direction}


def timestamp(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def swob(location, reader, context, now):
    def utc_text(epoch):
        return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    candidates = []
    for south, west, north, east in bounds(location, 78):
        records = json_at(reader, context, GEOMET_URL, f="json",
                          bbox=",".join(f"{n:.4f}" for n in (west, south, east, north)),
                          datetime=utc_text(now-2*3600) + "/" + utc_text(now),
                          sortby="-obs_date_tm", limit=800, properties=",".join(SWOB_FIELDS))
        for row in records["features"]:
            p = row["properties"]
            temp = p.get("air_temp")
            name = p.get("stn_nam-value")
            if not name or type(temp) not in (int, float):
                continue
            lon, lat = row["geometry"]["coordinates"][:2]
            distance = km_between(location, lat, lon)
            at = timestamp(p["obs_date_tm"])
            if distance > 78 or not 0 <= now-at <= 2*3600:
                continue
            wind = p.get("avg_wnd_spd_10m_pst2mts")
            direction = p.get("avg_wnd_dir_10m_pst2mts")
            if wind is None:
                wind = p.get("avg_wnd_spd_10m_pst10mts")
                direction = p.get("avg_wnd_dir_10m_pst10mts")
            candidates.append(observation(name, "ECCC", at, distance, temp, p.get("rel_hum"), wind, direction))
    return min(candidates, key=lambda report: (report["distance"], -report["at"]), default=None)


def metar(location, reader, context, now):
    candidates = []
    for box in bounds(location, 160):
        records = json_at(reader, context, METAR_URL, format="json",
                          bbox=",".join(f"{n:.4f}" for n in box))
        for row in records:
            temp, at = row.get("temp"), row.get("obsTime")
            if type(temp) not in (int, float) or type(at) not in (int, float) or not 0 <= now-at <= 2.5*3600:
                continue
            distance = km_between(location, row["lat"], row["lon"])
            if distance > 160:
                continue
            name = row.get("name") or row["icaoId"]
            speed = row.get("wspd")
            candidates.append(observation(name, "METAR / NOAA", at, distance, temp, None,
                                          speed*1.852 if speed is not None else None, row.get("wdir")))
    return min(candidates, key=lambda report: (report["distance"], -report["at"]), default=None)


def forecast(location, reader, context):
    return json_at(reader, context, FORECAST_URL, latitude=location["lat"], longitude=location["lon"],
                   timezone="auto", forecast_days=4,
                   current="temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m",
                   daily="weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max")


def direction_label(degrees):
    if not isinstance(degrees, (int, float)):
        return "VAR" if degrees == "VRB" else ""
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((degrees + 22.5) // 45) % 8]


def readings(report, us):
    result = ["Temperature  " + temperature(report["temp"], us)]
    if report["humidity"] is not None:
        result.append("Humidity  {:.0f}%".format(report["humidity"]))
    if report["wind"] is not None:
        speed = report["wind"]
        bearing = direction_label(report["direction"])
        if speed == 0:
            result.append("Wind  Calm")
        else:
            speed = f"{speed/1.609344:.0f} mph" if us else f"{speed:.0f} km/h"
            result.append("Wind  " + " ".join(part for part in (bearing, speed) if part))
    return result


def temperature(value, us):
    return f"{round(value * 9 / 5 + 32)} F" if us else f"{round(value)} C"


def conditions_and_forecast(location, station, model):
    us = location["country"] == "US"
    try:
        tz = ZoneInfo(model["timezone"])
    except (KeyError, ZoneInfoNotFoundError):
        tz = timezone.utc
    if station:
        km = station["distance"]
        dist = f"{km/1.609344:.0f} mi" if us else f"{km:.0f} km"
        observed = datetime.fromtimestamp(station["at"], tz).strftime("%b %d %I:%M %p %Z")
        sections = [["Current conditions", [station["station"] + " / " + dist,
                    station["source"] + " / " + observed, *readings(station, us)]]]
    else:
        cur = model["current"]
        at = datetime.fromisoformat(cur["time"]).replace(tzinfo=tz)
        estimate = observation(None, None, None, None, cur["temperature_2m"], cur.get("relative_humidity_2m"),
                               cur.get("wind_speed_10m"), cur.get("wind_direction_10m"))
        sections = [["Model conditions", [at.strftime("%b %d %I:%M %p %Z") if tz != timezone.utc
                    else at.strftime("%b %d %I:%M %p") + " local",
                    CONDITIONS.get(cur.get("weather_code"), "Current estimate"), *readings(estimate, us)]]]

    daily = model.get("daily", {})
    fields = ("time", "weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_probability_max")
    for number, (day, code, high, low, precip) in enumerate(zip(*(daily.get(key, []) for key in fields))):
        name = "Today" if number == 0 else date.fromisoformat(day).strftime("%a %b %d")
        rows = [CONDITIONS.get(code, "Forecast")]
        if high is not None and low is not None:
            rows.append("High " + temperature(high, us) + " / Low " + temperature(low, us))
        if precip is not None:
            rows.append(f"Precip chance  {precip:.0f}%")
        sections.append([name, rows])
    sections.append(["Open-Meteo forecast" if len(sections) > 1 else "Forecast unavailable", []])
    return sections


def fetch(spec, previous, reader, context, normalize):
    location = locate(spec, previous, reader, context)
    now = int(time.time())
    results = {}

    def request(key, get, *args):
        try:
            results[key] = get(location, reader, context, *args)
        except DATA_ERRORS as exc:
            print("{} weather unavailable: {}".format(key, exc), flush=True)

    metric_location = location["country"] == "CA" or (
        not location["country"] and 41 <= location["lat"] <= 84 and -141 <= location["lon"] <= -52)
    station_call = swob if metric_location else metar
    jobs = [Thread(target=request, args=(name, get, *args), daemon=True)
            for name, get, args in (("forecast", forecast, ()), ("station", station_call, (now,)))]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join()
    if not results.get("station") and metric_location:
        request("station", metar, now)
    station, model = results.get("station"), results.get("forecast") or {}
    if not station and not model:
        raise ValueError("no nearby station or model data available")
    sections = conditions_and_forecast(location, station, model)
    print("Weather updated for {} using {}.".format(
        location["label"], station["station"] + " / " + station["source"] if station else "Open-Meteo"), flush=True)
    return {"updated": now, "spec": spec, "place": location, "station": station,
            "title": normalize(location["label"]) or "Local weather",
            "sections": [[normalize(title), [normalize(row) for row in rows]] for title, rows in sections],
            "legacy": False}


def load(path, spec, normalize):
    try:
        with Path(path).open("rb") as file:
            data = json.loads(file.read(16384))
        if data["spec"] != spec or type(data["updated"]) is not int or data["updated"] <= 0:
            return None
        if not isinstance(data["sections"], list) or not 1 <= len(data["sections"]) <= 6:
            return None
        sections = []
        for title, rows in data["sections"]:
            if not isinstance(title, str) or not isinstance(rows, list) or len(rows) > 6:
                return None
            sections.append([normalize(title), [normalize(row) for row in rows]])
        prior = data["place"]
        data["place"] = place(prior["lat"], prior["lon"], prior["label"], prior["country"], prior["located"])
        data.update(title=normalize(data["title"]), sections=sections, legacy=False)
        return data
    except DATA_ERRORS:
        return None
