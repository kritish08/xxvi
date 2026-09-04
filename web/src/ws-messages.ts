// MIRRORS server/xxvi/realtime/messages.py — keep the two files in step.
//
// This is the one contract OpenAPI does not cover: every other client/server
// type comes from generated src/api.ts. WebSocket messages are hand-mirrored
// here instead, so every message type lives in exactly one place on each
// side and the shape stays simple enough to mirror by eye.
//
// The `type` field is the discriminator. It is what makes `ServerMessage`
// safe to parse and to switch on client-side (see lib/ws.ts).

export type RunStateMsg = {
  type: "run_state";
  phase: string;
  segment: number;
  difficulty: string | null;
  cleared_segments: number[];
  released_rewards: number[];
};

export type TrophyPopMsg = {
  type: "trophy_pop";
  trophy_id: string;
  name: string;
  // Python declares `grade: str`, but every value that ever reaches this
  // field is validated at content-load time against
  // content/schema.py::Grade = Literal["bronze", "silver", "gold", "platinum"].
  // The stricter union here is deliberate, not an invention: xxvi/content/schema.py
  // is the single source of truth for the 4 possible values.
  grade: "bronze" | "silver" | "gold" | "platinum";
};

export type CodeReleasedMsg = {
  type: "code_released";
  reward_id: number;
  label: string;
  code: string; // only ever sent on the player channel, after operator approval
};

export type ToastMsg = { type: "toast"; text: string };
export type OperatorPresenceMsg = { type: "operator_presence"; online: boolean };
export type GateResultMsg = {
  type: "gate_result";
  gate: string;
  outcome: string;
  attempts_remaining: number | null;
};

export type ServerMessage =
  | RunStateMsg
  | TrophyPopMsg
  | CodeReleasedMsg
  | ToastMsg
  | OperatorPresenceMsg
  | GateResultMsg;
