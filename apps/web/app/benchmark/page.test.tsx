/**
 * The benchmark screen.
 *
 * Four things make a benchmark a measurement rather than more practice, and
 * three of them are visible here:
 *
 * - it cannot be started on demand;
 * - there is no help, and no control that could offer any;
 * - the result is reported even when it is a fall.
 *
 * The fourth — that the items are unseen — is enforced on the server and
 * tested there. What this file guards is that the UI does not undo any of it
 * by being encouraging.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BenchmarkEligibility,
  BenchmarkResult,
  BenchmarkSession,
} from "@/lib/api";
import { SessionProvider } from "@/lib/session";

import BenchmarkPage from "./page";

const mocks = vi.hoisted(() => ({
  fetchBenchmarkEligibility: vi.fn(),
  startBenchmark: vi.fn(),
  answerBenchmarkItem: vi.fn(),
  completeBenchmark: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return { useRouter: () => setup.routerMock };
});

const DUE: BenchmarkEligibility = {
  due: true,
  reason:
    "A benchmark is due. It is unaided, and it can move your profile either way.",
  nextDueAt: null,
};

const NOT_DUE: BenchmarkEligibility = {
  due: false,
  reason:
    "Your last benchmark was recent. The next one is in about 12 days — taking them closer together would measure the items rather than you.",
  nextDueAt: "2026-08-10T00:00:00Z",
};

const SESSION: BenchmarkSession = {
  sessionId: "b1",
  band: "A2",
  unaided: true,
  items: [
    {
      key: "i1",
      itemType: "multiple_choice",
      skillKey: "grammar.basic_clause",
      cefrLevel: "A2",
      prompt: "She ___ to work by bus.",
      instructions: "Choose the best option.",
      options: ["go", "goes", "going"],
    },
    {
      key: "i2",
      itemType: "gap_fill",
      skillKey: "vocabulary.everyday_topics",
      cefrLevel: "A2",
      prompt: "I have lived here ___ 2019.",
      instructions: "",
      options: [],
    },
  ],
};

const HELD: BenchmarkResult = {
  sessionId: "b1",
  band: "A2",
  answered: 2,
  correct: 2,
  score: 1,
  lowered: [],
};

const FELL: BenchmarkResult = {
  ...HELD,
  correct: 0,
  score: 0,
  lowered: ["grammar.basic_clause", "vocabulary.everyday_topics"],
};

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <BenchmarkPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.fetchBenchmarkEligibility.mockResolvedValue(DUE);
  mocks.startBenchmark.mockResolvedValue(SESSION);
  mocks.answerBenchmarkItem.mockResolvedValue({
    itemKey: "i1",
    correct: true,
    score: 1,
    remaining: 1,
  });
  mocks.completeBenchmark.mockResolvedValue(HELD);
});

describe("before it starts", () => {
  it("says what a benchmark is for", async () => {
    renderPage();
    expect(
      await screen.findByText(/what you can do with none of that/i),
    ).toBeInTheDocument();
  });

  it("says up front that it can move the profile down", async () => {
    // Told in advance, not discovered at the end. A learner who did not know
    // this was possible would read a fall as the app breaking.
    renderPage();
    const panel = await screen.findByText(/could only agree with you/i);
    expect(panel).toBeInTheDocument();
  });

  it("offers the benchmark when one is due", async () => {
    renderPage();
    expect(
      await screen.findByRole("button", { name: /start the benchmark/i }),
    ).toBeInTheDocument();
  });

  it("offers no way to start one that is not due", async () => {
    // The load-bearing refusal. A learner who could take one whenever they
    // felt ready would be measuring their confidence.
    mocks.fetchBenchmarkEligibility.mockResolvedValue(NOT_DUE);
    renderPage();

    await screen.findByRole("heading", { name: /unaided/i });
    expect(
      screen.queryByRole("button", { name: /start the benchmark/i }),
    ).toBeNull();
  });

  it("says when the next one is instead of just refusing", async () => {
    mocks.fetchBenchmarkEligibility.mockResolvedValue(NOT_DUE);
    renderPage();
    expect(await screen.findByText(/about 12 days/i)).toBeInTheDocument();
  });
});

describe("while taking it", () => {
  async function start() {
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: /start the benchmark/i }),
    );
    return user;
  }

  it("shows one question at a time, with its position", async () => {
    await start();
    expect(
      await screen.findByRole("heading", { name: /question 1 of 2/i }),
    ).toBeInTheDocument();
  });

  it("says plainly that no help is available", async () => {
    await start();
    expect(
      await screen.findByText(/no help is available/i),
    ).toBeInTheDocument();
  });

  it("offers no hint, reveal, or explanation control", async () => {
    // There is nothing to reveal, so there must be nothing suggesting there
    // is. Everywhere else in the product these exist and are recorded.
    await start();
    await screen.findByRole("heading", { name: /question 1 of 2/i });

    for (const label of [/hint/i, /reveal/i, /show answer/i, /explain/i]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }
  });

  it("sends no hint count with an answer", async () => {
    const user = await start();
    await user.click(await screen.findByRole("radio", { name: "goes" }));
    await user.click(screen.getByRole("button", { name: /next question/i }));

    const [, , submission] = mocks.answerBenchmarkItem.mock.calls[0];
    expect(Object.keys(submission)).toEqual(["itemKey", "response"]);
  });

  it("does not say whether the answer was right", async () => {
    // Being told item one was wrong changes how item two is answered, and
    // the measurement is of the whole set.
    const user = await start();
    await user.click(await screen.findByRole("radio", { name: "goes" }));
    await user.click(screen.getByRole("button", { name: /next question/i }));

    await screen.findByRole("heading", { name: /question 2 of 2/i });
    expect(screen.queryByText(/correct/i)).toBeNull();
    expect(screen.queryByText(/well done/i)).toBeNull();
  });

  it("does not carry an answer over to the next question", async () => {
    const user = await start();
    await user.click(await screen.findByRole("radio", { name: "goes" }));
    await user.click(screen.getByRole("button", { name: /next question/i }));

    // The second item is open-response; its field must start empty.
    const field = await screen.findByLabelText(/your answer/i);
    expect(field).toHaveValue("");
  });

  it("cannot be submitted without an answer", async () => {
    await start();
    expect(
      await screen.findByRole("button", { name: /next question/i }),
    ).toBeDisabled();
  });
});

describe("the result", () => {
  async function finish(result: BenchmarkResult) {
    mocks.answerBenchmarkItem.mockResolvedValue({
      itemKey: "i1",
      correct: true,
      score: 1,
      remaining: 0,
    });
    mocks.completeBenchmark.mockResolvedValue(result);

    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: /start the benchmark/i }),
    );
    await user.click(await screen.findByRole("radio", { name: "goes" }));
    await user.click(screen.getByRole("button", { name: /next question/i }));
  }

  it("reports the score against what was attempted", async () => {
    await finish(HELD);
    expect(await screen.findByText(/2 of 2 unaided/i)).toBeInTheDocument();
  });

  it("says why it counts for more than practice", async () => {
    await finish(HELD);
    expect(
      await screen.findByText(/nothing was available to help/i),
    ).toBeInTheDocument();
  });

  it("reports a fall rather than burying it", async () => {
    // The single most important assertion here. A screen that hid a drop
    // would turn the one measurement in the product into another form of
    // encouragement.
    await finish(FELL);

    expect(
      await screen.findByText(/your estimate went down for 2 skills/i),
    ).toBeInTheDocument();
    expect(screen.getByText("grammar.basic_clause")).toBeInTheDocument();
  });

  it("frames a fall as the benchmark working, not as failure", async () => {
    await finish(FELL);
    expect(
      await screen.findByText(/that is the benchmark doing its job/i),
    ).toBeInTheDocument();
  });

  it("says so when nothing went down", async () => {
    await finish(HELD);
    expect(await screen.findByText(/nothing went down/i)).toBeInTheDocument();
  });
});
