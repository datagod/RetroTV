"""Live launch schedules, ISS passes and NASA mission headlines."""

from datetime import datetime
import json
import math
from pathlib import Path
from threading import Thread
import time
import xml.etree.ElementTree as ET

import retrotv_weather

LAUNCH_URL = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/"
ISS_URL = "https://iss-api.polluxlabs.io/iss-pass"
ISS_FALLBACK = "https://iss-in.space/api/passes/{:.4f}/{:.4f}"
NASA_FEEDS = {
    "NASA ISS": "https://www.nasa.gov/rss/dyn/shuttle_station.rss",
    "NASA ARTEMIS": "https://www.nasa.gov/missions/artemis/feed/",
}
SOURCE_TTL = 20 * 60
FAILURE_TTL = 5 * 60
DATA_ERRORS = (OSError, ValueError, TypeError, AttributeError, IndexError, KeyError, ET.ParseError)


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("time is missing a timezone")
    return int(result.timestamp())


def when(value):
    return time.strftime("%a %b %d %I:%M %p %Z", time.localtime(value))


def launches(reader, context, normalize, now):
    raw = retrotv_weather.json_at(reader, context, LAUNCH_URL, mode="normal", limit=10)
    results = []
    for item in raw["results"]:
        if not item.get("net"):
            continue
        net = stamp(item["net"])
        status = item.get("status") or {}
        if net <= now or status.get("id") in (3, 4, 6, 7) or not item.get("name"):
            continue
        precision = (item.get("net_precision") or {}).get("abbrev", "").upper()
        pad = (item.get("pad") or {}).get("location") or {}
        results.append({"net": net, "name": normalize(item["name"]), "site": normalize(pad.get("name") or ""),
                        "status": normalize(status.get("abbrev") or "TBC"), "go": status.get("id") == 1,
                        "timed": precision in ("SEC", "MIN", "HR"), "approx": precision == "HR"})
    return sorted(results, key=lambda item: item["net"])


def passes(reader, context, location):
    lat, lon = location["lat"], location["lon"]
    try:
        raw = retrotv_weather.json_at(reader, context, ISS_URL, lat=f"{lat:.4f}", lon=f"{lon:.4f}",
                                     n=5, days_ahead=10, min_elevation=15, visible_only="true")
        if raw.get("tle_stale") or not -5 <= int(time.time()) - stamp(raw["generated_at"]) < 2*3600:
            raise ValueError("latest orbit prediction is stale")
        items = []
        for item in raw["passes"]:
            if item.get("visible") and item.get("visible_start"):
                items.append({"start": stamp(item["visible_start"]), "end": stamp(item["visible_end"]),
                              "peak": int(round(item["culmination"]["elevation_deg"])),
                              "rise": item["rise"]["compass"], "set": item["set"]["compass"]})
        return {"mode": "visible", "source": "Pollux Labs", "items": items}
    except DATA_ERRORS:
        raw = retrotv_weather.json_at(reader, context, ISS_FALLBACK.format(lat, lon))
        items = []
        for item in raw:
            peak = item["culminate"]["degrees"]
            if peak >= 15:
                items.append({"start": stamp(item["rise"]["time"]), "end": stamp(item["set"]["time"]),
                              "peak": int(round(peak)), "rise": item["rise"]["direction"],
                              "set": item["set"]["direction"]})
        return {"mode": "overhead", "source": "ISS-in.space", "items": items[:6]}


def mission_news(reader, context, parse):
    feeds = []
    for label, url in NASA_FEEDS.items():
        try:
            feeds.append((label, parse(reader(url, context))[:3]))
        except DATA_ERRORS as error:
            print("{} unavailable: {}".format(label, error), flush=True)
    if not feeds:
        raise ValueError("no NASA mission headlines")
    seen = set()
    result = []
    for index in range(3):
        for label, stories in feeds:
            if index < len(stories) and stories[index].casefold() not in seen:
                result.append([label, stories[index]])
                seen.add(stories[index].casefold())
    return result


def countdown(seconds):
    minutes = max(0, math.ceil(seconds/60))
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    return ("{}D ".format(days) if days else "") + "{}H {:02d}M".format(hours, minutes)


def report(state, now):
    data = state["feeds"]
    sections = []
    events = [event for event in data.get("launches", []) if event["net"] > now]
    if events:
        first = events[0]
        rows = [first["name"]]
        if first["timed"]:
            rows.append(("Approx. " if first["approx"] else "") + when(first["net"]))
            if first["go"]:
                rows.append(("Est. " if first["approx"] else "") + "T-" + countdown(first["net"]-now))
        else:
            rows.append("Date or time to be confirmed")
        if first["site"]:
            rows.append(first["site"])
        rows.append("Launch Library 2 / " + first["status"])
        if "launches" in state["stale"]:
            rows.append("Last available schedule")
        sections.append(["Next rocket launch", rows])
        for event in events[1:3]:
            date = when(event["net"]) if event["timed"] else "Time to be confirmed"
            sections.append(["Also scheduled", [event["name"], date]])
    else:
        sections.append(["Next rocket launch", ["Launch schedule unavailable or no dated launch"]])

    predicted = data.get("passes")
    location = state.get("place")
    if predicted and location:
        mode = predicted["mode"]
        heading = "ISS visible passes" if mode == "visible" else "ISS overhead passes"
        future = [p for p in predicted["items"] if p["end"] > now]
        rows = [location["label"] + " / " + predicted["source"]]
        if "passes" in state["stale"]:
            rows.append("Last available predictions")
        if mode == "overhead":
            rows.append("Optical visibility unconfirmed")
        if not future:
            rows.append("No upcoming passes in this forecast")
        sections.append([heading, rows])
        for item in future[:3]:
            duration = (item["end"] - item["start"])//60
            sections.append([when(item["start"]), [
                f"Peak {item['peak']} deg / {duration} min",
                f"Rise {item['rise']} / Set {item['set']}",
            ]])
    else:
        sections.append(["ISS passes", ["Local predictions unavailable"]])

    stories = data.get("mission", [])
    for number, (source, title) in enumerate(stories[:5]):
        heading = source if "mission" not in state["stale"] or number else source + " / LAST UPDATE"
        sections.append([heading, [title]])
    if not stories:
        sections.append(["NASA mission updates", ["Feed unavailable"]])
    return {"updated": now, "legacy": False, "sections": sections, "state": state}


def refresh(spec, prior, reader, context, normalize, parse):
    now = int(time.time())
    old = (prior or {}).get("state") or {}
    if old and 0 <= now - old["checked"] < (FAILURE_TTL if old["stale"] else SOURCE_TTL):
        return report(old, now)
    try:
        location = retrotv_weather.locate(spec, old, reader, context)
    except DATA_ERRORS as error:
        print("Space Desk location unavailable: {}".format(error), flush=True)
        location = old.get("place")

    results = {}

    def collect(key, get, *args):
        try:
            results[key] = get(*args)
        except DATA_ERRORS as error:
            print("Space Desk {} unavailable: {}".format(key, error), flush=True)

    jobs = [
        ("launches", launches, reader, context, normalize, now),
        ("mission", mission_news, reader, context, parse),
    ]
    if location:
        jobs.append(("passes", passes, reader, context, location))
    workers = [Thread(target=collect, args=item, daemon=True) for item in jobs]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    stale = sorted({"launches", "passes", "mission"} - results.keys())
    cached = old.get("feeds", {}).copy()
    if not location or (old.get("place") and any(location[k] != old["place"][k] for k in ("lat","lon"))):
        cached.pop("passes", None)
    cached.update(results)
    state = {"checked": now, "spec": spec, "stale": stale, "place": location, "feeds": cached}
    print("Space Desk updated: {} launches, {} ISS passes, {} NASA headlines.".format(
        len(results.get("launches", [])), len(results.get("passes", {}).get("items", [])),
        len(results.get("mission", []))), flush=True)
    return report(state, now)


def load(path, spec):
    try:
        with path.open("rb") as stream:
            data = json.loads(stream.read(32768))
        state = data["state"]
        now = int(time.time())
        if state["spec"] != spec or not 0 <= now - state["checked"] < 7*86400:
            return None
        if state.get("place"):
            p = state["place"]
            state["place"] = retrotv_weather.place(p["lat"],p["lon"],p["label"],p["country"],p["located"])
        result = report(state, now)
        result["updated"] = state["checked"]
        return result
    except DATA_ERRORS:
        return None


def location_spec(folder):
    if (folder/retrotv_weather.LOCATION_FILE).is_file():
        return retrotv_weather.location_spec(folder)
    return retrotv_weather.location_spec(folder.parent/"CH 14 - Weather")
