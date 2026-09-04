// Task 29: `POST /api/operator/toast` reaches the player's WS channel
// (verified against a real uvicorn access log) but nothing in Console.tsx
// handled `type: "toast"` -- the button worked on the wire and rendered
// nothing. This test proves the fix end to end, the way the bug was
// actually found: mount the real Console, drive its real WS `connect`
// call the way lib/ws.ts really invokes it, and assert an operator
// message that arrives over the socket actually reaches the screen.
//
// Deliberately NOT just an OperatorToast.tsx unit test (see
// operator-toast.test.tsx for that) -- a unit test on the component in
// isolation would have passed the whole time this bug existed, because
// the break was in Console.tsx never mounting/feeding it, not in the
// component itself.

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";

const { getRunMock } = vi.hoisted(() => ({ getRunMock: vi.fn() }));
vi.mock("../src/lib/run-client", () => ({
  // getProfile: the send-off screen asks for the recipient's name once the
  // run completes. Never reached in this file, but the module mock has to
  // carry it or Console throws on any render.
  runApi: { getRun: getRunMock, getProfile: vi.fn().mockResolvedValue({ recipient: "Aman" }) },
}));

const { getContentMock } = vi.hoisted(() => ({ getContentMock: vi.fn() }));
vi.mock("../src/lib/client", () => ({
  api: { getContent: getContentMock },
}));

type Handlers = Record<string, (msg: unknown) => void>;
const { connectMock, capturedHandlers } = vi.hoisted(() => ({
  connectMock: vi.fn(),
  capturedHandlers: { current: null as Handlers | null },
}));
vi.mock("../src/lib/ws", () => ({
  connect: connectMock,
}));

import { Console } from "../src/Console";
import { BOOT_HOLD_MS } from "../src/shell/Boot";

const runView = {
  phase: "complete",
  segment: 8,
  difficulty: "kiddie",
  cleared_segments: [1, 2, 3, 4, 5, 6, 7, 8],
  released_rewards: [],
  lives: null,
  trophies: [],
  question: null,
};

describe("Console — operator toast", () => {
  beforeEach(() => {
    getRunMock.mockReset().mockResolvedValue(runView);
    getContentMock.mockReset().mockResolvedValue({ copy: { closing: "" }, trophies: [] });
    connectMock.mockReset().mockImplementation((_path: string, handlers: Handlers) => {
      capturedHandlers.current = handlers;
      return { close: vi.fn() };
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    capturedHandlers.current = null;
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

  it("renders a live message from the operator when a `toast` WS message arrives", async () => {
    await bootConsole();

    await waitFor(() => expect(capturedHandlers.current).not.toBeNull());
    expect(capturedHandlers.current?.toast).toBeTypeOf("function");

    act(() => {
      capturedHandlers.current!.toast({ type: "toast", text: "you're doing great, keep going" });
    });

    const message = await screen.findByText("you're doing great, keep going");
    // Distinguishable from a trophy pop: its own class, its own label —
    // never the grade vocabulary a trophy pop uses.
    expect(message.closest(".toast")).toHaveClass("toast--operator");
    expect(screen.getByText("operator")).toBeInTheDocument();
  });

  it("queues a second message behind the first rather than dropping it", async () => {
    await bootConsole();
    await waitFor(() => expect(capturedHandlers.current).not.toBeNull());

    act(() => {
      capturedHandlers.current!.toast({ type: "toast", text: "first message" });
    });
    expect(await screen.findByText("first message")).toBeInTheDocument();

    act(() => {
      capturedHandlers.current!.toast({ type: "toast", text: "second message" });
    });
    // Still showing the first — the second is queued, not replacing it.
    expect(screen.getByText("first message")).toBeInTheDocument();
    expect(screen.queryByText("second message")).toBeNull();
  });
});
