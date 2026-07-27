/**
 * Activity player: the writing kind.
 *
 * The load-bearing behaviour is honesty. Deterministic checks confirm the
 * learner produced connected language; nothing here judged whether it was
 * accurate. Presenting a passed length check as "good writing" is exactly the
 * dishonesty `docs/AI_TUTOR_BEHAVIOR.md` forbids, so the provisional warning
 * is a tested requirement rather than a nicety.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WritingActivity, WritingResult } from "@/lib/api";
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
    useParams: () => ({ key: "write:write.a2.late_email" }),
  };
});

const ACTIVITY: WritingActivity = {
  activityKey: "write:write.a2.late_email",
  activityType: "writing_task",
  title: "An email to say you will be late",
  cefrLevel: "A2",
  skillKey: "writing.linked_messages",
  estimatedMinutes: 10,
  genre: "email",
  prompt:
    "Your train is cancelled and you will arrive about an hour late.\n\nWrite an email to your colleague.",
  guidance: [
    "Apologise explicitly — say you are sorry.",
    "Link your reasons with 'because' or 'so'.",
  ],
  minWords: 50,
  maxWords: 150,
  minSentences: 4,
  requiredElements: ["sorry", "train"],
};

const PASSING: WritingResult = {
  activityType: "writing_task",
  activityKey: ACTIVITY.activityKey,
  score: 1,
  explanation:
    "These are automatic checks on length, structure and content. They do not judge grammar or word choice.",
  checks: [
    { code: "length", passed: true, message: "67 words — a good length." },
    { code: "sentences", passed: true, message: "5 sentences." },
    {
      code: "connectives",
      passed: true,
      message: "You linked ideas using: because, so.",
    },
    {
      code: "content",
      passed: true,
      message: "You covered everything the task asked for.",
    },
  ],
  wordCount: 67,
  sentenceCount: 5,
  lexicalVariety: 0.7,
  connectivesUsed: ["because", "so"],
  missingElements: [],
  evidenceRecorded: true,
  provisional: true,
  rubric: [],
  priorityFeedback: [],
  evaluatedBy: null,
};

/** What a deployment with an evaluator configured actually returns. */
const JUDGED: WritingResult = {
  ...PASSING,
  explanation:
    "Checked for length, structure and content, and assessed for accuracy and range against a rubric.",
  provisional: false,
  rubric: [
    {
      name: "accuracy",
      score: 0.7,
      confidence: 0.8,
      evidence: ["My train was cancelled"],
    },
  ],
  priorityFeedback: [
    {
      category: "grammar.tense.past_simple_form",
      original: "I have late yesterday",
      improved: "I was late yesterday",
      explanation: "Yesterday is a finished time, so the past simple fits.",
    },
  ],
  evaluatedBy: "fake",
};

const TOO_SHORT: WritingResult = {
  ...PASSING,
  score: 0.25,
  explanation:
    "Too short to say much yet. Write a bit more and the checks below will tell you more.",
  checks: [
    {
      code: "length",
      passed: false,
      message: "3 words. This task asks for at least 50.",
    },
  ],
  wordCount: 3,
  sentenceCount: 1,
  connectivesUsed: [],
  missingElements: ["sorry"],
  evidenceRecorded: false,
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
  mocks.completeActivity.mockResolvedValue(PASSING);
});

describe("the task", () => {
  it("shows the prompt and the guidance", async () => {
    renderPage();
    expect(await screen.findByText(/train is cancelled/i)).toBeInTheDocument();
    expect(screen.getByText(/apologise explicitly/i)).toBeInTheDocument();
  });

  it("states the requirements up front", async () => {
    // A word count the learner cannot see is a trap, not a requirement.
    renderPage();
    await screen.findByRole("heading", { name: /say you will be late/i });

    expect(screen.getByText(/50.150 words/i)).toBeInTheDocument();
    expect(screen.getByText(/at least 4 sentences/i)).toBeInTheDocument();
    expect(screen.getByText(/sorry, train/i)).toBeInTheDocument();
  });

  it("names the genre and level", async () => {
    renderPage();
    expect(await screen.findByText(/WRITING · A2 · EMAIL/)).toBeInTheDocument();
  });
});

describe("drafting", () => {
  it("counts words as the learner types", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: /say you will be late/i });

    await user.type(screen.getByRole("textbox"), "Hello there Sam");
    expect(screen.getByText(/3 words/)).toBeInTheDocument();
  });

  it("says how many more words are needed rather than blocking", async () => {
    // Guidance, not a gate: a learner who wants to submit something short
    // still gets told what the checks found.
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: /say you will be late/i });

    await user.type(screen.getByRole("textbox"), "Sorry, train broke.");
    expect(screen.getByText(/more to go/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /check my writing/i }),
    ).toBeEnabled();
  });

  it("will not submit an empty response", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /say you will be late/i });
    expect(
      screen.getByRole("button", { name: /check my writing/i }),
    ).toBeDisabled();
  });

  it("sends the text, not answers", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: /say you will be late/i });

    await user.type(screen.getByRole("textbox"), "Sorry, the train broke.");
    await user.click(screen.getByRole("button", { name: /check my writing/i }));

    expect(mocks.completeActivity).toHaveBeenCalledWith(
      "test-token",
      "write:write.a2.late_email",
      { text: "Sorry, the train broke." },
    );
  });
});

describe("feedback", () => {
  async function submit() {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: /say you will be late/i });
    await user.type(screen.getByRole("textbox"), "Sorry, the train broke.");
    await user.click(screen.getByRole("button", { name: /check my writing/i }));
    return user;
  }

  it("never claims the writing was judged good", async () => {
    // The single most important assertion in this file.
    await submit();

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/nothing here has judged your grammar/i);
    expect(status).toHaveTextContent(/length, structure/i);
  });

  it("lists each check with the reason", async () => {
    await submit();

    await screen.findByRole("status");
    expect(screen.getByText(/a good length/i)).toBeInTheDocument();
    expect(screen.getByText(/you linked ideas using/i)).toBeInTheDocument();
  });

  it("shows what the rubric looked at, and what it quoted", async () => {
    // A score with no evidence is a guess. The learner has to be able to
    // disagree with a judgement, which means seeing what it rested on.
    mocks.completeActivity.mockResolvedValue(JUDGED);
    await submit();

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/assessed against a rubric/i);
    expect(status).toHaveTextContent(/accuracy/i);
    expect(status).toHaveTextContent(/my train was cancelled/i);
  });

  it("names the evaluator and says it can be wrong", async () => {
    mocks.completeActivity.mockResolvedValue(JUDGED);
    await submit();

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/not by a teacher/i);
    expect(status).toHaveTextContent(/can be wrong/i);
  });

  it("drops the provisional warning once accuracy has been judged", async () => {
    mocks.completeActivity.mockResolvedValue(JUDGED);
    await submit();

    const status = await screen.findByRole("status");
    expect(status).not.toHaveTextContent(
      /nothing here has judged your grammar/i,
    );
  });

  it("limits corrections to what is worth fixing first", async () => {
    // Correcting everything teaches nothing.
    mocks.completeActivity.mockResolvedValue(JUDGED);
    await submit();

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/worth fixing first/i);
    expect(status).toHaveTextContent(/I was late yesterday/);
  });

  it("says when a response was too short to count for anything", async () => {
    mocks.completeActivity.mockResolvedValue(TOO_SHORT);
    await submit();

    const status = await screen.findByRole("status");
    // "Not enough to say" and "said badly" are different claims.
    expect(status).toHaveTextContent(/has not changed your profile/i);
    expect(status).toHaveTextContent(/it is saved/i);
  });

  it("does not reduce the result to a mark", async () => {
    await submit();

    const status = await screen.findByRole("status");
    expect(status.textContent).not.toMatch(/\d+\s?%/);
    expect(status.textContent).not.toMatch(/\bscore\b/i);
  });

  it("offers a way back to the plan", async () => {
    await submit();

    expect(
      await screen.findByRole("link", { name: /back to today.s plan/i }),
    ).toHaveAttribute("href", "/dashboard");
  });
});
