// SystemUpdate — "update 1 of 47". A fake firmware installer the player
// rage-taps through. The joke only lands if the setback is FELT: partway
// through, the bar snaps back near 1% and has to be re-earned, and that
// drop animates rather than jump-cutting (docs/design-system.md §6 —
// "avoid anything meaningful that resolves in under 200ms").
//
// Motion rule (§6 motion engineering, binding): the fill animates
// `transform: scaleX()` with `transform-origin: left` (set in
// SystemUpdate.css), never `width` — width forces layout and paint on
// every frame. This bar only changes value at discrete tap events (not
// continuously against elapsed time, unlike StickDrift's reticle), so a
// CSS `transition` on that transform is the right tool — compositor-only,
// no hand-rolled rAF loop needed for it. See shell/Install.tsx for the
// rAF-driven case, which is the pattern for genuinely continuous motion.
//
// Server authority: this component reports honest telemetry only.
// `inputCount` counts discrete presses/clicks — held-key OS auto-repeat
// is filtered via `event.repeat` so the number can't drift past the
// server's per-input timing floor (server/xxvi/games/verify.py,
// MIN_MS_PER_INPUT = 60ms/input). The server decides pass/fail, not this
// component; on completion this only reports what happened.

import { useCallback, useEffect, useRef, useState } from "react";
import type { GameProps } from "./types";
import "./SystemUpdate.css";

/** Fractions of taps_required at which the bar snaps back. Two marks so
 *  even a short segment (taps_required as low as 3, per the harness's own
 *  test) still lands at least one setback before completion, and a long
 *  one (35, per config/run.example.yaml) lands two. */
const SETBACK_FRACTIONS = [0.4, 0.75] as const;

/** The bar never reads exactly 0% after a setback — it reads "1%". That's
 *  the joke: "update 1 of 47" always seems to start over from scratch. */
const SETBACK_FLOOR_PERCENT = 1;

/** How long the "connection interrupted" flash stays up before fading
 *  back out. Long enough to read on a 30fps capture. */
const SETBACK_FLASH_MS = 640;

export function SystemUpdate({ params, onFinish }: GameProps) {
  const required = Math.max(1, Math.trunc(params.taps_required ?? 20));

  const [taps, setTaps] = useState(0);
  const [percent, setPercent] = useState(0);
  const [setback, setSetback] = useState(false);

  const tapsRef = useRef(0);
  const firedSetbacks = useRef<Set<number>>(new Set());
  const floorTaps = useRef(0);
  const floorPercent = useRef(0);
  const inputCount = useRef(0);
  const finished = useRef(false);
  const started = useRef(performance.now());
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (flashTimer.current) clearTimeout(flashTimer.current);
    },
    [],
  );

  const tap = useCallback(() => {
    if (finished.current) return;
    inputCount.current += 1;
    const next = tapsRef.current + 1;
    tapsRef.current = next;

    // Completion always wins over a setback mark landing on the same tap
    // — otherwise the very last tap could coincide with a setback
    // threshold and the run would never finish.
    if (next >= required) {
      finished.current = true;
      setTaps(next);
      setPercent(100);
      onFinish({
        passed: true,
        durationMs: Math.round(performance.now() - started.current),
        inputCount: inputCount.current,
        score: next,
        sequence: [],
      });
      return;
    }

    const fraction = next / required;
    const setbackIndex = SETBACK_FRACTIONS.findIndex(
      (mark, index) => fraction >= mark && !firedSetbacks.current.has(index),
    );

    if (setbackIndex !== -1) {
      firedSetbacks.current.add(setbackIndex);
      floorTaps.current = next;
      floorPercent.current = SETBACK_FLOOR_PERCENT;
      setTaps(next);
      setPercent(SETBACK_FLOOR_PERCENT);
      setSetback(true);
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setSetback(false), SETBACK_FLASH_MS);
      return;
    }

    setTaps(next);
    const span = Math.max(1, required - floorTaps.current);
    const progressed = next - floorTaps.current;
    const climbed = Math.round(
      floorPercent.current + (progressed / span) * (99 - floorPercent.current),
    );
    setPercent(Math.min(99, Math.max(SETBACK_FLOOR_PERCENT, climbed)));
  }, [required, onFinish]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.repeat) return; // OS auto-repeat isn't a distinct human tap
      if (event.code === "Space" || event.code === "Enter") {
        event.preventDefault();
        tap();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tap]);

  return (
    <section className={`game game--update${setback ? " game--update-setback" : ""}`}>
      <p className="label game__eyebrow">system software</p>
      <h2 className="update__title">update 1 of 47</h2>
      <div className="update__bar">
        <div className="update__fill" style={{ transform: `scaleX(${percent / 100})` }} />
      </div>
      <p aria-label="progress" className="update__percent">
        {percent}%
      </p>
      <button className="update__button" onClick={tap} autoFocus>
        install <span className="update__key">(space)</span>
      </button>
      <p className="update__flash" aria-hidden="true">
        connection interrupted — resyncing
      </p>
      <p className="update__count">
        {taps} / {required}
      </p>
    </section>
  );
}
