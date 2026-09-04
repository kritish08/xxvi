// `config.copy.how_to_play` used to be dead config: the server served it,
// it reached the generated API types, and no component ever read it.
// HowToPlay hardcoded the whole screen instead — including a heading
// ("2 acts · 8 trophies of memory · 8 of skill") that was simply wrong for
// any config that wasn't the author's own. These tests pin two things:
// the screen actually renders `copy`, and the heading is derived from the
// real trophy list rather than hardcoded, so it can never disagree with
// the loaded config.

import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HowToPlay } from "../src/shell/HowToPlay";
import { runApi } from "../src/lib/run-client";

vi.mock("../src/lib/run-client", () => ({ runApi: { ackHowto: vi.fn() } }));

function trophy(id: string) {
  return { id, name: id, grade: "bronze" as const, hidden: false };
}

// A three-act, 12-segment fixture — deliberately NOT "2 acts / 8 / 8", so a
// test that only ever exercised the old hardcoded numbers couldn't pass by
// accident.
function threeActFixture() {
  return [
    ...[1, 2, 3, 4, 5, 6].map((i) => trophy(`game-${i}`)),
    ...[1, 2, 3, 4, 5, 6].map((i) => trophy(`question-${i}`)),
    ...[1, 2, 3].map((i) => trophy(`act-${i}`)),
    trophy("platinum"),
  ];
}

describe("HowToPlay", () => {
  it("derives the heading from the real config instead of hardcoding a count", () => {
    render(
      <HowToPlay onDone={vi.fn()} copy="Answer trivia and clear the mini-games." trophies={threeActFixture()} />,
    );
    expect(screen.getByRole("heading")).toHaveTextContent(/3 acts/);
    expect(screen.getByRole("heading")).toHaveTextContent(/6 trophies of memory/);
    expect(screen.getByRole("heading")).toHaveTextContent(/6 of skill/);
    // The old hardcoded numbers must not survive for a config shaped
    // differently than the author's own.
    expect(screen.queryByText(/2 acts/)).toBeNull();
    expect(screen.queryByText(/8 trophies of memory/)).toBeNull();
  });

  it("renders the configured how_to_play copy, not hardcoded lines", () => {
    render(
      <HowToPlay
        onDone={vi.fn()}
        copy={"Answer trivia and clear the mini-games to earn trophies.\nMiss too much and the Devil takes over."}
        trophies={threeActFixture()}
      />,
    );
    expect(screen.getByText(/Answer trivia and clear the mini-games/)).toBeInTheDocument();
    expect(screen.getByText(/Miss too much and the Devil takes over/)).toBeInTheDocument();
  });

  it("splits a multi-line copy string into separate lines, not one run-on paragraph", () => {
    render(
      <HowToPlay
        onDone={vi.fn()}
        copy={"First line here.\nSecond line here."}
        trophies={threeActFixture()}
      />,
    );
    const first = screen.getByText(/First line here/);
    const second = screen.getByText(/Second line here/);
    expect(first).not.toBe(second);
  });

  it("degrades gracefully when copy is empty, rather than crashing", () => {
    render(<HowToPlay onDone={vi.fn()} copy="" trophies={threeActFixture()} />);
    expect(screen.getByRole("button", { name: /start/i })).toBeInTheDocument();
  });

  it("still explains KIDDIE and DEVIL, and starts the run on click", async () => {
    render(
      <HowToPlay onDone={vi.fn()} copy="Answer trivia and clear the mini-games." trophies={threeActFixture()} />,
    );
    expect(screen.getByText(/KIDDIE/)).toBeInTheDocument();
    expect(screen.getByText(/DEVIL/)).toBeInTheDocument();

    const onDone = vi.fn();
    render(
      <HowToPlay onDone={onDone} copy="Answer trivia and clear the mini-games." trophies={threeActFixture()} />,
    );
    await userEvent.click(screen.getAllByRole("button", { name: /start/i })[1]);
    expect(runApi.ackHowto).toHaveBeenCalled();
    expect(onDone).toHaveBeenCalled();
  });
});
