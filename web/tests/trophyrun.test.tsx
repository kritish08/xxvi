import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TrophyRun } from "../src/games/TrophyRun";

describe("TrophyRun", () => {
  it("fails when a prompt's window expires without input", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onFinish = vi.fn();
    render(<TrophyRun seed="s" params={{ prompts: 4, window_ms: 500, lives: 1 }} onFinish={onFinish} />);
    // The prompt sequence loads asynchronously (Web Crypto digest, a real
    // Promise the fake-timer clock does not control) — the previous
    // version of this test guessed it would resolve within a fixed 50ms
    // of *virtual* time. `advanceTimersByTimeAsync` returns as soon as its
    // own internal tick loop is done, in near-zero real wall-clock time —
    // it does not actually sleep 50 real ms, so that guess bought the
    // digest no real time to finish, and under CPU contention from the
    // rest of the suite running concurrently (this project's build-leak
    // test in particular shells out to a real `npm run build`) the digest
    // sometimes genuinely had not resolved yet, `prompts` was still `[]`,
    // the deadline effect's own `if (!prompts.length) return` guard had
    // therefore never armed a timer, and advancing straight to 700ms fired
    // nothing — flaky roughly 1 run in 3 under a full-suite load in
    // practice, always passing in isolation. See task-29 report.
    //
    // The fix waits for a real, polled condition instead of a fixed
    // duration: the first prompt actually on screen, proof `prompts.length
    // > 0` and the deadline timer is armed. `shouldAdvanceTime: true`
    // keeps the fake clock ticking in step with real time while this
    // polls, so the wait is genuinely bounded by when the digest resolves,
    // not by a number that can race.
    await screen.findByLabelText(/prompt/i);
    // A missed window now costs a LIFE, not the segment — this test renders
    // with lives: 1, so the first expiry is still the last one. The
    // multi-life path has its own test below.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: false }));
    vi.useRealTimers();
  });

  it("shows one prompt at a time", async () => {
    render(<TrophyRun seed="s" params={{ prompts: 4, window_ms: 5000 }} onFinish={vi.fn()} />);
    expect(await screen.findAllByLabelText(/prompt/i)).toHaveLength(1);
  });

  it("passes once every prompt is hit correctly, reporting score === prompts", async () => {
    const onFinish = vi.fn();
    render(<TrophyRun seed="run-seed" params={{ prompts: 3, window_ms: 5000 }} onFinish={onFinish} />);

    for (let i = 0; i < 3; i++) {
      const button = await screen.findByLabelText(/prompt/i);
      await userEvent.click(button);
    }

    expect(onFinish).toHaveBeenCalledWith(
      expect.objectContaining({ passed: true, score: 3, inputCount: 3 }),
    );
  });

  it("a wrong face is a retry, not an immediate fail — the run only ends when the window closes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onFinish = vi.fn();
    render(<TrophyRun seed="retry-seed" params={{ prompts: 2, window_ms: 2000 }} onFinish={onFinish} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });

    // Read the CURRENT target off the rendered glyph's aria-label (it
    // literally says which face is correct — the button's own onClick is
    // bound to that value, so clicking it can never miss) and deliberately
    // press a DIFFERENT face's key instead.
    const button = await screen.findByLabelText(/prompt (\w+)/i);
    const label = button.getAttribute("aria-label") ?? "";
    const labels = ["triangle", "circle", "cross", "square"];
    const keys = ["KeyW", "KeyD", "KeyS", "KeyA"];
    const correctFace = labels.findIndex((l) => label.includes(l));
    const wrongFace = (correctFace + 1) % 4;

    window.dispatchEvent(new KeyboardEvent("keydown", { code: keys[wrongFace] }));
    expect(onFinish).not.toHaveBeenCalled();

    // The prompt is still showing the same target (a miss doesn't advance
    // or restart it) — the correct key still works afterwards.
    window.dispatchEvent(new KeyboardEvent("keydown", { code: keys[correctFace] }));
    expect(onFinish).not.toHaveBeenCalled(); // only 1 of 2 prompts done

    vi.useRealTimers();
  });

  it("spends a life on a missed window instead of ending the segment", async () => {
    // The 800ms window on the final run made a single blink fatal after
    // eight correct hits. Wrong presses were always free; only the clock
    // could kill, and now it costs a life first.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onFinish = vi.fn();
    render(<TrophyRun seed="s" params={{ prompts: 4, window_ms: 500, lives: 3 }} onFinish={onFinish} />);
    await screen.findByLabelText(/prompt/i);

    for (let i = 0; i < 2; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(700);
      });
      expect(onFinish).not.toHaveBeenCalled();
    }

    // The third expiry is the last life.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: false }));
    vi.useRealTimers();
  });
});
