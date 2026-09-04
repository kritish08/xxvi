import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Login } from "../src/Login";

const { loginMock } = vi.hoisted(() => ({ loginMock: vi.fn() }));

vi.mock("../src/lib/client", () => ({
  api: { login: loginMock },
}));

describe("Login", () => {
  it("calls onSuccess after a valid submission", async () => {
    loginMock.mockResolvedValueOnce({ role: "player" });
    const onSuccess = vi.fn();
    render(<Login onSuccess={onSuccess} />);

    fireEvent.change(screen.getByLabelText("user"), { target: { value: "him" } });
    fireEvent.click(screen.getByRole("button", { name: "sign in" }));

    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });

  it("shows a generic error that reveals nothing about why it failed", async () => {
    loginMock.mockRejectedValueOnce(new Error("401"));
    render(<Login onSuccess={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("login failed.");
    expect(alert.textContent?.toLowerCase()).not.toContain("password");
    expect(alert.textContent?.toLowerCase()).not.toContain("username");
    expect(alert.textContent?.toLowerCase()).not.toContain("account");
  });

  it("lets him retry after a rejection -- the front door never locks", async () => {
    loginMock.mockRejectedValueOnce(new Error("401"));
    render(<Login onSuccess={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "sign in" }));
    await screen.findByRole("alert");

    expect(screen.getByRole("button", { name: "sign in" })).not.toBeDisabled();
  });
});
