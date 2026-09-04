import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Roast } from "../src/shell/Roast";

describe("Roast", () => {
  it("renders the roast text and calls onContinue when dismissed", async () => {
    const onContinue = vi.fn();
    render(<Roast roast="you really thought that was it" onContinue={onContinue} />);
    expect(screen.getByText("you really thought that was it")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "try again" }));
    expect(onContinue).toHaveBeenCalledTimes(1);
  });
});
