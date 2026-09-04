// Shared motion primitives for tasks 15-21 (docs/design-system.md §6,
// "Motion engineering"). Two rules this file exists to enforce:
//
//   1. Animate transform/opacity only — never width/height/top/left. Those
//      force layout and paint on every frame; transform/opacity are
//      compositor-only.
//   2. Continuous motion runs one requestAnimationFrame loop keyed off
//      performance.now() delta time, never setInterval — setInterval(fn, 50)
//      is 20fps and drifts against the display's real refresh rate.
//
// React stays out of the frame loop entirely: rafLoop hands the caller raw
// elapsed/delta numbers to write straight into element.style via a ref, so
// nothing here calls setState. Callers re-render only on state changes that
// actually change the UI (start, pass, fail) — not once per frame.

export type FrameCallback = (elapsedMs: number, deltaMs: number) => void;

/**
 * Runs `callback` once per animation frame until `stop()` is called.
 * `elapsedMs` and `deltaMs` are both derived from `performance.now()`, so
 * motion stays correct regardless of the display's actual frame rate.
 */
export function rafLoop(callback: FrameCallback): () => void {
  let handle = 0;
  let stopped = false;
  const start = performance.now();
  let last = start;

  const tick = (now: number) => {
    if (stopped) return;
    const deltaMs = now - last;
    last = now;
    callback(now - start, deltaMs);
    handle = requestAnimationFrame(tick);
  };

  handle = requestAnimationFrame(tick);

  return () => {
    stopped = true;
    cancelAnimationFrame(handle);
  };
}

/**
 * Sets a progress bar's fill via `transform: scaleX()`, never `width`.
 * The element needs `transform-origin: left` in CSS (not set here, since
 * that's a one-time style, not a per-frame write).
 */
export function setProgress(el: HTMLElement, fraction: number): void {
  const clamped = Math.min(1, Math.max(0, fraction));
  el.style.transform = `scaleX(${clamped})`;
}
