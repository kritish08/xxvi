// StackTower — ported from the Kyrex coming-soon page's LayerStacker
// (kyrex-digitech/kyrex-web, src/components/coming-soon/LayerStacker.tsx).
//
// The mechanic is unchanged and is the one that made it worth reusing: a
// block slides left<->right above the tower, you drop it, and whatever
// overhangs the block below is sliced off. The tower narrows until you
// miss. A near-perfect drop grows the block back, so a good run can
// recover width instead of only ever losing it.
//
// WHAT CHANGED IN THE PORT, and why:
//   - Next.js/Tailwind/styled-jsx out, XXVI tokens and a plain stylesheet
//     in (stacktower.css). It has to look like this console, not like the
//     Kyrex site.
//   - The Kyrex layer chips ("L01 · DEVOPS") are gone. They were brand
//     furniture for a company page and mean nothing here.
//   - No localStorage best score. A segment is not a high-score table; the
//     target is the only bar that matters.
//   - No idle splash and no self-restart. The segment already framed this,
//     and pass/fail belongs to the server via onFinish -- a mechanic that
//     restarts itself would be reporting nothing.
//   - A TARGET, which the original had no concept of: reaching it ends the
//     segment as a pass immediately.
//
// SINGLE TRY, deliberately. Simon hands out 3 tries (2 in Devil) because
// one mistyped face there is a slip. Here the miss IS the game -- a stack
// that forgives a miss has no stakes at all. So one miss ends the segment,
// and the run's normal difficulty rules take it from there: Kiddie replays
// the segment, Devil spends a life (and a wipe once they are gone).

import { useCallback, useEffect, useRef, useState } from "react";
import type { GameProps } from "./types";
import "./stacktower.css";

// Geometry. Kept in abstract units and scaled by CSS so the physics never
// depend on layout, the same rule StickDrift follows.
const STAGE_W = 320;
const BLOCK_H = 26;
const INITIAL_BLOCK_W = 160;
/** How many block rows the stage is tall, and how many must stay EMPTY
 *  above the live block. The camera used to start moving only once the
 *  tower was 11 high, which left the sliding block pinned against the top
 *  edge with barely a row of air above it — no room to read where it was
 *  going, which is the only thing you are actually judging. */
const STAGE_ROWS = 16;
const HEADROOM_ROWS = 4;

const SPEED_START = 2.2;
const SPEED_MAX = 5.2;
const SPEED_INCR = 0.035;

/** Within this many units of dead centre counts as perfect. */
const PERFECT_TOLERANCE = 4;
/** A perfect drop widens the block by this much, capped at the start width. */
const GROW_PER_PERFECT = 11;

/** How long the toppling block is left on screen before the segment ends.
 *  Without it the miss and the failure screen land on the same frame and
 *  the cause is invisible -- the same mistake Simon used to make. */
const FAIL_HOLD_MS = 700;

type Block = { x: number; w: number; perfect?: boolean };

export function StackTower({ params, onFinish }: GameProps) {
  const target = Math.max(1, Math.trunc(params.target ?? 8));

  const [stack, setStack] = useState<Block[]>([
    { x: (STAGE_W - INITIAL_BLOCK_W) / 2, w: INITIAL_BLOCK_W },
  ]);
  const [active, setActive] = useState<Block>({ x: 0, w: INITIAL_BLOCK_W });
  const [score, setScore] = useState(0);
  const [combo, setCombo] = useState(0);
  const [toppling, setToppling] = useState<Block | null>(null);

  const dir = useRef<1 | -1>(1);
  const speed = useRef(SPEED_START);
  const activeRef = useRef(active);
  const drops = useRef(0);
  const started = useRef(Date.now());
  const finished = useRef(false);
  // Mirrors `score` for the rAF/keyboard path, which reads it synchronously.
  const scoreRef = useRef(0);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  const finish = useCallback(
    (passed: boolean) => {
      if (finished.current) return;
      finished.current = true;
      onFinish({
        passed,
        durationMs: Date.now() - started.current,
        inputCount: drops.current,
        score: scoreRef.current,
        sequence: [],
      });
    },
    [onFinish],
  );

  // One rAF loop. Position is written through a ref and committed once per
  // frame; nothing else re-renders per frame (design-system.md §6).
  useEffect(() => {
    if (finished.current) return;
    let raf = 0;
    const tick = () => {
      if (finished.current) return;
      const a = activeRef.current;
      let x = a.x + dir.current * speed.current;
      if (x + a.w >= STAGE_W) {
        x = STAGE_W - a.w;
        dir.current = -1;
      } else if (x <= 0) {
        x = 0;
        dir.current = 1;
      }
      const next = { ...a, x };
      activeRef.current = next;
      setActive(next);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [toppling]);

  const drop = useCallback(() => {
    if (finished.current || toppling) return;
    const a = activeRef.current;
    const top = stack[stack.length - 1];
    drops.current += 1;

    const leftEdge = Math.max(a.x, top.x);
    const rightEdge = Math.min(a.x + a.w, top.x + top.w);
    const overlap = rightEdge - leftEdge;

    // Missed the tower entirely. One miss is the whole game -- see the
    // header comment on why this mechanic gets no second chance.
    if (overlap <= 0) {
      setToppling(a);
      window.setTimeout(() => finish(false), FAIL_HOLD_MS);
      return;
    }

    const perfect =
      Math.abs(a.x - top.x) <= PERFECT_TOLERANCE &&
      Math.abs(a.w - top.w) <= PERFECT_TOLERANCE;

    let placedW: number;
    let placedX: number;
    if (perfect) {
      placedW = Math.min(INITIAL_BLOCK_W, top.w + GROW_PER_PERFECT);
      const centre = top.x + top.w / 2;
      placedX = Math.max(0, Math.min(STAGE_W - placedW, centre - placedW / 2));
    } else {
      placedW = overlap;
      placedX = leftEdge;
    }

    const next = scoreRef.current + 1;
    scoreRef.current = next;
    setScore(next);
    setCombo((c) => (perfect ? c + 1 : 0));
    setStack((s) => [...s, { x: placedX, w: placedW, perfect }]);

    // Target reached: the segment is over, now, as a pass. The original had
    // no end state at all -- it ran until you missed.
    if (next >= target) {
      finish(true);
      return;
    }

    speed.current = Math.min(SPEED_MAX, speed.current + SPEED_INCR);
    const spawn: Block = { x: dir.current === 1 ? 0 : STAGE_W - placedW, w: placedW };
    activeRef.current = spawn;
    setActive(spawn);
  }, [stack, target, toppling, finish]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.repeat) return; // a held key is one drop, not many
      if (event.code === "Space" || event.code === "Enter") {
        event.preventDefault();
        drop();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drop]);

  // Keep HEADROOM_ROWS of empty stage above the live block at all times.
  // The live block sits one row above the tower, so the row it occupies is
  // `stack.length`; the camera scrolls exactly enough to hold it that far
  // down from the top edge.
  const cameraY = Math.max(0, (stack.length + HEADROOM_ROWS + 1 - STAGE_ROWS) * BLOCK_H);

  return (
    <section className="game game--stack">
      <p className="label game__eyebrow">structural integrity</p>
      <h2 className="stack__title">stack it</h2>

      <p className="stack__readout label">
        <span className="stack__count">
          {score}
          <span className="stack__of"> / {target}</span>
        </span>
        {combo >= 2 && <span className="stack__combo">perfect &times;{combo}</span>}
      </p>

      <div
        className="stack__stage"
        style={{ ["--stage-w" as string]: `${STAGE_W}px`, ["--block-h" as string]: `${BLOCK_H}px` }}
      >
        <div className="stack__camera" style={{ transform: `translateY(${cameraY}px)` }}>
          {stack.map((b, i) => (
            <div
              key={i}
              className={`stack__block${b.perfect ? " is-perfect" : ""}`}
              style={{ left: b.x, bottom: i * BLOCK_H, width: b.w }}
            />
          ))}

          {!toppling && (
            <div
              className="stack__active"
              style={{ left: active.x, bottom: stack.length * BLOCK_H, width: active.w }}
            />
          )}

          {toppling && (
            <div
              className="stack__toppling"
              style={{ left: toppling.x, bottom: stack.length * BLOCK_H, width: toppling.w }}
            />
          )}
        </div>
      </div>

      <p className="stack__hint">space to drop &middot; dead centre grows it back &middot; one miss ends it</p>
    </section>
  );
}
