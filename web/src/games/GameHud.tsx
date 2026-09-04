// The persistent in-game HUD. Rendered by GameHost alongside whichever
// mechanic is playing, so all four gain it at once without any of them
// being touched.
//
// WHY THIS EXISTS: driving the real app showed a game screen with no
// statement of where he is in the run — no segment count, no lives, no
// trophy tally — and, on Stick Drift, no indication that the thing is
// timed at all. Twenty seconds of holding a stick steady with no visible
// clock is not tension, it is just waiting: there is nothing to play
// against. Everything sat in a left-hand column with the right half of a
// 1440px screen empty, which reads as an unfinished web page rather than
// console software.
//
// Deliberately fixed to the viewport rather than part of the mechanic's
// own layout: a mechanic that has to remember to render its own HUD is a
// mechanic that can forget, and the four of them would drift apart.

type Props = {
  /** 1-based, from the segment brief. */
  segment: number;
  /** Total segments in the run, derived from content rather than hardcoded. */
  total: number;
  /** Devil-mode pool. `null` in Kiddie — the row is simply absent, never
   *  rendered as "—", because a life counter that never moves is noise. */
  lives: number | null;
  trophies: number;
  /** Only for mechanics that are actually against a clock (drift). The bar
   *  is a pure CSS animation rather than a per-frame React update: the
   *  compositor owns it, so it cannot stutter under a 30fps capture and it
   *  costs nothing on the main thread while a game loop is running. */
  durationMs?: number;
};

export function GameHud({ segment, total, lives, trophies, durationMs }: Props) {
  return (
    <div className="hud" aria-hidden="true">
      <div className="hud__row">
        <span className="hud__stat">
          <span className="label hud__key">segment</span>
          <span className="hud__value">
            {segment}
            <span className="hud__of"> / {total}</span>
          </span>
        </span>

        {lives !== null && (
          <span className="hud__stat hud__stat--lives">
            <span className="label hud__key">lives</span>
            {/* Pips, not a number: three of something disappearing reads
                instantly at a glance mid-game, where a digit has to be
                read. Also survives the codec — shape, not small text. */}
            <span className="hud__pips">
              {Array.from({ length: 3 }, (_, i) => (
                <span key={i} className={`hud__pip${i < lives ? " is-lit" : ""}`} />
              ))}
            </span>
          </span>
        )}

        <span className="hud__stat">
          <span className="label hud__key">trophies</span>
          <span className="hud__value">{trophies}</span>
        </span>
      </div>

      {durationMs !== undefined && (
        <div className="hud__timer">
          <div
            className="hud__timer-fill"
            style={{ animationDuration: `${durationMs}ms` }}
          />
        </div>
      )}
    </div>
  );
}
