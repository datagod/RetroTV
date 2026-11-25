"""Pack the six 1080p cabinet images for the RetroTV gallery."""

from array import array
from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parent
XBR_RECT = (448, 180, 1472, 900)
XBR_SOURCE_TUBE = (600, 260, 1320, 800)
XBR_TUBE = (600, 290, 1320, 770)
XBR_GALLERY = (
    "zenith-space-command",
    "rca-colortrak-2000",
    "sharp-linytron",
    "panasonic-superflat",
    "jvc-d-series",
)


def pack_argb1555(image):
    words = array("H", (
        (0x8000 | ((red >> 3) << 10) | ((green >> 3) << 5) | (blue >> 3)) if alpha >= 128 else 0
        for red, green, blue, alpha in image.getdata()
    ))
    if sys.byteorder != "little":
        words.byteswap()
    return words.tobytes()


def prepare_xbr(source):
    with Image.open(source) as image:
        artwork = image.convert("RGBA")
    if artwork.size != (1920, 1080):
        raise ValueError("Expected a 1920x1080 XBR artwork canvas")
    if artwork.getchannel("A").crop(XBR_SOURCE_TUBE).getextrema() != (0, 0):
        raise ValueError("The original XBR tube must be transparent")

    # Fit the painted bezel to the native picture. Video pixels are supplied
    # separately by the core at the opening and are never resampled.
    left, top, right, bottom = XBR_RECT
    _, old_top, _, old_bottom = XBR_SOURCE_TUBE
    tube_left, new_top, tube_right, new_bottom = XBR_TUBE
    result = Image.new("RGBA", (right - left, bottom - top))
    for src_top, src_end, dest_top, dest_end in (
        (top, old_top, top, new_top),
        (old_top, old_bottom, new_top, new_bottom),
        (old_bottom, bottom, new_bottom, bottom),
    ):
        band = artwork.crop((left, src_top, right, src_end))
        result.paste(band.resize((right - left, dest_end - dest_top), Image.Resampling.BICUBIC),
                     (0, dest_top - top))

    # Define the exact cutoff at pixel boundaries, including around dark bevels.
    mask = Image.new("L", result.size, color=255)
    mask.paste(0, (tube_left - left, new_top - top, tube_right - left, new_bottom - top))
    result.putalpha(mask)
    return pack_argb1555(result)


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    (output / "compact").mkdir(parents=True, exist_ok=True)
    (output / "v2").mkdir(parents=True, exist_ok=True)
    for name in ("trinitron-xbr-1989", *XBR_GALLERY):
        source = ROOT / "cabinets" / (name + "-1080p.png")
        (output / "compact" / (name + ".raw")).write_bytes(prepare_xbr(source))
    with Image.open(ROOT / "assets/startup-bezel.png") as image:
        (output / "v2/cabinet.raw").write_bytes(pack_argb1555(image.convert("RGBA")))
