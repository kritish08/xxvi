# XXVI — Design System

**Binding on every frontend task (14–21).** Implementers do not invent visual decisions; they read this and apply it. If something here conflicts with a task brief, this file wins on appearance, the brief wins on behaviour.

---

## 1. The governing constraint

This is not viewed on a monitor. It is viewed **through Discord screen-share** — a low-bitrate, chroma-subsampled video codec — while he plays fullscreen on a laptop.

That inverts a lot of normal design advice. The codec destroys:

- soft gradients (banding)
- 1px hairlines (they flicker or vanish)
- soft drop shadows (mush)
- small text (illegible)
- saturated red/orange **text** on dark (4:2:0 chroma subsampling smears colour edges)
- **film grain, noise overlays, scanlines, CRT texture** — high-frequency detail is the single most expensive thing you can put in a video stream. It eats the entire bitrate and everything else degrades to compensate.

It preserves: **large flat fills, high luminance contrast, thick strokes, big type.**

So: no atmospheric texture, no grain, no scanlines, no glassmorphism, no blur. Flat, bold, high-contrast. The restraint is a technical requirement, not a style preference.

---

## 2. Identity

**Console software, not a web app.** The whole illusion collapses the moment it looks like a website.

Signals that read as *console*:

- **Full-bleed always.** 100vw × 100vh, no scrollbars anywhere, ever. No centred max-width container.
- **Left-anchored, hard indent.** Content starts at a generous left rail (`--rail: 8vw`). Never centre a screen's content block — centre only the trophy pop and the platinum moment.
- **Horizontal rails**, not vertical stacked cards.
- **Near-square corners.** 2px radius. Never `rounded-2xl`, never pills.
- **Uppercase micro-labels** with wide tracking above every screen title. This one detail does more work than any other.
- **Selection = scale + ring**, never a background-colour swap.

### The motif

The title splits: `XX · VI`. **The interpunct is the app's divider**, everywhere — metadata rows, breadcrumbs, stat separators. `2 ACTS · 8 SEGMENTS · 0%`. He will never consciously notice it. That's the point.

---

## 3. Typography

Three faces, all open-source, all **self-hosted as woff2** — no external font CDN. Nothing in this app may depend on a third-party request at midnight.

| Role | Face | Use |
|---|---|---|
| Display | **Archivo Expanded**, 800 | The title, screen headings, trophy names, the platinum moment |
| UI | **IBM Plex Sans**, 400/600 | Everything else. Sturdy, high x-height, survives compression |
| Mono | **IBM Plex Mono**, 500 | Product key entry, redemption codes, the countdown |

Not Inter. Not Roboto. Not system-ui. Not Space Grotesk.

```css
--font-display: "Archivo Expanded", "Archivo", sans-serif;
--font-ui: "IBM Plex Sans", sans-serif;
--font-mono: "IBM Plex Mono", monospace;
```

### Scale

Console type is large. Read at desk distance, but generous — and the codec punishes anything small.

```css
--type-display: clamp(4rem, 9vw, 9rem);      /* XXVI, platinum */
--type-h1:      clamp(2rem, 3.6vw, 3.5rem);  /* screen titles */
--type-body:    clamp(1.25rem, 1.8vw, 1.75rem);
--type-label:   0.8125rem;                    /* uppercase, tracked */

--track-display: -0.02em;
--track-label:    0.22em;
```

**Nothing renders below 16px.** No exceptions.

---

## 4. Colour

Two palettes. Difficulty selection swaps them live — that swap is a designed moment, not a theme toggle.

Never pure black: `#000` plus bright text causes ringing artifacts on video.

### KIDDIE — cold

```css
--bg:      #0A0E14;   /* near-black, blue-cast */
--surface: #121821;
--line:    #223041;
--text:    #E8EDF2;
--muted:   #7C8B9C;
--accent:  #2E9BFF;
```

### DEVIL — warm

```css
--bg:      #0D0507;
--surface: #1A0A0D;
--line:    #3A1216;
--text:    #F2E8E8;
--muted:   #9C7C80;
--accent:  #FF3B30;
```

**Rule for DEVIL:** red is a *fill, rule, and glow* colour. **Never red text on dark** — chroma subsampling smears it into an unreadable halo. Text stays `--text` in both palettes; the accent does its work through borders, bars, and rings.

### Trophy grades — fixed, palette-independent

```css
--bronze:   #C97B4A;
--silver:   #C3CDD6;
--gold:     #E8B33C;
--platinum: #8FE3F0;
```

Platinum is deliberately the highest-luminance value in the entire system. It is the climax, and it has to punch through compression when everything else has been crushed.

---

## 5. Space and shape

```css
--rail: 8vw;          /* left indent for screen content */
--radius: 2px;
--border: 2px;        /* never 1px — it disappears on video */
--gap-tight: 0.75rem;
--gap: 1.5rem;
--gap-loose: 4rem;
```

Shadows: **none**. Depth comes from a flat surface step (`--bg` → `--surface`) and from ring glows on focus. If you need emphasis, use a 2px accent rule, not a shadow.

---

## 6. Motion

One easing curve across the entire app, so everything feels like one machine:

```css
--ease: cubic-bezier(0.16, 1, 0.3, 1);   /* expo-out */
--fast: 180ms;
--base: 320ms;
--slow: 480ms;
```

- Entrances: fast in, slow settle, slight overshoot on scale (`1.04` → `1`).
- **No rapid full-screen flashing.** Compression artifact and an accessibility problem.
- Respect `prefers-reduced-motion`: cut durations to 0.01ms, keep the end state.

### Motion engineering — how it stays smooth

Tokens do not make motion smooth. These rules do, and they are binding.

**Animate `transform` and `opacity`. Nothing else.** Those two are handled by the compositor and never touch layout. Animating `width`, `height`, `top`, `left`, `margin`, or `box-shadow` forces layout and paint on every single frame, and it visibly stutters.

- A progress bar animates `transform: scaleX()` with `transform-origin: left`, never `width: N%`.
- A moving reticle animates `transform: translate3d()`, never `left`.
- Anything that animates repeatedly gets `will-change: transform` — and only those, since over-applying it wastes GPU memory.

**Continuous motion uses `requestAnimationFrame` with delta time. Never `setInterval`.** `setInterval(fn, 50)` is 20fps, drifts against the display's refresh, and is guaranteed to look cheap. Any game with a continuously moving element runs one rAF loop, computes elapsed time from `performance.now()`, and derives position from elapsed time rather than accumulating per-tick increments — so the motion is correct regardless of frame rate.

**Keep React out of the frame loop.** Calling `setState` every frame re-renders the tree 60 times a second for a value only CSS needs. Hold the animated value in a `useRef`, write it directly to `element.style.transform` inside the rAF callback, and let React render only on state changes that actually alter the UI — start, pass, fail. This is the difference between a game that feels native and one that feels like a web page pretending.

**Design for a 30fps capture.** Discord samples the screen at 30fps, often lower under load. Fast, small movements alias into stutter at that rate. Prefer larger movements over longer durations; avoid anything meaningful that resolves in under 200ms, because on his recording it may occupy fewer than six frames.

**No layout shift, ever.** The trophy pop is `position: fixed`, out of document flow, so it cannot reflow the screen behind it. Reserve space for anything that appears later rather than letting content jump.

**Fonts must not flash.** Self-hosted woff2, `<link rel="preload">`, `font-display: block`. A font swapping in mid-boot causes a text reflow at exactly the moment the illusion is being established.

**Fullscreen changes the viewport.** Entering or leaving fullscreen fires a resize; never run a transition through it. Size from `vw`/`vh` and CSS-driven layout so the app reflows correctly rather than animating between two viewport sizes.

### The signature moment — the trophy pop

It happens 19+ times. It is the thing he will remember, so it gets the most care of anything in the app.

Slides down from top-centre, overshoots, holds four seconds, retracts up. Grade colour as a 2px ring and a left bar. Icon, name in display face, grade in tracked uppercase beneath.

**It must read as complete with the sound muted** — his stream may not carry system audio. Every piece of information is visual. Sound is a bonus layer that carries zero meaning on its own.

---

## 6.5 Audio architecture

Four layers, three of them synthesised. Sound is **never load-bearing** — his screen share may not carry system audio, so every cue has a visual equivalent and the whole experience reads on mute. Audio is for him in the room, not for the recording.

### The unlock gesture

Browsers require a user gesture to start an `AudioContext`, request fullscreen, or play audio. **The boot screen's power-on click does all three at once.** That is not a coincidence to be tidied away later — it is the only gesture in the flow before content starts, and building anything that needs a second one is a design error.

On that click: resume the `AudioContext`, request fullscreen, and pre-decode every narration file. Decoding during the fake install bar is free — that bar exists partly to buy this time.

### Four buses

Everything routes through three gain nodes into the destination, so levels are one place rather than scattered per-sound.

| Bus | Contents | Source | Nominal |
|---|---|---|---|
| **MUSIC** | ambient bed, boot drone | WebAudio, procedural | −20 dB |
| **SFX** | UI stings, trophy pops | WebAudio oscillators | 0 dB |
| **VOICE** | narration | Pre-generated TTS files | 0 dB |

**UI stings** are synthesised because a decoded file has scheduling latency exactly where a click must feel immediate. **Trophy pops** escalate bronze → silver → gold in pitch and length; platinum lands lower, wider and longer. **Narration** is the only recorded layer.

### The music bed is procedural, and it reacts to state

Not a track. A slow evolving pad built from a few detuned oscillators through a filter — which is what a console home screen actually sounds like, and it solves four problems at once: nothing to fail to load, no loop-point seam, no licensing question when this repo goes public, and it can **respond to the run**.

| State | The bed does |
|---|---|
| Boot | low drone, rises |
| Profile / library / difficulty | calm pad, widest and most present |
| **KIDDIE** | cool register, gentle LFO |
| **DEVIL** | drops a fifth, detunes slightly, LFO slows — same bed, darker. The palette swap and the audio swap are one event. |
| During a game | a soft pulse enters; tension without melody |
| During a question | **bed thins and drops ~6 dB** — see below |
| Life lost (Devil) | brief dip and recover |
| Checkpoint passed | resolves upward |
| **Platinum** | full resolution, then out |

### Ducking, and why the question phase is quiet

They are on a call, talking, for twenty minutes. Music under speech is exhausting, and if his system audio is captured it sits under both their voices in the recording permanently. So the bed is **deliberately unequal**: present in the cinematic beats — boot, install, difficulty, checkpoint, platinum — and pulled back during questions, which is exactly when he is thinking out loud and they are talking most.

Ducking rules, all as smooth ramps via `setTargetAtTime` — never an instant gain change, which clicks:

- **VOICE plays** → MUSIC to −32 dB, SFX to −6 dB. Attack 120 ms, release 400 ms.
- **Trophy sting** → MUSIC −6 dB for the sting's length.
- **Question phase** → MUSIC −6 dB and the pad thins for as long as it lasts.

### Controls

A mute affordance is always reachable, and it mutes the master, not one bus. Separate music and sound toggles are over-engineering here.

Sound remains **non-load-bearing**: on mute, every trophy, state change and error still reads visually. Audio is for him in the room; the recording must work without it.

### Narration

Generated once at authoring time and committed as static audio. **Never runtime TTS** — that means an API dependency at midnight, latency before every pop, and a failure mode on the one night that cannot have one.

Roughly six to eight lines. It never names a trophy — real PlayStation doesn't either, and a generic line means the audio never has to be regenerated when trophy names change:

- boot: one line
- install: two or three, matching the on-screen subtitles
- trophy pop: **one generic line**, reused for all 18
- **platinum: its own line** — this is the moment
- cabinet: optional closing beat

Narration **ducks** the sting layer by about 6dB while playing, or the platinum sting and the platinum line will collide.

### Sync — the part that is easy to get wrong

The sting and the animation must be triggered from **the same event in the same frame**. Not the sound in a callback and the animation in an effect — they drift, and 80ms of drift reads as cheap.

Schedule audio against `AudioContext.currentTime`, not `setTimeout`. Start the CSS animation in the same handler. If a sound must lead or trail the visual, express it as an explicit offset, not as accidental ordering.

### The trophy pop, choreographed

The signature moment, 19+ times over. It gets the most care of anything in the app.

```
   0ms   sting attack  ·  toast begins slide from -100% Y
   0-180 slide in, overshoot to scale 1.04
 180-320 settle to 1.0
 320-4320 hold          (sting has decayed by ~600ms)
4320-4640 retract up, fade
```

Platinum breaks the pattern deliberately: full-screen rather than a toast, the sting runs ~1.8s, and the narration line fires **after** the sting rather than under it. Everything else in the app is a variation on one rhythm; this is the one that isn't.

### Controls

A mute affordance is always reachable. `prefers-reduced-motion` shortens animation but does **not** disable audio — they are separate accessibility concerns and conflating them is a common mistake.

## 7. Iconography and sound — all code, no assets

- **Trophy icons: inline SVG.** Four chalice forms, one per grade, `currentColor`-driven so the palette shift is free. Flat, thick-stroked, no gradients.
- **Box art: pure typography.** `X X V I` over a 2px rule, `XX · VI` beneath, in Archivo Expanded 800. No illustration — the split *is* the joke, and an image would bury it.
- **Trophy sounds: WebAudio oscillators**, one short sweep per grade, ascending. No audio files, no Sony assets, nothing to fail to load.
- **No emoji anywhere.** The face glyphs `△ ○ ✕ □` are the only pictographic language in the app.

---

## 8. Ban list

Any of these appearing in a review is a defect:

- `Inter`, `Roboto`, `system-ui`, `Space Grotesk` as a display face
- Purple or indigo gradients; the Tailwind default palette
- `border-radius` above 4px; pills; `rounded-2xl`
- `box-shadow` for depth; glassmorphism; `backdrop-filter: blur`
- Emoji in any heading, label, or button
- A centred max-width container; a hero-plus-three-cards layout
- Visible scrollbars; any vertical page scroll
- Grain, noise, scanline, or CRT overlays
- Red text on a dark ground (DEVIL palette)
- Text below 16px; borders below 2px
- Placeholder text used as a substitute for a label

---

## 9. Accessibility floor

- Body text ≥ 7:1 against its background. This is above WCAG AAA on purpose — the codec eats contrast before he sees it.
- Every state that uses colour also uses shape, text, or position. Trophy grade is written out, not implied by colour alone.
- Focus is always visible: 2px accent ring, 2px offset. Keyboard is the supported input path, so focus states are primary UI, not an afterthought.
- `Esc` is bound to nothing — it exits fullscreen and that is not overridable.
