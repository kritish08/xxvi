// Ship-blocking finding #1 (task-30 review): a failed game moves the run's
// phase `game -> game`. React sees the same element type (`SegmentGame`) in
// the same position on the next render and does NOT remount it, so:
//   - SegmentGame's `useEffect(..., [])` never re-fires -> no fresh
//     `startSegment()` call -> the player is replaying with the brief
//     that already produced a failure.
//   - GameHost's `submitted` ref (games/GameHost.tsx) also survives the
//     "remount" that never happened, so its second `finish()` call returns
//     early at the `if (submitted.current) return;` guard: nothing is
//     submitted and `onDone()` is never called. The screen hangs forever;
//     only a page reload escapes.
//
// Reproduced here the way the reviewer reproduced it: mount the real
// Console, drive it through two consecutive "game" phases exactly as the
// server would present them on a failure, and assert `startSegment` is
// called again and a *different* token is submitted on the retry.
//
// Same mocking pattern as console-operator-toast.test.tsx (real Console,
// mocked run-client/content/ws) plus gamehost.test.tsx's fake mechanic.

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import type { GameProps } from "../src/games/types";

const { getRunMock, startSegmentMock, submitGameMock } = vi.hoisted(() => ({
  getRunMock: vi.fn(),
  startSegmentMock: vi.fn(),
  submitGameMock: vi.fn(),
}));
vi.mock("../src/lib/run-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/lib/run-client")>();
  return {
    ...actual,
    runApi: {
      ...actual.runApi,
      getRun: getRunMock,
      startSegment: startSegmentMock,
      submitGame: submitGameMock,
    },
  };
});

const { getContentMock } = vi.hoisted(() => ({ getContentMock: vi.fn() }));
vi.mock("../src/lib/client", () => ({
  api: { getContent: getContentMock },
}));

vi.mock("../src/lib/ws", () => ({
  connect: vi.fn().mockImplementation(() => ({ close: vi.fn() })),
}));

function FakeGame({ onFinish }: GameProps) {
  return (
    <button type="button" onClick={() => onFinish({ passed: false, durationMs: 5, inputCount: 1, score: 0, sequence: [] })}>
      finish
    </button>
  );
}
vi.mock("../src/games/registry", () => ({ GAMES: { fake: FakeGame } }));

import { Console } from "../src/Console";

const gamePhaseView = {
  phase: "game",
  segment: 1,
  difficulty: "kiddie",
  cleared_segments: [],
  released_rewards: [],
  lives: null,
  trophies: [],
  question: null,
};

describe("Console — same-phase game retry after a failure", () => {
  beforeEach(() => {
    getContentMock.mockReset().mockResolvedValue({ copy: { closing: "" }, trophies: [] });
    startSegmentMock.mockReset();
    submitGameMock.mockReset().mockResolvedValue(gamePhaseView);
    getRunMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function bootConsole() {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<Console />);
    const power = await screen.findByRole("button", { name: /press to power on/i });
    await act(async () => {
      await userEvent.setup({ delay: null }).click(power);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2300);
    });
  }

  it("remounts SegmentGame and fetches a fresh brief when the server keeps the phase at 'game'", async () => {
    // First read: run is already in the "game" phase (as if arriving mid-run).
    getRunMock.mockResolvedValue(gamePhaseView);
    // A fresh brief per call, keyed off call order rather than a fixed
    // two-deep queue of `mockResolvedValueOnce` -- Console's other effects
    // (WS reconnects, the content re-fetch on trophy count, StrictMode-less
    // but still React-scheduled renders) are free to call `startSegment`
    // more than exactly twice in a real browser too; what actually matters
    // for this fix is that every "game" phase render gets ITS OWN fresh
    // token, never a stale one replayed from a prior attempt.
    startSegmentMock.mockImplementation(() => {
      const n = startSegmentMock.mock.calls.length;
      return Promise.resolve({ segment: 1, token: `token-${n}`, seed: `s${n}`, mechanic: "fake", params: {} });
    });

    await bootConsole();

    // First attempt loads.
    await waitFor(() => expect(startSegmentMock).toHaveBeenCalledTimes(1));
    const firstFinish = await screen.findByRole("button", { name: "finish" });
    await act(async () => {
      await userEvent.setup({ delay: null }).click(firstFinish);
    });

    // The failed attempt submitted token-1 exactly once.
    await waitFor(() => expect(submitGameMock).toHaveBeenCalledTimes(1));
    expect(submitGameMock.mock.calls[0][0]).toBe("token-1");

    // A failure now holds a beat on screen before the retry, rather than
    // restarting instantly and silently ("it respawns from the left and
    // nothing happens"). Dismissing it is what releases the retry.
    const continueButton = await screen.findByRole("button", { name: /try again/i });
    await act(async () => {
      await userEvent.setup({ delay: null }).click(continueButton);
    });

    // Server keeps phase at "game" (a Devil failure with lives left, or a
    // Kiddie in-place retry) -- refresh() resolves to the same phase.
    // The fix must still force a remount and a fresh startSegment() call.
    await waitFor(() => expect(startSegmentMock).toHaveBeenCalledTimes(2));

    // A fresh brief must be on screen -- a *second* "finish" button that
    // will submit token-2, not a leftover instance whose `submitted` ref
    // is already tripped.
    const secondFinish = await screen.findByRole("button", { name: "finish" });
    await act(async () => {
      await userEvent.setup({ delay: null }).click(secondFinish);
    });

    await waitFor(() => expect(submitGameMock).toHaveBeenCalledTimes(2));
    expect(submitGameMock.mock.calls[1][0]).toBe("token-2");
    expect(submitGameMock.mock.calls[1][0]).not.toBe(submitGameMock.mock.calls[0][0]);
  });

  it("does not hang on 'loading segment…' when the brief fetch 409s", async () => {
    // The reported hang: a completed sequence left the screen stuck with no
    // input accepted. `startSegment` had no .catch, so a 409 ("not at a
    // game" — the run had already moved on) rejected unhandled and `brief`
    // stayed null forever.
    // The run has already moved on to the question — which is exactly why
    // the brief fetch 409s. The first read still says "game" (the stale
    // view the component mounted from); the resync is what reveals it.
    const questionPhaseView = {
      ...gamePhaseView,
      phase: "question",
      question: { prompt: "which one?", blank: "____" },
    };
    getRunMock.mockResolvedValueOnce(gamePhaseView).mockResolvedValue(questionPhaseView);
    startSegmentMock.mockReset().mockRejectedValue(
      Object.assign(new Error("409 /api/run/segment/start"), { status: 409 }),
    );

    await bootConsole();

    await waitFor(() => expect(startSegmentMock).toHaveBeenCalled());
    // The 409 must trigger a resync, and the run's real phase then decides
    // what renders — rather than the placeholder staying up forever with no
    // input accepted.
    await waitFor(() => expect(screen.queryByText(/loading segment/i)).toBeNull());
    expect(await screen.findByText("which one?")).toBeDefined();
  });

  it("recovers from a Devil wipe, where the segment changes on a FAILURE", async () => {
    // Losing the last Devil life sends the run back to segment 1. Failure
    // used to be detected as "still at a game AND on the same segment", so a
    // wipe read as neither a pass nor a failure: SegmentGame never remounted
    // and the screen froze on the old segment — stale segment in the HUD
    // beside freshly restored lives — with refreshing the page the only way
    // out.
    getRunMock.mockResolvedValue(gamePhaseView);
    startSegmentMock.mockReset().mockImplementation(() =>
      Promise.resolve({
        segment: 6,
        token: `token-${startSegmentMock.mock.calls.length}`,
        seed: "s",
        mechanic: "fake",
        params: {},
      }),
    );
    // The server wipes: still a game, but back at segment 1.
    submitGameMock.mockReset().mockResolvedValue({ ...gamePhaseView, segment: 1 });

    await bootConsole();
    await waitFor(() => expect(startSegmentMock).toHaveBeenCalledTimes(1));
    await act(async () => {
      await userEvent.setup({ delay: null }).click(await screen.findByRole("button", { name: "finish" }));
    });

    // It must be recognised as a failure, and say the RIGHT thing.
    const again = await screen.findByRole("button", { name: /try again/i });
    expect(screen.getByText(/everything resets/i)).toBeDefined();

    // ...and dismissing it must fetch a brief for the new segment.
    await act(async () => {
      await userEvent.setup({ delay: null }).click(again);
    });
    await waitFor(() => expect(startSegmentMock).toHaveBeenCalledTimes(2));
  });

  it("does not refetch a brief when the parent re-renders mid-game", async () => {
    // A second brief mid-game swaps the token under the running game, and
    // GameHost then submits the NEWEST one — so a game played for twelve
    // seconds hands the server a token issued moments ago, which correctly
    // refuses it. Observed live as three /segment/start calls in one game,
    // the last eleven seconds into play, and on screen as "I finished it
    // and it said WRONG".
    getRunMock.mockResolvedValue(gamePhaseView);
    startSegmentMock.mockReset().mockImplementation(() =>
      Promise.resolve({
        segment: 1,
        token: `token-${startSegmentMock.mock.calls.length}`,
        seed: "s",
        mechanic: "fake",
        params: {},
      }),
    );

    await bootConsole();
    await waitFor(() => expect(startSegmentMock).toHaveBeenCalledTimes(1));

    // Force parent re-renders: every /api/run poll resolves a new object,
    // which is exactly what happens in the real app every 15 seconds.
    for (let i = 0; i < 4; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(16_000);
      });
    }

    expect(startSegmentMock).toHaveBeenCalledTimes(1);
  });
});
