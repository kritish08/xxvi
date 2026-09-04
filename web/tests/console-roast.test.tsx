// Smaller finding (task-30 review): Question.roast (content/schema.py) was
// authored, validated at content-load time, and never actually shown
// anywhere -- eight roasts written for nothing. This proves it now
// surfaces on a wrong answer, and that the run holds on screen (does not
// refresh/move to the next game) until he dismisses it -- the "pauses to
// read even one roast" beat run_service.py's SPEEDRUN_SECONDS comment
// already assumed existed.
//
// Same mounting pattern as console-operator-toast.test.tsx: real Console,
// mocked run-client/content/ws.

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";

const { getRunMock, submitAnswerMock } = vi.hoisted(() => ({
  getRunMock: vi.fn(),
  submitAnswerMock: vi.fn(),
}));
vi.mock("../src/lib/run-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/lib/run-client")>();
  return {
    ...actual,
    runApi: {
      ...actual.runApi,
      getRun: getRunMock,
      submitAnswer: submitAnswerMock,
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

import { Console } from "../src/Console";
import { BOOT_HOLD_MS } from "../src/shell/Boot";

const questionPhaseView = {
  phase: "question",
  segment: 1,
  difficulty: "kiddie",
  cleared_segments: [],
  released_rewards: [],
  lives: null,
  trophies: [],
  question: { prompt: "what did I say?", blank: "____ __" },
};

describe("Console — a wrong answer surfaces its roast", () => {
  beforeEach(() => {
    getContentMock.mockReset().mockResolvedValue({ copy: { closing: "" }, trophies: [] });
    getRunMock.mockReset().mockResolvedValue(questionPhaseView);
    submitAnswerMock.mockReset();
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
      // Clear Boot.tsx's hold before it calls onDone(). Imported, never
      // restated: this value has already moved once.
      await vi.advanceTimersByTimeAsync(BOOT_HOLD_MS + 100);
    });
  }

  it("shows the roast and holds the screen until dismissed, then refreshes", async () => {
    submitAnswerMock.mockResolvedValue({
      ...questionPhaseView,
      phase: "game",
      segment: 1,
      passed: false,
      roast: "you absolutely did not say that",
    });

    await bootConsole();
    await waitFor(() => expect(getRunMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      await userEvent.setup({ delay: null }).type(screen.getByLabelText("answer"), "wrong");
    });
    await act(async () => {
      await userEvent.setup({ delay: null }).click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("you absolutely did not say that")).toBeInTheDocument();
    // Held here: the segment restart already happened server-side, but the
    // client must not have refreshed past the roast yet.
    expect(getRunMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await userEvent.setup({ delay: null }).click(screen.getByRole("button", { name: "try again" }));
    });

    await waitFor(() => expect(getRunMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("you absolutely did not say that")).toBeNull();
  });

  it("does not show a roast overlay on a correct answer", async () => {
    submitAnswerMock.mockResolvedValue({
      ...questionPhaseView,
      phase: "game",
      segment: 2,
      passed: true,
      roast: null,
    });

    await bootConsole();
    await waitFor(() => expect(getRunMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      await userEvent.setup({ delay: null }).type(screen.getByLabelText("answer"), "correct");
    });
    await act(async () => {
      await userEvent.setup({ delay: null }).click(screen.getByRole("button", { name: "submit" }));
    });

    await waitFor(() => expect(getRunMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "try again" })).toBeNull();
  });
});
