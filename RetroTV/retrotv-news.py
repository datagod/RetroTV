#!/usr/bin/env python3
"""Fetch and display the scrolling RetroTV news bulletin."""

import argparse
import contextlib
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
import html
from importlib import import_module
from itertools import zip_longest
import json
import mmap
import os
from pathlib import Path
import re
import signal
import ssl
import tempfile
import textwrap
from threading import Thread
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET

FEEDS = {
    "BBC NEWS": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "NPR": "https://feeds.npr.org/1004/rss.xml",
    "DEUTSCHE WELLE": "https://rss.dw.com/xml/rss-en-all",
}
STOCK_FEEDS = {
    "CNBC TECH": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "TECHCRUNCH AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "SPACENEWS": "https://spacenews.com/feed/",
}
STOCK_TICKERS = ("SPCX", "TSLA", "ANT", "NVDA", "AMD", "MSFT", "GOOGL", "RKLB")
NASDAQ_QUOTE = "https://api.nasdaq.com/api/quote/{}/info?assetclass=stocks"
STOCK_MARKER = "stock"
STOCK_REFRESH_SECONDS = 300
MAX_BYTES = 512 * 1024
MAX_PER_FEED = 24
MAX_HEADLINES = MAX_PER_FEED * len(FEEDS)
REFRESH_SECONDS = 600
PANEL_REFRESH = {"guide": 60, "space": 120}
PANEL_HEADER = {
    "weather": ("CH 14  /  WEATHER", "LOCAL WEATHER"),
    "guide": ("CH 15 / WHAT'S ON NOW", "RETROTV PROGRAM GUIDE"),
    "space": ("CH 16  /  SPACE DESK", "LAUNCHES / ISS / NEWS"),
    "watch": ("CH 21 / MISTER WATCH", "DAILY RELEASE WIRE"),
    "twin-galaxies": ("CH 22 / TWIN GALAXIES", "DAILY SCORE WIRE"),
}
DAILY_BULLETINS = {
    "watch": ("MiSTer Watch", "retrotv_watch"),
    "twin-galaxies": ("Twin Galaxies", "retrotv_twingalaxies"),
}
RETRY_SECONDS = 60
CACHE_NAME = ".latest-bulletin.json"
REFRESH_FILE = "news-refresh-minutes.txt"
ASSET_DIR = Path(__file__).resolve().parent
FONT_PATH = ASSET_DIR / "retrotv-news-font.mem"
CA_PATH = ASSET_DIR / "retrotv-news-ca.pem"

# The FPGA reads row n at n * ROW_BYTES in the selected 8 MiB page.
DDR_BASE = 0x32800000
ROWS = 4096
ROW_BYTES = 2048
PAGE_BYTES = ROWS * ROW_BYTES
LAYOUTS = ((428, 3, 19), (640, 4, 26), (720, 4, 34))

BLUE = (8, 32, 127)
PANEL = (16, 49, 156)
WHITE = (241, 246, 255)
AMBER = (255, 216, 113)
CYAN = (127, 215, 249)
RULE = (71, 116, 203)
GREEN = (116, 242, 174)
RED = (255, 162, 154)


def normalize_title(title):
    title = html.unescape(title).translate(str.maketrans({
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-", "\u2026": "...",
    }))
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    title = " ".join(re.sub(r"<[^>]*>", " ", title).split())
    title = "".join(ch for ch in title if 32 <= ord(ch) < 127)
    return title if len(title) <= 180 else title[:177].rstrip() + "..."


def parse_feed(payload):
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("unexpected XML declarations")
    root = ET.fromstring(payload)
    titles = []
    seen = set()
    for item in root.findall("./channel/item"):
        text = normalize_title(item.findtext("title", default=""))
        key = text.casefold()
        if text and key not in seen:
            titles.append(text)
            seen.add(key)
            if len(titles) >= MAX_PER_FEED:
                break
    if not titles:
        raise ValueError("RSS has no usable headlines")
    return titles


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError("feed tried to leave HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_url(url, context, *, binary=False, accept=None):
    opener = urllib.request.build_opener(HTTPSRedirect(), urllib.request.HTTPSHandler(context=context))
    headers = {"User-Agent": "RetroTV/1.0 (personal news reader)"}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    with opener.open(request, timeout=8) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or (not binary and b"\0" in data):
        raise ValueError("invalid response length or encoding")
    return data


def fetch_feed(source, url, context):
    try:
        return [(source, title) for title in parse_feed(read_url(url, context))]
    except (OSError, ValueError, ET.ParseError) as error:
        print("{} feed unavailable: {}".format(source, error), flush=True)
        return []


def load_quote(quote):
    if not isinstance(quote, dict):
        return None
    price = quote.get("price")
    change = quote.get("change")
    time_et = quote.get("time")
    session = quote.get("session")
    if (not isinstance(price, str) or len(price) > 8
            or not re.fullmatch(r"\$[0-9]{1,7}(?:\.[0-9]{2})?", price)
            or not isinstance(change, str) or len(change) > 7
            or (change != "--" and not re.fullmatch(r"[+-]?[0-9]{1,3}\.[0-9]{1,2}%", change))
            or not isinstance(time_et, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", time_et)
            or not isinstance(session, str) or not re.fullmatch(r"[A-Z -]{0,18}", session)):
        return None
    datetime.fromisoformat(time_et)
    return {"price": price, "change": change, "time": time_et, "session": session}


def fetch_quote(ticker, context):
    try:
        data = json.loads(read_url(NASDAQ_QUOTE.format(ticker), context))["data"]
        if data["symbol"] != ticker:
            raise ValueError("quote symbol mismatch")
        quote = data["primaryData"]
        raw_price = quote["lastSalePrice"].replace(",", "")
        if not re.fullmatch(r"\$[0-9]{1,7}(?:\.[0-9]{1,8})?", raw_price):
            raise ValueError("last sale price missing")
        price = Decimal(raw_price[1:])
        if not 0 < price < 1_000_000:
            raise ValueError("last sale price out of range")
        display_price = "$" + format(price, ".2f")
        if len(display_price) > 8:
            display_price = "$" + format(price, ".0f")
        change = quote.get("percentageChange") or "--"
        if len(change) > 7 or not re.fullmatch(r"[+-]?[0-9]+\.[0-9]{1,2}%", change):
            change = "--"
        raw_time = quote["lastTradeTimestamp"].removeprefix("Closed at ")
        time_et = datetime.strptime(raw_time, "%b %d, %Y %I:%M %p ET").isoformat(timespec="minutes")
        session = (data.get("marketStatus") or "").upper()
        return load_quote({
            "price": display_price,
            "change": change,
            "time": time_et,
            "session": session if re.fullmatch(r"[A-Z -]{0,18}", session) else "",
        })
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
        print("{} quote unavailable: {}".format(ticker, error), flush=True)
        return None


def fetch(stock=False, previous=None):
    context = ssl.create_default_context(cafile=str(CA_PATH))
    feeds = STOCK_FEEDS if stock else FEEDS
    results = [[] for _ in feeds]
    quotes = {}

    def collect_news(index, source, url):
        results[index] = fetch_feed(source, url, context)

    def collect_quote(ticker):
        quote = fetch_quote(ticker, context)
        if quote:
            quotes[ticker] = quote

    # Daemon jobs let the controller switch channels during network requests.
    jobs = [Thread(target=collect_news, args=(index, label, url), daemon=True)
            for index, (label, url) in enumerate(feeds.items())]
    if stock:
        jobs.extend(Thread(target=collect_quote, args=(ticker,), daemon=True) for ticker in STOCK_TICKERS)
    for job in jobs:
        job.start()
    for job in jobs:
        job.join()

    titles = []
    seen = set()
    for group in zip_longest(*results):
        for source, title in filter(None, group):
            key = re.sub(r"[^a-z0-9]", "", title.casefold())
            if key and key not in seen:
                titles.append({"source": source, "title": title})
                seen.add(key)
    if not titles and not quotes:
        raise ValueError("no news or market data returned usable results")

    updated = int(time.time())
    counts = ", ".join("{} {}".format(items[0][0], len(items)) for items in results if items)
    print("Fetched {} unique headlines ({}).".format(len(titles), counts or "none"), flush=True)
    if not stock:
        return {"updated": updated, "titles": titles}

    previous = previous or {}
    missing = [ticker for ticker in STOCK_TICKERS if ticker not in quotes]
    print("Fetched {} of {} Nasdaq quotes.".format(len(quotes), len(STOCK_TICKERS)), flush=True)
    return {
        "updated": updated,
        "news_updated": updated if titles else previous.get("news_updated", 0),
        "news_offline": not titles,
        "titles": titles or previous.get("titles", []),
        "quotes": {**previous.get("quotes", {}), **quotes},
        "quote_missing": missing,
    }


def load_bulletin(path, stock=False):
    try:
        with path.open("rb") as source:
            data = json.loads(source.read(32 * 1024))
        stamp = data["updated"]
        if type(stamp) is not int or stamp <= 0 or not isinstance(data["titles"], list):
            return None
        if len(data["titles"]) > MAX_HEADLINES or (not stock and not data["titles"]):
            return None
        titles = []
        legacy = False
        for item in data["titles"]:
            if isinstance(item, str) and not stock:
                item = {"source": "BBC NEWS", "title": item}
                legacy = True
            if (not isinstance(item, dict) or item.get("source") not in (STOCK_FEEDS if stock else FEEDS) or
                    not isinstance(item.get("title"), str)):
                return None
            title = normalize_title(item["title"])
            if not title:
                return None
            titles.append({"source": item["source"], "title": title})
        bulletin = {"updated": stamp, "titles": titles, "legacy": legacy}
        if stock:
            stored = data.get("quotes", {})
            if not isinstance(stored, dict):
                return None
            quotes = {}
            for ticker in STOCK_TICKERS:
                quote = load_quote(stored.get(ticker))
                if quote:
                    quotes[ticker] = quote
            news_updated = data.get("news_updated", 0)
            if type(news_updated) is not int or not 0 <= news_updated <= stamp:
                return None
            missing = data.get("quote_missing", [])
            if not isinstance(missing, list):
                return None
            if not titles and not quotes:
                return None
            bulletin.update(news_updated=news_updated, news_offline=bool(data.get("news_offline")),
                            quotes=quotes, quote_missing=[ticker for ticker in STOCK_TICKERS if ticker in missing])
        return bulletin
    except (OSError, ValueError, TypeError, KeyError):
        return None


def save_bulletin(path, bulletin):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".news-", delete=False) as output:
        pending = Path(output.name)
        try:
            json.dump(bulletin, output)
            output.write("\n")
            output.close()
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


def packed_color(rgb):
    r, g, b = rgb
    word = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
    return word.to_bytes(2, "little")


def read_font(path):
    with path.open(encoding="ascii") as source:
        rows = [int(line, 2) for line in source.read().splitlines()
                if line.strip() and not line.startswith("//")]
    if len(rows) != 2048 or any(row > 31 for row in rows):
        raise ValueError("Invalid RetroTV font")
    return tuple(rows)


class BulletinRenderer:
    def __init__(self, font):
        self.font = font

    @lru_cache(maxsize=4096)
    def glyph_row(self, char, line, scale, foreground, background):
        bits = self.font[ord(char) * 8 + line]
        colors = [foreground if bits & (16 >> n) else background for n in range(5)]
        return b"".join(color * scale for color in colors + [background])

    def render(self, bulletin, layout, offline=False, stock=False, weather=False, panel=""):
        if weather:
            panel = "weather"
        width, scale, margin = layout
        blue = packed_color(BLUE)
        opacity_row = blue * width + bytes(ROW_BYTES - width * 2)
        image = bytearray(opacity_row * ROWS)
        colors = {name: packed_color(value) for name, value in
                  (("panel", PANEL), ("white", WHITE), ("amber", AMBER), ("cyan", CYAN),
                   ("rule", RULE), ("green", GREEN), ("red", RED))}
        step = scale * 9
        columns = (width - 2 * margin) // (6 * scale)

        def bar(y_start, y_end, color, x, right):
            row = color * (right - x)
            for y in range(y_start, y_end):
                start = y * ROW_BYTES + 2 * x
                image[start:start + len(row)] = row

        def text(y, words, color, background=blue, font_scale=scale, column=0):
            assert (column + len(words)) * 6 * font_scale <= width - 2 * margin
            for line in range(7):
                row = b"".join(self.glyph_row(char, line, font_scale, color, background) for char in words)
                for replica in range(font_scale):
                    start = (y + line * font_scale + replica) * ROW_BYTES + (margin + column * 6 * font_scale) * 2
                    image[start:start + len(row)] = row

        label_scale = 2 if scale == 3 else 3
        label_step = label_scale * 9
        bulletin = bulletin or {}

        def stock_board(y):
            quotes = bulletin.get("quotes", {})
            missing = STOCK_TICKERS if offline else bulletin.get("quote_missing", [])
            sessions = {quote["session"] for quote in quotes.values()}
            session = next(iter(sessions)) if len(sessions) == 1 else ""
            fact = session + " / USD" if session else "USD"
            text(y, "NASDAQ QUOTES", colors["cyan"])
            y += step
            if quotes:
                times = {quote["time"] for quote in quotes.values()}
                oldest = datetime.fromisoformat(min(times)).strftime("%b %d %I:%M %p").upper()
                when = ("OLDEST " if len(times) > 1 else "AS OF ") + oldest + " ET"
                text(y, when, colors["amber"], font_scale=label_scale)
                y += label_step
            text(y, fact, colors["cyan"], font_scale=label_scale)
            y += label_step + 4
            for ticker in STOCK_TICKERS:
                quote = quotes.get(ticker)
                flag = "*" if quote and ticker in missing else " "
                text(y, ticker + flag, colors["white"])
                if quote:
                    pct = quote["change"]
                    color = "white"
                    if pct.startswith("-") and pct != "--":
                        color = "red"
                    elif pct.startswith("+"):
                        color = "green"
                    text(y, quote["price"].rjust(8), colors["white"], column=6)
                    text(y, pct.rjust(7), colors[color], column=14)
                else:
                    text(y, "-- NO QUOTE", colors["amber"], column=8)
                y += step - 4
            if quotes and any(ticker in quotes for ticker in missing):
                text(y, "* LAST SAVED QUOTE", colors["amber"], font_scale=label_scale)
                y += label_step
            return y + 20

        bar(0, step * 2 + 15, colors["panel"], 0, width)
        bar(step * 2 + 15, step * 2 + 18, colors["amber"], 0, width)
        header = "CH 13  /  STOCK NEWS" if stock else "CH 12  /  NEWS"
        subtitle = "TECH  /  AI  /  SPACE" if stock else "WORLD NEWS  HEADLINES"
        if panel in PANEL_HEADER:
            header, default_subtitle = PANEL_HEADER[panel]
            caption = bulletin.get("title", default_subtitle).upper()
            subtitle = caption if len(caption) <= columns else caption[:columns-3].rstrip() + "..."
        text(10, header, colors["white"], colors["panel"])
        text(10 + step, subtitle, colors["cyan"], colors["panel"])

        y = step * 2 + 31
        boundaries = []
        gap = 40
        if panel in PANEL_HEADER:
            if offline or not bulletin:
                if panel in DAILY_BULLETINS:
                    if offline:
                        notice = "SHOWING SAVED BULLETIN" if bulletin.get("sections") else "RELEASE FEEDS UNAVAILABLE"
                    else:
                        notice = "WAITING FOR DAILY BULLETIN"
                elif panel == "weather":
                    notice = "LAST WEATHER REPORT" if bulletin else (
                        "WEATHER UNAVAILABLE" if offline else "LOCATING LOCAL WEATHER")
                else:
                    notice = "DATA UNAVAILABLE" if offline else (
                        "READING CHANNELS" if panel == "guide" else "CONNECTING TO SPACE FEEDS")
                for line in textwrap.wrap(notice, columns):
                    text(y, line, colors["amber"])
                    y += step
                y += 16
            for index, (heading, rows) in enumerate(bulletin.get("sections", [])):
                part = [(heading, "cyan", scale)]
                for row_index, row in enumerate(rows):
                    if panel == "guide":
                        part.append((row, "amber" if row.startswith("Next ") else "white", label_scale))
                    elif panel == "space":
                        color = "amber" if row.startswith(("T-", "Est. T-")) else "white"
                        part.append((row, color, scale if row_index == 0 else label_scale))
                    elif panel == "watch":
                        roundup = heading in ("New arcade releases", "Arcade updates")
                        color = "amber" if row_index == 0 and not roundup else "white"
                        part.append((row, color, 2 if roundup else label_scale))
                    elif panel == "twin-galaxies":
                        part.append((row, "amber" if index == 0 else "white", label_scale))
                    elif index == 0 and row_index < 2:
                        part.append((row, "amber" if row_index == 1 else "cyan", label_scale))
                    else:
                        part.append((row, "white", scale))
                lines = [(line, color, size) for words, color, size in part
                         for line in textwrap.wrap(
                             (normalize_title(words) if panel == "space" else words).upper(),
                             (width - 2 * margin) // (6 * size))]
                height = sum(size * 9 for _, _, size in lines) + 24
                if y + height + gap > ROWS:
                    break
                if index:
                    bar(y - 10, y - 8, colors["rule"], margin, width - margin)
                for line, color, size in lines:
                    text(y, line, colors[color], font_scale=size)
                    y += size * 9
                y += 24
                boundaries.append(y)
        else:
            if stock:
                y = stock_board(y)
            stamp = bulletin.get("news_updated" if stock else "updated")
            if stamp:
                date = time.strftime("%b %d %I:%M %p %Z", time.localtime(stamp)).upper()
                label = "NEWS UPDATED " if stock else "UPDATED "
                for line in textwrap.wrap(label + date, columns):
                    text(y, line, colors["amber"])
                    y += step
                y += 3
            if offline or bulletin.get("news_offline") or not bulletin:
                failed = offline or bulletin.get("news_offline")
                notice = "FEEDS UNAVAILABLE" if failed else "CONNECTING TO NEWS FEEDS"
                for line in textwrap.wrap(notice, columns):
                    text(y, line, colors["amber"])
                    y += step
            y += 19

            titles = bulletin.get("titles", [])
            label_height = label_scale * 7
            for index, item in enumerate(titles):
                if stock and index and index % 6 == 0 and y <= ROWS - 720:
                    y = stock_board(y + 12)
                lines = textwrap.wrap(item["title"].upper(), columns, break_on_hyphens=False)
                if y + label_height + 8 + len(lines) * step + 20 + gap > ROWS:
                    break
                bar(y - 9, y - 7, colors["rule"], margin, width - margin)
                text(y, item["source"], colors["cyan"], font_scale=label_scale)
                y += label_height + 8
                for line in lines:
                    text(y, line, colors["white"])
                    y += step
                y += 20
                boundaries.append(y)

        shown = len(boundaries)
        # Repeat short bulletins at whole-headline boundaries.
        if not boundaries:
            boundaries.append(y)
        while True:
            fitting = [end for end in boundaries if y + gap + end + gap <= ROWS]
            if not fitting:
                break
            start = (y + gap) * ROW_BYTES
            length = fitting[-1] * ROW_BYTES
            image[start:start + length] = image[:length]
            y += gap + fitting[-1]
        return image, shown


def publish(memory, tty, renderer, bulletin, bank, stock=False, offline=False, weather=False, panel=""):
    shown = 0
    for number, layout in enumerate(LAYOUTS):
        page, shown = renderer.render(bulletin, layout, offline, stock, weather, panel)
        start = (number * 2 + bank) * PAGE_BYTES
        memory[start:start + PAGE_BYTES] = page
    with tty.open("ab", buffering=0) as port:
        port.write(bytes([0xD4 + bank]))
    panel = "weather" if weather else panel
    kind = {"guide": "Program guide", "weather": "Weather", "space": "Space Desk"}.get(panel, "News")
    if panel in DAILY_BULLETINS:
        kind = DAILY_BULLETINS[panel][0]
    units = "sections" if panel else "headlines"
    print("{} bulletin published: {} visible {}, bank {}".format(kind, shown, units, bank), flush=True)
    return 1 - bank


def refresh_seconds(folder, stock=False, panel=""):
    try:
        with (folder / REFRESH_FILE).open(encoding="ascii") as source:
            minutes = int(source.read(24).strip())
        if 1 <= minutes <= 365 * 24 * 60:
            return minutes * 60
    except (OSError, ValueError):
        pass
    return PANEL_REFRESH.get(panel, STOCK_REFRESH_SECONDS if stock else REFRESH_SECONDS)


def channel_mode(folder):
    try:
        return (folder / ".retrotv-news").read_text(encoding="utf-8").strip().casefold()
    except (OSError, ValueError):
        return ""


def is_stock(folder):
    return channel_mode(folder) == STOCK_MARKER


def channel_bulletin(folder):
    mode = channel_mode(folder)
    cache = folder / CACHE_NAME
    if mode == "guide":
        import retrotv_guide

        bulletin, update = retrotv_guide.source(folder, normalize_title, ASSET_DIR)
        return mode, bulletin, update
    if mode == "space":
        import retrotv_space

        spec = retrotv_space.location_spec(folder)

        def update(previous):
            context = ssl.create_default_context(cafile=str(CA_PATH))
            return retrotv_space.refresh(spec, previous, read_url, context, normalize_title, parse_feed)

        return mode, retrotv_space.load(cache, spec), update
    if mode == "weather":
        import retrotv_weather

        spec = retrotv_weather.location_spec(folder)

        def update(previous):
            context = ssl.create_default_context(cafile=str(CA_PATH))
            return retrotv_weather.fetch(spec, previous, read_url, context, normalize_title)

        return mode, retrotv_weather.load(cache, spec, normalize_title), update
    stock = mode == STOCK_MARKER
    return mode, load_bulletin(cache, stock), lambda previous: fetch(stock, previous)


def refresh_daily(folder, mode, once=False):
    import retrotv_daily

    label, module = DAILY_BULLETINS[mode]
    fetch = import_module(module).fetch
    cache = folder / CACHE_NAME
    accept = None
    if mode == "twin-galaxies":
        context = None  # Use the system trust store for the public Twin Galaxies routes.
        accept = "text/html,application/xml;q=0.9,*/*;q=0.8"
    else:
        context = ssl.create_default_context(cafile=str(CA_PATH))

    def update(previous):
        return fetch(lambda url: read_url(url, context, accept=accept), normalize_title, previous)

    while True:
        delay = retrotv_daily.refresh_if_due(cache, update, save_bulletin, label)
        if once:
            return
        time.sleep(delay)


def play(folder, tty):
    mode = channel_mode(folder)
    if mode == "moon":
        import retrotv_moon

        renderer = BulletinRenderer(read_font(FONT_PATH))
        context = ssl.create_default_context(cafile=str(CA_PATH))
        retrotv_moon.play(folder, tty, ASSET_DIR, renderer, packed_color, read_url, context, normalize_title)
        return
    cache = folder / CACHE_NAME
    daily = mode in DAILY_BULLETINS
    if daily:
        import retrotv_daily

        bulletin = retrotv_daily.bulletin(cache)
    else:
        mode, bulletin, update = channel_bulletin(folder)
    stock = mode == STOCK_MARKER
    panel = mode if mode in PANEL_HEADER else ""
    if stock:
        print("Stock news channel active.", flush=True)
    renderer = BulletinRenderer(read_font(FONT_PATH))
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    with contextlib.ExitStack() as stack:
        stack.callback(os.close, fd)
        memory = stack.enter_context(mmap.mmap(fd, PAGE_BYTES * 6, offset=DDR_BASE))
        # The tune command clears the previous art before bank zero is reused.
        time.sleep(.05)
        offline = daily and bool((bulletin or {}).get("offline"))
        bank = publish(memory, tty, renderer, bulletin, 0, stock, offline=offline, panel=panel)
        if daily:
            # The boot worker owns network refreshes. The display only reads its cache.
            while True:
                time.sleep(10)
                current = retrotv_daily.bulletin(cache)
                if current != bulletin:
                    bulletin = current
                    bank = publish(memory, tty, renderer, bulletin, bank, panel=panel,
                                   offline=bool((bulletin or {}).get("offline")))
        interval = refresh_seconds(folder, stock, panel)
        delay = 0
        if bulletin and not bulletin["legacy"]:
            delay = min(interval, max(0, interval - (time.time() - bulletin["updated"])))
        offline = False
        while True:
            time.sleep(delay)
            previous = bulletin
            try:
                bulletin = update(previous)
            except (OSError, ValueError, ET.ParseError) as error:
                print("News feed unavailable: {}".format(error),flush=True)
                if not offline:
                    bank = publish(memory, tty, renderer, bulletin, bank, stock, offline=True, panel=panel)
                    offline = True
                delay = RETRY_SECONDS
                continue
            if panel != "guide" and (panel != "space" or (previous or {}).get("state") != bulletin["state"]):
                try:
                    save_bulletin(cache, bulletin)
                except OSError as error:
                    print("Could not save last bulletin: {}".format(error), flush=True)
            bank = publish(memory, tty, renderer, bulletin, bank, stock, panel=panel)
            offline = False
            delay = refresh_seconds(folder, stock, panel)


def stop_worker(_signum, _frame):
    raise SystemExit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder",type=Path)
    parser.add_argument("--tty",type=Path,default=Path("/dev/ttyS1"))
    command = parser.add_mutually_exclusive_group()
    command.add_argument("--refresh-cache", action="store_true",
                         help="refresh the cache without using the display")
    command.add_argument("--daily-bulletin", "--daily-watch", action="store_true",
                         help="run the channel's daily cache updater")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM,stop_worker)
    try:
        mode = channel_mode(args.folder)
        if args.daily_bulletin or (args.refresh_cache and mode in DAILY_BULLETINS):
            if mode not in DAILY_BULLETINS:
                raise ValueError("expected a daily bulletin channel folder")
            refresh_daily(args.folder, mode, once=args.refresh_cache)
        elif args.refresh_cache:
            mode, previous, update = channel_bulletin(args.folder)
            bulletin = update(previous)
            if mode != "guide":
                save_bulletin(args.folder / CACHE_NAME, bulletin)
            if mode == "guide":
                print("Read {} program listings.".format(len(bulletin["sections"])), flush=True)
            elif mode == "space":
                print("Saved Space Desk bulletin.", flush=True)
            elif mode == "weather":
                print("Saved weather for {}.".format(bulletin["title"]), flush=True)
            else:
                print("Saved {} headlines.".format(len(bulletin["titles"])), flush=True)
        else:
            play(args.folder,args.tty)
    except (OSError,ValueError,ET.ParseError) as error:
        parser.exit(1,"{}\n".format(error))


if __name__ == "__main__":
    main()
