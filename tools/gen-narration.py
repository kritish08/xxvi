#!/usr/bin/env python3
"""Generate the narration audio. Run once at authoring time; the mp3s are
committed and the run never calls an API.

COMMITTED ON PURPOSE. The first version of this script was not, so the six
lines it produced could not be re-cut, re-voiced, or even read back -- the
only record of what the console says was inside the audio itself. The script
is the source of truth for the words; the mp3s are build output.

MODEL: gpt-audio-1.5, not the tts-* family. The shipped lines were made with
gpt-4o-mini-tts using default delivery and no steering, which is exactly why
they came out robotic. gpt-audio-1.5 is a speech model driven by an actual
system prompt, so the direction below does real work.

LENGTH BUDGETS ARE HARD CONSTRAINTS, not preferences:
  boot       Boot.tsx holds BOOT_HOLD_MS = 2200ms before advancing.
  install-*  Install.tsx's SUBTITLES land 1.69s apart and the install runs
             6.5s total; install-1 and install-3 are 52% apart, so each has
             ~3.3s before the next beat. This is why only two of the four
             install beats are narrated at all.
Every generated file is measured below and the script fails loudly if a line
overruns its budget, rather than shipping audio that gets cut off.

Usage:  OPENAI_API_KEY=sk-... python3 tools/gen-narration.py
"""
import base64
import json
import os
import pathlib
import subprocess
import sys

OUT = pathlib.Path(__file__).resolve().parent.parent / "web/public/audio/narration"

MODEL = "gpt-audio-1.5"
VOICE = "cedar"

# The delivery direction. This is the whole difference between a system voice
# and a screen reader, and the previous generation had none of it.
DIRECTION = (
    "You are the system voice of a premium game console. Read the line "
    "exactly as written and add nothing -- no greeting, no commentary, no "
    "acknowledgement. Delivery: deadpan and dry, warm underneath, unhurried, "
    "close-mic'd and intimate, as if speaking quietly to one person in a "
    "dark room at midnight. Never bright, never chirpy, never an announcer. "
    "Let the full stops breathe. Underplay every line -- the humour is in "
    "how flat it is."
)

# key -> (line, max_seconds). See the length-budget note above.
LINES: dict[str, tuple[str, float]] = {
    # Boot.tsx's BOOT_HOLD_MS, which was raised to 3200ms to fit this line
    # rather than the line being cut to fit it.
    "boot": ("XXVI. Powering on.", 3.2),
    # Mirrors Install.tsx's on-screen subtitle "copying 20 years…". Budget is
    # the real gap to the next narrated beat: INSTALL_MS 6500 x 52% = 3.38s.
    # Deliberately just the subtitle. The longer version ("...This takes a
    # moment.") measured 4.30s against a 3.38s slot -- past what pacing can
    # close without sounding rushed, so the line got shorter rather than the
    # delivery getting faster.
    "install-1": ("Copying twenty years.", 3.38),
    # Mirrors "verifying trauma…". This is the LAST narrated line of the
    # install, so its constraint is not "fits inside the install screen" --
    # it is "does not collide with another line", and nothing follows it.
    # Running a little past the install and finishing over the how-to-play
    # screen (which waits for him) reads as continuity, not as a bug. The
    # ceiling is generous for that reason; it exists to catch a runaway
    # generation, not to keep the line inside a screen it need not fit.
    "install-3": ("Verifying trauma. Most of it checks out.", 5.0),
    # The platinum. No length budget worth enforcing -- it plays over a
    # screen that waits for him.
    "platinum": ("Platinum. Twenty years, and you cleared it on the "
                 "first night. Happy birthday, Aman.", 12.0),
}


def generate(key: str, line: str, api_key: str) -> pathlib.Path:
    payload = {
        "model": MODEL,
        "modalities": ["audio", "text"],
        "audio": {"voice": VOICE, "format": "mp3"},
        "messages": [
            {"role": "system", "content": DIRECTION},
            {"role": "user", "content": f'Read this line: "{line}"'},
        ],
    }
    result = subprocess.run(
        ["curl", "-s", "https://api.openai.com/v1/chat/completions",
         "-H", f"Authorization: Bearer {api_key}",
         "-H", "content-type: application/json",
         "-d", json.dumps(payload)],
        capture_output=True, text=True, check=True,
    )
    body = json.loads(result.stdout)
    if "error" in body:
        raise SystemExit(f"{key}: API error: {body['error'].get('message')}")
    audio = body["choices"][0]["message"].get("audio")
    if not audio:
        raise SystemExit(f"{key}: response carried no audio")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{key}.mp3"
    raw = OUT / f".{key}.raw.mp3"
    raw.write_bytes(base64.b64decode(audio["data"]))

    # The model pads generously at both ends -- "XXVI. Powering on." came
    # back as 5.02s of which most was silence. Trim both ends, keeping a
    # short lead-in so the first consonant is never clipped. Measuring
    # before this ran would have blamed the writing for a padding problem.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(raw),
         "-af", "silenceremove=start_periods=1:start_silence=0.08:"
                "start_threshold=-45dB:detection=peak,"
                "areverse,"
                "silenceremove=start_periods=1:start_silence=0.15:"
                "start_threshold=-45dB:detection=peak,"
                "areverse",
         "-c:a", "libmp3lame", "-b:a", "128k", str(path)],
        check=True,
    )
    raw.unlink()
    return path


# Generated pacing varies run to run by ~20% for the same words -- the same
# boot line came back at 2.78s, 2.83s and 3.24s across three generations.
# Regenerating until a line happens to fit its budget is a lottery, not a
# build step, so an overrun is corrected deterministically instead: atempo
# time-compresses without shifting pitch, and a few percent is inaudible.
# Capped, because past this it starts to sound rushed and the fix becomes
# worse than the problem -- beyond the cap the line itself is too long and
# the script says so.
MAX_TEMPO = 1.18


def fit_to_budget(path: pathlib.Path, seconds: float, budget: float) -> float:
    if seconds <= budget:
        return seconds
    tempo = seconds / budget
    if tempo > MAX_TEMPO:
        return seconds  # unfixable by pacing; caller reports it
    # Aim slightly inside the budget so measurement jitter cannot push it back
    # over, then re-measure rather than trusting the arithmetic.
    tempo = min(MAX_TEMPO, tempo * 1.02)
    temporary = path.with_suffix(".fit.mp3")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(path),
         "-af", f"atempo={tempo:.4f}", "-c:a", "libmp3lame", "-b:a", "128k",
         str(temporary)],
        check=True,
    )
    temporary.replace(path)
    return duration(path)


def duration(path: pathlib.Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("set OPENAI_API_KEY")

    overruns = []
    for key, (line, budget) in LINES.items():
        path = generate(key, line, api_key)
        raw_seconds = duration(path)
        seconds = fit_to_budget(path, raw_seconds, budget)
        fits = seconds <= budget
        adjusted = "" if seconds == raw_seconds else f" (from {raw_seconds:.2f}s)"
        print(f"{'ok  ' if fits else 'LONG'} {key:11} {seconds:5.2f}s{adjusted:16} "
              f"budget {budget:4.1f}s  {path.stat().st_size:>7,}B  \"{line}\"")
        if not fits:
            overruns.append(
                f"{key}: {seconds:.2f}s against a {budget:.1f}s budget, and "
                f"more than {MAX_TEMPO:.0%} pacing would be needed to close it"
            )

    if overruns:
        print("\nThese would be cut off on screen -- shorten the line and rerun:")
        for problem in overruns:
            print(f"  - {problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
