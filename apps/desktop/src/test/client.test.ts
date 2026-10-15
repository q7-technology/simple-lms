import { ApiClient, ApiError, Cancelled, Unreachable } from "../api/client";
import { FakeXhr } from "./harness";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("ApiClient", () => {
  let calls: { url: string; init: RequestInit }[];
  let answers: (Response | Error)[];
  let sent: FakeXhr[];
  let client: ApiClient;

  beforeEach(() => {
    calls = [];
    answers = [];
    sent = [];
    client = new ApiClient(async (url, init) => {
      calls.push({ url, init });
      const a = answers.shift() ?? json(500, { detail: "no answer queued" });
      if (a instanceof Error) throw a;
      return a;
    }, () => {
      const x = new FakeXhr();
      sent.push(x);
      return x as unknown as XMLHttpRequest;
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

  it("says a file is too big when the proxy refuses it, not that Simple LMS can't be reached", async () => {
    const sending = client.upload("page-video", new Blob([new Uint8Array([0])]));
    sent[0].answer(413, "Request Entity Too Large");
    const e = (await sending.catch((x) => x)) as ApiError;
    expect(e).toBeInstanceOf(ApiError);
    expect(e.status).toBe(413);
    expect(e.message).toBe("That file is too big: the most is 200 MB for a video, 20 MB otherwise.");
  });

  it("sends a module's file as it is, with its own type and the token", async () => {
    client.token = "lms_s.abc";
    const video = new Blob([new Uint8Array([0, 0, 0])], { type: "video/mp4" });
    const sending = client.upload("page-video", video);
    expect(sent[0].method).toBe("POST");
    expect(sent[0].url).toBe("/v1/uploads?purpose=page-video");
    expect(sent[0].body).toBe(video);
    expect(sent[0].headers["Content-Type"]).toBe("video/mp4");
    expect(sent[0].headers.Authorization).toBe("Bearer lms_s.abc");
    sent[0].answer(201, JSON.stringify({ id: "u-1", purpose: "page-video", content_type: "video/mp4", size_bytes: 3 }));
    expect((await sending).id).toBe("u-1");
  });

  it("says how far a file has got, and stops sending it when asked", async () => {
    const seen: number[] = [];
    const sending = client.upload("page-video", new Blob([new Uint8Array([0])]), (done) => seen.push(done));
    sent[0].progress(42, 100);
    sent[0].progress(100, 100);
    expect(seen).toEqual([0.42, 1]);
    sending.abort();
    expect(sent[0].aborted).toBe(true);
    await expect(sending).rejects.toBeInstanceOf(Cancelled);
  });

  it("gives the API's errors for a file, and says when it can't be reached", async () => {
    const refused = client.upload("page-pdf", new Blob([new Uint8Array([0])]));
    sent[0].answer(422, JSON.stringify({ errors: [{ field: "file", message: "isn't a PDF" }] }));
    await expect(refused).rejects.toThrow("file: isn't a PDF");
    const lost = client.upload("page-pdf", new Blob([new Uint8Array([0])]));
    sent[1].fail();
    await expect(lost).rejects.toBeInstanceOf(Unreachable);
  });

  it("fetches a kept file with the token", async () => {
    client.token = "lms_s.abc";
    answers.push(new Response(new Uint8Array([0xff, 0xd8, 0xff]), { status: 200, headers: { "Content-Type": "image/jpeg" } }));
    const b = await client.blob("/v1/uploads/abc");
    expect(b.type).toBe("image/jpeg");
    expect(new Headers(calls[0].init.headers).get("Authorization")).toBe("Bearer lms_s.abc");
    answers.push(json(404, { detail: "no file abc" }));
    await expect(client.blob("/v1/uploads/abc")).rejects.toThrow("no file abc");
  });
});
