// The last shell screen before segment 1 (Tasks 18-20 own everything past
// this). No box art here — that reveal already happened on the library
// card (shell/Install.tsx) and doesn't repeat.
//
// `copy.how_to_play` (server/xxvi/content/schema.py::CopyBlock) used to be
// dead config: served by /api/content, present in the generated API
// types, never read by any component. This screen hardcoded its own body
// instead — including a heading with an act/trophy count baked in, which
// was simply wrong for any config that wasn't the author's own. The
// heading below is derived from the real, served trophy list instead
// (the same technique lib/trophy-content.ts already uses for the library
// card's count) rather than parsed out of the free-text copy, so it can
// never disagree with the config that's actually loaded — trusting a
// number embedded in hand-authored prose would reopen exactly the bug
// this fixes. `copy` itself supplies the body lines beneath it: whatever
// the config author wrote, split on its own line breaks, is what shows.
// KIDDIE/DEVIL and the "codes already earned" note stay static — they're
// true of the product for every config, not narrative content a config
// author would rewrite.

import { runApi } from "../lib/run-client";
import type { TrophyView } from "../lib/client";

function countByPrefix(trophies: readonly TrophyView[], prefix: string): number {
  return trophies.filter((t) => t.id.startsWith(prefix)).length;
}

export function HowToPlay({
  onDone,
  copy,
  trophies,
}: {
  onDone: () => void;
  /** `ContentView.copy.how_to_play` — a config-authored, possibly
   *  multi-line string. Each line renders as its own paragraph. */
  copy: string;
  /** `ContentView.trophies` — the heading is counted from this, never
   *  hardcoded, so it can't disagree with the loaded config. */
  trophies: readonly TrophyView[];
}) {
  const start = async () => {
    await runApi.ackHowto();
    onDone();
  };

  const acts = countByPrefix(trophies, "act-");
  const memory = countByPrefix(trophies, "question-");
  const skill = countByPrefix(trophies, "game-");
  const lines = copy
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  return (
    <section className="howto">
      <div className="label howto__label">how to play</div>
      <h1>
        {acts} act{acts === 1 ? "" : "s"} &middot; {memory} trophies of memory &middot; {skill} of skill
      </h1>
      {lines.map((line, i) => (
        <p className="howto__line" key={i}>
          {line}
        </p>
      ))}
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
