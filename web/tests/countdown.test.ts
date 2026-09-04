import { describe, expect, it } from "vitest";
import { formatCountdown } from "../src/lib/countdown";

describe("formatCountdown", () => {
  it("renders days, hours, minutes and seconds", () => {
    expect(formatCountdown(2 * 86400 + 3 * 3600 + 4 * 60 + 5)).toBe("02:03:04:05");
  });
  it("pads single digits", () => {
    expect(formatCountdown(61)).toBe("00:00:01:01");
  });
  it("floors at zero and never goes negative", () => {
    expect(formatCountdown(0)).toBe("00:00:00:00");
    expect(formatCountdown(-500)).toBe("00:00:00:00");
  });
});
