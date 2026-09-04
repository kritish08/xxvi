// Typed wrappers over /api/operator/* — Operator.tsx's own module.
//
// Deliberately NOT added to lib/client.ts: a parallel task is
// reorganising that file, and this task's whole job is to stay
// conflict-free with it. Types are still aliased onto src/api.ts's
// generated `components["schemas"]` (never hand-duplicated) and every
// request body is checked against its generated schema with
// `satisfies`, exactly like lib/client.ts does — same pattern, separate
// file, same safety.
//
// `RunSummary` (GET /api/operator/state) now carries `lives` and
// `trophies` for real (xxvi/api/operator_routes.py, task 29) — `lives`
// straight from `Run.lives` (there is no separate ledger for it),
// `trophies` from the `trophies_earned` ledger via
// `RunRepository.earned_trophies`, the same source `RunView.trophies`
// (run_routes.py) reads, per this project's standing rule that a ledger
// is authoritative over run-state bookkeeping. `lives` is still `int |
// null` (null in Kiddie mode, and before Devil is chosen) — Operator.tsx's
// `run.lives != null` guard on rendering it is about that null, not about
// a missing field anymore.
import type { components } from "../api";

export type GateId = components["schemas"]["GateId"];
export type CodeReleasedMsg = components["schemas"]["CodeReleasedMsg"];

export type OperatorRunSummary = components["schemas"]["RunSummary"];

export type OperatorStateView = {
  live_forced: boolean;
  runs: OperatorRunSummary[];
};

/** Thrown by every `operatorApi.*` call on a non-2xx response. */
export class OperatorApiError extends Error {
  status: number;
  constructor(status: number, path: string) {
    super(`${status} ${path}`);
    this.name = "OperatorApiError";
    this.status = status;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new OperatorApiError(response.status, path);
  }
  return (await response.json()) as T;
}

const post = <T,>(path: string, body?: unknown): Promise<T> =>
  call<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });

export const operatorApi = {
  getState: () => call<OperatorStateView>("/api/operator/state"),

  // The response carries a real gift-card code (xxvi/vault/service.py:
  // "never logged, never persisted" — this HTTP response is the only
  // place it will ever be readable again). A 409 here means someone/
  // something already released it — not an error the caller needs to
  // surface as a code, just a signal to resync from the ledger.
  approveRelease: (runId: number, rewardId: number) =>
    post<CodeReleasedMsg>(
      "/api/operator/approve",
      { run_id: runId, reward_id: rewardId } satisfies components["schemas"]["ApproveRequest"],
    ),

  sendToast: (runId: number, text: string) =>
    post<Record<string, number>>(
      "/api/operator/toast",
      { run_id: runId, text } satisfies components["schemas"]["ToastRequest"],
    ),

  // Only checkpoint_1 / checkpoint_2 can ever actually be locked —
  // xxvi/gates/service.py's GATE_POLICY gives ACTIVATION
  // `max_attempts=None` ("the front door is never bricked"), so this
  // module intentionally never offers `activation` as a gate id from the
  // UI, though the endpoint itself accepts any GateId.
  /** Passes a checkpoint WITHOUT the passphrase and releases its reward.
   *  The rescue route — see xxvi/api/operator_routes.py::bypass_checkpoint
   *  for why a button that defeats the gate is the right trade on the
   *  night. The response carries a real code, same handling rules as
   *  `approve` above. */
  passCheckpoint: (runId: number) =>
    post<components["schemas"]["BypassCheckpointResponse"]>(
      "/api/operator/pass-checkpoint",
      { run_id: runId } satisfies components["schemas"]["BypassCheckpointRequest"],
    ),

  /** Wipes a run back to its first screen, INCLUDING the released-code
   *  ledger — see operator_routes.py::reset_run. The literal "RESET" is the
   *  server's typed confirmation; it is not a formality this client should
   *  quietly supply from a plain boolean elsewhere in the UI. */
  resetRun: (runId: number) =>
    post<components["schemas"]["ResetRunResponse"]>(
      "/api/operator/reset-run",
      { run_id: runId, confirm: "RESET" } satisfies components["schemas"]["ResetRunRequest"],
    ),

  /** Clears the current game without playing it and lands on its question.
   *  Narrow on purpose — it never answers the question and never releases a
   *  code, so unlike the checkpoint bypass it needs no confirmation. */
  skipGame: (runId: number) =>
    post<components["schemas"]["SkipGameResponse"]>(
      "/api/operator/skip-game",
      { run_id: runId } satisfies components["schemas"]["SkipGameRequest"],
    ),

  unlockGate: (runId: number, gate: GateId) =>
    post<Record<string, boolean>>(
      "/api/operator/unlock-gate",
      { run_id: runId, gate } satisfies components["schemas"]["UnlockGateRequest"],
    ),

  forceGoLive: () => post<Record<string, boolean>>("/api/operator/force-golive"),
};
