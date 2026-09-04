import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StackTower } from "../src/games/StackTower";

function press(code = "Space", repeat = false) {
  act(() => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code, repeat }));
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("StackTower", () => {
  it("shows the target it is played against", () => {
    render(<StackTower seed="s" params={{ target: 8 }} onFinish={vi.fn()} />);
    expect(screen.getByText("/ 8")).toBeDefined();
  });

  it("passes the moment the target is reached", () => {
    // target 1: the first block spawns flush left against a centred base, so
    // it always overlaps. One drop reaches the target, and reaching it must
    // end the segment immediately rather than playing on until a miss —
    // which is the whole difference from the original game.
    const onFinish = vi.fn();
    render(<StackTower seed="s" params={{ target: 1 }} onFinish={onFinish} />);
    press();
    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(onFinish.mock.calls[0][0]).toMatchObject({ passed: true });
    expect(onFinish.mock.calls[0][0].score).toBe(1);
  });

  it("ends the segment on a single miss, after the toppling block is visible", () => {
    // SINGLE TRY is the point of this mechanic: the miss IS the game, so
    // unlike Simon there is no allowance. The delay exists so the cause is
    // on screen before the failure screen replaces it.
    vi.useFakeTimers();
    const onFinish = vi.fn();
    render(<StackTower seed="s" params={{ target: 9 }} onFinish={onFinish} />);

    press(); // places, narrowing the tower
    press(); // second drop cannot overlap the narrowed block: a miss

    expect(onFinish).not.toHaveBeenCalled(); // still showing the topple
    act(() => {
      vi.advanceTimersByTime(800);
    });
    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(onFinish.mock.calls[0][0]).toMatchObject({ passed: false });
  });

  it("reports exactly one outcome however hard the drop key is hammered", () => {
    vi.useFakeTimers();
    const onFinish = vi.fn();
    render(<StackTower seed="s" params={{ target: 9 }} onFinish={onFinish} />);
    for (let i = 0; i < 12; i++) press();
    act(() => {
      vi.advanceTimersByTime(1200);
    });
    expect(onFinish).toHaveBeenCalledTimes(1);
  });

  it("ignores auto-repeat so a held key is one drop, not many", () => {
    const onFinish = vi.fn();
    render(<StackTower seed="s" params={{ target: 3 }} onFinish={onFinish} />);
    for (let i = 0; i < 5; i++) press("Space", true);
    expect(onFinish).not.toHaveBeenCalled();
  });

  it("never reports more blocks than drops", () => {
    // The server band (STACK_INPUT_MAX_MULTIPLIER) rejects a run claiming
    // more blocks placed than drops made, so this relationship is
    // load-bearing rather than cosmetic.
    const onFinish = vi.fn();
    render(<StackTower seed="s" params={{ target: 1 }} onFinish={onFinish} />);
    press();
    const outcome = onFinish.mock.calls[0][0];
    expect(outcome.inputCount).toBeGreaterThanOrEqual(outcome.score);
  });
});
