// operatorOnline is driven by Console.tsx's `operator_presence` WS handler
// (lib/ws.ts) — this component only renders it. It starts false: the
// dashboard hasn't necessarily connected by the time this screen shows,
// and "offline" is the honest default until the socket says otherwise.

import { runApi } from "../lib/run-client";

export function ProfileSelect({
  onDone,
  operatorOnline,
  recipient = "you",
  operator = "the operator",
}: {
  onDone: () => void;
  operatorOnline: boolean;
  /** `ContentView.recipient` — defaults to "you" so the tile still reads
   *  sensibly before `content` has loaded. */
  recipient?: string;
  /** `ContentView.operator` — same default as `Checkpoint`'s. */
  operator?: string;
}) {
  const choose = async () => {
    await runApi.chooseProfile();
    onDone();
  };

  return (
    <section className="profiles">
      <div className="label profiles__label">select profile</div>
      <h1>who&rsquo;s using the console?</h1>
      <div className="profiles__row">
        <button className="profile" onClick={() => void choose()} autoFocus>
          <span className="profile__avatar">{recipient.charAt(0).toUpperCase()}</span>
          <span className="profile__name">{recipient}</span>
        </button>
        <div
          className={`profile profile--other ${operatorOnline ? "is-online" : ""}`}
          aria-live="polite"
        >
          <span className="profile__avatar">{operator.charAt(0).toUpperCase()}</span>
          <span className="profile__name">{operator}</span>
          <span className="profile__status">
            <span className="profile__dot" aria-hidden="true" />
            {operatorOnline ? "online" : "offline"}
          </span>
        </div>
      </div>
    </section>
  );
}
