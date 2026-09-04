// Typed wrappers over every RUN-PHASE route: everything under
// `/api/run/*`. This module exists so these route strings -- and the
// segment/game/checkpoint vocabulary embedded in them -- never ship in the
// bundle an anonymous visitor downloads for the coming-soon page.
//
// The rule that keeps that true: NOTHING reachable from App.tsx's pre-gate
// render path (ComingSoon, Login) may import this module, even
// transitively. Only Console.tsx and its descendants (shell/*, games/*) do
// -- and Console itself is only ever reached via
// `React.lazy(() => import("../Console"))` in App.tsx, so Vite/Rollup
// code-splits this whole module, and everything that only it needs, into a
// chunk that is never fetched until the gate is open and there's a
// authenticated player to load it for. If a future component imports
// `runApi` eagerly from anywhere the gate itself renders, that guarantee
// silently breaks -- re-run this project's build-output leak test
// (tests/build-leak.test.ts) after touching this file's import graph.
//
// Same rules as lib/client.ts otherwise: every shape below is a type ALIAS
// onto src/api.ts's generated `components["schemas"]`, and every request
// body is checked against its generated schema with `satisfies`, so a
// Pydantic rename breaks `npm run build` here rather than failing silently
// at runtime.
//
// A few shapes here deliberately do NOT match the original task plan and
// were corrected against the real backend (server/xxvi/api/run_routes.py)
// rather than invented — the generated schema is the proof:
//   - Answers are free text (`answer: string`), not a multiple-choice index.
//     `QuestionView` only ever carries `prompt` and `blank` — the `accept`
//     list never reaches the client (see xxvi/content/schema.py::Question).
//   - `RunView.lives` is Devil mode's remaining-life pool (`number | null`;
//     null in Kiddie mode, which has no lives to spend).
//   - A 409 from any mutating route means "you are not in the phase you
//     think you are" (see run_routes.py's per-route phase guards). The
//     right client response is to resync (re-fetch `getRun()`), not retry
//     the same call — retrying a stale phase transition will 409 forever.

import type { components } from "../api";
import { ApiError, call, post } from "./http";

export type QuestionView = components["schemas"]["QuestionView"];
export type RunView = components["schemas"]["RunView"];
export type ProfileView = components["schemas"]["ProfileView"];
export type SegmentBrief = components["schemas"]["SegmentBriefView"];
export type CheckpointResponse = components["schemas"]["CheckpointResponse"];
export type AnswerResponse = components["schemas"]["AnswerResponse"];
export type GameResultPayload = components["schemas"]["GameResultBody"];

// Re-exported for the same reason lib/client.ts re-exports it: existing
// duck-typed/`instanceof` checks in run-phase components import `ApiError`
// from whichever of the two modules they already pull `runApi` from.
export { ApiError };

export const runApi = {
  getRun: () => call<RunView>("/api/run"),
  /** The run so far. Only ever describes cleared segments — see
   *  run_routes.py::profile for why that boundary is the whole point. */
  getProfile: () => call<ProfileView>("/api/run/profile"),
  activate: (code: string) =>
    post<RunView>("/api/run/activate", { code } satisfies components["schemas"]["ActivateRequest"]),
  chooseProfile: () => post<RunView>("/api/run/profile"),
  chooseDifficulty: (difficulty: components["schemas"]["Difficulty"]) =>
    post<RunView>(
      "/api/run/difficulty",
      { difficulty } satisfies components["schemas"]["DifficultyRequest"],
    ),
  installed: () => post<RunView>("/api/run/installed"),
  ackHowto: () => post<RunView>("/api/run/howto"),

  startSegment: () => post<SegmentBrief>("/api/run/segment/start"),
  submitGame: (token: string, result: GameResultPayload) =>
    post<RunView>(
      "/api/run/segment/game",
      { token, result } satisfies components["schemas"]["GameSubmission"],
    ),
  // Free text, normalised server-side against the question's `accept` list
  // (which never reaches the browser) — not a multiple-choice index.
  // Returns `AnswerResponse`, not bare `RunView` — `passed`/`roast` ride
  // along on the same response so Console.tsx can show the wrong-answer
  // roast (Question.roast, content/schema.py) before moving on, without a
  // second round-trip.
  submitAnswer: (answer: string) =>
    post<AnswerResponse>(
      "/api/run/segment/answer",
      { answer } satisfies components["schemas"]["AnswerRequest"],
    ),
  submitCheckpoint: (code: string) =>
    post<CheckpointResponse>(
      "/api/run/checkpoint",
      { code } satisfies components["schemas"]["CheckpointRequest"],
    ),
};
