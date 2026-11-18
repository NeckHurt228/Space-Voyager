#!/usr/bin/env bash
# Install the vision models + libraries used for tracking, masking, the scene probe and the
# reference study (tools/vision.py, tools/scene_probe.py, tools/study_reference.py). Run once per machine.
#
# Models are Google's public MediaPipe models (Apache 2.0) from storage.googleapis.com, checked
# against pinned sha256 sums. No model code runs at install time.
set -euo pipefail

DEST="${CLIP_COACH_VISION_MODELS:-$HOME/.cache/clip-coach/vision}"
BASE="https://storage.googleapis.com/mediapipe-models"

pip install -q mediapipe numpy pillow rapidocr-onnxruntime
# rapidocr pulls in plain opencv-python, which overwrites the contrib build (the CSRT tracker lives in
# contrib). Keep exactly one OpenCV: the contrib build mediapipe asks for.
if ! python3 -c "import cv2, sys; sys.exit(0 if hasattr(cv2, 'TrackerCSRT_create') else 1)" 2>/dev/null; then
  pip uninstall -y -q opencv-python opencv-python-headless opencv-contrib-python-headless >/dev/null 2>&1 || true
  CV="$(pip show opencv-contrib-python 2>/dev/null | awk '/^Version:/{print $2}')"
  pip install -q --force-reinstall --no-deps "opencv-contrib-python${CV:+==$CV}"
fi

# MediaPipe's tasks library needs EGL/GLES even on CPU
if ! ldconfig -p | grep -q "libEGL.so.1"; then
  if command -v apt-get >/dev/null; then
    SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"
    $SUDO apt-get install -y -q libegl1 libgles2 >/dev/null 2>&1 || { $SUDO apt-get update -q >/dev/null && $SUDO apt-get install -y -q libegl1 libgles2 >/dev/null; }
  else
    echo "warning: libEGL.so.1 not found; install your OS's libegl1 / libgles2 (mesa) packages" >&2
  fi
fi

mkdir -p "$DEST"
fetch() {  # name url sha256
  local f="$DEST/$1"
  if [[ -f "$f" ]] && [[ "$(sha256sum "$f" | awk '{print $1}')" == "$3" ]]; then return; fi
  echo "downloading $1"
  curl -fsSL -o "$f.part" "$2"
  if [[ "$(sha256sum "$f.part" | awk '{print $1}')" != "$3" ]]; then
    rm -f "$f.part"; echo "checksum mismatch for $1" >&2; exit 1
  fi
  mv "$f.part" "$f"
}
fetch selfie_multiclass_256x256.tflite "$BASE/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite" c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0
fetch magic_touch.tflite "$BASE/interactive_segmenter/magic_touch/float32/latest/magic_touch.tflite" e24338a717c1b7ad8d159666677ef400babb7f33b8ad60c4d96db4ecf694cd25
fetch efficientdet_lite2.tflite "$BASE/object_detector/efficientdet_lite2/float32/latest/efficientdet_lite2.tflite" ad2abbf2b4e10585e15176fd7b5ef03c28dda959ae26fc142549fdd1814db91d

python3 -c "import sys; sys.path.insert(0, 'tools'); import numpy as np, vision; v = vision.Vision(); v.people(np.zeros((64, 64, 3), np.uint8)); v.close(); print('vision models ready at', vision.MODEL_DIR)" 2>&1 | grep -v -E '^(W0000|I0000|INFO|WARNING)' || true
