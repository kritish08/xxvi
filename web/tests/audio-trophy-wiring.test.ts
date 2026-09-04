// lib/trophy-sound.ts (task 17, off-limits here) documents exactly one
// integration seam for the app it was built in parallel with:
// `routeTrophySfxThrough(context, sfxBus)`, to be called once "at the
// point the audio context is created." This test proves lib/audio.ts's
// buildEngine() actually calls it, with the real engine's own context and
// SFX bus — not just that the call compiles.
//
// jsdom has no Web Audio implementation (trophy.test.tsx notes the same),
// so this stubs the minimal surface lib/audio.ts's buildEngine()/PadSynth
// touch. It is not a substitute for the real-browser check described in
// the task report — it only proves the wiring call happens with the right
// arguments, not that real audio ducks or plays.

import { beforeEach, describe, expect, it, vi } from "vitest";

const routeTrophySfxThrough = vi.fn();
vi.mock("../src/lib/trophy-sound", () => ({ routeTrophySfxThrough }));

class FakeParam {
  value = 0;
  setValueAtTime() {
    return this;
  }
  setTargetAtTime() {
    return this;
  }
  linearRampToValueAtTime() {
    return this;
  }
  exponentialRampToValueAtTime() {
    return this;
  }
}
class FakeNode {
  connect() {
    return this;
  }
  disconnect() {}
}
class FakeGain extends FakeNode {
  gain = new FakeParam();
}
class FakeOscillator extends FakeNode {
  frequency = new FakeParam();
  detune = new FakeParam();
  type = "sine";
  start() {}
  stop() {}
}
class FakeBufferSource extends FakeNode {
  buffer: AudioBuffer | null = null;
  loop = false;
  onended: (() => void) | null = null;
  start() {}
  stop() {}
}
class FakeFilter extends FakeNode {
  frequency = new FakeParam();
  Q = new FakeParam();
  type = "lowpass";
}
/** The master safety limiter (buildEngine's createDynamicsCompressor).
 *  Its absence from this fake is what makes the "engine build must not
 *  throw" assertion below meaningful: buildEngine() runs inside
 *  unlockAudio()'s catch-all, so a missing node type does not surface as an
 *  error — it silently produces NO ENGINE AT ALL, and every sound in the app
 *  becomes a no-op. That is precisely how this test caught the limiter being
 *  added. */
class FakeCompressor extends FakeNode {
  threshold = new FakeParam();
  knee = new FakeParam();
  ratio = new FakeParam();
  attack = new FakeParam();
  release = new FakeParam();
}
class FakeAudioContext {
  currentTime = 0;
  state: "running" | "suspended" = "suspended";
  destination = new FakeNode();
  createGain() {
    return new FakeGain();
  }
  createOscillator() {
    return new FakeOscillator();
  }
  createBiquadFilter() {
    return new FakeFilter();
  }
  createDynamicsCompressor() {
    return new FakeCompressor();
  }
  createBufferSource() {
    return new FakeBufferSource();
  }
  decodeAudioData() {
    return Promise.resolve({} as AudioBuffer);
  }
  resume() {
    this.state = "running";
    return Promise.resolve();
  }
}

beforeEach(() => {
  vi.resetModules();
  routeTrophySfxThrough.mockClear();
  vi.stubGlobal("AudioContext", FakeAudioContext);
});

describe("trophy sting bus wiring", () => {
  it("routes trophy-sound.ts through the real SFX bus at engine creation", async () => {
    const audio = await import("../src/lib/audio");
    await audio.unlockAudio();

    expect(routeTrophySfxThrough).toHaveBeenCalledTimes(1);
    const [ctx, bus] = routeTrophySfxThrough.mock.calls[0] as [unknown, unknown];
    expect(ctx).toBe(audio.getAudioContext());
    expect(bus).toBe(audio.getBus("sfx"));
  });
});
