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
  * burned-in captions: Anton, white with black outline, coloured ROLE: tag above,
    pop-in animation, plus an optional persistent header (e.g. an A-R-M-Y tracker)
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
          "green": "&H50E040&", "orange": "&H0090FF&", "grey": "&HB0B0B0&"}


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


def build_ass(plan: dict, path: Path) -> None:
    st = plan.get("style", {})
    font = st.get("font", "Anton")
    size = st.get("size", 104)
    tag_size = st.get("tag_size", 62)
    y = st.get("caption_y", 1180)          # lower-middle, clear of the bottom ~15%
    head_y = st.get("header_y", 360)
    pop = r"{\fscx70\fscy70\t(0,90,\fscx108\fscy108)\t(90,150,\fscx100\fscy100)}"

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,1,0,1,7,4,5,60,60,0,1",
        f"Style: Tag,{font},{tag_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,2,0,1,5,3,5,60,60,0,1",
        f"Style: Head,{font},{st.get('header_size', 150)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,8,4,5,40,40,0,1",
        f"Style: Mark,{font},44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,1,0,1,3,2,5,40,40,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def ev(layer, a, b, style, text):
        lines.append(f"Dialogue: {layer},{ass_time(a)},{ass_time(b)},{style},,0,0,0,,{text}")

    for c in plan.get("captions", []):
        a, b = c["start"], c["end"]
        text = c["text"].replace("\n", r"\N")
        anim = pop if c.get("pop", True) else ""
        ev(2, a, b, "Cap", rf"{{\pos(540,{y})\c{col(c.get('color', 'white'))}}}{anim}{text}")
        if c.get("tag"):
            ev(2, a, b, "Tag", rf"{{\pos(540,{y - size // 2 - 46})\c{col(c.get('tag_color', 'yellow'))}}}{c['tag']}")

    # header tracker: each state shows the full word, with filled letters solid and the rest faint
    for h in plan.get("header", []):
        word, filled = h["word"], h["filled"]
        hl = h.get("highlight", "yellow")
        parts = []
        for i, ch in enumerate(word):
            if i < filled - 1:
                parts.append(rf"{{\alpha&H00&\c{col('white')}}}{ch}")
            elif i == filled - 1:
                parts.append(rf"{{\alpha&H00&\c{col(hl)}}}{ch}")
            else:
                parts.append(rf"{{\alpha&HC8&\c{col('white')}}}{ch}")
        anim = r"{\fscx92\fscy92\t(0,120,\fscx100\fscy100)}"
        ev(1, h["start"], h["end"], "Head", rf"{{\pos(540,{head_y})}}{anim}" + " ".join(parts))

    if plan.get("watermark"):
        ev(0, 0, plan["_duration"], "Mark", rf"{{\pos(540,{st.get('watermark_y', 1600)})\alpha&H40&}}{plan['watermark']}")

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
    dur = sum(s["out"] - s["in"] for s in segs)
    plan["_duration"] = dur

    ass = base / "_captions.ass"
    build_ass(plan, ass)

    f = []
    # ---- audio: bleeps on the source timeline, then cut
    bleeps = plan.get("bleeps", [])
    bexpr = "+".join(f"between(t,{a},{b})" for a, b in bleeps) or "0"
    if info["has_audio"]:
        f.append(f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=enable='{bexpr}':volume=0[o]")
    else:
        f.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{max(s['out'] for s in segs) + 1}[o]")
    f.append(f"sine=f=1000:r=48000,aformat=sample_rates=48000:channel_layouts=stereo,"
             f"volume={plan.get('bleep_volume', 0.25)},volume=enable='not({bexpr})':volume=0[bl]")
    f.append("[o][bl]amix=inputs=2:normalize=0:duration=first[asrc]")

    n = len(segs)
    f.append(f"[0:v]split={n}" + "".join(f"[vs{i}]" for i in range(n)))
    f.append(f"[asrc]asplit={n}" + "".join(f"[as{i}]" for i in range(n)))
    cat = ""
    for i, s in enumerate(segs):
        f.append(f"[vs{i}]trim={s['in']}:{s['out']},setpts=PTS-STARTPTS[v{i}]")
        f.append(f"[as{i}]atrim={s['in']}:{s['out']},asetpts=PTS-STARTPTS[a{i}]")
        cat += f"[v{i}][a{i}]"
    f.append(f"{cat}concat=n={n}:v=1:a=1[vc][ac]")

    # ---- video: 9:16 with blurred fill, 2x for smooth zoom, zoom/shake, B&W, captions
    f.append(f"[vc]fps={fps},split[vbg][vfg]")
    f.append(f"[vbg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:2,eq=brightness=-0.08[bg]")
    f.append(f"[vfg]scale={W}:{H}:force_original_aspect_ratio=decrease[fg]")
    f.append(f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale={W * 2}:{H * 2}:flags=lanczos[v916]")
    z = zoom_expr(plan.get("zooms", []))
    sx, sy = shake_expr(plan.get("shake", []), "x"), shake_expr(plan.get("shake", []), "y")
    f.append(f"[v916]zoompan=z='{z}':d=1:s={W}x{H}:fps={fps}:"
             f"x='iw/2-(iw/zoom/2)+{sx}':y='ih/2-(ih/zoom/2)+{sy}'[vz]")
    bw = "+".join(f"between(t,{b['start']},{b['end']})" for b in plan.get("bw", [])) or "0"
    f.append(f"[vz]hue=s=0:enable='{bw}',eq=contrast=1.12:enable='{bw}'[vb]")
    ass_esc = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    f.append(f"[vb]subtitles='{ass_esc}':fontsdir='{FONT_DIR}',format=yuv420p[vout]")

    # ---- SFX
    sfx = plan.get("sfx", [])
    mix_in = "[ac]"
    for k, s in enumerate(sfx):
        if s.get("type", "boom") == "boom":
            gen = ("aevalsrc='0.9*sin(2*PI*(42+70*exp(-9*t))*t)*exp(-3.2*t)':s=48000:d=1.2,"
                   "aformat=sample_rates=48000:channel_layouts=stereo")
        else:
            die(f"unknown sfx type {s.get('type')}")
        ms = int(round(s["at"] * 1000))
        f.append(f"{gen},volume={s.get('gain_db', 0)}dB,adelay={ms}|{ms}[sfx{k}]")
        mix_in += f"[sfx{k}]"
    if sfx:
        f.append(f"{mix_in}amix=inputs={len(sfx) + 1}:normalize=0:duration=first[amix]")
    else:
        f.append("[ac]anull[amix]")

    graph = ";".join(f)
    tmp = out.with_name(out.stem + "_pre.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-filter_complex", graph,
         "-map", "[vout]", "-map", "[amix]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-t", f"{dur:.3f}", str(tmp.with_suffix(".mov"))])
    tmp = tmp.with_suffix(".mov")

    # ---- loudness, two-pass
    target = "I=-14:TP=-1.5:LRA=11"
    meas = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(tmp), "-af",
                f"loudnorm={target}:print_format=json", "-f", "null", "-"])
    m = json.loads(meas[meas.rfind("{"): meas.rfind("}") + 1])
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp), "-af",
         f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
         f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true",
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
