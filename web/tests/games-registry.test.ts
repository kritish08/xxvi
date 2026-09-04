// server/xxvi/content/schema.py::GameSlot.mechanic is the source of truth for
// the mechanic names. Every name that Literal accepts must be registered
// here, or a config referencing it reaches the player as "unknown mechanic"
// on a screen he cannot get past.

import { describe, expect, it } from "vitest";
import { GAMES } from "../src/games/registry";

describe("GAMES registry", () => {
  it("registers every mechanic the content schema accepts", () => {
    // Mirrors Mechanic in server/xxvi/content/schema.py. `stack` is the
    // Kyrex tower game ported in; `update` is no longer used by any segment
    // in config/run.yaml but stays registered and tested, so putting it back
    // is a one-line config change rather than a revert.
    expect(Object.keys(GAMES).sort()).toEqual([
      "drift",
      "simon",
      "stack",
      "trophy_run",
      "update",
    ]);
  });

  it("maps each mechanic to a distinct component", () => {
    const values = Object.values(GAMES);
    expect(new Set(values).size).toBe(values.length);
  });
});
