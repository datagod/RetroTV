"""Build RetroTV's Twin Galaxies bulletin from its public news and score lists."""

from datetime import date
from html.parser import HTMLParser
import re
import xml.etree.ElementTree as ET

SITE = "https://www.twingalaxies.com"
NEWS_SITEMAP = SITE + "/news-sitemap.xml"
SCORE_TICKER = "https://store.twingalaxies.com/"
PERFORMANCE = re.compile(r"https://www\.twingalaxies\.com/records/voting-performances/[0-9]+")
ARTICLE = re.compile(r"https://www\.twingalaxies\.com/newsDetails/[0-9]+")
ACCEPTED = "Recently accepted scores"
SUBMISSIONS = "Submission Watch"
HEADLINES = "Twin Galaxies news"


class ScoreTicker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scores = {}
        self.url = None
        self.column = "player"

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "a" and "tgh-tick__lnk" in classes:
            url = attrs.get("href") or ""
            if PERFORMANCE.fullmatch(url):
                self.url = url
                self.fields = {"g": [], "s": [], "r": [], "player": []}
                self.column = "player"
        elif tag == "span" and self.url:
            self.column = next((key for key in ("g", "s", "r") if key in classes), None)

    def handle_endtag(self, tag):
        if not self.url:
            return
        if tag == "span":
            self.column = "player"
        elif tag == "a":
            fields = {key: " ".join("".join(parts).split()) for key, parts in self.fields.items()}
            if fields["r"].upper() == "ACCEPTED" and all(fields[key] for key in ("g", "s", "player")):
                self.scores.setdefault(self.url, (fields["g"], fields["s"], fields["player"]))
            self.url = None

    def handle_data(self, data):
        if self.url and self.column:
            self.fields[self.column].append(data)


class ScoreMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.properties = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        attrs = dict(attrs)
        prop = attrs.get("property")
        if prop in ("og:title", "og:description"):
            self.properties[prop] = attrs.get("content") or ""


def news_rows(payload, normalize):
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("unexpected sitemap XML declaration")
    headlines, submissions = [], []
    seen = set()
    for entry in ET.fromstring(payload).findall("./{*}url"):
        url = entry.findtext("{*}loc", "")
        article = entry.find("{*}news")
        if not ARTICLE.fullmatch(url) or url in seen or article is None:
            continue
        title = normalize(article.findtext("{*}title", ""))
        stamp = article.findtext("{*}publication_date", "")
        if not title:
            continue
        try:
            day = date.fromisoformat(stamp[:10]).strftime("%b %d")
        except ValueError:
            continue
        seen.add(url)
        if title.casefold().startswith("submission watch:"):
            submissions.append(normalize(day + " / " + title.partition(":")[2].strip()))
        else:
            headlines.append(normalize(day + " / " + title))
    if not headlines and not submissions:
        raise ValueError("news sitemap has no current stories")
    return headlines[:12], submissions[:6]


def score_row(url, score, get, normalize, detailed=False):
    game, result, player = score
    row = [normalize(f"{game} / {result} / {player}")]
    if detailed:
        try:
            meta = ScoreMetadata()
            meta.feed(get(url).decode("utf-8"))
            title = meta.properties.get("og:title", "").removeprefix("Twin Galaxies ")
            platform, separator, _ = title.partition(" - ")
            track = meta.properties.get("og:description", "")
            if separator and platform and track:
                row.append(normalize(f"{platform} / {track}"))
        except (OSError, ValueError) as error:
            print(f"Twin Galaxies score details unavailable: {error}", flush=True)
    return row


def accepted_rows(get, normalize):
    parser = ScoreTicker()
    parser.feed(get(SCORE_TICKER).decode("utf-8"))
    if not parser.scores:
        raise ValueError("accepted-score ticker has no usable entries")
    rows = []
    entries = list(parser.scores.items())[:10]
    for index, (url, score) in enumerate(entries):
        rows.extend(score_row(url, score, get, normalize, detailed=index < 4))
    return rows, len(entries)


def fetch(get, normalize, previous=None):
    scores = headlines = submissions = None
    try:
        headlines, submissions = news_rows(get(NEWS_SITEMAP), normalize)
    except (OSError, ValueError, ET.ParseError) as error:
        print(f"Twin Galaxies news sitemap unavailable: {error}", flush=True)
    try:
        scores, count = accepted_rows(get, normalize)
    except (OSError, ValueError) as error:
        print(f"Twin Galaxies score ticker unavailable: {error}", flush=True)
    if headlines is None and scores is None:
        raise ValueError("no Twin Galaxies source returned usable results")

    saved = dict((previous or {}).get("sections", []))
    source = "Source: Twin Galaxies"
    notices = [source]
    if scores is None:
        scores = saved.get(ACCEPTED, [])
        notices.append("Showing saved scores" if scores else "Accepted scores unavailable")
        count = 0
    if headlines is None:
        headlines = saved.get(HEADLINES, [])
        submissions = saved.get(SUBMISSIONS, [])
        notices.append("Showing saved news" if headlines or submissions else "News unavailable")
    sections = [["Daily score & news wire", notices]]
    for heading, rows in ((ACCEPTED, scores), (SUBMISSIONS, submissions), (HEADLINES, headlines)):
        if rows:
            sections.append([heading, rows])
    print(f"Twin Galaxies fetched {count} accepted scores, {len(submissions)} submission stories, "
          f"and {len(headlines)} news headlines.", flush=True)
    return {"title": "Daily / " + date.today().isoformat(), "sections": sections}
