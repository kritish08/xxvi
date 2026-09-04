// Trophy Run — a rapid QTE chain over the face buttons (△ ○ ✕ □). The Act
// II instance (segment 8: 10 prompts, 800ms window, see config/run.yaml) is
// the run's climax — the last thing standing between him and the platinum
// trophy, so this component gets the same care as the trophy pop itself.
//
// Server authority: `xxvi/games/verify.py`'s `trophy_run` branch checks
// only `score == prompts` and an input-count band
// (`prompts <= input_count <= prompts * 3`) — never `sequence`. The "* 3"
// headroom is explained in verify.py's own comment as slack for
// "missed/retried attempts within the window", which is why THIS component
// lets a wrong face be re-tried until the window actually closes, rather
// than ending the run on the first miss — the only reading consistent with
// both that comment and this mechanic's own brief ("Miss the window and
// the run ends," not "miss a press").
//
// Sequence generation mirrors SimonSays.tsx's `simonSequence` (itself a
// mirror of server/xxvi/games/seeds.py) rather than importing it: verify.py
// never checks `sequence` for `trophy_run` at all, so there is no shared
// cross-language vector to keep the two in step with the way Simon's
// `web/tests/seq.test.ts` does — this only has to be *displayed*
// deterministically per seed, and a local copy keeps that fact visible at
// the definition site instead of implying a contract that doesn't exist.
//
// Motion: the per-prompt countdown bar animates `transform: scaleX()` via
// a single rAF loop (lib/motion.ts's `rafLoop`), written straight into the
// DOM through a ref — no per-frame `setState` — the same pattern
// shell/Install.tsx already uses for its progress bar.

import { useCallback, useEffect, useRef, useState } from "react";
import { useGamepadFace } from "../lib/gamepad";
import { FACE_GLYPHS, FACE_KEY_LABELS, FACE_LABELS, faceFromEvent } from "../lib/input";
import { rafLoop } from "../lib/motion";
import type { GameProps } from "./types";
import "./game.css";
import "./trophyrun.css";

/** Mirrors server/xxvi/games/seeds.py::simon_sequence byte-for-byte (see
 *  module comment for why this is a local copy rather than an import from
 *  ./SimonSays). */
async function promptSequence(seed: string, length: number): Promise<number[]> {
  const out: number[] = [];
  let counter = 0;
  while (out.length < length) {
    const data = new TextEncoder().encode(`${seed}:${counter}`);
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", data));
    for (const byte of digest) out.push(byte % FACE_GLYPHS.length);
    counter += 1;
  }
  return out.slice(0, length);
}

export function TrophyRun({ seed, params, onFinish }: GameProps) {
  const total = Math.max(1, Math.trunc(params.prompts ?? 6));
  const windowMs = Math.max(1, Math.trunc(params.window_ms ?? 1200));

  const [prompts, setPrompts] = useState<number[]>([]);
  const [index, setIndex] = useState(0);
  // Bumped to restart the current prompt's window after a life is lost.
  const [windowNonce, setWindowNonce] = useState(0);
  const [missPulse, setMissPulse] = useState(0); // bumped on a wrong-but-not-fatal press, to retrigger a CSS pulse
  // Lives. A missed WINDOW used to end the segment outright, which made the
  // 800ms window on the final run brutal: one blink and eight correct hits
  // were gone. Wrong presses were always free; it was only ever the clock
  // that could kill, and now the clock costs a life instead.
  const allowance = Math.max(1, Math.trunc(params.lives ?? 3));
  const [livesLeft, setLivesLeft] = useState(allowance);
  const livesRef = useRef(allowance);
  const hits = useRef(0);
  const inputs = useRef(0);
  const done = useRef(false);
  const started = useRef(Date.now());
  const barRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void promptSequence(seed, total).then((sequence) => {
      if (!cancelled) setPrompts(sequence);
    });
    return () => {
      cancelled = true;
    };
  }, [seed, total]);

  const finish = useCallback(
    (passed: boolean) => {
      if (done.current) return;
      done.current = true;
      onFinish({
        passed,
        durationMs: Date.now() - started.current,
        inputCount: inputs.current,
        score: hits.current,
        sequence: prompts,
      });
    },
    [onFinish, prompts],
  );

  // The deadline for the CURRENT prompt only. Resets every time `index`
  // advances (a correct press) — each prompt gets its own full window.
  useEffect(() => {
    if (!prompts.length || done.current) return;
    if (index >= prompts.length) {
      finish(hits.current >= total);
      return;
    }
    const timer = setTimeout(() => {
      // Out of time on this prompt. Spend a life and give the SAME prompt a
      // fresh window; only the last one ends the segment.
      const remaining = livesRef.current - 1;
      livesRef.current = remaining;
      setLivesLeft(remaining);
      if (remaining <= 0) {
        finish(false);
        return;
      }
      setMissPulse((n) => n + 1);
      setWindowNonce((n) => n + 1);
    }, windowMs);
    return () => clearTimeout(timer);
  }, [prompts, index, windowMs, total, finish, windowNonce]);

  // The visual countdown — transform only, one rAF loop, no per-frame
  // setState (design-system.md §6, "Motion engineering").
  useEffect(() => {
    if (!prompts.length || index >= prompts.length || done.current) return;
    const bar = barRef.current;
    if (bar) bar.style.transform = "scaleX(1)";
    const stop = rafLoop((elapsedMs) => {
      const fraction = Math.max(0, 1 - elapsedMs / windowMs);
      if (bar) bar.style.transform = `scaleX(${fraction})`;
    });
    return stop;
  }, [prompts, index, windowMs, windowNonce]);

  const press = useCallback(
    (face: number) => {
      if (done.current || index >= prompts.length) return;
      inputs.current += 1;
      if (face !== prompts[index]) {
        // A miss inside the window is a retry, not a fail (verify.py's
        // input-count band exists exactly to allow this) — flash and let
        // the deadline timer above be the only thing that can end the run.
        setMissPulse((n) => n + 1);
        return;
      }
      hits.current += 1;
      setIndex((n) => n + 1);
    },
    [index, prompts],
  );

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const face = faceFromEvent(event);
      if (face !== null) {
        event.preventDefault();
        press(face);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [press]);

  // Optional, additive: a controller reports the same `press(face)` the
  // keyboard does, edge-triggered by the hook itself so a held pad button
  // can't spam presses (see lib/gamepad.ts). Keyboard remains the
  // supported path — this is pure enhancement, never required for a game
  // to be completable (docs/design-system.md §9, task 23 brief).
  const padConnected = useGamepadFace(press);

  const current = prompts[index];

  return (
    <section className="game game--trophyrun">
      <div className="label game__label">segment · trophy run</div>
      <p className="game__progress label">
        {hits.current} / {total}
      </p>
      <p className="trophyrun__lives label">
        <span>lives</span>
        <span className="trophyrun__pips">
          {Array.from({ length: allowance }, (_, i) => (
            <span key={i} className={`trophyrun__pip${i < livesLeft ? " is-lit" : ""}`} />
          ))}
        </span>
      </p>
      <p className="game__hint label" aria-hidden={!padConnected} data-visible={padConnected}>
        controller detected
      </p>

      <div className="trophyrun__stage">
        {current !== undefined && (
          <button
            key={index}
            type="button"
            className={`trophyrun__prompt${missPulse ? " is-missed" : ""}`}
            aria-label={`prompt ${FACE_LABELS[current]}`}
            onClick={() => press(current)}
            onAnimationEnd={() => setMissPulse(0)}
          >
            {FACE_GLYPHS[current]}
          </button>
        )}
        <div className="trophyrun__timer">
          <div className="trophyrun__timer-fill" ref={barRef} />
        </div>
      </div>

      {/* Key mapping stays on screen throughout, matching every other
          face-input mechanic (§7, §9) — the glyph shown above says WHICH
          face, this says which key. */}
      <ul className="trophyrun__legend" aria-label="key mapping">
        {FACE_GLYPHS.map((glyph, face) => (
          <li key={face} className="trophyrun__legend-item">
            <span className="trophyrun__legend-glyph" aria-hidden="true">
              {glyph}
            </span>
            <span className="label">{FACE_KEY_LABELS[face]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
