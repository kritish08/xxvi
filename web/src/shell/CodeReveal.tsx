// The code reveal — the moment the gift lands. This is the payoff the
// entire night exists for, so the rule for this screen is restraint, not
// cleverness: mono type, large, selectable, a copy button, and a plain
// nudge to screenshot it.
//
// There is NO email path anywhere in this system (no mailer, no template,
// nothing that re-sends a released code) — an earlier version of this
// screen's note claimed the code was "also in your email", which was
// simply false and would have sent him looking for something that doesn't
// exist if a copy failed. The actual safety net if a code is missed here
// is operator-side: `cli release` (server/xxvi/cli.py) prints the code
// again on its AlreadyReleased path, so the operator can always recover
// and relay a code that was emitted but never reached him.
//
// It does NOT auto-dismiss and does NOT animate itself away — he may be
// screenshotting it mid-call. Console.tsx renders it as an overlay on top
// of whatever screen comes next (already advanced underneath, since the
// server doesn't wait for this to be dismissed) and only clears it when he
// presses "continue" himself. That is a deliberate addition beyond the
// original task-plan sample, which had no way to leave this screen at
// all — "never auto-dismiss" cannot mean "never leaves," or the run is
// stuck here forever once the final code is redeemed.

import { useState } from "react";
import "./codereveal.css";

type Release = { reward_id: number; label: string; code: string };

type Props = {
  release: Release;
  onContinue: () => void;
};

export function CodeReveal({ release, onContinue }: Props) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard?.writeText(release.code);
      setCopied(true);
    } catch {
      // Clipboard access can be denied or unavailable. Not a crisis: the
      // code is still on screen, selectable, and screenshottable, and if
      // it's genuinely missed the operator can recover and relay it later
      // (see this file's header comment).
      setCopied(false);
    }
  };

  return (
    <section className="reveal">
      <p className="label reveal__label">reward unlocked</p>
      <h2 className="reveal__title">{release.label}</h2>

      <p className="reveal__code" aria-label="redemption code">
        {release.code}
      </p>

      <div className="reveal__actions">
        <button onClick={() => void copy()}>{copied ? "copied" : "copy code"}</button>
        <button className="reveal__continue" onClick={onContinue}>
          continue
        </button>
      </div>

      <p className="reveal__note">screenshot this — it won&rsquo;t be shown again.</p>
    </section>
  );
}
