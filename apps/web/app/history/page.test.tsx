/**
 * A learner's own past work.
 *
 * The property this screen exists to protect is not that history is listed —
 * it is that old feedback is presented as a *record* rather than as a current
 * verdict. The checks, the curriculum version and the evaluator can all have
 * moved since a piece of work was submitted, and this is the one place a
 * learner comes to check what they were actually told.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AttemptFeedback, HistoryPage } from "@/lib/api";
import { SessionProvider } from "@/lib/session";

import HistoryScreen from "./page";

const mocks = vi.hoisted(() => ({
  fetchHistory: vi.fn(),
  fetchAttemptFeedback: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return { useRouter: () => setup.routerMock };
});

const PAGE: HistoryPage = {
  items: [
    {
      attemptId: "a1",
      activityKey: "write:write.b1.email",
      activityType: "writing_task",
      submittedAt: "2026-07-20T10:00:00Z",
      summary: "Last weekend I visited my sister in another city.",
      score: 0.75,
      wasJudged: true,
    },
    {
      attemptId: "a2",
      activityKey: "reflect:daily",
      activityType: "reflection",
      submittedAt: "2026-07-19T10:00:00Z",
      summary: "Questions are still the hard part.",
      score: null,
      wasJudged: false,
    },
  ],
  nextBefore: null,
};

const JUDGED: AttemptFeedback = {
  attemptId: "a1",
  activityKey: "write:write.b1.email",
  activityType: "writing_task",
  submittedAt: "2026-07-20T10:00:00Z",
  evaluatorId: "deterministic/0.1.0",
  response: { text: "Last weekend I visited my sister.", score: 0.75 },
  wasJudged: true,
  isStale: true,
};

const UNJUDGED: AttemptFeedback = {
  ...JUDGED,
  attemptId: "a2",
  activityType: "reflection",
  evaluatorId: null,
  response: { note: "Questions are still the hard part.", scored: false },
  wasJudged: false,
  isStale: false,
};

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <HistoryScreen />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mocks.fetchHistory.mockReset();
  mocks.fetchAttemptFeedback.mockReset();
  mocks.fetchHistory.mockResolvedValue(PAGE);
  mocks.fetchAttemptFeedback.mockResolvedValue(JUDGED);
});

describe("the list", () => {
  it("shows the learner's own words rather than a score", async () => {
    // A list of percentages does not tell someone which piece of work they
    // are looking at.
    renderPage();
    expect(
      await screen.findByText(/visited my sister in another city/i),
    ).toBeInTheDocument();
  });

  it("says plainly when nothing judged an entry", async () => {
    renderPage();
    expect(await screen.findByText(/nothing judged this/i)).toBeInTheDocument();
  });

  it("shows no score for unjudged work", async () => {
    // A blank or zero score would invent a verdict nobody gave.
    renderPage();
    await screen.findByText(/visited my sister/i);
    expect(screen.queryByText(/0%/)).toBeNull();
  });

  it("says so when there is nothing yet, without sounding like a fault", async () => {
    mocks.fetchHistory.mockResolvedValue({ items: [], nextBefore: null });
    renderPage();
    expect(await screen.findByText(/nothing yet/i)).toBeInTheDocument();
  });
});

describe("opening one", () => {
  async function open(name: RegExp) {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name }));
    return user;
  }

  it("dates old feedback rather than presenting it as current", async () => {
    // The assertion this file exists for.
    await open(/visited my sister/i);

    expect(await screen.findByText(/as it was recorded/i)).toBeInTheDocument();
    expect(
      screen.getByText(/rather than as a verdict on your work today/i),
    ).toBeInTheDocument();
  });

  it("names the evaluator that produced it", async () => {
    // A learner comparing two pieces of feedback deserves to know whether
    // the same thing judged them.
    await open(/visited my sister/i);
    expect(
      await screen.findByText(/deterministic\/0\.1\.0/),
    ).toBeInTheDocument();
  });

  it("does not claim staleness for work nothing judged", async () => {
    mocks.fetchAttemptFeedback.mockResolvedValue(UNJUDGED);
    await open(/questions are still the hard part/i);

    expect(
      await screen.findByText(/nothing judged this, so there is no feedback/i),
    ).toBeInTheDocument();
  });

  it("shows what the learner actually wrote", async () => {
    await open(/visited my sister/i);
    const detail = await screen.findByRole("status");
    expect(detail.textContent).toContain("visited my sister");
  });
});
