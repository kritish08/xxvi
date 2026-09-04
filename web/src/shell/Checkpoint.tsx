// The checkpoint code gate between acts. Three wrong attempts locks it —
// but he is on a call with the one person who can clear it instantly, so
// "locked" must never read as a dead end. That is this component's whole
// reason for existing: whatever else is right or wrong here, the locked
// state has to say, in plain words, "tell kritish, he can clear it."
//
// `xxvi/gates/service.py::GateService.submit` returns `outcome: "wrong"`
// even on the EXACT attempt that pushes the gate over its 3-attempt limit
// (the row's `locked` flag flips true in that same write, but the verdict
// for that specific response is still "wrong" — only the NEXT attempt sees
// the gate already locked and gets `outcome: "locked"` back). So a client
// that only special-cases `outcome === "locked"` shows "wrong. 0 attempts
// left." with a still-enabled submit button — exactly the dead-end-shaped
// gap this screen exists to avoid. Treating `attempts_remaining === 0` as
// equivalent to locked, regardless of what `outcome` says, closes that gap
// one attempt earlier than waiting for the server to say the word.
//
// IMPORTANT — the form stays enabled even while `isLocked`. This was
// verified against a real running server (see task-20-report.md): once
// locked, the client has no signal for when Kritish clears it server-side
// — there is no push notification for that today, only "tell him, he
// clears it, he tells you to try again." If the form disabled itself here,
// that "try again" would have nothing to press: a client-side dead end
// bolted onto the server's already-not-a-dead-end design. Resubmitting
// while genuinely still locked is free, not a wasted attempt —
// `GateService.submit` checks `row.locked` before it ever compares the
// candidate or records a failure — so leaving the form live costs nothing
// and is what actually lets the "he can clear it" promise resolve.
//
// Server authority: a 409 here means "you are not at a checkpoint" (a
// stale view of run state) — the fix is to resync (`onDesync`, which
// Console.tsx wires to its own `refresh()`), never to retry the same
// request. `busy` (checked at the top of `submit`, not only via the
// button's `disabled`, since a disabled submit button does not reliably
// stop a `<form>`'s Enter-key submission in every browser) guards against
// a double-fire on the same code.

import { useState, type FormEvent } from "react";
import { runApi, type CheckpointResponse } from "../lib/run-client";
import "./checkpoint.css";

// Duck-typed rather than `instanceof ApiError`: the prescribed test for
// this component (web/tests/checkpoint.test.tsx, per task-20-brief.md)
// mocks the whole `../lib/run-client` module down to `{ runApi: { ... } }`,
// which does not re-export `ApiError` — an `instanceof` check against that
// undefined binding would throw the moment any submit ever rejected.
// `lib/http.ts`'s `ApiError` always carries a numeric `status`; checking
// structurally is equally correct against the real class and immune to
// how a test happens to shape its mock.
function is409(error: unknown): boolean {
  return typeof error === "object" && error !== null && "status" in error && (error as { status: unknown }).status === 409;
}

type Release = NonNullable<CheckpointResponse["released"]>;

type Props = {
  onPassed: (release: Release | null) => void;
  /** Called on a 409 ("not at a checkpoint" — stale view). Console.tsx
   *  wires this to its own `refresh()` so the screen resyncs to whatever
   *  phase the server actually has it in, instead of retrying a request
   *  that will 409 forever. */
  onDesync: () => void;
  /** The operator's name (`ContentView.operator`, server/xxvi/content/
   *  schema.py::RunConfig.operator). Defaults to the schema's own
   *  "the operator" so this reads sensibly even if `content` hasn't
   *  loaded yet by the time this screen mounts. */
  operator?: string;
};

export function Checkpoint({ onPassed, onDesync, operator = "the operator" }: Props) {
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<CheckpointResponse | null>(null);
  const [busy, setBusy] = useState(false);

  // See module comment: the exact wrong-attempt that reaches 0 remaining
  // still comes back as outcome "wrong", not "locked" — this is the
  // moment that must read as "locked" to him regardless.
  const isLocked = status?.outcome === "locked" || status?.attempts_remaining === 0;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    // Deliberately NOT gated on `isLocked` — see the module comment.
    if (busy || !code.trim()) return;
    setBusy(true);
    try {
      const response = await runApi.submitCheckpoint(code.trim().toUpperCase());
      setStatus(response);
      if (response.outcome === "ok") onPassed(response.released);
    } catch (error) {
      if (is409(error)) {
        onDesync();
      } else {
        throw error;
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="checkpoint">
      <p className="label checkpoint__label">checkpoint</p>
      {/* "segment cleared" was wrong and it confused the first person to
          reach this screen: he has just cleared FOUR segments — a whole act
          — and this is the gate between acts, not the end of one segment.
          It also never said what the gate is for, so the screen read as an
          unexplained password prompt appearing out of nowhere. */}
      <h2 className="checkpoint__title">act cleared</h2>
      <p className="checkpoint__line">
        a gift card is waiting behind this. {operator} has the code — ask for it.
      </p>

      <form className="checkpoint__form" onSubmit={(event) => void submit(event)}>
        <input
          className="checkpoint__input"
          aria-label="code"
          value={code}
          onChange={(event) => setCode(event.target.value.toUpperCase())}
          disabled={busy}
          autoFocus
          autoComplete="off"
          spellCheck={false}
        />
        <button type="submit" disabled={busy || !code.trim()}>
          submit
        </button>
      </form>

      {status?.outcome === "wrong" && !isLocked && (
        <p className="checkpoint__status" role="status">
          wrong. {status.attempts_remaining} {status.attempts_remaining === 1 ? "attempt" : "attempts"} left.
        </p>
      )}

      {/* A lockout must never read as a dead end — he is on a call with
          the one person who can clear it, and the copy says so in plain
          words, not "locked" and nothing else. */}
      {isLocked && (
        <p className="checkpoint__alert" role="alert">
          locked. tell {operator} — they can clear it from their end right now.
        </p>
      )}
    </section>
  );
}
