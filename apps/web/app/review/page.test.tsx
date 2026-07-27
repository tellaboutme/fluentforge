/**
 * Review player.
 *
 * The load-bearing assertion: a card must not contain its own answer before
 * the learner has committed. A review that reveals the answer up front tests
 * nothing, and the whole spacing model rests on genuine retrieval attempts.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type DueReviews } from "@/lib/api";
import { SessionProvider } from "@/lib/session";
import { routerMock } from "@/test/setup";

import ReviewPage from "./page";

const mocks = vi.hoisted(() => ({
  fetchDueReviews: vi.fn(),
  answerReview: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

function card(overrides: Partial<DueReviews["cards"][number]> = {}) {
  return {
    id: "c1",
    memoryObjectKey: "make_a_decision",
    reviewMode: "meaning_recognition",
    lemma: "make a decision",
    pos: "phrase",
    cefrLevel: "B1",
    meaning: null,
    example: null,
    repetitions: 0,
    lapses: 0,
    ...overrides,
  };
}

const ANSWER = {
  id: "c1",
  intervalDays: 2.56,
  dueAt: "2026-07-30T12:00:00Z",
  explanation: "Back in about 3 days.",
  repetitions: 1,
  lapses: 0,
  meaning: "decide something",
  example: "It took us a week to make a decision.",
};

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <ReviewPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mocks.fetchDueReviews.mockReset();
  mocks.answerReview.mockReset();
  mocks.answerReview.mockResolvedValue(ANSWER);
});

describe("retrieval before reveal", () => {
  it("does not put the answer in the DOM before the learner commits", async () => {
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card()],
    });
    const { container } = renderPage();

    await screen.findByRole("heading", { name: "make a decision" });
    expect(container.textContent).not.toContain("decide something");
    expect(container.textContent).not.toContain("It took us a week");
  });

  it("reveals the meaning only after grading", async () => {
    const user = userEvent.setup();
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card()],
    });
    renderPage();

    await screen.findByRole("heading", { name: "make a decision" });
    await user.click(screen.getByRole("button", { name: /i knew it/i }));

    expect(await screen.findByText("decide something")).toBeInTheDocument();
    expect(screen.getByText(/it took us a week/i)).toBeInTheDocument();
  });

  it("tells the learner which memory is being tested", async () => {
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card({ reviewMode: "contextual_production" })],
    });
    renderPage();

    expect(
      await screen.findByText(/use it in a sentence of your own/i),
    ).toBeInTheDocument();
  });

  it("distinguishes recognition from production wording", async () => {
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card({ reviewMode: "meaning_recognition" })],
    });
    renderPage();

    expect(
      await screen.findByText(/do you know what this means/i),
    ).toBeInTheDocument();
  });

  it("explains why the effort matters", async () => {
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card()],
    });
    renderPage();

    expect(
      await screen.findByText(/the effort is what makes it stick/i),
    ).toBeInTheDocument();
  });
});

describe("grading", () => {
  it("offers four grades, not a right/wrong toggle", async () => {
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card()],
    });
    renderPage();

    await screen.findByRole("heading", { name: "make a decision" });
    for (const label of [
      /didn't know it/i,
      /hard, but/i,
      /i knew it/i,
      /instantly/i,
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("says what each grade will do to the schedule", async () => {
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card()],
    });
    renderPage();

    await screen.findByRole("heading", { name: "make a decision" });
    expect(screen.getByText(/comes back very soon/i)).toBeInTheDocument();
    expect(screen.getByText(/longer interval/i)).toBeInTheDocument();
  });

  it("sends the chosen grade", async () => {
    const user = userEvent.setup();
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card()],
    });
    renderPage();

    await screen.findByRole("heading", { name: "make a decision" });
    await user.click(screen.getByRole("button", { name: /didn't know it/i }));

    expect(mocks.answerReview).toHaveBeenCalledWith(
      "test-token",
      "c1",
      "forgot",
    );
  });

  it("announces the new interval in a live region", async () => {
    const user = userEvent.setup();
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card()],
    });
    renderPage();

    await screen.findByRole("heading", { name: "make a decision" });
    await user.click(screen.getByRole("button", { name: /i knew it/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent(/back in about 3 days/i);
  });

  it("can be graded with the keyboard alone", async () => {
    const user = userEvent.setup();
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card()],
    });
    renderPage();

    await screen.findByRole("heading", { name: "make a decision" });
    await user.tab();
    await user.tab();
    await user.keyboard("{Enter}");

    expect(mocks.answerReview).toHaveBeenCalled();
  });
});

describe("the queue", () => {
  it("moves to the next card", async () => {
    const user = userEvent.setup();
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 2,
      returned: 2,
      cards: [card(), card({ id: "c2", lemma: "look up" })],
    });
    renderPage();

    await screen.findByRole("heading", { name: "make a decision" });
    await user.click(screen.getByRole("button", { name: /i knew it/i }));
    await user.click(await screen.findByRole("button", { name: /next card/i }));

    expect(
      await screen.findByRole("heading", { name: "look up" }),
    ).toBeInTheDocument();
  });

  it("finishes cleanly after the last card", async () => {
    const user = userEvent.setup();
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 1,
      returned: 1,
      cards: [card()],
    });
    renderPage();

    await screen.findByRole("heading", { name: "make a decision" });
    await user.click(screen.getByRole("button", { name: /i knew it/i }));
    await user.click(await screen.findByRole("button", { name: /finish/i }));

    expect(
      await screen.findByRole("heading", { name: /that's your reviews done/i }),
    ).toBeInTheDocument();
  });

  it("explains an empty queue rather than looking broken", async () => {
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 0,
      returned: 0,
      cards: [],
    });
    renderPage();

    expect(
      await screen.findByRole("heading", { name: /nothing due right now/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/spacing means waiting/i)).toBeInTheDocument();
  });

  it("shows a loading state first", () => {
    mocks.fetchDueReviews.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(
      /loading your reviews/i,
    );
  });

  it("recovers from a transient failure", async () => {
    const user = userEvent.setup();
    mocks.fetchDueReviews
      .mockRejectedValueOnce(
        new ApiError(503, "curriculum_not_loaded", "Not loaded."),
      )
      .mockResolvedValue({ dueNow: 1, returned: 1, cards: [card()] });
    renderPage();

    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(
      await screen.findByRole("heading", { name: "make a decision" }),
    ).toBeInTheDocument();
  });

  it("redirects a signed-out visitor", async () => {
    window.sessionStorage.clear();
    mocks.fetchDueReviews.mockResolvedValue({
      dueNow: 0,
      returned: 0,
      cards: [],
    });
    render(
      <SessionProvider>
        <ReviewPage />
      </SessionProvider>,
    );

    expect(routerMock.replace).toHaveBeenCalledWith("/sign-in");
  });
});
