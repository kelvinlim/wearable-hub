import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { formatApiError } from "./apiError.js";

describe("formatApiError", () => {
  it("passes through FastAPI string details", () => {
    assert.equal(formatApiError("end must be >= start"), "end must be >= start");
    assert.equal(formatApiError("  Subject not found  "), "Subject not found");
  });

  it("joins message, guidance, and error_id from a pull failure", () => {
    assert.equal(
      formatApiError({
        message: "Pull failed on 2026-10-24: The wearable provider did not respond in time.",
        reason: "provider_timeout",
        guidance: "Retry this date. If it keeps timing out, try a smaller range.",
        error_id: "a1b2c3d4",
        failed_date: "2026-10-24",
        completed_dates: [],
        stack: "Traceback (most recent call last): should never render",
        token: "ya29.secret",
      }),
      "Pull failed on 2026-10-24: The wearable provider did not respond in time. "
        + "Retry this date. If it keeps timing out, try a smaller range. Ref a1b2c3d4",
    );
  });

  it("does not duplicate guidance already in the message", () => {
    assert.equal(
      formatApiError({
        message: "Failed. Retry this date.",
        guidance: "Retry this date.",
        error_id: "abcd",
      }),
      "Failed. Retry this date. Ref abcd",
    );
  });

  it("uses the first FastAPI validation msg", () => {
    assert.equal(
      formatApiError([{ loc: ["query", "start"], msg: "Field required", type: "missing" }]),
      "Field required",
    );
  });

  it("falls back when detail is empty or unknown", () => {
    assert.equal(formatApiError(null, "Internal Server Error"), "Internal Server Error");
    assert.equal(formatApiError({}, "Internal Server Error"), "Internal Server Error");
    assert.equal(formatApiError(undefined, "Internal Server Error"), "Internal Server Error");
  });
});
