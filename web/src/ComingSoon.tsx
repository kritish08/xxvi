import { useEffect, useState } from "react";
import "./gate.css";
import { formatCountdown } from "./lib/countdown";
import type { SessionInfo } from "./lib/client";

type Props = {
  session: SessionInfo;
  copy: string;
  teaser: string;
};

/**
 * The only screen an anonymous visitor ever sees: no boot screen, no
 * library, no hint of what is behind the gate. `copy` and `teaser` are
 * server-supplied (`GET /api/content`) and rendered verbatim -- this
 * component contributes no additional text of its own, so nothing it adds
 * can leak anything the copy doesn't already say.
 *
 * The countdown is cosmetic. `session.seconds_until_live` is a snapshot
 * from the server; this component ticks it down locally between polls
 * purely so the number looks alive, and re-syncs to the server's value
 * every time a fresh `session` prop arrives (i.e. every poll in App.tsx).
 * It never decides whether the gate is open -- `session.live`, read by the
 * caller, does that.
 */
export function ComingSoon({ session, copy, teaser }: Props) {
  const [remaining, setRemaining] = useState(session.seconds_until_live);

  useEffect(() => {
    setRemaining(session.seconds_until_live);
    const tick = window.setInterval(() => setRemaining((n) => Math.max(0, n - 1)), 1000);
    return () => window.clearInterval(tick);
  }, [session.seconds_until_live]);

  const personalised = session.authenticated && session.role === "player";

  return (
    <section className="gate__message-block">
      <p className="gate__message">{personalised ? teaser : copy}</p>
      {personalised && (
        <div className="gate__countdown-block">
          <p className="label gate__countdown-label">counting down</p>
          <p className="gate__countdown" aria-label="time remaining">
            {formatCountdown(remaining)}
          </p>
        </div>
      )}
    </section>
  );
}
