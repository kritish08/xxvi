// The signature moment (docs/design-system.md §6.5, §6 "The signature
// moment — the trophy pop"). It fires 19+ times across the run and gets
// more care than anything else in this app.
//
// The one rule that outranks everything aesthetic here: it must read as
// complete with the sound muted. Grade is written out as text below the
// name — never conveyed by colour alone — because his screen share may not
// carry system audio.
//
// Choreography is §6.5's, to the millisecond:
//
//    0ms   sting attack  ·  toast begins slide from -100% Y
//    0-180 slide in, overshoot to scale 1.04
//  180-320 settle to 1.0
//  320-4320 hold          (sting has decayed by ~600ms)
//  4320-4640 retract up, fade
//
// This is deliberately built as two separate CSS animations (trophyPopIn,
// trophyPopOut in trophy.css) rather than one continuous 4640ms keyframe
// timeline, with `.toast--retracting` added by a JS timer at totalMs - 320.
// A single combined animation collapses under prefers-reduced-motion to a
// single near-instant jump straight to its *final* keyframe — i.e. the
// retracted, invisible one — which technically "keeps the end state" but
// means a reduced-motion viewer never actually sees the toast. Two
// independently-triggered animations mean the entrance collapses to the
// settled, fully legible state and *stays there* for the whole hold, and
// only jumps to hidden when the retract is actually due — verified in a
// real browser (see task report).
//
// Sync: the sting and the entrance animation are triggered from the same
// synchronous handler (useLayoutEffect, which runs after the DOM commit
// but before paint) so they start together, not audio-in-a-callback vs
// animation-in-an-effect drifting apart by 80ms. Audio is scheduled
// against AudioContext.currentTime inside playTrophySound, never
// setTimeout — see lib/trophy-sound.ts.
//
// The element is keyed by trophy_id so each pop is a fresh DOM node: the
// entrance animation runs from its own frame 0 the instant the node is
// inserted, with no manual class-toggle/reflow dance needed to restart it
// between pops.
//
// Platinum breaks the pattern on purpose (§6.5): full-screen rather than a
// toast, sting ~1.8s, and it is the climax of the whole run.

import { useLayoutEffect, useState } from "react";
import { playTrophySound } from "../lib/trophy-sound";
import { TrophyIcon } from "./TrophyIcon";
import type { TrophyPopMsg } from "../ws-messages";
import "./trophy.css";

type Props = {
  queue: TrophyPopMsg[];
  onDismiss: () => void;
  /** Total on-screen time for a standard pop, ms. Matches §6.5's 4640ms
   *  timeline (0 -> slide in -> settle -> hold -> retract) by default. */
  holdMs?: number;
  /** Total on-screen time for the platinum moment, ms. Long enough for the
   *  ~1.8s sting to fully resolve before the retract begins. */
  platinumHoldMs?: number;
  /** How long the retract phase takes, ms — must match trophy.css's
   *  --toast-retract so the JS-scheduled class flip lines up with the
   *  CSS animation length. */
  retractMs?: number;
  /** Retract length for the platinum moment; must match --platinum-retract. */
  platinumRetractMs?: number;
  /** Fires synchronously alongside the sting, once per pop. Lets an
   *  integrator duck the MUSIC bus (§6.5: "trophy sting -> MUSIC -6dB for
   *  the sting's length") once lib/audio.ts exists, without this file
   *  importing it. No-op if not supplied. */
  onSting?: (grade: TrophyPopMsg["grade"]) => void;
};

const STANDARD_TOTAL_MS = 4640;
const STANDARD_RETRACT_MS = 320;
const PLATINUM_TOTAL_MS = 6600;
const PLATINUM_RETRACT_MS = 700;

export function TrophyToast({
  queue,
  onDismiss,
  holdMs = STANDARD_TOTAL_MS,
  platinumHoldMs = PLATINUM_TOTAL_MS,
  retractMs = STANDARD_RETRACT_MS,
  platinumRetractMs = PLATINUM_RETRACT_MS,
  onSting,
}: Props) {
  const current = queue[0];
  const isPlatinum = current?.grade === "platinum";
  const totalMs = isPlatinum ? platinumHoldMs : holdMs;
  const thisRetractMs = isPlatinum ? platinumRetractMs : retractMs;
  const [retracting, setRetracting] = useState(false);

  useLayoutEffect(() => {
    if (!current) return;
    setRetracting(false);
    // Same synchronous tick as the DOM insertion that starts the CSS
    // animation (React fires useLayoutEffect after the commit, before the
    // browser paints) — this is the "same event, same frame" §6.5 asks for.
    playTrophySound(current.grade);
    onSting?.(current.grade);

    const retractTimer = setTimeout(() => setRetracting(true), Math.max(0, totalMs - thisRetractMs));
    const dismissTimer = setTimeout(onDismiss, totalMs);
    return () => {
      clearTimeout(retractTimer);
      clearTimeout(dismissTimer);
    };
    // Deliberately keyed on [current, totalMs, thisRetractMs] only:
    // onDismiss/onSting are callbacks that may be a fresh function identity
    // on every parent render, and this effect must fire exactly once per
    // pop (when a new trophy object arrives at the head of the queue), not
    // on every unrelated parent re-render while a pop is already on screen.
  }, [current, totalMs, thisRetractMs]);

  if (!current) return null;

  return (
    <aside
      key={current.trophy_id}
      className={`toast toast--${current.grade}${isPlatinum ? " toast--climax" : ""}${retracting ? " toast--retracting" : ""}`}
      role="status"
      aria-live="polite"
    >
      <span className={`toast__icon toast__icon--${current.grade}`}>
        <TrophyIcon grade={current.grade} />
      </span>
      <span className="toast__body">
        <strong className="toast__name">{current.name}</strong>
        {/* Grade written out, not implied by colour — this is what has to
            survive a muted, compressed recording (§6.5, §9). */}
        <span className="toast__grade label">{current.grade} trophy unlocked</span>
      </span>
    </aside>
  );
}
