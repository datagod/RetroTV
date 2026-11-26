"""Pack full-screen RetroTV cabinet overlays and background photographs."""

import argparse
import gzip
from pathlib import Path
import re

from PIL import Image, ImageChops

from make_xbr_cabinets import NATIVE_GALLERY, XBR_RECT, fit_xbr, pack_argb1555
from retrotv_scenes import BACKGROUNDS, CABINETS, HEIGHT, SPAN, TRANSPARENT_CABINETS, VIDEO, WIDTH

ROOT = Path(__file__).resolve().parent


def cabinet_artwork(source, name):
    if name in NATIVE_GALLERY or name in TRANSPARENT_CABINETS:
        with Image.open(source) as image:
            return image.convert("RGBA")
    artwork = Image.new("RGBA", (WIDTH, HEIGHT))
    artwork.paste(fit_xbr(source), XBR_RECT[:2])
    return artwork


def cabinet_spans(artwork, transparent_exterior=False):
    if artwork.size != (WIDTH, HEIGHT):
        raise ValueError("Expected a 1920x1080 cabinet")
    alpha = artwork.getchannel("A")
    if alpha.crop(VIDEO).getextrema() != (0, 0):
        raise ValueError("Expected a transparent 720x480 video aperture")

    if transparent_exterior:
        # Run lengths preserve transparent details between feet and trim so
        # every pixel outside the product silhouette shows the selected room.
        mask = alpha.point(lambda level: 255 if level >= 128 else 0).tobytes()
        for y in range(HEIGHT):
            offset = y * WIDTH
            for match in re.finditer(b"\xff+", mask[offset:offset + WIDTH]):
                start, end = match.span()
                data = pack_argb1555(artwork.crop((start, y, end, y + 1)))
                yield SPAN.pack((offset + start) * 2, len(data))
                yield data
        return

    # Cabinet source art uses black exterior mattes. Trace the solid silhouette
    # per row so dark speakers and trim enclosed by the edge stay opaque.
    red, green, blue, _ = artwork.split()
    visible = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(
        lambda level: 255 if level > 20 else 0)
    glass_left, glass_top, glass_right, glass_bottom = VIDEO
    for y in range(HEIGHT):
        bounds = visible.crop((0, y, WIDTH, y + 1)).getbbox()
        if bounds is None:
            continue
        left, _, right, _ = bounds
        regions = ((left, min(right, glass_left)), (max(left, glass_right), right)) \
            if glass_top <= y < glass_bottom else ((left, right),)
        for start, end in regions:
            if start < end:
                data = pack_argb1555(artwork.crop((start, y, end, y + 1)))
                yield SPAN.pack((y * WIDTH + start) * 2, len(data))
                yield data


def pack(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name in CABINETS:
        source = ROOT / "cabinets" / (name + "-1080p.png")
        data = b"".join(cabinet_spans(cabinet_artwork(source, name),
                                     transparent_exterior=name in TRANSPARENT_CABINETS))
        (folder / (name + ".cab.gz")).write_bytes(gzip.compress(data, compresslevel=6, mtime=0))
    for name in BACKGROUNDS[1:]:
        with Image.open(ROOT / "backgrounds" / (name + ".jpg")) as source:
            if source.size != (WIDTH, HEIGHT):
                raise ValueError("Expected a 1920x1080 background")
            data = pack_argb1555(source.convert("RGBA"))
        (folder / (name + ".bg.gz")).write_bytes(gzip.compress(data, compresslevel=6, mtime=0))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=ROOT / "scenes")
    pack(parser.parse_args().output)
