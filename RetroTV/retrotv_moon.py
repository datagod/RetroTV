"""Draw lunar phase, sky position and events into RetroTV's fixed image banks."""

import array
import contextlib
import ctypes
from datetime import datetime, timedelta, timezone
import importlib
import json
import math
import mmap
import os
from pathlib import Path
import runpy
import sys
import tempfile
import textwrap
import time
from urllib.parse import urlsplit
import zlib

import retrotv_weather

WHEEL = "astronomy_engine-2.1.19-py3-none-any.whl"
NASA = "https://svs.gsfc.nasa.gov"
SNAPSHOT = ".moon-daily"
LOCATION_RETRY = 300
BG = (7, 19, 56)
PANEL = (14, 40, 116)
WHITE = (241, 248, 255)
CYAN = (127, 220, 251)
AMBER = (255, 212, 109)
RULE = (47, 82, 145)
PHASES = ("New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
          "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent")
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def load_engine(assets):
    wheel = assets / WHEEL
    if not wheel.is_file():
        raise ValueError("Moon Channel astronomy wheel is missing")
    sys.path.insert(0, str(wheel))
    try:
        return importlib.import_module("astronomy")
    finally:
        sys.path.pop(0)


def heading(azimuth):
    return COMPASS[int((azimuth + 11.25) // 22.5) % len(COMPASS)]


def phase_name(angle):
    # Quarter names describe the short interval centered on the exact phase.
    nearest = round(angle / 90)
    if abs(angle - nearest * 90) < 3:
        return PHASES[(nearest * 2) % 8]
    return PHASES[int(angle // 90) * 2 + 1]


def horizon_vector(direction):
    az, alt = map(math.radians, (direction.azimuth, direction.altitude))
    return (math.cos(alt) * math.cos(az), -math.cos(alt) * math.sin(az), math.sin(alt))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def image_basis(engine, moment, observer, moon, moon_geo, sun_geo):
    az, alt = map(math.radians, (moon_geo.azimuth, moon_geo.altitude))
    # Astronomy Engine's horizon vector axes are north, west, up.
    right = (-math.sin(az), -math.cos(az), 0)
    up = (-math.sin(alt) * math.cos(az), math.sin(alt) * math.sin(az), math.cos(alt))
    ra, decl = math.radians(15 * moon.ra), math.radians(moon.dec)
    north = engine.Vector(-math.sin(decl) * math.cos(ra),
                          -math.sin(decl) * math.sin(ra), math.cos(decl), moment)
    here = engine.RotateVector(engine.Rotation_EQD_HOR(moment, observer), north)
    nx, ny = dot((here.x, here.y, here.z), right), dot((here.x, here.y, here.z), up)
    norm = math.hypot(nx, ny)
    sun_x, sun_y = dot(horizon_vector(sun_geo), right), dot(horizon_vector(sun_geo), up)
    norm_sun = math.hypot(sun_x, sun_y)
    return ((nx / norm, ny / norm) if norm > 1e-10 else (0, 1),
            (sun_x / norm_sun, sun_y / norm_sun) if norm_sun > 1e-10 else (0, 1))


def observation(engine, place, when):
    moment = engine.Time.Parse(when.strftime("%Y-%m-%dT%H:%M:%SZ"))
    observer = engine.Observer(place["lat"], place["lon"], 0)
    moon = engine.Equator(engine.Body.Moon, moment, observer, True, True)
    sun = engine.Equator(engine.Body.Sun, moment, observer, True, True)
    apparent = engine.Horizon(moment, observer, moon.ra, moon.dec, engine.Refraction.Normal)
    moon_geo = engine.Horizon(moment, observer, moon.ra, moon.dec, engine.Refraction.Airless)
    sun_geo = engine.Horizon(moment, observer, sun.ra, sun.dec, engine.Refraction.Airless)
    north, bright = image_basis(engine, moment, observer, moon, moon_geo, sun_geo)
    lit = engine.Illumination(engine.Body.Moon, moment)
    rise = engine.SearchRiseSet(engine.Body.Moon, observer, engine.Direction.Rise, moment, 7)
    setting = engine.SearchRiseSet(engine.Body.Moon, observer, engine.Direction.Set, moment, 7)
    high = engine.SearchHourAngle(engine.Body.Moon, observer, 0, moment, 1)
    theta = math.radians(lit.phase_angle)
    return {
        "place": place["label"], "when": when, "phase": phase_name(engine.MoonPhase(moment)),
        "lit": lit.phase_fraction, "azimuth": apparent.azimuth, "altitude": apparent.altitude,
        "north": north, "light": (bright[0] * math.sin(theta), bright[1] * math.sin(theta), math.cos(theta)),
        "rise": rise, "set": setting, "high": high.time,
    }


def nasa_image(hour, reader, context, artwork):
    result = json.loads(reader(NASA + "/api/dialamoon/" + hour.strftime("%Y-%m-%dT%H:00"), context))
    link = urlsplit(result["image"]["url"])
    if link.scheme not in ("http", "https") or link.netloc != "svs.gsfc.nasa.gov" or not link.path.startswith("/vis/"):
        raise ValueError("unexpected NASA Moon image URL")
    raw = reader(NASA + link.path, context, binary=True)
    if raw[:3] != b"\xff\xd8\xff":
        raise ValueError("NASA Moon image is not a JPEG")
    lib = artwork.lib
    with tempfile.NamedTemporaryFile(prefix="retrotv-moon-", suffix=".jpg", dir="/tmp") as image:
        image.write(raw)
        image.flush()
        handle = lib.imlib_load_image_immediately(os.fsencode(image.name))
        if not handle:
            raise ValueError("could not decode NASA Moon image")
        lib.imlib_context_set_image(handle)
        try:
            width, height = lib.imlib_image_get_width(), lib.imlib_image_get_height()
            if width != height or not 200 <= width <= 1024:
                raise ValueError("NASA Moon image has unexpected dimensions")
            rgba = lib.imlib_image_get_data_for_reading_only()
            if not rgba:
                raise ValueError("could not read decoded lunar pixels")
            samples = array.array("I")
            samples.frombytes(ctypes.string_at(rgba, width * height * 4))
        finally:
            lib.imlib_free_image()
    # Dial-A-Moon's basic images use a fixed angular scale. Use the reported
    # apparent diameter so a crescent and a full disk sample the same limb.
    radius = width * float(result["diameter"]) / 4167
    if not 0.34 * width <= radius < (width-1)/2:
        raise ValueError("NASA Moon image radius is out of range")
    return width, radius, samples


class Slate:
    def __init__(self, width, height, font, color):
        self.width = width
        self.height = height
        self.font = font
        self.color = color
        self.pixels = bytearray(color(BG) * (width * height))

    def bar(self, x, y, width, height, color):
        row = self.color(color) * width
        for line in range(y, y + height):
            start = 2 * (line * self.width + x)
            self.pixels[start:start + len(row)] = row

    def text(self, x, y, text, font_size, color, *, background=BG, width=None, center=False):
        room = self.width-x if width is None else width
        lines = textwrap.wrap(text.upper(), room // (6 * font_size))
        fg, bg = self.color(color), self.color(background)
        for words in lines:
            if y + 7 * font_size > self.height:
                break
            origin = x + (room - len(words) * 6 * font_size)//2 if center else x
            for row in range(7):
                span = b"".join(self.font.glyph_row(char, row, font_size, fg, bg) for char in words)
                for copy in range(font_size):
                    start = 2 * ((y + row * font_size + copy) * self.width + origin)
                    self.pixels[start:start + len(span)] = span
            y += 9 * font_size
        return y

    def moon(self, cx, cy, radius, pixel_aspect, data, photo):
        nx, ny = data["north"]
        lx, ly, lz = data["light"]
        if photo:
            source_width, source_radius, source = photo
            origin = (source_width-1)/2
        tones = [self.color((max(15,i), max(20,i), max(31,i))) for i in range(256)]
        wide = int(radius / pixel_aspect + 1)
        for y in range(cy-radius, cy+radius+1):
            dy = (cy-y)/radius
            dy2 = dy**2
            for x in range(cx-wide, cx+wide+1):
                dx = (x-cx)*pixel_aspect/radius
                rr = dx**2 + dy2
                if rr > 1:
                    continue
                if photo:
                    px = round(origin + source_radius * (ny*dx - nx*dy))
                    py = round(origin - source_radius * (nx*dx + ny*dy))
                    shade = source[py * source_width + px] & 255
                else:
                    light = lx*dx + ly*dy + lz*math.sqrt(1-rr)
                    shade = round(36+204*light**.55) if light > 0 else 0
                start = 2*(y*self.width+x)
                self.pixels[start:start+2] = tones[shade]


def event_label(moment):
    if moment is None:
        return "None in next 7 days"
    utc = moment.Utc().replace(tzinfo=timezone.utc)
    local = utc.astimezone()
    return local.strftime("%b %d  %I:%M %p").replace("  0", "  ")


def render(data, photo, size, font, color, normalize, *, location_error=False):
    width, height = size
    compact = width == 428
    canvas = Slate(width, height, font, color)
    head, footer = (62, 348) if compact else (83, 443)
    margin, header_scale, body = (15, 3, 2) if compact else (28, 4, 3)
    subtitle = 2 if compact else 3
    canvas.bar(0, 0, width, head, PANEL)
    canvas.bar(0, head, width, 3, AMBER)
    canvas.text(margin, 9, "CH 17  /  MOON", header_scale, WHITE, background=PANEL)
    label = normalize(data["place"]) if data else ""
    max_len = (width - 2 * margin)//(6 * subtitle)
    if len(label) > max_len:
        label = label[:max_len-3].rstrip() + "..."
    if label:
        canvas.text(margin, head-(22 if compact else 30), label, subtitle, CYAN, background=PANEL)
    if not data:
        message = "Location unavailable" if location_error else "Finding the Moon"
        canvas.text(margin, head+38, message, body, WHITE)
        return canvas.pixels

    split = int(width * .44 if compact else width * .455)
    right = split + (16 if compact else 24)
    right_width = width - right - margin//2
    canvas.bar(split, head+18, 2, footer-head-35, RULE)
    center_y, radius = (169, 73) if compact else (224, 110)
    canvas.moon(split//2, center_y, radius, 32/27 if compact else 1, data, photo)
    y = canvas.text(6, 256 if compact else 353, data["phase"], body, CYAN,
                    width=split-12, center=True)
    canvas.text(6, y+6, "{:.1f}% lit".format(100 * data["lit"]), body, WHITE,
                width=split-12, center=True)

    y = head+(20 if compact else 27)
    canvas.text(right, y, "Sky position", body, CYAN, width=right_width)
    az = data["azimuth"]
    alt = data["altitude"]
    y = canvas.text(right, y+(23 if compact else 30), "{} / AZ {:03d} DEG".format(heading(az), round(az)%360),
                    body, WHITE, width=right_width)
    elevation = "{:.0f} DEG {}".format(abs(alt), "ABOVE HORIZON" if alt >= 0 else "BELOW HORIZON")
    canvas.text(right, y+4, elevation, 2, WHITE, width=right_width)
    start, step = (164, 60) if compact else (206, 74)
    for index, (name, value) in enumerate((("Next moonrise", data["rise"]), ("Next moonset", data["set"]),
                                           ("Next high point", data["high"]))):
        y = start + index * step
        canvas.text(right, y, name, 2 if compact else 3, CYAN, width=right_width)
        canvas.text(right, y+(22 if compact else 30), event_label(value), body, WHITE, width=right_width)

    canvas.bar(0, footer, width, 2, RULE)
    local = data["when"].astimezone()
    stamp = local.strftime("AS OF %b %d %I:%M %p %Z")
    credit = "NASA SVS" if photo else "PHASE DIAGRAM"
    credit_x = width - margin - 12 * len(credit)
    available = credit_x - margin - 8
    if len(stamp)*12 > available:
        stamp = local.strftime("%b %d %I:%M %p %Z")
    if len(stamp)*12 > available:
        stamp = local.strftime("%b %d %I:%M %p")
    canvas.text(margin, footer+8, stamp, 2, CYAN, width=available)
    canvas.text(credit_x, footer+8, credit, 2, CYAN)
    return canvas.pixels


def location_spec(folder):
    weather = folder.parent/"CH 14 - Weather"
    path = folder if (folder/retrotv_weather.LOCATION_FILE).is_file() else weather
    return retrotv_weather.location_spec(path)


def location(folder, reader, context, normalize, spec=None):
    weather = folder.parent/"CH 14 - Weather"
    if spec is None:
        spec = location_spec(folder)
    prior = retrotv_weather.load(weather/".latest-bulletin.json", spec, normalize)
    return retrotv_weather.locate(spec, prior, reader, context)


def snapshot_key(day, spec, sizes):
    return {"day": day.isoformat(), "location": spec, "sizes": [list(size) for size in sizes]}


def load_snapshot(path, key):
    lengths = [w*h*2 for w,h in key["sizes"]]
    expected = sum(lengths)
    try:
        with path.open("rb") as saved:
            if json.loads(saved.readline(4096)) != key:
                return None
            packed = saved.read(expected + 65537)
        if len(packed) > expected + 65536:
            return None
        decoder = zlib.decompressobj()
        flat = decoder.decompress(packed, expected + 1)
        if len(flat) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            return None
    except (OSError, ValueError, zlib.error):
        return None

    frames = []
    start = 0
    for length in lengths:
        frames.append(flat[start:start+length])
        start += length
    return frames


def save_snapshot(path, key, frames):
    with tempfile.NamedTemporaryFile(prefix=".moon-daily-", dir=path.parent, delete=False) as output:
        pending = Path(output.name)
        try:
            output.write((json.dumps(key) + "\n").encode("ascii"))
            output.write(zlib.compress(b"".join(frames), level=1))
            output.close()
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


def wait_for_tomorrow(day):
    # Convert the next local midnight using its own offset across DST changes.
    midnight = datetime.combine(day + timedelta(days=1), datetime.min.time()).timestamp()
    while datetime.now().date() == day:
        time.sleep(max(1, min(3600, midnight - time.time())))


def play(folder, tty, assets, font, color, reader, context, normalize):
    engine = load_engine(assets)
    artwork_engine = runpy.run_path(str(assets/"retrotv-music.py"))
    artwork = artwork_engine["Artwork"]()
    layouts = (
        (artwork_engine["ART_BASE"], artwork_engine["ART_STRIDE"],
         (artwork_engine["GLASS_WIDTH"], artwork_engine["GLASS_HEIGHT"])),
        (artwork_engine["COMPACT_ART_BASE"], artwork_engine["COMPACT_SLOT_BYTES"], artwork_engine["COMPACT_ART_SIZE"]),
        (artwork_engine["TRINITRON_ART_BASE"], artwork_engine["COMPACT_SLOT_BYTES"], artwork_engine["TRINITRON_ART_SIZE"]),
    )
    bank = 0
    sizes = [size for _, _, size in layouts]
    cache = folder / SNAPSHOT
    error_day = None
    with contextlib.ExitStack() as stack:
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        stack.callback(os.close, fd)
        slots = [(stack.enter_context(mmap.mmap(fd, stride*2, offset=base)), stride, size)
                 for base, stride, size in layouts]

        def publish(frames, day, restored):
            nonlocal bank
            for (memory, stride, _), frame in zip(slots, frames):
                offset = bank * stride
                memory[offset:offset + len(frame)] = frame
            artwork_engine["notify_core"](tty, 0xCC + bank)
            print("Moon fixed frame published (bank {}, {}, {}).".format(
                bank, day, "saved snapshot" if restored else "new snapshot"), flush=True)
            bank ^= 1

        # Retire the last image bank before reusing it on a channel change.
        time.sleep(.05)
        while True:
            now = datetime.now(timezone.utc)
            day = now.astimezone().date()
            spec = location_spec(folder)
            key = snapshot_key(day, spec, sizes)
            frames = load_snapshot(cache, key)
            restored = frames is not None
            if frames is None:
                try:
                    place = location(folder, reader, context, normalize, spec)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    print("Moon location unavailable: {}".format(error), flush=True)
                    frames = [render(None, None, size, font, color, normalize, location_error=True)
                              for size in sizes]
                    if error_day != day:
                        publish(frames, day, False)
                        error_day = day
                    time.sleep(LOCATION_RETRY)
                    continue
                now = datetime.now(timezone.utc)
                day = now.astimezone().date()
                key = snapshot_key(day, spec, sizes)
                data = observation(engine, place, now)
                photo = None
                try:
                    photo = nasa_image(now, reader, context, artwork)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    print("Moon NASA image unavailable: {}".format(error), flush=True)
                frames = [render(data, photo, size, font, color, normalize) for size in sizes]
                if datetime.now().date() != day:
                    continue
                try:
                    save_snapshot(cache, key, frames)
                except OSError as error:
                    print("Could not save daily Moon snapshot: {}".format(error), flush=True)
            if datetime.now().date() != day:
                continue
            publish(frames, day, restored)
            wait_for_tomorrow(day)
