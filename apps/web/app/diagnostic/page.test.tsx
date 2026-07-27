/**
 * Diagnostic player.
 *
 * The behaviours asserted here are the ones a learner would notice and a type
 * checker cannot see: focus landing on each new question, feedback being
 * announced, and the report never presenting the starting band as a score.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { SessionProvider } from "@/lib/session";

import DiagnosticPage from "./page";

const mocks = vi.hoisted(() => ({
  startDiagnostic: vi.fn(),
  fetchNextItem: vi.fn(),
  submitResponse: vi.fn(),
  completeDiagnostic: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

const CHOICE_ITEM = {
  key: "grammar.a1.be_present",
  itemType: "multiple_choice" as const,
  skillKey: "grammar.basic_clause",
  cefrLevel: "A1",
  prompt: "She ___ a teacher.",
  instructions: "",
  options: ["is", "are", "am", "be"],
  difficulty: 0.1,
  minWords: null,
  maxWords: null,
};

const GAP_ITEM = {
  ...CHOICE_ITEM,
  key: "grammar.a1.article",
  itemType: "gap_fill" as const,
  prompt: "I have ___ apple in my bag.",
  instructions: "Write one word.",
  options: [],
};

const RATING_ITEM = {
  ...CHOICE_ITEM,
  key: "self.speaking.sustained",
  itemType: "self_assessment" as const,
  prompt: "I can describe my daily routine.",
  instructions: "Rate 0 to 4.",
  options: [],
};

const REPORT = {
  sessionId: "s1",
  itemsAnswered: 14,
  skillsObserved: 9,
  startingBand: "A2",
  outcomes: [
    {
      skillKey: "grammar.basic_clause",
      title: "Basic clause",
      cefrLevel: "A1",
      masteryProbability: 0.63,
      confidence: 0.25,
      evidenceCount: 3,
      distinctContexts: 2,
      status: "emerging",
    },
  ],
  caveats: [
    "This is an internal estimate, not an official CEFR certificate.",
    "Your starting level decides which content you see first. It is not a score.",
  ],
};

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <DiagnosticPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.startDiagnostic.mockResolvedValue({
    id: "s1",
    status: "in_progress",
    answered: 0,
  });
  mocks.completeDiagnostic.mockResolvedValue(REPORT);
});

function servesOnce(item: unknown) {
  mocks.fetchNextItem
    .mockResolvedValueOnce({
      sessionId: "s1",
      finished: false,
      answered: 0,
      item,
    })
    .mockResolvedValue({
      sessionId: "s1",
      finished: true,
      answered: 1,
      item: null,
    });
}

describe("serving items", () => {
  it("shows a loading state before the first question", () => {
    mocks.fetchNextItem.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(
      /preparing your diagnostic/i,
    );
  });

  it("renders multiple choice as real radio inputs", async () => {
    servesOnce(CHOICE_ITEM);
    renderPage();

    await screen.findByRole("heading", { name: /she ___ a teacher/i });
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    expect(screen.getByRole("radio", { name: "is" })).toBeInTheDocument();
  });

  it("renders gap fill as a labelled text field", async () => {
    servesOnce(GAP_ITEM);
    renderPage();

    await screen.findByRole("heading", { name: /i have ___ apple/i });
    expect(screen.getByLabelText(/your answer/i)).toBeInTheDocument();
    expect(screen.getByText(/write one word/i)).toBeInTheDocument();
  });

  it("renders self-assessment as words, not bare numbers", async () => {
    servesOnce(RATING_ITEM);
    renderPage();

    await screen.findByRole("heading", {
      name: /i can describe my daily routine/i,
    });
    expect(
      screen.getByRole("radio", { name: /not at all/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /easily/i })).toBeInTheDocument();
  });

  it("moves focus to each new question", async () => {
    servesOnce(CHOICE_ITEM);
    renderPage();

    const heading = await screen.findByRole("heading", {
      name: /she ___ a teacher/i,
    });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it("tells the learner this is not a test", async () => {
    servesOnce(CHOICE_ITEM);
    renderPage();
    expect(await screen.findByText(/this is not a test/i)).toBeInTheDocument();
  });
});

describe("answering", () => {
  it("cannot be submitted empty", async () => {
    servesOnce(CHOICE_ITEM);
    renderPage();

    await screen.findByRole("heading", { name: /she ___/i });
    expect(
      screen.getByRole("button", { name: /check answer/i }),
    ).toBeDisabled();
  });

  it("can be answered with the keyboard alone", async () => {
    const user = userEvent.setup();
    servesOnce(CHOICE_ITEM);
    mocks.submitResponse.mockResolvedValue({
      correct: true,
      score: 1,
      explanation: "Correct.",
      expected: ["is"],
      answered: 1,
      finished: false,
      checks: [],
      provisional: false,
    });
    renderPage();

    await screen.findByRole("heading", { name: /she ___/i });
    await user.tab();
    await user.keyboard(" ");

    const submit = screen.getByRole("button", { name: /check answer/i });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(mocks.submitResponse).toHaveBeenCalledWith("test-token", "s1", {
        itemKey: CHOICE_ITEM.key,
        response: "is",
      }),
    );
  });

  it("announces feedback in a live region", async () => {
    const user = userEvent.setup();
    servesOnce(CHOICE_ITEM);
    mocks.submitResponse.mockResolvedValue({
      correct: false,
      score: 0,
      explanation: "'are' goes with you/we/they.",
      expected: ["is"],
      answered: 1,
      finished: false,
      checks: [],
      provisional: false,
    });
    renderPage();

    await screen.findByRole("heading", { name: /she ___/i });
    await user.click(screen.getByRole("radio", { name: "are" }));
    await user.click(screen.getByRole("button", { name: /check answer/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent(/not quite/i);
    expect(status).toHaveTextContent(/goes with you\/we\/they/i);
  });

  it("locks the answer once submitted", async () => {
    const user = userEvent.setup();
    servesOnce(CHOICE_ITEM);
    mocks.submitResponse.mockResolvedValue({
      correct: true,
      score: 1,
      explanation: "Correct.",
      expected: ["is"],
      answered: 1,
      finished: false,
      checks: [],
      provisional: false,
    });
    renderPage();

    await screen.findByRole("heading", { name: /she ___/i });
    await user.click(screen.getByRole("radio", { name: "is" }));
    await user.click(screen.getByRole("button", { name: /check answer/i }));

    await screen.findByRole("status");
    expect(screen.getByRole("radio", { name: "is" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /check answer/i }),
    ).not.toBeInTheDocument();
  });
});

describe("the report", () => {
  it("presents the starting band as routing, never as a score", async () => {
    mocks.fetchNextItem.mockResolvedValue({
      sessionId: "s1",
      finished: true,
      answered: 14,
      item: null,
    });
    renderPage();

    await screen.findByRole("heading", {
      name: /here is what we can say so far/i,
    });

    const band = screen.getByText("A2").closest("div");
    expect(band).not.toBeNull();
    // The disclaimer sits beside the band itself, not only in the caveats list.
    expect(
      within(band as HTMLElement).getByText(/it is not a score/i),
    ).toBeInTheDocument();
    expect(
      within(band as HTMLElement).getByText(/starting level for your content/i),
    ).toBeInTheDocument();
  });

  it("shows every caveat the API returned", async () => {
    mocks.fetchNextItem.mockResolvedValue({
      sessionId: "s1",
      finished: true,
      answered: 14,
      item: null,
    });
    renderPage();

    await screen.findByRole("heading", {
      name: /here is what we can say so far/i,
    });
    for (const caveat of REPORT.caveats) {
      expect(screen.getByText(caveat)).toBeInTheDocument();
    }
  });

  it("labels an emerging skill as needing evidence, not as a level", async () => {
    mocks.fetchNextItem.mockResolvedValue({
      sessionId: "s1",
      finished: true,
      answered: 14,
      item: null,
    });
    renderPage();

    const outcome = (await screen.findByText("Basic clause")).closest("li");
    expect(outcome).not.toBeNull();
    expect(
      within(outcome as HTMLElement).getByText(/emerging/i),
    ).toBeInTheDocument();
  });
});

describe("written responses", () => {
  const WRITING_ITEM = {
    ...CHOICE_ITEM,
    key: "writing.a2.last_weekend",
    itemType: "written_response" as const,
    prompt: "What did you do last weekend?",
    instructions: "Write about 50 words.",
    options: [],
    minWords: 40,
    maxWords: 160,
  };

  it("renders a textarea, not a set of choices", async () => {
    servesOnce(WRITING_ITEM);
    renderPage();

    const box = await screen.findByLabelText(/your answer/i);
    expect(box.tagName).toBe("TEXTAREA");
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
  });

  it("states the length requirement before the learner writes", async () => {
    servesOnce(WRITING_ITEM);
    renderPage();

    await screen.findByLabelText(/your answer/i);
    expect(screen.getByText(/aim for at least 40/i)).toBeInTheDocument();
  });

  it("counts words as the learner types, politely", async () => {
    const user = userEvent.setup();
    servesOnce(WRITING_ITEM);
    renderPage();

    const box = await screen.findByLabelText(/your answer/i);
    await user.type(box, "I went to the park");

    const counter = screen.getByText(/5 words/i);
    expect(counter).toHaveAttribute("aria-live", "polite");
  });

  it("reassures the learner that grammar is not being graded", async () => {
    servesOnce(WRITING_ITEM);
    renderPage();

    await screen.findByLabelText(/your answer/i);
    expect(
      screen.getByText(/nothing here is graded for grammar/i),
    ).toBeInTheDocument();
  });

  it("lets a short answer be submitted rather than blocking it", async () => {
    const user = userEvent.setup();
    servesOnce(WRITING_ITEM);
    renderPage();

    const box = await screen.findByLabelText(/your answer/i);
    await user.type(box, "Short.");
    expect(
      screen.getByRole("button", { name: /submit my answer/i }),
    ).toBeEnabled();
  });

  it("does not present a provisional result as right or wrong", async () => {
    const user = userEvent.setup();
    servesOnce(WRITING_ITEM);
    mocks.submitResponse.mockResolvedValue({
      correct: true,
      score: 0.75,
      explanation:
        "These are automatic checks on length, structure and content. They do not judge grammar or word choice.",
      expected: [],
      answered: 1,
      finished: false,
      provisional: true,
      checks: [
        { code: "length", passed: true, message: "46 words — a good length." },
        {
          code: "connectives",
          passed: false,
          message: "Try joining your ideas with words like 'because'.",
        },
      ],
    });
    renderPage();

    await user.type(
      await screen.findByLabelText(/your answer/i),
      "Some writing.",
    );
    await user.click(screen.getByRole("button", { name: /submit my answer/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/here is what we could check/i);
    expect(status).not.toHaveTextContent(/^correct$/i);
    expect(status).not.toHaveTextContent(/not quite/i);
  });

  it("lists which checks were met and which to work on", async () => {
    const user = userEvent.setup();
    servesOnce(WRITING_ITEM);
    mocks.submitResponse.mockResolvedValue({
      correct: true,
      score: 0.5,
      explanation: "Automatic checks only.",
      expected: [],
      answered: 1,
      finished: false,
      provisional: true,
      checks: [
        { code: "length", passed: true, message: "46 words — a good length." },
        {
          code: "connectives",
          passed: false,
          message: "Try joining your ideas.",
        },
      ],
    });
    renderPage();

    await user.type(
      await screen.findByLabelText(/your answer/i),
      "Some writing.",
    );
    await user.click(screen.getByRole("button", { name: /submit my answer/i }));

    await screen.findByRole("status");
    const met = screen.getByText(/a good length/i).closest("li");
    const todo = screen.getByText(/try joining your ideas/i).closest("li");

    // Not colour alone: each item carries a text cue for screen readers.
    expect(within(met as HTMLElement).getByText(/^Met:$/)).toBeInTheDocument();
    expect(
      within(todo as HTMLElement).getByText(/^To work on:$/),
    ).toBeInTheDocument();
  });
});

describe("failure", () => {
  it("explains a missing curriculum and offers a retry", async () => {
    mocks.startDiagnostic.mockRejectedValue(
      new ApiError(503, "curriculum_not_loaded", "No curriculum is loaded."),
    );
    renderPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/make load-curriculum/i);
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("does not offer a retry that cannot succeed", async () => {
    mocks.startDiagnostic.mockRejectedValue(
      new ApiError(404, "session_not_found", "That session does not exist."),
    );
    renderPage();

    await screen.findByRole("alert");
    expect(
      screen.queryByRole("button", { name: /try again/i }),
    ).not.toBeInTheDocument();
  });
});
