import { describe, expect, it } from "vitest";
import { shouldSubmitRating } from "./feedback";

describe("shouldSubmitRating", () => {
  it("does not submit the same rating twice", () => {
    expect(shouldSubmitRating(1, 1)).toBe(false);
  });

  it("allows the visitor to replace a previous rating", () => {
    expect(shouldSubmitRating(1, -1)).toBe(true);
  });
});
