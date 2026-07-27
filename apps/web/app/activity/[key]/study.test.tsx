/**
 * Activity player: the study kind.
 *
 * Two things carry the weight here.
 *
 * The explanation stays on screen while the learner practises — that is what a
 * study unit *is*. And because it does, the result has to say out loud that
 * this was guided practice rather than recall. A perfect score with the rule
 * in front of you is not proof, and a UI that implies otherwise is lying to
 * the learner about their own progress.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StudyActivity, StudyResult } from "@/lib/api";
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
    useParams: () => ({ key: "study:study.a2.past_simple" }),
  };
});

const ACTIVITY: StudyActivity = {
  activityKey: "study:study.a2.past_simple",
  activityType: "study_task",
  title: "Talking about finished time",
  cefrLevel: "A2",
  skillKey: "grammar.past_future_basic",
  estimatedMinutes: 8,
  explanation:
    "Use the past simple for something finished, at a time that is finished.\n\nFor negatives and questions, use 'did' plus the plain form.",
  examples: ["We arrived at eight.", "I did not see your message."],
  items: [
    {
      key: "i1",
      itemType: "gap_fill",
      feature: "grammar.tense.past_simple_form",
      featureLabel: "Past simple forms",
      prompt: "Yesterday she ___ (go) to the office by bus.",
      options: [],
    },
    {
      key: "i2",
      itemType: "choice",
      feature: "grammar.word_order.question",
      featureLabel: "Question formation",
      prompt: "___ you finish the report on Friday?",
      options: ["Did", "Do"],
    },
  ],
};

const RESULT: StudyResult = {
  activityType: "study_task",
  activityKey: ACTIVITY.activityKey,
  score: 0.5,
  correctCount: 1,
  total: 2,
  explanation: "Mostly there. Worth another look at: Question formation.",
  results: [
    {
      key: "i1",
      feature: "grammar.tense.past_simple_form",
      featureLabel: "Past simple forms",
      correct: true,
      expected: "went",
      note: "'Go' is irregular: the past simple is 'went'.",
    },
    {
      key: "i2",
      feature: "grammar.word_order.question",
      featureLabel: "Question formation",
      correct: false,
      expected: "Did",
      note: "'On Friday' is a finished time, so the question uses 'did'.",
    },
  ],
  evidenceRecorded: true,
  independence: 0.65,
  loggedFeatures: ["grammar.word_order.question"],
};

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <ActivityPage />
    </SessionProvider>,
  );
}

/**
 * Render the unit and answer every item correctly.
 *
 * Renders as well as answering: a helper that assumed its caller had already
 * mounted the page would silently query an empty document, and the failure
 * would look like a missing heading rather than a missing render.
 */
async function answerEverything() {
  const user = userEvent.setup();
  renderPage();
  await screen.findByRole("heading", { name: /finished time/i });
  await user.type(screen.getByRole("textbox"), "went");
  await user.click(screen.getByRole("radio", { name: "Did" }));
  return user;
}

beforeEach(() => {
  mocks.fetchActivity.mockReset();
  mocks.completeActivity.mockReset();
  mocks.fetchActivity.mockResolvedValue(ACTIVITY);
  mocks.completeActivity.mockResolvedValue(RESULT);
});

describe("the explanation", () => {
  it("is on screen before anything is asked", async () => {
    renderPage();
    expect(await screen.findByText(/use the past simple/i)).toBeInTheDocument();
  });

  it("stays on screen while the learner practises", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /finished time/i });

    // Both are visible at once. That is the design, not an oversight.
    expect(screen.getByText(/use the past simple/i)).toBeInTheDocument();
    expect(screen.getAllByRole("group").length).toBeGreaterThan(0);
  });

  it("shows the worked examples", async () => {
    renderPage();
    expect(await screen.findByText(/we arrived at eight/i)).toBeInTheDocument();
  });
});

describe("practising", () => {
  it("gives a gap-fill a text box and a choice item radios", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /finished time/i });

    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(2);
  });

  it("names what each item is practising", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /finished time/i });

    // The label, never the raw taxonomy code.
    expect(screen.getByText("Past simple forms")).toBeInTheDocument();
    expect(screen.queryByText(/grammar\.tense/)).not.toBeInTheDocument();
  });

  it("will not submit a partially answered unit", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /finished time/i });
    expect(
      screen.getByRole("button", { name: /answer all 2/i }),
    ).toBeDisabled();
  });

  it("reports how much help was taken", async () => {
    // Self-reported, and it reduces the weight of the evidence. Hiding that a
    // learner needed the rule would overstate what they showed.
    const user = await answerEverything();
    await user.click(
      screen.getAllByRole("button", { name: /need a hint/i })[0],
    );
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    expect(mocks.completeActivity).toHaveBeenCalledWith(
      "test-token",
      "study:study.a2.past_simple",
      { answers: { i1: "went", i2: "Did" }, hintsUsed: 1 },
    );
  });

  it("reports no help when none was taken", async () => {
    const user = await answerEverything();
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    expect(mocks.completeActivity).toHaveBeenCalledWith(
      "test-token",
      "study:study.a2.past_simple",
      { answers: { i1: "went", i2: "Did" }, hintsUsed: 0 },
    );
  });

  it("never reveals an answer or note before submission", async () => {
    renderPage();
    await screen.findByRole("heading", { name: /finished time/i });

    expect(screen.queryByText(/is irregular/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Correct:$/)).not.toBeInTheDocument();
  });
});

describe("feedback", () => {
  it("explains each item, right or wrong", async () => {
    const user = await answerEverything();
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    await screen.findByRole("status");
    expect(screen.getByText(/is irregular/i)).toBeInTheDocument();
    expect(screen.getByText(/a finished time/i)).toBeInTheDocument();
  });

  it("marks each outcome with text, not colour alone", async () => {
    const user = await answerEverything();
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    // Scoped to the result panel: the explanation above has its own list of
    // worked examples, and those are not outcomes.
    const status = await screen.findByRole("status");
    const items = within(status).getAllByRole("listitem");
    expect(within(items[0]).getByText(/^Correct:$/)).toBeInTheDocument();
    expect(within(items[1]).getByText(/^Missed:$/)).toBeInTheDocument();
  });

  it("says plainly that this was guided practice, not recall", async () => {
    // The invariant: help on screen means the evidence is weaker, and the
    // learner is told so rather than left to infer it.
    const user = await answerEverything();
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/explanation in front of you/i);
    expect(status).toHaveTextContent(/spaced review/i);
  });

  it("says what has been added to the practice queue", async () => {
    const user = await answerEverything();
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/added to your practice queue/i);
    expect(status).toHaveTextContent(/Question formation/);
  });

  it("does not reduce the result to a mark", async () => {
    const user = await answerEverything();
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    const status = await screen.findByRole("status");
    expect(status.textContent).not.toMatch(/\d+\s?%/);
  });

  it("offers a way back to the plan", async () => {
    const user = await answerEverything();
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    expect(
      await screen.findByRole("link", { name: /back to today.s plan/i }),
    ).toHaveAttribute("href", "/dashboard");
  });
});
