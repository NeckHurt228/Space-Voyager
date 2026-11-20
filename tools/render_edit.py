#!/usr/bin/env python3
"""
render_edit.py - render a finished Short in the competitor house style from an edit plan.

  python3 tools/render_edit.py reports/<clip>/edit_plan.json

What it does (all driven by the plan):
  * cuts the source into segments and joins them (jump cuts)
  * bleeps words (1 kHz) at given source times
  * fits any aspect to 1080x1920 with a blurred copy of the frame behind it
  * punch-ins / slow push-ins / shake (zooms, in edited-timeline seconds)
  * black & white windows (payoff)
  * burned-in captions in the ArmoredPOVs look: Montserrat ExtraBold on solid black boxes,
    coloured ROLE: tag on its own box on top, red italic punchlines with white asterisks,
    per-caption x/y placement near the speaker, optional header tracker and watermark
  * "band" framing (style.band_aspect): sharp centre band, blurred copy of the frame above/below
  * synthesized SFX (bass "boom") at given times
  * loudness normalised to -14 LUFS (two-pass)
  * optional voiceover: runs tools/vo_mix.py with the plan's "vo_plan" afterwards
  * TRACKING: "tracks" follow an object (OpenCV CSRT) so a caption or marker can ride on it
  * MASKING: a caption with "behind" is drawn under a subject cut-out (MediaPipe), so a person or
    object passes in front of the text

All times in "zooms", "bw", "shake", "captions", "header", "sfx", "tracks", "masks" are EDITED-video
seconds, and all x/y/box values are OUTPUT pixels (1080x1920). "segments" and "bleeps" are SOURCE seconds.

Two stages: stage A renders the cut, framing, zooms, B&W and sound into reports/<clip>/base.mov (cached:
it is reused while those fields don't change), stage B tracks/masks on that base and burns the captions.
`--base-only` stops after stage A, so you can look at the framed video and pick track points / boxes
in output pixels (tools/scene_probe.py base.mov lists people, faces and objects with their boxes).

Export ("export", optional; default 1080x1920 at the source frame rate):
  "export": {"width": 2160, "height": 3840, "fps": 60, "motion": "interpolate" | "duplicate"}
  4K is worth it on YouTube even from a small source (4K uploads get a better codec / bitrate). 60 fps from a
  30 fps source needs in-between frames: "interpolate" (motion-compensated; check fast motion for warping on the
  QA sheet) or "duplicate" (repeated frames, no artifacts). All plan coordinates stay on the 1080x1920 canvas.

Tracking / masking fields:
  "tracks":   [{"id": "gunner", "at": 1.2, "box": [x, y, w, h]}            # object's box at time `at`
               {"id": "nade", "at": 2.0, "point": [x, y], "size": 120}]     # or a point (box = size x size)
  captions:   {"follow": "gunner", "anchor": "above"|"below"|"center", "offset": [dx, dy], ...}
              x/y are then ignored; the caption rides on the tracked box (clamped inside the safe area)
  markers:    {"follow": "nade", "start", "end", "r"}                       # red circle + arrow sticks to it
  "masks":    [{"id": "m1", "subject": "people"}                            # every person in frame
               {"id": "m2", "subject": "person:gunner"}                     # only the tracked person (cleanest)
               {"id": "m3", "subject": "track:humvee"}]                     # any tracked object (point segmenter;
                                                                            # can bleed into similar background)
  captions:   {"behind": "m1", ...}   text goes BEHIND the masked subject (the "text behind person" look)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import vision  # noqa: E402  (tools/vision.py: tracking + masking)

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "assets" / "fonts"
W, H = 1080, 1920

# ASS colours are &HBBGGRR
COLORS = {"white": "&HFFFFFF&", "yellow": "&H00E5FF&", "red": "&H2020FF&", "cyan": "&HFFE500&",
          "green": "&H50E040&", "orange": "&H0090FF&", "grey": "&HB0B0B0&"}  # (legacy)


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        die(f"{cmd[0]} failed:\n{p.stderr[-2000:]}")
    return p.stdout + p.stderr


def probe(path: Path) -> dict:
    out = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                          "-show_format", str(path)]))
    v = next(s for s in out["streams"] if s["codec_type"] == "video")
    num, den = v.get("avg_frame_rate", "30/1").split("/")
    return {"fps": round(float(num) / float(den), 3) if float(den) else 30.0,
            "has_audio": any(s["codec_type"] == "audio" for s in out["streams"])}


# --------------------------------------------------------------------------
# Captions (ASS)
# --------------------------------------------------------------------------
def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def col(name: str) -> str:
    return COLORS.get(name, name)


def _ass_header(styles: list[str]) -> list[str]:
    return ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
            "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding", *styles, "",
            "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]


def _text_width(text: str, size: float) -> float:
    """Rough rendered width of a caption line in Montserrat ExtraBold caps (for clamping on screen)."""
    longest = max((ln for ln in text.split("\n")), key=len, default=text)
    return 0.68 * size * len(longest)


def _smooth_path(xs: list[float], win: int) -> list[float]:
    """Zero-lag smoothing (Gaussian-weighted, centred, edges held) so a tracked caption glides instead of
    copying every jolt of the tracker."""
    import numpy as np
    if win < 3 or len(xs) < 3:
        return xs
    sig = win / 4.0
    k = np.exp(-0.5 * (np.arange(-win, win + 1) / sig) ** 2)
    k /= k.sum()
    padded = np.pad(np.asarray(xs, float), (win, win), mode="edge")
    return list(np.convolve(padded, k, mode="valid"))


def _follow_positions(c: dict, tr: dict, fps: float, size: float, n_lines: int) -> list[tuple]:
    """(start, end, x0, y0, x1, y1) pieces for a caption riding on a tracked box.

    "smooth": seconds of smoothing on the caption's own path (default 0.35; 0 = raw tracker),
    "follow_amount": 0..1, how much of the subject's motion the caption copies (default 1; 0.5 = it
    moves half as far, calmer on violent motion while still drifting with the subject).
    Each piece is emitted with \\move, so libass interpolates between frames (smooth at 60 fps too)."""
    a, b = c["start"], c["end"]
    dx, dy = c.get("offset", [0, 0])
    anchor = c.get("anchor", "above")
    box_h = n_lines * size * 1.18
    half_w = _text_width(c["text"], c.get("size", size)) / 2 + 20
    i0, i1 = int(round(a * fps)), max(int(round(b * fps)), int(round(a * fps)) + 1)
    xs, ys = [], []
    for i in range(i0, i1 + 1):
        cx, cy, w, h = vision.position_at(tr, i / fps)
        if anchor == "above":
            y = cy - h / 2 - box_h - 24
        elif anchor == "below":
            y = cy + h / 2 + 24
        else:
            y = cy - box_h / 2
        xs.append(cx + dx)
        ys.append(y + dy)
    amt = float(c.get("follow_amount", 1.0))
    xs = [xs[0] + amt * (v - xs[0]) for v in xs]
    ys = [ys[0] + amt * (v - ys[0]) for v in ys]
    win = int(round(float(c.get("smooth", 0.35)) * fps / 2))
    xs, ys = _smooth_path(xs, win), _smooth_path(ys, win)
    clamp_x = lambda v: int(min(max(v, half_w + 30), W - half_w - 30))
    clamp_y = lambda v: int(min(max(v, 170), 1600 - box_h))
    out = []
    for k in range(len(xs) - 1):
        t0, t1 = (i0 + k) / fps, (i0 + k + 1) / fps
        if t0 >= b:
            break
        out.append((max(a, t0), min(b, t1), clamp_x(xs[k]), clamp_y(ys[k]), clamp_x(xs[k + 1]), clamp_y(ys[k + 1])))
    return out


def build_ass(plan: dict, path: Path, behind_path: Path | None = None, tracks: dict | None = None,
              fps: float = 30.0) -> bool:
    """ArmoredPOVs-style captions: Montserrat ExtraBold on a solid black box, the ROLE: tag as
    coloured text on its own black box sitting on top, punchlines in red italic with white
    asterisks, optional small watermark at the bottom centre.
    Captions with "behind" go to `behind_path` (drawn under the subject cut-out); returns True if any did."""
    tracks = tracks or {}
    st = dict(plan.get("style", {}))
    urgent = st.get("preset") == "urgent"
    if urgent:
        # UrgentPOVs look (measured from their Short covers at 720x1280, scaled to 1080 wide): sentence-case
        # Open Sans on translucent dark boxes, coloured speaker tag on its own box, italic *action* lines,
        # small italic note line under a caption, red Narrator tag, orange Context tag
        for k, v in {"size": 84, "tag_size": 47, "pad": 10, "pad_y": 0, "tag_pad": 7, "tag_pad_y": 0, "tag_gap": 0,
                     "font": "Open Sans", "font_italic": "Open Sans", "font_tag": "Open Sans",
                     "font_watermark": "Open Sans SemiBold", "caption_y": 900}.items():
            st.setdefault(k, v)
    # sizes calibrated against ArmoredPOVs frames (rendered side by side at the same scale)
    size = st.get("size", 88)              # main caption font size (1080-wide canvas)
    tag_size = st.get("tag_size", 50)
    pad = st.get("pad", 14)                # black box padding left/right of the main text
    pad_y = st.get("pad_y", 2)             # ...and above/below (the font's ascent already adds room)
    tag_pad = st.get("tag_pad", 9)
    tag_pad_y = st.get("tag_pad_y", 1)
    y_default = st.get("caption_y", 1150)  # TOP edge of the main text
    gap = st.get("tag_gap", 0)             # space between tag box and main box (negative = overlap)
    lift = st.get("tag_lift", 0)           # fine-tune for font ascent/descent differences
    # font family names as registered in assets/fonts (any .ttf/.otf dropped there can be used)
    f_main = st.get("font", "MontserratXB")
    f_ital = st.get("font_italic", "MontserratXBI")
    f_tag = st.get("font_tag", "MontserratB")
    f_mark = st.get("font_watermark", "MontserratSB")
    box = st.get("box_color", "&H58141414" if urgent else "&H00070707")   # AABBGGRR, AA 00 = opaque
    ital_col, ital_flag = ("&H00FFFFFF", -1) if urgent else ("&H002020E6", 0)
    note_size = st.get("note_size", int(size * (0.43 if urgent else 0.6)))
    styles = [
        f"Style: Box,{f_main},{size},&H00FFFFFF,&H00FFFFFF,{box},{box},0,0,0,0,100,100,0,0,3,{pad},0,8,40,40,0,1",
        f"Style: BoxI,{f_ital},{size},{ital_col},{ital_col},{box},{box},0,{ital_flag},0,0,100,100,0,0,3,{pad},0,8,40,40,0,1",
        f"Style: Tag,{f_tag},{tag_size},&H0000E5FF,&H0000E5FF,{box},{box},0,0,0,0,100,100,0,0,3,{tag_pad},0,2,40,40,0,1",
        f"Style: Note,{f_ital},{note_size},&H0024D2F7,&H0024D2F7,{box},{box},0,-1,0,0,100,100,0,0,3,{pad},0,8,40,40,0,1",
        f"Style: Mark,{f_mark},{st.get('watermark_size', 50)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,0,3,5,40,40,0,1",
        "Style: Draw,Arial,20,&H00FFFFFF,&H00FFFFFF,&H002020E6,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        f"Style: Head,{f_main},{st.get('header_size', 58)},&H00FFFFFF,&H00FFFFFF,{box},{box},0,0,0,0,100,100,6,0,3,{pad},0,8,40,40,0,1",
        f"Style: Label,{f_ital},{int(size * 0.62)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,-1,0,0,100,100,0,0,1,1,2,7,40,40,0,1",
    ]
    lines = _ass_header(styles)
    behind_lines = _ass_header(styles)

    def ev(layer, a, b, style, text, target=None):
        (lines if target is None else target).append(
            f"Dialogue: {layer},{ass_time(a)},{ass_time(b)},{style},,0,0,0,,{text}")

    tag_colors = {"green": "&H3BEA3B&", "teal": "&HEAFC37&", "cyan": "&HEAFC37&", "yellow": "&H00E5FF&",
                  "white": "&HFFFFFF&", "red": "&H2020E6&", "orange": "&H0090FF&"}
    if urgent:  # UrgentPOVs palette: narrator red, context orange, one colour per speaker
        tag_colors.update({"red": "&H2F2FD3&", "orange": "&H3BA9F2&", "blue": "&HF2A63E&", "green": "&H64D94C&",
                           "yellow": "&H3ED2F7&", "white": "&HFFFFFF&", "lime": "&H5AE6E6&"})
    any_behind = False
    for c in plan.get("captions", []):
        a, b = c["start"], c["end"]
        text = c["text"].replace("\n", r"\N")
        red = c.get("color") == "red"
        if urgent:
            # italic for *actions* and stat callouts; red only when asked (e.g. "*~4,000 lbs recoiling*")
            red = c.get("italic", c["text"].lstrip().startswith("*"))
            if c.get("color") == "red":
                text = rf"{{\c{tag_colors['red']}}}" + text
            elif c.get("color") and c["color"] != "white":
                text = rf"{{\c{tag_colors.get(c['color'], c['color'])}}}" + text
        elif red:  # red italic, asterisks stay white
            text = text.replace("*", r"{\c&HFFFFFF&}*{\c&H2020E6&}")
        elif c.get("color") and c["color"] != "white" and not urgent:
            text = rf"{{\c{tag_colors.get(c['color'], c['color'])}}}" + text
        fs = rf"\fs{c['size']}" if c.get("size") else ""  # per-caption size, e.g. one big punch word
        if c.get("label"):  # e.g. *Drop 1/4* or *Time: 10:33*: no box, small italic, anchored top-left
            ev(2, a, b, "Label", rf"{{\an7\pos({c.get('x', 70)},{c.get('y', 330)})}}{text}")
            continue
        if c.get("follow"):
            if c["follow"] not in tracks:
                die(f"caption '{c['text']}' follows unknown track '{c['follow']}'")
            pieces = _follow_positions(c, tracks[c["follow"]], fps, c.get("size", size), c["text"].count("\n") + 1)
        else:
            x, y = c.get("x", 540), c.get("y", y_default)
            pieces = [(a, b, x, y, x, y)]
        target = None
        if c.get("behind"):
            target, any_behind = behind_lines, True
        for (pa, pb, x, y, x2, y2) in pieces:
            ms = max(1, int(round((pb - pa) * 1000)))
            place = rf"\pos({x},{y})" if (x, y) == (x2, y2) else rf"\move({x},{y},{x2},{y2},0,{ms})"
            ev(2, pa, pb, "BoxI" if red else "Box", rf"{{{place}\xbord{pad}\ybord{pad_y}{fs}}}{text}", target)
            if c.get("tag"):
                dty = - pad_y - tag_pad_y - gap - lift
                tplace = rf"\pos({x},{y + dty})" if (x, y) == (x2, y2) else rf"\move({x},{y + dty},{x2},{y2 + dty},0,{ms})"
                ev(3, pa, pb, "Tag", rf"{{{tplace}\xbord{tag_pad}\ybord{tag_pad_y}\c{tag_colors.get(c.get('tag_color', 'green'), c.get('tag_color'))}}}{c['tag']}", target)
            if c.get("note"):  # small italic line under the caption, e.g. "(Really mad)" / "(Last thing you wanna hear)"
                n_lines = c["text"].count("\n") + 1
                dny = int(n_lines * c.get("size", size) * (1.04 if urgent else 1.2)) + pad_y
                nplace = rf"\pos({x},{y + dny})" if (x, y) == (x2, y2) else rf"\move({x},{y + dny},{x2},{y2 + dny},0,{ms})"
                ncol = tag_colors.get(c.get("note_color", "lime"), c.get("note_color", "lime"))
                ev(2, pa, pb, "Note", rf"{{{nplace}\xbord{pad}\ybord{pad_y}\c{ncol}}}{c['note']}", target)

    for h in plan.get("header", []):  # optional progress tracker, in the same box style
        word, filled = h["word"], h["filled"]
        parts = []
        for i, ch in enumerate(word):
            colr = "&H00E5FF&" if i == filled - 1 else "&HFFFFFF&"
            alpha = "&H00&" if i < filled else "&HB0&"
            parts.append(rf"{{\alpha{alpha}\c{colr}}}{ch}")
        ev(1, h["start"], h["end"], "Head", rf"{{\pos(540,{st.get('header_y', 300)})}}" + "".join(parts))

    if plan.get("watermark"):
        ev(0, 0, plan["_duration"], "Mark",
           rf"{{\pos(540,{st.get('watermark_y', 1785)})\alpha&H08&}}{plan['watermark']}")

    # red circle + arrow marker: {"start","end","x","y","r"} in output pixels (1080x1920)
    for mk in plan.get("markers", []):
        r = mk.get("r", 70); x, y = mk.get("x", 540), mk.get("y", 960); t = mk.get("thick", 10)
        k = 0.5523 * r  # bezier ring drawn in a 0..2r box, then placed so its centre lands on (x, y)
        c = r
        circle = (f"m {c + r} {c} b {c + r} {c + k} {c + k} {c + r} {c} {c + r} b {c - k} {c + r} {c - r} {c + k} {c - r} {c} "
                  f"b {c - r} {c - k} {c - k} {c - r} {c} {c - r} b {c + k} {c - r} {c + r} {c - k} {c + r} {c}")
        # tracking: "follow": track id (per-frame path from the tracker), or a manual
        # "path": [[t_rel_seconds, x, y], ...] keyframes (piecewise, one event per step)
        if mk.get("follow"):
            if mk["follow"] not in tracks:
                die(f"marker follows unknown track '{mk['follow']}'")
            tr = tracks[mk["follow"]]
            n_fr = max(1, int(round((mk["end"] - mk["start"]) * fps)))
            path_pts = [[k / fps, *vision.position_at(tr, mk["start"] + k / fps)[:2]] for k in range(n_fr + 1)]
        else:
            path_pts = mk.get("path") or [[0, x, y], [mk["end"] - mk["start"], x, y]]
        shaft = "m 0 14 l 14 0 l 112 98 l 98 112"
        head = "m 150 150 l 84 132 l 132 84"
        tip = 0.72 * r + t
        for (t0, xa, ya), (t1, xb, yb) in zip(path_pts, path_pts[1:]):
            a_, b_ = mk["start"] + t0, mk["start"] + t1
            ms = int((t1 - t0) * 1000)
            mv = lambda ox, oy: rf"\move({int(xa + ox)},{int(ya + oy)},{int(xb + ox)},{int(yb + oy)},0,{ms})"
            ev(4, a_, b_, "Draw",
               rf"{{\an7{mv(-r, -r)}\bord{t}\shad0\1a&HFF&\3c&H2020E6&\3a&H00&\p1}}{circle}{{\p0}}")
            # arrow from the upper left, tip touching the ring at 45 degrees
            ev(4, a_, b_, "Draw",
               rf"{{\an7{mv(-tip - 150, -tip - 150)}\bord0\shad0\1c&H2020E6&\1a&H00&\p1}}{shaft} {head}{{\p0}}")

    full = f"m 0 0 l {W} 0 l {W} {H} l 0 {H}"

    def circle_path(cx, cy, r):
        k = 0.5523 * r
        return (f"m {cx + r} {cy} b {cx + r} {cy + k} {cx + k} {cy + r} {cx} {cy + r} b {cx - k} {cy + r} {cx - r} {cy + k} "
                f"{cx - r} {cy} b {cx - r} {cy - k} {cx - k} {cy - r} {cx} {cy - r} b {cx + k} {cy - r} {cx + r} {cy - k} {cx + r} {cy}")

    # UrgentPOVs freeze callout: {"start","end","subject": "person:<track>"|"people"|{"points": [[x,y],..]}|null,"label": "*VERY STRICT*",
    #  "label_x": 90, "label_y": 330, "dim": 0.55, "glow": true, "type_dur": 0.35, "flash": true}
    # (pair it with a {"freeze": src_t, "dur": ...} segment and a {"type": "whoosh"} sfx for the full effect)
    flashes = list(plan.get("flashes", []))
    for co in plan.get("callouts", []):
        a, b = co["start"], co["end"]
        dim_a = format(int(255 * (1 - co.get("dim", 0.55))), "02X")
        dim_target = behind_lines if co.get("subject") else None
        if co.get("subject"):
            any_behind = True
        ev(1, a, b, "Draw", rf"{{\an7\pos(0,0)\bord0\shad0\1c&H000000&\1a&H{dim_a}&\p1}}{full}{{\p0}}", dim_target)
        if co.get("label"):
            lab = co["label"]
            n = len(lab)
            td = co.get("type_dur", 0.35)
            lx, ly = co.get("label_x", 90), co.get("label_y", 330)
            lsize = co.get("label_size", int(size * 0.95))
            for k in range(1, n + 1):  # typewriter: one more character per step
                ta = a + td * (k - 1) / n
                tb = b if k == n else a + td * k / n
                ev(6, ta, tb, "Box", rf"{{\an7\pos({lx},{ly})\xbord{pad}\ybord{pad_y}\fs{lsize}\i1\c&H2020E6&}}{lab[:k]}")
        if co.get("flash", True):
            flashes.append({"at": max(0.0, a - 0.12), "dur": 0.25})
            flashes.append({"at": b - 0.04, "dur": 0.25})
    # spotlight: dim everything except a soft circle, white glowing ring {"start","end","x","y","r"}
    for sp in plan.get("spotlights", []):
        a, b, x, y, r = sp["start"], sp["end"], sp["x"], sp["y"], sp.get("r", 150)
        dim_a = format(int(255 * (1 - sp.get("dim", 0.55))), "02X")
        ev(1, a, b, "Draw", rf"{{\an7\pos(0,0)\bord0\shad0\1c&H000000&\1a&H{dim_a}&\iclip(1,{circle_path(x, y, r)})\p1}}{full}{{\p0}}")
        ev(1, a, b, "Draw", rf"{{\an7\pos(0,0)\bord{sp.get('ring', 7)}\blur9\shad0\1a&HFF&\3c&HFFFFFF&\3a&H30&\p1}}{circle_path(x, y, r)}{{\p0}}")
    # pointer: red down-triangle that pops in above a thing, optional tiny label {"start","end","x","y"|"follow","label"}
    for po in plan.get("pointers", []):
        a, b = po["start"], po["end"]
        sz = po.get("size", 46)
        tri = f"m 0 0 l {2 * sz} 0 l {sz} {int(1.15 * sz)}"
        if po.get("follow"):
            tr = tracks[po["follow"]]
            n_fr = max(1, int(round((b - a) * fps)))
            pts = []
            for k in range(n_fr + 1):
                cx, cy, w, h = vision.position_at(tr, a + k / fps)
                pts.append([k / fps, cx, cy - h / 2 - 12])
        else:
            pts = [[0, po["x"], po["y"]], [b - a, po["x"], po["y"]]]
        for j, ((t0, xa, ya), (t1, xb, yb)) in enumerate(zip(pts, pts[1:])):
            ta, tb = a + t0, a + t1
            ms = max(1, int((t1 - t0) * 1000))
            pop = r"\fscx35\fscy35\t(0,140,\fscx100\fscy100)" if j == 0 else ""
            ev(4, ta, tb, "Draw", rf"{{\an2\move({int(xa)},{int(ya)},{int(xb)},{int(yb)},0,{ms}){pop}\bord0\shad0\1c&H2020E6&\p1}}{tri}{{\p0}}")
            if po.get("label"):
                ly_a, ly_b = int(ya - 1.15 * sz - 8), int(yb - 1.15 * sz - 8)
                ev(4, ta, tb, "Note", rf"{{\an2\move({int(xa)},{ly_a},{int(xb)},{ly_b},0,{ms})\xbord8\ybord0\c&HFFFFFF&}}{po['label']}")

    # full-screen white flash: {"at": seconds, "dur": 0.3}
    for fl in flashes:
        a = fl["at"]; d = fl.get("dur", 0.3)
        ev(5, a, a + d, "Draw",
           rf"{{\an7\pos(0,0)\bord0\shad0\1c&HFFFFFF&\fad(0,{int(d * 1000)})\p1}}m 0 0 l {W} 0 l {W} {H} l 0 {H}{{\p0}}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if behind_path is not None:
        behind_path.write_text("\n".join(behind_lines) + "\n", encoding="utf-8")
    return any_behind


# --------------------------------------------------------------------------
# Video expressions
# --------------------------------------------------------------------------
def zoom_expr(zooms: list[dict]) -> str:
    expr = "1"
    for z in reversed(zooms):
        a, b = z["start"], z["end"]
        z0, z1 = z.get("from", z.get("scale", 1)), z.get("to", z.get("scale", 1))
        val = f"({z0}+({z1}-{z0})*(it-{a})/{max(b - a, 1e-3)})" if z0 != z1 else f"{z0}"
        expr = f"if(between(it,{a},{b}),{val},{expr})"
    return expr


def shake_expr(shakes: list[dict], axis: str) -> str:
    if not shakes:
        return "0"
    f = 47 if axis == "x" else 61
    terms = [f"between(it,{s['start']},{s['end']})*{s.get('amp', 14)}*sin(it*{f})" for s in shakes]
    return "(" + "+".join(terms) + ")"


# --------------------------------------------------------------------------
def seg_dur(s: dict) -> float:
    """Edited length of a segment: {"in","out"[,"speed"]} or a freeze {"freeze": src_t, "dur": d}."""
    if "freeze" in s:
        return float(s["dur"])
    return (s["out"] - s["in"]) / s.get("speed", 1.0)


STAGE_A_KEYS = ("source", "segments", "bleeps", "bleep_volume", "fps", "zooms", "bw", "shake", "sfx")
STAGE_A_STYLE = ("band_aspect", "grade", "zoom_center")


def _stage_a_key(plan: dict, src: Path) -> str:
    st = plan.get("style", {})
    sig = {k: plan.get(k) for k in STAGE_A_KEYS}
    sig["style"] = {k: st.get(k) for k in STAGE_A_STYLE}
    sig["src"] = [src.stat().st_size, int(src.stat().st_mtime)]
    for s in plan.get("sfx", []):
        if s.get("path"):
            fp = Path(s["path"]); fp = fp if fp.is_absolute() else ROOT / fp
            sig.setdefault("sfx_files", []).append([str(fp), fp.stat().st_size if fp.exists() else 0])
    return hashlib.sha1(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:16]


def _resolve_tracks(plan: dict, base_vid: Path, fps: float) -> dict:
    """Run the tracker for every track used by a caption / marker / mask, over the span it's needed."""
    specs = {t["id"]: t for t in plan.get("tracks", [])}
    if not specs:
        return {}
    need: dict[str, list[float]] = {}

    def use(tid, a, b):
        if tid not in specs:
            die(f"unknown track '{tid}'")
        lo, hi = need.get(tid, [a, b])
        need[tid] = [min(lo, a), max(hi, b)]

    for c in plan.get("captions", []):
        if c.get("follow"):
            use(c["follow"], c["start"], c["end"])
    for mk in plan.get("markers", []) + plan.get("pointers", []):
        if mk.get("follow"):
            use(mk["follow"], mk["start"], mk["end"])
    for co in plan.get("callouts", []):
        subj = co.get("subject") if isinstance(co.get("subject"), str) else ""
        if subj.startswith(("track:", "person:")):
            use(subj.split(":", 1)[1], co["start"], co["end"])
    masks = {m["id"]: m for m in plan.get("masks", [])}
    for c in plan.get("captions", []):
        m = masks.get(c.get("behind"))
        subj = str(m.get("subject", "")) if m else ""
        if subj.startswith(("track:", "person:")):
            use(subj.split(":", 1)[1], c["start"], c["end"])
    out = {}
    for tid, (a, b) in need.items():
        t = specs[tid]
        if "box" in t:
            box = t["box"]
        elif "point" in t:
            sz = t.get("size", 140)
            box = [t["point"][0] - sz / 2, t["point"][1] - sz / 2, sz, sz]
        else:
            die(f"track '{tid}' needs a box or a point")
        tr = vision.track(base_vid, t["at"], box, a - 0.1, b + 0.1)
        if tr["lost"] > 0.15:
            print(f"warning: track '{tid}' lost the object on {tr['lost']:.0%} of frames - "
                  f"check the follow captions / markers, or pick a bigger, more textured box")
        out[tid] = tr
    return out


def _render_masks(plan: dict, base_vid: Path, tracks: dict, fps: float, n_frames: int, path: Path) -> None:
    """Grey mask video (white = subject in front of the 'behind' captions) for the whole edit."""
    masks = {m["id"]: m for m in plan.get("masks", [])}
    windows: list[tuple[int, int, dict]] = []
    for c in plan.get("captions", []):
        if not c.get("behind"):
            continue
        if c["behind"] not in masks:
            die(f"caption '{c['text']}' uses unknown mask '{c['behind']}'")
        windows.append((int(c["start"] * fps) - 1, int(c["end"] * fps) + 1, masks[c["behind"]]))
    glow_windows = []
    for co in plan.get("callouts", []):
        if co.get("subject"):
            m = {"subject": co["subject"], "feather": 2, "grow": 2}
            w = (int(co["start"] * fps) - 1, int(co["end"] * fps) + 1, m)
            windows.append(w)
            if co.get("glow", True):
                glow_windows.append(w)
    vis = vision.Vision()
    info = vision.video_info(base_vid)
    wr = vision.GrayWriter(path, info["w"], info["h"], fps)
    gw = vision.GrayWriter(path.with_name("_glow.mkv"), info["w"], info["h"], fps) if glow_windows else None
    for i, fr in vision.read_frames(base_vid):
        if i >= n_frames:
            break
        act = [m for (i0, i1, m) in windows if i0 <= i <= i1]
        if not act:
            wr.write(None)
            if gw:
                gw.write(None)
            continue
        acc = np.zeros(fr.shape[:2], np.float32)
        for m in {id(m): m for m in act}.values():
            subj = m.get("subject", "people")
            if isinstance(subj, dict) and "points" in subj:  # several clicks on one subject (best for close, blurry people)
                acc = np.maximum(acc, np.max([vis.thing(fr, x, y) for x, y in subj["points"]], axis=0))
                continue
            if subj == "people":
                acc = np.maximum(acc, vis.people(fr))
            elif subj.startswith("person:"):
                acc = np.maximum(acc, vis.person_at(fr, vision.position_at(tracks[subj[7:]], i / fps)))
            elif subj.startswith("track:"):
                cx, cy, _, _ = vision.position_at(tracks[subj[6:]], i / fps)
                acc = np.maximum(acc, vis.thing(fr, cx, cy))
            else:
                die(f"unknown mask subject '{subj}' (use 'people', 'person:<track>' or 'track:<track>')")
        cm = vision.clean_mask(acc, feather=m.get("feather", 3), grow=m.get("grow", 2))
        wr.write(cm)
        if gw:
            if any(i0 <= i <= i1 for (i0, i1, _) in glow_windows):
                # white outer glow: grown + blurred silhouette (sits under the cut-out, shows as a halo)
                g = cv2.dilate(cm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
                g = cv2.GaussianBlur(g, (0, 0), 14)
                gw.write(np.clip(g.astype(np.float32) * 1.4, 0, 255).astype(np.uint8))
            else:
                gw.write(None)
    # pad if the decoder returned fewer frames than the timeline
    for _ in range(max(0, n_frames - info["n"])):
        wr.write(None)
        if gw:
            gw.write(None)
    if gw:
        gw.close()
    wr.close()
    vis.close()


def render(plan_path: Path, base_only: bool = False) -> Path:
    plan = json.loads(plan_path.read_text())
    base = plan_path.parent
    src = Path(plan["source"])
    if not src.is_absolute():
        src = ROOT / src
    if not src.exists():
        die(f"source not found: {src}")
    out = Path(plan.get("output", base / "final.mp4"))
    if not out.is_absolute():
        out = ROOT / out
    info = probe(src)
    fps = plan.get("fps", info["fps"])
    segs = plan["segments"]
    # a segment may carry "speed" (0.5 = half-speed slow motion; audio is pitch-kept with atempo)
    dur = sum(seg_dur(s) for s in segs)
    plan["_duration"] = dur

    out.parent.mkdir(parents=True, exist_ok=True)
    base_vid = base / "base.mov"
    key = _stage_a_key(plan, src)
    key_file = base / "base.key"
    if base_vid.exists() and key_file.exists() and key_file.read_text().strip() == key:
        print(f"stage A: reusing {base_vid.relative_to(ROOT) if base_vid.is_relative_to(ROOT) else base_vid}")
    else:
        _render_stage_a(plan, src, info, fps, segs, dur, base_vid)
        key_file.write_text(key)
    if base_only:
        print(f"Wrote {base_vid} (framed, cut, no captions) - pick track boxes / points on this, in output pixels")
        return base_vid
    return _render_stage_b(plan, base_vid, out, fps, dur)


def _render_stage_a(plan: dict, src: Path, info: dict, fps: float, segs: list, dur: float, base_vid: Path) -> None:
    f = []
    # ---- audio: bleeps on the source timeline, then cut
    # bleeps: [a, b] = mute + 1 kHz tone; {"start": a, "end": b, "tone": false} = mute only
    # (e.g. when a meme SFX covers the word instead of the beep)
    bl = [{"start": x[0], "end": x[1], "tone": True} if isinstance(x, list) else {"tone": True, **x}
          for x in plan.get("bleeps", [])]
    bexpr = "+".join(f"between(t,{b['start']},{b['end']})" for b in bl) or "0"
    texpr = "+".join(f"between(t,{b['start']},{b['end']})" for b in bl if b["tone"]) or "0"
    if info["has_audio"]:
        f.append(f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=enable='{bexpr}':volume=0[o]")
    else:
        f.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{max(s.get('out', s.get('freeze', 0)) for s in segs) + 1}[o]")
    f.append(f"sine=f=1000:r=48000,aformat=sample_rates=48000:channel_layouts=stereo,"
             f"volume={plan.get('bleep_volume', 0.25)},volume=enable='not({texpr})':volume=0[bl]")
    f.append("[o][bl]amix=inputs=2:normalize=0:duration=first[asrc]")

    n = len(segs)
    f.append(f"[0:v]split={n}" + "".join(f"[vs{i}]" for i in range(n)))
    f.append(f"[asrc]asplit={n}" + "".join(f"[as{i}]" for i in range(n)))
    cat = ""
    for i, s in enumerate(segs):
        sp = float(s.get("speed", 1.0))
        if "freeze" in s:  # hold one frame (UrgentPOVs callout freeze); its audio is silence
            ft, fd = float(s["freeze"]), float(s["dur"])
            f.append(f"[vs{i}]trim=start={ft}:end={ft + 0.05},setpts=PTS-STARTPTS,"
                     f"tpad=stop_mode=clone:stop_duration={fd + 0.1},trim=duration={fd},setpts=PTS-STARTPTS[v{i}]")
            f.append(f"[as{i}]atrim=start={ft}:end={ft + 0.01},asetpts=PTS-STARTPTS,volume=0,apad=whole_dur={fd}[a{i}]")
            cat += f"[v{i}][a{i}]"
            continue
        f.append(f"[vs{i}]trim={s['in']}:{s['out']},setpts=(PTS-STARTPTS)/{sp}[v{i}]")
        atempo = ""
        if sp != 1.0:
            r, chain = sp, []
            while r < 0.5:
                chain.append("atempo=0.5"); r /= 0.5
            chain.append(f"atempo={r:.4f}")
            atempo = "," + ",".join(chain) + (f",volume={s['slow_volume']}" if "slow_volume" in s else "")
        f.append(f"[as{i}]atrim={s['in']}:{s['out']},asetpts=PTS-STARTPTS{atempo}[a{i}]")
        cat += f"[v{i}][a{i}]"
    f.append(f"{cat}concat=n={n}:v=1:a=1[vc][ac]")

    # ---- video: 9:16 with blurred fill, 2x for smooth zoom, zoom/shake, B&W, captions
    f.append(f"[vc]fps={fps},split[vbg][vfg]")
    band = plan.get("style", {}).get("band_aspect")  # e.g. 0.74 = width/height of the sharp centre band
    f.append(f"[vbg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
             f"boxblur=22:3,eq=brightness=-0.03:saturation=0.9[bg]")
    # style.grade: lift dark, muddy footage (brighter, more contrast, a touch of sharpening)
    grade = ",eq=brightness=0.06:contrast=1.18:saturation=1.12:gamma=1.08,unsharp=5:5:0.9" if plan.get("style", {}).get("grade") else ""
    if band:
        f.append(f"[vfg]crop='min(iw,ih*{band})':'min(ih,iw/{band})'{grade},scale={W}:-2[fg]")
    else:
        f.append(f"[vfg]null{grade},scale={W}:{H}:force_original_aspect_ratio=decrease[fg]")
    f.append(f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale={W * 2}:{H * 2}:flags=lanczos[v916]")
    z = zoom_expr(plan.get("zooms", []))
    sx, sy = shake_expr(plan.get("shake", []), "x"), shake_expr(plan.get("shake", []), "y")
    # zoom centre (fractions of the frame), e.g. style.zoom_center [0.62, 0.45] to follow a subject off-centre
    cx, cy = plan.get("style", {}).get("zoom_center", [0.5, 0.5])
    f.append(f"[v916]zoompan=z='{z}':d=1:s={W}x{H}:fps={fps}:"
             f"x='max(0,min(iw-iw/zoom,iw*{cx}-(iw/zoom/2)+{sx}))':"
             f"y='max(0,min(ih-ih/zoom,ih*{cy}-(ih/zoom/2)+{sy}))'[vz]")
    bw = "+".join(f"between(t,{b['start']},{b['end']})" for b in plan.get("bw", [])) or "0"
    f.append(f"[vz]hue=s=0:enable='{bw}',eq=contrast=1.12:enable='{bw}'[vb]")
    f.append("[vb]format=yuv420p[vout]")

    # ---- SFX
    # {"type": "boom", "at": 7.3}  - synthesized bass hit
    # {"type": "file", "path": "assets/sfx/x.mp3", "at": 7.3, "trim": [0, 1.2], "gain_db": 6}
    #   "at" is when the file's first sample plays; "hit" (seconds into the file) shifts it so the
    #   sound's attack lands exactly on "at" instead
    sfx = plan.get("sfx", [])
    extra_inputs: list[str] = []
    mix_in = "[ac]"
    for k, s in enumerate(sfx):
        kind = s.get("type", "boom")
        at = s["at"]
        if kind == "drone":  # low tension bed: two detuned low tones with a slow pulse
            d = s.get("dur", 3.0)
            # pitched where phone speakers can play it (they drop most sound below ~200 Hz)
            gen = (f"aevalsrc='0.3*(0.5*sin(2*PI*110*t)+sin(2*PI*220*t)+0.6*sin(2*PI*329.6*t)+0.25*sin(2*PI*441*t))"
                   f"*(0.75+0.25*sin(2*PI*1.6*t))':s=48000:d={d},"
                   f"afade=t=in:d=0.4,afade=t=out:st={max(0.0, d - 0.12):.3f}:d=0.12,"
                   "aformat=sample_rates=48000:channel_layouts=stereo")
        elif kind == "whoosh":  # filtered pink-noise swell (no pitched tones), for freezes / flashes
            d = s.get("dur", 0.45)
            gen = (f"anoisesrc=d={d}:c=pink:a=0.7,highpass=f=700,lowpass=f=9000,"
                   f"afade=t=in:d={0.65 * d:.3f}:curve=exp,afade=t=out:st={0.65 * d:.3f}:d={0.35 * d:.3f},"
                   "aformat=sample_rates=48000:channel_layouts=stereo")
        elif kind == "boom":
            gen = ("aevalsrc='0.9*sin(2*PI*(42+70*exp(-9*t))*t)*exp(-3.2*t)':s=48000:d=1.2,"
                   "aformat=sample_rates=48000:channel_layouts=stereo")
        elif kind == "file":
            fp = Path(s["path"])
            fp = fp if fp.is_absolute() else ROOT / fp
            if not fp.exists():
                die(f"sfx file not found: {fp}")
            extra_inputs += ["-i", str(fp)]
            idx = len(extra_inputs) // 2  # input 0 is the source clip
            t0, t1 = s.get("trim", [0, None])
            trim = f"atrim={t0}" + (f":{t1}" if t1 else "")
            fade = f",afade=t=out:st={max(0.0, (t1 or 0) - t0 - 0.25):.3f}:d=0.25" if t1 else ""
            gen = (f"[{idx}:a]{trim},asetpts=PTS-STARTPTS{fade},"
                   "aformat=sample_rates=48000:channel_layouts=stereo")
            at = at - (s.get("hit", t0) - t0)
        else:
            die(f"unknown sfx type {kind}")
        ms = max(0, int(round(at * 1000)))
        f.append(f"{gen},volume={s.get('gain_db', 0)}dB,adelay={ms}|{ms}[sfx{k}]")
        mix_in += f"[sfx{k}]"
    if sfx:
        f.append(f"{mix_in}amix=inputs={len(sfx) + 1}:normalize=0:duration=first[amix]")
    else:
        f.append("[ac]anull[amix]")

    graph = ";".join(f)
    tmp = base_vid.with_name("_base_tmp.mov")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), *extra_inputs,
         "-filter_complex", graph,
         "-map", "[vout]", "-map", "[amix]", "-c:v", "libx264", "-preset", "fast", "-crf", "10",
         "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-t", f"{dur:.3f}", str(tmp)])
    tmp.replace(base_vid)


def _ff_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _render_stage_b(plan: dict, base_vid: Path, out: Path, fps: float, dur: float) -> Path:
    base = out.parent
    n_frames = int(round(dur * fps))
    tracks = _resolve_tracks(plan, base_vid, fps)
    ass, ass_b = base / "_captions.ass", base / "_captions_behind.ass"
    # ---- export size / frame rate. Captions stay authored on the 1080x1920 canvas; libass redraws them
    # at the export size, so text is sharp at 4K instead of being upscaled with the picture.
    ex = plan.get("export", {})
    ew, eh = int(ex.get("width", W)), int(ex.get("height", H))
    efps = float(ex.get("fps", fps))
    pre = ""
    if abs(efps - fps) > 0.01:
        if ex.get("motion", "interpolate") == "interpolate":  # motion-compensated in-between frames
            pre += f"minterpolate=fps={efps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
        else:  # "duplicate": repeat frames (no warping risk, motion stays 30 fps-smooth)
            pre += f"fps={efps},"
    if (ew, eh) != (W, H):
        pre += f"scale={ew}:{eh}:flags=lanczos,"
    pre = pre.rstrip(",") or "null"
    any_behind = build_ass(plan, ass, ass_b, tracks, efps)
    sub = f"subtitles='{_ff_path(ass)}':fontsdir='{_ff_path(FONT_DIR)}'"
    inputs = ["-i", str(base_vid)]
    if any_behind:
        mask_vid = base / "_mask.mkv"
        _render_masks(plan, base_vid, tracks, fps, n_frames, mask_vid)
        inputs += ["-i", str(mask_vid)]
        glow_vid = base / "_glow.mkv"
        if glow_vid.exists():  # callouts: white halo under the cut-out subject
            inputs += ["-i", str(glow_vid)]
            vgraph = (f"[0:v]{pre},split[va][vb];[va]subtitles='{_ff_path(ass_b)}':fontsdir='{_ff_path(FONT_DIR)}'[vt];"
                      f"[2:v]fps={efps},scale={ew}:{eh},format=gray[g];color=c=white:s={ew}x{eh}:r={efps}[wh];"
                      f"[wh][g]alphamerge[glow];[vt][glow]overlay=0:0:shortest=1[vtg];"
                      f"[1:v]fps={efps},scale={ew}:{eh},format=gray[m];[vb][m]alphamerge[cut];[vtg][cut]overlay=0:0:format=auto[vc];"
                      f"[vc]{sub},format=yuv420p[vout]")
        else:
            vgraph = (f"[0:v]{pre},split[va][vb];[va]subtitles='{_ff_path(ass_b)}':fontsdir='{_ff_path(FONT_DIR)}'[vt];"
                      f"[1:v]fps={efps},scale={ew}:{eh},format=gray[m];[vb][m]alphamerge[cut];[vt][cut]overlay=0:0:format=auto[vc];"
                      f"[vc]{sub},format=yuv420p[vout]")
    else:
        vgraph = f"[0:v]{pre},{sub},format=yuv420p[vout]"
    venc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    if ew * eh > 1920 * 1080 * 1.5:  # 4K: H.264 High@5.2 (what YouTube ingests fine), a bit more bitrate headroom
        venc = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
                "-profile:v", "high", "-level:v", "5.2"]
    if abs(efps - fps) > 0.01:
        venc += ["-r", f"{efps:g}"]

    # ---- loudness, two-pass (measured on the stage-A mix, applied while burning captions)
    target = "I=-14:TP=-1.5:LRA=11"
    meas = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(base_vid), "-af",
                f"loudnorm={target}:print_format=json", "-f", "null", "-"])
    m = json.loads(meas[meas.rfind("{"): meas.rfind("}") + 1])
    try:
        silent = float(m["input_i"]) < -70
    except ValueError:  # "-inf" for pure silence
        silent = True
    agraph = (f"[0:a]loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']}:linear=true[aout]") if not silent else "[0:a]anull[aout]"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
         "-filter_complex", vgraph + ";" + agraph, "-map", "[vout]", "-map", "[aout]", *venc,
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t", f"{dur:.3f}", str(out)])
    for p in (ass, ass_b, base / "_mask.mkv", base / "_glow.mkv"):
        p.unlink(missing_ok=True)
    (base / "tracks.json").write_text(json.dumps(
        {k: {"lost": v["lost"], "fps": v["fps"], "path": {str(i): xy for i, xy in list(v["frames"].items())[::3]}}
         for k, v in tracks.items()}))

    # ---- optional voiceover
    if plan.get("vo_plan"):
        vp = Path(plan["vo_plan"])
        vp = vp if vp.is_absolute() else ROOT / vp
        vo_cfg = json.loads(vp.read_text())
        vo_file = Path(vo_cfg.get("vo_file", ""))
        if not (vo_file if vo_file.is_absolute() else vp.parent / vo_file).exists():
            print(f"note: voiceover audio {vo_file} not found yet, so rendered without VO")
        else:
            final = out.with_name(out.stem + "_vo.mp4")
            run([sys.executable, str(ROOT / "tools" / "vo_mix.py"), "mix", str(out), str(vp), "--out", str(final)])
            print(f"Wrote {final}")
    print(f"Wrote {out} ({dur:.2f}s)")
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        die("usage: render_edit.py <edit_plan.json> [--base-only]")
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            die(f"{t} not found on PATH")
    render(Path(args[0]).resolve(), base_only="--base-only" in sys.argv)


if __name__ == "__main__":
    main()
