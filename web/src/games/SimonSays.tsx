// Simon Says — watch a face-button sequence, then repeat it. A wrong press
// fails immediately; the server (server/xxvi/games/verify.py) is the only
// thing that decides pass/fail for real, so this component's `passed` is
// advisory (see types.ts and GameHost.tsx).

import { useCallback, useEffect, useRef, useState } from "react";
import { useGamepadFace } from "../lib/gamepad";
import { FACE_GLYPHS, FACE_KEY_LABELS, FACE_LABELS, faceFromEvent } from "../lib/input";
import type { GameProps } from "./types";
import "./game.css";

/** Mirrors server/xxvi/games/seeds.py — counter-mode SHA-256, byte % 4, not
 *  `random`, precisely so the two sides can agree on the same sequence from
 *  the same seed without any extra round trip. Any change here must be made
 *  there too — web/tests/seq.test.ts pins a vector computed straight from
 *  the Python reference and is what catches the two sides drifting apart. */
export async function simonSequence(seed: string, length: number): Promise<number[]> {
  const out: number[] = [];
  let counter = 0;
  while (out.length < length) {
    const data = new TextEncoder().encode(`${seed}:${counter}`);
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", data));
    for (const byte of digest) out.push(byte % 4);
    counter += 1;
  }
  return out.slice(0, length);
}

// Sequence playback pacing, in ms. This is game information, not decorative
// motion: prefers-reduced-motion (docs/design-system.md §6) shortens the
// *flourish* on a lit face — the scale/opacity transition in game.css,
// driven by the --fast/--base tokens index.css already collapses to
// 0.01ms under reduced motion — but never these step timings. Zeroing them
// would flash the whole sequence in a single frame and make the game
// unplayable, the same "shorten, never delete" lesson task 17 hit with the
// trophy toast's own timing.
const STEP_MS = 460;
const LIT_MS = 280;
/** Wrong presses allowed INSIDE one segment before it is actually lost.
 *  A single mistyped face used to end the whole segment instantly, with no
 *  indication of what had gone wrong -- the same "one typo costs
 *  everything" problem the question allowance fixed. Devil gets fewer, not
 *  none: it should be tighter, not arbitrary. */
const MINI_LIVES: Record<string, number> = { kiddie: 3, devil: 2 };
/** How long a wrong press stays on screen before the sequence replays. */
const MISTAKE_HOLD_MS = 900;
/** How long the WINNING press's flash stays lit before self-clearing.
 *  Every other press's flash is implicitly cleared by the next press
 *  overwriting it, or (on a mistake) by MISTAKE_HOLD_MS's own timeout --
 *  but the press that completes the sequence has no next press to
 *  overwrite it, and nothing else in this component ever cleared it. It
 *  only ever went away because GameHost happened to unmount this
 *  component once its (async, network-bound) submission resolved -- so a
 *  slow response left the win glowing on screen for as long as that took,
 *  read back as "the success flash never clears". This is a real
 *  self-clear, not a fix that only works because something else usually
 *  tidies up first. */
const FLASH_HOLD_MS = 500;

export function SimonSays({ seed, params, difficulty, onFinish }: GameProps) {
  const length = Math.max(1, Math.trunc(params.length ?? 4));
  const [sequence, setSequence] = useState<number[]>([]);
  const [showing, setShowing] = useState<number | null>(null);
  // "mistake" is the MISTAKE_HOLD_MS window after a wrong press: the
  // sequence has not yet replayed, but input must not be accepted the way
  // it still is during "repeat". Inferring that window from `phase` used
  // to be the same bug three times over (extra tries burned, the header
  // still saying "your turn", a timeout racing an unmount) — see `locked`
  // below, which is the single mechanism that now closes all three.
  const [phase, setPhase] = useState<"watch" | "repeat" | "mistake">("watch");
  // Mirrors entered.current for render purposes only — the ref is what
  // press() reads/writes synchronously, this is just so the progress
  // counter actually re-renders after each press (a ref mutation alone
  // doesn't).
  const [enteredCount, setEnteredCount] = useState(0);
  // `tries` in config overrides the per-difficulty default, so the
  // allowance is tunable per segment without a code change (and so tests
  // can pin it to 1 to exercise the exhaustion path directly).
  const allowance = Math.max(
    1,
    Math.trunc(params.tries ?? (difficulty === "devil" ? MINI_LIVES.devil : MINI_LIVES.kiddie)),
  );
  const [attemptsLeft, setAttemptsLeft] = useState(allowance);
  /** The last press, so it can be shown as right or wrong. Without this a
   *  correct press produced no visible result at all -- reported as
   *  "I clicked anything and nothing happened". */
  const [flash, setFlash] = useState<{ face: number; ok: boolean } | null>(null);
  const entered = useRef<number[]>([]);
  const started = useRef(Date.now());
  // Guards against a second onFinish firing from a rapid double keypress
  // landing before phase's setState re-render disables further presses —
  // one game round reports exactly one outcome.
  const finished = useRef(false);
  // Synchronous twin of `phase === "mistake"`. `press()` reads THIS, not
  // `phase`, to decide whether to accept input: a ref is up to date the
  // instant it's written, where `phase` only catches up on the next
  // render. Set the moment a wrong press lands, cleared inside the same
  // timeout that ends the hold and replays the sequence.
  const locked = useRef(false);
  // Handle for that timeout, so a component that unmounts mid-hold can
  // cancel it instead of leaving it queued to setState on a dead component.
  const mistakeTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Same idea for the winning press's self-clear (FLASH_HOLD_MS above).
  const flashTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (mistakeTimeout.current !== null) clearTimeout(mistakeTimeout.current);
      if (flashTimeout.current !== null) clearTimeout(flashTimeout.current);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void simonSequence(seed, length).then((seq) => {
      if (!cancelled) setSequence(seq);
    });
    return () => {
      cancelled = true;
    };
  }, [seed, length]);

  // Watch phase: step through the sequence with chained setTimeout, never
  // setInterval — a fixed-period interval drifts against real elapsed time
  // once anything in the callback takes non-zero time, where a chain that
  // schedules its own next step is immune to that (§6, "Motion
  // engineering"). This is stepped/discrete playback, not continuous
  // per-frame motion, so timers rather than requestAnimationFrame are the
  // right tool here.
  useEffect(() => {
    if (!sequence.length || phase !== "watch") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const showStep = (index: number) => {
      if (cancelled) return;
      if (index >= sequence.length) {
        setShowing(null);
        setPhase("repeat");
        started.current = Date.now();
        return;
      }
      setShowing(sequence[index]);
      timer = setTimeout(() => {
        if (cancelled) return;
        setShowing(null);
        timer = setTimeout(() => showStep(index + 1), STEP_MS - LIT_MS);
      }, LIT_MS);
    };

    timer = setTimeout(() => showStep(0), STEP_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sequence, phase]);

  const press = useCallback(
    (face: number) => {
      // `locked.current` (not `phase`) is what actually gates the
      // MISTAKE_HOLD_MS window — see its declaration above.
      if (phase !== "repeat" || locked.current || finished.current) return;
      entered.current = [...entered.current, face];
      setEnteredCount(entered.current.length);
      const position = entered.current.length - 1;

      if (entered.current[position] !== sequence[position]) {
        setFlash({ face, ok: false });
        const remaining = attemptsLeft - 1;
        setAttemptsLeft(remaining);
        if (remaining <= 0) {
          finished.current = true;
          onFinish({
            passed: false,
            durationMs: Date.now() - started.current,
            inputCount: entered.current.length,
            score: position,
            sequence: entered.current,
          });
          return;
        }
        // Still has attempts: lock input, show the mistake, then replay
        // the sequence and let him go again. Nothing is reported to the
        // server -- from its side this is still one segment attempt, and
        // the sequence it finally receives is the one he actually
        // completed.
        locked.current = true;
        setPhase("mistake");
        mistakeTimeout.current = setTimeout(() => {
          mistakeTimeout.current = null;
          entered.current = [];
          setEnteredCount(0);
          setFlash(null);
          locked.current = false;
          setPhase("watch");
        }, MISTAKE_HOLD_MS);
        return;
      }
      setFlash({ face, ok: true });
      if (entered.current.length === sequence.length) {
        finished.current = true;
        // Nothing else ever overwrites or clears this flash -- there is no
        // next press to do it, unlike every earlier correct press in the
        // sequence. Self-clear it rather than depending on GameHost's
        // (async, network-bound) unmount to tidy up. See FLASH_HOLD_MS.
        flashTimeout.current = setTimeout(() => {
          flashTimeout.current = null;
          setFlash(null);
        }, FLASH_HOLD_MS);
        onFinish({
          passed: true,
          durationMs: Date.now() - started.current,
          inputCount: entered.current.length,
          score: sequence.length,
          sequence: entered.current,
        });
      }
    },
    [phase, sequence, onFinish, attemptsLeft],
  );

  // Keyboard is the supported path (§9) — the on-screen faces exist for
  // the person watching the screen share, not as the primary input.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const face = faceFromEvent(event);
      if (face !== null) {
        event.preventDefault();
        press(face);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [press]);

  // Optional, additive: a controller reports the same `press(face)` the
  // keyboard does, edge-triggered by the hook itself so a held pad button
  // can't spam presses (see lib/gamepad.ts). Keyboard remains the
  // supported path — this is pure enhancement, never required for a game
  // to be completable (docs/design-system.md §9, task 23 brief).
  const padConnected = useGamepadFace(press);

  return (
    <section className="game game--simon">
      <div className="label game__label">segment · simon says</div>
      {/* The turn state has to be unmissable. Presses during "watch" are
          correctly ignored, but nothing SAID so, so pressing keys early
          read as "the keyboard does not work". "mistake" gets its own
          string for the same reason — the screen must not keep inviting
          input the game is about to discard. */}
      <p
        className="game__prompt simon__turn"
        data-turn={phase}
        role="status"
        aria-live="polite"
      >
        {phase === "watch" ? "watch…" : phase === "mistake" ? "hold on…" : "your turn"}
      </p>

      {/* Attempts remaining inside this segment. Pips, like the HUD's
          lives — a count that shrinks reads at a glance mid-game. */}
      <p className="simon__attempts label">
        <span className="simon__attempts-key">tries</span>
        <span className="simon__pips">
          {Array.from({ length: allowance }, (_, i) => (
            <span key={i} className={`simon__pip${i < attemptsLeft ? " is-lit" : ""}`} />
          ))}
        </span>
      </p>
      <p className="game__hint label" aria-hidden={!padConnected} data-visible={padConnected}>
        controller detected
      </p>
      {/* Key mapping stays on screen throughout, not just during "repeat" —
          it's the only pictographic language in the app (§7) and keyboard
          is the supported path (§9), so the mapping is primary UI. */}
      <div className="game__faces">
        {FACE_GLYPHS.map((glyph, face) => (
          <button
            key={face}
            type="button"
            className={
              `face face--${face}` +
              (showing === face ? " is-lit" : "") +
              (flash?.face === face ? (flash.ok ? " is-right" : " is-wrong") : "")
            }
            aria-label={FACE_LABELS[face]}
            onClick={() => press(face)}
            disabled={phase !== "repeat"}
          >
            <span className="face__glyph" aria-hidden="true">
              {glyph}
            </span>
            <span className="face__key label">{FACE_KEY_LABELS[face]}</span>
          </button>
        ))}
      </div>
      <p className="game__progress label">
        {enteredCount} / {sequence.length || length}
      </p>
    </section>
  );
}
