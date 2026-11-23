#!/usr/bin/env python3
"""Offline test for niche_finder.py: runs the whole pipeline against a fake YouTube API.

    python3 tools/test_niche_finder.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import niche_finder as nf  # noqa: E402

NOW = nf.now_utc()


def ago(days):
    return nf.iso(NOW - timedelta(days=days))


# channel id -> (title, created days ago, total views, [(video id, published days ago, views, seconds, vertical, title)])
CHANNELS = {
    # new faceless AI channel, 20 days old, 14M from this week's uploads -> QUALIFIES (uploads method)
    "UC_new_hit": ("AI Cat Stories", 20, 30_000_000, [
        ("v1", 2, 8_000_000, 35, True, "AI cat saves baby kitten #aicat #aistory"),
        ("v2", 5, 6_000_000, 41, True, "AI cat goes to work #aicat"),
        ("v3", 12, 9_000_000, 30, True, "AI cat vs dog #aicat #aistory"),
        ("v4", 3, 900_000, 600, False, "AI cat compilation (long video)"),  # long-form: still counts for views
    ]),
    # 5 days old: every view is in the window -> QUALIFIES (exact)
    "UC_baby": ("Fruit Drama Daily", 5, 11_000_000, [
        ("v5", 1, 7_000_000, 50, True, "fruit drama episode 3 #fruitdrama #aistory"),
        ("v6", 4, 2_000_000, 48, True, "fruit drama episode 2 #fruitdrama"),
    ]),
    # new but only 3M this week -> near miss
    "UC_small": ("Riddle Room", 15, 5_000_000, [
        ("v7", 3, 3_000_000, 20, True, "riddle only geniuses solve #riddle"),
    ]),
    # huge but old channel -> filtered out by age
    "UC_old": ("Old Giant", 900, 9_000_000_000, [
        ("v8", 1, 50_000_000, 25, True, "satisfying soap cutting"),
    ]),
}


class FakeAPI(nf.YouTubeAPI):
    def __init__(self):
        super().__init__("fake", budget=10_000)
        self.calls = []

    def _video(self, vid):
        for cid, (_, _, _, vids) in CHANNELS.items():
            for v in vids:
                if v[0] == vid:
                    _, d, views, secs, vert, title = v
                    m, s = divmod(secs, 60)
                    return {"id": vid,
                            "snippet": {"channelId": cid, "title": title, "publishedAt": ago(d),
                                        "description": title, "categoryId": "24", "tags": [],
                                        "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}}},
                            "statistics": {"viewCount": str(views), "likeCount": "10"},
                            "contentDetails": {"duration": f"PT{m}M{s}S"},
                            "player": {"embedWidth": "360" if vert else "640", "embedHeight": "640" if vert else "360"}}
        return None

    def get(self, endpoint, **p):
        self.used += nf.COST[endpoint]
        self.calls.append(endpoint)
        if endpoint == "videos" and p.get("chart"):
            return {"items": [{"id": "v8"}]}
        if endpoint == "search":
            assert p["publishedAfter"] <= ago(6.9) and p["videoDuration"] == "short"
            ids = ["v1", "v5", "v7", "v8"] if p.get("q") is None else []
            return {"items": [{"id": {"videoId": i}} for i in ids]}
        if endpoint == "videos":
            return {"items": [x for x in (self._video(i) for i in p["id"].split(",")) if x]}
        if endpoint == "channels":
            out = []
            for cid in p["id"].split(","):
                title, age, total, _ = CHANNELS[cid]
                out.append({"id": cid, "snippet": {"title": title, "publishedAt": ago(age), "customUrl": "@" + cid},
                            "statistics": {"viewCount": str(total), "subscriberCount": "1000", "videoCount": "4"},
                            "contentDetails": {"relatedPlaylists": {"uploads": "UU" + cid}}})
            return {"items": out}
        if endpoint == "playlistItems":
            cid = p["playlistId"][2:]
            return {"items": [{"contentDetails": {"videoId": v[0], "videoPublishedAt": ago(v[1])}}
                              for v in sorted(CHANNELS[cid][3], key=lambda v: v[1])]}
        if endpoint == "videoCategories":
            return {"items": [{"id": "24", "snippet": {"title": "Entertainment"}}]}
        raise AssertionError(endpoint)


def main():
    assert nf.parse_duration("PT1M5S") == 65 and nf.parse_duration("PT45S") == 45
    assert nf.parse_duration("P0D") == 0 and nf.parse_duration("PT1H") == 3600
    with tempfile.TemporaryDirectory() as tmp:
        seeds = Path(tmp, "seeds.txt")
        seeds.write_text("// comment\n(blank)\nai cat\n")
        assert nf.load_seeds(seeds) == ["", "ai cat"]
        args = nf.build_parser().parse_args(["--seeds", str(seeds), "--out", tmp, "--faceless", "off", "--quiet"])
        api = FakeAPI()
        assert nf.pipeline(api, args) == 0
        data = json.loads(next(Path(tmp).glob("niches_*.json")).read_text())
        got = {c["id"]: c for c in data["channels"]}
        assert set(got) == {"UC_new_hit", "UC_baby"}, got.keys()
        assert got["UC_new_hit"]["views_7d"] == 14_900_000 and got["UC_new_hit"]["views_7d_method"] == "uploads"
        assert got["UC_baby"]["views_7d"] == 11_000_000 and got["UC_baby"]["views_7d_method"] == "exact"
        assert "aicat" in got["UC_new_hit"]["keywords"]
        assert [c["id"] for c in data["near_misses"]] == ["UC_small"]
        assert data["meta"]["channels_scanned"] == 4 and data["meta"]["young_channels"] == 3
        assert any(n["niche"] == "aistory" and n["channels"] == 2 for n in data["niches"]), data["niches"]

        # second run: the stored snapshot is backdated 7 days, so the snapshot method takes over
        store = nf.Store(Path(tmp, "niche_finder.db"))
        store.db.execute("UPDATE snapshots SET ts=?, total_views=total_views-20000000 WHERE channel_id='UC_new_hit'",
                         (ago(7),))
        store.commit()
        args2 = nf.build_parser().parse_args(["--seeds", str(seeds), "--out", tmp, "--faceless", "off",
                                              "--quiet", "--recheck-only"])
        for f in Path(tmp).glob("niches_*"):
            f.unlink()
        assert nf.pipeline(FakeAPI(), args2) == 0
        data = json.loads(next(Path(tmp).glob("niches_*.json")).read_text())
        hit = {c["id"]: c for c in data["channels"]}["UC_new_hit"]
        assert abs(hit["views_7d"] - 20_000_000) < 1000 and hit["views_7d_method"].startswith("snapshot"), hit
    print("all niche_finder tests passed")


if __name__ == "__main__":
    main()
