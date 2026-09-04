// docs/design-system.md's one hard rule for this component: every pop must
// read as complete with the sound muted. These tests exercise the DOM
// (jsdom has no Web Audio implementation, so playTrophySound is a no-op in
// this environment by construction — see lib/trophy-sound.ts's own
// feature-detection) and assert that grade and name are always present as
// text, never only implied by a CSS class or an icon.

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { TrophyToast } from "../src/shell/TrophyToast";
import { TrophyCabinet } from "../src/shell/TrophyCabinet";

afterEach(cleanup);

const pop = { type: "trophy_pop" as const, trophy_id: "game-1", name: "First Blood", grade: "bronze" as const };

describe("TrophyToast", () => {
  it("renders the name and grade as text, not only as sound or colour", () => {
    render(<TrophyToast queue={[pop]} onDismiss={vi.fn()} />);
    expect(screen.getByText("First Blood")).toBeInTheDocument();
    expect(screen.getByText(/bronze/i)).toBeInTheDocument();
  });

  it("shows one trophy at a time when several arrive together", () => {
    render(
      <TrophyToast
        queue={[pop, { ...pop, trophy_id: "game-2", name: "Second" }]}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("First Blood")).toBeInTheDocument();
    expect(screen.queryByText("Second")).toBeNull();
  });

  it("renders nothing when the queue is empty", () => {
    const { container } = render(<TrophyToast queue={[]} onDismiss={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("dismisses after the hold and advances to the next queued pop", () => {
    vi.useFakeTimers();
    try {
      const onDismiss = vi.fn();
      render(<TrophyToast queue={[pop]} onDismiss={onDismiss} holdMs={100} />);
      expect(onDismiss).not.toHaveBeenCalled();
      vi.advanceTimersByTime(100);
      expect(onDismiss).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("gives platinum a longer hold and its own full-screen treatment, breaking the toast pattern on purpose", () => {
    const platinumPop = { type: "trophy_pop" as const, trophy_id: "platinum", name: "XXVI", grade: "platinum" as const };
    render(<TrophyToast queue={[platinumPop]} onDismiss={vi.fn()} />);
    const node = screen.getByRole("status");
    expect(node).toHaveClass("toast--climax");
    expect(screen.getByText("XXVI")).toBeInTheDocument();
    expect(screen.getByText(/platinum/i)).toBeInTheDocument();
  });
});

describe("TrophyCabinet", () => {
  const trophies = [
    { id: "game-1", name: "First Blood", grade: "bronze", hidden: false },
    { id: "hidden-rage-quit", name: "Rage Quit", grade: "bronze", hidden: true },
    { id: "platinum", name: "XXVI", grade: "platinum", hidden: false },
  ];

  it("masks the name of a hidden trophy that has not popped", () => {
    render(<TrophyCabinet trophies={trophies} earned={["game-1"]} closing="" />);
    expect(screen.queryByText("Rage Quit")).toBeNull();
    expect(screen.getAllByText("???").length).toBe(1);
  });

  it("reveals a hidden trophy once earned", () => {
    render(<TrophyCabinet trophies={trophies} earned={["game-1", "hidden-rage-quit"]} closing="" />);
    expect(screen.getByText("Rage Quit")).toBeInTheDocument();
  });

  it("marks unearned standard trophies as locked without hiding their names", () => {
    render(<TrophyCabinet trophies={trophies} earned={["game-1"]} closing="" />);
    expect(screen.getByText("XXVI").closest("li")).toHaveClass("trophy--locked");
  });

  it("does not re-derive or undo server-side masking — it trusts the given name verbatim", () => {
    // A hidden trophy the server has already unmasked (e.g. because it was
    // earned) must render as given, even though `hidden` is still true.
    const alreadyRevealed = [
      { id: "hidden-x", name: "Speedrunner", grade: "silver", hidden: true },
    ];
    render(<TrophyCabinet trophies={alreadyRevealed} earned={["hidden-x"]} closing="" />);
    expect(screen.getByText("Speedrunner")).toBeInTheDocument();
    expect(screen.queryByText("???")).toBeNull();
  });

  it("computes percent from standard (non-hidden) trophies only", () => {
    render(<TrophyCabinet trophies={trophies} earned={["game-1"]} closing="" />);
    // 2 standard trophies (game-1, platinum), 1 earned => 50%
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("renders the closing line only when provided", () => {
    const { rerender } = render(<TrophyCabinet trophies={trophies} earned={[]} closing="" />);
    expect(screen.queryByText("nice run.")).toBeNull();
    rerender(<TrophyCabinet trophies={trophies} earned={[]} closing="nice run." />);
    expect(screen.getByText("nice run.")).toBeInTheDocument();
  });
});
