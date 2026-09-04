// The question screen. THE BRIEF IS STALE HERE: `QuestionView` is free
// text (`{ prompt, blank }`), not multiple choice — the `accept` list never
// reaches the browser (see xxvi/content/schema.py::Question, and
// lib/client.ts's own header comment). This component only ever renders
// `question.prompt` and `question.blank`; it has no way to leak the answer
// key because it never receives it.
//
// The Devil-mode confirm step is the one thing this task exists to get
// right: a typo costing one of only three lives for the whole run is the
// avoidable failure this design steers around. So in DEVIL, submitting
// does not call `onAnswered` — it moves to a "confirm" stage that echoes
// back EXACTLY what will be sent (trimmed, unmodified — no case-folding,
// so what he sees is what ships) and only calls `onAnswered` on an
// explicit second action. In KIDDIE, where a wrong answer just replays the
// segment, that friction has no payoff, so it submits directly.
//
// `locked` guards every path against a double-fire submit — required by
// the task's "server authority" note ("segment tokens are single-use... a
// double-submit is a rejected replay, not a retry") — once `onAnswered`
// has been called, nothing in this component calls it again, even if the
// parent hasn't unmounted it yet by the time a stray second click lands.

import { useRef, useState, type FormEvent } from "react";
import type { QuestionView } from "../lib/run-client";
import "./question.css";

type Props = {
  question: QuestionView;
  /** RunView.difficulty — "kiddie" | "devil" | null. Only "devil" gets the
   *  confirm step. */
  difficulty: string | null;
  /** RunView.lives — the remaining Devil pool, shown on the confirm step
   *  so a wrong answer's cost is never a surprise. null in KIDDIE (no
   *  lives to spend) or before a difficulty is chosen. */
  lives: number | null;
  /** RunView.question_attempts_left — tries remaining on THIS question,
   *  including the one he is about to make. Shown in both difficulties:
   *  the stakes of the next keystroke should never be a guess. */
  attemptsLeft: number | null;
  /** Set when the previous submission was wrong but survivable. Carries his
   *  exact text back so a near-miss — a one-letter spelling variant — is a
   *  two-key correction rather than a full retype — the entire situation
   *  this allowance exists for. */
  missedWith: string | null;
  onAnswered: (answer: string) => void;
};

export function Question({
  question,
  difficulty,
  lives,
  attemptsLeft,
  missedWith,
  onAnswered,
}: Props) {
  const isDevil = difficulty === "devil";
  // Seeds from `missedWith` on mount. The parent remounts this component on
  // every miss (see Console.tsx's `key`), which is also what clears `locked`
  // — without that remount a survivable miss would leave the form disabled
  // forever, with the run sitting on a question he can no longer answer.
  const [value, setValue] = useState(missedWith ?? "");
  const [confirming, setConfirming] = useState(false);
  const [locked, setLocked] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const trimmed = value.trim();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (locked || !trimmed) return;
    if (isDevil && !confirming) {
      setConfirming(true);
      return;
    }
    setLocked(true);
    onAnswered(trimmed);
  };

  const editAgain = () => {
    setConfirming(false);
    // The input re-enables the instant `confirming` flips, but its
    // `disabled` attribute is still true for this render — focus has to
    // wait a tick for the DOM to actually unlock.
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  return (
    <section className="question">
      <p className="label question__label">recall</p>
      <h2 className="question__prompt">{question.prompt}</h2>
      {question.blank && <p className="question__blank">{question.blank}</p>}

      {/* Always mounted, never conditionally rendered — same rule as
          Activation's error line (design-system.md §6, "no layout shift,
          ever"): the prompt must not jump down the screen the moment he
          gets one wrong. The non-breaking space reserves the height. */}
      <p className="question__attempts label" role="status" data-missed={missedWith !== null}>
        {missedWith !== null && attemptsLeft !== null ? (
          <>
            not it. {attemptsLeft} {attemptsLeft === 1 ? "try" : "tries"} left
            {attemptsLeft === 1 ? " — this one counts" : ""}.
          </>
        ) : (
          " "
        )}
      </p>

      <form className="question__form" onSubmit={submit}>
        <input
          ref={inputRef}
          className="question__input"
          aria-label="answer"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          disabled={locked || confirming}
          autoFocus
          autoComplete="off"
          spellCheck={false}
        />

        {!confirming && (
          <button type="submit" disabled={locked || !trimmed}>
            {isDevil ? "review" : "submit"}
          </button>
        )}

        {/* Devil-only confirm step: echoes back exactly what will be sent,
            verbatim, before it costs a life. This is the moment the whole
            task's "three things" list opens with. It stays inside the same
            <form> (rather than a separate element with its own click
            handler) so the natural "type, Enter, review, Enter again"
            rhythm just works, and so there is exactly one submit path to
            reason about, not two. */}
        {confirming && (
          <div className="question__confirm" role="group" aria-label="confirm your answer">
            <p className="label question__confirm-label">you are about to submit</p>
            <p className="question__confirm-value">&ldquo;{trimmed}&rdquo;</p>
            {/* The stakes have to be TRUE, not merely dramatic: with
                attempts remaining a wrong answer costs an attempt and
                nothing else, and telling him it costs a life when it
                doesn't is the kind of lie that makes him play scared for
                no reason. Only the last attempt is the expensive one. */}
            {lives !== null && (
              <p className="question__confirm-stakes">
                {attemptsLeft !== null && attemptsLeft > 1 ? (
                  <>
                    wrong costs a try, not a life. {attemptsLeft} tries left,{" "}
                    {lives} {lives === 1 ? "life" : "lives"} intact.
                  </>
                ) : (
                  <>
                    last try — wrong costs a life. {lives}{" "}
                    {lives === 1 ? "life" : "lives"} left.
                  </>
                )}
              </p>
            )}
            <div className="question__confirm-actions">
              <button type="button" onClick={editAgain} disabled={locked}>
                edit
              </button>
              <button type="submit" disabled={locked} autoFocus>
                confirm &amp; submit
              </button>
            </div>
          </div>
        )}
      </form>
    </section>
  );
}
