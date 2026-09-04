// The last screen, and the only one allowed to be sentimental.
//
// Power off is not a navigation. It tears the console down: the music
// fades out and stops for good, fullscreen is handed back (the boot click
// took it; this returns it), and the chrome disappears — see Console.tsx,
// which hides it once `onPoweredOff` fires. What is left is a dark screen
// that does not offer a way back in.

import { useEffect, useRef, useState } from "react";
import { shutdownAudio } from "../lib/audio";
import { exitFullscreen } from "../lib/fullscreen";
import "./goodbye.css";

/** The shutdown sequence. Each line lands, holds, and is struck through as
 *  the next arrives — the console dismantling itself rather than a spinner
 *  pretending to work. Timings are the beat this needs to land, not
 *  measurements of anything real. */
const SHUTDOWN = [
  "closing the session",
  "releasing the codes",
  "wiping the save data",
  "deleting XXVI",
] as const;

const STEP_MS = 700;
/** Held on the last struck-through line before the screen goes dark. */
const BLACKOUT_MS = 900;

function PowerGlyph({ state }: { state: "live" | "dim" }) {
  return (
    <svg
      className={`goodbye__glyph is-${state}`}
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

type Phase = "farewell" | "shutting-down" | "off";

export function Goodbye({
  recipient,
  onPoweredOff,
}: {
  recipient: string;
  /** Told once the console is genuinely down, so the shell can drop the
   *  chrome. Fired at the START of the sequence, not the end: the mute and
   *  profile buttons should not outlive the decision to shut down. */
  onPoweredOff: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("farewell");
  const [step, setStep] = useState(0);
  const timers = useRef<number[]>([]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const powerOff = () => {
    if (phase !== "farewell") return;
    setPhase("shutting-down");
    onPoweredOff();

    // The console really does go quiet and really does give the screen back.
    shutdownAudio(SHUTDOWN.length * STEP_MS + BLACKOUT_MS);
    void exitFullscreen();

    SHUTDOWN.forEach((_, i) => {
      timers.current.push(
        window.setTimeout(() => setStep(i + 1), (i + 1) * STEP_MS),
      );
    });
    timers.current.push(
      window.setTimeout(
        () => setPhase("off"),
        SHUTDOWN.length * STEP_MS + BLACKOUT_MS,
      ),
    );
  };

  if (phase === "off") {
    // Nothing offered. No "play again", no way back in. The run is over and
    // the screen should feel over.
    return (
      <main className="goodbye goodbye--off">
        <PowerGlyph state="dim" />
        <p className="goodbye__until">until next time.</p>
      </main>
    );
  }

  if (phase === "shutting-down") {
    return (
      <main className="goodbye goodbye--shutdown" aria-live="polite">
        <ol className="goodbye__steps">
          {SHUTDOWN.slice(0, Math.max(1, step + 1)).map((line, i) => (
            <li key={line} className={`goodbye__step${i < step ? " is-done" : ""}`}>
              {line}
            </li>
          ))}
        </ol>
      </main>
    );
  }

  return (
    <main className="goodbye">
      <p className="label goodbye__label">thanks for playing</p>
      <h1 className="goodbye__line">happy birthday, {recipient.toLowerCase()}.</h1>
      <p className="goodbye__body">
        twenty years of this. eight segments, one night, and you still remembered
        the chilli flakes. go spend it — and text me when GTA 6 actually lands.
      </p>
      <button className="goodbye__power" onClick={powerOff} autoFocus>
        <PowerGlyph state="live" />
        <span>power off</span>
      </button>
    </main>
  );
}
