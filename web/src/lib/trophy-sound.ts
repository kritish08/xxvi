// Trophy pop stings — docs/design-system.md §6.5 ("Four buses") and §7
// ("Trophy sounds: WebAudio oscillators, one short sweep per grade,
// ascending. No audio files, nothing to fail to load.").
//
// Sound is never load-bearing (§6.5, §9): every failure path here is
// swallowed, and every export is safe to call in an environment with no
// Web Audio at all (including this module's own Vitest/jsdom run).
//
// --- Bus integration (read before "fixing" the missing import) ---
//
// §6.5 defines MUSIC/SFX/VOICE as three gain nodes owned by lib/audio.ts
// (Task 16's file, explicitly off-limits to this task) so that levels and
// ducking live in one place. Trophy pops are supposed to route through the
// SFX bus rather than straight to the destination.
//
// Task 16 is being built in parallel in a different worktree, so
// lib/audio.ts does not exist here. Importing it would break `npm run
// build` in *this* worktree today, and guessing its export names would
// likely just be wrong — worse than not integrating at all, because it
// would fail silently at merge instead of loudly at compile time.
//
// So: this module is self-sufficient by default (it lazily creates its own
// AudioContext and a single gain node standing in for the SFX bus, at the
// bus's documented nominal level of 0dB / gain 1) and exposes exactly one
// integration seam, `routeTrophySfxThrough`. Whoever wires the app after
// Task 16 lands calls it once with the real AudioContext and SFX GainNode;
// every pop from that point on plays through the shared bus — and
// therefore ducks, and gets ducked, correctly — instead of this module's
// standalone path. Nothing else about this file needs to change for that
// to work.
//
// ASSUMPTION flagged for the integrator: the reverse direction — "trophy
// sting -> MUSIC -6dB for the sting's length" (§6.5 ducking rules) — can't
// be implemented from this file, because it requires reaching into the
// MUSIC bus, which this module deliberately never touches. TrophyToast
// exposes an `onSting` callback for exactly this: wire it to lib/audio.ts's
// duck function once that file exists.

export type Grade = "bronze" | "silver" | "gold" | "platinum";

function getAudioContextCtor(): typeof AudioContext | undefined {
  if (typeof AudioContext !== "undefined") return AudioContext;
  const g = globalThis as { webkitAudioContext?: typeof AudioContext };
  return g.webkitAudioContext;
}

let ownContext: AudioContext | null = null;
let ownBus: GainNode | null = null;
let externalContext: AudioContext | null = null;
let externalBus: AudioNode | null = null;

function resolveBus(): { ctx: AudioContext; bus: AudioNode } | null {
  if (externalContext && externalBus) return { ctx: externalContext, bus: externalBus };
  if (ownContext && ownBus) return { ctx: ownContext, bus: ownBus };

  const Ctor = getAudioContextCtor();
  if (!Ctor) return null;
  try {
    const ctx = new Ctor();
    const bus = ctx.createGain();
    bus.gain.value = 1; // 0dB nominal — matches the SFX bus's documented level
    bus.connect(ctx.destination);
    ownContext = ctx;
    ownBus = bus;
    return { ctx, bus };
  } catch {
    return null;
  }
}

/**
 * Integration seam for lib/audio.ts's real SFX bus (docs/design-system.md
 * §6.5). Call once, after Task 16 lands, with its AudioContext and SFX
 * GainNode. Every `playTrophySound` call after that routes through it.
 */
export function routeTrophySfxThrough(context: AudioContext, sfxBus: AudioNode): void {
  externalContext = context;
  externalBus = sfxBus;
}

type Voice = { freqStart: number; freqEnd: number; type: OscillatorType; detuneCents?: number };
type GradeSpec = { voices: Voice[]; durationMs: number; peakGain: number };

// Bronze -> silver -> gold escalate in pitch and length (§7). Platinum
// deliberately breaks that climb: it starts *lower* than gold, adds more
// detuned voices for width, and runs the ~1.8s length §6.5 specifies for
// the platinum sting — "lands lower, wider and longer."
const SPECS: Record<Grade, GradeSpec> = {
  bronze: {
    voices: [{ freqStart: 392.0, freqEnd: 523.25, type: "sine" }], // G4 -> C5
    durationMs: 260,
    peakGain: 0.22,
  },
  silver: {
    voices: [
      { freqStart: 523.25, freqEnd: 659.25, type: "sine" }, // C5 -> E5
      { freqStart: 659.25, freqEnd: 830.61, type: "triangle", detuneCents: 4 }, // E5 -> Ab5
    ],
    durationMs: 340,
    peakGain: 0.22,
  },
  gold: {
    voices: [
      { freqStart: 659.25, freqEnd: 880.0, type: "triangle" }, // E5 -> A5
      { freqStart: 880.0, freqEnd: 1108.73, type: "sine", detuneCents: 6 }, // A5 -> Db6
      { freqStart: 440.0, freqEnd: 587.33, type: "sine", detuneCents: -5 }, // A4 -> D5, under-voice
    ],
    durationMs: 420,
    peakGain: 0.24,
  },
  platinum: {
    voices: [
      { freqStart: 220.0, freqEnd: 440.0, type: "sawtooth" }, // A3 -> A4, lower start than gold
      { freqStart: 220.0, freqEnd: 440.0, type: "sine", detuneCents: -9 },
      { freqStart: 220.0, freqEnd: 440.0, type: "sine", detuneCents: 9 }, // +/- detune = the "wider" width
      { freqStart: 330.0, freqEnd: 660.0, type: "triangle", detuneCents: 4 },
    ],
    durationMs: 1800,
    peakGain: 0.26,
  },
};

/**
 * Schedules a grade's sting against `ctx.currentTime` — never `setTimeout`
 * — so it starts as close to "now" as Web Audio scheduling allows. Callers
 * that must keep a CSS animation in lockstep (TrophyToast) call this
 * synchronously from the exact handler that starts the animation, per
 * §6.5's "Sync" rule. No-op, swallowed, if Web Audio is unavailable, if the
 * grade isn't recognised, or if anything about construction fails — sound
 * is a bonus layer and nothing may depend on it (§6.5, §9).
 */
export function playTrophySound(grade: string): void {
  const spec = SPECS[grade as Grade];
  if (!spec) return;

  const target = resolveBus();
  if (!target) return;
  const { ctx, bus } = target;

  try {
    if (ctx.state === "suspended") void ctx.resume().catch(() => undefined);

    const start = ctx.currentTime;
    const durationS = spec.durationMs / 1000;
    const end = start + durationS;
    const attack = Math.min(0.015, durationS / 6);
    const release = Math.min(0.12, durationS / 3);
    const peakPerVoice = spec.peakGain / spec.voices.length;

    const envelope = ctx.createGain();
    envelope.gain.setValueAtTime(0.0001, start);
    envelope.gain.linearRampToValueAtTime(peakPerVoice, start + attack);
    envelope.gain.setValueAtTime(peakPerVoice, Math.max(start + attack, end - release));
    // Exponential ramp toward (not to, that's not representable) zero —
    // the standard way to release a WebAudio envelope without a click.
    envelope.gain.exponentialRampToValueAtTime(0.0001, end);
    envelope.connect(bus);

    for (const voice of spec.voices) {
      const osc = ctx.createOscillator();
      osc.type = voice.type;
      if (voice.detuneCents) osc.detune.setValueAtTime(voice.detuneCents, start);
      osc.frequency.setValueAtTime(voice.freqStart, start);
      osc.frequency.exponentialRampToValueAtTime(Math.max(1, voice.freqEnd), end);
      osc.connect(envelope);
      osc.start(start);
      osc.stop(end + 0.05);
      osc.onended = () => {
        osc.disconnect();
      };
    }
  } catch {
    // deliberately swallowed
  }
}
