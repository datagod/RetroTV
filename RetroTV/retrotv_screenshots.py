"""Show the screenshots channel using RetroTV's existing still-image banks."""

from contextlib import contextmanager
from pathlib import Path
import select
import socket
import time

GALLERY_CONTROL = Path("/tmp/retrotv-screenshots.sock")
SLIDESHOW_CONTROL = Path("/tmp/retrotv-slideshow.sock")
FRAME_INTERVAL = .05
SLIDE_INTERVAL = 20
FRAMES = 9
FONT = Path(__file__).with_name("retrotv-news-font.mem")


@contextmanager
def open_image_controls(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as port:
        path.unlink(missing_ok=True)
        port.bind(str(path))
        try:
            path.chmod(0o600)
            yield port
        finally:
            path.unlink(missing_ok=True)


def slide_rows(outgoing, incoming, width, height, distance, forward):
    cut = distance * 2
    stride = width * 2
    if forward:
        return b"".join(outgoing[y+cut:y+stride] + incoming[y:y+cut]
                        for y in range(0, stride * height, stride))
    return b"".join(incoming[y+stride-cut:y+stride] + outgoing[y:y+stride-cut]
                    for y in range(0, stride * height, stride))


class Gallery:
    def __init__(self, folder, layouts, load, publish):
        self.folder = folder
        self.layouts = layouts
        self.load = load
        self.publish = publish
        self.path = None
        self.frame = None
        self.confirmation = None
        self.deadline = None
        self.last_frame = 0
        self.font = tuple(int(line, 2) for line in FONT.read_text(encoding="ascii").splitlines()
                          if line and not line.startswith("//"))

    def images(self):
        return sorted(path for path in self.folder.glob("*.png")
                      if not path.name.startswith(".") and not path.is_symlink() and path.is_file())

    def message(self, text, frames=None):
        ink, background = b"\xff\xff", b"\x44\x94"
        for i, (width, height) in enumerate(self.layouts):
            image = bytearray(frames[i] if frames else background * width * height)
            scale = 2
            left = (width - len(text) * 6 * scale) // 2
            top = height - 40 if frames else (height - 7 * scale) // 2
            bar = background * (len(text) * 6 * scale + 20)
            for row in range(top - 7, top + 7 * scale + 7):
                start = 2 * (row * width + left - 10)
                image[start:start + len(bar)] = bar
            for row in range(7):
                line = b"".join(
                    b"".join((ink if self.font[ord(char) * 8 + row] & (16 >> col)
                              else background) * scale for col in range(5)) +
                    background * scale for char in text)
                for repeat in range(scale):
                    start = 2 * ((top + row * scale + repeat) * width + left)
                    image[start:start + len(line)] = line
            yield image

    def display(self, frames):
        time.sleep(max(0, self.last_frame + FRAME_INTERVAL - time.monotonic()))
        self.publish(frames)
        self.last_frame = time.monotonic()

    def show(self, path, direction=0):
        if path is None:
            self.path = self.frame = None
            self.deadline = None
            self.display(tuple(self.message("NO SCREENSHOTS YET")))
            return
        incoming = self.load(path)
        if direction and self.frame is not None and path != self.path:
            for step in range(1, FRAMES):
                frames = [slide_rows(old, new, width, height, width * step // FRAMES,
                                     direction > 0)
                          for old, new, (width, height) in zip(self.frame, incoming, self.layouts)]
                self.display(frames)
        self.path = path
        self.frame = incoming
        self.display(incoming)
        self.deadline = time.monotonic() + SLIDE_INTERVAL
        print("Screenshot " + path.name, flush=True)

    def advance(self, direction, images=None, start=None):
        if images is None:
            images = self.images()
        if not images:
            self.show(None)
            return
        if start is None:
            start = (images.index(self.path) + direction) if self.path in images else -1

        for offset in range(len(images)):
            path = images[(start + offset * direction) % len(images)]
            try:
                self.show(path, direction)
                return
            except (OSError, ValueError) as error:
                print("Skipping screenshot {}: {}".format(path.name, error), flush=True)
        self.show(None)

    def key(self, command):
        if self.confirmation is not None:
            path, identity = self.confirmation
            self.confirmation = None
            if command == b"d":
                images = self.images()
                try:
                    if path in images and path.lstat() == identity:
                        path.unlink()
                        print("Deleted screenshot " + path.name, flush=True)
                        self.advance(1, self.images(), images.index(path))
                        return
                except OSError as error:
                    print("Could not delete screenshot: {}".format(error), flush=True)
            self.display(self.frame)
            self.deadline = time.monotonic() + SLIDE_INTERVAL
        elif command == b"d" and self.frame is not None:
            try:
                identity = self.path.lstat()
            except FileNotFoundError:
                self.advance(1)
                return
            self.confirmation = (self.path, identity)
            self.display(tuple(self.message("PRESS D AGAIN TO DELETE", self.frame)))
        elif command in (b"n", b"p"):
            self.advance(1 if command == b"n" else -1)

    def run(self):
        with open_image_controls(GALLERY_CONTROL) as port:
            self.advance(1)
            while True:
                deadline = self.deadline if self.confirmation is None else None
                wait = .5 if deadline is None else min(.5, max(0, deadline - time.monotonic()))
                readable, _, _ = select.select([port], [], [], wait)
                if readable:
                    self.key(port.recv(8))
                elif self.path is None:
                    images = self.images()
                    if images:
                        self.advance(1, images)
                elif deadline is not None and time.monotonic() >= deadline:
                    self.advance(1)
