// The last shell screen before segment 1 (Tasks 18-20 own everything past
// this). No box art here — that reveal already happened on the library
// card (shell/Install.tsx) and doesn't repeat.

import { runApi } from "../lib/run-client";

export function HowToPlay({ onDone }: { onDone: () => void }) {
  const start = async () => {
    await runApi.ackHowto();
    onDone();
  };

  return (
    <section className="howto">
      <div className="label howto__label">how to play</div>
      <h1>2 acts &middot; 8 trophies of memory &middot; 8 of skill</h1>
      <p className="howto__line">clear an act, and kritish releases a code.</p>
      <p className="howto__line">
        <strong>KIDDIE</strong> — a fail costs you the current segment.
      </p>
      <p className="howto__line">
        <strong>DEVIL</strong> — a fail costs you everything.
      </p>
      <p className="howto__note">
        codes you&rsquo;ve already earned are yours. nothing takes those back.
      </p>
      <button className="howto__start" onClick={() => void start()} autoFocus>
        start
      </button>
    </section>
  );
}
