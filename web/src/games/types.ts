// Shared contract every mechanic (simon, update, drift, trophy_run) is
// built against. GameHost is the only thing that constructs GameProps and
// the only thing that reads a GameOutcome — a mechanic component never
// talks to the network directly (see GameHost.tsx).

export type GameOutcome = {
  /** The mechanic's own read of whether the player succeeded. Advisory
   *  only — GameHost forwards it to the server as `passed_client_side`,
   *  and the server's verdict (server/xxvi/games/verify.py) is what
   *  actually decides pass or fail. Never branch UI on this value. */
  passed: boolean;
  durationMs: number;
  inputCount: number;
  score: number;
  /** Mechanic-specific payload the server re-derives and compares against
   *  (e.g. Simon's entered face-button sequence, checked against
   *  simon_sequence(seed, length) — see verify_result). Empty array for
   *  mechanics that don't need one. */
  sequence: number[];
};

export type GameProps = {
  seed: string;
  /** "kiddie" | "devil" | null. Optional so mechanics that do not care are
   *  unaffected. Simon uses it to size its per-attempt allowance — a single
   *  mistyped face should not cost a whole segment. */
  difficulty?: string | null;
  params: Record<string, number>;
  onFinish: (outcome: GameOutcome) => void;
};
