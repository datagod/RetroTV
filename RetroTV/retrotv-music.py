#!/usr/bin/env python3
"""Show folder slideshows, with optional MP3s on the broadcast clock."""

import argparse
import array
import contextlib
import ctypes
import json
import mmap
import os
import random
import selectors
import shutil
import signal
import subprocess
import tempfile
import sys
import time
from pathlib import Path


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
STOCK_IMAGE = Path(__file__).resolve().parent / "assets" / "music-stock.png"


def probe_ffmpeg(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,duration",
            "-of", "json", str(path.resolve()),
        ],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(result.stdout)["streams"]
    if not streams or streams[0].get("codec_name") != "mp3":
        raise ValueError("%s does not contain MP3 audio" % path.name)
    duration_ms = round(float(streams[0]["duration"]) * 1000)
    return duration_ms


def probe_mpg123(path):
    """Measure the original file with the audio library installed on MiSTer."""
    lib = ctypes.CDLL("libmpg123.so.0")
    ptr = ctypes.c_void_p
    intp = ctypes.POINTER(ctypes.c_int)
    length_name = "mpg123_length_64" if hasattr(lib, "mpg123_length_64") else "mpg123_length"
    signatures = {
        "mpg123_init": (ctypes.c_int,),
        "mpg123_exit": (None,),
        "mpg123_new": (ptr, ctypes.c_char_p, intp),
        "mpg123_delete": (None, ptr),
        "mpg123_open": (ctypes.c_int, ptr, ctypes.c_char_p),
        "mpg123_scan": (ctypes.c_int, ptr),
        "mpg123_getformat": (ctypes.c_int, ptr, ctypes.POINTER(ctypes.c_long), intp, intp),
        length_name: (ctypes.c_int64 if length_name.endswith("_64") else ctypes.c_long, ptr),
    }
    for name, (result, *arguments) in signatures.items():
        function = getattr(lib, name)
        function.restype = result
        function.argtypes = arguments

    if lib.mpg123_init() != 0:
        raise RuntimeError("Could not initialize libmpg123")
    try:
        error = ctypes.c_int()
        handle = lib.mpg123_new(None, ctypes.byref(error))
        if not handle:
            raise RuntimeError("Could not open libmpg123 decoder (%d)" % error.value)
        try:
            if lib.mpg123_open(handle, os.fsencode(path)) != 0 or lib.mpg123_scan(handle) != 0:
                raise ValueError("Could not scan %s" % path.name)
            rate = ctypes.c_long()
            channels = ctypes.c_int()
            encoding = ctypes.c_int()
            if lib.mpg123_getformat(handle, ctypes.byref(rate), ctypes.byref(channels),
                                    ctypes.byref(encoding)) != 0 or rate.value <= 0:
                raise ValueError("Could not read the sample rate of %s" % path.name)
            return round(getattr(lib, length_name)(handle) * 1000 / rate.value)
        finally:
            lib.mpg123_delete(handle)
    finally:
        lib.mpg123_exit()


def index_tracks(folder):
    probe = probe_ffmpeg if shutil.which("ffprobe") else probe_mpg123
    files = sorted(folder.iterdir(), key=lambda path: (path.name.casefold(), path.name))

    tracks = []
    for path in files:
        if path.name.startswith(".") or path.suffix.casefold() != ".mp3" or not path.is_file():
            continue
        duration_ms = probe(path)
        if duration_ms <= 0:
            raise ValueError("%s has no playable duration" % path.name)
        tracks.append(dict(audio=path.name, duration_ms=duration_ms))

    if not tracks:
        raise ValueError("No MP3 files in %s" % folder)
    return tracks


def select_track(tracks, elapsed_ms, random_start=False):
    total_ms = sum(track["duration_ms"] for track in tracks)
    if total_ms <= 0:
        raise ValueError("The music channel has no playable tracks")
    position = random.randrange(total_ms) if random_start else max(0, elapsed_ms) % total_ms
    for index, track in enumerate(tracks):
        if position < track["duration_ms"]:
            return dict(track, index=index, offset_ms=position, total_ms=total_ms)
        position -= track["duration_ms"]


def elapsed_since_epoch(state):
    for line in state.read_text(encoding="utf-8").splitlines():
        if line.startswith("epoch\t"):
            return int((time.time() - float(line.split("\t", 1)[1])) * 1000)
    raise ValueError("Broadcast epoch missing from %s" % state)



def slideshow_images(folder):
    return sorted(
        (path for path in folder.iterdir()
         if path.suffix.casefold() in IMAGE_SUFFIXES and path.is_file()),
        key=lambda path: (path.name.casefold(), path.name),
    ) or [STOCK_IMAGE]


SLIDE_SECONDS = 20.0
GLASS_WIDTH, GLASS_HEIGHT = 428, 379
ART_BASE = 0x30E80000
ART_STRIDE = 0x50000
COMPACT_CABINET_BASE = 0x31000000
COMPACT_SLOT_BYTES = 0x100000
COMPACT_CABINET_NAMES = ("cabinet", "wood", "portable", "vhs", "sony")
COMPACT_ART_BASE = 0x31500000
COMPACT_ART_SIZE = (640, 480)
TRINITRON_CABINET_BASE = 0x31700000
TRINITRON_CABINET_FILE = "trinitron-720.raw"
TRINITRON_ART_BASE = 0x31900000
TRINITRON_ART_SIZE = (720, 480)
XBR_CABINET_FILE = "trinitron-xbr-1989.raw"
XBR_CABINET_BASE = 0x31B00000
XBR_CABINET_SIZE = (1024, 720)
XBR_SLOT_BYTES = 0x200000
XBR_GALLERY_FILES = (
    XBR_CABINET_FILE,
    "zenith-space-command.raw",
    "rca-colortrak-2000.raw",
    "sharp-linytron.raw",
    "panasonic-superflat.raw",
    "jvc-d-series.raw",
)
NATIVE_CABINETS = {
    "load-trinitron": (TRINITRON_CABINET_BASE, (960, 624), 0xCF),
    "load-xbr": (XBR_CABINET_BASE, XBR_CABINET_SIZE, 0xD1),
}


def write_cabinet_frames(base, stride, frames):
    memory = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        length = (len(frames) - 1) * stride + len(frames[-1])
        with mmap.mmap(memory, length, offset=base) as slots:
            for slot, frame in enumerate(frames):
                offset = slot * stride
                slots[offset:offset + len(frame)] = frame
    finally:
        os.close(memory)


def load_compact_cabinets(folder, tty):
    frames = [(folder / (name + ".raw")).read_bytes() for name in COMPACT_CABINET_NAMES]
    if any(len(frame) != 832 * 624 * 2 for frame in frames):
        raise ValueError("Expected five 832x624 ARGB1555 cabinet files")
    write_cabinet_frames(COMPACT_CABINET_BASE, COMPACT_SLOT_BYTES, frames)
    notify_core(tty, 0xCE)


def native_cabinet_pixels(path, size):
    frame = path.read_bytes()
    width, height = size
    if len(frame) != width * height * 2:
        raise ValueError("Expected a %dx%d ARGB1555 cabinet file at %s" % (width, height, path))
    return frame


def load_native_cabinet(path, tty, base, size, ready_code):
    frame = native_cabinet_pixels(path, size)
    write_cabinet_frames(base, len(frame), (frame,))
    notify_core(tty, ready_code)


def load_xbr_gallery(folder, tty):
    frames = [native_cabinet_pixels(folder / filename, XBR_CABINET_SIZE)
              for filename in XBR_GALLERY_FILES]
    write_cabinet_frames(XBR_CABINET_BASE, XBR_SLOT_BYTES, frames)
    notify_core(tty, 0xD2)


# Lookup tables for the low and high bytes of an opaque ARGB1555 pixel.
BLUE_LOW = bytes(value >> 3 for value in range(256))
GREEN_LOW = bytes(((value >> 3) & 7) << 5 for value in range(256))
GREEN_HIGH = bytes(value >> 6 for value in range(256))
RED_HIGH = bytes(0x80 | ((value >> 3) << 2) for value in range(256))


def merge_byte_planes(left, right):
    # Use a bulk OR rather than visiting each byte in Python.
    combined = int.from_bytes(left, "little") | int.from_bytes(right, "little")
    return combined.to_bytes(len(left), "little")


def pack_opaque_pixels(rgba, count):
    pixels = ctypes.string_at(rgba, count * 4)
    if sys.byteorder == "big":
        alpha, red, green, blue = (pixels[offset::4] for offset in range(4))
    else:
        blue, green, red, alpha = (pixels[offset::4] for offset in range(4))
    if alpha.count(255) != count:
        return None
    packed = bytearray(count * 2)
    packed[::2] = merge_byte_planes(blue.translate(BLUE_LOW), green.translate(GREEN_LOW))
    packed[1::2] = merge_byte_planes(red.translate(RED_HIGH), green.translate(GREEN_HIGH))
    return packed


class Artwork:
    """Decode and scale a still once, then write the inactive DDR slot."""

    def __init__(self):
        self.lib = ctypes.CDLL("libImlib2.so.1")
        signatures = {
            "imlib_load_image_immediately": (ctypes.c_void_p, ctypes.c_char_p),
            "imlib_context_set_image": (None, ctypes.c_void_p),
            "imlib_image_get_width": (ctypes.c_int,),
            "imlib_image_get_height": (ctypes.c_int,),
            "imlib_create_cropped_scaled_image": (ctypes.c_void_p, *([ctypes.c_int] * 6)),
            "imlib_image_get_data_for_reading_only": (ctypes.POINTER(ctypes.c_uint32),),
            "imlib_free_image": (None,),
        }
        for name, (result, *arguments) in signatures.items():
            function = getattr(self.lib, name)
            function.restype = result
            function.argtypes = arguments

    def pixels(self, path, frame_width=GLASS_WIDTH, frame_height=GLASS_HEIGHT, pixel_aspect=32 / 27, upscale=True):
        source = self.lib.imlib_load_image_immediately(os.fsencode(path))
        if not source:
            raise ValueError("Could not decode artwork: %s" % path)
        self.lib.imlib_context_set_image(source)
        try:
            width = self.lib.imlib_image_get_width()
            height = self.lib.imlib_image_get_height()
            # The core's 720x480 raster is displayed at pixel aspect 32:27.
            scale = min(frame_width * pixel_aspect / width, frame_height / height)
            if not upscale:
                scale = min(scale, 1)
            out_w = max(1, round(width * scale / pixel_aspect))
            out_h = max(1, round(height * scale))
            scaled = self.lib.imlib_create_cropped_scaled_image(0, 0, width, height, out_w, out_h)
        finally:
            self.lib.imlib_free_image()
        if not scaled:
            raise ValueError("Could not scale artwork: %s" % path)

        self.lib.imlib_context_set_image(scaled)
        try:
            rgba = self.lib.imlib_image_get_data_for_reading_only()
            if not rgba:
                raise ValueError("Could not read artwork: %s" % path)
            left = (frame_width - out_w) // 2
            top = (frame_height - out_h) // 2
            packed = pack_opaque_pixels(rgba, out_w * out_h)
            if packed is not None:
                if out_w == frame_width and out_h == frame_height:
                    return packed
                frame = bytearray(b"\x00\x80" * (frame_width * frame_height))
                row_bytes = out_w * 2
                for row in range(out_h):
                    dest = ((top + row) * frame_width + left) * 2
                    src = row * row_bytes
                    frame[dest:dest + row_bytes] = packed[src:src + row_bytes]
                return frame

            # Preserve alpha blending for images with transparent pixels.
            words = array.array("H", [0x8000]) * (frame_width * frame_height)
            for row in range(out_h):
                start = (top + row) * frame_width + left
                source_row = row * out_w
                for col in range(out_w):
                    pixel = rgba[source_row + col]
                    alpha = pixel >> 24
                    red = ((pixel >> 16) & 255) * alpha // 255
                    green = ((pixel >> 8) & 255) * alpha // 255
                    blue = (pixel & 255) * alpha // 255
                    words[start + col] = 0x8000 | ((red >> 3) << 10) | ((green >> 3) << 5) | (blue >> 3)
            if sys.byteorder != "little":
                words.byteswap()
            return words.tobytes()
        finally:
            self.lib.imlib_free_image()


class Slideshow:
    def __init__(self, images, slots, tty, native_slots=()):
        self.images = images
        self.slots = slots
        self.native_slots = native_slots
        self.tty = tty
        self.artwork = Artwork()
        self.index = 0
        self.bank = 0
        self.deadline = 0.0

    def show_due(self):
        if self.deadline is None or time.monotonic() < self.deadline:
            return
        while True:
            path = self.images[self.index]
            try:
                pixels = self.artwork.pixels(path)
                native_pixels = [
                    self.artwork.pixels(path, *size, pixel_aspect=1, upscale=False)
                    for _, size in self.native_slots
                ]
            except (OSError, ValueError) as error:
                if path == STOCK_IMAGE:
                    raise
                print("Skipping artwork: %s" % error, file=sys.stderr, flush=True)
                self.images.pop(self.index)
                if not self.images:
                    self.images.append(STOCK_IMAGE)
                self.index %= len(self.images)
            else:
                break

        start = self.bank * ART_STRIDE
        self.slots[start:start + len(pixels)] = pixels
        for (slots, _), frame in zip(self.native_slots, native_pixels):
            start = self.bank * COMPACT_SLOT_BYTES
            slots[start:start + len(frame)] = frame
        notify_core(self.tty, 0xCC + self.bank)
        print("Slide %s" % path.name, flush=True)
        self.bank ^= 1
        self.index = (self.index + 1) % len(self.images)
        self.deadline = time.monotonic() + SLIDE_SECONDS if len(self.images) > 1 else None


class MpgPlayer:
    def __init__(self):
        self.process = subprocess.Popen(
            ["mpg123", "-R", "-o", "alsa"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        self.events = selectors.DefaultSelector()
        self.events.register(self.process.stdout, selectors.EVENT_READ, "player")
        self.player_output = b""
        self.control_output = b""
        self.controls = []
        self.paused = False
        self.muted = False

    def send(self, command):
        self.process.stdin.write(os.fsencode(command) + b"\n")
        self.process.stdin.flush()

    def events_for(self, timeout):
        for key, _ in self.events.select(timeout):
            data = os.read(key.fd, 65536)
            if key.data == "player":
                if not data:
                    raise RuntimeError("mpg123 closed its control stream")
                messages = (self.player_output + data).split(b"\n")
                self.player_output = messages.pop()
                for message in messages:
                    if message.startswith(b"@E"):
                        raise RuntimeError(os.fsdecode(message))
                    if message.startswith((b"@P ", b"@J ")):
                        yield message
            else:
                controls = (self.control_output + data).split(b"\n")
                self.control_output = controls.pop()
                self.controls.extend(controls)

    def wait_for(self, expected):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if any(message.startswith(expected) for message in list(self.events_for(max(0, deadline - time.monotonic())))):
                return
        raise RuntimeError("mpg123 did not reply to %s" % os.fsdecode(expected))

    def queue(self, path, offset_ms):
        if "\n" in str(path) or "\r" in str(path):
            raise ValueError("Track path contains a line break")
        self.send("LOADPAUSED " + str(path.resolve()))
        self.wait_for(b"@P 1")
        if offset_ms >= 1000:
            self.send("JUMP %ds" % (offset_ms // 1000))
            self.wait_for(b"@J ")

    def set_mute(self, message):
        self.muted = message == b"mute"
        self.send("VOLUME %d" % (0 if self.muted else 100))

    def play_until_next(self, duration_ms, slideshow):
        list(self.events_for(0))
        for message in self.controls:
            if message in (b"mute", b"unmute"):
                self.set_mute(message)
        self.controls = [message for message in self.controls if message not in (b"mute", b"unmute")]
        self.send("PAUSE")
        self.paused = False
        deadline = time.monotonic() + duration_ms / 1000 + 2
        remaining = 0.0
        while True:
            now = time.monotonic()
            timeout = None if self.paused else max(0, deadline - now)
            if slideshow.deadline is not None:
                slide_timeout = max(0, slideshow.deadline - now)
                timeout = slide_timeout if timeout is None else min(timeout, slide_timeout)
            messages = list(self.events_for(0 if self.controls else timeout))
            messages.extend(self.controls)
            self.controls.clear()
            for message in messages:
                if message == b"@P 0" or message == b"next":
                    return 1
                if message == b"previous":
                    return -1
                if message == b"pause":
                    self.send("PAUSE")
                    if self.paused:
                        deadline = time.monotonic() + remaining
                    else:
                        remaining = max(0, deadline - time.monotonic())
                    self.paused = not self.paused
                if message in (b"mute", b"unmute"):
                    self.set_mute(message)
            slideshow.show_due()
            if not self.paused and time.monotonic() >= deadline:
                print("Music track exceeded its indexed duration", file=sys.stderr, flush=True)
                return 1

    def close(self):
        self.events.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def notify_core(tty, code):
    with tty.open("ab", buffering=0) as port:
        port.write(bytes((code,)))


def open_art_buffers(stack, folder):
    memory = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    stack.callback(os.close, memory)
    slots = stack.enter_context(mmap.mmap(memory, 2 * ART_STRIDE, offset=ART_BASE))

    # Let the core retire the preceding bank before reusing bank 0.
    time.sleep(0.035)
    cabinet_folder = folder.parent.parent / "compact"
    native_slots = []
    for filenames, base, size in (
        (("cabinet.raw",), COMPACT_ART_BASE, COMPACT_ART_SIZE),
        ((TRINITRON_CABINET_FILE, XBR_CABINET_FILE), TRINITRON_ART_BASE, TRINITRON_ART_SIZE),
    ):
        if any((cabinet_folder / filename).is_file() for filename in filenames):
            layout_slots = stack.enter_context(mmap.mmap(
                memory, 2 * COMPACT_SLOT_BYTES, offset=base))
            native_slots.append((layout_slots, size))
    return slots, native_slots


def open_slideshow(stack, args):
    slots, native_slots = open_art_buffers(stack, args.folder)
    slideshow = Slideshow(slideshow_images(args.folder), slots, args.tty, native_slots)
    slideshow.show_due()
    return slideshow


def play_slideshow(args):
    with contextlib.ExitStack() as stack:
        slideshow = open_slideshow(stack, args)
        while slideshow.deadline is not None:
            time.sleep(max(0, slideshow.deadline - time.monotonic()))
            slideshow.show_due()
        signal.pause()


def play_screenshots(args):
    from retrotv_screenshots import Gallery

    artwork = Artwork()
    with contextlib.ExitStack() as stack:
        slots, native_slots = open_art_buffers(stack, args.folder)
        layouts = [(GLASS_WIDTH, GLASS_HEIGHT), *(size for _, size in native_slots)]
        banks = [(slots, ART_STRIDE), *((slot, COMPACT_SLOT_BYTES) for slot, _ in native_slots)]
        bank = 0

        def load(path):
            return (artwork.pixels(path, upscale=False), *(
                artwork.pixels(path, *size, pixel_aspect=1, upscale=False)
                for _, size in native_slots))

        def publish(frames):
            nonlocal bank
            for (slot, stride), frame in zip(banks, frames):
                start = bank * stride
                slot[start:start + len(frame)] = frame
            notify_core(args.tty, 0xCC + bank)
            bank ^= 1

        Gallery(args.folder, layouts, load, publish).run()


def play_channel(args, tracks, elapsed_ms):
    selected = select_track(tracks, elapsed_ms, args.random)
    track_index, offset_ms = selected["index"], selected["offset_ms"]
    player = MpgPlayer()
    try:
        with contextlib.ExitStack() as stack:
            control = os.open(args.control, os.O_RDWR | os.O_NONBLOCK)
            stack.callback(os.close, control)
            player.events.register(control, selectors.EVENT_READ, "control")
            slideshow = open_slideshow(stack, args)
            while True:
                track = tracks[track_index]
                player.queue(args.folder / track["audio"], offset_ms)
                print("Music %s +%dms" % (track["audio"], offset_ms), flush=True)
                step = player.play_until_next(track["duration_ms"] - offset_ms, slideshow)
                player.send("STOP")
                player.wait_for(b"@P 0")
                track_index = (track_index + step) % len(tracks)
                offset_ms = 0
    finally:
        player.close()


def stop_worker(_signum, _frame):
    raise SystemExit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("index", help="Read track durations and write music.json")
    build.add_argument("folder", type=Path)
    plan = commands.add_parser("plan", help="Select the current track from music.json")
    plan.add_argument("folder", type=Path)
    cabinets = commands.add_parser("load-cabinets", help="Load the compact cabinet frames into MiSTer DDR")
    cabinets.add_argument("folder", type=Path)
    cabinets.add_argument("--tty", type=Path, default=Path("/dev/ttyS1"))
    for name in NATIVE_CABINETS:
        cabinet = commands.add_parser(name, help="Load a native cabinet bezel into MiSTer DDR")
        cabinet.add_argument("path", type=Path)
        cabinet.add_argument("--tty", type=Path, default=Path("/dev/ttyS1"))
    gallery = commands.add_parser("load-xbr-gallery", help="Load all six F4 cabinets into MiSTer DDR")
    gallery.add_argument("folder", type=Path)
    gallery.add_argument("--tty", type=Path, default=Path("/dev/ttyS1"))
    slides = commands.add_parser("slideshow", help="Display a folder of images without audio")
    slides.add_argument("folder", type=Path)
    slides.add_argument("--tty", type=Path, default=Path("/dev/ttyS1"))
    shots = commands.add_parser("screenshots", help="View and manage RetroTV screenshots")
    shots.add_argument("folder", type=Path)
    shots.add_argument("--tty", type=Path, default=Path("/dev/ttyS1"))
    play = commands.add_parser("play", help="Play an indexed music channel on MiSTer")
    play.add_argument("folder", type=Path)
    play.add_argument("--control", type=Path, required=True)
    play.add_argument("--tty", type=Path, default=Path("/dev/ttyS1"))
    for command in (plan, play):
        position = command.add_mutually_exclusive_group()
        position.add_argument("--random", action="store_true")
        position.add_argument("--elapsed-ms", type=int)
        command.add_argument("--state", type=Path, default=Path("/tmp/retrotv-broadcast"))
    args = parser.parse_args()
    try:
        if args.command == "load-xbr-gallery":
            load_xbr_gallery(args.folder, args.tty)
            return 0
        if args.command in NATIVE_CABINETS:
            load_native_cabinet(args.path, args.tty, *NATIVE_CABINETS[args.command])
            return 0
        if args.command == "load-cabinets":
            load_compact_cabinets(args.folder, args.tty)
            return 0
        if args.command in {"slideshow", "screenshots"}:
            signal.signal(signal.SIGTERM, stop_worker)
            if args.command == "screenshots":
                play_screenshots(args)
            else:
                play_slideshow(args)
            return 0
        manifest = args.folder / "music.json"
        if args.command == "index":
            tracks = index_tracks(args.folder)
            with tempfile.NamedTemporaryFile(dir=args.folder, prefix=".music-", delete=False) as output:
                temporary = Path(output.name)
                try:
                    output.write((json.dumps(tracks, indent=2) + "\n").encode("utf-8"))
                    output.close()
                    temporary.replace(manifest)
                finally:
                    if temporary.exists():
                        temporary.unlink()
        else:
            tracks = json.loads(manifest.read_text(encoding="utf-8"))
            elapsed_ms = args.elapsed_ms
            if elapsed_ms is None:
                elapsed_ms = 0 if args.random else elapsed_since_epoch(args.state)
            if args.command == "play":
                signal.signal(signal.SIGTERM, stop_worker)
                play_channel(args, tracks, elapsed_ms)
            else:
                track = select_track(tracks, elapsed_ms, args.random)
                first_slide = slideshow_images(args.folder)[0]
                track["image"] = str(STOCK_IMAGE) if first_slide == STOCK_IMAGE else first_slide.name
                print(json.dumps(track))
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, "%s\n" % error)


if __name__ == "__main__":
    main()
