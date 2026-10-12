import { ApiClient, ApiError, Unreachable } from "../api/client";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("ApiClient", () => {
  let calls: { url: string; init: RequestInit }[];
  let answers: (Response | Error)[];
  let client: ApiClient;

  beforeEach(() => {
    calls = [];
    answers = [];
    client = new ApiClient(async (url, init) => {
      calls.push({ url, init });
      const a = answers.shift() ?? json(500, { detail: "no answer queued" });
      if (a instanceof Error) throw a;
      return a;
    });
  });

  it("sends the token and leaves out empty filters", async () => {
    client.token = "lms_s.abc";
    answers.push(json(200, { people: [] }));
    await client.get("/v1/matrix", { role: "picker", status: "" });
    expect(calls[0].url).toBe("/v1/matrix?role=picker");
    expect(new Headers(calls[0].init.headers).get("Authorization")).toBe("Bearer lms_s.abc");
  });

  it("forgets the token and says so when the API stops taking it", async () => {
    const signedOut = vi.fn();
    client.onSignedOut = signedOut;
    client.token = "lms_s.old";
    answers.push(json(401, { detail: "session expired or invalid" }));
    await expect(client.get("/v1/auth/me")).rejects.toBeInstanceOf(ApiError);
    expect(client.token).toBeNull();
    expect(signedOut).toHaveBeenCalled();
  });

  it("gives the API's field errors and code", async () => {
    answers.push(json(422, { errors: [{ field: "granted_on", message: "can't be in the future" }] }));
    const e = (await client.post("/v1/people/LL042/records", {}).catch((x) => x)) as ApiError;
    expect(e.message).toBe("granted_on: can't be in the future");
    answers.push(json(403, { detail: "nobody records their own competency", code: "own_record" }));
    expect(((await client.post("/v1/people/MG001/records", {}).catch((x) => x)) as ApiError).code).toBe("own_record");
  });

  it("says Simple LMS can't be reached when there is no proper answer", async () => {
    answers.push(new TypeError("Failed to fetch"));
    await expect(client.get("/v1/matrix")).rejects.toBeInstanceOf(Unreachable);
    answers.push(new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(client.get("/v1/matrix")).rejects.toThrow("Can't reach Simple LMS right now.");
  });
});
