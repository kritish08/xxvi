// A live message from the operator, mid-run (POST /api/operator/toast ->
// ToastMsg on the player WS channel -- ws-messages.ts, xxvi/api/
// operator_routes.py). He types something while his friend is playing, on
// a Discord call, and it lands on the friend's screen in his own voice.
//
// Deliberately built on the SAME toast primitive as the trophy pop
// (shell/TrophyToast.tsx, trophy.css) -- same card shape, same padding and
// border treatment, same 320ms-in / hold / 320ms-out choreography via the
// `.toast` base class and `.toast--retracting` timer pattern -- so this
// reads as the same *family* of console-style notification the run
// already trained the eye on, not a second visual language bolted on.
//
// But it must never be mistaken for a trophy pop -- a trophy is an
// achievement the RUN is telling him about; this is a PERSON talking. So
// every dimension that could blur the two is deliberately different
// (operator-toast.css):
//   - slides up from the bottom-centre, not down from the top-centre
//     (trophy toasts and operator toasts can never occupy the same pixels
//     even if both are queued at once)
//   - the accent colour (kiddie blue / devil red -- whichever palette is
//     live), never a bronze/silver/gold/platinum grade colour
//   - a speech-bubble icon, never a trophy chalice
//   - the label reads "operator", never a grade word
//   - the message wraps across lines -- a sentence has no fixed length the
//     way a trophy name does, so it is never truncated
//
// Per docs/design-system.md's one hard rule for every notification in this
// app: it must read as complete with the sound muted. The message text
// itself carries all the meaning; the chime (lib/audio.ts's
// playOperatorToastSound, wired by Console.tsx) is a bonus layer, exactly
// like the trophy sting.
import { useLayoutEffect, useState } from "react";
import type { ToastMsg } from "../ws-messages";
import "./trophy.css";
import "./operator-toast.css";

/** ToastMsg carries no id from the server -- each POST is independent, so
 *  the queue-owner (Console.tsx) stamps one on arrival, the same role
 *  `trophy_id` plays for TrophyToast's queue. */
export type QueuedOperatorToast = ToastMsg & { id: number };

type Props = {
  queue: QueuedOperatorToast[];
  onDismiss: () => void;
  /** Total on-screen time, ms. Matches the standard (non-platinum) trophy
   *  pop's 4640ms rhythm by default -- same family, same pacing. */
  holdMs?: number;
  /** Must match operator-toast.css's --toast-retract-driven animation
   *  length (shared token with trophy.css). */
  retractMs?: number;
  /** Fires synchronously alongside the entrance, once per message -- same
   *  seam as TrophyToast's `onSting`. No-op if not supplied. */
  onChime?: () => void;
};

const DEFAULT_HOLD_MS = 4640;
const DEFAULT_RETRACT_MS = 320;

export function OperatorToast({
  queue,
  onDismiss,
  holdMs = DEFAULT_HOLD_MS,
  retractMs = DEFAULT_RETRACT_MS,
  onChime,
}: Props) {
  const current = queue[0];
  const [retracting, setRetracting] = useState(false);

  useLayoutEffect(() => {
    if (!current) return;
    setRetracting(false);
    // Same-frame as the DOM insertion that starts the CSS animation --
    // mirrors TrophyToast's sync rule (design-system.md §6.5 "Sync").
    onChime?.();

    const retractTimer = setTimeout(() => setRetracting(true), Math.max(0, holdMs - retractMs));
    const dismissTimer = setTimeout(onDismiss, holdMs);
    return () => {
      clearTimeout(retractTimer);
      clearTimeout(dismissTimer);
    };
    // Keyed on [current, holdMs, retractMs] only, not onDismiss/onChime --
    // same reasoning as TrophyToast: this must fire once per message, not
    // on every unrelated parent re-render while one is already on screen.
  }, [current, holdMs, retractMs]);

  if (!current) return null;

  return (
    <aside
      key={current.id}
      className={`toast toast--operator${retracting ? " toast--retracting" : ""}`}
      role="status"
      aria-live="polite"
    >
      <span className="toast__icon toast__icon--operator" aria-hidden="true">
        <SpeechBubbleIcon />
      </span>
      <span className="toast__body">
        <strong className="toast__name toast__name--operator">{current.text}</strong>
        <span className="toast__grade toast__grade--operator label">operator</span>
      </span>
    </aside>
  );
}

// A speech bubble, not a trophy chalice -- deliberately the most legible
// "a person is talking" glyph available at this size, flat stroke only
// (no fill, no shadow) to match TrophyIcon's codec rules.
function SpeechBubbleIcon() {
  return (
    <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 10 H42 V32 H20 L11 40 V32 H6 Z" />
      <path d="M14 18 H34" />
      <path d="M14 25 H28" />
    </svg>
  );
}
