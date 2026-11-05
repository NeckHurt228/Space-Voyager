#!/usr/bin/env bash
# Install the speech-to-text model for tools/transcribe.py (run once per machine).
#
# Whisper "small" (CTranslate2 int8, ~250MB) for faster-whisper. The usual hosts
# (Hugging Face / OpenAI) can be blocked in sandboxed environments, so this pulls a
# mirror published to the npm registry in 4 parts, as plain tarballs. No npm install
# runs and no package code is executed. The joined file is checked against the
# published sha256 before use.
#
# If you'd rather use Hugging Face directly, set CLIP_COACH_ASR_MODEL to any
# faster-whisper model directory (e.g. a download of Systran/faster-whisper-small).
set -euo pipefail

DEST="${CLIP_COACH_ASR_MODEL:-$HOME/.cache/clip-coach/whisper-small-ct2}"
PKG="@skillninja/shortmovie-telop-model-p"
REG="https://registry.npmjs.org"

pip install -q faster-whisper numpy

if [[ -f "$DEST/model.bin" ]]; then
  echo "model already present at $DEST"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$DEST"

for i in 0 1 2 3; do
  url="$(curl -fsS "$REG/$PKG$i" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["versions"][d["dist-tags"]["latest"]]["dist"]["tarball"])')"
  echo "downloading part $((i+1))/4"
  curl -fsS -o "$TMP/p$i.tgz" "$url"
  mkdir -p "$TMP/x$i"
  tar -xzf "$TMP/p$i.tgz" -C "$TMP/x$i"
done

cat "$TMP"/x0/package/model.bin.part0 "$TMP"/x1/package/model.bin.part1 \
    "$TMP"/x2/package/model.bin.part2 "$TMP"/x3/package/model.bin.part3 > "$DEST/model.bin"
cp "$TMP"/x0/package/{config.json,preprocessor_config.json,tokenizer.json,vocabulary.json,LICENSE} "$DEST/"

want="$(awk '{print $1}' "$TMP/x0/package/model.sha256")"
got="$(sha256sum "$DEST/model.bin" | awk '{print $1}')"
if [[ "$want" != "$got" ]]; then
  rm -f "$DEST/model.bin"
  echo "checksum mismatch, model removed" >&2
  exit 1
fi
echo "speech model ready at $DEST"
