// The cross-language contract: the server issues a seed, the browser must
// derive the same Simon sequence from it. server/xxvi/games/seeds.py is
// the reference (counter-mode SHA-256, byte % 4, not `random`, precisely
// so the two sides can agree without a round trip). This file is a
// contract test, not an example — if SERVER_VECTOR ever disagrees with
// simonSequence's output, the two sides have drifted and Simon becomes
// unverifiable server-side (server/xxvi/games/verify.py compares the
// player's entered sequence against simon_sequence(seed, length)
// directly).

import { describe, expect, it } from "vitest";
import { simonSequence } from "../src/games/SimonSays";

describe("simonSequence", () => {
  it("is deterministic for a seed", async () => {
    expect(await simonSequence("seed-a", 6)).toEqual(await simonSequence("seed-a", 6));
  });

  it("differs between seeds", async () => {
    expect(await simonSequence("seed-a", 8)).not.toEqual(await simonSequence("seed-b", 8));
  });

  it("makes a short sequence a prefix of a longer one", async () => {
    const long = await simonSequence("seed-a", 8);
    expect(await simonSequence("seed-a", 4)).toEqual(long.slice(0, 4));
  });

  it("emits only face buttons", async () => {
    expect(new Set(await simonSequence("seed-a", 40)).size).toBeLessThanOrEqual(4);
    for (const value of await simonSequence("seed-a", 40)) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(4);
    }
  });

  it("matches the sequence the server generates for a known seed", async () => {
    // Pinned against the real Python reference:
    //   cd server && python3 -c "from xxvi.games.seeds import simon_sequence;
    //   print(simon_sequence('pinned', 8))"
    // => [0, 2, 3, 3, 1, 2, 0, 0]
    expect(await simonSequence("pinned", 8)).toEqual(SERVER_VECTOR);
  });
});

const SERVER_VECTOR: number[] = [0, 2, 3, 3, 1, 2, 0, 0];
