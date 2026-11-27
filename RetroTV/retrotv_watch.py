"""Fetch and cache MiSTer's once-per-day release bulletin."""

from datetime import date
from email.utils import parsedate_to_datetime
from html import unescape
import json
import re
import xml.etree.ElementTree as ET

TRACKER = "https://misterzine.fyi/releases/feed.xml"
GITHUB = "https://api.github.com/repos/"
UPDATE_ALL = "https://raw.githubusercontent.com/theypsilon/Update_All_MiSTer/master/CHANGELOG.md"
APPS = (
    ("MisterZine Arcade Frontend", "matijaerceg/misterzine-on-device"),
    ("MisterZine Plex Core", "matijaerceg/misterzine-plex-core"),
)
REPO_LINK = re.compile(r'https://github\.com/([\w.-]+/[\w.-]+)/commits(?:[/?"#]|$)', re.ASCII)
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(https?://[^)]+\)")


def tracker_items(payload, normalize):
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("unexpected XML declarations")
    seen = set()
    for item in ET.fromstring(payload).findall("./channel/item"):
        categories = [field.text for field in item.findall("category")]
        if len(categories) < 2 or categories[0] not in ("new", "updated"):
            continue
        title = normalize(re.sub(r"^\[[^\]]+\]\s*", "", item.findtext("title", "")))
        key = title.casefold()
        if not title or key in seen:
            continue
        try:
            day = parsedate_to_datetime(item.findtext("pubDate", "")).date().isoformat()
        except (ValueError, TypeError):
            continue
        seen.add(key)
        description = unescape(item.findtext("description", ""))
        repo = REPO_LINK.search(description)
        guid = item.findtext("guid", "").split(":", 1)[0]
        provider = "MiSTer Distribution" if guid == "distribution_mister" else normalize(guid)
        detail = [normalize(row) for row in re.findall(r"<p>(.*?)</p>", description, re.DOTALL)
                  if not re.search(r"public MiSTer databases|<a\s|<img\s", row)]
        detail = [row for row in detail if row]
        yield {
            "title": title, "new": categories[0] == "new", "arcade": categories[1] == "Arcade",
            "day": day, "provider": provider,
            "detail": detail[:2], "repo": repo[1] if repo else "",
        }


def note_text(value, normalize):
    value = MARKDOWN_LINK.sub(r"\1", value)
    return normalize(re.sub(r"https?://\S+", "", value).replace("**", "").replace("`", "").lstrip("#-* "))


def update_all_notes(get, normalize):
    try:
        versions = re.split(r"^## (?=Version )", get(UPDATE_ALL).decode("utf-8"), flags=re.MULTILINE)
        lines = versions[1].splitlines()
        changes = [note_text(line, normalize) for line in lines[1:]
                   if line.lstrip().startswith(("* ", "- "))]
        return [normalize(lines[0]), *[line for line in changes if line][:2]]
    except (OSError, ValueError, IndexError) as error:
        print(f"MiSTer Watch Update All changelog unavailable: {error}", flush=True)
        return []


def notes_from_github(repo, endpoint, get, normalize):
    try:
        records = json.loads(get(GITHUB + repo + endpoint))
        if not isinstance(records, list):
            raise ValueError("unexpected GitHub response")
        if "/commits" in endpoint:
            notes = []
            for record in records:
                message = record["commit"]["message"].partition("\n")[0]
                if not message.startswith(("Merge ", "Release ")):
                    line = normalize(message)
                    if line and line not in notes:
                        notes.append(line)
            return notes[:3]
        for record in records:
            if record.get("draft") or not record.get("published_at"):
                continue
            version = normalize(record.get("name") or record["tag_name"])
            day = date.fromisoformat(record["published_at"][:10]).isoformat()
            label = " / PREVIEW" if record.get("prerelease") else ""
            notes = []
            for line in (record.get("body") or "").splitlines():
                line = note_text(line, normalize)
                if len(line) >= 18 and not line.startswith(("Full Changelog", "What's Changed", "MisterZine Plex Core ")):
                    notes.append(line)
            return [normalize(f"{version} / {day}{label}"), *notes[:2]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"MiSTer Watch source {repo} unavailable: {error}", flush=True)
    return []


def arcade_line(item, normalize):
    title = item["title"].removesuffix(" (Arcade)")
    day = date.fromisoformat(item["day"]).strftime("%b %d")
    facts = [row for row in item["detail"] if not row.startswith("Core:")]
    return normalize(" / ".join([title, day, *facts]))


def fetch(get, normalize, _previous=None):
    try:
        items = list(tracker_items(get(TRACKER), normalize))
    except (OSError, ValueError, ET.ParseError) as error:
        print(f"MiSTer Watch tracker unavailable: {error}", flush=True)
        items = []
    cores = [item for item in items if not item["arcade"]][:6]
    new_arcades = [item for item in items if item["arcade"] and item["new"]][:9]
    updated_arcades = [item for item in items if item["arcade"] and not item["new"]][:7]
    core_sections, releases, noted = [], [], set()
    for item in cores:
        repo = item["repo"]
        notes = []
        if repo.casefold().startswith("mister-devel/") and repo not in noted and len(noted) < 4:
            noted.add(repo)
            notes = notes_from_github(repo, "/commits?per_page=5", get, normalize)
        label = "New core" if item["new"] else "Core update"
        detail = [*item["detail"], *("Dev: " + note[:175] for note in notes[:2])]
        title = item["title"].removesuffix(" (Computer core)").removesuffix(" (Console core)")
        meta = " / ".join(filter(None, (label, item["day"], item["provider"])))
        core_sections.append([title, [normalize(meta), *detail]])
    main = notes_from_github("MiSTer-devel/Main_MiSTer", "/commits?per_page=4", get, normalize)
    if main:
        releases.append(["MiSTer Main development", ["Developer changes from GitHub", *main]])
    updater = update_all_notes(get, normalize)
    if updater:
        releases.append(["Update All", updater])
    for label, repo in APPS:
        notes = notes_from_github(repo, "/releases?per_page=2", get, normalize)
        if notes:
            releases.append([label, notes])
    if not (core_sections or new_arcades or updated_arcades or releases):
        raise ValueError("no MiSTer updates returned usable results")
    sections = [["Daily release wire", [
        "Core and arcade listings: MisterZine tracker",
        "Development and release notes: GitHub",
    ]]]
    sections += core_sections[:3] + releases + core_sections[3:]
    for label, entries in (("New arcade releases", new_arcades), ("Arcade updates", updated_arcades)):
        if entries:
            sections.append([label, [
                arcade_line(item, normalize) for item in entries
            ]])
    print(f"MiSTer Watch fetched {len(cores)} core listings, {len(new_arcades) + len(updated_arcades)}"
          f" arcade listings and {len(releases)} developer reports.", flush=True)
    return {"title": "Daily / " + date.today().isoformat(), "sections": sections}
