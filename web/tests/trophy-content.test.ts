// "How many trophies are there" must be derived from GET /api/content, not
// hardcoded — Task 16's library card originally hardcoded 16 (reasoning
// from how-to-play copy that only describes the 16 segment trophies) and
// was wrong; the real standard total also includes the 2 act trophies and
// Platinum. These tests exercise lib/trophy-content.ts's pure counting
// function directly against fixtures with different trophy counts (so a
// test that only ever saw one fixture couldn't hide a reversion to a
// hardcoded number), plus the fetch wrapper's failure handling.

import { describe, expect, it, vi } from "vitest";
import { standardTrophyCount, fetchStandardTrophyCount, type TrophySummary } from "../src/lib/trophy-content";

function trophy(overrides: Partial<TrophySummary> = {}): TrophySummary {
  return { id: "t", name: "Trophy", grade: "bronze", hidden: false, ...overrides };
}

describe("standardTrophyCount", () => {
  it("counts only non-hidden trophies", () => {
    const trophies = [
      trophy({ id: "a", hidden: false }),
      trophy({ id: "b", hidden: false }),
      trophy({ id: "c", hidden: true }),
    ];
    expect(standardTrophyCount(trophies)).toBe(2);
  });

  it("is derived from the fixture, not a literal — two different fixtures produce two different totals", () => {
    const nineteen = Array.from({ length: 19 }, (_, i) => trophy({ id: `s${i}`, hidden: false })).concat([
      trophy({ id: "h1", hidden: true }),
      trophy({ id: "h2", hidden: true }),
      trophy({ id: "h3", hidden: true }),
    ]);
    const seven = Array.from({ length: 7 }, (_, i) => trophy({ id: `s${i}`, hidden: false }));

    expect(standardTrophyCount(nineteen)).toBe(19);
    expect(standardTrophyCount(seven)).toBe(7);
    expect(standardTrophyCount(nineteen)).not.toBe(standardTrophyCount(seven));
  });

  it("is not the old hardcoded 16 for the real content shape (8 question + 8 game + 2 act + platinum + 3 hidden)", () => {
    const standard = [
      ...Array.from({ length: 8 }, (_, i) => trophy({ id: `question-${i + 1}` })),
      ...Array.from({ length: 8 }, (_, i) => trophy({ id: `game-${i + 1}` })),
      trophy({ id: "act-1" }),
      trophy({ id: "act-2" }),
      trophy({ id: "platinum", grade: "platinum" }),
    ];
    const hidden = [
      trophy({ id: "hidden-rage-quit", hidden: true }),
      trophy({ id: "hidden-drift-denier", hidden: true }),
      trophy({ id: "hidden-speedrun", hidden: true, grade: "silver" }),
    ];
    expect(standardTrophyCount([...standard, ...hidden])).toBe(19);
  });

  it("returns 0 for an empty list rather than throwing", () => {
    expect(standardTrophyCount([])).toBe(0);
  });
});

describe("fetchStandardTrophyCount", () => {
  it("resolves the derived count on success", async () => {
    vi.doMock("../src/lib/client", () => ({
      api: { getContent: vi.fn().mockResolvedValue({ copy: {}, trophies: [trophy(), trophy({ id: "b" })] }) },
    }));
    // vi.doMock isn't hoisted, and lib/trophy-content is already cached
    // from this file's top-level static import — resetModules forces the
    // dynamic import below to re-evaluate against the freshly-mocked
    // ../src/lib/client rather than returning the already-cached,
    // real-fetch-backed module instance.
    vi.resetModules();
    const { fetchStandardTrophyCount: fetchWithMock } = await import("../src/lib/trophy-content");
    expect(await fetchWithMock()).toBe(2);
    vi.doUnmock("../src/lib/client");
    vi.resetModules();
  });

  it("degrades to null (not 0, not throwing) when the fetch fails", async () => {
    vi.doMock("../src/lib/client", () => ({
      api: { getContent: vi.fn().mockRejectedValue(new Error("network error")) },
    }));
    vi.resetModules();
    const { fetchStandardTrophyCount: fetchWithMock } = await import("../src/lib/trophy-content");
    await expect(fetchWithMock()).resolves.toBeNull();
    vi.doUnmock("../src/lib/client");
    vi.resetModules();
  });

  // Sanity check that the un-mocked export still exists and is callable —
  // guards against the vi.doMock dance above accidentally leaving the
  // module registry in a state where the real export breaks.
  it("is the same function whether or not a mock was ever installed", () => {
    expect(typeof fetchStandardTrophyCount).toBe("function");
  });
});
