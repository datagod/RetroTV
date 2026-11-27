"""Build a program guide from RetroTV's published channels and broadcast clock."""

import json
from pathlib import Path
import re
import runpy
import time

CARD_BY_MODE = {
    "stock": "Market quotes and tech headlines",
    "weather": "Local conditions and four-day forecast",
    "guide": "This program guide",
    "space": "Rocket launches, ISS passes and mission updates",
    "moon": "Lunar phase, sky position, moonrise and moonset",
    "watch": "Daily MiSTer core, arcade and developer release notes",
    "twin-galaxies": "Daily gaming news and recently accepted scores",
}


def display_title(name, normalize):
    stem = Path(name).stem
    stem = re.sub(r"\s*-\s*Retro[_ ]?TV(?:[_ ]?2)?$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s+-\s+[A-Za-z0-9_-]{11}$", "", stem)
    title = normalize(stem) or normalize(name)
    return title if len(title) <= 84 else title[:81].rstrip() + "..."


def clock_rows(playlist, elapsed, now, choose, normalize, break_ms=0):
    clip, offset = choose(playlist, elapsed, break_ms)
    if clip is None:
        left = max(1, (break_ms - offset + 999) // 1000)
        when = time.strftime("%I:%M:%S %p", time.localtime(now + left)).lstrip("0")
        return ["Now  Test card break", "0:{:02d} LEFT".format(left),
                "Next " + when + "  " + display_title(playlist[0][0].name, normalize)]
    index = next(i for i, (path, _) in enumerate(playlist) if path == clip)
    duration = playlist[index][1]
    left = max(1, (duration - offset + 999)//1000)
    if left >= 3600:
        remaining = "{}H {:02d}M LEFT".format(left//3600, left//60 % 60)
    else:
        remaining = "{}:{:02d} LEFT".format(left//60, left % 60)
    when = time.strftime("%I:%M:%S %p", time.localtime(now + left)).lstrip("0")
    next_clip = playlist[(index+1) % len(playlist)][0]
    next_title = "Test card break" if break_ms and index == len(playlist)-1 else display_title(next_clip.name, normalize)
    return ["Now  " + display_title(clip.name, normalize),
            remaining, "Next " + when + "  " + next_title]


def indexed_clips(folder, prepared, engine):
    if prepared is not None:
        return prepared
    # The guide follows a new clip immediately without writing an index on every tune.
    records = engine["read_index"](folder)
    clips = []
    for path in engine["media_files"](folder, ".mpg"):
        stat = path.stat()
        if stat.st_size < 4:
            continue
        duration = engine["indexed_duration"](records.get(path.name), [stat.st_size, stat.st_mtime_ns])
        if duration is None:
            duration = engine["duration_ms"](path, stat.st_size)
        if duration:
            clips.append((path, duration))
    return clips


def channel_rows(folder, elapsed, now, engine, normalize):
    kind, prepared = engine["prepare_channel"](folder)
    choose = engine["clock_position"]
    if kind == "video":
        clips = indexed_clips(folder, prepared, engine)
        return clock_rows(clips, elapsed, now, choose, normalize,
                          engine["MOVIE_BREAK_MS"]) if clips else ["No indexed video"]
    if kind == "play":
        tracks = json.loads((folder/"music.json").read_text(encoding="utf-8"))
        clips = [(folder/row["audio"], row["duration_ms"]) for row in tracks
                 if type(row["duration_ms"]) is int and row["duration_ms"] > 0]
        return clock_rows(clips, elapsed, now, choose, normalize) if clips else ["Music rotation"]
    if kind == "slideshow":
        pictures = sum(1 for file in folder.iterdir() if file.suffix.casefold() in engine["IMAGE_SUFFIXES"]
                       and file.is_file())
        return [f"Slideshow / {pictures} images",
                "Images change every 20 seconds while tuned" if pictures > 1 else "Still image"]
    if kind == "testcards":
        return ["Broadcast test cards", "Images change every 20 seconds while tuned"]
    if kind == "screenshots":
        return ["Screenshots taken with Print Screen"]
    marker = (folder/engine["NEWS_MARKER"]).read_text(encoding="utf-8").strip().casefold()
    return [CARD_BY_MODE.get(marker, "World news headlines")]


def fetch(folder, engine, normalize):
    now = time.time()
    epoch = engine["read_epoch"]()
    if epoch is None or epoch < 1_000_000_000:
        raise ValueError("broadcast clock is unavailable")
    elapsed = int(max(0, now - epoch) * 1000)
    sections = []
    for name in engine["CHANNEL_LIST"].read_text(encoding="utf-8").splitlines():
        if not name or Path(name).name != name:
            continue
        channel = folder.parent/name
        try:
            rows = channel_rows(channel, elapsed, now, engine, normalize)
        except (OSError, ValueError, TypeError, KeyError):
            rows = ["Channel is updating"]
        sections.append([normalize(name), rows])
    if not sections:
        raise ValueError("channel catalog is empty")
    stamp = time.strftime("%I:%M:%S %p", time.localtime(now)).lstrip("0")
    print("Program guide updated for {} channels at {}.".format(len(sections), stamp), flush=True)
    return {"updated": int(now), "title": "As of " + stamp, "sections": sections, "legacy": False}


def source(folder, normalize, assets):
    engine = runpy.run_path(str(assets/"retrotv-broadcast.py"))
    return None, lambda _previous: fetch(folder, engine, normalize)
