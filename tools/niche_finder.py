#!/usr/bin/env python3
"""
niche_finder.py - find YouTube Shorts niches that are proven RIGHT NOW by brand-new channels.

A niche counts as proven when a channel that is at most N days old (default 30) pulls
10M+ views in the last 7 days from Shorts. One new channel doing that is a signal.
Several new channels doing it in the same niche is a proven niche.

Pipeline
  1. Discover: search Shorts published in the last 7 days, sorted by views, across a list
     of seed queries (tools/niche_seeds.txt) and regions, plus the cheap "most popular" chart.
     Channels found on earlier runs that are still young are re-checked for free (watchlist).
  2. Filter by channel age: keep channels created on or after (today - --max-channel-age days).
  3. Measure each young channel's last-7-day views (see "How 7-day views are measured" below)
     and keep those at or above --min-views (default 10,000,000).
  4. Faceless check: run face detection on the thumbnails of the channel's top Shorts
     (needs: pip install "opencv-python-headless<5"; skipped with a warning when it's missing).
  5. Group the survivors into niches by shared keywords (titles, tags, hashtags) and write
     a CSV, a JSON file and an HTML report with thumbnails.

How 7-day views are measured
  The YouTube API has no "views in the last 7 days" number for other people's channels, so the
  tool uses the best figure it has, and says which one it used:
    exact      the channel is 7 days old or younger, so ALL its views are from the last 7 days.
    snapshot   an earlier run stored the channel's total views 6+ days ago; the difference
               is scaled to 7 days. Run the tool daily and this becomes the main method.
    uploads    sum of views on videos the channel published in the last 7 days. This is a
               LOWER BOUND (older videos keep getting views too), so a channel can only be
               under-counted, never over-counted.

Quota
  The free YouTube Data API quota is 10,000 units a day. A search costs 100 units, every
  other call costs 1. The default run spends about 3,000-5,000 units. --quota-budget caps it.

Usage
  export YOUTUBE_API_KEY=...            # Google Cloud console > YouTube Data API v3 > API key
  python3 tools/niche_finder.py
  python3 tools/niche_finder.py --min-views 5000000 --max-channel-age 45 --regions US,GB,IN
  python3 tools/niche_finder.py --seeds my_seeds.txt --pages 2 --faceless-only
  python3 tools/niche_finder.py --recheck-only      # just re-measure the watchlist (cheap)

Outputs (default --out reports/niches)
  niches_<date>.html   report: niche summary + one card per channel with its top Shorts
  niches_<date>.csv    one row per qualifying channel
  niches_<date>.json   everything, including near-misses
  niche_finder.db      SQLite: channel snapshots + watchlist, used by later runs
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_ROOT = "https://www.googleapis.com/youtube/v3/"
HERE = Path(__file__).resolve().parent
DEFAULT_SEEDS = HERE / "niche_seeds.txt"

COST = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1, "videoCategories": 1}

# A Short can be up to 3 minutes long (since Oct 2024).
SHORTS_MAX_SECONDS = 180


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_DUR = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$")


def parse_duration(s: str) -> float | None:
    """ISO-8601 duration (PT1M5S) -> seconds. None for live/upcoming or unparseable."""
    if not s:
        return None
    m = _DUR.match(s)
    if not m:
        return None
    d, h, mi, se = m.groups()
    return int(d or 0) * 86400 + int(h or 0) * 3600 + int(mi or 0) * 60 + float(se or 0)


def fmt_num(n: float | int | None) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.1f}{unit}"
    return f"{int(n)}"


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# --------------------------------------------------------------------------
# API client
# --------------------------------------------------------------------------
class QuotaExhausted(Exception):
    pass


class NotFound(Exception):
    pass


class YouTubeAPI:
    def __init__(self, api_key: str, budget: int, verbose: bool = False):
        self.api_key = api_key
        self.budget = budget
        self.used = 0
        self.verbose = verbose

    def can_afford(self, endpoint: str) -> bool:
        return self.used + COST[endpoint] <= self.budget

    def get(self, endpoint: str, **params) -> dict:
        cost = COST[endpoint]
        if self.used + cost > self.budget:
            raise QuotaExhausted(f"quota budget {self.budget} reached")
        params = {k: v for k, v in params.items() if v not in (None, "")}
        url = API_ROOT + endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"X-Goog-Api-Key": self.api_key,
                                                   "Accept": "application/json"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode())
                self.used += cost
                if self.verbose:
                    print(f"  [api] {endpoint} ok (+{cost}, total {self.used})", file=sys.stderr)
                return data
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                reason = ""
                try:
                    reason = json.loads(body)["error"]["errors"][0].get("reason", "")
                except Exception:
                    pass
                if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded") and e.code == 403:
                    self.used += cost
                    raise QuotaExhausted("YouTube says the daily quota is used up "
                                         "(it resets at midnight Pacific time)")
                if e.code == 404:
                    self.used += cost
                    raise NotFound(f"{endpoint}: {reason or 'not found'}")
                if e.code in (500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                if e.code in (400, 401, 403):
                    raise SystemExit(f"YouTube API refused the request ({e.code} {reason or ''}). "
                                     f"Check YOUTUBE_API_KEY and that 'YouTube Data API v3' is enabled "
                                     f"for its Google Cloud project.\n{body[:400]}")
                raise
            except urllib.error.URLError:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise
        raise RuntimeError("unreachable")


# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------
@dataclass
class Video:
    id: str
    channel_id: str
    title: str
    published: str
    views: int
    likes: int | None
    comments: int | None
    seconds: float | None
    vertical: bool | None
    tags: list[str]
    description: str
    category_id: str
    thumb: str

    @property
    def is_short(self) -> bool:
        return self.seconds is not None and 0 < self.seconds <= SHORTS_MAX_SECONDS and self.vertical is not False

    @property
    def url(self) -> str:
        return (f"https://www.youtube.com/shorts/{self.id}" if self.is_short
                else f"https://www.youtube.com/watch?v={self.id}")


@dataclass
class Channel:
    id: str
    title: str
    handle: str
    created: str
    country: str
    subs: int | None
    total_views: int
    video_count: int
    uploads_playlist: str
    avatar: str
    topics: list[str] = field(default_factory=list)
    # filled in later
    age_days: float = 0.0
    views_7d: int = 0
    views_7d_method: str = ""
    uploads_7d: int = 0
    shorts_7d: int = 0
    shorts_share: float = 0.0
    views_per_day: float = 0.0
    top_videos: list[dict] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    category: str = ""
    face_rate: float | None = None
    faceless: str = "unknown"  # yes / no / unknown
    qualifies: bool = False
    note: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/{self.handle}" if self.handle else f"https://www.youtube.com/channel/{self.id}"


def video_from_api(item: dict) -> Video:
    sn, st, cd = item.get("snippet", {}), item.get("statistics", {}), item.get("contentDetails", {})
    pl = item.get("player", {})
    vertical = None
    try:
        w, h = int(pl.get("embedWidth", 0)), int(pl.get("embedHeight", 0))
        if w and h:
            vertical = h >= w
    except (TypeError, ValueError):
        pass
    th = sn.get("thumbnails", {})
    thumb = (th.get("high") or th.get("medium") or th.get("default") or {}).get("url", "")
    return Video(
        id=item["id"], channel_id=sn.get("channelId", ""), title=sn.get("title", ""),
        published=sn.get("publishedAt", ""), views=int(st.get("viewCount", 0) or 0),
        likes=int(st["likeCount"]) if "likeCount" in st else None,
        comments=int(st["commentCount"]) if "commentCount" in st else None,
        seconds=parse_duration(cd.get("duration", "")), vertical=vertical,
        tags=sn.get("tags", []) or [], description=sn.get("description", "") or "",
        category_id=sn.get("categoryId", ""), thumb=thumb)


def channel_from_api(item: dict) -> Channel:
    sn, st, cd = item.get("snippet", {}), item.get("statistics", {}), item.get("contentDetails", {})
    th = sn.get("thumbnails", {})
    topics = [u.rsplit("/", 1)[-1].replace("_", " ")
              for u in item.get("topicDetails", {}).get("topicCategories", []) or []]
    return Channel(
        id=item["id"], title=sn.get("title", ""), handle=sn.get("customUrl", "") or "",
        created=sn.get("publishedAt", ""), country=sn.get("country", "") or "",
        subs=None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0) or 0),
        total_views=int(st.get("viewCount", 0) or 0), video_count=int(st.get("videoCount", 0) or 0),
        uploads_playlist=cd.get("relatedPlaylists", {}).get("uploads", ""),
        avatar=(th.get("medium") or th.get("default") or {}).get("url", ""), topics=topics)


# --------------------------------------------------------------------------
# storage (snapshots + watchlist)
# --------------------------------------------------------------------------
class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                channel_id TEXT, ts TEXT, total_views INTEGER, subs INTEGER, videos INTEGER,
                PRIMARY KEY (channel_id, ts));
            CREATE TABLE IF NOT EXISTS watchlist (
                channel_id TEXT PRIMARY KEY, title TEXT, created TEXT, first_seen TEXT,
                last_views_7d INTEGER, last_checked TEXT);
        """)

    def add_snapshot(self, ch: Channel, ts: datetime):
        self.db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?)",
                        (ch.id, iso(ts), ch.total_views, ch.subs, ch.video_count))

    def snapshot_delta_7d(self, ch: Channel, ts: datetime) -> tuple[int, float] | None:
        """Views gained since the stored snapshot closest to 7 days ago (at least 6 days old),
        scaled to 7 days. Returns (views_7d, days_spanned)."""
        rows = self.db.execute("SELECT ts, total_views FROM snapshots WHERE channel_id=? AND ts<=?",
                               (ch.id, iso(ts - timedelta(days=6)))).fetchall()
        if not rows:
            return None
        target = ts - timedelta(days=7)
        best = min(rows, key=lambda r: abs((parse_ts(r[0]) - target).total_seconds()))
        days = (ts - parse_ts(best[0])).total_seconds() / 86400
        gained = max(0, ch.total_views - int(best[1]))
        return int(gained * 7 / days), days

    def watch(self, ch: Channel, ts: datetime):
        self.db.execute("""INSERT INTO watchlist VALUES (?,?,?,?,?,?)
                           ON CONFLICT(channel_id) DO UPDATE SET title=excluded.title,
                           last_views_7d=excluded.last_views_7d, last_checked=excluded.last_checked""",
                        (ch.id, ch.title, ch.created, iso(ts), ch.views_7d, iso(ts)))

    def watchlist(self, created_after: datetime, min_views: int) -> list[str]:
        rows = self.db.execute("SELECT channel_id FROM watchlist WHERE created>=? AND last_views_7d>=?",
                               (iso(created_after), min_views)).fetchall()
        return [r[0] for r in rows]

    def commit(self):
        self.db.commit()


# --------------------------------------------------------------------------
# niche keywords
# --------------------------------------------------------------------------
STOP = set("""
a an the and or but if of to in on at for from by with without into onto over under up down out off
is are was were be been being am do does did done have has had having i me my we our you your he she
it its they them their this that these those what which who whom whose when where why how all any
both each few more most other some such no nor not only own same so than too very can will just
should now get got gets let lets like vs versus new day days part ep episode official full
shorts short ytshorts youtubeshorts youtube yt video videos viral fyp foryou foryoupage trending
trend subscribe sub like comment share follow tiktok reels reel explore explorepage shortsfeed
shortvideo shortsvideo viralvideo viralshorts trendingshorts edit edits pov omg wow wait end
1 2 3 4 5 6 7 8 9 10 de la el en y que los las un una por para con del se es mi
""".split())

TOKEN = re.compile(r"[#@]?[a-z0-9][a-z0-9'_-]{1,30}")


def text_terms(text: str) -> list[str]:
    out = []
    for t in TOKEN.findall(text.lower()):
        t = t.lstrip("#@").strip("'-_")
        if len(t) < 3 or t in STOP or t.isdigit():
            continue
        out.append(t)
    return out


def channel_keywords(videos: list[Video], k: int = 8) -> list[str]:
    """Terms that appear across many of the channel's videos (document frequency),
    weighted a little by views so the hits define the niche."""
    score = Counter()
    for v in videos:
        terms = set(text_terms(v.title))
        terms |= {t for tag in v.tags for t in text_terms(tag)}
        terms |= {t for t in text_terms(" ".join(re.findall(r"#\w+", v.description)))}
        w = 1 + math.log10(max(v.views, 10))
        for t in terms:
            score[t] += w
    return [t for t, _ in score.most_common(k)]


def group_niches(channels: list[Channel]) -> list[dict]:
    """A niche = a keyword shared by qualifying channels. Sorted by number of channels,
    then combined 7-day views. Single-channel niches are kept: one new channel at 10M+/week
    is already a signal."""
    by_term: dict[str, list[Channel]] = defaultdict(list)
    for ch in channels:
        for t in ch.keywords[:6]:
            by_term[t].append(ch)
    niches = []
    for term, chs in by_term.items():
        views = sum(c.views_7d for c in chs)
        co = Counter(t for c in chs for t in c.keywords[:6] if t != term)
        related = [t for t, n in co.most_common(4) if n >= max(1, len(chs) // 2)]
        niches.append({"niche": term, "related": related, "channels": len(chs), "views_7d": views,
                       "faceless_channels": sum(1 for c in chs if c.faceless == "yes"),
                       "faceless_checked": sum(1 for c in chs if c.faceless != "unknown"),
                       "channel_titles": [c.title for c in sorted(chs, key=lambda c: -c.views_7d)],
                       "channel_ids": [c.id for c in sorted(chs, key=lambda c: -c.views_7d)]})
    niches.sort(key=lambda n: (-n["channels"], -n["views_7d"]))
    # drop niches whose channel set is identical to a stronger niche (same channels, weaker term)
    seen, out = set(), []
    for n in niches:
        key = tuple(sorted(n["channel_titles"]))
        if n["channels"] == 1 and key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


# --------------------------------------------------------------------------
# faceless check
# --------------------------------------------------------------------------
class FaceChecker:
    def __init__(self):
        self.ok = False
        self.why = ""
        try:
            import cv2  # noqa
            import numpy  # noqa
            self.cv2 = cv2
            self.np = numpy
            self.front = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            self.profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
            self.ok = not self.front.empty()
            if not self.ok:
                self.why = "OpenCV face model failed to load"
        except ImportError:
            self.why = 'opencv is not installed (pip install "opencv-python-headless<5")'
        except AttributeError:
            # OpenCV 5 moved the Haar face detector out of the main package
            self.why = 'this OpenCV has no Haar face detector (pip install "opencv-python-headless<5")'

        self.fetch_failed = 0

    def has_face(self, url: str) -> bool | None:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "niche-finder"}),
                                        timeout=15) as r:
                buf = r.read()
        except Exception:
            self.fetch_failed += 1
            return None
        img = self.cv2.imdecode(self.np.frombuffer(buf, self.np.uint8), self.cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        # crop letterbox bars that YouTube adds around vertical thumbnails
        cols = self.np.where(img.std(axis=0) > 8)[0]
        if len(cols) > 10:
            img = img[:, cols[0]:cols[-1] + 1]
        img = self.cv2.equalizeHist(img)
        min_side = max(24, int(min(img.shape[:2]) * 0.10))
        for casc in (self.front, self.profile):
            if casc.empty():
                continue
            faces = casc.detectMultiScale(img, scaleFactor=1.1, minNeighbors=7, minSize=(min_side, min_side))
            if len(faces):
                return True
        return False

    def rate(self, thumbs: list[str]) -> float | None:
        results = [r for r in (self.has_face(u) for u in thumbs if u) if r is not None]
        if not results:
            return None
        return sum(results) / len(results)


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------
def load_seeds(path: Path) -> list[str]:
    """One search query per line. Lines starting with '//' are comments, blank lines are skipped,
    and the line '(blank)' means a search with no query (YouTube's overall top Shorts)."""
    if not path.exists():
        raise SystemExit(f"seed file not found: {path}")
    seeds: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        q = "" if line == "(blank)" else line
        if q not in seeds:
            seeds.append(q)
    return seeds


def fetch_videos(api: YouTubeAPI, ids: list[str]) -> list[Video]:
    out = []
    for batch in chunks(ids, 50):
        data = api.get("videos", part="snippet,statistics,contentDetails,player", id=",".join(batch),
                       maxResults=50, maxHeight=1280)
        out += [video_from_api(it) for it in data.get("items", [])]
    return out


def fetch_channels(api: YouTubeAPI, ids: list[str]) -> list[Channel]:
    out = []
    for batch in chunks(ids, 50):
        data = api.get("channels", part="snippet,statistics,contentDetails,topicDetails",
                       id=",".join(batch), maxResults=50)
        out += [channel_from_api(it) for it in data.get("items", [])]
    return out


def discover(api: YouTubeAPI, seeds: list[str], regions: list[str], pages: int,
             published_after: datetime, log) -> tuple[set[str], dict[str, str]]:
    """Returns (video ids, {video id: what found it})."""
    found: dict[str, str] = {}
    # 1) most-popular chart (1 unit per page, mostly long-form, but cheap)
    for rc in regions:
        token = None
        for _ in range(4):
            try:
                data = api.get("videos", part="id", chart="mostPopular", regionCode=rc,
                               maxResults=50, pageToken=token)
            except QuotaExhausted:
                return set(found), found
            for it in data.get("items", []):
                found.setdefault(it["id"], f"chart:{rc}")
            token = data.get("nextPageToken")
            if not token:
                break
    log(f"  most-popular charts: {len(found)} videos")
    # 2) searches (100 units each)
    n_search = 0
    for q in seeds:
        for rc in regions:
            token = None
            for _ in range(pages):
                if not api.can_afford("search"):
                    log(f"  quota budget reached after {n_search} searches; continuing with what was found")
                    return set(found), found
                try:
                    data = api.get("search", part="snippet", type="video", videoDuration="short",
                                   order="viewCount", publishedAfter=iso(published_after),
                                   q=q or None, regionCode=rc, maxResults=50, pageToken=token,
                                   safeSearch="none")
                except QuotaExhausted as e:
                    log(f"  {e}; continuing with what was found")
                    return set(found), found
                n_search += 1
                for it in data.get("items", []):
                    vid = it.get("id", {}).get("videoId")
                    if vid:
                        found.setdefault(vid, f"search:{q or '(blank)'}:{rc}")
                token = data.get("nextPageToken")
                if not token:
                    break
    log(f"  {n_search} searches -> {len(found)} candidate videos")
    return set(found), found


def channel_recent_videos(api: YouTubeAPI, ch: Channel, since: datetime, max_pages: int) -> list[Video]:
    """The channel's uploads published since `since` (newest first), with stats."""
    ids, token = [], None
    for _ in range(max_pages):
        data = api.get("playlistItems", part="contentDetails", playlistId=ch.uploads_playlist,
                       maxResults=50, pageToken=token)
        items = data.get("items", [])
        page_ids = [it["contentDetails"]["videoId"] for it in items]
        dates = [it["contentDetails"].get("videoPublishedAt", "") for it in items]
        ids += page_ids
        token = data.get("nextPageToken")
        if not token or (dates and dates[-1] and parse_ts(dates[-1]) < since):
            break
    vids = fetch_videos(api, ids)
    return [v for v in vids if v.published and parse_ts(v.published) >= since]


def measure_channel(api: YouTubeAPI, store: Store, ch: Channel, ts: datetime, days: int,
                    max_pages: int, categories: dict[str, str]):
    created = parse_ts(ch.created)
    ch.age_days = (ts - created).total_seconds() / 86400
    window_start = ts - timedelta(days=days)
    # pull everything since the channel was created (young channels only, so this is small;
    # --max-pages caps it for channels that upload hundreds of Shorts)
    try:
        recent = channel_recent_videos(api, ch, created, max_pages) if ch.uploads_playlist else []
    except NotFound:
        recent = []
        ch.note = "uploads playlist not readable"
    in_window = [v for v in recent if parse_ts(v.published) >= window_start]
    ch.uploads_7d = len(in_window)
    ch.shorts_7d = sum(1 for v in in_window if v.is_short)
    ch.shorts_share = (sum(1 for v in recent if v.is_short) / len(recent)) if recent else 0.0

    uploads_views = sum(v.views for v in in_window)
    candidates = [("uploads", uploads_views)]
    if ch.age_days <= days:
        candidates.append(("exact", ch.total_views))
    snap = store.snapshot_delta_7d(ch, ts)
    if snap:
        candidates.append((f"snapshot({snap[1]:.1f}d)", snap[0]))
    method, views = max(candidates, key=lambda c: c[1])
    ch.views_7d, ch.views_7d_method = int(views), method
    ch.views_per_day = ch.total_views / max(ch.age_days, 1)

    top = sorted(recent, key=lambda v: -v.views)[:6]
    ch.top_videos = [{"id": v.id, "title": v.title, "views": v.views, "published": v.published,
                      "seconds": v.seconds, "url": v.url, "thumb": v.thumb, "short": v.is_short}
                     for v in top]
    ch.keywords = channel_keywords(recent or top)
    cats = Counter(v.category_id for v in recent if v.category_id)
    if cats:
        ch.category = categories.get(cats.most_common(1)[0][0], cats.most_common(1)[0][0])
    return recent


def load_categories(api: YouTubeAPI) -> dict[str, str]:
    try:
        data = api.get("videoCategories", part="snippet", regionCode="US")
        return {it["id"]: it["snippet"]["title"] for it in data.get("items", [])}
    except QuotaExhausted:
        return {}


def run(args) -> int:
    key = args.api_key or os.environ.get("YOUTUBE_API_KEY", "")
    if not key:
        print("No API key. Set YOUTUBE_API_KEY (or pass --api-key).\n"
              "Get one free: console.cloud.google.com > create project > enable 'YouTube Data API v3' > "
              "Credentials > Create credentials > API key.", file=sys.stderr)
        return 2
    api = YouTubeAPI(key, args.quota_budget, args.verbose)
    pipeline(api, args)
    return 0


def pipeline(api: YouTubeAPI, args, log=None, on_stage=None) -> dict:
    """Runs the whole search. `log(text)` receives progress lines and `on_stage(n, label)` is
    called at each of the 5 stages (both optional; the desktop app uses them).
    Returns {"stamp", "json", "html", "csv", "meta"}."""
    if log is None:
        log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))
    stage = on_stage or (lambda n, label: None)
    ts = now_utc()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    store = Store(out / "niche_finder.db")
    published_after = ts - timedelta(days=args.days)
    created_after = ts - timedelta(days=args.max_channel_age)
    regions = [r.strip().upper() for r in args.regions.split(",") if r.strip()]
    seeds = getattr(args, "seed_list", None) or load_seeds(Path(args.seeds))

    log(f"Window: Shorts published since {published_after:%Y-%m-%d %H:%M} UTC; "
        f"channels created since {created_after:%Y-%m-%d}; threshold {fmt_num(args.min_views)} views/7d")

    # ---- 1. discovery
    video_ids: set[str] = set()
    found_by: dict[str, str] = {}
    stage(1, "Searching this week's top Shorts")
    if not args.recheck_only:
        log(f"Discovering ({len(seeds)} seed queries x {len(regions)} region(s) x {args.pages} page(s), "
            f"budget {api.budget} units)...")
        video_ids, found_by = discover(api, seeds, regions, args.pages, published_after, log)

    candidate_channels: dict[str, int] = defaultdict(int)  # channel -> views of discovered Shorts
    try:
        vids = fetch_videos(api, sorted(video_ids))
    except QuotaExhausted as e:
        log(f"  {e}")
        vids = []
    for v in vids:
        if v.is_short and v.published and parse_ts(v.published) >= published_after:
            candidate_channels[v.channel_id] += v.views
    for cid in store.watchlist(created_after, int(args.min_views * 0.3)):
        candidate_channels.setdefault(cid, 0)
    log(f"  {sum(1 for v in vids if v.is_short)} recent Shorts from {len(candidate_channels)} channels "
        f"(incl. watchlist)")

    # ---- 2. channel age filter
    stage(2, "Checking channel ages")
    try:
        channels = fetch_channels(api, list(candidate_channels))
    except QuotaExhausted as e:
        log(f"  {e}")
        channels = []
    for ch in channels:
        store.add_snapshot(ch, ts)
    young = [c for c in channels if c.created and parse_ts(c.created) >= created_after]
    log(f"  {len(young)} of {len(channels)} channels were created in the last {args.max_channel_age} days")

    # cheap pre-filter: a channel with fewer total views than the threshold can't qualify
    young = [c for c in young if c.total_views >= args.min_views * args.prefilter]
    young.sort(key=lambda c: -c.total_views)
    log(f"  {len(young)} young channels have enough total views to possibly qualify; measuring...")

    # ---- 3. measure 7-day views
    stage(3, "Measuring views")
    categories = load_categories(api)
    measured: list[Channel] = []
    for ch in young:
        try:
            measure_channel(api, store, ch, ts, args.days, args.max_pages, categories)
        except QuotaExhausted as e:
            log(f"  {e}; stopping measurement")
            ch.note = "not measured (quota)"
            break
        ch.qualifies = ch.views_7d >= args.min_views
        if args.video_min_views:
            ch.qualifies = ch.qualifies and any(v["views"] >= args.video_min_views for v in ch.top_videos)
        measured.append(ch)
        store.watch(ch, ts)
        log(f"  measured {ch.title}: {fmt_num(ch.views_7d)} views in {args.days}d"
            + ("  -> QUALIFIES" if ch.qualifies else ""))
    store.commit()

    # ---- 4. faceless check on qualifiers
    stage(4, "Checking for faces")
    hits = [c for c in measured if c.qualifies]
    fc = FaceChecker() if args.faceless != "off" else None
    if fc and not fc.ok:
        log(f"  faceless check skipped: {fc.why}")
    elif fc:
        for ch in hits:
            ch.face_rate = fc.rate([v["thumb"] for v in ch.top_videos])
            if ch.face_rate is None:
                ch.faceless = "unknown"
            else:
                ch.faceless = "yes" if ch.face_rate <= args.face_threshold else "no"
        if fc.fetch_failed:
            log(f"  faceless check: {fc.fetch_failed} thumbnails could not be downloaded (i.ytimg.com blocked?)")
    if args.faceless_only:
        hits = [c for c in hits if c.faceless == "yes"]

    hits.sort(key=lambda c: -c.views_7d)
    near = sorted([c for c in measured if not c.qualifies], key=lambda c: -c.views_7d)[:25]
    niches = group_niches(hits)

    # ---- 5. outputs
    stage(5, "Grouping niches")
    stamp = ts.strftime("%Y-%m-%d_%H%M%S")
    meta = {"generated": iso(ts), "days": args.days, "min_views": args.min_views,
            "max_channel_age_days": args.max_channel_age, "regions": regions, "seed_queries": len(seeds),
            "quota_used": api.used, "videos_scanned": len(vids), "channels_scanned": len(channels),
            "young_channels": len([c for c in channels if c.created and parse_ts(c.created) >= created_after])}
    write_csv(out / f"niches_{stamp}.csv", hits)
    (out / f"niches_{stamp}.json").write_text(json.dumps(
        {"meta": meta, "niches": niches, "channels": [asdict(c) for c in hits],
         "near_misses": [asdict(c) for c in near]}, indent=2))
    write_html(out / f"niches_{stamp}.html", meta, niches, hits, near)

    if not args.quiet:
        print_summary(meta, niches, hits, near)
        print(f"\nReport: {out / f'niches_{stamp}.html'}\nCSV:    {out / f'niches_{stamp}.csv'}")
    return {"stamp": stamp, "json": str(out / f"niches_{stamp}.json"), "html": str(out / f"niches_{stamp}.html"),
            "csv": str(out / f"niches_{stamp}.csv"), "meta": meta}


# --------------------------------------------------------------------------
# outputs
# --------------------------------------------------------------------------
def write_csv(path: Path, hits: list[Channel]):
    cols = ["title", "url", "age_days", "created", "views_7d", "views_7d_method", "total_views", "subs",
            "uploads_7d", "shorts_7d", "shorts_share", "faceless", "face_rate", "category", "keywords",
            "top_video_title", "top_video_views", "top_video_url"]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in hits:
            tv = c.top_videos[0] if c.top_videos else {}
            w.writerow([c.title, c.url, f"{c.age_days:.1f}", c.created[:10], c.views_7d, c.views_7d_method,
                        c.total_views, c.subs if c.subs is not None else "hidden", c.uploads_7d, c.shorts_7d,
                        f"{c.shorts_share:.2f}", c.faceless,
                        "" if c.face_rate is None else f"{c.face_rate:.2f}", c.category, " ".join(c.keywords),
                        tv.get("title", ""), tv.get("views", ""), tv.get("url", "")])


def print_summary(meta, niches, hits, near):
    print(f"\n=== {len(hits)} new channel(s) at {fmt_num(meta['min_views'])}+ views in {meta['days']} days "
          f"(created in last {meta['max_channel_age_days']} days) ===")
    print(f"scanned {meta['videos_scanned']} videos, {meta['channels_scanned']} channels, "
          f"{meta['young_channels']} young; quota used {meta['quota_used']}")
    if niches:
        print("\nNICHES (keyword shared by qualifying channels)")
        for n in niches[:15]:
            rel = f" (+{', '.join(n['related'])})" if n["related"] else ""
            face = (f"faceless {n['faceless_channels']}/{n['faceless_checked']}" if n["faceless_checked"]
                    else "faceless unchecked")
            print(f"  {n['niche']:<18}{rel:<34} {n['channels']} ch  {fmt_num(n['views_7d']):>7} views/7d  {face}")
    if hits:
        print("\nCHANNELS")
        for c in hits:
            print(f"  {c.title[:32]:<32} {fmt_num(c.views_7d):>7}/7d [{c.views_7d_method}]  "
                  f"age {c.age_days:4.0f}d  subs {fmt_num(c.subs):>6}  faceless {c.faceless:<7} "
                  f"{', '.join(c.keywords[:4])}")
            print(f"  {'':<32} {c.url}")
    elif near:
        print("\nNobody cleared the bar. Closest young channels:")
        for c in near[:8]:
            print(f"  {c.title[:32]:<32} {fmt_num(c.views_7d):>7}/7d  age {c.age_days:3.0f}d  "
                  f"{', '.join(c.keywords[:4])}  {c.url}")


def write_html(path: Path, meta, niches, hits, near):
    e = html.escape

    def card(c: Channel) -> str:
        vids = "".join(
            f'<a class="v" href="{e(v["url"])}" target="_blank" rel="noopener">'
            f'<img loading="lazy" src="{e(v["thumb"])}" alt=""><span>{fmt_num(v["views"])}</span>'
            f'<em>{e(v["title"][:70])}</em></a>' for v in c.top_videos[:4])
        face = {"yes": "faceless", "no": "shows faces", "unknown": "faceless: unchecked"}[c.faceless]
        fr = "" if c.face_rate is None else f" ({c.face_rate:.0%} of thumbs have a face)"
        return f"""
<article class="card">
  <header>
    {f'<img class="av" src="{e(c.avatar)}" alt="">' if c.avatar else '<div class="av"></div>'}
    <div><h3><a href="{e(c.url)}" target="_blank" rel="noopener">{e(c.title)}</a></h3>
    <p>{c.age_days:.0f} days old &middot; {fmt_num(c.subs)} subs &middot; {c.uploads_7d} uploads in {meta['days']}d
       &middot; {e(c.category)}</p></div>
    <div class="big">{fmt_num(c.views_7d)}<small>views / {meta['days']}d &middot; {e(c.views_7d_method)}</small></div>
  </header>
  <p class="tags"><b class="f-{c.faceless}">{face}</b>{e(fr)} &middot; {' '.join('<span>' + e(k) + '</span>' for k in c.keywords)}</p>
  <div class="vids">{vids}</div>
</article>"""

    niche_rows = "".join(
        f"<tr><td><b>{e(n['niche'])}</b> <small>{e(', '.join(n['related']))}</small></td>"
        f"<td>{n['channels']}</td><td>{fmt_num(n['views_7d'])}</td><td>{(str(n['faceless_channels']) + '/' + str(n['faceless_checked'])) if n['faceless_checked'] else '?'}</td>"
        f"<td><small>{e(', '.join(n['channel_titles'][:5]))}</small></td></tr>" for n in niches[:40])
    near_rows = "".join(
        f"<tr><td><a href='{e(c.url)}' target='_blank' rel='noopener'>{e(c.title)}</a></td>"
        f"<td>{fmt_num(c.views_7d)}</td><td>{c.age_days:.0f}d</td><td><small>{e(', '.join(c.keywords[:5]))}</small></td></tr>"
        for c in near)
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Shorts Niche Finder</title>
<style>
:root{{--bg:#f6f6f4;--fg:#1b1b1b;--mut:#6b6b6b;--card:#fff;--line:#e3e3df;--acc:#c62828;--ok:#2e7d32}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141414;--fg:#eee;--mut:#9a9a9a;--card:#1e1e1e;--line:#2e2e2e;--acc:#ef5350;--ok:#66bb6a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px 64px}}h1{{margin:0 0 4px;font-size:26px}}
.meta{{color:var(--mut);margin:0 0 24px}}h2{{font-size:18px;margin:32px 0 10px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}}
td,th{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;color:var(--mut)}}small{{color:var(--mut)}}
.wrap{{overflow-x:auto}}a{{color:inherit}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:0 0 14px}}
.card header{{display:flex;gap:12px;align-items:center}}.card header>div:nth-child(2){{flex:1;min-width:0}}
.card h3{{margin:0;font-size:17px}}.card p{{margin:2px 0;color:var(--mut);font-size:13px}}
.av{{width:48px;height:48px;border-radius:50%;object-fit:cover;background:var(--line)}}
.big{{font-size:26px;font-weight:700;color:var(--acc);text-align:right}}.big small{{display:block;font-size:11px;font-weight:400}}
.tags span{{display:inline-block;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:0 6px;margin:2px}}
.f-yes{{color:var(--ok)}}.f-no{{color:var(--acc)}}
.vids{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:10px}}
.v{{text-decoration:none;font-size:12px}}.v img{{width:100%;aspect-ratio:9/12;object-fit:cover;border-radius:6px;background:var(--line)}}
.v span{{display:block;font-weight:700;font-size:13px}}.v em{{font-style:normal;color:var(--mut)}}
@media (max-width:600px){{.card header{{flex-wrap:wrap}}.big{{text-align:left;width:100%}}}}
</style></head><body><main>
<h1>Shorts niches proven by new channels</h1>
<p class="meta">{e(meta['generated'])} &middot; channels created in the last {meta['max_channel_age_days']} days with
{fmt_num(meta['min_views'])}+ views in {meta['days']} days &middot; regions {e(', '.join(meta['regions']))} &middot;
scanned {meta['videos_scanned']} videos / {meta['channels_scanned']} channels &middot; quota used {meta['quota_used']}</p>
<h2>Niches ({len(niches)})</h2>
{'<div class="wrap"><table><tr><th>Niche</th><th>Channels</th><th>Views/7d</th><th>Faceless</th><th>Who</th></tr>' + niche_rows + '</table></div>' if niches else '<p>No channel cleared the bar this run.</p>'}
<h2>Channels ({len(hits)})</h2>
{''.join(card(c) for c in hits)}
<h2>Near misses</h2>
{'<div class="wrap"><table><tr><th>Channel</th><th>Views/7d</th><th>Age</th><th>Keywords</th></tr>' + near_rows + '</table></div>' if near else '<p>None.</p>'}
</main></body></html>"""
    path.write_text(body)


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Find Shorts niches proven by brand-new channels.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--api-key", help="YouTube Data API v3 key (default: $YOUTUBE_API_KEY)")
    p.add_argument("--days", type=int, default=7, help="view window in days (default 7)")
    p.add_argument("--min-views", type=float, default=10_000_000, help="min channel views in the window (default 10M)")
    p.add_argument("--video-min-views", type=float, default=0,
                   help="also require one single Short with at least this many views (default off)")
    p.add_argument("--max-channel-age", type=int, default=30, help="max channel age in days (default 30)")
    p.add_argument("--regions", default="US", help="comma-separated region codes to search (default US)")
    p.add_argument("--seeds", default=str(DEFAULT_SEEDS), help="file with one search query per line")
    p.add_argument("--pages", type=int, default=1, help="result pages per search query (50 videos each)")
    p.add_argument("--max-pages", type=int, default=4, help="max upload pages read per channel (50 each)")
    p.add_argument("--quota-budget", type=int, default=9000, help="max API units this run (free tier: 10,000/day)")
    p.add_argument("--prefilter", type=float, default=0.3,
                   help="only measure young channels whose TOTAL views are at least min-views x this "
                        "(default 0.3, so near misses still show up)")
    p.add_argument("--faceless", choices=["auto", "off"], default="auto", help="run the thumbnail face check")
    p.add_argument("--faceless-only", action="store_true", help="drop channels where faces were detected")
    p.add_argument("--face-threshold", type=float, default=0.25,
                   help="max share of thumbnails with a face to still count as faceless (default 0.25)")
    p.add_argument("--recheck-only", action="store_true", help="skip searching, re-measure the watchlist only")
    p.add_argument("--out", default="reports/niches", help="output folder")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet", action="store_true")
    return p


def main(argv=None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
