/**
 * Offline behaviour.
 *
 * The whole point of Milestone 8 here is that offline support is *honest*.
 * A cache that answers silently, or a submission that disappears into a
 * queue, would make the product less trustworthy rather than more useful.
 *
 * So the tests are mostly about what the learner is told:
 *
 * - Offline is announced, and the announcement says what still works before
 *   it says what does not.
 * - A submission attempted offline fails immediately with its own code,
 *   rather than as a generic connection error, and the message says the
 *   work has not been sent.
 * - A read is still attempted, because the service worker may have a saved
 *   copy and it is the one that knows.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, request } from "@/lib/api";
import { ErrorNotice } from "@/components/Status";

import { OfflineNotice } from "./Offline";

/** Pretend the browser has, or has not, a network. */
function setOnline(online: boolean): void {
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    get: () => online,
  });
}

beforeEach(() => {
  setOnline(true);
  vi.restoreAllMocks();
});

afterEach(() => {
  setOnline(true);
});

describe("the offline banner", () => {
  it("stays out of the way while there is a network", () => {
    setOnline(true);
    const { container } = render(<OfflineNotice />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says what still works before it says what does not", () => {
    // "You are offline" on its own leaves someone guessing whether their
    // half-written essay is about to be lost.
    setOnline(false);
    render(<OfflineNotice />);

    expect(screen.getByText(/you are offline/i)).toBeInTheDocument();
    expect(screen.getByText(/still read today.s plan/i)).toBeInTheDocument();
  });

  it("says plainly that work will not be marked yet", () => {
    setOnline(false);
    render(<OfflineNotice />);
    // Matched against the whole banner: the sentence spans a line break, and
    // asserting on a text node would fail the next time it reflows.
    expect(screen.getByRole("status").textContent).toMatch(
      /nothing you write will be marked until you are back/i,
    );
  });

  it("promises the work is not lost", () => {
    setOnline(false);
    render(<OfflineNotice />);
    expect(screen.getByText(/stays on screen/i)).toBeInTheDocument();
  });

  it("announces itself politely rather than interrupting", () => {
    // `role="status"` is announced at the next pause. An alert would cut
    // across whatever the learner is being read at the time.
    setOnline(false);
    render(<OfflineNotice />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("submitting while offline", () => {
  it("fails immediately, without reaching the network", async () => {
    // Everything is scored on the server. Queuing the submission would
    // record evidence at a moment the learner was not present for, using a
    // timestamp the client chose.
    setOnline(false);
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await expect(
      request("/api/v1/anything", { method: "POST" }),
    ).rejects.toThrow(ApiError);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("uses its own code, not a generic connection failure", async () => {
    setOnline(false);
    const error = await request("/api/v1/anything", { method: "POST" }).catch(
      (cause: unknown) => cause,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("offline");
  });

  it("is treated as retryable, because it is the most retryable thing there is", async () => {
    setOnline(false);
    const error = (await request("/api/v1/anything", { method: "POST" }).catch(
      (cause: unknown) => cause,
    )) as ApiError;

    expect(error.isTransient).toBe(true);
  });

  it("tells the learner their work has not been sent", () => {
    // A learner who assumed it had been sent would stop waiting for an
    // answer they were never going to get.
    render(
      <ErrorNotice
        error={new ApiError(0, "offline", "You are offline.", {})}
        onRetry={() => {}}
      />,
    );

    expect(screen.getByText(/nothing has been sent yet/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });
});

describe("reading while offline", () => {
  it("is still attempted, because a saved copy may exist", async () => {
    // The service worker owns the cache and is the only thing that knows
    // whether it has this page. Refusing here would hide a copy the learner
    // could have used.
    setOnline(false);
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: true })));

    await request("/api/v1/plans/today");
    expect(fetchSpy).toHaveBeenCalled();
  });

  it("reports a genuine failure as unreachable, not as offline", async () => {
    // The two are different facts: "the browser has no network" and "this
    // request did not arrive". Only the second proves anything.
    setOnline(true);
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("boom"));

    const error = (await request("/api/v1/plans/today").catch(
      (cause: unknown) => cause,
    )) as ApiError;

    expect(error.code).toBe("network_unavailable");
  });
});
