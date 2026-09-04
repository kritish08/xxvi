// The operator dashboard. Kritish's only view of the run while his friend
// plays, on a Discord call, on 20 Aug 2026 — screen-shared, so nothing
// here may render a value he hasn't deliberately asked for (see the code
// reveal below). docs/design-system.md is BINDING on everything visual;
// this file only makes behavioural choices the design system doesn't
// cover.
//
// LIVE STATE, READ HONESTLY FROM THE REAL SERVER (not assumed from the
// task brief's reference code): `/api/ws/operator` (xxvi/api/ws_routes.py)
// exists so this dashboard shows up in `hub.operator_online()` — which is
// what lets a connected player see "operator online".
//
// UPDATE (task 29): `run_state`/`trophy_pop` are now genuinely broadcast to
// OPERATOR_CHANNEL too, mirrored from the exact same events the player
// channel gets (xxvi/api/run_routes.py's `_publish`) — so a segment
// advancing, a checkpoint passing, or a trophy popping reaches this screen
// live, not just on the next poll tick. `gate_result` still has no
// server-side sender at all (on EITHER channel — a pre-existing gap, not
// something this task's broadcast touches), and `code_released` is and
// must stay player-channel-only (it can carry a real gift-card code —
// see operator_routes.py's own comment). This dashboard still polls
// tightly (2s) as the safety net regardless: the socket is real now, but a
// dropped or never-firing connection must not freeze this screen, so the
// poll runs independently of the socket's state and the staleness readout
// below reflects the poll's own freshness, not the socket's.
import { useCallback, useEffect, useRef, useState } from "react";
import "./operator.css";
import { connect } from "./lib/ws";
import {
  OperatorApiError,
  operatorApi,
  type GateId,
  type OperatorRunSummary,
  type OperatorStateView,
} from "./lib/operator-api";

// xxvi/core/models.py::Shape defaults (acts=2, segments_per_act=4) — the
// same "2 ACTS · 8 SEGMENTS" the design system's own motif names. Not
// carried on RunSummary, so it is named here rather than guessed per run.
const TOTAL_SEGMENTS = 8;

const REWARD_IDS = [1, 2] as const;
const CLEARABLE_GATES: { id: GateId; label: string }[] = [
  { id: "checkpoint_1", label: "checkpoint 1" },
  { id: "checkpoint_2", label: "checkpoint 2" },
];

const POLL_MS = 2000;
const STALE_AFTER_MS = POLL_MS * 3;

type PendingRelease = { runId: number; rewardId: number };
type KnownCode = { label: string; code: string };

const codeKey = (runId: number, rewardId: number) => `${runId}:${rewardId}`;

export function Operator() {
  const [state, setState] = useState<OperatorStateView | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const [pendingRelease, setPendingRelease] = useState<PendingRelease | null>(null);
  const [releaseBusy, setReleaseBusy] = useState(false);
  const [releaseError, setReleaseError] = useState<string | null>(null);

  // A code is only ever known here because THIS session's own /approve
  // call returned it (see lib/operator-api.ts — the server never lets it
  // be re-fetched). Held in memory only: a reload loses it, on purpose,
  // same as it would be lost anywhere else — nothing about this screen
  // makes that safer to relax.
  const [knownCodes, setKnownCodes] = useState<Record<string, KnownCode>>({});
  const [shownCodes, setShownCodes] = useState<Record<string, boolean>>({});

  const [gateFlash, setGateFlash] = useState<Record<number, string>>({});
  // The checkpoint bypass. Confirm-gated, unlike the one-click attempts
  // reset beside it: this one hands over a gift card without the phrase.
  const [pendingBypass, setPendingBypass] = useState<number | null>(null);
  // Reset. Separated from every other control because it is the only one
  // that destroys the record of a released gift card.
  const [pendingReset, setPendingReset] = useState<number | null>(null);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [bypassBusy, setBypassBusy] = useState(false);
  const [bypassError, setBypassError] = useState<string | null>(null);
  const gateBusyRef = useRef<Set<string>>(new Set());

  const [toastDrafts, setToastDrafts] = useState<Record<number, string>>({});
  const [toastBusy, setToastBusy] = useState<Record<number, boolean>>({});
  const [toastSent, setToastSent] = useState<Record<number, boolean>>({});

  const [pendingGoLive, setPendingGoLive] = useState(false);
  const [goLiveBusy, setGoLiveBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const next = await operatorApi.getState();
      setState(next);
      setLastUpdated(Date.now());
    } catch {
      // The poll is the only real freshness signal this screen has (see
      // header comment). A failed poll leaves the last-known state on
      // screen rather than blanking it — `lastUpdated` simply stops
      // advancing, which the staleness readout below surfaces on its own.
    }
  }, []);

  useEffect(() => {
    void refresh();
    // Real side effect: this is what tells the player's socket
    // `operator_presence: { online: true }`. The message handlers here
    // are otherwise dead today (see header comment) but cost nothing and
    // make a future server-side push work without touching this file again.
    const socket = connect("/api/ws/operator", {
      run_state: () => void refresh(),
      gate_result: () => void refresh(),
      code_released: () => void refresh(),
    });
    const poll = setInterval(refresh, POLL_MS);
    return () => {
      socket.close();
      clearInterval(poll);
    };
  }, [refresh]);

  // A 1Hz text tick for "updated Ns ago" / staleness — not a frame loop,
  // same pattern as ComingSoon.tsx's countdown.
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, []);

  const stale = lastUpdated === null || now - lastUpdated > STALE_AFTER_MS;
  const staleSeconds = lastUpdated === null ? null : Math.max(0, Math.round((now - lastUpdated) / 1000));

  const skipGame = async (runId: number) => {
    const key = `${runId}:skip`;
    if (gateBusyRef.current.has(key)) return;
    gateBusyRef.current.add(key);
    try {
      const result = await operatorApi.skipGame(runId);
      setGateFlash((prev) => ({ ...prev, [runId]: `game skipped — he is on question ${result.segment}` }));
      await refresh();
      setTimeout(() => setGateFlash((prev) => ({ ...prev, [runId]: "" })), 4000);
    } catch {
      setGateFlash((prev) => ({ ...prev, [runId]: "skip failed — is he actually on a game?" }));
    } finally {
      gateBusyRef.current.delete(key);
    }
  };

  const confirmReset = async () => {
    if (pendingReset === null || resetBusy) return;
    setResetBusy(true);
    setResetError(null);
    try {
      await operatorApi.resetRun(pendingReset);
      setPendingReset(null);
      // Any code this dashboard was still showing belongs to a run that no
      // longer exists. Dropping them stops a stale card being read out.
      setKnownCodes({});
      setShownCodes({});
      await refresh();
    } catch (error) {
      setResetError(error instanceof Error ? error.message : "reset failed — try again");
    } finally {
      setResetBusy(false);
    }
  };

  const confirmBypass = async () => {
    if (pendingBypass === null || bypassBusy) return;
    setBypassBusy(true);
    setBypassError(null);
    const runId = pendingBypass;
    try {
      const result = await operatorApi.passCheckpoint(runId);
      // The code comes back here as well as going to his screen. Keep it
      // visible on the dashboard for the same reason `approveRelease` does:
      // it is never persisted or logged anywhere, so this response is the
      // operator's only copy.
      if (result.released) {
        setKnownCodes((prev) => ({
          ...prev,
          [codeKey(runId, result.released!.reward_id)]: {
            label: result.released!.label,
            code: result.released!.code,
          },
        }));
      }
      setPendingBypass(null);
      await refresh();
    } catch (error) {
      // 409 carries the run's real phase/segment — he pressed this because
      // he believed it was somewhere else, so show him what it says.
      const detail = error instanceof Error ? error.message : String(error);
      setBypassError(detail || "bypass failed — try again");
    } finally {
      setBypassBusy(false);
    }
  };

  const confirmRelease = async () => {
    if (!pendingRelease || releaseBusy) return;
    setReleaseBusy(true);
    setReleaseError(null);
    const { runId, rewardId } = pendingRelease;
    try {
      const released = await operatorApi.approveRelease(runId, rewardId);
      setKnownCodes((prev) => ({
        ...prev,
        [codeKey(runId, rewardId)]: { label: released.label, code: released.code },
      }));
      setPendingRelease(null);
      await refresh();
    } catch (error) {
      // AlreadyReleased (409): someone/something beat this click to it.
      // The ledger is now the truth, so just resync — there is no code
      // to show from this call, and pretending otherwise would violate
      // the one rule that matters most here.
      if (error instanceof OperatorApiError && error.status === 409) {
        setPendingRelease(null);
        await refresh();
      } else {
        setReleaseError("release failed — try again");
      }
    } finally {
      setReleaseBusy(false);
    }
  };

  const toggleReveal = (runId: number, rewardId: number) => {
    const key = codeKey(runId, rewardId);
    setShownCodes((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const clearGate = async (runId: number, gate: GateId) => {
    const key = `${runId}:${gate}`;
    if (gateBusyRef.current.has(key)) return; // one-click, but not a double-fire
    gateBusyRef.current.add(key);
    try {
      await operatorApi.unlockGate(runId, gate);
      // NOT "checkpoint 1 cleared" — that was untrue and was read exactly as
      // it sounded. `unlockGate` resets the wrong-attempt LOCKOUT; it does
      // not pass the gate, and the player still has to enter the real code.
      setGateFlash((prev) => ({
        ...prev,
        [runId]: `${gate.replace("_", " ")} attempts reset — he can try again`,
      }));
      await refresh();
      setTimeout(() => setGateFlash((prev) => ({ ...prev, [runId]: "" })), 4000);
    } catch {
      setGateFlash((prev) => ({ ...prev, [runId]: "clear failed — try again" }));
    } finally {
      gateBusyRef.current.delete(key);
    }
  };

  const sendToast = async (runId: number) => {
    const text = (toastDrafts[runId] ?? "").trim();
    if (!text || toastBusy[runId]) return;
    setToastBusy((prev) => ({ ...prev, [runId]: true }));
    try {
      await operatorApi.sendToast(runId, text);
      setToastDrafts((prev) => ({ ...prev, [runId]: "" }));
      setToastSent((prev) => ({ ...prev, [runId]: true }));
      setTimeout(() => setToastSent((prev) => ({ ...prev, [runId]: false })), 3000);
    } finally {
      setToastBusy((prev) => ({ ...prev, [runId]: false }));
    }
  };

  const confirmGoLive = async () => {
    if (goLiveBusy) return;
    setGoLiveBusy(true);
    try {
      await operatorApi.forceGoLive();
      setPendingGoLive(false);
      await refresh();
    } finally {
      setGoLiveBusy(false);
    }
  };

  if (!state) return null;

  return (
    <main className="operator">
      <header className="operator__header">
        <div>
          <p className="label">operator</p>
          <h1 className="operator__title">console</h1>
        </div>
        <div className="operator__status" role="status">
          <span
            className={`operator__status-dot operator__status-dot--${stale ? "stale" : "fresh"}`}
            aria-hidden="true"
          />
          <span className="label">
            {stale
              ? staleSeconds === null
                ? "connecting"
                : `stale · ${staleSeconds}s`
              : "live"}
          </span>
        </div>
      </header>

      <div className="operator__runs">
        {state.runs.length === 0 && <p className="operator__empty">no run yet.</p>}

        {state.runs.map((run) => (
          <RunCard
            key={run.id}
            run={run}
            gateFlash={gateFlash[run.id]}
            onClearGate={(gate) => void clearGate(run.id, gate)}
            onBypassCheckpoint={() => setPendingBypass(run.id)}
            onResetRun={() => setPendingReset(run.id)}
            onSkipGame={() => void skipGame(run.id)}
            atGame={run.phase === "game"}
            atCheckpoint={run.phase === "checkpoint"}
            onRequestRelease={(rewardId) => setPendingRelease({ runId: run.id, rewardId })}
            knownCodes={knownCodes}
            shownCodes={shownCodes}
            onToggleReveal={(rewardId) => toggleReveal(run.id, rewardId)}
            toastDraft={toastDrafts[run.id] ?? ""}
            onToastChange={(value) => setToastDrafts((prev) => ({ ...prev, [run.id]: value }))}
            onToastSubmit={() => void sendToast(run.id)}
            toastBusy={Boolean(toastBusy[run.id])}
            toastSent={Boolean(toastSent[run.id])}
          />
        ))}
      </div>

      {/* Force go-live: deliberately isolated from the routine controls
          above by a full section break, and behind its own confirm — it
          skips the timed unlock for everyone, at once, and cannot be
          undone by clicking it again. */}
      <footer className="operator__danger">
        <p className="label">rescue path · rarely used</p>
        {state.live_forced ? (
          <p className="operator__forced">live: forced by operator</p>
        ) : (
          <button
            type="button"
            className="operator__golive-btn"
            onClick={() => setPendingGoLive(true)}
          >
            force go-live
          </button>
        )}
      </footer>

      {pendingRelease && (
        <div role="dialog" aria-modal="true" className="operator__confirm">
          <p className="label">confirm release</p>
          <p className="operator__confirm-line">
            release reward {pendingRelease.rewardId} for run {pendingRelease.runId}?
          </p>
          <p className="operator__confirm-warning">
            this sends a real gift-card code and cannot be undone. the code is shown once, here,
            only after you reveal it — copy it before leaving this screen.
          </p>
          {releaseError && (
            <p role="alert" className="operator__confirm-error">
              {releaseError}
            </p>
          )}
          <div className="operator__confirm-actions">
            <button
              type="button"
              autoFocus
              disabled={releaseBusy}
              onClick={() => void confirmRelease()}
            >
              confirm release
            </button>
            <button
              type="button"
              className="operator__confirm-cancel"
              disabled={releaseBusy}
              onClick={() => setPendingRelease(null)}
            >
              cancel
            </button>
          </div>
        </div>
      )}

      {pendingReset !== null && (
        <div role="dialog" aria-modal="true" className="operator__confirm operator__confirm--danger">
          <p className="label">confirm reset</p>
          <p className="operator__confirm-line">
            wipe this run back to the very first screen?
          </p>
          <p className="operator__confirm-warning">
            deletes every trophy, answer and event — AND the record that a gift card
            was released, so an already-given code becomes releasable again. for
            testing. it cannot be undone.
          </p>
          {resetError && (
            <p role="alert" className="operator__confirm-error">
              {resetError}
            </p>
          )}
          <div className="operator__confirm-actions">
            <button type="button" autoFocus disabled={resetBusy} onClick={() => void confirmReset()}>
              confirm reset
            </button>
            <button
              type="button"
              className="operator__confirm-cancel"
              disabled={resetBusy}
              onClick={() => { setPendingReset(null); setResetError(null); }}
            >
              cancel
            </button>
          </div>
        </div>
      )}

      {pendingBypass !== null && (
        <div role="dialog" aria-modal="true" className="operator__confirm operator__confirm--danger">
          <p className="label">confirm checkpoint bypass</p>
          <p className="operator__confirm-line">
            let him past this checkpoint without the phrase, and release its gift card now?
          </p>
          <p className="operator__confirm-warning">
            this is the whole point of the phrase. only use it if he cannot get the
            code in and the night is stalling. it cannot be undone.
          </p>
          {bypassError && (
            <p role="alert" className="operator__confirm-error">
              {bypassError}
            </p>
          )}
          <div className="operator__confirm-actions">
            <button type="button" autoFocus disabled={bypassBusy} onClick={() => void confirmBypass()}>
              confirm bypass
            </button>
            <button
              type="button"
              className="operator__confirm-cancel"
              disabled={bypassBusy}
              onClick={() => { setPendingBypass(null); setBypassError(null); }}
            >
              cancel
            </button>
          </div>
        </div>
      )}

      {pendingGoLive && (
        <div role="dialog" aria-modal="true" className="operator__confirm operator__confirm--danger">
          <p className="label">confirm force go-live</p>
          <p className="operator__confirm-line">
            skip the timed midnight unlock and go live for every player right now?
          </p>
          <p className="operator__confirm-warning">
            only use this if the automatic unlock did not fire. this cannot be undone.
          </p>
          <div className="operator__confirm-actions">
            <button type="button" autoFocus disabled={goLiveBusy} onClick={() => void confirmGoLive()}>
              confirm force go-live
            </button>
            <button
              type="button"
              className="operator__confirm-cancel"
              disabled={goLiveBusy}
              onClick={() => setPendingGoLive(false)}
            >
              cancel
            </button>
          </div>
        </div>
      )}
    </main>
  );
}

type RunCardProps = {
  run: OperatorRunSummary;
  gateFlash: string | undefined;
  onClearGate: (gate: GateId) => void;
  onBypassCheckpoint: () => void;
  onResetRun: () => void;
  onSkipGame: () => void;
  /** Only offered while a game is actually in play — the route refuses
   *  otherwise, and a button that can only 409 is worse than no button. */
  atGame: boolean;
  /** Only offered when the run is actually at a checkpoint — the route
   *  refuses otherwise, and a live button that always 409s is worse than
   *  no button at the moment he needs to trust it. */
  atCheckpoint: boolean;
  onRequestRelease: (rewardId: number) => void;
  knownCodes: Record<string, KnownCode>;
  shownCodes: Record<string, boolean>;
  onToggleReveal: (rewardId: number) => void;
  toastDraft: string;
  onToastChange: (value: string) => void;
  onToastSubmit: () => void;
  toastBusy: boolean;
  toastSent: boolean;
};

function RunCard({
  run,
  gateFlash,
  onClearGate,
  onBypassCheckpoint,
  onResetRun,
  onSkipGame,
  atGame,
  atCheckpoint,
  onRequestRelease,
  knownCodes,
  shownCodes,
  onToggleReveal,
  toastDraft,
  onToastChange,
  onToastSubmit,
  toastBusy,
  toastSent,
}: RunCardProps) {
  const difficultyClass = run.difficulty ? `operator__difficulty--${run.difficulty}` : "";

  return (
    <section className="operator__run" aria-label={`run ${run.id}`}>
      <div className="operator__run-head">
        <span className={`operator__difficulty ${difficultyClass}`}>{run.difficulty ?? "—"}</span>
        <h2 className="operator__phase">{run.phase}</h2>
      </div>

      <dl className="operator__stats">
        <div className="operator__stat">
          <dt className="label">segment</dt>
          <dd>
            {run.segment} · {TOTAL_SEGMENTS}
          </dd>
        </div>
        <div className="operator__stat">
          <dt className="label">cleared</dt>
          <dd>
            {run.cleared_segments.length} · {TOTAL_SEGMENTS}
          </dd>
        </div>
        {/* `lives` is real now (xxvi/api/operator_routes.py, task 29:
            Run.lives), but still genuinely `null` in Kiddie mode and
            before Devil is chosen (persistence/models.py) — that guard
            stays for that reason, not because the field might be
            missing. The single most useful number on this screen during
            a Devil run. */}
        {run.lives != null && (
          <div className="operator__stat">
            <dt className="label">lives</dt>
            <dd>{run.lives}</dd>
          </div>
        )}
        {(run.trophies?.length ?? 0) > 0 && (
          <div className="operator__stat">
            <dt className="label">trophies</dt>
            <dd>{run.trophies.length}</dd>
          </div>
        )}
      </dl>

      {/* Gate clear: one click, no confirm, on purpose — this is what he
          reaches for at the exact moment the player is frustrated. */}
      <div className="operator__gates">
        {/* Says what the buttons DO. The old wording ("locked at a
            checkpoint?" over "clear checkpoint 1") read as "let him
            through", which is not what it does — it resets the three-strike
            lockout so he can keep trying. He still needs the code. */}
        <p className="label">locked out after three wrong tries?</p>
        <div className="operator__gate-row">
          {CLEARABLE_GATES.map((gate) => (
            <button
              key={gate.id}
              type="button"
              className="operator__gate-btn"
              onClick={() => onClearGate(gate.id)}
            >
              reset {gate.label} attempts
            </button>
          ))}
        </div>
        {gateFlash && (
          <p role="status" className="operator__gate-flash">
            {gateFlash}
          </p>
        )}

        {/* The escape hatch, deliberately separated from the reset above:
            that one lets him keep trying, this one gives up on the phrase
            entirely and hands over the card. Only shown at a checkpoint. */}
        {atCheckpoint && (
          <>
            <p className="label operator__gate-label">can't get the code in at all?</p>
            <button
              type="button"
              className="operator__gate-btn operator__gate-btn--danger"
              onClick={onBypassCheckpoint}
            >
              pass checkpoint without the code
            </button>
          </>
        )}

        {atGame && (
          <>
            <p className="label operator__gate-label">stuck on the game itself?</p>
            <button type="button" className="operator__gate-btn" onClick={onSkipGame}>
              skip this game
            </button>
          </>
        )}

        {/* Testing tool, deliberately last and deliberately alone. */}
        <p className="label operator__gate-label">testing</p>
        <button
          type="button"
          className="operator__gate-btn operator__gate-btn--reset"
          onClick={onResetRun}
        >
          reset this run
        </button>
      </div>

      <div className="operator__rewards">
        {REWARD_IDS.map((rewardId) => {
          const released = run.released_rewards.includes(rewardId);
          const key = codeKey(run.id, rewardId);
          const known = knownCodes[key];
          const shown = Boolean(shownCodes[key]);

          return (
            <div className="operator__reward" key={rewardId}>
              <div className="operator__reward-row">
                <span className="label">reward {rewardId}</span>
                <span
                  className={`operator__reward-tag operator__reward-tag--${released ? "released" : "pending"}`}
                >
                  {released ? "released" : "pending"}
                </span>
                {!released && (
                  <button
                    type="button"
                    className="operator__release-btn"
                    onClick={() => onRequestRelease(rewardId)}
                  >
                    release reward {rewardId}
                  </button>
                )}
                {released && known && (
                  <button
                    type="button"
                    className="operator__reveal-btn"
                    onClick={() => onToggleReveal(rewardId)}
                  >
                    {shown ? "hide code" : "reveal code"}
                  </button>
                )}
              </div>
              {released && known && shown && (
                <p className="operator__code" data-testid={`code-${rewardId}`}>
                  {known.code}
                </p>
              )}
              {released && !known && (
                <p className="operator__reward-note">
                  released before this dashboard saw it — the player already has the code.
                </p>
              )}
            </div>
          );
        })}
      </div>

      <form
        className="operator__toast-form"
        onSubmit={(event) => {
          event.preventDefault();
          onToastSubmit();
        }}
      >
        <label className="label" htmlFor={`toast-${run.id}`}>
          say something
        </label>
        <div className="operator__toast-row">
          <input
            id={`toast-${run.id}`}
            className="operator__toast-input"
            value={toastDraft}
            onChange={(event) => onToastChange(event.target.value)}
            placeholder="a message for his screen"
            disabled={toastBusy}
          />
          <button type="submit" disabled={toastBusy || !toastDraft.trim()}>
            send
          </button>
        </div>
        {toastSent && (
          <p role="status" className="operator__toast-sent">
            sent
          </p>
        )}
      </form>
    </section>
  );
}
