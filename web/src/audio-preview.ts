// Entry point for audio-preview.html. AUTHORING TOOL, NOT PART OF THE RUN --
// see the AUTHORING_PAGES comment in vite.config.ts, including the note to
// delete both before the 20th.
//
// It imports the real modules rather than reimplementing anything, so what
// is heard here is exactly what plays in the run. It deliberately renders no
// run content: bed-state and effect names only, nothing from config/run.yaml.

import {
  duckForVoice,
  missingBedTracks,
  playNarration,
  playOperatorToastSound,
  preloadNarration,
  setBedState,
  unlockAudio,
  type BedState,
} from "./lib/audio";
import { playTrophySound } from "./lib/trophy-sound";


const BEDS: BedState[] = [
  "boot",
  "calm",
  "kiddie",
  "devil",
  "game",
  "question",
  "life-lost",
  "checkpoint",
  "platinum",
];

const NARRATION_KEYS = ["boot", "install-1", "install-3", "platinum"];

function button(label: string, onClick: () => void): HTMLButtonElement {
  const el = document.createElement("button");
  el.type = "button";
  el.textContent = label;
  el.addEventListener("click", onClick);
  return el;
}

function mount(id: string, buttons: HTMLButtonElement[]): void {
  const host = document.getElementById(id);
  if (!host) return;
  for (const el of buttons) host.append(el);
}

document.getElementById("start")?.addEventListener("click", (event) => {
  const startButton = event.currentTarget as HTMLButtonElement;
  startButton.disabled = true;
  startButton.textContent = "audio running";

  // Same single-gesture unlock the boot screen uses.
  void unlockAudio();
  void preloadNarration();

  const panel = document.getElementById("panel");
  if (panel) panel.hidden = false;
  const now = document.getElementById("now");

  const bedButtons = BEDS.map((state) =>
    button(state, () => {
      setBedState(state);
      if (now) now.textContent = state;
      for (const el of bedButtons) el.classList.toggle("current", el.textContent === state);
    }),
  );
  bedButtons[0].classList.add("current");
  mount("beds", bedButtons);

  mount("sfx", [
    button("operator toast", () => playOperatorToastSound()),
    ...(["bronze", "silver", "gold", "platinum"] as const).map((grade) =>
      button(`trophy — ${grade}`, () => playTrophySound(grade)),
    ),
  ]);

  mount(
    "voice",
    NARRATION_KEYS.map((key) => button(key, () => playNarration(key))),
  );

  mount("duck", [
    button("duck music for 3s", () => {
      duckForVoice(true);
      window.setTimeout(() => duckForVoice(false), 3000);
    }),
  ]);


  // A missing music file is silent by design, which is exactly the kind of
  // thing that goes unnoticed until the night. Say so, out loud, here.
  const status = document.getElementById("music-status");
  const report = () => {
    if (!status) return;
    const missing = missingBedTracks();
    status.textContent = missing.length
      ? `${missing.length} music file(s) not found — those states are SILENT: ${missing.join(", ")}`
      : "all four music tracks loaded.";
    status.style.color = missing.length ? "#e8b33c" : "#7c8b9c";
  };
  window.setTimeout(report, 1200);
  window.setTimeout(report, 4000);
});
