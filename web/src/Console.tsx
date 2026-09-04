// The console shell. Dispatches on RunView.phase; Boot precedes all of it
// client-side (the server has no concept of "booted"). Tasks 18-20 own
// everything past howto; this file (task 20) wires the game/question/
// checkpoint/complete phases that Tasks 15-17 left as a placeholder.
//
// GameHost/registry (task 18) are consumed here but not owned. This file
// also finishes two things only Console.tsx can, since it's the only file
// with both the WS connection and a place to mount an overlay:
//   - Mounting `TrophyToast` at all (task 17 built and tested it; nothing
//     mounted it) and feeding it from `trophy_pop` WS messages.
//   - Wiring `TrophyToast`'s `onSting` to `duckForSting` (lib/audio.ts's
//     `buildEngine` already routes the sting's own audio through the real
//     SFX bus — see its "TROPHY STING WIRING" comment; this is the other
//     half, MUSIC ducking under the sting, task 18 flagged as blocked on
//     this file existing).

import { useCallback, useEffect, useRef, useState } from "react";
import "./console.css";
import { Activation } from "./shell/Activation";
import { Boot } from "./shell/Boot";
import { Checkpoint } from "./shell/Checkpoint";
import { CodeReveal } from "./shell/CodeReveal";
import { DifficultySelect } from "./shell/DifficultySelect";
import { HowToPlay } from "./shell/HowToPlay";
import { Install } from "./shell/Install";
import { ProfileSelect } from "./shell/ProfileSelect";
import { Question } from "./shell/Question";
import { Goodbye } from "./shell/Goodbye";
import { Profile } from "./shell/Profile";
import { Roast } from "./shell/Roast";
import { TrophyCabinet } from "./shell/TrophyCabinet";
import { Loading } from "./Loading";
import { TrophyToast } from "./shell/TrophyToast";
import { OperatorToast, type QueuedOperatorToast } from "./shell/OperatorToast";
import { GameHost } from "./games/GameHost";
import { api, type ContentView } from "./lib/client";
import {
  runApi,
  type CheckpointResponse,
  type RunView,
  type SegmentBrief,
} from "./lib/run-client";
import { connect } from "./lib/ws";
import {
  isAudioUnlocked,
  type BedState,
  duckForSting,
  playNarration,
  playOperatorToastSound,
  setBedState,
  toggleMute,
} from "./lib/audio";
import { isFullscreen, onFullscreenChange, requestFullscreen } from "./lib/fullscreen";
import type { TrophyPopMsg } from "./ws-messages";

// Phases that get the calm, present pad (design-system.md §6.5's table).
// "difficulty" is deliberately absent — DifficultySelect drives its own
// live kiddie/devil preview on hover/focus, and re-asserting "calm" here
// on every render would fight that preview.
const CALM_PHASES = new Set(["activation", "profile", "install", "howto"]);

/** The ambient bed for every non-calm, non-difficulty phase (§6.5's
 *  table). Shared between the main phase effect and the life-lost dip's
 *  recovery timer below, so "what should the bed be right now" has one
 *  answer, not two copies that can drift. */
function bedForPhase(phase: string): BedState {
  if (phase === "question") return "question";
  if (phase === "checkpoint") return "checkpoint";
  return "game"; // game, complete, and any future phase default here
}

type Release = NonNullable<CheckpointResponse["released"]>;

/** Task 20's slice of the "game" phase: fetch a fresh segment brief once,
 *  then hand off to Task 18's harness. `GameHost` decides pass/fail
 *  server-side (see its own contract) and calls `onDone` either way — this
 *  component's only job is getting a brief onto the screen. */
function SegmentGame({
  onDone,
  onDesync,
  total,
  lives,
  trophies,
  difficulty,
}: {
  onDone: (outcome: { failed: boolean; wiped: boolean }) => void;
  onDesync: () => void;
  total: number;
  lives: number | null;
  trophies: number;
  difficulty: string | null;
}) {
  const [brief, setBrief] = useState<SegmentBrief | null>(null);

  // `onDesync` is a fresh closure on every Console render, so putting it in
  // the dependency array below re-ran this effect on EVERY parent render --
  // the 15s poll, any WebSocket message, an audio state change. Each re-run
  // fetched ANOTHER segment token, and GameHost then submitted the newest
  // one: a game played for 12.8s handed the server a token issued 0.1s
  // earlier, which correctly refused it as claiming more play time than the
  // token had existed. That is the "I finished it and it said WRONG".
  // Observed as three /segment/start calls in one game, the last of them 11
  // seconds into play. Held in a ref so the effect can own an empty
  // dependency array and fetch exactly one brief per mount.
  const desyncRef = useRef(onDesync);
  desyncRef.current = onDesync;

  useEffect(() => {
    let cancelled = false;
    void runApi
      .startSegment()
      .then((b) => {
        if (!cancelled) setBrief(b);
      })
      .catch(() => {
        // 409 "not at a game": the run has already moved on (the usual
        // cause is this component mounting for a segment that was just
        // cleared). There was no catch here at all, so the rejection went
        // unhandled and `brief` stayed null forever -- the screen sat on
        // "loading segment…" and accepted no input, which is exactly the
        // hang reported after completing a sequence. Resync and let the
        // run's real phase decide what renders.
        if (!cancelled) desyncRef.current();
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!brief) return <p className="label placeholder">loading segment&hellip;</p>;
  return (
    <GameHost
      brief={brief}
      onDone={onDone}
      total={total}
      lives={lives}
      trophies={trophies}
      difficulty={difficulty}
    />
  );
}

// A 409 from any mutating /api/run/* route means "you are not in the phase
// you think you are" (a stale client view) — the fix is to resync
// (re-fetch GET /api/run), never to retry the same request. Duck-typed
// against `ApiError`'s shape rather than `instanceof` so this has no
// runtime dependency on how a test happens to mock `lib/client` (see
// shell/Checkpoint.tsx's identical helper and its own comment on why).
function isConflict(error: unknown): boolean {
  return typeof error === "object" && error !== null && "status" in error && (error as { status: unknown }).status === 409;
}

export function Console() {
  const [run, setRun] = useState<RunView | null>(null);
  const [content, setContent] = useState<ContentView | null>(null);
  const [booted, setBooted] = useState(false);
  const [operatorOnline, setOperatorOnline] = useState(false);
  const [fullscreen, setFullscreen] = useState(isFullscreen());
  const [muted, setMutedState] = useState(false);
  const [audioReady, setAudioReady] = useState(false);
  const [trophyQueue, setTrophyQueue] = useState<TrophyPopMsg[]>([]);
  // Live messages from the operator (POST /api/operator/toast ->
  // ToastMsg on this same WS channel). A separate queue/component from
  // trophyQueue/TrophyToast on purpose — see shell/OperatorToast.tsx's
  // header comment on why the two must never be visually confusable, even
  // though they share the same underlying `.toast` primitive. The server
  // sends no id per message, so one is stamped here on arrival (mirrors
  // trophy_pop's server-supplied trophy_id, which TrophyToast keys on).
  const [toastQueue, setToastQueue] = useState<QueuedOperatorToast[]>([]);
  const nextToastId = useRef(0);
  // The gift-card reveal. Rendered as an overlay above whatever screen the
  // run has already moved on to underneath (the server doesn't wait for
  // this to be dismissed) — cleared only by CodeReveal's own "continue"
  // button, never a timer (design-system.md's "do not auto-dismiss it").
  const [release, setRelease] = useState<Release | null>(null);
  // A wrong answer's roast (Question.roast, content/schema.py) — held here,
  // not shown inline on Question itself, because the server has ALREADY
  // moved the phase to "game" (a full segment restart) by the time the
  // response with the roast on it comes back. Rendered as an overlay, same
  // "don't move on until he dismisses it" rule as `release` above — see
  // Roast.tsx's header comment for why this pause is deliberate, not
  // incidental.
  const [roast, setRoast] = useState<string | null>(null);
  // The last wrong-but-survivable answer, held so the question can come back
  // with his own text still in the box for editing. Doubles as the remount
  // signal: a miss leaves the run's phase at "question" with the same
  // `run.question` object, so — exactly like the `game -> game` case
  // below — React would keep the SAME `Question` instance mounted, with its
  // `locked` state still true from the submission that just failed. The
  // form would be dead and the run unfinishable. `miss.count` is part of
  // Question's `key` for that reason; it is not decorative.
  const [miss, setMiss] = useState<{ count: number; answer: string } | null>(null);
  // A failed game used to restart instantly and silently — the screen just
  // reset, with nothing to tell him he had lost. This holds the beat.
  const [gameFailed, setGameFailed] = useState<string | null>(null);
  // The profile overlay. Purely informational, so unlike the roast and the
  // code reveal it never blocks the run — it opens and closes over it.
  const [profileOpen, setProfileOpen] = useState(false);
  // The send-off. The cabinet is the screen he screenshots; this is the one
  // that ends the night. Held here rather than inside TrophyCabinet so the
  // cabinet stays presentational.
  const [sayingGoodbye, setSayingGoodbye] = useState(false);
  const [recipient, setRecipient] = useState("");
  // Once the console is off, the chrome goes with it. A mute button and a
  // profile button floating over a dead screen say "web page", which is the
  // one impression the whole build exists to avoid.
  const [poweredOff, setPoweredOff] = useState(false);
  // A failed game moves the run's phase `game -> game` (a Devil in-place
  // retry, or a Kiddie replay). React does not remount `SegmentGame` just
  // because the switch still renders it in the same position, so without
  // forcing a fresh `key` the retry would (a) never re-run SegmentGame's
  // fetch-a-brief effect and (b) inherit GameHost's already-tripped
  // `submitted` ref, which makes its next `finish()` call a silent no-op
  // that never calls `onDone()` — a permanent softlock. Bumped once per
  // game attempt (on every `onDone` from the game phase, pass or fail) and
  // used as `SegmentGame`'s `key` below so every attempt gets a real mount.
  const [gameAttempt, setGameAttempt] = useState(0);

  const refresh = useCallback(async () => setRun(await runApi.getRun()), []);

  useEffect(() => {
    void refresh();
    const socket = connect("/api/ws/player", {
      run_state: () => void refresh(),
      operator_presence: (m) => setOperatorOnline(m.online),
      trophy_pop: (m) => setTrophyQueue((queue) => [...queue, m]),
      code_released: (m) => setRelease(m),
      toast: (m) => setToastQueue((queue) => [...queue, { ...m, id: nextToastId.current++ }]),
    });
    // The socket is cosmetic; polling is the safety net if it dies.
    const poll = setInterval(refresh, 15_000);
    return () => {
      socket.close();
      clearInterval(poll);
    };
  }, [refresh]);

  // GET /api/content is public and carries trophy names/copy — re-fetched
  // whenever the earned-trophy count changes, which is what un-masks a
  // hidden trophy's real name after it pops (masking is server-side; see
  // shell/TrophyCabinet.tsx's own comment on why it never re-derives that
  // itself).
  useEffect(() => {
    void api.getContent().then(setContent);
  }, [run?.trophies.length]);

  // Esc exits fullscreen and that isn't overridable (design-system.md §9) —
  // this only ever *observes* the change to offer a quiet way back in, it
  // never fights it.
  useEffect(() => onFullscreenChange(setFullscreen), []);

  // The goodbye screen says his name, and only the profile route carries it.
  // Fetched once, when the run is actually finished.
  useEffect(() => {
    if (run?.phase !== "complete" || recipient) return;
    void runApi
      .getProfile()
      .then((p) => setRecipient(p.recipient))
      .catch(() => undefined); // a nameless send-off beats no send-off
  }, [run?.phase, recipient]);

  // The difficulty palette persists across every screen after it's chosen
  // (DifficultySelect previews it live before that; see its own comment).
  useEffect(() => {
    if (run?.difficulty === "devil") {
      document.documentElement.dataset.palette = "devil";
    } else {
      delete document.documentElement.dataset.palette;
    }
  }, [run?.difficulty]);

  // Ambient bed per state (§6.5's table): calm phases, "question" (bed
  // thins -6dB), "checkpoint" (resolves upward), and "game" as the
  // fallback for everything else that isn't difficulty select (which
  // drives its own live preview — see DifficultySelect.tsx).
  useEffect(() => {
    if (!booted || !run) return;
    if (run.phase === "difficulty") return;
    // DEVIL STAYS INTENSE THE WHOLE RUN. The bed used to drop to the calm
    // track for the preamble and to "game" for most phases, so the darker
    // music only appeared on the difficulty screen and on a lost life —
    // which is exactly backwards. Devil should sound like Devil from the
    // moment it is chosen until the run ends. The platinum is the one
    // exception: that moment resolves upward in both modes, and taking it
    // away would be taking away the payoff.
    if (run.difficulty === "devil" && run.phase !== "complete") {
      setBedState("devil");
      return;
    }
    setBedState(CALM_PHASES.has(run.phase) ? "calm" : bedForPhase(run.phase));
  }, [booted, run?.phase, run?.difficulty]);

  // "Life lost (Devil): brief dip and recover" (§6.5's table) — fires when
  // RunView.lives drops between two reads of run state (a Devil failure
  // that still had lives left; the run-service docstring on
  // `_apply_failure` is the source for "costs a life and replays the
  // segment in place"). `prevLives` starts at `undefined` (not compared)
  // so mounting mid-run with an already-reduced pool never reads as a
  // fresh loss.
  const prevLivesRef = useRef<number | null | undefined>(undefined);
  useEffect(() => {
    if (!booted || !run || run.difficulty !== "devil" || run.lives === null) return;
    const prev = prevLivesRef.current;
    prevLivesRef.current = run.lives;
    if (prev !== undefined && prev !== null && run.lives < prev) {
      setBedState("life-lost");
      const recoverPhase = run.phase;
      const timer = setTimeout(() => setBedState(bedForPhase(recoverPhase)), 900);
      return () => clearTimeout(timer);
    }
  }, [booted, run?.lives, run?.difficulty, run?.phase]);

  // unlockAudio() (fired from Boot's power-on click) resolves asynchronously
  // — check once booted, and once more shortly after, rather than assuming
  // it's ready the instant Boot hands off. The mute affordance only needs
  // to appear once there's a bus graph for it to control.
  useEffect(() => {
    if (!booted) return;
    setAudioReady(isAudioUnlocked());
    const timer = setTimeout(() => setAudioReady(isAudioUnlocked()), 300);
    return () => clearTimeout(timer);
  }, [booted]);

  // Not `null`: this is the second half of the 5.5s black screen measured
  // in Loading.tsx — the first /api/run can be slow when Neon's compute is
  // cold, and until it lands there is nothing else on screen.
  if (!run) return <Loading />;
  if (!booted) return <Boot onDone={() => setBooted(true)} />;

  const screen = (() => {
    switch (run.phase) {
      case "activation":
        return <Activation onDone={refresh} />;
      case "profile":
        return <ProfileSelect onDone={refresh} operatorOnline={operatorOnline} />;
      case "difficulty":
        return <DifficultySelect onDone={refresh} />;
      case "install":
        return <Install onDone={refresh} />;
      case "howto":
        return <HowToPlay onDone={refresh} />;
      case "game":
        // `key={gameAttempt}` forces a fresh mount on every attempt — see
        // `gameAttempt`'s own comment above for why a same-phase retry
        // otherwise softlocks.
        return (
          <SegmentGame
            key={gameAttempt}
            onDesync={() => void refresh()}
            // Total segments derived from content rather than hardcoded to
            // 8 — config/run.yaml's acts x segments_per_act is the source
            // of truth and this screen must not disagree with it.
            total={(content?.trophies ?? []).filter((t) => t.id.startsWith("game-")).length || 8}
            lives={run.lives}
            trophies={run.trophies.length}
            difficulty={run.difficulty}
            onDone={({ failed, wiped }) => {
              // Bump ONLY on failure. A failure leaves the phase at "game",
              // so without a fresh key React keeps the same SegmentGame
              // mounted and the retry never refetches a brief. A PASS moves
              // the phase on, and remounting there fired a `startSegment`
              // for a segment already cleared -- a guaranteed 409, which is
              // what left the screen hanging after a completed sequence.
              if (failed) {
                // A wipe is not "the same segment, from the top" — the whole
                // run has gone. Saying the wrong one at that exact moment is
                // worse than saying nothing.
                setGameFailed(
                  wiped
                    ? "that was the last life. everything resets — from segment one."
                    : "that one got away from you. same segment, from the top.",
                );
                setGameAttempt((n) => n + 1);
              }
              void refresh();
            }}
          />
        );
      case "question":
        // `run.question` is only ever non-null while `run.phase ===
        // "question"` (see run_routes.py's `_view`) — the `run.question ?`
        // guard exists for the render between a phase flip landing and the
        // next `refresh()` resolving, not because the two can genuinely
        // disagree.
        return run.question ? (
          <Question
            key={`question-${run.segment}-${miss?.count ?? 0}`}
            question={run.question}
            difficulty={run.difficulty}
            lives={run.lives}
            attemptsLeft={run.question_attempts_left}
            missedWith={miss?.answer ?? null}
            onAnswered={(answer) => {
              void (async () => {
                try {
                  const result = await runApi.submitAnswer(answer);
                  if (result.retry) {
                    // Wrong, but he keeps the segment, the lives and the
                    // trophies — he just spent one try. Bumping `count`
                    // remounts the form (see `miss`'s own comment) with his
                    // text preserved for editing.
                    setMiss((previous) => ({
                      count: (previous?.count ?? 0) + 1,
                      answer,
                    }));
                    await refresh();
                    return;
                  }
                  // Anything else ends this question one way or another, so
                  // the next one must not open holding the last one's text.
                  setMiss(null);
                  if (!result.passed && result.roast) {
                    // The segment restart has already happened
                    // server-side — hold here and let `roast`'s own
                    // "continue" trigger `refresh()`, so the roast gets
                    // its beat on screen before the fresh game replaces
                    // this one (see the `roast` state's own comment).
                    setRoast(result.roast);
                    return;
                  }
                } catch (error) {
                  if (!isConflict(error)) throw error;
                  // 409: resync rather than retry (server authority — see
                  // this file's `isConflict`).
                }
                await refresh();
              })();
            }}
          />
        ) : null;
      case "checkpoint":
        return (
          <Checkpoint
            onDesync={() => void refresh()}
            onPassed={(released) => {
              // The checkpoint itself always advances the run regardless
              // of whether a code came back yet (run_service.py's
              // `submit_checkpoint`: passing and releasing are two
              // separate outcomes). If the operator hasn't approved the
              // release yet, `released` is null here and the code arrives
              // later over `code_released` on the WS handler above.
              if (released) setRelease(released);
              void refresh();
            }}
          />
        );
      case "complete":
        if (sayingGoodbye)
          return (
            <Goodbye recipient={recipient || "you"} onPoweredOff={() => setPoweredOff(true)} />
          );
        return (
          <TrophyCabinet
            trophies={content?.trophies ?? []}
            earned={run.trophies}
            closing={content?.copy.closing ?? ""}
            onDone={() => setSayingGoodbye(true)}
          />
        );
      default:
        return <div className="placeholder">segment {run.segment} — unrecognised phase {run.phase}</div>;
    }
  })();

  return (
    <>
      {/* CodeReveal fully replaces the screen, rather than layering on top
          of it, while it's up — the run has already advanced underneath
          (the server doesn't wait for this to be dismissed), but the NEXT
          screen (e.g. a fresh game's keyboard listeners) has no business
          being live and capturing input while this is what's actually on
          screen. Roast gets the same treatment for the same reason, one
          tier down — a code release wins if, somehow, both are pending at
          once. */}
      {release ? (
        <CodeReveal release={release} onContinue={() => setRelease(null)} />
      ) : gameFailed ? (
        <Roast roast={gameFailed} onContinue={() => setGameFailed(null)} />
      ) : roast ? (
        <Roast
          roast={roast}
          onContinue={() => {
            setRoast(null);
            void refresh();
          }}
        />
      ) : (
        screen
      )}
      {trophyQueue.length > 0 && (
        <TrophyToast
          queue={trophyQueue}
          onDismiss={() => setTrophyQueue((queue) => queue.slice(1))}
          onSting={(grade) => {
            duckForSting(grade === "platinum" ? 1800 : 480);
            if (grade === "platinum") {
              setBedState("platinum");
              // The platinum narration existed as a file from the first
              // authoring pass and was never played by anything — the
              // biggest moment of the run was silent. Fires here rather
              // than on every trophy: a voice line on all nineteen would
              // be grating, and this one names the moment for what it is.
              playNarration("platinum");
            }
          }}
        />
      )}
      {toastQueue.length > 0 && (
        <OperatorToast
          queue={toastQueue}
          onDismiss={() => setToastQueue((queue) => queue.slice(1))}
          onChime={playOperatorToastSound}
        />
      )}
      {profileOpen && !poweredOff && (
        <Profile trophies={content?.trophies ?? []} onClose={() => setProfileOpen(false)} />
      )}
      {!poweredOff && (
      <div className="chrome">
        <button
          className="chrome__button"
          onClick={() => setProfileOpen((open) => !open)}
          aria-label="profile"
          aria-pressed={profileOpen}
          title="profile"
        >
          <ProfileGlyph />
        </button>
        {!fullscreen && (
          // Fullscreen is refused or dropped (Esc) without warning — this
          // is the quiet way back in the brief calls for, not a modal or
          // a banner that interrupts whatever's on screen.
          <button
            className="chrome__button"
            onClick={() => void requestFullscreen(document.documentElement)}
            aria-label="return to fullscreen"
            title="return to fullscreen"
          >
            <ExpandGlyph />
          </button>
        )}
        {audioReady && (
          <button
            className="chrome__button"
            onClick={() => setMutedState(toggleMute())}
            aria-label={muted ? "unmute" : "mute"}
            aria-pressed={muted}
            title={muted ? "unmute" : "mute"}
          >
            {muted ? <MutedGlyph /> : <SoundGlyph />}
          </button>
        )}
      </div>
      )}
    </>
  );
}

function ProfileGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="1.25rem" height="1.25rem" aria-hidden="true">
      <circle cx="12" cy="8" r="3.4" stroke="currentColor" strokeWidth="2" fill="none" />
      <path
        d="M5 20a7 7 0 0 1 14 0"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

function ExpandGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="1.25rem" height="1.25rem" aria-hidden="true">
      <path
        d="M4 10V4h6M20 14v6h-6M4 4l6 6M20 20l-6-6"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function SoundGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="1.25rem" height="1.25rem" aria-hidden="true">
      <path
        d="M4 9v6h4l5 4V5L8 9H4Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
        fill="none"
      />
      <path d="M17 9a5 5 0 0 1 0 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
    </svg>
  );
}

function MutedGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="1.25rem" height="1.25rem" aria-hidden="true">
      <path
        d="M4 9v6h4l5 4V5L8 9H4Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
        fill="none"
      />
      <path d="M16 9l5 6M21 9l-5 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
