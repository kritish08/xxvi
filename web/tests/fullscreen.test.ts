import { describe, expect, it, vi } from "vitest";
import { requestFullscreen } from "../src/lib/fullscreen";

describe("requestFullscreen", () => {
  it("returns true when the browser grants it", async () => {
    const element = { requestFullscreen: vi.fn().mockResolvedValue(undefined) };
    expect(await requestFullscreen(element as unknown as HTMLElement)).toBe(true);
  });

  it("returns false instead of throwing when the browser refuses", async () => {
    const element = { requestFullscreen: vi.fn().mockRejectedValue(new Error("denied")) };
    expect(await requestFullscreen(element as unknown as HTMLElement)).toBe(false);
  });

  it("returns false when the API is missing entirely", async () => {
    expect(await requestFullscreen({} as HTMLElement)).toBe(false);
  });
});
