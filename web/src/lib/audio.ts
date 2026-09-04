// Shared audio foundation for the console shell and every task built on top
// of it (docs/design-system.md §6.5, "Audio architecture" — BINDING).
// Later tasks (17: trophy stings, 18-20: games) connect into this module
// rather than building their own AudioContext — the bus graph below is the
// stable contract they inherit.
//
// TROPHY STING WIRING (task 18's job, done here): lib/trophy-sound.ts
// (task 17, off-limits to this task) builds its own standalone
// AudioContext by default and exposes exactly one integration seam,
// `routeTrophySfxThrough(context, sfxBus)`, for whoever wires the app
// after this module exists to call once. buildEngine() below is that
// point — "the point the audio context is created" — so every trophy pop
// from the first engine build onward plays through the real SFX bus
// instead of trophy-sound.ts's standalone one, and therefore respects the
// master mute and ducks/gets ducked correctly. The reverse direction —
// sting ducks MUSIC (§6.5's "Trophy sting → MUSIC −6dB for the sting's
// length") — is `duckForSting` below; TrophyToast's `onSting` callback is
// the seam for that, wired at whatever call site renders TrophyToast.
//
//   MUSIC ─┐
//   SFX   ─┼─> master ─> destination
//   VOICE ─┘
//
// A mute affordance touches `master` only, never a single bus (§6.5,
// "Controls").
//
// THE UNLOCK GESTURE — the one gesture before content starts is the boot
// screen's power-on click. unlockAudio() is built to be called from inside
// that single handler, alongside requestFullscreen() (lib/fullscreen.ts).
// It resumes the AudioContext, starts the procedural pad, and kicks off
// narration pre-decoding in the background — none of that blocks the
// caller, and nothing here ever throws: audio is an enhancement, never
// load-bearing.

import { routeTrophySfxThrough } from "./trophy-sound";

export type Bus = "music" | "sfx" | "voice";

export type BedState =
  | "boot"
  | "calm"
  | "kiddie"
  | "devil"
  | "game"
  | "question"
  | "life-lost"
  | "checkpoint"
  | "platinum";

// Nominal bus levels. "Nominal" = where a bus sits when nothing is ducking
// it.
//
// MUSIC WAS INAUDIBLE AT -20dB. The tracks are mastered to -15 LUFS by
// tools/prep-music.sh, so a -20dB bus under a -6dB master put the bed at
// roughly -41 LUFS at the output — technically playing, practically silent,
// and reported as "the volume is so low". The three gain stages have to be
// read together, not tuned one at a time: source LUFS + bus + master is the
// only number that matters, and it should land near -26 LUFS for a bed that
// sits under speech without disappearing.
const NOMINAL_DB: Record<Bus, number> = { music: -9, sfx: -3, voice: 0 };

// Headroom on the master. Small now rather than -6dB, because the limiter
// below — not this constant — is what actually guarantees no clipping when
// three buses peak together. Using headroom for that job meant paying the
// cost on every quiet moment as well.
const MASTER_HEADROOM_DB = -2;

// Duck depths, expressed as offsets FROM each bus's nominal rather than as
// absolute levels. The absolute form (-32dB for the voice duck) silently
// encoded the old -20dB music nominal: it read as a 12dB duck then and
// would have become a 23dB duck the moment the nominal moved, which is how
// a volume fix turns into "the music vanishes whenever anyone speaks".
const DUCK_UNDER_VOICE_DB = -12;
const DUCK_SFX_UNDER_VOICE_DB = -6;
const DUCK_UNDER_STING_DB = -6;
const THINNED_BED_DB = -6;

function dbToGain(db: number): number {
  return Math.pow(10, db / 20);
}

// ---- Narration ----------------------------------------------------------
// "Generated once at authoring time and committed as static audio" (§6.5).
// The actual files are a content-authoring deliverable outside this task's
// file ownership (web/shell, lib/audio.ts, lib/fullscreen.ts) — this module
// owns the mechanism: pre-decode on unlock, play through VOICE with the
// right ducking. Until those files exist, fetch() 404s and preload/play
// both resolve to a silent no-op — which is the "sound is never
// load-bearing" contract exercised in practice, not just claimed.
// NARRATION IS OFF. Flip this to true to bring it back — nothing else needs
// to change, the files and the wiring are all still here.
//
// Two generations were rejected as robotic: gpt-4o-mini-tts with default
// delivery, then gpt-audio-1.5 with heavy direction. The second was a large
// technical improvement and still landed as "so bad". At that point the
// problem stops looking like execution and starts looking like the premise.
//
// The note that decided it was "I thought of PS5, you created 1989's Wii".
// That is not a complaint about voice quality — it is a genre observation,
// and it is correct. A PS5 does not talk. Its boot is a tone and a hum. Its
// trophy pop is a sound, not a sentence. Consoles that narrate themselves —
// Wii, Kinect, early smart TVs — are exactly the reference being rejected,
// and no amount of better TTS moves a product from one category to the
// other. Synthetic speech also degrades badly through Discord's codec, which
// is the only way he will ever hear it.
//
// So the console goes quiet and says what it has to say in text, which it
// was already doing: every narrated line has an on-screen counterpart
// (Install.tsx's SUBTITLES, Boot's status, the trophy toast). Nothing is
// lost but the voice.
const NARRATION_ENABLED = false;

const NARRATION_MANIFEST: Record<string, string> = {
  boot: "/audio/narration/boot.mp3",
  // Only the 1st and 3rd install beats are narrated — four lines is 10.1s of
  // speech inside a 6.5s install. See Install.tsx's SUBTITLES comment.
  "install-1": "/audio/narration/install-1.mp3",
  "install-3": "/audio/narration/install-3.mp3",
  // The payoff line, fired from Console.tsx's platinum sting. Deliberately
  // the only trophy that speaks: a voice line on all nineteen would grate.
  platinum: "/audio/narration/platinum.mp3",
};

// ---- The music bed (§6.5, "The music bed reacts to state") ---------------
//
// REAL AUDIO FILES, NOT SYNTHESIS. Two attempts at generating this
// procedurally both came back as "a motor": first a literal sustained
// sawtooth drone, then sparse notes still sitting on a held sine root. The
// second attempt fixed the melody and kept the hum, which is the same
// mistake twice. Anything continuously sounding, however carefully voiced,
// reads as machinery through a laptop speaker on a Discord call — and this
// is not a problem worth a third try when licensed music is a download away.
//
// So: each bed state maps to a looping track. Tracks crossfade, they never
// cut. Several states deliberately share one file — four tracks cover nine
// states, which keeps the sourcing job small enough to actually finish.
//
// MISSING FILES ARE SILENT, NEVER SUBSTITUTED. There is no synthesised
// fallback on purpose: silence is a neutral absence, where a drone is an
// actively bad sound that nobody would choose. `missingBedTracks()` reports
// what did not load so the shortfall is visible rather than discovered on
// the night.

/** The four tracks, already prepared as seamless level-matched loops by
 *  `tools/prep-music.sh` — do not drop a raw generated file in here.
 *
 *  These play through an AudioBufferSourceNode with `loop = true`, which
 *  butt-joins the buffer's end to its start; unless the waveform matches
 *  across that seam it clicks, once per loop, for the whole run. WebAudio
 *  has no crossfading-loop primitive, so the crossfade is baked into the
 *  file instead. The prep script also trims each track to its strongest
 *  section and matches all four to -15 LUFS, so a state change never jumps
 *  in level. See that script for the construction and the per-track
 *  regions. */
const BED_TRACKS = {
  /** Calm, sparse, ambient. The default state of the console: menus, the
   *  countdown, and the question screen. Should be able to sit under a
   *  voice line without competing with it. */
  menu: "/audio/music/menu.mp3",
  /** Darker and heavier, same tempo family as `menu` so the Devil swap
   *  reads as the room changing rather than the soundtrack changing. */
  tense: "/audio/music/tense.mp3",
  /** In-game. Forward motion, a pulse, but no melody strong enough to
   *  fight the game's own sound effects. */
  game: "/audio/music/game.mp3",
  /** Warm and resolving, for the two moments that pay off: clearing an act
   *  and the platinum. */
  triumph: "/audio/music/triumph.mp3",
} as const;

type BedTrack = keyof typeof BED_TRACKS;

/** Nine states, four files. `question` shares `menu` and is separated from
 *  it by the -6dB bus duck in `setBedState` rather than by a different
 *  track — the design calls for the bed to thin there, not to change. */
const BED_TRACK_FOR: Record<BedState, BedTrack> = {
  boot: "menu",
  calm: "menu",
  kiddie: "menu",
  question: "menu",
  devil: "tense",
  "life-lost": "tense",
  game: "game",
  checkpoint: "triumph",
  platinum: "triumph",
};

// Bed states that duck MUSIC ~6dB below its own nominal while active, per
// the ducking table. This is how `question` is distinguished from the other
// states sharing the `menu` track: the bed thins there rather than changing.
// checkpoint/platinum resolve *upward* instead, so they are intentionally
// not in this set.
const THINNED_STATES = new Set<BedState>(["question"]);

// Crossfade length. Long enough that a state change feels like a room
// changing rather than a track being swapped; short enough that the new
// state is established before he has finished reading the screen.
const BED_CROSSFADE_S = 1.4;

class MusicBed {
  private ctx: AudioContext;
  private destination: AudioNode;
  private buffers = new Map<BedTrack, AudioBuffer>();
  private failed = new Set<BedTrack>();
  private playing: { track: BedTrack; source: AudioBufferSourceNode; gain: GainNode } | null = null;
  /** Tracks still fading out. A swap detaches the outgoing source and lets
   *  it ring for the crossfade; if another swap lands inside that window
   *  the previous one is STILL SOUNDING, so without this a rapid sequence
   *  of state changes stacks two or three tracks on top of each other --
   *  reported as "two songs at once clashing". They are held here so a new
   *  swap can cut them short instead of leaving them to overlap. */
  private fadingOut = new Set<{ source: AudioBufferSourceNode; gain: GainNode }>();
  private current: BedTrack = BED_TRACK_FOR.boot;
  private started = false;

  constructor(ctx: AudioContext, destination: AudioNode) {
    this.ctx = ctx;
    this.destination = destination;
  }

  /** Fetch and decode every track. Each is independent: one 404 costs that
   *  track and nothing else. Never throws — audio is an enhancement. */
  async load(): Promise<void> {
    await Promise.all(
      (Object.keys(BED_TRACKS) as BedTrack[]).map(async (track) => {
        try {
          const response = await fetch(BED_TRACKS[track]);
          if (!response.ok) throw new Error(String(response.status));
          this.buffers.set(track, await this.ctx.decodeAudioData(await response.arrayBuffer()));
        } catch {
          this.failed.add(track);
        }
      }),
    );
    // A load that finishes after start() must still bring the bed in.
    if (this.started && !this.playing) this.swapTo(this.current);
  }

  missing(): string[] {
    return [...this.failed].map((track) => BED_TRACKS[track]);
  }

  private swapTo(track: BedTrack): void {
    const buffer = this.buffers.get(track);
    const now = this.ctx.currentTime;

    // Fade the outgoing one out and stop it once it is actually silent —
    // stopping on the fade's start would defeat the crossfade entirely.
    // Anything already mid-fade gets cut short rather than allowed to ring
    // under a second incoming track.
    for (const stale of this.fadingOut) {
      stale.gain.gain.cancelScheduledValues(now);
      stale.gain.gain.setValueAtTime(stale.gain.gain.value, now);
      stale.gain.gain.linearRampToValueAtTime(0, now + 0.12);
      try {
        stale.source.stop(now + 0.15);
      } catch {
        // already stopped; nothing to do
      }
    }

    if (this.playing) {
      const outgoing = this.playing;
      this.fadingOut.add(outgoing);
      outgoing.gain.gain.cancelScheduledValues(now);
      outgoing.gain.gain.setValueAtTime(outgoing.gain.gain.value, now);
      outgoing.gain.gain.linearRampToValueAtTime(0, now + BED_CROSSFADE_S);
      outgoing.source.stop(now + BED_CROSSFADE_S + 0.05);
      outgoing.source.onended = () => {
        this.fadingOut.delete(outgoing);
        outgoing.source.disconnect();
        outgoing.gain.disconnect();
      };
      this.playing = null;
    }

    if (!buffer) return; // missing track: silence, never a substitute

    const gain = this.ctx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(1, now + BED_CROSSFADE_S);
    gain.connect(this.destination);

    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.loop = true;
    source.connect(gain);
    source.start(now);

    this.playing = { track, source, gain };
  }

  start(): void {
    if (this.started) return;
    this.started = true;
    this.swapTo(this.current);
  }

  setState(state: BedState): void {
    const track = BED_TRACK_FOR[state];
    this.current = track;
    // States sharing a track must not restart it: going kiddie -> question
    // is a bus-level duck, not a new piece of music.
    if (!this.started || this.playing?.track === track) return;
    this.swapTo(track);
  }

  stop(): void {
    if (!this.playing) return;
    this.playing.source.stop();
    this.playing.source.disconnect();
    this.playing.gain.disconnect();
    this.playing = null;
  }
}

type Engine = {
  ctx: AudioContext;
  master: GainNode;
  buses: Record<Bus, GainNode>;
  pad: MusicBed;
  muted: boolean;
  bedState: BedState;
  narrationBuffers: Map<string, AudioBuffer>;
  narrationSource: AudioBufferSourceNode | null;
};

let engine: Engine | null = null;
let pendingBedState: BedState = "boot";
let unlockPromise: Promise<void> | null = null;
let voiceDuckActive = false;

function getAudioContextCtor(): typeof AudioContext | undefined {
  if (typeof window === "undefined") return undefined;
  return (
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  );
}

function buildEngine(): Engine | null {
  const Ctor = getAudioContextCtor();
  if (!Ctor) return null;

  const ctx = new Ctor();

  // Safety limiter, last thing before the speakers. This is what makes a
  // near-unity master safe: it only engages on the rare moments when three
  // buses peak together (a trophy sting under narration over the bed), and
  // is inaudible the rest of the time. The previous approach — 6dB of
  // permanent master headroom — paid for those peaks continuously, in every
  // quiet moment, which is a large part of why the whole mix was too quiet.
  // Fast attack to actually catch a transient, slow release so it recovers
  // without pumping, and a high ratio because this is a limiter and not a
  // compressor meant to shape anything.
  const limiter = ctx.createDynamicsCompressor();
  limiter.threshold.value = -3;
  limiter.knee.value = 0;
  limiter.ratio.value = 20;
  limiter.attack.value = 0.003;
  limiter.release.value = 0.25;
  limiter.connect(ctx.destination);

  const master = ctx.createGain();
  master.gain.value = dbToGain(MASTER_HEADROOM_DB);
  master.connect(limiter);

  const buses = {
    music: ctx.createGain(),
    sfx: ctx.createGain(),
    voice: ctx.createGain(),
  } satisfies Record<Bus, GainNode>;
  (Object.keys(buses) as Bus[]).forEach((bus) => {
    buses[bus].gain.value = dbToGain(NOMINAL_DB[bus]);
    buses[bus].connect(master);
  });

  const pad = new MusicBed(ctx, buses.music);

  // See the module comment above "TROPHY STING WIRING" — this is the
  // integration seam trophy-sound.ts documents as unwired until this
  // module exists. From here on, playTrophySound() routes through the
  // real SFX bus rather than its own standalone AudioContext.
  routeTrophySfxThrough(ctx, buses.sfx);

  return {
    ctx,
    master,
    buses,
    pad,
    muted: false,
    bedState: "boot",
    narrationBuffers: new Map(),
    narrationSource: null,
  };
}

/** Called from the boot power-on click, alongside requestFullscreen().
 *  Safe to call more than once — later calls just resume an
 *  already-suspended context (e.g. Safari re-suspending after the tab
 *  backgrounds). Never throws: a denied or broken AudioContext must not
 *  block boot, fullscreen, or anything downstream of the click. */
export function unlockAudio(): Promise<void> {
  if (unlockPromise) return unlockPromise;

  unlockPromise = (async () => {
    try {
      if (!engine) engine = buildEngine();
      if (!engine) return;
      if (engine.ctx.state === "suspended") await engine.ctx.resume();
      // Not awaited: decoding four music tracks must not hold up the boot
      // click. `MusicBed.load` starts playback itself if it finishes after
      // start(), so the bed comes in a moment late rather than not at all.
      void engine.pad.load();
      engine.pad.start();
      engine.pad.setState(pendingBedState);
      engine.bedState = pendingBedState;
      void preloadNarration();
    } catch (error) {
      // Still swallowed — audio is an enhancement, never load-bearing, and
      // nothing here may block boot. But it is no longer SILENT: this catch
      // covers buildEngine(), so one unsupported node type takes out every
      // sound in the app while the run continues perfectly happily, and the
      // only symptom is "there's no audio". Adding the master limiter did
      // exactly that under test. A warning costs nothing and turns a
      // mystery into a one-line answer in devtools.
      console.warn("[xxvi] audio unavailable; continuing without it", error);
    }
  })();

  return unlockPromise;
}

export function isAudioUnlocked(): boolean {
  return engine !== null && engine.ctx.state === "running";
}

/** Task 17 connects trophy-sting oscillators straight into this node —
 *  this is the whole contract, not a bag of one-off helpers. */
export function getBus(bus: Bus): GainNode | null {
  return engine ? engine.buses[bus] : null;
}

export function getAudioContext(): AudioContext | null {
  return engine ? engine.ctx : null;
}

/** Which music files failed to load, by path. A missing track is silent by
 *  design (see MusicBed's header) — this is how that silence stays visible
 *  instead of being discovered on the night. Empty before `load()` resolves
 *  and whenever everything is present. */
export function missingBedTracks(): string[] {
  return engine ? engine.pad.missing() : [];
}

// ---- Mute ----------------------------------------------------------------

export function isMuted(): boolean {
  return engine?.muted ?? false;
}

export function setMuted(muted: boolean): void {
  if (!engine) return;
  engine.muted = muted;
  const target = muted ? 0 : dbToGain(MASTER_HEADROOM_DB);
  engine.master.gain.setTargetAtTime(target, engine.ctx.currentTime, 0.05);
}

export function toggleMute(): boolean {
  setMuted(!isMuted());
  return isMuted();
}

// ---- Ducking (§6.5, "Ducking, and why the question phase is quiet") ------
// All ramps via setTargetAtTime — never an instant gain change, which
// clicks.

function rampBus(bus: Bus, db: number, timeConstantSec: number): void {
  if (!engine) return;
  engine.buses[bus].gain.setTargetAtTime(dbToGain(db), engine.ctx.currentTime, timeConstantSec);
}

/** VOICE plays → MUSIC to -32dB, SFX to -6dB. Attack 120ms, release 400ms. */
export function duckForVoice(active: boolean): void {
  voiceDuckActive = active;
  if (active) {
    rampBus("music", NOMINAL_DB.music + DUCK_UNDER_VOICE_DB, 0.12);
    rampBus("sfx", NOMINAL_DB.sfx + DUCK_SFX_UNDER_VOICE_DB, 0.12);
  } else {
    rampBus("music", NOMINAL_DB.music, 0.4);
    rampBus("sfx", NOMINAL_DB.sfx, 0.4);
  }
}

/** Trophy sting → MUSIC -6dB for the sting's length. Task 17 calls this
 *  around its sting playback, on the same event that starts the sting. */
export function duckForSting(durationMs: number): void {
  rampBus("music", NOMINAL_DB.music + DUCK_UNDER_STING_DB, 0.08);
  setTimeout(() => {
    if (!voiceDuckActive) rampBus("music", NOMINAL_DB.music, 0.4);
  }, durationMs);
}

// ---- Operator toast chime -------------------------------------------
// A live message from the operator, mid-run (ws-messages.ts's ToastMsg,
// shell/OperatorToast.tsx). This module already owns the real SFX bus (no
// parallel-task seam to cross, unlike lib/trophy-sound.ts's situation), so
// the chime is generated straight through `engine.buses.sfx` here rather
// than in its own module.
//
// Deliberately NOT a trophy sting reused verbatim: a trophy pop always
// sweeps upward in pitch (lib/trophy-sound.ts's SPECS) because it's an
// escalating achievement. This is a flat two-note chime — same register
// as a UI notification, not an award — so the two are distinguishable by
// ear alone, on top of everything OperatorToast.tsx already does visually.
// Ducks MUSIC the same way a trophy sting does (§6.5's only documented
// precedent for "an SFX event ducks MUSIC for the event's length") by
// reusing `duckForSting` below — the ramp itself has nothing
// trophy-specific about it.
const TOAST_CHIME_MS = 260;

/** No-op if the engine hasn't been unlocked yet, or if anything about
 *  playback fails — sound is never load-bearing (§6.5, §9); the toast
 *  itself carries every bit of meaning visually regardless of whether
 *  this plays. */
export function playOperatorToastSound(): void {
  if (!engine) return;
  try {
    const { ctx, buses } = engine;
    if (ctx.state === "suspended") void ctx.resume().catch(() => undefined);

    const start = ctx.currentTime;
    const durationS = TOAST_CHIME_MS / 1000;
    const end = start + durationS;

    const envelope = ctx.createGain();
    envelope.gain.setValueAtTime(0.0001, start);
    envelope.gain.linearRampToValueAtTime(0.2, start + 0.012);
    envelope.gain.setValueAtTime(0.2, Math.max(start + 0.012, end - 0.08));
    envelope.gain.exponentialRampToValueAtTime(0.0001, end);
    envelope.connect(buses.sfx);

    // Two flat notes in quick succession, not a sweep — see module
    // comment above.
    [587.33, 880.0].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, start);
      const voiceStart = start + i * 0.09;
      osc.connect(envelope);
      osc.start(voiceStart);
      osc.stop(end + 0.05);
      osc.onended = () => osc.disconnect();
    });

    duckForSting(TOAST_CHIME_MS);
  } catch {
    // deliberately swallowed — see module comment.
  }
}

/** Shifts the ambient bed to match run state (boot/calm/kiddie/devil now;
 *  game/question/life-lost/checkpoint/platinum are here for tasks 17-20 to
 *  drive). The difficulty palette swap and the audio swap are one event —
 *  call this from the same handler that flips the palette (see
 *  DifficultySelect.tsx), not from a separate effect reacting to it. */
/** Take the whole console silent, for good. Fades the master out over
 *  `fadeMs`, stops the music bed, and suspends the AudioContext.
 *
 *  Muting is not enough here: `setMuted` only pulls the master gain to zero
 *  while every source keeps running, so the tracks are still playing behind
 *  a closed door and a later unmute brings them straight back. Powering the
 *  console off has to actually stop them. */
export function shutdownAudio(fadeMs = 1600): void {
  if (!engine) return;
  const { ctx, master, pad } = engine;
  try {
    const now = ctx.currentTime;
    master.gain.cancelScheduledValues(now);
    master.gain.setValueAtTime(master.gain.value, now);
    // A ramp, not a cut: a hard stop reads as the page crashing rather than
    // as a console shutting down.
    master.gain.linearRampToValueAtTime(0.0001, now + fadeMs / 1000);
    window.setTimeout(() => {
      try {
        pad.stop();
        void ctx.suspend();
      } catch {
        // Already gone. Nothing to do, and nothing worth surfacing.
      }
    }, fadeMs + 80);
  } catch {
    // Audio is never load-bearing — see this module's header.
  }
}

export function setBedState(state: BedState): void {
  pendingBedState = state;
  if (!engine) return;
  engine.bedState = state;
  engine.pad.setState(state);
  rampBus(
    "music",
    NOMINAL_DB.music + (THINNED_STATES.has(state) ? THINNED_BED_DB : 0),
    0.6,
  );
}

// ---- Narration -------------------------------------------------------

export async function preloadNarration(files: Record<string, string> = NARRATION_MANIFEST): Promise<void> {
  // Skips the fetches entirely when narration is off, rather than
  // downloading and decoding audio nothing will ever play.
  if (!engine || !NARRATION_ENABLED) return;
  const ctx = engine.ctx;
  const buffers = engine.narrationBuffers;
  await Promise.all(
    Object.entries(files).map(async ([key, url]) => {
      if (buffers.has(key)) return;
      try {
        const response = await fetch(url);
        if (!response.ok) return;
        const data = await response.arrayBuffer();
        const buffer = await ctx.decodeAudioData(data);
        buffers.set(key, buffer);
      } catch {
        // No asset yet, or the browser couldn't decode it — narration is
        // never load-bearing, every cue has a visual equivalent (§6.5).
      }
    }),
  );
}

/** Plays a pre-decoded narration line through VOICE, ducking MUSIC/SFX for
 *  its length (§6.5's voice-ducking rule). No-ops silently if the line
 *  never finished decoding — see the module comment on NARRATION_MANIFEST. */
export function playNarration(key: string): void {
  // Gated here rather than at each of the four call sites: this way the
  // cue points stay in the code, documenting where the console WOULD
  // speak, and flipping NARRATION_ENABLED restores all of them at once.
  if (!engine || !NARRATION_ENABLED) return;
  const buffer = engine.narrationBuffers.get(key);
  if (!buffer) return;

  engine.narrationSource?.stop();
  const source = engine.ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(engine.buses.voice);
  engine.narrationSource = source;

  duckForVoice(true);
  source.onended = () => {
    if (engine?.narrationSource === source) {
      engine.narrationSource = null;
      duckForVoice(false);
    }
  };
  source.start();
}
