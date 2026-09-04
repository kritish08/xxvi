// StickDrift — hold a reticle on target while it pulls off on its own.
// The DualSense joke, and the one game in this build where the FEEL of
// the motion is the entire experience (task-19 brief). Get this wrong —
// setInterval(50ms), setState every tick — and it's the single most
// motion-sensitive component in the app visibly stuttering.
//
// docs/design-system.md §6 "Motion engineering", binding, and how this
// file follows it:
//
//   - One requestAnimationFrame loop (lib/motion.ts's rafLoop), never
//     setInterval. setInterval(fn, 50) is 20fps and drifts against the
//     display's real refresh rate.
//   - The reticle's position is a pure function of ELAPSED TIME
//     (performance.now(), via rafLoop's elapsedMs), not an accumulator
//     incremented once per tick. drift(t) = sign * driftRate * t is
//     recomputed fresh every frame; it is never `offset += driftRate`.
//     The player's correction is the one quantity that has to integrate
//     real key-hold duration, and that's done the same way: by measuring
//     elapsed wall-clock time between a key's down/up timestamps, not by
//     stepping a counter once per frame or once per tick.
//   - The animated value is written straight to element.style.transform
//     via a ref inside the rAF callback. React re-renders only on
//     mount and on the terminal pass/fail call to onFinish — never once
//     per frame.
//   - translate3d, never left.
//
// Server authority (server/xxvi/games/verify.py): for the "drift"
// mechanic the server only checks `duration_ms >= configured duration`
// and `input_count > 0` — it does not re-simulate the reticle. That
// means the actual enforcement of "you drifted off and lost" happens
// here: failing early reports a duration_ms short of the requirement,
// which the server then rejects on its own. This component must not
// pretend to a later duration than it actually ran.

import { useEffect, useRef } from "react";
import { rafLoop } from "../lib/motion";
import type { GameProps } from "./types";
import "./StickDrift.css";

/** Reticle position lives on an abstract axis (-100..100), independent of
 *  any pixel measurement, so the physics never depend on layout. It is
 *  converted to a pixel offset for `translate3d` at render time by
 *  measuring the track's actual width — CSS `%` inside `translate3d` is
 *  relative to the *translated element's own* box, not its container, so
 *  it cannot be used directly to position the reticle within the track. */
const TRACK_LIMIT_UNITS = 100; // reaching either edge is an instant fail
const TARGET_ZONE_UNITS = 8; // the zone you must HOLD -- narrower now; keep .drift__zone in sync
/** The pull REVERSES on this cadence. Without it the whole mechanic was
 *  "hold one arrow key", which is why it never felt like anything: there
 *  was one correct input and no moment that demanded a reaction. */
const FLIP_SECONDS = 3.5;
/** How far off-centre a segment can begin. Seeded, so a given segment
 *  always opens the same way, but it no longer always opens dead centre
 *  with nothing happening. */
const MAX_START_OFFSET_UNITS = 55;
const BASE_DRIFT_UNITS_PER_SEC = 5; // unaided drift at drift_rate = 1.0
const CORRECTION_UNITS_PER_SEC = 20; // how hard a held arrow key pushes back
const RETICLE_PX = 40; // must match .drift__reticle's width in StickDrift.css

/** Deterministic per-seed pull direction, so a given segment always
 *  drifts the same way on replay (and so two players on the same seed
 *  get the same challenge) without needing a PRNG dependency here. */
function driftSign(seed: string): 1 | -1 {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  return hash % 2 === 0 ? 1 : -1;
}

/** Where the reticle starts, from the same seed. Deterministic per segment.
 *  Exported so tests can choose a seed with a known opening position rather
 *  than assuming every segment still begins dead centre. */
export function startOffset(seed: string): number {
  let hash = 7;
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 131 + seed.charCodeAt(i)) | 0;
  const unit = ((hash >>> 0) % 2001) / 1000 - 1; // -1..1
  return unit * MAX_START_OFFSET_UNITS;
}

/** Drift displacement at elapsed time `t` seconds, with the pull reversing
 *  every FLIP_SECONDS. Still a pure closed-form function of elapsed time,
 *  never a per-frame accumulator (design-system.md §6) -- the alternating
 *  segments are summed analytically rather than stepped. */
function driftAt(t: number, sign: 1 | -1, unitsPerSecond: number): number {
  const k = Math.floor(t / FLIP_SECONDS);
  // Completed whole segments alternate and cancel in pairs: the running
  // sum of (-1)^j for j < k is 1 when k is odd and 0 when k is even.
  const completed = k % 2 === 1 ? unitsPerSecond * FLIP_SECONDS : 0;
  const partial = (k % 2 === 0 ? 1 : -1) * unitsPerSecond * (t - k * FLIP_SECONDS);
  return sign * (completed + partial);
}

export function StickDrift({ seed, params, onFinish }: GameProps) {
  const duration = Math.max(1, Math.trunc(params.duration_ms ?? 20000));
  const driftRate = params.drift_rate ?? 1;
  const sign = useRef(driftSign(seed));

  const trackRef = useRef<HTMLDivElement>(null);
  const reticleRef = useRef<HTMLDivElement>(null);
  const trackHalfPx = useRef(0);

  // Held-key state: a start timestamp (elapsed ms) while a direction is
  // currently held, plus a running total already banked on release. The
  // in-progress contribution is computed fresh each frame as
  // (now - heldSinceMs) — an elapsed-time measurement, not a per-frame
  // accumulation — and folded into the total on keyup/blur.
  const leftTotalMs = useRef(0);
  const rightTotalMs = useRef(0);
  const leftHeldSinceMs = useRef<number | null>(null);
  const rightHeldSinceMs = useRef<number | null>(null);

  const inputCount = useRef(0);
  const timeInZoneMs = useRef(0);
  const lockRef = useRef<HTMLDivElement>(null);
  /** Milliseconds that must be spent inside the zone to pass. Mirrors
   *  verify.py's `hold_ms` default (60% of the segment) so the meter on
   *  screen and the server's rule are the same number. */
  const requiredHoldMs = params.hold_ms ?? duration * 0.6;
  /** Seeded starting position — no longer always dead centre. */
  const origin = useRef(startOffset(seed));
  const finished = useRef(false);
  const started = useRef(performance.now());
  const lastElapsed = useRef(0);

  useEffect(() => {
    const measure = () => {
      const width = trackRef.current?.clientWidth ?? 0;
      trackHalfPx.current = Math.max(0, width / 2 - RETICLE_PX / 2);
    };
    measure();
    window.addEventListener("resize", measure);

    const finish = (passed: boolean) => {
      if (finished.current) return;
      finished.current = true;
      onFinish({
        passed,
        durationMs: Math.round(performance.now() - started.current),
        inputCount: inputCount.current,
        score: Math.round(timeInZoneMs.current),
        sequence: [],
      });
    };

    const heldMs = (heldSince: number | null, bankedMs: number, now: number) =>
      bankedMs + (heldSince === null ? 0 : Math.max(0, now - heldSince));

    const stopLoop = rafLoop((elapsedMs, deltaMs) => {
      if (finished.current) return;

      const drift = driftAt(
        elapsedMs / 1000,
        sign.current,
        driftRate * BASE_DRIFT_UNITS_PER_SEC,
      );
      const left = heldMs(leftHeldSinceMs.current, leftTotalMs.current, elapsedMs);
      const right = heldMs(rightHeldSinceMs.current, rightTotalMs.current, elapsedMs);
      const correction = ((right - left) / 1000) * CORRECTION_UNITS_PER_SEC;
      const position = origin.current + drift + correction;
      const clamped = Math.max(-TRACK_LIMIT_UNITS, Math.min(TRACK_LIMIT_UNITS, position));

      const inZone = Math.abs(position) <= TARGET_ZONE_UNITS;

      if (lockRef.current) {
        // Written straight to style from inside the rAF loop, exactly like
        // the reticle -- never React state. This runs every frame.
        const held = Math.min(1, timeInZoneMs.current / requiredHoldMs);
        lockRef.current.style.transform = `scaleX(${held.toFixed(4)})`;
      }
      if (reticleRef.current) {
        const px = (clamped / TRACK_LIMIT_UNITS) * trackHalfPx.current;
        reticleRef.current.style.transform = `translate3d(${px.toFixed(2)}px, 0, 0)`;
        // Locked feedback lives on the reticle itself (colour change),
        // not a full-track wash — the zone band stays visible underneath
        // at all times, which is the thing the player actually needs to
        // see. Position (reticle inside the bordered zone) carries the
        // signal; colour only reinforces it (§9 — never colour alone).
        reticleRef.current.classList.toggle("is-locked", inZone);
      }
      if (inZone) timeInZoneMs.current += deltaMs;

      // Filling the meter IS the win. It used to only be checked when the
      // clock ran out, so holding the zone early bought nothing and the
      // screen just kept going -- "even after the bar is filled nothing
      // happened". The duration is now a deadline, not a fixed run length.
      if (timeInZoneMs.current >= requiredHoldMs) {
        finish(true);
        return;
      }

      lastElapsed.current = elapsedMs;

      if (Math.abs(position) > TRACK_LIMIT_UNITS) {
        finish(false);
      } else if (elapsedMs >= duration) {
        // Deadline reached without filling the meter: a genuine loss.
        finish(false);
      }
    });

    const setHeld = (direction: "left" | "right", isDown: boolean) => {
      const now = lastElapsed.current;
      const since = direction === "left" ? leftHeldSinceMs : rightHeldSinceMs;
      const total = direction === "left" ? leftTotalMs : rightTotalMs;
      if (isDown) {
        if (since.current === null) since.current = now;
      } else if (since.current !== null) {
        total.current += Math.max(0, now - since.current);
        since.current = null;
      }
    };

    const keydown = (event: KeyboardEvent) => {
      if (event.code !== "ArrowLeft" && event.code !== "ArrowRight") return;
      event.preventDefault();
      if (!event.repeat) inputCount.current += 1; // OS auto-repeat isn't a new input
      setHeld(event.code === "ArrowLeft" ? "left" : "right", true);
    };

    const keyup = (event: KeyboardEvent) => {
      if (event.code === "ArrowLeft") setHeld("left", false);
      else if (event.code === "ArrowRight") setHeld("right", false);
    };

    // A dropped keyup (e.g. the window loses focus while a key is held)
    // must not leave the reticle correcting forever against a phantom hold.
    const releaseAll = () => {
      setHeld("left", false);
      setHeld("right", false);
    };

    window.addEventListener("keydown", keydown);
    window.addEventListener("keyup", keyup);
    window.addEventListener("blur", releaseAll);

    return () => {
      stopLoop();
      window.removeEventListener("resize", measure);
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("keyup", keyup);
      window.removeEventListener("blur", releaseAll);
    };
  }, [duration, driftRate, onFinish]);

  return (
    <section className="game game--drift">
      <p className="label game__eyebrow">controller diagnostics</p>
      <h2 className="drift__title">hold it steady</h2>
      <div ref={trackRef} className="drift__track" aria-hidden="true">
        <div className="drift__zone" />
        <div ref={reticleRef} className="drift__reticle" />
      </div>

      {/* The lock meter. Without it, holding the zone produced no visible
          result at all — the reticle glowed and nothing else happened, so
          the screen said "hold it steady" while giving no sign that
          holding it steady was doing anything. This bar IS the game:
          it only fills while the reticle is inside the band. */}
      <div className="drift__lock" aria-hidden="true">
        <div ref={lockRef} className="drift__lock-fill" />
      </div>
      <p className="drift__hint">
        <strong>hold</strong> &larr; &rarr; to push back &middot; fill the bar to pass &middot; the pull reverses
      </p>
    </section>
  );
}
