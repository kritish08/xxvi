// Ship-blocking finding (task-30 review, finding #5): CodeReveal used to
// tell him "it's also in your email" -- there is no email path anywhere in
// this system, so that was simply false. This proves the false claim is
// gone and the note no longer references email at all.

import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CodeReveal } from "../src/shell/CodeReveal";

const release = { reward_id: 1, label: "Act One Reward", code: "GIFT-CODE-0001" };

describe("CodeReveal", () => {
  it("shows the code but never claims it's also in his email", () => {
    render(<CodeReveal release={release} onContinue={vi.fn()} />);
    expect(screen.getByLabelText("redemption code")).toHaveTextContent("GIFT-CODE-0001");
    expect(screen.queryByText(/email/i)).toBeNull();
  });
});
