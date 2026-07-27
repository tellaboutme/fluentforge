import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, camelise, fetchProfile, request } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(
  response: Partial<Response> & { json?: () => Promise<unknown> },
) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
      ...response,
    }),
  );
}

describe("camelise", () => {
  it("converts snake_case keys recursively", () => {
    expect(
      camelise({
        user_id: 1,
        domain_summaries: [{ tracked_skills: 2, mean_confidence: 0.5 }],
      }),
    ).toEqual({
      userId: 1,
      domainSummaries: [{ trackedSkills: 2, meanConfidence: 0.5 }],
    });
  });

  it("preserves nulls, which carry meaning for cefr_estimate", () => {
    expect(camelise({ cefr_estimate: null })).toEqual({ cefrEstimate: null });
  });

  it("leaves primitives and arrays of primitives alone", () => {
    expect(camelise(["a", 1, true])).toEqual(["a", 1, true]);
  });
});

describe("request", () => {
  it("camelises a successful response", async () => {
    stubFetch({ json: async () => ({ access_token: "t", expires_in: 60 }) });
    await expect(request("/x")).resolves.toEqual({
      accessToken: "t",
      expiresIn: 60,
    });
  });

  it("throws ApiError carrying the stable machine code", async () => {
    stubFetch({
      ok: false,
      status: 401,
      json: async () => ({
        code: "invalid_credentials",
        message: "Email or password is incorrect.",
        details: {},
        request_id: "abc",
      }),
    });

    await expect(request("/x")).rejects.toMatchObject({
      code: "invalid_credentials",
      status: 401,
      requestId: "abc",
    });
  });

  it("reports an unreachable server distinctly from a protocol error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    await expect(request("/x")).rejects.toMatchObject({
      code: "network_unavailable",
      status: 0,
    });
  });

  it("survives an error body that is not JSON", async () => {
    stubFetch({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    });
    await expect(request("/x")).rejects.toBeInstanceOf(ApiError);
  });

  it("sends the bearer token when given one", async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", spy);

    await fetchProfile("token-123");

    const [, init] = spy.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer token-123",
    );
  });

  it("omits the Authorization header when signed out", async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", spy);

    await request("/x");

    const [, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(
      (init.headers as Record<string, string>).Authorization,
    ).toBeUndefined();
  });
});

describe("ApiError", () => {
  it("marks server faults and missing curriculum as retryable", () => {
    expect(new ApiError(503, "curriculum_not_loaded", "x").isTransient).toBe(
      true,
    );
    expect(new ApiError(500, "internal_error", "x").isTransient).toBe(true);
  });

  it("does not invite a retry on bad credentials", () => {
    expect(new ApiError(401, "invalid_credentials", "x").isTransient).toBe(
      false,
    );
  });
});
