#!/usr/bin/env python3
"""Assemble the RetroTV MiSTer installer from its three build inputs."""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORKERS = (
    "retrotv-menu.sh", "retrotv-broadcast.py", "retrotv-music.py", "retrotv-news.py",
    "retrotv_guide.py", "retrotv_moon.py", "retrotv_space.py", "retrotv_weather.py",
    "retrotv_screenshots.py",
    "astronomy_engine-2.1.19-py3-none-any.whl", "assets/music-stock.png",
)
GALLERY = (
    "trinitron-xbr-1989", "zenith-space-command", "rca-colortrak-2000",
    "sharp-linytron", "panasonic-superflat", "jvc-d-series",
)


def package(rbf, main, ca, archive):
    files = [
        (HERE / "install.py", "install.py"),
        (ROOT / "INSTALL.md", "INSTALL.md"),
        (ROOT / "ATTRIBUTIONS.md", "ATTRIBUTIONS.md"),
        (ROOT / "COPYING", "COPYING"),
        (ROOT / "COPYING.LESSER", "COPYING.LESSER"),
        (ROOT / "LICENSE.txt", "LICENSE.txt"),
        (HERE / "THIRD_PARTY.md", "THIRD_PARTY.md"),
        (HERE / "RetroTV.mgl", "payload/_Other/RetroTV.mgl"),
        (rbf, "payload/_Other/.retrotv/RetroTV.rbf"),
        (main, "payload/linux/retrotv-main"),
        (ca, "payload/linux/retrotv-news-ca.pem"),
        (ROOT / "rtl/media_overlay_font.mem", "payload/linux/retrotv-news-font.mem"),
        (HERE / "Analyze_RetroTV_Channels.sh", "payload/Scripts/Analyze_RetroTV_Channels.sh"),
        (HERE / "v2/cabinet.raw", "payload/games/RetroTV/v2/cabinet.raw"),
    ]
    files.extend((HERE / name, "payload/linux/" + name) for name in WORKERS)
    for name in GALLERY:
        frame = "compact/" + name + ".raw"
        files.append((HERE / frame, "payload/games/RetroTV/" + frame))
    for marker in sorted((HERE / "channels").glob("CH */.retrotv-news")):
        files.append((marker, "payload/games/RetroTV/" + marker.relative_to(HERE).as_posix()))

    for source, _ in files:
        if not source.is_file() or not source.stat().st_size:
            raise ValueError("Missing release file: " + str(source))

    archive.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as bundle:
        for source, destination in files:
            bundle.write(source, destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rbf", "main", "ca", "archive"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    package(args.rbf, args.main, args.ca, args.archive)
