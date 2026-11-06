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

All times in "zooms", "bw", "shake", "captions", "header", "sfx" are EDITED-video seconds.
"segments" and "bleeps" are SOURCE seconds.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

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


def build_ass(plan: dict, path: Path) -> None:
    """ArmoredPOVs-style captions: Montserrat ExtraBold on a solid black box, the ROLE: tag as
    coloured text on its own black box sitting on top, punchlines in red italic with white
    asterisks, optional small watermark at the bottom centre."""
    st = plan.get("style", {})
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
    styles = [
        f"Style: Box,{f_main},{size},&H00FFFFFF,&H00FFFFFF,&H00070707,&H00070707,0,0,0,0,100,100,0,0,3,{pad},0,8,40,40,0,1",
        f"Style: BoxI,{f_ital},{size},&H002020E6,&H002020E6,&H00070707,&H00070707,0,0,0,0,100,100,0,0,3,{pad},0,8,40,40,0,1",
        f"Style: Tag,{f_tag},{tag_size},&H0000E5FF,&H0000E5FF,&H00070707,&H00070707,0,0,0,0,100,100,0,0,3,{tag_pad},0,2,40,40,0,1",
        f"Style: Mark,{f_mark},{st.get('watermark_size', 50)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,0,3,5,40,40,0,1",
        "Style: Draw,Arial,20,&H00FFFFFF,&H00FFFFFF,&H002020E6,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        f"Style: Head,{f_main},{st.get('header_size', 58)},&H00FFFFFF,&H00FFFFFF,&H00070707,&H00070707,0,0,0,0,100,100,6,0,3,{pad},0,8,40,40,0,1",
    ]
    lines = _ass_header(styles)

    def ev(layer, a, b, style, text):
        lines.append(f"Dialogue: {layer},{ass_time(a)},{ass_time(b)},{style},,0,0,0,,{text}")

    tag_colors = {"green": "&H3BEA3B&", "teal": "&HEAFC37&", "cyan": "&HEAFC37&", "yellow": "&H00E5FF&",
                  "white": "&HFFFFFF&", "red": "&H2020E6&", "orange": "&H0090FF&"}
    for c in plan.get("captions", []):
        a, b = c["start"], c["end"]
        x, y = c.get("x", 540), c.get("y", y_default)
        text = c["text"].replace("\n", r"\N")
        red = c.get("color") == "red"
        if red:  # red italic, asterisks stay white
            text = text.replace("*", r"{\c&HFFFFFF&}*{\c&H2020E6&}")
        elif c.get("color") and c["color"] != "white":
            text = rf"{{\c{tag_colors.get(c['color'], c['color'])}}}" + text
        fs = rf"\fs{c['size']}" if c.get("size") else ""  # per-caption size, e.g. one big punch word
        ev(2, a, b, "BoxI" if red else "Box", rf"{{\pos({x},{y})\xbord{pad}\ybord{pad_y}{fs}}}{text}")
        if c.get("tag"):
            ty = y - pad_y - tag_pad_y - gap - lift
            ev(3, a, b, "Tag", rf"{{\pos({x},{ty})\xbord{tag_pad}\ybord{tag_pad_y}\c{tag_colors.get(c.get('tag_color', 'green'), c.get('tag_color'))}}}{c['tag']}")

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
        r = mk.get("r", 70); x, y = mk["x"], mk["y"]; t = mk.get("thick", 10)
        k = 0.5523 * r  # bezier ring drawn in a 0..2r box, then placed so its centre lands on (x, y)
        c = r
        circle = (f"m {c + r} {c} b {c + r} {c + k} {c + k} {c + r} {c} {c + r} b {c - k} {c + r} {c - r} {c + k} {c - r} {c} "
                  f"b {c - r} {c - k} {c - k} {c - r} {c} {c - r} b {c + k} {c - r} {c + r} {c - k} {c + r} {c}")
        # tracking: optional "path": [[t_rel_seconds, x, y], ...] keyframes (piecewise, one event per step)
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

    # full-screen white flash: {"at": seconds, "dur": 0.3}
    for fl in plan.get("flashes", []):
        a = fl["at"]; d = fl.get("dur", 0.3)
        ev(5, a, a + d, "Draw",
           rf"{{\an7\pos(0,0)\bord0\shad0\1c&HFFFFFF&\fad(0,{int(d * 1000)})\p1}}m 0 0 l {W} 0 l {W} {H} l 0 {H}{{\p0}}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
def render(plan_path: Path) -> Path:
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
    dur = sum((s["out"] - s["in"]) / s.get("speed", 1.0) for s in segs)
    plan["_duration"] = dur

    ass = base / "_captions.ass"
    build_ass(plan, ass)

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
        f.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{max(s['out'] for s in segs) + 1}[o]")
    f.append(f"sine=f=1000:r=48000,aformat=sample_rates=48000:channel_layouts=stereo,"
             f"volume={plan.get('bleep_volume', 0.25)},volume=enable='not({texpr})':volume=0[bl]")
    f.append("[o][bl]amix=inputs=2:normalize=0:duration=first[asrc]")

    n = len(segs)
    f.append(f"[0:v]split={n}" + "".join(f"[vs{i}]" for i in range(n)))
    f.append(f"[asrc]asplit={n}" + "".join(f"[as{i}]" for i in range(n)))
    cat = ""
    for i, s in enumerate(segs):
        sp = float(s.get("speed", 1.0))
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
    ass_esc = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    f.append(f"[vb]subtitles='{ass_esc}':fontsdir='{FONT_DIR}',format=yuv420p[vout]")

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
    tmp = out.with_name(out.stem + "_pre.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), *extra_inputs,
         "-filter_complex", graph,
         "-map", "[vout]", "-map", "[amix]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-t", f"{dur:.3f}", str(tmp.with_suffix(".mov"))])
    tmp = tmp.with_suffix(".mov")

    # ---- loudness, two-pass
    target = "I=-14:TP=-1.5:LRA=11"
    meas = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(tmp), "-af",
                f"loudnorm={target}:print_format=json", "-f", "null", "-"])
    m = json.loads(meas[meas.rfind("{"): meas.rfind("}") + 1])
    try:
        silent = float(m["input_i"]) < -70
    except ValueError:  # "-inf" for pure silence
        silent = True
    af = ["-af", f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                 f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
                 f"offset={m['target_offset']}:linear=true"] if not silent else []
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp), *af,
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    tmp.unlink(missing_ok=True)
    ass.unlink(missing_ok=True)

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
    if len(sys.argv) != 2:
        die("usage: render_edit.py <edit_plan.json>")
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            die(f"{t} not found on PATH")
    render(Path(sys.argv[1]).resolve())


if __name__ == "__main__":
    main()
