// GameHost owns two safety properties that don't show up anywhere else in
// this app yet: a single-use token must survive a double-fire, and a 409
// must resync rather than retry (see server/xxvi/games/tokens.py and
// run_routes.py's per-route phase guards). A fake mechanic, mocked into
// the registry, keeps these tests fast and decoupled from any real
// mechanic's own timing.

import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GameHost } from "../src/games/GameHost";
import type { GameProps } from "../src/games/types";

const submitGame = vi.fn();

vi.mock("../src/lib/run-client", async (importOriginal) => {
  // Keep the real ApiError class — GameHost branches on it for the 409
  // case, so a mock that dropped it would break that path.
  const actual = await importOriginal<typeof import("../src/lib/run-client")>();
  return {
    ...actual,
    runApi: {
      ...actual.runApi,
      submitGame: (...args: unknown[]) => submitGame(...args),
    },
  };
});

function FakeGame({ onFinish }: GameProps) {
  return (
    <button
      type="button"
      onClick={() => onFinish({ passed: true, durationMs: 10, inputCount: 1, score: 1, sequence: [0] })}
    >
      finish
    </button>
  );
}

vi.mock("../src/games/registry", () => ({ GAMES: { fake: FakeGame } }));

const brief = { segment: 1, token: "tok", seed: "seed", mechanic: "fake", params: {} };

afterEach(() => {
  vi.clearAllMocks();
  document.body.style.cursor = "";
});

describe("GameHost", () => {
  it("submits exactly once even if the deciding action fires twice", async () => {
    submitGame.mockResolvedValue({});
    const onDone = vi.fn();
    render(<GameHost brief={brief} onDone={onDone} total={8} lives={null} trophies={0} difficulty={null} />);
    const button = screen.getByRole("button", { name: "finish" });
    await userEvent.click(button);
    await userEvent.click(button);
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(submitGame).toHaveBeenCalledTimes(1);
  });

  it("sends passed_client_side as advisory alongside the raw outcome", async () => {
    submitGame.mockResolvedValue({});
    render(<GameHost brief={brief} onDone={vi.fn()} total={8} lives={null} trophies={0} difficulty={null} />);
    await userEvent.click(screen.getByRole("button", { name: "finish" }));
    await waitFor(() => expect(submitGame).toHaveBeenCalledTimes(1));
    expect(submitGame).toHaveBeenCalledWith(
      "tok",
      expect.objectContaining({
        mechanic: "fake",
        passed_client_side: true,
        duration_ms: 10,
        input_count: 1,
        score: 1,
        sequence: [0],
      }),
    );
  });

  it("resyncs instead of retrying on a 409, and still hands off", async () => {
    const { ApiError } = await import("../src/lib/run-client");
    submitGame.mockRejectedValue(new ApiError(409, "/api/run/segment/game"));
    const onDone = vi.fn();
    render(<GameHost brief={brief} onDone={onDone} total={8} lives={null} trophies={0} difficulty={null} />);
    await userEvent.click(screen.getByRole("button", { name: "finish" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(submitGame).toHaveBeenCalledTimes(1);
  });

  it("hides the cursor while mounted and restores it on unmount", () => {
    submitGame.mockResolvedValue({});
    const { unmount } = render(<GameHost brief={brief} onDone={vi.fn()} total={8} lives={null} trophies={0} difficulty={null} />);
    expect(document.body.style.cursor).toBe("none");
    unmount();
    expect(document.body.style.cursor).not.toBe("none");
  });

  it("shows an alert for an unregistered mechanic instead of crashing", () => {
    render(
      <GameHost
        brief={{ ...brief, mechanic: "unknown" }}
        onDone={vi.fn()}
        total={8}
        lives={null}
        trophies={0}
        difficulty={null}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("unknown mechanic: unknown");
  });
});
