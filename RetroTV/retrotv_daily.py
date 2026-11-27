"""Maintain one cached scrolling bulletin per channel, with a daily refresh."""

import json
import time
import xml.etree.ElementTree as ET

DAY = 24 * 60 * 60
MAX_SECTIONS = 32


def cache_state(path):
    try:
        with path.open("rb") as source:
            state = json.loads(source.read(64 * 1024))
        if type(state.get("attempted")) is int:
            return state
    except (OSError, ValueError, AttributeError):
        pass
    return {}


def bulletin(path):
    return cached_bulletin(cache_state(path))


def cached_bulletin(state):
    data = state.get("bulletin")
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list) or not 0 < len(sections) <= MAX_SECTIONS:
        return {"offline": True} if state.get("offline") else None
    for section in sections:
        if not isinstance(section, list) or len(section) != 2 or not isinstance(section[1], list):
            return None
        if not all(isinstance(line, str) and line.isascii() and len(line) <= 180
                   for line in [section[0], *section[1]]):
            return None
    if not isinstance(data.get("title"), str) or not data["title"].isascii():
        return None
    return {**data, "offline": state.get("offline", False)}


def refresh_if_due(path, fetch, save, label):
    # The boot worker and a manual cache refresh share the same schedule.
    import fcntl

    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = int(time.time())
        if now < 1704067200:  # Wait for the system clock after a cold boot.
            return 60
        state = cache_state(path)
        attempted = state.get("attempted", 0)
        if now - attempted < DAY:
            return min(DAY, attempted + DAY - now)
        state["attempted"] = now
        save(path, state)
        try:
            state["bulletin"] = fetch(cached_bulletin(state))
            state["offline"] = False
        except (OSError, ValueError, ET.ParseError) as error:
            print(f"{label} could not update its bulletin: {error}", flush=True)
            state["offline"] = True
        save(path, state)
        return max(1, now + DAY - int(time.time()))
