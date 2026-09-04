// The install phase opens on the library card — the emotional centre of
// the shell. `X X V I` over a 2px rule, `XX · VI` beneath, and the
// strapline. The title is never explained anywhere in the product: no
// tooltip, no subtitle spelling out the joke. He works it out or he
// doesn't — that is the design, so nothing here adds one.
//
// The bar animates `transform: scaleX()` with `transform-origin: left`
// (set in console.css), never `width` — and it runs on a single rAF loop
// via lib/motion.ts's rafLoop/setProgress, not setInterval, so it holds up
// under a 30fps capture. This is also where narration pre-decodes (kicked
// off back at the power-on click) — the bar's ~6.5s duration is partly
// there to buy that time, so it must not be sped up.

import { useEffect, useRef, useState } from "react";
import { runApi } from "../lib/run-client";
import { playNarration } from "../lib/audio";
import { rafLoop, setProgress } from "../lib/motion";
import { fetchStandardTrophyCount } from "../lib/trophy-content";

const INSTALL_MS = 6500;

// All four subtitles show; only two are narrated, and that is deliberate.
// The subtitles land ~1.69s apart (26% of INSTALL_MS), but the generated
// narration runs 2.0-2.95s per line — four of them is 10.1s of speech inside
// a 6.5s install, so each line would be cut off by the next. Narrating the
// 1st and 3rd leaves a ~0.4s gap and matches the design system's "two or
// three" for this beat. Measured, not guessed; see task-29 notes.
const SUBTITLES = [
  { at: 0, text: "copying 20 years…", narration: "install-1" },
  { at: 26, text: "decompressing inside jokes…", narration: undefined },
  { at: 52, text: "verifying trauma…", narration: "install-3" },
  { at: 78, text: "indexing grudges…", narration: undefined },
] as const;

function LibraryCard({
  onInstall,
  standardTotal,
}: {
  onInstall: () => void;
  /** null covers both "still loading" and "the fetch failed" — either way
   *  the card degrades to just "0%", never a wrong number, never a blank
   *  screen (see lib/trophy-content.ts). */
  standardTotal: number | null;
}) {
  return (
    <section className="library">
      <div className="boxart">
        <p className="boxart__title">X&nbsp;X&nbsp;V&nbsp;I</p>
        <hr className="boxart__rule" />
        <p className="boxart__split label">XX&nbsp;·&nbsp;VI</p>
      </div>
      <p className="library__progress label">
        {standardTotal !== null ? <>0% &nbsp;·&nbsp; 0 of {standardTotal} trophies</> : "0%"}
      </p>
      <p className="library__strapline">you&rsquo;ve been playing this one since 2006.</p>
      <button className="library__install" onClick={onInstall} autoFocus>
        install
      </button>
    </section>
  );
}

function InstallBar({ onDone }: { onDone: () => void }) {
  const fillRef = useRef<HTMLDivElement>(null);
  const [percent, setPercent] = useState(0);
  const [subtitleIndex, setSubtitleIndex] = useState(0);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    let lastShownPercent = -1;
    let lastNarrationIndex = -1;

    const stop = rafLoop((elapsedMs) => {
      // Ease-out: quick start, unhurried finish — an install bar that
      // crawls at 0% and 100% and moves through the middle reads as real.
      const t = Math.min(1, elapsedMs / INSTALL_MS);
      const eased = 1 - (1 - t) * (1 - t);
      const fraction = eased;

      if (fillRef.current) setProgress(fillRef.current, fraction);

      // React only re-renders on the integer percent changing — not once
      // per frame — per design-system.md §6's "keep React out of the
      // frame loop."
      const shown = Math.floor(fraction * 100);
      if (shown !== lastShownPercent) {
        lastShownPercent = shown;
        setPercent(shown);

        let subtitle = 0;
        for (let i = SUBTITLES.length - 1; i >= 0; i--) {
          if (shown >= SUBTITLES[i].at) {
            subtitle = i;
            break;
          }
        }
        if (subtitle !== lastNarrationIndex) {
          lastNarrationIndex = subtitle;
          setSubtitleIndex(subtitle);
          playNarration(SUBTITLES[subtitle].narration);
        }
      }

      if (t >= 1) {
        stop();
        void runApi.installed().then(() => onDoneRef.current());
      }
    });

    return stop;
  }, []);

  return (
    <section className="install">
      <div className="label install__label">installing</div>
      <h1>X&nbsp;X&nbsp;V&nbsp;I</h1>
      <div className="install__bar">
        <div className="install__fill" ref={fillRef} />
      </div>
      <p className="install__percent">{percent}%</p>
      <p className="install__subtitle">{SUBTITLES[subtitleIndex].text}</p>
    </section>
  );
}

export function Install({ onDone }: { onDone: () => void }) {
  const [installing, setInstalling] = useState(false);
  const [standardTotal, setStandardTotal] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchStandardTrophyCount().then((total) => {
      if (!cancelled) setStandardTotal(total);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!installing) return <LibraryCard onInstall={() => setInstalling(true)} standardTotal={standardTotal} />;
  return <InstallBar onDone={onDone} />;
}
