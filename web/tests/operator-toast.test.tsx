// shell/OperatorToast.tsx — the operator's live, mid-run message. Same
// "must read as complete with the sound muted" rule TrophyToast follows
// (trophy.test.tsx), plus the requirement this component exists to satisfy:
// clearly a different KIND of notification than a trophy pop, not a copy
// of it wearing a different colour.

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { OperatorToast } from "../src/shell/OperatorToast";

afterEach(cleanup);

const msg = { type: "toast" as const, text: "nice one, keep going", id: 1 };

describe("OperatorToast", () => {
  it("renders the message text as real DOM text, not only implied by sound", () => {
    render(<OperatorToast queue={[msg]} onDismiss={vi.fn()} />);
    expect(screen.getByText("nice one, keep going")).toBeInTheDocument();
  });

  it("renders nothing when the queue is empty", () => {
    const { container } = render(<OperatorToast queue={[]} onDismiss={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows one message at a time when several arrive together", () => {
    render(
      <OperatorToast
        queue={[msg, { type: "toast", text: "second one", id: 2 }]}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("nice one, keep going")).toBeInTheDocument();
    expect(screen.queryByText("second one")).toBeNull();
  });

  it("dismisses after the hold and advances to the next queued message", () => {
    vi.useFakeTimers();
    try {
      const onDismiss = vi.fn();
      render(<OperatorToast queue={[msg]} onDismiss={onDismiss} holdMs={100} />);
      expect(onDismiss).not.toHaveBeenCalled();
      vi.advanceTimersByTime(100);
      expect(onDismiss).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("fires onChime once per message, synchronously with the entrance", () => {
    const onChime = vi.fn();
    const { rerender } = render(<OperatorToast queue={[msg]} onDismiss={vi.fn()} onChime={onChime} />);
    expect(onChime).toHaveBeenCalledTimes(1);
    rerender(
      <OperatorToast
        queue={[msg, { type: "toast", text: "next", id: 2 }]}
        onDismiss={vi.fn()}
        onChime={onChime}
      />,
    );
    // Still showing `msg` (head of queue unchanged) — no second chime.
    expect(onChime).toHaveBeenCalledTimes(1);
  });

  // The core requirement this component exists to satisfy: never
  // confusable with a trophy pop, in markup as well as on screen.
  it("is visually and semantically distinct from a trophy pop", () => {
    render(<OperatorToast queue={[msg]} onDismiss={vi.fn()} />);
    const node = screen.getByRole("status");
    expect(node).toHaveClass("toast--operator");
    // Never a grade word — that vocabulary belongs to trophies only.
    for (const grade of ["bronze", "silver", "gold", "platinum"]) {
      expect(node.className).not.toContain(grade);
    }
    expect(screen.getByText("operator")).toBeInTheDocument();
    expect(screen.queryByText(/trophy/i)).toBeNull();
  });

  it("wraps a long message rather than truncating it (unlike a trophy's fixed-length name)", () => {
    const long = {
      type: "toast" as const,
      text: "this is a much longer message than any trophy name would ever be, on purpose",
      id: 1,
    };
    render(<OperatorToast queue={[long]} onDismiss={vi.fn()} />);
    const node = screen.getByText(long.text);
    expect(node).toHaveClass("toast__name--operator");
  });
});
