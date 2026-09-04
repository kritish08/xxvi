// Mounts the mechanic named by the current segment brief, submits its
// result, and hands off. The server — not this component, not the
// mechanic — decides pass or fail (server/xxvi/games/verify.py);
// `passed_client_side` is advisory and structurally ignored there. So this
// file never branches its own rendering on a mechanic's `outcome.passed`;
// it submits and calls `onDone`, and the caller's next read of
// `/api/run` (the same `onDone={refresh}` pattern every other shell
// screen already uses — see Activation.tsx, DifficultySelect.tsx) is what
// actually decides what renders next.

import { useEffect, useRef } from "react";
import { GAMES } from "./registry";
import { GameHud } from "./GameHud";
import { runApi, type SegmentBrief } from "../lib/run-client";
import type { GameOutcome } from "./types";

type HostProps = {
  brief: SegmentBrief;
  onDone: (outcome: { failed: boolean; wiped: boolean }) => void;
  /** Run context for the HUD. Passed in rather than fetched here: GameHost
   *  already has exactly one job and the caller already holds the run. */
  total: number;
  lives: number | null;
  trophies: number;
  difficulty: string | null;
};

export function GameHost({ brief, onDone, total, lives, trophies, difficulty }: HostProps) {
  // Guards the segment token against a double-fire. The token is
  // single-use server-side (xxvi/games/tokens.py, enforced by a unique
  // constraint on consumption) — a second `/api/run/segment/game` call
  // with the same token is a rejected replay, not a harmless retry. A
  // rapid double press/click landing before a mechanic disables its own
  // inputs must still produce exactly one submission.
  const submitted = useRef(false);

  // Hide the mouse cursor for the duration of gameplay. Keyboard is the
  // supported input path (design-system.md §9), and a visible cursor
  // sitting over the console is the fastest way to break the "console
  // software, not a web app" illusion (§2). GameHost is the right place
  // for this: it's mounted for exactly the lifetime of a game, regardless
  // of which mechanic — flagged as unimplementable from the shell's own
  // files in task 16 because the game screens live here, not there.
  useEffect(() => {
    const previous = document.body.style.cursor;
    document.body.style.cursor = "none";
    return () => {
      document.body.style.cursor = previous;
    };
  }, []);

  const Game = GAMES[brief.mechanic];

  const finish = async (outcome: GameOutcome) => {
    if (submitted.current) return;
    submitted.current = true;
    let failed = false;
    let wiped = false;
    try {
      const after = await runApi.submitGame(brief.token, {
        mechanic: brief.mechanic,
        passed_client_side: outcome.passed,
        duration_ms: outcome.durationMs,
        input_count: outcome.inputCount,
        score: outcome.score,
        sequence: outcome.sequence,
      });
      // The SERVER's verdict, not the mechanic's advisory `passed`. A pass
      // ALWAYS leaves the run at `question`, so "still at a game" is the
      // whole test.
      //
      // It used to also require `after.segment === brief.segment`, which
      // was wrong for the one case that matters most: losing the last Devil
      // life wipes the run to segment 1, so the segment DOES change on a
      // failure. The run was then never marked failed, SegmentGame never
      // remounted, and the screen froze on the old segment with its submit
      // guard already tripped and the HUD showing a stale segment beside
      // freshly restored lives. Refreshing the page was the only way out.
      failed = after.phase === "game";
      // A wipe, not a retry: the run has been sent back to the beginning.
      wiped = failed && after.segment !== brief.segment;
    } catch {
      // A 409 here means "you are not in the phase you think you are" —
      // most likely this token was already consumed (single-use) or the
      // run moved on through another path (e.g. the operator's console).
      // Any other failure (a dropped connection, a stale token that
      // expired) gets the same treatment: this is a live one-shot event,
      // and getting stuck on this screen because of a transient failure
      // is worse than moving on and letting the very next `/api/run` read
      // reveal the run's real phase. Resync, never retry — retrying a
      // single-use token can only ever 409 again.
    }
    onDone({ failed, wiped });
  };

  if (!Game) return <p role="alert">unknown mechanic: {brief.mechanic}</p>;

  // Only mechanics that are genuinely against a clock get one. `drift` is
  // the sustained-hold mechanic, and it was the one observed running for
  // twenty seconds with nothing on screen to play against.
  const durationMs = brief.mechanic === "drift" ? brief.params.duration_ms : undefined;

  return (
    <>
      <GameHud
        segment={brief.segment}
        total={total}
        lives={lives}
        trophies={trophies}
        durationMs={durationMs}
      />
      <Game
        seed={brief.seed}
        params={brief.params}
        difficulty={difficulty}
        onFinish={(outcome) => void finish(outcome)}
      />
    </>
  );
}
