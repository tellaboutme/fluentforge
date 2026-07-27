/**
 * Activity player: the reading kind.
 *
 * The load-bearing behaviour: the text stays on screen while the learner
 * answers. This is comprehension practice, not a memory test — hiding the text
 * would silently change what is being measured.
 *
 * The study and writing kinds have their own files, because each has a
 * different contract with the learner and mixing them would obscure that.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type Activity } from "@/lib/api";
import { SessionProvider } from "@/lib/session";

import ActivityPage from "./page";

const mocks = vi.hoisted(() => ({
  fetchActivity: vi.fn(),
  completeActivity: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return {
    useRouter: () => setup.routerMock,
    useParams: () => ({ key: "read:text.a2.message" }),
  };
});

const ACTIVITY: Activity = {
  activityKey: "read:text.a2.message",
  activityType: "reading_task",
  title: "A message from a colleague",
  body: "Hi Sam,\n\nI'm going to be about twenty minutes late.",
  cefrLevel: "A2",
  skillKey: "reading.short_everyday_texts",
  estimatedMinutes: 5,
  wordCount: 42,
  questions: [
    {
      key: "gist",
      questionType: "gist",
      prompt: "Why is Alex writing?",
      options: ["To say they will arrive late.", "To cancel the meeting."],
    },
    {
      key: "detail",
      questionType: "detail",
      prompt: "Who will talk about the budget?",
      options: ["Maria", "Sam"],
    },
  ],
};

const RESULT = {
  activityType: "reading_task" as const,
  activityKey: ACTIVITY.activityKey,
  score: 0.5,
  correctCount: 1,
  total: 2,
  explanation: "You got the main idea. Some details were missed.",
  results: [
    {
      key: "gist",
      questionType: "gist",
      correct: true,
      expected: "To say they will arrive late.",
    },
    {
      key: "detail",
      questionType: "detail",
      correct: false,
      expected: "Maria",
    },
  ],
  evidenceRecorded: true,
};

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <ActivityPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mocks.fetchActivity.mockReset();
  mocks.completeActivity.mockReset();
  mocks.fetchActivity.mockResolvedValue(ACTIVITY);
  mocks.completeActivity.mockResolvedValue(RESULT);
});

describe("reading first", () => {
  it("shows the text before any questions", async () => {
    renderPage();

    await screen.findByRole("heading", { name: /a message from a colleague/i });
    expect(screen.getByText(/twenty minutes late/i)).toBeInTheDocument();
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
  });

  it("tells the learner what they are in for", async () => {
    renderPage();
    expect(await screen.findByText(/42 words/i)).toBeInTheDocument();
    expect(screen.getByText(/about 5 minutes/i)).toBeInTheDocument();
  });

  it("keeps the text visible while answering", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a message from a colleague/i });
    await user.click(screen.getByRole("button", { name: /I.ve read it/i }));

    // Comprehension, not recall: the text must not disappear.
    expect(screen.getByText(/twenty minutes late/i)).toBeInTheDocument();
    expect(screen.getAllByRole("radio").length).toBeGreaterThan(0);
  });

  it("says the text can be looked at again", async () => {
    renderPage();
    expect(
      await screen.findByText(/look back at it while you answer/i),
    ).toBeInTheDocument();
  });
});

describe("answering", () => {
  it("labels what each question is testing", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a message/i });
    await user.click(screen.getByRole("button", { name: /I.ve read it/i }));

    expect(screen.getByText("Main idea")).toBeInTheDocument();
    expect(screen.getByText("Detail")).toBeInTheDocument();
  });

  it("will not submit a partially answered task", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a message/i });
    await user.click(screen.getByRole("button", { name: /I.ve read it/i }));

    expect(
      screen.getByRole("button", { name: /answer all 2 questions/i }),
    ).toBeDisabled();
  });

  it("submits once every question is answered", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a message/i });
    await user.click(screen.getByRole("button", { name: /I.ve read it/i }));
    await user.click(screen.getByRole("radio", { name: /arrive late/i }));
    await user.click(screen.getByRole("radio", { name: "Maria" }));
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    expect(mocks.completeActivity).toHaveBeenCalledWith(
      "test-token",
      "read:text.a2.message",
      { answers: { gist: "To say they will arrive late.", detail: "Maria" } },
    );
  });

  it("never shows the answers before submission", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a message/i });
    await user.click(screen.getByRole("button", { name: /I.ve read it/i }));

    // Options are visible, but nothing marks which is correct.
    expect(screen.queryByText(/correct/i)).not.toBeInTheDocument();
  });
});

describe("feedback", () => {
  it("frames the result as comprehension, not a mark", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a message/i });
    await user.click(screen.getByRole("button", { name: /I.ve read it/i }));
    await user.click(screen.getByRole("radio", { name: /arrive late/i }));
    await user.click(screen.getByRole("radio", { name: "Maria" }));
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/you got the main idea/i);
    expect(status.textContent).not.toMatch(/\d+\s?%/);
    expect(status.textContent).not.toMatch(/\b1\s*\/\s*2\b/);
  });

  it("marks each outcome with text, not colour alone", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a message/i });
    await user.click(screen.getByRole("button", { name: /I.ve read it/i }));
    await user.click(screen.getByRole("radio", { name: /arrive late/i }));
    await user.click(screen.getByRole("radio", { name: "Maria" }));
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    await screen.findByRole("status");
    const items = screen.getAllByRole("listitem");
    expect(within(items[0]).getByText(/^Correct:$/)).toBeInTheDocument();
    expect(within(items[1]).getByText(/^Missed:$/)).toBeInTheDocument();
  });

  it("offers a way back to the plan", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a message/i });
    await user.click(screen.getByRole("button", { name: /I.ve read it/i }));
    await user.click(screen.getByRole("radio", { name: /arrive late/i }));
    await user.click(screen.getByRole("radio", { name: "Maria" }));
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    expect(
      await screen.findByRole("link", { name: /back to today.s plan/i }),
    ).toHaveAttribute("href", "/dashboard");
  });
});

describe("states", () => {
  it("shows a loading state first", () => {
    mocks.fetchActivity.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(/opening/i);
  });

  it("explains a missing activity", async () => {
    mocks.fetchActivity.mockRejectedValue(
      new ApiError(
        404,
        "activity_not_found",
        "That activity is not available.",
      ),
    );
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /not available/i,
    );
  });
});
