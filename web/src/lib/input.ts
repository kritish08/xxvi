// Face buttons: 0 triangle, 1 circle, 2 cross, 3 square — the only
// pictographic language in this app (docs/design-system.md §7). Keyboard
// is the supported input path (§9); on-screen buttons exist for the
// operator's benefit watching the screen share, not as the primary input.
//
// Esc is deliberately unbound — it exits fullscreen and that behaviour is
// not overridable (§9).

export const FACE_KEYS: Record<string, number> = {
  KeyW: 0, ArrowUp: 0,
  KeyD: 1, ArrowRight: 1,
  KeyS: 2, ArrowDown: 2,
  KeyA: 3, ArrowLeft: 3,
};

export const FACE_GLYPHS = ["△", "○", "✕", "□"];
export const FACE_LABELS = ["triangle", "circle", "cross", "square"];
/** The on-screen legend shown throughout Simon (and any future mechanic
 *  that reuses face input) so the key mapping never has to be memorised. */
export const FACE_KEY_LABELS = ["W / ↑", "D / →", "S / ↓", "A / ←"];

export function faceFromEvent(event: KeyboardEvent): number | null {
  const value = FACE_KEYS[event.code];
  return value === undefined ? null : value;
}
