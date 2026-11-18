#!/usr/bin/env python3
"""
vision.py - the computer-vision pieces shared by the renderer, the scene probe and the reference study.

  * track()          follow an object through a video (OpenCV CSRT, forward and backward from a key frame,
                     smoothed), so captions / markers can stick to it
  * Vision.people()  soft mask of every person in a frame (MediaPipe selfie-multiclass)
  * Vision.thing()   soft mask of the one object under a point (MediaPipe "magic touch"), for masking a
                     specific soldier, vehicle or weapon instead of everyone
  * Vision.faces()   face boxes (face-skin class of the same model), so captions can stay off faces
  * Vision.detect()  object boxes with labels (EfficientDet-Lite2, COCO: person, car, truck, dog, ...)

Models live in $CLIP_COACH_VISION_MODELS (default ~/.cache/clip-coach/vision); install them with
`bash tools/setup_vision.sh`. Needs: opencv-contrib-python-headless, mediapipe, numpy, and libEGL
(apt: libegl1 libgles2), all installed by the setup script.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import cv2
import numpy as np

MODEL_DIR = Path(os.environ.get("CLIP_COACH_VISION_MODELS", Path.home() / ".cache" / "clip-coach" / "vision"))


# --------------------------------------------------------------------------
# video I/O
# --------------------------------------------------------------------------
def video_info(path: str | Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"error: cannot open {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    info = {"fps": fps, "w": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "h": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "n": int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}
    cap.release()
    return info


def read_frames(path: str | Path, i0: int = 0, i1: int | None = None, scale: float = 1.0):
    """Yield (index, frame) for frames i0..i1 (inclusive), optionally downscaled."""
    cap = cv2.VideoCapture(str(path))
    if i0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i0)
    i = i0
    while i1 is None or i <= i1:
        ok, fr = cap.read()
        if not ok:
            break
        if scale != 1.0:
            fr = cv2.resize(fr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        yield i, fr
        i += 1
    cap.release()


class GrayWriter:
    """Write single-channel 8-bit frames (masks) to a lossless video through ffmpeg."""

    def __init__(self, path: Path, w: int, h: int, fps: float):
        self.p = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
             "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-", "-c:v", "ffv1", "-pix_fmt", "gray", str(path)],
            stdin=subprocess.PIPE)
        self.blank = np.zeros((h, w), np.uint8)

    def write(self, m: np.ndarray | None) -> None:
        self.p.stdin.write((self.blank if m is None else m).tobytes())

    def close(self) -> None:
        self.p.stdin.close()
        if self.p.wait() != 0:
            raise SystemExit("error: ffmpeg failed writing the mask video")


# --------------------------------------------------------------------------
# tracking
# --------------------------------------------------------------------------
def _csrt():
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    return cv2.legacy.TrackerCSRT_create()


def _run(frames: list[np.ndarray], box: tuple[int, int, int, int]) -> list[tuple | None]:
    tr = _csrt()
    tr.init(frames[0], tuple(int(v) for v in box))
    out: list[tuple | None] = [tuple(box)]
    for fr in frames[1:]:
        ok, b = tr.update(fr)
        out.append(tuple(b) if ok else None)
    return out


def _smooth(vals: np.ndarray, win: int) -> np.ndarray:
    if len(vals) < 3 or win < 2:
        return vals
    win = min(win, len(vals) - (1 - len(vals) % 2))
    k = np.ones(win) / win
    pad = win // 2
    padded = np.pad(vals, (pad, pad), mode="edge")
    return np.convolve(padded, k, mode="valid")[: len(vals)]


def track(video: str | Path, at: float, box: list[float], t0: float, t1: float,
          work_width: int = 540, smooth: int = 7) -> dict:
    """Follow `box` ([x, y, w, h] in video pixels at time `at`) from t0 to t1.

    Returns {"fps", "frames": {frame_index: [cx, cy, w, h]}, "lost": fraction of frames where the tracker
    lost the object (the last good position is held there)}. Positions are smoothed with a centred moving
    average so a caption riding on them doesn't jitter."""
    info = video_info(video)
    fps, n = info["fps"], info["n"]
    s = min(1.0, work_width / info["w"])
    ia = min(max(int(round(at * fps)), 0), n - 1)
    i0 = min(max(int(round(t0 * fps)), 0), ia)
    i1 = max(min(int(round(t1 * fps)), n - 1), ia)
    frames = [f for _, f in read_frames(video, i0, i1, s)]
    if not frames:
        raise SystemExit(f"error: no frames to track in {video} between {t0}s and {t1}s")
    b = [v * s for v in box]
    k = ia - i0
    fwd = _run(frames[k:], b)
    bwd = _run(frames[: k + 1][::-1], b)[::-1] if k > 0 else [tuple(b)]
    raw = bwd[:-1] + fwd
    lost = sum(1 for r in raw if r is None) / len(raw)
    # fill gaps by holding the nearest good value (towards the key frame)
    filled: list[tuple] = []
    last = tuple(b)
    for j in range(k, len(raw)):
        last = raw[j] or last
        raw[j] = last
    last = tuple(b)
    for j in range(k, -1, -1):
        last = raw[j] or last
        raw[j] = last
    arr = np.array(raw, dtype=float) / s
    cx = _smooth(arr[:, 0] + arr[:, 2] / 2, smooth)
    cy = _smooth(arr[:, 1] + arr[:, 3] / 2, smooth)
    w = _smooth(arr[:, 2], smooth * 2 + 1)
    h = _smooth(arr[:, 3], smooth * 2 + 1)
    for j in range(len(raw)):
        filled.append([round(cx[j], 1), round(cy[j], 1), round(w[j], 1), round(h[j], 1)])
    return {"fps": fps, "lost": round(lost, 3), "frames": {i0 + j: v for j, v in enumerate(filled)}}


def position_at(tr: dict, t: float) -> list[float]:
    """Tracked [cx, cy, w, h] at time t (clamped to the tracked range)."""
    fr = tr["frames"]
    keys = sorted(fr)
    i = min(max(int(round(t * tr["fps"])), keys[0]), keys[-1])
    return fr[i]


# --------------------------------------------------------------------------
# segmentation / detection
# --------------------------------------------------------------------------
class Vision:
    """Lazy-loaded MediaPipe models. All inputs are BGR frames (OpenCV); masks come back float32 0..1."""

    def __init__(self, model_dir: Path = MODEL_DIR):
        self.dir = Path(model_dir)
        self._people = self._touch = self._det = None
        try:
            import mediapipe  # noqa: F401
        except ImportError as e:
            raise SystemExit("error: mediapipe is not installed - run: bash tools/setup_vision.sh") from e
        import atexit
        atexit.register(self.close)

    def close(self) -> None:
        """Release the models (MediaPipe crashes noisily if this is left to interpreter shutdown)."""
        for name in ("_people", "_touch", "_det"):
            m = getattr(self, name)
            if m is not None:
                try:
                    m.close()
                except Exception:
                    pass
                setattr(self, name, None)

    def _model(self, name: str) -> str:
        p = self.dir / name
        if not p.exists():
            raise SystemExit(f"error: model {p} missing - run: bash tools/setup_vision.sh")
        return str(p)

    @staticmethod
    def _img(frame):
        import mediapipe as mp
        return mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))

    def _seg_people(self, frame):
        from mediapipe.tasks.python import BaseOptions, vision
        if self._people is None:
            self._people = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
                base_options=BaseOptions(model_asset_path=self._model("selfie_multiclass_256x256.tflite")),
                output_confidence_masks=True))
        r = self._people.segment(self._img(frame))
        return [m.numpy_view().reshape(frame.shape[:2]) for m in r.confidence_masks]

    def people(self, frame: np.ndarray) -> np.ndarray:
        """Every person in the frame (hair, skin, clothes, gear)."""
        bg = self._seg_people(frame)[0]
        return np.clip(1.0 - bg, 0, 1).astype(np.float32)

    def person_at(self, frame: np.ndarray, box: list[float]) -> np.ndarray:
        """Only the person (or people blob) overlapping `box` [cx, cy, w, h] - cleaner than thing() for people,
        because the selfie model never bleeds into the background the way the point segmenter can."""
        m = self.people(frame)
        lab_n, lab = cv2.connectedComponents((m > 0.5).astype(np.uint8))
        cx, cy, w, h = box
        x0, x1 = int(max(0, cx - w / 2)), int(min(frame.shape[1], cx + w / 2))
        y0, y1 = int(max(0, cy - h / 2)), int(min(frame.shape[0], cy + h / 2))
        ids, counts = np.unique(lab[y0:y1, x0:x1], return_counts=True)
        keep = [i for i, c in zip(ids, counts) if i != 0 and c > 0.05 * max(1, (x1 - x0) * (y1 - y0))]
        return np.where(np.isin(lab, keep), m, 0).astype(np.float32)

    def faces(self, frame: np.ndarray, min_frac: float = 0.0015) -> list[list[int]]:
        """Face boxes [x, y, w, h], biggest first (face-skin class, connected components)."""
        face = (self._seg_people(frame)[3] > 0.5).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(face)
        area = frame.shape[0] * frame.shape[1]
        boxes = [list(map(int, stats[i, :4])) for i in range(1, n) if stats[i, 4] > min_frac * area]
        return sorted(boxes, key=lambda b: -b[2] * b[3])

    def thing(self, frame: np.ndarray, x: float, y: float) -> np.ndarray:
        """The single object under pixel (x, y)."""
        from mediapipe.tasks.python import BaseOptions, vision
        from mediapipe.tasks.python.components.containers import keypoint as kp
        if self._touch is None:
            self._touch = vision.InteractiveSegmenterLegacy.create_from_options(
                vision.InteractiveSegmenterLegacyOptions(
                    base_options=BaseOptions(model_asset_path=self._model("magic_touch.tflite")),
                    output_category_mask=False))
        R = vision.InteractiveSegmenterLegacyRegionOfInterest
        h, w = frame.shape[:2]
        roi = R(format=R.Format.KEYPOINT, keypoint=kp.NormalizedKeypoint(
            x=float(np.clip(x / w, 0, 1)), y=float(np.clip(y / h, 0, 1))))
        m = self._touch.segment(self._img(frame), roi).confidence_masks[0].numpy_view()
        return m.reshape(h, w).astype(np.float32)

    def detect(self, frame: np.ndarray, min_score: float = 0.35, max_results: int = 12) -> list[dict]:
        from mediapipe.tasks.python import BaseOptions, vision
        if self._det is None:
            self._det = vision.ObjectDetector.create_from_options(vision.ObjectDetectorOptions(
                base_options=BaseOptions(model_asset_path=self._model("efficientdet_lite2.tflite")),
                score_threshold=min_score, max_results=max_results))
        out = []
        for d in self._det.detect(self._img(frame)).detections:
            c = d.categories[0]
            b = d.bounding_box
            out.append({"label": c.category_name, "score": round(c.score, 2),
                        "box": [int(b.origin_x), int(b.origin_y), int(b.width), int(b.height)]})
        return out


def clean_mask(m: np.ndarray, feather: int = 3, grow: int = 2) -> np.ndarray:
    """Binary-ish mask -> 8-bit alpha with a slightly grown, feathered edge (hides halos at the cut)."""
    a = (m > 0.5).astype(np.uint8) * 255
    if grow:
        a = cv2.dilate(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    # keep only blobs of a meaningful size (drops speckles that would punch holes in the caption)
    n, lab, st, _ = cv2.connectedComponentsWithStats(a)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, 4] > 0.002 * a.size
    a = np.where(keep[lab], 255, 0).astype(np.uint8)
    if feather:
        a = cv2.GaussianBlur(a, (2 * feather + 1, 2 * feather + 1), 0)
    return a
