"""Build and publish RetroTV's static HDMI scenery without touching playback."""

from contextlib import contextmanager
from functools import lru_cache
import gzip
from itertools import takewhile
import mmap
import os
from pathlib import Path
import select
import socket
from struct import Struct
import time

WIDTH, HEIGHT = 1920, 1080
VIDEO = (600, 290, 1320, 770)
FRAME_BYTES = WIDTH * HEIGHT * 2
DDR_BASE = 0x36000000
BANK_BYTES = 0x400000
BANK_SETTLE = 0.05
CONTROL = Path("/tmp/retrotv-scenes.sock")
VISIBLE_BANK = Path("/tmp/retrotv-scene-bank")
SPAN = Struct("<II")

GAME_CABINETS = ("nintendo", "sega", "atari", "playstation", "turbografx")
ARCADE_CABINETS = ("arcade-star-patrol", "arcade-lunar-run", "arcade-pixel-drift",
                   "arcade-night-circuit", "arcade-robot-relay")
CLASSIC_ARCADE_CABINETS = ("arcade-defender", "arcade-robotron", "arcade-pac-man")
TRANSPARENT_CABINETS = GAME_CABINETS + ARCADE_CABINETS + CLASSIC_ARCADE_CABINETS
COMPACT_CABINETS = (
    "trinitron-xbr-1989", "zenith-space-command", "rca-colortrak-2000",
    "sharp-linytron", "panasonic-superflat", "jvc-d-series",
    "midcentury-1950s", "sony-pvm-1990s", "sears-color-1984", "weyland-yutani",
) + TRANSPARENT_CABINETS
FULL_HD_CABINETS = ("arcade-bubbatron-upright", "arcade-fpgatron-upright")
CABINETS = COMPACT_CABINETS + FULL_HD_CABINETS
BACKGROUNDS = (
    "black", "midcentury-living-room", "retro-media-room", "spacecraft-bay",
    "1941-radio-parlor", "1944-evening-parlor", "1948-bungalow-living-room",
    "1951-walnut-living-room", "1954-pastel-living-room", "1957-ranch-living-room",
    "1959-desert-living-room", "1962-danish-living-room", "1966-mod-living-room",
    "1969-sunken-living-room",
    "arcade-1980-mall", "arcade-1981-boardwalk", "arcade-1982-neon",
    "arcade-1983-pizza-parlor", "arcade-1984-skate-rink",
    "tropical-veranda", "operational-command-center",
)


@lru_cache(maxsize=3)
def read_background(folder, name):
    if name == "black":
        return b"\x00\x80" * (WIDTH * HEIGHT)
    data = gzip.decompress((folder / (name + ".bg.gz")).read_bytes())
    if len(data) != FRAME_BYTES:
        raise ValueError("Invalid background frame: " + name)
    return data


@lru_cache(maxsize=len(CABINETS))
def read_cabinet(folder, name):
    data = gzip.decompress((folder / (name + ".cab.gz")).read_bytes())
    spans = []
    index = 0
    previous_end = 0
    while index < len(data):
        if len(data) - index < SPAN.size:
            raise ValueError("Invalid cabinet span: " + name)
        start, size = SPAN.unpack_from(data, index)
        index += SPAN.size
        end = start + size
        if (start < previous_end or start % 2 or not size or size % 2
                or end > FRAME_BYTES or index + size > len(data)):
            raise ValueError("Invalid cabinet pixel range: " + name)
        spans.append((start, data[index:index + size]))
        previous_end = end
        index += size
    if not spans:
        raise ValueError("Empty cabinet: " + name)
    return spans


def compose(folder, cabinet, background):
    frame = bytearray(read_background(folder, background))
    for offset, pixels in read_cabinet(folder, cabinet):
        frame[offset:offset + len(pixels)] = pixels
    left, top, right, bottom = VIDEO
    glass = bytes((right - left) * 2)
    for row in range(top, bottom):
        start = (row * WIDTH + left) * 2
        frame[start:start + len(glass)] = glass
    return frame


@contextmanager
def video_memory():
    memory = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        with mmap.mmap(memory, 2 * BANK_BYTES, offset=DDR_BASE) as slots:
            yield slots
    finally:
        os.close(memory)


def run_scenes(folder, publish, stop):
    cabinets = tuple(takewhile(lambda name: (folder / (name + ".cab.gz")).is_file(), CABINETS))
    if not cabinets:
        return
    backgrounds = tuple(name for name in BACKGROUNDS
                        if name == "black" or (folder / (name + ".bg.gz")).is_file())

    from retrotv_screenshots import open_image_controls

    cabinet_index = background_index = 0
    bank = 0
    displayed = None
    last_publish = 0.0
    try:
        with video_memory() as slots:
            with open_image_controls(CONTROL) as port:
                port.setblocking(False)
                while not stop.is_set():
                    selection = cabinet_index, background_index
                    if selection != displayed:
                        cabinet = cabinets[cabinet_index]
                        background = backgrounds[background_index]
                        frame = compose(folder, cabinet, background)
                        if stop.wait(max(0, BANK_SETTLE - (time.monotonic() - last_publish))):
                            break
                        start = bank * BANK_BYTES
                        slots[start:start + FRAME_BYTES] = frame
                        if not publish(bytes((0xD6 + bank,))):
                            break
                        current = VISIBLE_BANK.with_suffix(".tmp")
                        current.write_text(str(bank) + "\n", encoding="ascii")
                        current.replace(VISIBLE_BANK)
                        last_publish = time.monotonic()
                        displayed = selection
                        bank ^= 1
                        print(f"Scene [{cabinet}] [{background}]", flush=True)
                    readable, _, _ = select.select([port], [], [], .2)
                    if not readable:
                        continue
                    while True:
                        try:
                            command = port.recv(1)
                        except BlockingIOError:
                            break
                        if command == b"0":
                            cabinet_index = 0
                        elif command in (b"u", b"d"):
                            cabinet_index = (cabinet_index + (1 if command == b"u" else -1)) % len(cabinets)
                        elif command in (b"+", b"-"):
                            background_index = (background_index + (1 if command == b"+" else -1)) % len(backgrounds)
    except (OSError, EOFError, ValueError) as error:
        print(f"HDMI scenery unavailable: {error}", flush=True)
        publish(b"\xd8")
    finally:
        VISIBLE_BANK.unlink(missing_ok=True)
