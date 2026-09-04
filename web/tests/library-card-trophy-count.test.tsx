// The library card (shell/Install.tsx) shows "0 of N trophies" where N
// must come from GET /api/content, not a hardcoded constant — see
// lib/trophy-content.ts's header comment for why the old hardcoded 16 was
// wrong. These tests render the real Install component against a mocked
// api.getContent and assert the displayed number tracks the fixture: two
// different fixtures must produce two different displayed totals (a test
// that only ever checked one fixture couldn't catch a reversion to a
// literal), and a failing fetch must degrade to no count rather than a
// wrong one or a blank screen.

import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Install } from "../src/shell/Install";

const getContent = vi.fn();

vi.mock("../src/lib/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/lib/client")>();
  return {
    ...actual,
    api: { ...actual.api, getContent: (...args: unknown[]) => getContent(...args) },
  };
});

function trophySet(standardCount: number, hiddenCount = 0) {
  return {
    copy: { coming_soon: "", teaser: "", how_to_play: "", closing: "" },
    trophies: [
      ...Array.from({ length: standardCount }, (_, i) => ({
        id: `standard-${i}`,
        name: `Trophy ${i}`,
        grade: "bronze",
        hidden: false,
      })),
      ...Array.from({ length: hiddenCount }, (_, i) => ({
        id: `hidden-${i}`,
        name: "???",
        grade: "bronze",
        hidden: true,
      })),
    ],
  };
}

afterEach(() => {
  getContent.mockReset();
});

describe("Install's library card trophy count", () => {
  it("shows a count derived from a 19-standard/3-hidden fixture — not the old hardcoded 16", async () => {
    getContent.mockResolvedValue(trophySet(19, 3));
    render(<Install onDone={vi.fn()} />);
    expect(await screen.findByText(/0 of 19 trophies/)).toBeInTheDocument();
    expect(screen.queryByText(/0 of 16 trophies/)).toBeNull();
  });

  it("shows a different total for a different fixture, proving the number is derived, not literal", async () => {
    getContent.mockResolvedValue(trophySet(7, 0));
    render(<Install onDone={vi.fn()} />);
    expect(await screen.findByText(/0 of 7 trophies/)).toBeInTheDocument();
  });

  it("degrades to showing no count — never a wrong one, never a blank screen — when the fetch fails", async () => {
    getContent.mockRejectedValue(new Error("network error"));
    render(<Install onDone={vi.fn()} />);

    // The rest of the library card must still be there: not a blank screen.
    expect(screen.getByText(/playing this one since 2006/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "install" })).toBeInTheDocument();

    await waitFor(() => expect(getContent).toHaveBeenCalled());
    // No trophy count text of any kind — degrade to "0%" alone rather than
    // inventing or freezing a number.
    expect(screen.queryByText(/trophies/)).toBeNull();
    expect(screen.getByText("0%")).toBeInTheDocument();
  });
});
