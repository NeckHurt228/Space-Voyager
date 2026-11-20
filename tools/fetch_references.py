#!/usr/bin/env python3
"""
fetch_references.py - download a channel's most-viewed Shorts (1080p+) into references/<channel>/ for
tools/study_reference.py. Run it where YouTube is reachable (your own computer: cloud sessions block it).

  pip install -U yt-dlp
  python3 tools/fetch_references.py @AirHardReal @ArmoredPOVs @combatful --top 25
  python3 tools/study_reference.py references/          # then study them all and build STYLE_PROFILE.md

Lists every Short on the channel with its view count, keeps the --top most viewed (plus --latest newest,
so the profile isn't only old hits), and downloads them. Already-downloaded videos are skipped.
The videos are for private study only: references/ is git-ignored except the text results.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("channels", nargs="*", help="handles like @ArmoredPOVs, or channel URLs")
    ap.add_argument("--ids-file", default=None,
                    help="download exactly these video IDs (one per line) into the file's folder, e.g. references/UrgentPOVs/ids.txt")
    ap.add_argument("--top", type=int, default=25, help="most-viewed Shorts per channel (default 25)")
    ap.add_argument("--latest", type=int, default=5, help="also the N newest Shorts (default 5)")
    a = ap.parse_args()
    try:
        import yt_dlp
    except ImportError:
        sys.exit("yt-dlp is missing: pip install -U yt-dlp")

    if a.ids_file:
        ids_path = Path(a.ids_file)
        ids = [l.strip().split("|")[0] for l in ids_path.read_text().splitlines() if l.strip() and not l.startswith("#")]
        out = ids_path.parent
        opts = {"format": "bv*[height>=1080]+ba/bv*+ba/b", "merge_output_format": "mp4",
                "outtmpl": str(out / "%(view_count)s_%(id)s.%(ext)s"), "download_archive": str(out / ".downloaded.txt"),
                "quiet": True, "no_warnings": True, "noprogress": True}
        with yt_dlp.YoutubeDL(opts) as y:
            for vid in ids:
                try:
                    y.download([f"https://www.youtube.com/shorts/{vid}"])
                    print(f"  ok  {vid}")
                except Exception as ex:
                    print(f"  skip {vid}: {str(ex)[:120]}")
        print(f"done: {out}")
    for ch in a.channels:
        handle = ch.rstrip("/").split("/")[-1]
        if not handle.startswith("@") and "youtube.com" not in ch:
            handle = "@" + handle
        url = ch if ch.startswith("http") else f"https://www.youtube.com/{handle}/shorts"
        print(f"listing {url} ...")
        with yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True}) as y:
            info = y.extract_info(url, download=False)
        entries = [e for e in info.get("entries", []) if e and e.get("id")]
        name = (info.get("uploader_id") or info.get("channel") or handle).lstrip("@").replace(" ", "")
        ranked = sorted(entries, key=lambda e: -(e.get("view_count") or 0))
        pick = {e["id"]: e for e in ranked[: a.top]}
        pick.update({e["id"]: e for e in entries[: a.latest]})
        out = ROOT / "references" / name
        out.mkdir(parents=True, exist_ok=True)
        print(f"{name}: {len(entries)} Shorts listed, downloading {len(pick)} to {out}")
        opts = {
            # 1080p+ video (the study measures caption sizes in pixels; low-res copies blur thin text)
            "format": "bv*[height>=1080]+ba/bv*+ba/b",
            "merge_output_format": "mp4",
            "outtmpl": str(out / "%(view_count)s_%(id)s.%(ext)s"),
            "download_archive": str(out / ".downloaded.txt"),
            "quiet": True, "no_warnings": True, "noprogress": True,
        }
        with yt_dlp.YoutubeDL(opts) as y:
            for vid, e in pick.items():
                try:
                    y.download([f"https://www.youtube.com/shorts/{vid}"])
                    print(f"  ok  {e.get('view_count') or 0:>12,}  {e.get('title', '')[:60]}")
                except Exception as ex:  # one blocked / age-gated video shouldn't stop the batch
                    print(f"  skip {vid}: {str(ex)[:120]}")
        # titles + view counts, so the study can line results up with performance
        with open(out / "index.tsv", "w", encoding="utf-8") as f:
            f.write("id\tviews\ttitle\n")
            for e in ranked:
                f.write(f"{e['id']}\t{e.get('view_count') or ''}\t{(e.get('title') or '').replace(chr(9), ' ')}\n")


if __name__ == "__main__":
    main()
