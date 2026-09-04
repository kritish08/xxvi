// Difficulty select swaps the palette live as focus moves between options,
// and per design-system.md §6.5 the audio bed shifts with it — "same
// event, not two." previewDifficulty() below is that one event: it flips
// the `data-palette` attribute (index.css reads it) and calls
// setBedState() synchronously from the same onMouseEnter/onFocus handler,
// rather than one driving the other through a useEffect a render later.
//
// Choosing a difficulty is permanent for the run (server-enforced), but
// hovering the *other* option before committing is exactly the "swap is a
// designed moment" the design system describes, so both options preview
// live and only the click commits.

import { useState } from "react";
import { runApi } from "../lib/run-client";
import { setBedState } from "../lib/audio";
import type { components } from "../api";

type Difficulty = components["schemas"]["Difficulty"];

export function DifficultySelect({ onDone }: { onDone: () => void }) {
  const [previewed, setPreviewed] = useState<Difficulty>("kiddie");
  const [busy, setBusy] = useState(false);

  const previewDifficulty = (difficulty: Difficulty) => {
    setPreviewed(difficulty);
    // Same event: DOM write and audio bed call together, not decoupled.
    if (difficulty === "devil") {
      document.documentElement.dataset.palette = "devil";
    } else {
      delete document.documentElement.dataset.palette;
    }
    setBedState(difficulty);
  };

  const choose = async (difficulty: Difficulty) => {
    setBusy(true);
    try {
      await runApi.chooseDifficulty(difficulty);
      onDone();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`difficulty difficulty--${previewed}`}>
      <div className="label difficulty__label">select difficulty</div>
      <h1>how do you want to play?</h1>
      <div className="difficulty__row">
        <button
          className="difficulty__option"
          onMouseEnter={() => previewDifficulty("kiddie")}
          onFocus={() => previewDifficulty("kiddie")}
          onClick={() => void choose("kiddie")}
          disabled={busy}
          autoFocus
        >
          <strong>KIDDIE</strong>
          <span>a fail costs you the current segment</span>
        </button>
        <button
          className="difficulty__option"
          onMouseEnter={() => previewDifficulty("devil")}
          onFocus={() => previewDifficulty("devil")}
          onClick={() => void choose("devil")}
          disabled={busy}
        >
          <strong>DEVIL</strong>
          <span>a fail costs you everything</span>
        </button>
      </div>
      <p className="difficulty__note">
        codes you&rsquo;ve already earned are yours. nothing takes those back.
      </p>
    </section>
  );
}
