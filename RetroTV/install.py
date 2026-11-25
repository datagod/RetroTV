#!/usr/bin/env python3
"""Install the RetroTV release package on a MiSTer SD card."""

import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

PAYLOAD = Path(__file__).resolve().parent / "payload"
CARD = Path("/media/fat")
MAIN = b"main=linux/retrotv-main"
START_COMMAND = b"nohup /bin/sh /media/fat/linux/retrotv-menu.sh >/dev/null 2>&1 &"


def write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        staged = Path(temp.name)
        try:
            temp.write(data)
            temp.close()
            staged.chmod(mode)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def update_config(path, edit, mode):
    previous = path.read_bytes() if path.exists() else b""
    updated = edit(previous)
    if updated == previous:
        return
    backup = path.with_name(path.name + ".retrotv.bak")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    write(path, updated, mode)


def add_core_setting(data):
    line_end = b"\r\n" if b"\r\n" in data else b"\n"
    lines = data.splitlines(keepends=True)
    inside_retro = False
    section_end = None
    for index, line in enumerate(lines):
        match = re.match(rb"^\s*\[([^\]]+)\]", line)
        if match:
            if inside_retro and section_end is None:
                section_end = index
            inside_retro = match[1].lower() == b"retrotv"
            if inside_retro:
                section_end = None
        if inside_retro and re.match(rb"^\s*main\s*=", line, re.IGNORECASE):
            lines[index] = MAIN + line_end
            return b"".join(lines)
    if section_end is not None or inside_retro:
        index = len(lines) if inside_retro else section_end
        if index and not lines[index - 1].endswith(b"\n"):
            lines[index - 1] += line_end
        lines.insert(index, MAIN + line_end)
        return b"".join(lines)
    prefix = data.rstrip(b"\r\n") + line_end * 2 if data else b""
    return prefix + b"[RetroTV]" + line_end + MAIN + line_end


def add_startup_command(data):
    if any(START_COMMAND.split(b" >/dev")[0] in line
           for line in data.splitlines() if not line.lstrip().startswith(b"#")):
        return data
    current = data.rstrip(b"\r\n") + b"\n" if data else b"#!/bin/sh\n"
    return current + b"\n# RetroTV channel controller\n" + START_COMMAND + b"\n"


def install(card, payload):
    if not (card / "MiSTer").is_file():
        raise ValueError("MiSTer executable missing from " + str(card))
    if not (payload / "_Other/.retrotv/RetroTV.rbf").is_file():
        raise ValueError("Extract the entire RetroTV release before installing.")
    for source in sorted(payload.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(payload)
        target = card / relative
        if source.name == ".retrotv-news" and target.exists():
            continue
        executable = source.suffix == ".sh" or source.name == "retrotv-main"
        write(target, source.read_bytes(), 0o755 if executable else 0o644)

    update_config(card / "MiSTer.ini", add_core_setting, 0o644)
    update_config(card / "linux/user-startup.sh", add_startup_command, 0o755)


if __name__ == "__main__":
    try:
        if sys.version_info < (3, 9):
            raise ValueError("RetroTV requires Python 3.9 or newer on the MiSTer.")
        if os.geteuid() != 0:
            raise ValueError("Run the installer as root on your MiSTer.")
        install(CARD, PAYLOAD)
    except (OSError, ValueError) as error:
        sys.exit("RetroTV installation failed: " + str(error))
    print("RetroTV is installed. Reboot the MiSTer and select Other > RetroTV.")
