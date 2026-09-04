import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Goodbye } from "../src/shell/Goodbye";

const shutdownAudio = vi.fn();
const exitFullscreen = vi.fn().mockResolvedValue(undefined);
vi.mock("../src/lib/audio", () => ({ shutdownAudio: (...a: unknown[]) => shutdownAudio(...a) }));
vi.mock("../src/lib/fullscreen", () => ({ exitFullscreen: () => exitFullscreen() }));

afterEach(() => {
  vi.useRealTimers();
  shutdownAudio.mockClear();
  exitFullscreen.mockClear();
});

describe("Goodbye", () => {
  it("says his name", () => {
    render(<Goodbye recipient="Aman" onPoweredOff={vi.fn()} />);
    expect(screen.getByText(/happy birthday, aman\./i)).toBeDefined();
  });

  it("actually stops the audio and gives the screen back", async () => {
    // Power off is not navigation. Muting would leave every track running
    // behind a closed door; fullscreen was taken by the boot click and has
    // to be handed back.
    render(<Goodbye recipient="Aman" onPoweredOff={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /power off/i }));
    expect(shutdownAudio).toHaveBeenCalled();
    expect(exitFullscreen).toHaveBeenCalled();
  });

  it("tells the shell to drop the chrome immediately, not at the end", async () => {
    // A mute button floating over a console that is shutting down reads as
    // a web page, which is the one impression this whole screen avoids.
    const onPoweredOff = vi.fn();
    render(<Goodbye recipient="Aman" onPoweredOff={onPoweredOff} />);
    await userEvent.click(screen.getByRole("button", { name: /power off/i }));
    expect(onPoweredOff).toHaveBeenCalledTimes(1);
  });

  it("runs the shutdown sequence and ends dark", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<Goodbye recipient="Aman" onPoweredOff={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /power off/i }));

    expect(screen.getByText(/closing the session/i)).toBeDefined();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByText(/deleting XXVI/i)).toBeDefined();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200);
    });
    expect(screen.getByText(/until next time\./i)).toBeDefined();
    // Nothing offered once it is off — no way back in.
    expect(screen.queryByRole("button")).toBeNull();
  });
});
