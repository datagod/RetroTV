#!/usr/bin/env python3
"""Turn the measured Trinitron PNG into a 144x96 indexed ROM.

Raster v0.10.0 already uses 545 of 553 M10K blocks. A 4-bit pixel occupies
one 2048-deep M10K word, so eight free blocks hold at most 16384 pixels.
144x96 is 13824 pixels, exactly 3:2, and scales by 5 onto the 720x480 raster.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "RetroTV" / "assets" / "tv_frame.png"
OUT = ROOT / "rtl" / "retrotv"
VIDEO = (720, 480)
ROM = (144, 96)
SCALE = VIDEO[0] // ROM[0]
COLORS = 15


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def sample_block(image: Image.Image, rom_x: int, rom_y: int) -> tuple[int, int, int, int]:
    # Center of the 5x5 stored-pixel block this ROM entry represents.
    pixel = image.getpixel((rom_x * SCALE + SCALE // 2, rom_y * SCALE + SCALE // 2))
    return tuple(pixel)


def punch_glass(stored: Image.Image, indices: list[int]) -> None:
    """Keep the measured glass clear. Lanczos leaves a few opaque specks inside it."""
    pixels = stored.load()
    xs = []
    ys = []
    for y in range(VIDEO[1]):
        for x in range(VIDEO[0]):
            if pixels[x, y][3] < 128:
                xs.append(x)
                ys.append(y)
    if not xs:
        fail("The resized cabinet has no transparent glass.")
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    for rom_y in range(ROM[1]):
        for rom_x in range(ROM[0]):
            center_x = rom_x * SCALE + SCALE // 2
            center_y = rom_y * SCALE + SCALE // 2
            if left <= center_x <= right and top <= center_y <= bottom:
                indices[rom_y * ROM[0] + rom_x] = 0


def quantize(samples: list[tuple[int, int, int, int]]) -> tuple[list[int], list[tuple[int, int, int]]]:
    opaque = [(red, green, blue) for red, green, blue, alpha in samples if alpha >= 128]
    if not opaque:
        fail("The cabinet PNG has no opaque pixels.")
    sheet = Image.new("RGB", (len(opaque), 1))
    sheet.putdata(opaque)
    reduced = sheet.quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw_palette = reduced.getpalette() or []
    palette = [(0, 0, 0)]
    for index in range(COLORS):
        base = index * 3
        if base + 2 < len(raw_palette):
            palette.append((raw_palette[base], raw_palette[base + 1], raw_palette[base + 2]))
        else:
            palette.append((0, 0, 0))
    mapped = iter(reduced.getdata())
    indices = []
    for _red, _green, _blue, alpha in samples:
        if alpha < 128:
            indices.append(0)
        else:
            indices.append(next(mapped) + 1)
    return indices, palette


def write_mem(indices: list[int], palette: list[tuple[int, int, int]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pixels = OUT / "bezel_pixels.mem"
    colors = OUT / "bezel_palette.mem"
    pixels.write_text("\n".join(f"{value:x}" for value in indices) + "\n", encoding="ascii")
    colors.write_text(
        "\n".join(f"{red:02x}{green:02x}{blue:02x}" for red, green, blue in palette) + "\n",
        encoding="ascii",
    )
    if pixels.read_text(encoding="ascii").count("\n") != ROM[0] * ROM[1]:
        fail("Pixel ROM length does not match 144x96.")
    if colors.read_text(encoding="ascii").count("\n") != 16:
        fail("Palette ROM does not contain 16 entries.")


def write_preview(indices: list[int], palette: list[tuple[int, int, int]]) -> None:
    preview = Image.new("RGB", VIDEO, (20, 90, 160))
    draw = preview.load()
    for rom_y in range(ROM[1]):
        for rom_x in range(ROM[0]):
            index = indices[rom_y * ROM[0] + rom_x]
            if index == 0:
                continue
            color = palette[index]
            x0 = rom_x * SCALE
            y0 = rom_y * SCALE
            for y in range(y0, y0 + SCALE):
                for x in range(x0, x0 + SCALE):
                    draw[x, y] = color
    destination = ROOT.parent / "RetroTV" / "output" / "fpga-bezel-preview.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    preview.save(destination)
    print(f"Preview: {destination}")


def transparent_box(indices: list[int]) -> tuple[int, int, int, int]:
    xs = [index % ROM[0] for index, value in enumerate(indices) if value == 0]
    ys = [index // ROM[0] for index, value in enumerate(indices) if value == 0]
    if not xs:
        fail("The ROM has no transparent glass.")
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    return left, top, right - left + 1, bottom - top + 1


def main() -> None:
    if VIDEO[0] % ROM[0] or VIDEO[1] % ROM[1] or VIDEO[0] // ROM[0] != VIDEO[1] // ROM[1]:
        fail("ROM size must divide 720x480 by the same integer.")
    if not SOURCE.is_file():
        fail(f"Missing cabinet PNG: {SOURCE}")
    with Image.open(SOURCE) as source:
        frame = source.convert("RGBA")
    if frame.size != (1920, 1080):
        fail(f"{SOURCE} is {frame.size[0]}x{frame.size[1]}. Expected the 1920x1080 measured cabinet.")
    stored = frame.resize(VIDEO, Image.Resampling.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    stored.save(OUT / "trinitron.png")
    samples = [sample_block(stored, x, y) for y in range(ROM[1]) for x in range(ROM[0])]
    indices, palette = quantize(samples)
    punch_glass(stored, indices)
    write_mem(indices, palette)
    write_preview(indices, palette)
    left, top, width, height = transparent_box(indices)
    opaque = sum(value != 0 for value in indices)
    print(f"ROM: {ROM[0]}x{ROM[1]}, {opaque} opaque, {len(indices) - opaque} clear")
    print(f"Glass in ROM pixels: x={left} y={top} {width}x{height}")
    print(f"Glass in 720x480 pixels: x={left * SCALE} y={top * SCALE} {width * SCALE}x{height * SCALE}")
    print(f"Wrote {OUT / 'bezel_pixels.mem'}")
    print(f"Wrote {OUT / 'bezel_palette.mem'}")


if __name__ == "__main__":
    main()
