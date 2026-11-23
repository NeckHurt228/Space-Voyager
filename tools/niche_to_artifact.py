#!/usr/bin/env python3
"""
niche_to_artifact.py - turn a niche_finder result (reports/niches/niches_<stamp>.json) into the
document the in-chat Niche Finder page reads (collection "searches", one document per search).

    python3 tools/niche_to_artifact.py reports/niches/niches_2026-11-23_193700.json > /tmp/doc.json
    python3 tools/niche_to_artifact.py <json> --example     # mark it as example data (shows a banner)

Claude then writes it with ArtifactData: action "set", collection "searches", doc_id = the stamp,
file_path = the output file. Keeps each document well under the 256 KiB limit.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def trim(data: dict, example: bool) -> dict:
    meta = data["meta"]
    chans = []
    for c in data["channels"][:40]:
        chans.append({
            "id": c["id"], "title": c["title"], "handle": c.get("handle", ""),
            "age_days": round(c["age_days"], 1), "subs": c.get("subs"), "views_7d": c["views_7d"],
            "method": "snapshot" if str(c.get("views_7d_method", "")).startswith("snapshot") else c.get("views_7d_method", "uploads"),
            "uploads_7d": c.get("uploads_7d", 0), "faceless": c.get("faceless", "unknown"),
            "category": c.get("category", ""), "keywords": (c.get("keywords") or [])[:8],
            "videos": [{"id": v["id"], "title": v["title"][:120], "views": v["views"], "url": v["url"]}
                       for v in (c.get("top_videos") or [])[:4]],
        })
    near = [{"id": c["id"], "title": c["title"], "handle": c.get("handle", ""), "views_7d": c["views_7d"],
             "age_days": round(c["age_days"], 1), "keywords": (c.get("keywords") or [])[:4]}
            for c in data.get("near_misses", [])[:15]]
    niches = [{"niche": n["niche"], "related": n.get("related", [])[:4], "channels": n["channels"],
               "views_7d": n["views_7d"], "faceless_channels": n.get("faceless_channels", 0),
               "faceless_checked": n.get("faceless_checked", 0),
               "channel_titles": n.get("channel_titles", [])[:6], "channel_ids": n.get("channel_ids", [])[:20]}
              for n in data.get("niches", [])[:20]]
    return {"generated": meta["generated"], "example": example or bool(meta.get("demo")),
            "days": meta["days"], "min_views": meta["min_views"], "max_channel_age": meta["max_channel_age_days"],
            "regions": meta.get("regions", []), "quota_used": meta.get("quota_used", 0),
            "videos_scanned": meta.get("videos_scanned", 0), "channels_scanned": meta.get("channels_scanned", 0),
            "young_channels": meta.get("young_channels", 0),
            "niches": niches, "channels": chans, "near_misses": near}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result_json")
    ap.add_argument("--example", action="store_true")
    a = ap.parse_args()
    doc = trim(json.loads(Path(a.result_json).read_text()), a.example)
    out = json.dumps(doc, separators=(",", ":"))
    if len(out.encode()) > 250_000:
        sys.exit("document too large for the page's database")
    print(out)


if __name__ == "__main__":
    main()
