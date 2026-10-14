import { LearnerApi } from "../api/client";

const answer = (status: number, body: unknown) => async () =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("The learner app's client", () => {
  it.each(["/v1/auth/pin-login", "/v1/auth/login"])("does not sign out on a wrong guess at %s", async (path) => {
    const client = new LearnerApi(answer(401, { detail: "wrong", code: "wrong_pin" }));
    client.token = "lms_s.stale";
    const signedOut = vi.fn();
    client.onSignedOut = signedOut;
    await expect(client.post(path, {})).rejects.toMatchObject({ status: 401, code: "wrong_pin" });
    expect(signedOut).not.toHaveBeenCalled();
  });

  it("signs out when the API no longer takes the token", async () => {
    const client = new LearnerApi(answer(401, { detail: "not signed in" }));
    client.token = "lms_s.stale";
    const signedOut = vi.fn();
    client.onSignedOut = signedOut;
    await expect(client.get("/v1/people/LL042/training")).rejects.toMatchObject({ status: 401 });
    expect(signedOut).toHaveBeenCalledOnce();
  });

  it("sends a file as it is, with its own type", async () => {
    const seen: RequestInit[] = [];
    const client = new LearnerApi(async (_url, init) => {
      seen.push(init);
      return new Response(JSON.stringify({ id: "u-1" }), { status: 201 });
    });
    client.token = "lms_s.kim";
    const photo = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" });
    expect(await client.upload("ticket", photo)).toEqual({ id: "u-1" });
    expect(seen[0].body).toBe(photo);
    expect((seen[0].headers as Record<string, string>)["Content-Type"]).toBe("image/jpeg");
  });
});
