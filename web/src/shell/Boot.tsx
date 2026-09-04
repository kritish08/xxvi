// The power-on click is the single unlock gesture for the whole app
// (design-system.md §6.5). Everything that requires a user gesture —
// AudioContext.resume(), requestFullscreen(), audio playback — happens in
// this one handler and nowhere else. Anything downstream that needs a
// second gesture is a design error.
//
// The box-art title reveal belongs to the library card (shell/Install.tsx)
// — that is its own beat and gets its own screen. Boot stays deliberately
// generic: a power glyph, not the title, so nothing here steals the reveal.

import { useEffect, useRef, useState } from "react";
import { requestFullscreen } from "../lib/fullscreen";
import { playNarration, unlockAudio } from "../lib/audio";

// Long enough for the boot narration to finish. The line ("XXVI. Powering
// on.") measures 2.78s -- see tools/gen-narration.py, which enforces this
// budget and fails the build rather than shipping a line that gets cut off.
// Raised from 2200ms: the alternative was cutting words out of an already
// three-word line to fit an arbitrary hold, which is the tail wagging the dog.
// Exported so tests wait on this value rather than restating it. Two test
// files previously hardcoded "2300" to clear it, and both broke the moment
// it moved.
export const BOOT_HOLD_MS = 3200;

function PowerGlyph({ active }: { active: boolean }) {
  return (
    <svg
      className={`boot__glyph ${active ? "is-active" : ""}`}
      viewBox="0 0 24 24"
      width="2.5rem"
      height="2.5rem"
      aria-hidden="true"
    >
      <path d="M12 3v8" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" fill="none" />
      <path
        d="M6.5 6.5a8 8 0 1 0 11 0"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

export function Boot({ onDone }: { onDone: () => void }) {
  const [phase, setPhase] = useState<"idle" | "on">("idle");
  // onDone is a fresh closure on every Console render (it wraps refresh);
  // hold the latest in a ref so the hold-timer effect below doesn't need
  // onDone in its dependency array and re-arm itself mid-boot.
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    if (phase !== "on") return;
    const timer = setTimeout(() => doneRef.current(), BOOT_HOLD_MS);
    return () => clearTimeout(timer);
  }, [phase]);

  const powerOn = () => {
    // The one unlock gesture, all at once (§6.5):
    void unlockAudio().then(() => playNarration("boot"));
    void requestFullscreen(document.documentElement); // may be refused; we continue either way
    setPhase("on");
  };

  return (
    <main className={`boot boot--${phase}`}>
      <div className="label boot__label">XXVI console</div>
      {phase === "idle" ? (
        <button className="boot__power" onClick={powerOn} autoFocus>
          <PowerGlyph active={false} />
          <span>press to power on</span>
        </button>
      ) : (
        <div className="boot__status" aria-live="polite">
          <PowerGlyph active />
          <span className="boot__status-text">booting</span>
          <span className="boot__status-bar" aria-hidden="true" />
        </div>
      )}
    </main>
  );
}
