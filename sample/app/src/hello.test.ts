import { describe, it, expect } from "vitest";
import { hello } from "./hello";

describe("hello", () => {
  it("TEST-1-1-1.1 [[HELLO-1]] hello は Hello Claude! を返す", () => {
    expect(hello()).toBe("Hello Claude!");
  });
});
