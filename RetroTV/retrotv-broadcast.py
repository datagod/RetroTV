#!/usr/bin/env python3
"""Choose and mount original MPEG clips using RetroTV's shared broadcast clock."""

from collections import deque
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import ExitStack

import json
import os
from pathlib import Path
import random
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import termios
import threading
import time
import traceback

STATE = "/tmp/retrotv-broadcast"
HEAD = 256 * 1024
TAIL = 4 * 1024 * 1024
MAX_MS = 6 * 3600 * 1000
# Used only when a clip has no readable timestamps. 2.5 Mbit/s.
FALLBACK_BPS = 2500000


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)


def parse_pts(block):
    if len(block) < 5:
        return None
    if (block[0] & 0xF0) not in (0x20, 0x30):
        return None
    if (block[0] & 1) == 0 or (block[2] & 1) == 0 or (block[4] & 1) == 0:
        return None
    return (
        ((block[0] & 0x0E) << 29)
        | (block[1] << 22)
        | ((block[2] & 0xFE) << 14)
        | (block[3] << 7)
        | (block[4] >> 1)
    )


def packet_pts(data, found):
    # found points at a 00 00 01 start code. These archives are MPEG-1
    # program streams: optional FF stuffing, an optional STD buffer, then
    # a 0010/0011 timestamp. MPEG-2 PES (the 10xxxxxx header) is accepted too.
    stream_id = data[found + 3]
    video_stream = 0xE0 <= stream_id <= 0xEF
    audio_stream = 0xC0 <= stream_id <= 0xDF
    if not video_stream and not audio_stream:
        return None, False
    length = (data[found + 4] << 8) | data[found + 5]
    header = found + 6
    end = found + 6 + length if length else len(data)
    if end > len(data):
        end = len(data)
    if header >= end:
        return None, video_stream
    if (data[header] & 0xC0) == 0x80:
        if header + 8 <= end and ((data[header + 1] >> 6) & 3) >= 2:
            return parse_pts(data[header + 3 : header + 8]), video_stream
        return None, video_stream
    cursor = header
    while cursor < end and data[cursor] == 0xFF:
        cursor += 1
    if cursor < end and (data[cursor] & 0xC0) == 0x40:
        cursor += 2
    if cursor + 5 <= end and (data[cursor] & 0xF0) in (0x20, 0x30):
        return parse_pts(data[cursor : cursor + 5]), video_stream
    return None, video_stream


def pts_values(data):
    video = []
    other = []
    start = 0
    limit = len(data)
    while True:
        found = data.find(b"\x00\x00\x01", start)
        if found < 0 or found + 9 > limit:
            break
        pts, is_video = packet_pts(data, found)
        length = (data[found + 4] << 8) | data[found + 5]
        stream_id = data[found + 3]
        pes = (0xC0 <= stream_id <= 0xDF) or (0xE0 <= stream_id <= 0xEF)
        if pes and length and found + 6 + length <= limit:
            start = found + 6 + length
        else:
            start = found + 3
        if pts is None:
            continue
        if is_video:
            video.append(pts)
        else:
            other.append(pts)
    return video or other


def duration_ms(path, size):
    if size <= 0:
        return 0
    with open(path, "rb") as handle:
        if size <= HEAD + TAIL:
            data = handle.read(size)
            samples = pts_values(data)
            first = min(samples) if samples else None
            last = max(samples) if samples else None
        else:
            head = handle.read(HEAD)
            handle.seek(size - TAIL)
            tail = handle.read(TAIL)
            head_pts = pts_values(head)
            tail_pts = pts_values(tail)
            first = min(head_pts) if head_pts else None
            last = max(tail_pts) if tail_pts else None
    if first is not None and last is not None and last >= first:
        ms = ((last - first) & 0x1FFFFFFFF) * 1000 // 90000
        if 500 <= ms <= MAX_MS:
            return int(ms)
    estimate = size * 8 * 1000 // FALLBACK_BPS
    if estimate < 1000:
        estimate = 1000
    if estimate > MAX_MS:
        estimate = MAX_MS
    print("Estimated duration for %s: %d ms" % (path.name, estimate), file=sys.stderr)
    return int(estimate)


INDEX = ".retrotv-times.json"
NEWS_MARKER = ".retrotv-news"
SCREENSHOT_CHANNEL = "CH - 50 Screenshots"
TEST_CARD_CHANNEL = "CH 0 - Test Cards"
LEGACY_TEST_CARD_CHANNEL = "CH 51 - Test Cards"
MOVIE_BREAK_MS = 20_000
MOUNT_SOCKET = "/tmp/retrotv-video.sock"


def atomic_text(path, contents):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as pending:
        temporary = Path(pending.name)
        try:
            pending.write(contents)
            pending.close()
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()


def media_files(folder, suffix):
    return sorted(
        (path for path in folder.iterdir() if path.suffix.casefold() == suffix and
         "\n" not in path.name and "\r" not in path.name and path.is_file()),
        key=lambda path: (path.name.casefold(), path.name),
    )


def channel_order(path):
    name = path.name.casefold()
    match = re.match(r"ch\s+(?:-\s*)?([0-9]+)\b", name)
    return (0, int(match[1]), name, path.name) if match else (1, 0, name, path.name)


def channel_folders(root):
    return sorted(
        (path for path in root.iterdir() if path.is_dir() and path.name not in {"cache", "live"} and
         not path.name.startswith(".") and path.name != LEGACY_TEST_CARD_CHANNEL and
         "\n" not in path.name and "\r" not in path.name),
        key=channel_order,
    )


def migrate_test_cards(root):
    old = root / LEGACY_TEST_CARD_CHANNEL
    new = root / TEST_CARD_CHANNEL
    if old.is_dir() and not new.exists():
        old.rename(new)
    else:
        new.mkdir(exist_ok=True)
        if old.is_dir():
            for path in old.iterdir():
                target = new / path.name
                if path.is_file() and not target.exists():
                    shutil.copy2(path, target)
            archive = Path(tempfile.mkdtemp(prefix=".retrotv-channel-51-", dir=root))
            old.rename(archive / old.name)
    last = root / "last"
    if first_line(last) == LEGACY_TEST_CARD_CHANNEL:
        atomic_text(last, TEST_CARD_CHANNEL + "\n")


def list_channels(root):
    migrate_test_cards(root)
    for folder in channel_folders(root):
        if folder.name in {SCREENSHOT_CHANNEL, TEST_CARD_CHANNEL} or (folder / NEWS_MARKER).is_file():
            print(folder.name)
            continue
        manifest = folder / "music.json"
        indexed_music = (manifest.is_file() and manifest.stat().st_size > 0 and
                         any(not path.name.startswith(".") for path in media_files(folder, ".mp3")))
        images = any(path.suffix.casefold() in {".jpg", ".jpeg", ".png"} and path.is_file()
                     for path in folder.iterdir())
        if indexed_music or media_files(folder, ".mpg") or images:
            print(folder.name)


def read_index(folder):
    try:
        with (folder / INDEX).open(encoding="utf-8") as source:
            value = json.load(source)
        if value.get("version") == 1 and isinstance(value.get("clips"), dict):
            return value["clips"]
    except (OSError, ValueError, AttributeError):
        pass
    return {}


def indexed_duration(entry, signature):
    if (isinstance(entry, list) and len(entry) == 3 and entry[:2] == signature and
            type(entry[2]) is int and 0 < entry[2] <= MAX_MS):
        return entry[2]
    return None


def index_channel(folder):
    index = folder / INDEX
    old_data = read_index(folder)
    clips = []
    new_data = {}
    for path in media_files(folder, ".mpg"):
        stat = path.stat()
        if stat.st_size < 4:
            continue
        signature = [stat.st_size, stat.st_mtime_ns]
        duration = indexed_duration(old_data.get(path.name), signature)
        if duration is None:
            duration = duration_ms(path, stat.st_size)
        new_data[path.name] = signature + [duration]
        clips.append((path, duration))

    changed = old_data != new_data
    if changed:
        atomic_text(index, json.dumps({"version": 1, "clips": new_data},
                                      ensure_ascii=True, separators=(",", ":")) + "\n")
    return clips, changed


def read_epoch():
    try:
        with Path(STATE).open(encoding="utf-8") as source:
            for line in source:
                if line.startswith("epoch\t"):
                    return float(line.split("\t", 1)[1])
    except (OSError, ValueError):
        pass
    return None


def clock_epoch():
    epoch = read_epoch()
    if epoch is not None and epoch >= 1000000000:
        return epoch
    now = time.time()
    if now >= 1000000000:
        try:
            uptime = float(Path("/proc/uptime").read_text().split()[0])
        except (OSError, ValueError, IndexError):
            uptime = 0.0
        epoch = now - uptime
    elif epoch is None:
        epoch = now
    atomic_text(Path(STATE), "epoch\t%.3f\n" % epoch)
    return epoch


def clock_position(clips, elapsed_ms, break_ms=0):
    total = sum(duration for _, duration in clips)
    position = max(0, elapsed_ms) % (total + break_ms)
    for path, duration in clips:
        if position < duration:
            return path, position
        position -= duration
    return None, position


def choose_clip(clips, mode, active, elapsed_ms):
    if not clips:
        raise ValueError("Channel contains no playable MPG files")
    if mode == "elapsed":
        return clock_position(clips, elapsed_ms)
    paths = [path for path, _ in clips]
    current = Path(active)
    if current not in paths:
        return paths[0], 0
    step = 1 if mode == "next" else -1
    return paths[(paths.index(current) + step) % len(paths)], 0


def join_frame(seconds, name):
    seconds = min(max(seconds, 0), 0xFFFFFF)
    encoded = name.encode("ascii", "ignore")[:32]
    return b"\xca\0" + seconds.to_bytes(3, "big") + encoded + b"\0"


def mount_clip(clip, seconds, label, tty_path, begin=None, finish=None):
    with tempfile.TemporaryDirectory(prefix="retrotv-mount-", dir="/tmp") as reply:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.bind(os.path.join(reply, "reply"))
            client.settimeout(4)
            client.connect(MOUNT_SOCKET)
            with open(tty_path, "wb", buffering=0) as tty:
                if begin is None:
                    tty.write(b"\xd0")
                elif not begin(b"\xd0"):
                    return False
                termios.tcdrain(tty)
                client.send(os.fsencode(clip))
                if client.recv(1) != b"\x01":
                    raise OSError("MiSTer could not mount %s" % clip)
                frame = join_frame(seconds, label)
                if finish is None:
                    tty.write(frame)
                elif not finish(frame):
                    return False
                termios.tcdrain(tty)
    return True


CHANNEL_STEPS = {0xA6: 1, 0xA8: -1}
CHANNEL_SETTLE_SECONDS = 0.250
CHANNEL_LABEL_SECONDS = 0.100


def browse_channels(channels, current, key, tty_fd):
    """Preview each step immediately and return only the settled channel."""
    if not channels or key not in CHANNEL_STEPS:
        raise ValueError("Expected a channel list and a Left or Right key")
    if current in channels:
        index = channels.index(current)
    else:
        index = -1 if CHANNEL_STEPS[key] > 0 else 0

    pending = deque()
    visible_until = 0.0
    settle_at = 0.0

    while True:
        if key is not None:
            index = (index + CHANNEL_STEPS[key]) % len(channels)
            pending.append((key, channels[index]))
            settle_at = time.monotonic() + CHANNEL_SETTLE_SECONDS
            key = None

        now = time.monotonic()
        if pending and now >= visible_until:
            direction, name = pending.popleft()
            os.write(tty_fd, preview_frame(name))
            visible_until = time.monotonic() + CHANNEL_LABEL_SECONDS
            print("tune %02x -> [%s]" % (direction, name), file=sys.stderr, flush=True)

        deadline = visible_until if pending else max(settle_at, visible_until)
        ready, _, _ = select.select([tty_fd], [], [], max(0, deadline - time.monotonic()))
        if ready:
            event = os.read(tty_fd, 1)
            if not event:
                raise OSError("Channel key input closed")
            if event == b"\xa5":
                return None
            if event[0] in CHANNEL_STEPS:
                key = event[0]
        elif not pending:
            return name



IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
COMMAND_FIFO = Path("/dev/MiSTer_cmd")
CHANNEL_LIST = Path("/tmp/retrotv-chans")
INPUT_SOCKET = Path("/tmp/retrotv-input.sock")
RESCAN = Path("/tmp/retrotv-rescan-mpg")
ACTIVE = Path("/tmp/retrotv-active-mpg")
ACTIVE_PID = Path("/tmp/retrotv-active-mpg-pid")
MUSIC_PROGRAM = Path(__file__).with_name("retrotv-music.py")
NEWS_PROGRAM = Path(__file__).with_name("retrotv-news.py")
CONTROLS = {0xA9: b"next", 0xAA: b"previous", 0xAB: b"pause", 0xAC: b"mute", 0xAD: b"unmute"}


def first_line(path):
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.readline().rstrip("\r\n")
    except FileNotFoundError:
        return ""


def preview_frame(name):
    label = bytes(byte for byte in name.encode("ascii", "ignore") if 32 <= byte < 127)[:32]
    return b"\xc2" + label + b"\0"


def prepare_channel(folder):
    """Classify a channel and resolve indexed clips without opening video."""
    if folder.name == SCREENSHOT_CHANNEL:
        return "screenshots", None
    if folder.name == TEST_CARD_CHANNEL:
        return "testcards", None
    if (folder / NEWS_MARKER).is_file():
        return "news", None
    clips = []
    music = False
    images = False
    for path in folder.iterdir():
        suffix = path.suffix.casefold()
        if suffix == ".mpg" and "\r" not in path.name and "\n" not in path.name and path.is_file():
            clips.append(path)
        elif suffix == ".mp3" and not path.name.startswith(".") and path.is_file():
            music = True
        elif suffix in IMAGE_SUFFIXES and path.is_file():
            images = True

    manifest = folder / "music.json"
    if music and manifest.is_file() and manifest.stat().st_size > 0:
        return "play", None
    if not clips and images:
        return "slideshow", None
    recorded = read_index(folder)
    cached = []
    for path in sorted(clips, key=lambda path: (path.name.casefold(), path.name)):
        stat = path.stat()
        if stat.st_size < 4:
            continue
        duration = indexed_duration(recorded.get(path.name), [stat.st_size, stat.st_mtime_ns])
        if duration is None:
            return "video", None
        cached.append((path, duration))
    return "video", cached


class ChannelPlayback:
    """Owns playback and file mounts on the worker thread."""

    def __init__(self, controller):
        self.controller = controller
        self.process = None
        self.stopping = False
        self.control = None
        self.control_dir = None
        self.card_break = None

    def interrupt(self):
        if self.process is not None and not self.stopping:
            self.process.terminate()
            self.stopping = True

    def stop(self):
        self.card_break = None
        if self.process is not None:
            self.interrupt()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
            self.stopping = False
        if self.control is not None:
            os.close(self.control)
            self.control = None
        if self.control_dir is not None:
            self.control_dir.cleanup()
            self.control_dir = None

    def start_media(self, folder, kind, how, begin, duration=None):
        if kind == "news":
            command = [sys.executable, "-u", str(NEWS_PROGRAM), str(folder)]
        else:
            command = [sys.executable, "-u", str(MUSIC_PROGRAM), kind, str(folder)]
        command += ["--tty", str(self.controller.tty_path)]
        if duration is not None:
            command += ["--seconds", str(duration)]
        if kind == "play":
            self.control_dir = tempfile.TemporaryDirectory(prefix="retrotv-music-", dir="/tmp")
            fifo = Path(self.control_dir.name) / "control"
            os.mkfifo(str(fifo))
            self.control = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            command += ["--control", str(fifo)]
            if how == "random":
                command.append("--random")
        if not begin(b"\xcb"):
            self.stop()
            return False
        self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
        for path in (ACTIVE, ACTIVE_PID):
            path.unlink(missing_ok=True)
        return True

    def mount(self, clip, offset_ms, label, begin, finish):
        seconds = offset_ms // 1000
        if not mount_clip(clip, seconds, label, self.controller.tty_path, begin, finish):
            return False
        atomic_text(ACTIVE, str(clip) + "\n")
        atomic_text(ACTIVE_PID, str(self.controller.host_pid) + "\n")
        print("mounted [%s] %s +%ds" % (clip.parent.name, clip.name, seconds), flush=True)
        return True

    def start_break(self, channel, clip, duration_ms, begin):
        if self.start_media(self.controller.root / TEST_CARD_CHANNEL, "test-card", "", begin,
                            duration_ms / 1000):
            self.card_break = (channel, clip)
            print("Test-card break [%s] for %.2fs" % (channel, duration_ms / 1000), flush=True)
            return True
        return False

    def tune(self, channel, how, serial, prepared=None):
        controller = self.controller
        if not controller.is_current(serial):
            return
        try:
            self.stop()
            folder = controller.root / channel
            kind, clips = prepared.result() if prepared is not None else prepare_channel(folder)
            prefix = b"\xc5" if how == "preview" else preview_frame(channel)

            def begin(command):
                return controller.send_current(serial, prefix + command)

            if kind == "video":
                if clips is None:
                    clips, _ = index_channel(folder)
                if not clips:
                    raise ValueError("Channel contains no playable MPG files")
                elapsed_ms = int((time.time() - controller.epoch) * 1000)
                clip, into = clock_position(clips, elapsed_ms, MOVIE_BREAK_MS)
                if clip is None:
                    playing = self.start_break(channel, clips[0][0], MOVIE_BREAK_MS - into, begin)
                else:
                    playing = self.mount(clip, into, channel, begin,
                                         lambda frame: controller.send_current(serial, frame))
            else:
                playing = self.start_media(folder, kind, how, begin)
            if playing:
                atomic_text(controller.last, channel + "\n")
        except (OSError, ValueError, RuntimeError, CancelledError) as error:
            self.stop()
            print("Could not tune [%s]: %s" % (channel, error), flush=True)
            controller.send_current(serial, b"\xc4")

    def control_key(self, key, serial, eof=False):
        controller = self.controller
        if not controller.is_current(serial):
            return
        if self.process is not None and self.card_break is None:
            if self.control is not None:
                try:
                    os.write(self.control, CONTROLS[key] + b"\n")
                except BlockingIOError:
                    pass
            return
        if key not in (0xA9, 0xAA):
            return
        channel = first_line(controller.last)
        try:
            if not channel:
                raise ValueError("No active channel")
            folder = controller.root / channel
            kind, clips = prepare_channel(folder)
            if kind != "video":
                return
            if clips is None:
                clips, _ = index_channel(folder)
            if not clips:
                raise ValueError("Channel contains no playable MPG files")

            def send(frame):
                return controller.send_current(serial, frame)

            if self.card_break is not None:
                if eof:
                    return
                self.stop()
                clip = clips[0 if key == 0xA9 else -1][0]
            else:
                active = first_line(ACTIVE)
                if eof and active == str(clips[-1][0]):
                    self.start_break(channel, clips[0][0], MOVIE_BREAK_MS, send)
                    return
                clip, _ = choose_clip(clips, "next" if key == 0xA9 else "previous", active, 0)
            self.mount(clip, 0, "", send, send)
        except (OSError, ValueError, RuntimeError) as error:
            print("Could not advance [%s]: %s" % (channel, error), flush=True)
            controller.send_current(serial, b"\xc4")

    def check(self, serial):
        if not self.controller.is_current(serial):
            return
        if self.process is not None and self.process.poll() is not None:
            card_break = self.card_break
            self.stop()
            if card_break is not None:
                channel, clip = card_break

                def send(frame):
                    return self.controller.send_current(serial, frame)

                try:
                    self.mount(clip, 0, "", send, send)
                except (OSError, ValueError, RuntimeError) as error:
                    print("Could not restart [%s]: %s" % (channel, error), flush=True)
                    send(b"\xc4")
                return
            print("slideshow or music worker stopped", flush=True)
            self.controller.send_current(serial, b"\xc4")


class ChannelListener:
    """Reads every UART key on one thread and hands playback to a second."""

    def __init__(self, root, tty_path, host_pid, startup, ready_codes):
        self.root = root
        self.last = root / "last"
        self.tty_path = tty_path
        self.host_pid = host_pid
        self.startup = startup
        self.ready_codes = ready_codes
        self.epoch = clock_epoch()
        self.channel = first_line(self.last)
        self.channels = []
        self.catalog_id = None
        self.refresh_channels()
        self.guard = threading.Lock()
        self.serial = 0
        self.closed = False
        self.labels = deque()
        self.visible_until = 0.0
        self.settle_at = None
        self.prepared = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.playback = ChannelPlayback(self)
        self.health_check = None
        self.start_at = None if startup == "keep" else time.monotonic() + 3

    def is_current(self, serial):
        with self.guard:
            return not self.closed and self.serial == serial

    def next_serial(self):
        with self.guard:
            self.serial += 1
            return self.serial

    def send_current(self, serial, frame):
        with self.guard:
            if self.closed or self.serial != serial:
                return False
            os.write(self.tty, frame)
            return True

    def publish_scene(self, frame):
        with self.guard:
            if self.closed:
                return False
            os.write(self.tty, frame)
            return True

    def submit_playback(self, operation, *args):
        task = self.executor.submit(operation, *args)
        task.add_done_callback(self.report_worker_error)
        return task

    @staticmethod
    def report_worker_error(task):
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                traceback.print_exception(type(error), error, error.__traceback__)

    def refresh_channels(self):
        try:
            stat = CHANNEL_LIST.stat()
            identity = stat.st_ino, stat.st_mtime_ns, stat.st_size
            if identity != self.catalog_id:
                names = CHANNEL_LIST.read_text(encoding="utf-8").splitlines()
                self.channels = [name for name in names if name]
                self.catalog_id = identity
        except FileNotFoundError:
            return

    def host_alive(self):
        try:
            argv = Path("/proc/%d/cmdline" % self.host_pid).read_bytes().split(b"\0")
        except FileNotFoundError:
            return False
        return argv and argv[0] == b"/media/fat/linux/retrotv-main" and any(
            arg.rsplit(b"/", 1)[-1] in (b"RetroTV.rbf", b"RetroTV_2.rbf") for arg in argv[1:])

    def show_label(self, now):
        if self.labels and now >= self.visible_until:
            direction, name, pressed_at = self.labels.popleft()
            self.send_current(self.serial, preview_frame(name))
            sent = time.monotonic()
            self.visible_until = sent + CHANNEL_LABEL_SECONDS
            action = "guide" if direction is None else "%02x" % direction
            print("tune %s -> [%s] (label sent in %.1fms)" %
                  (action, name, (sent - pressed_at) * 1000), flush=True)

    def preview(self, key, now):
        if not self.channels:
            self.refresh_channels()
        if not self.channels:
            self.send_current(self.serial, b"\xc4")
            return
        step = CHANNEL_STEPS[key]
        if self.channel in self.channels:
            index = self.channels.index(self.channel)
        else:
            index = -1 if step > 0 else 0
        self.select_channel(self.channels[(index + step) % len(self.channels)], key, now)

    def select_channel(self, name, key, now):
        self.start_at = None
        self.next_serial()
        self.channel = name
        self.labels.append((key, self.channel, now))
        self.show_label(now)
        if self.settle_at is None:
            self.submit_playback(self.playback.interrupt)
        if self.prepared is not None:
            self.prepared.cancel()
        self.prepared = self.executor.submit(prepare_channel, self.root / self.channel)
        self.settle_at = now + CHANNEL_SETTLE_SECONDS

    def handle_input(self, command, now):
        if command.startswith(b"tune "):
            self.refresh_channels()
            name = os.fsdecode(command[5:])
            if name in self.channels:
                self.labels.clear()
                self.visible_until = now
                self.select_channel(name, None, now)
        elif command == b"next" and self.settle_at is None:
            self.submit_playback(self.playback.control_key, 0xA9, self.serial)

    def tune_due(self, now):
        self.show_label(now)
        if (self.settle_at is None or self.labels or
                now < max(self.settle_at, self.visible_until)):
            return
        self.submit_playback(self.playback.tune, self.channel, "preview", self.serial, self.prepared)
        self.settle_at = None
        self.prepared = None

    def housekeeping(self, now):
        self.refresh_channels()
        if self.settle_at is not None:
            return
        try:
            rescan = first_line(RESCAN)
            if rescan:
                RESCAN.unlink(missing_ok=True)
                if rescan in self.channels and (rescan == self.channel or self.start_at is not None):
                    self.channel = rescan
                    self.start_at = None
                    print("rescan [%s]" % rescan, flush=True)
                    self.submit_playback(self.playback.tune, rescan, "elapsed", self.next_serial())
        except OSError as error:
            print("Could not read channel refresh: %s" % error, flush=True)
        if self.start_at is not None and now >= self.start_at:
            self.start_at = None
            self.send_current(self.serial, self.ready_codes)
            if self.channels:
                resume = self.startup == "resume" and self.channel in self.channels
                self.channel = self.channel if resume else random.choice(self.channels)
                print("greet [%s]" % self.channel, flush=True)
                self.submit_playback(self.playback.tune, self.channel,
                                     "elapsed" if resume else "random", self.next_serial())
        if self.health_check is None or self.health_check.done():
            self.health_check = self.submit_playback(self.playback.check, self.serial)

    def run(self):
        self.tty = os.open(self.tty_path, os.O_RDWR | os.O_NONBLOCK | os.O_NOCTTY)
        from retrotv_scenes import run_scenes
        from retrotv_screenshots import open_image_controls

        scene_stop = threading.Event()
        scenery = threading.Thread(target=run_scenes, args=(
            self.root.parent / "scenes", self.publish_scene, scene_stop), daemon=True)
        scenery.start()
        housekeeping_at = 0
        controls = ExitStack()
        try:
            input_port = controls.enter_context(open_image_controls(INPUT_SOCKET))
            input_port.setblocking(False)
            while True:
                deadline = housekeeping_at
                if self.settle_at is not None:
                    preview_at = self.visible_until if self.labels else max(self.settle_at, self.visible_until)
                    deadline = min(deadline, preview_at)
                ready, _, _ = select.select([self.tty, input_port], [], [], max(0, deadline - time.monotonic()))
                events = b""
                if self.tty in ready:
                    try:
                        events = os.read(self.tty, 64)
                    except BlockingIOError:
                        pass
                for key in events:
                    now = time.monotonic()
                    if key == 0xA5:
                        self.next_serial()
                        print("escape", flush=True)
                        try:
                            fd = os.open(COMMAND_FIFO, os.O_WRONLY | os.O_NONBLOCK)
                            try:
                                os.write(fd, b"load_core /media/fat/menu.rbf\n")
                            finally:
                                os.close(fd)
                        except OSError as error:
                            print("Could not load menu: %s" % error, flush=True)
                            self.send_current(self.serial, b"\xc4")
                            self.labels.clear()
                            self.settle_at = None
                            continue
                        print("loaded menu", flush=True)
                        return
                    if key in CHANNEL_STEPS:
                        self.preview(key, now)
                    elif key in CONTROLS and self.settle_at is None:
                        # Main forwards the manual N key separately, leaving A9 for EOF.
                        self.submit_playback(self.playback.control_key, key, self.serial, key == 0xA9)
                if input_port in ready:
                    self.handle_input(input_port.recv(512), time.monotonic())
                # Read queued keys before committing a selection at its deadline.
                now = time.monotonic()
                if now >= housekeeping_at:
                    if not self.host_alive():
                        return
                    self.housekeeping(now)
                    housekeeping_at = now + .2
                self.tune_due(now)
        finally:
            controls.close()
            scene_stop.set()
            with self.guard:
                self.closed = True
            scenery.join()
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.playback.stop()
            os.close(self.tty)


def stop_listener(_signum, _frame):
    raise SystemExit(0)


def main(argv):
    try:
        if len(argv) == 2 and argv[1] == "clock":
            clock_epoch()
        elif len(argv) == 3 and argv[1] == "channels":
            list_channels(Path(argv[2]))
        elif len(argv) == 3 and argv[1] == "index":
            clips, changed = index_channel(Path(argv[2]))
            if not clips:
                fail("No playable MPG files")
            print("Updated" if changed else "Unchanged", len(clips), "clips")
        elif len(argv) == 7 and argv[1] == "mount":
            folder, tty_path, mode, active, label = argv[2:]
            if mode not in ("elapsed", "next", "previous"):
                fail("Invalid mount mode")
            clips, _ = index_channel(Path(folder))
            elapsed_ms = int((time.time() - clock_epoch()) * 1000) if mode == "elapsed" else 0
            clip, into = choose_clip(clips, mode, active, elapsed_ms)
            seconds = into // 1000
            mount_clip(clip, seconds, label, tty_path)
            print("mounted [%s] %s +%ds" % (Path(folder).name, clip.name, seconds), file=sys.stderr)
            print(clip)
        elif len(argv) == 7 and argv[1] == "listen":
            root, tty_path, host_pid, startup, ready_codes = argv[2:]
            signal.signal(signal.SIGTERM, stop_listener)
            ChannelListener(Path(root), Path(tty_path), int(host_pid), startup,
                            bytes.fromhex(ready_codes)).run()
        elif len(argv) == 6 and argv[1] == "browse":
            with open(argv[2], encoding="utf-8") as handle:
                channels = [name for name in handle.read().splitlines() if name]
            selected = browse_channels(channels, argv[3], int(argv[4], 16), int(argv[5]))
            if selected is None:
                return 2
            print(selected)
        else:
            fail("usage: retrotv-broadcast.py clock | channels ROOT | index FOLDER | "
                 "mount FOLDER TTY MODE ACTIVE LABEL | browse CHANNELS CURRENT KEY FD | "
                 "listen ROOT TTY PID STARTUP CODES")
    except (OSError, ValueError) as error:
        fail(str(error))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
