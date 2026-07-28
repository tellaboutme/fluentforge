/**
 * The end-of-session screen.
 *
 * This is the screen most likely to lie. The end of a session is where every
 * learning product reaches for a number — points, a streak, a percentage
 * gained — and every one of those would be invented: derived from a handful
 * of attempts, presented as measured, impossible to argue with, and forbidden
 * by `docs/ADAPTIVE_ENGINE.md`.
 *
 * So most of what follows is about what is absent. There is a test that the
 * words "improved", "gained" and "streak" do not appear, which is a blunt
 * instrument and the right one: the failure mode here is not a bug, it is
 * somebody later deciding the screen looks bare.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionSummary } from "@/lib/api";
import { SessionProvider } from "@/lib/session";
import { paramsMock } from "@/test/setup";

import FinishPage from "./page";

const mocks = vi.hoisted(() => ({ completeSession: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return {
    useRouter: () => setup.routerMock,
    useParams: () => setup.paramsMock,
  };
});

const FULL: SessionSummary = {
  sessionId: "sit-1",
  status: "completed",
  startedAt: "2026-07-28T09:00:00Z",
  endedAt: "2026-07-28T09:34:00Z",
  openMinutes: 34,
  planId: "plan-1",
  activities: [
    {
      activityKey: "read:cafe.b1",
      activityType: "reading_task",
      submittedAt: "2026-07-28T09:10:00Z",
      score: 0.75,
      wasJudged: true,
      onPlan: true,
    },
    {
      activityKey: "reflect:daily",
      activityType: "reflection",
      submittedAt: "2026-07-28T09:30:00Z",
      score: null,
      wasJudged: false,
      onPlan: false,
    },
  ],
  skills: [
    {
      key: "reading.familiar_arguments",
      title: "Following an argument",
      evidenceRecorded: 2,
      distinctContexts: 1,
      status: "emerging",
      needs: "This has held up in one fewer situation than it needs.",
    },
  ],
  planItemsDone: 1,
  planItemsTotal: 3,
  notes: [
    "One sitting is not proof of anything on its own.",
    "You did 1 of the 3 things on today's plan.",
  ],
};

const EMPTY: SessionSummary = {
  ...FULL,
  activities: [],
  skills: [],
  planItemsDone: 0,
  planItemsTotal: 0,
  notes: [
    "One sitting is not proof of anything on its own.",
    "Nothing was finished in this sitting, so nothing was recorded.",
  ],
};

function renderPage() {
  paramsMock.sessionId = "sit-1";
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <FinishPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mocks.completeSession.mockReset();
  mocks.completeSession.mockResolvedValue(FULL);
});

describe("what it reports", () => {
  it("lists what was finished", async () => {
    renderPage();
    expect(await screen.findByText("read:cafe.b1")).toBeInTheDocument();
  });

  it("says nothing judged the reflection", async () => {
    // The one activity deliberately left unjudged. A summary that scored it
    // would undo the point of it.
    renderPage();
    expect(await screen.findByText(/nothing judged this/i)).toBeInTheDocument();
  });

  it("names the skills that got evidence and how broadly they now stand", async () => {
    renderPage();

    expect(
      await screen.findByText("Following an argument"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/2 pieces of evidence just now/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/1 different situation so far/i),
    ).toBeInTheDocument();
  });

  it("says what a skill still needs, in words rather than a percentage", async () => {
    // A number here would read as a score to beat.
    renderPage();

    expect(
      await screen.findByText(/one fewer situation than it needs/i),
    ).toBeInTheDocument();
  });
});

describe("what it refuses to say", () => {
  it("calls the minutes elapsed time and disclaims measuring work", async () => {
    // Someone who started a sitting and made lunch did not study for
    // thirty-four minutes.
    renderPage();

    expect(
      await screen.findByText(/elapsed time, not time spent working/i),
    ).toBeInTheDocument();
  });

  it("never claims the learner improved", async () => {
    // Blunt on purpose. The failure mode is not a bug — it is somebody
    // later deciding this screen looks bare.
    const { container } = renderPage();
    await screen.findByText("read:cafe.b1");

    expect(container.textContent).not.toMatch(
      /improv|gained|streak|level ?up|points|xp/i,
    );
  });

  it("shows the notes above everything else", async () => {
    renderPage();

    const note = await screen.findByText(/not proof of anything/i);
    const activity = screen.getByText("read:cafe.b1");

    expect(
      note.compareDocumentPosition(activity) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("does not treat an unfinished plan as a failure", async () => {
    renderPage();

    expect(
      await screen.findByText(/1 of the 3 things on today's plan/i),
    ).toBeInTheDocument();
  });
});

describe("an empty sitting", () => {
  it("says nothing was recorded, and that it is not held against them", async () => {
    mocks.completeSession.mockResolvedValue(EMPTY);
    renderPage();

    expect(
      await screen.findByText(/nothing was finished in this sitting/i),
    ).toBeInTheDocument();
  });
});

describe("reloading", () => {
  it("completes by id, so a refresh returns the same summary", async () => {
    // Idempotency is what lets this be a page with an address rather than a
    // modal that must not be dismissed.
    renderPage();
    await screen.findByText("read:cafe.b1");

    expect(mocks.completeSession).toHaveBeenCalledWith("test-token", "sit-1");
  });
});
