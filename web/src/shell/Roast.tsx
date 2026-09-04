// The roast — Question.roast (content/schema.py) was authored, validated
// at content-load time, and never actually shown anywhere until this
// component existed (see the task-30 review's finding on it). This is
// "designed to appear here": run_service.py's SPEEDRUN_SECONDS comment
// already assumed a player "pauses to read even one roast" before this
// screen was wired up to make that literally true.
//
// A wrong answer's server-side transition (question -> game, a full
// segment restart) has already happened by the time this renders --
// Console.tsx holds `refresh()` until this is dismissed specifically so
// the roast gets its beat on screen before the next game takes over, the
// same "don't auto-dismiss the moment that matters" rule CodeReveal.tsx
// follows for the reward reveal.

import "./roast.css";

type Props = {
  roast: string;
  onContinue: () => void;
};

export function Roast({ roast, onContinue }: Props) {
  return (
    <section className="roast">
      <p className="label roast__label">wrong</p>
      <p className="roast__line">{roast}</p>
      <button className="roast__continue" onClick={onContinue} autoFocus>
        try again
      </button>
    </section>
  );
}
