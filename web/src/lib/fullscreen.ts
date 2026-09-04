// Fullscreen is an enhancement and must never block anything (design-system
// §6 "Fullscreen changes the viewport" and the Task 16 brief).
//
// requestFullscreen() requires a user gesture, so this is only ever called
// from inside a click handler — specifically the boot screen's power-on
// click, alongside AudioContext.resume() (see lib/audio.ts). That is the
// one gesture in the whole flow; if the browser refuses, everything below
// still works windowed.
//
// `Esc` exits fullscreen and that is not overridable by page script, so
// nothing in this app binds Esc. Dropping out of fullscreen must never
// interrupt a run — see Console.tsx's quiet "back to fullscreen" affordance,
// which listens via onFullscreenChange rather than trying to prevent the
// exit.

export async function requestFullscreen(element: HTMLElement): Promise<boolean> {
  if (typeof element.requestFullscreen !== "function") return false;
  try {
    await element.requestFullscreen();
    return true;
  } catch {
    return false;
  }
}

export function isFullscreen(): boolean {
  return typeof document !== "undefined" && document.fullscreenElement !== null;
}

export function onFullscreenChange(handler: (active: boolean) => void): () => void {
  const listener = () => handler(isFullscreen());
  document.addEventListener("fullscreenchange", listener);
  return () => document.removeEventListener("fullscreenchange", listener);
}

/** Leave fullscreen, if we are in it. The boot click took the screen; this
 *  is the other half of that bargain and belongs to power off. Never
 *  throws — a browser that refuses is not worth breaking the send-off for. */
export async function exitFullscreen(): Promise<void> {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
  } catch {
    // Refused or already out. Either way there is nothing to recover from.
  }
}
