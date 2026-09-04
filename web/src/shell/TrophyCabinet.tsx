// The screen he screenshots. A poster, not a list — platinum gets a hero
// slot, everything else is a grid of flat cards grouped by grade so the
// escalation reads at a glance even with the sound (and the codec's fine
// detail) gone.
//
// Masking is already done server-side by GET /api/content (see
// server/xxvi/api/content_routes.py: a hidden trophy's `name` comes back as
// "???" until it's in the account's earned set). This component does not
// re-implement or undo that — it trusts `trophy.name` exactly as given and
// only ever asks "is this the one that's still hidden" to decide whether to
// show the lock treatment, never to re-derive or hide a name itself.
//
// Re-fetching /api/content when the earned count changes (so a freshly
// popped hidden trophy reveals its real name) is the caller's job: this
// component is presentational, driven entirely by the `trophies`/`earned`
// props, per the task's fixed interface
// (`<TrophyCabinet trophies earned closing />`). Task 17 does not own
// App.tsx/Console.tsx, so it cannot wire that fetch itself — whoever mounts
// this component (Task 15/16's shell, at merge) re-fetches `/api/content`
// on every `trophy_pop` WS message and passes the new list down. Because
// this is a plain function component with no internal fetch state, it
// re-renders correctly the moment fresher props arrive; there is nothing
// else it needs to do to support that.

import { TrophyIcon, type Grade } from "./TrophyIcon";
import { standardTrophyCount } from "../lib/trophy-content";
import "./trophy.css";

type Trophy = { id: string; name: string; grade: string; hidden: boolean };

type Props = {
  trophies: Trophy[];
  earned: string[];
  closing: string;
  /** Moves on to the send-off. Optional so the component stays usable (and
   *  testable) as the pure presentational thing it has always been. */
  onDone?: () => void;
};

const GRADE_RANK: Record<string, number> = { platinum: 0, gold: 1, silver: 2, bronze: 3 };

function rank(grade: string): number {
  return GRADE_RANK[grade] ?? 4;
}

function TrophyTile({ trophy, owned }: { trophy: Trophy; owned: boolean }) {
  const masked = trophy.hidden && !owned;
  return (
    <li className={`trophy trophy--${trophy.grade}${owned ? " trophy--owned" : " trophy--locked"}`}>
      <span className="trophy__icon">
        <TrophyIcon grade={trophy.grade} />
      </span>
      {/* Name gets its own row at full tile width — the grade/status line
          used to share a row with it and, on a narrow tile, squeezed the
          name down to a single character before ellipsis ever kicked in.
          A poster only reads as a poster if the names are legible. */}
      <span className="trophy__text">
        <span className="trophy__name">{masked ? "???" : trophy.name}</span>
        <span className="trophy__meta">
          {/* Grade written out, never colour-only (§9) — also doubles as
              the label a masked hidden trophy can still show without
              spoiling it. */}
          <span className="trophy__grade label">{trophy.grade}</span>
          {!owned && !masked && <span className="trophy__lock label">· locked</span>}
          {masked && <span className="trophy__lock label">· hidden</span>}
        </span>
      </span>
    </li>
  );
}

export function TrophyCabinet({ trophies, earned, closing, onDone }: Props) {
  const held = new Set(earned);
  // Shared with the library card (shell/Install.tsx) via
  // lib/trophy-content.ts, so the two surfaces can't silently disagree on
  // "how many trophies are there."
  const standardTotal = standardTrophyCount(trophies);
  const standardOwned = trophies.filter((t) => !t.hidden && held.has(t.id)).length;
  const percent = standardTotal ? Math.round((standardOwned / standardTotal) * 100) : 0;
  const totalOwned = trophies.filter((t) => held.has(t.id)).length;

  const platinum = trophies.find((t) => t.grade === "platinum");
  const rest = trophies
    .filter((t) => t.id !== platinum?.id)
    .slice()
    .sort((a, b) => rank(a.grade) - rank(b.grade));

  return (
    <section className="cabinet">
      <header className="cabinet__header">
        <p className="label">XXVI · trophies</p>
        <h1 className="cabinet__title">trophy cabinet</h1>
        <p className="cabinet__stat">
          <span className="cabinet__percent">{percent}%</span>
          <span className="label cabinet__statLabel">
            {standardOwned} of {standardTotal} · {totalOwned} of {trophies.length} total
          </span>
        </p>
      </header>

      {platinum && (
        <ul className="cabinet__hero">
          <TrophyTile trophy={platinum} owned={held.has(platinum.id)} />
        </ul>
      )}

      <ul className="cabinet__grid">
        {rest.map((trophy) => (
          <TrophyTile key={trophy.id} trophy={trophy} owned={held.has(trophy.id)} />
        ))}
      </ul>

      {closing && <p className="cabinet__closing">{closing}</p>}
      {onDone && (
        <div className="cabinet__end">
          <button onClick={onDone}>finish</button>
        </div>
      )}
    </section>
  );
}

export type { Grade };
