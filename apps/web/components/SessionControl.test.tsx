/**
 * Beginning and ending a sitting.
 *
 * The decision worth protecting is that opening the dashboard does not start
 * one. The endpoint is idempotent, so calling it on load would work — and
 * then `openMinutes` would count a browser tab left open on a page nobody was
 * reading, which is precisely the fiction the field is named to avoid.
 *
 * The other is that a sitting is optional. Every attempt is recorded and every
 * skill updated whether or not one is open, so a failure here must not stop a
 * learner reaching their plan.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { routerMock } from "@/test/setup";

import { SessionControl } from "./SessionControl";

const mocks = vi.hoisted(() => ({
  fetchCurrentSession: vi.fn(),
  startSession: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return { useRouter: () => setup.routerMock };
});

beforeEach(() => {
  mocks.fetchCurrentSession.mockReset();
  mocks.startSession.mockReset();
  mocks.fetchCurrentSession.mockResolvedValue({
    sessionId: null,
    startedAt: null,
    planId: null,
  });
  mocks.startSession.mockResolvedValue({
    sessionId: "sit-1",
    startedAt: "2026-07-28T09:00:00Z",
    planId: null,
    resumed: false,
  });
});

it("reads the current sitting rather than starting one", async () => {
  // The load-bearing one. Starting on load would begin a sitting for anyone
  // who merely opened the app.
  render(<SessionControl token="t" />);

  await screen.findByRole("button", { name: /start a session/i });
  expect(mocks.fetchCurrentSession).toHaveBeenCalled();
  expect(mocks.startSession).not.toHaveBeenCalled();
});

it("starts one when the learner asks", async () => {
  render(<SessionControl token="t" />);

  await userEvent.click(
    await screen.findByRole("button", { name: /start a session/i }),
  );

  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /finish for today/i }),
    ).toBeInTheDocument(),
  );
});

it("offers to finish when one is already open", async () => {
  mocks.fetchCurrentSession.mockResolvedValue({
    sessionId: "sit-9",
    startedAt: "2026-07-28T09:00:00Z",
    planId: null,
  });

  render(<SessionControl token="t" />);

  await userEvent.click(
    await screen.findByRole("button", { name: /finish for today/i }),
  );

  expect(routerMock.push).toHaveBeenCalledWith("/finish/sit-9");
});

it("stays out of the way when the lookup fails", async () => {
  // A sitting is a nicety. Failing to read one must not stop the learner
  // reaching their plan.
  mocks.fetchCurrentSession.mockRejectedValue(new Error("offline"));

  render(<SessionControl token="t" />);

  expect(
    await screen.findByRole("button", { name: /start a session/i }),
  ).toBeInTheDocument();
});
