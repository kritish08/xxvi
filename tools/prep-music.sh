#!/usr/bin/env bash
# Turn raw generated tracks into seamless, level-matched loops for the music
# bed (web/src/lib/audio.ts). Run once per new source track; the output is
# committed, so the app never does any of this at runtime.
#
# WHY THE CROSSFADE IS BAKED IN, NOT DONE IN THE BROWSER: the bed plays
# through an AudioBufferSourceNode with `loop = true`, which butt-joins the
# end of the buffer to its start. Unless the waveform happens to match across
# that seam it clicks, once per loop, forever. WebAudio has no crossfading
# loop primitive, and doing it live means two sources and a gain schedule
# per track. Preparing the file solves it once, offline, verifiably.
#
# The standard crossfade-loop construction: take a body of length L starting
# at S, plus the C seconds immediately following it. Crossfade that tail into
# the body's own head. The result is exactly L long and its end now flows
# into its start, because the start IS the end, blended.
#
#   ffmpeg acrossfade(A, B, d) = A[0 : len(A)-d] + xfade(A_tail, B_head) + B[d :]
#   with A = tail (length C) and B = body (length L), that is
#   xfade(tail, body_head) + body[C:L]  ->  length L, seam-free.
#
# Regions were chosen from a per-second loudness analysis of each source:
# skip the intro ramp, stop before the outro fade, sit in the fullest part.
set -euo pipefail

SRC="${1:-$HOME/Downloads}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/web/public/audio/music"
XFADE=4                 # seconds; long enough to hide the seam in ambient material
TARGET_LUFS=-15         # all four matched; see NOMINAL_DB in web/src/lib/audio.ts

mkdir -p "$OUT"

# name  start  body-length   (start + length + XFADE must fit the source)
prep() {
  local name=$1 start=$2 len=$3
  local src="$SRC/$name.mp3" dst="$OUT/$name.mp3"
  [ -f "$src" ] || { echo "!! missing $src"; return 1; }

  # 1. Extract the body and the tail as separate files, then crossfade the
  #    tail into the body's head.
  #
  #    Deliberately two passes rather than one filtergraph: two `atrim`
  #    filters cannot both read `[0:a]` (it needs an explicit `asplit`, and
  #    even then acrossfade has to buffer one branch until the other
  #    finishes). The single-graph version silently produced a zero-byte
  #    file -- "Output file is empty, nothing was encoded" -- so this is
  #    written the boring way on purpose. WAV intermediates, so the loop
  #    seam is never built out of twice-lossy material.
  ffmpeg -v error -y -ss "$start" -t "$len" -i "$src" \
    -ac 2 -ar 44100 -c:a pcm_s16le "/tmp/prep-$name-body.wav"
  ffmpeg -v error -y -ss "$((start+len))" -t "$XFADE" -i "$src" \
    -ac 2 -ar 44100 -c:a pcm_s16le "/tmp/prep-$name-tail.wav"
  ffmpeg -v error -y -i "/tmp/prep-$name-tail.wav" -i "/tmp/prep-$name-body.wav" \
    -filter_complex "[0:a][1:a]acrossfade=d=$XFADE:c1=tri:c2=tri[out]" \
    -map "[out]" -c:a pcm_s16le "/tmp/prep-$name.wav"
  rm -f "/tmp/prep-$name-body.wav" "/tmp/prep-$name-tail.wav"
  ffmpeg -v error -y -i "/tmp/prep-$name.wav" \
    -c:a libmp3lame -b:a 160k "/tmp/prep-$name.mp3"
  rm -f "/tmp/prep-$name.wav"

  # 2. Measure, then apply a single static gain. Deliberately NOT loudnorm's
  #    dynamic mode: it pumps on sparse ambient material, which is most of
  #    what these tracks are.
  #    ebur128 prints its summary at the default log level, so this step must
  #    NOT pass `-v error` -- doing so silently yields an empty measurement.
  local lufs gain
  lufs=$(ffmpeg -i "/tmp/prep-$name.mp3" -af ebur128 -f null - 2>&1 \
         | awk '/^ *I: +-?[0-9]/ {print $2}' | tail -1)
  [ -n "$lufs" ] || { echo "!! could not measure loudness for $name"; return 1; }
  gain=$(python3 -c "print(f'{$TARGET_LUFS - ($lufs):.2f}')")
  ffmpeg -v error -y -i "/tmp/prep-$name.mp3" -af "volume=${gain}dB" \
    -c:a libmp3lame -b:a 160k "$dst"
  rm -f "/tmp/prep-$name.mp3"

  printf '%-9s %5.1fs loop  (from %3ds)  %6s LUFS -> %-6s gain %+sdB\n' \
    "$name" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$dst")" \
    "$start" "$lufs" "$TARGET_LUFS" "$gain"
}

# menu    — 20s intro ramp, outro drops at 110s.  Full texture 16-110.
prep menu    20  80
# tense   — deliberately starts at 60s: the track only reaches its best
#           material there, and it falls away again after ~120s.
prep tense   60  56
# game    — dead flat from 10s to 150s, so take the longest body of the four.
prep game    15 115
# triumph — peaks 70-90s, long outro fade from 130s.
prep triumph 62  60
