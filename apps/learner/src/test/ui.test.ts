import { ApiError, Unreachable } from "../api/client";
import { plain } from "../ui";

describe("an error in plain words", () => {
  it("says what a field needs, as a sentence", () => {
    expect(plain(new ApiError(422, { errors: [{ field: "signed_name", message: "type your name as it is on your record: Kim Lee" }] })))
      .toBe("Type your name as it is on your record: Kim Lee.");
  });

  it("gives the API's reason one full stop", () => {
    expect(plain(new ApiError(409, { detail: "this policy is no longer in use." }))).toBe("This policy is no longer in use.");
    expect(plain(new ApiError(409, { detail: "WHS policy has no version to sign yet" }))).toBe("WHS policy has no version to sign yet.");
  });

  it("never shows a bare status", () => {
    expect(plain(new ApiError(403, {}))).toBe("That didn't work. Try again, or ask your manager.");
    expect(plain(new ApiError(404, null))).toBe("That didn't work. Try again, or ask your manager.");
    expect(plain(new ApiError(502, { detail: "bad gateway" }))).toBe("Simple LMS isn't answering right now. Try again in a moment.");
  });

  it("puts anything else thrown in plain words too", () => {
    expect(plain(new Unreachable())).toBe("No signal: Simple LMS can't be reached right now.");
    expect(plain(new Error("That picture couldn't be made. Try again."))).toBe("That picture couldn't be made. Try again.");
    expect(plain("boom")).toBe("Something went wrong. Try again.");
    expect(plain(undefined)).toBe("Something went wrong. Try again.");
    expect(plain(new Error(""))).toBe("Something went wrong. Try again.");
  });
});
