// Optional gamepad support (task 23, cuttable). Keyboard is the supported
// input path throughout this app (lib/input.ts, docs/design-system.md §9);
// this file only ever ADDS a second source of the same `face` presses that
// SimonSays.tsx / TrophyRun.tsx already accept from the keyboard. Nothing
// here may be awaited, nothing here may block a game from being completed
// with no controller present — a pad that never enumerates, or a
// `navigator.getGamepads` that throws, changes nothing about how the game
// plays. See this task's brief: "a controller that fails to enumerate at
// 12:01 AM cannot be allowed to block anything."
//
// Standard gamepad button order (the Gamepad API's "standard" mapping,
// https://developer.mozilla.org/en-US/docs/Web/API/Gamepad/mapping) is
// index 0 cross, 1 circle, 2 square, 3 triangle. This project's face
// indices (lib/input.ts) are triangle 0, circle 1, cross 2, square 3 — a
// different order, mirrored here exactly rather than re-derived.

import { useEffect, useRef, useState } from "react";

/** buttons[standard index] -> this project's face index. Read as: standard
 *  slot 0 (cross) maps to face 2, slot 1 (circle) to face 1, slot 2
 *  (square) to face 3, slot 3 (triangle) to face 0. */
export const DUALSENSE_FACE_MAP: readonly number[] = [2, 1, 3, 0];

/** Pure and defensive: `buttons` comes straight off `navigator.getGamepads()`,
 *  a live browser object this code does not control the shape of, so no
 *  assumption is made beyond "array-like, or not". Returns the first
 *  pressed face button (lowest standard index wins) or null if none is
 *  pressed / the input is not usable. */
export function faceFromButtons(buttons: readonly GamepadButton[] | null | undefined): number | null {
  if (!buttons) return null;
  for (let index = 0; index < DUALSENSE_FACE_MAP.length; index += 1) {
    if (buttons[index]?.pressed) return DUALSENSE_FACE_MAP[index];
  }
  return null;
}

function readFirstGamepad(): Gamepad | null {
  if (typeof navigator === "undefined" || typeof navigator.getGamepads !== "function") return null;
  try {
    const pads = navigator.getGamepads();
    if (!pads) return null;
    for (const pad of pads) {
      if (pad && typeof pad === "object" && Array.isArray(pad.buttons)) return pad;
    }
  } catch {
    // A gamepad implementation that throws on enumeration is exactly the
    // "fails to enumerate" case this task exists to survive. Treat it the
    // same as no pad connected.
    return null;
  }
  return null;
}

/**
 * Polls the Gamepad API via requestAnimationFrame and reports face-button
 * presses as edges: a held button fires `onFace` once on the frame it
 * becomes pressed, not once per frame for as long as it's held. Returns
 * whether a pad is currently connected, purely so callers can show an
 * unobtrusive "controller detected" acknowledgement — nothing in this
 * hook's contract requires a caller to look at that value.
 *
 * `onFace` may be a new function identity every render (both call sites
 * pass a `useCallback` whose deps change on every accepted press) — the
 * poll loop itself is only ever set up once per mount, via a ref, so a
 * changing callback identity can't tear down and restart the rAF loop
 * (which would otherwise forget which button was already held and could
 * double-fire a still-held button on the next render).
 */
export function useGamepadFace(onFace: (face: number) => void): boolean {
  const [connected, setConnected] = useState(false);
  const onFaceRef = useRef(onFace);

  useEffect(() => {
    onFaceRef.current = onFace;
  });

  useEffect(() => {
    if (typeof navigator === "undefined" || typeof navigator.getGamepads !== "function") return;

    let frame = 0;
    let previousFace: number | null = null;

    const poll = () => {
      const pad = readFirstGamepad();
      setConnected(Boolean(pad));

      let face: number | null = null;
      if (pad) {
        try {
          face = faceFromButtons(pad.buttons);
        } catch {
          face = null;
        }
      }

      if (face !== null && face !== previousFace) onFaceRef.current(face);
      previousFace = face;

      frame = requestAnimationFrame(poll);
    };

    frame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(frame);
  }, []);

  return connected;
}
