/**
 * The error log screen.
 *
 * What matters here is what the screen refuses to do. It has a list of the
 * learner's mistakes, which is the easiest thing in the product to render
 * discouragingly, and three specific ways to get it wrong:
 *
 * - showing the machine code, which reads as a diagnosis and cannot be acted
 *   on;
 * - rendering a missing remedy as a dash, which collapses three quite
 *   different gaps into one shrug;
 * - calling every remedy "practise this", when a comprehension error opens
 *   another text and nothing is being explained at all.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ErrorLog } from "@/lib/api";
import { SessionProvider } from "@/lib/session";

import ErrorsPage from "./page";

const mocks = vi.hoisted(() => ({ fetchErrorLog: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return { useRouter: () => setup.routerMock };
});

const RICH: ErrorLog = {
  items: [
    {
      code: "grammar.word_order.question",
      label: "Word order in questions",
      description: "Questions built in statement order.",
      occurrences: 4,
      firstSeenAt: "2026-07-01T09:00:00Z",
      lastSeenAt: "2026-07-20T09:00:00Z",
      blocksMeaning: true,
      priority: 0.8,
      scheduled: true,
      remedyKey: "study:questions.a2",
      remedyTitle: "Asking questions",
      remedyType: "study_task",
      noRemedyReason: null,
    },
    {
      code: "reading.comprehension.inference",
      label: "Reading what a text implies",
      description: "What the text implies without stating it, missed.",
      occurrences: 3,
      firstSeenAt: "2026-07-02T09:00:00Z",
      lastSeenAt: "2026-07-21T09:00:00Z",
      blocksMeaning: true,
      priority: 0.7,
      scheduled: true,
      remedyKey: "read:cafe.b1",
      remedyTitle: "Under new management",
      remedyType: "reading_task",
      noRemedyReason: null,
    },
    {
      code: "pronunciation.segment.contrast",
      label: "Sounds that change meaning",
      description: "Two sounds merged where the contrast carries meaning.",
      occurrences: 2,
      firstSeenAt: "2026-07-03T09:00:00Z",
      lastSeenAt: "2026-07-22T09:00:00Z",
      blocksMeaning: true,
      priority: 0.6,
      scheduled: false,
      remedyKey: null,
      remedyTitle: null,
      remedyType: null,
      noRemedyReason: "needs_speech",
    },
    {
      code: "item.grammar.past_future_basic",
      label: "Something in grammar.past_future_basic",
      description: "Difficulty with: an item.",
      occurrences: 1,
      firstSeenAt: "2026-07-04T09:00:00Z",
      lastSeenAt: "2026-07-23T09:00:00Z",
      blocksMeaning: false,
      priority: 0.2,
      scheduled: false,
      remedyKey: null,
      remedyTitle: null,
      remedyType: null,
      noRemedyReason: "no_feature",
    },
  ],
  withoutRemedy: 2,
};

const EMPTY: ErrorLog = { items: [], withoutRemedy: 0 };

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <ErrorsPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mocks.fetchErrorLog.mockReset();
  mocks.fetchErrorLog.mockResolvedValue(RICH);
});

describe("what is shown", () => {
  it("uses the readable label and never the code", async () => {
    renderPage();

    expect(
      await screen.findByText(/word order in questions/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("grammar.word_order.question")).toBeNull();
  });

  it("says how often, rather than that the learner keeps doing it", async () => {
    // "You keep doing this" is an accusation; "seen 4 times" is a fact.
    renderPage();
    expect(await screen.findByText(/seen 4 times/i)).toBeInTheDocument();
  });

  it("marks the errors that change the meaning", async () => {
    renderPage();
    expect(
      (await screen.findAllByText(/changes the meaning/i)).length,
    ).toBeGreaterThan(0);
  });

  it("says when something is recorded but not being drilled yet", async () => {
    // Otherwise a learner sees an error that never reaches their plan and
    // cannot tell whether that is deliberate.
    renderPage();
    expect(
      (await screen.findAllByText(/not being drilled yet/i)).length,
    ).toBeGreaterThan(0);
  });
});

describe("what to do about it", () => {
  it("offers a study unit for a production error", async () => {
    renderPage();
    expect(
      await screen.findByText(/practise: asking questions/i),
    ).toBeInTheDocument();
  });

  it("does not call a reading remedy practice", async () => {
    // Nothing is being explained. The learner is meeting the same kind of
    // question on a passage they have not seen, and saying "practise this"
    // would misdescribe it.
    renderPage();

    expect(await screen.findByText(/read another one/i)).toBeInTheDocument();
  });

  it("links the remedy to the activity that opens it", async () => {
    renderPage();

    const link = await screen.findByText(/read another one/i);
    expect(link.closest("a")).toHaveAttribute(
      "href",
      "/activity/read%3Acafe.b1",
    );
  });
});

describe("when there is nothing to open", () => {
  it("says a sound contrast needs something this product cannot do", async () => {
    // The load-bearing distinction. "Not written yet" and "needs an audio
    // pipeline" are different promises, and a dash would collapse them.
    renderPage();

    expect(
      await screen.findByText(/cannot teach a sound/i),
    ).toBeInTheDocument();
  });

  it("explains a legacy code as imprecise rather than as a gap", async () => {
    renderPage();

    expect(
      await screen.findByText(/before we could name mistakes precisely/i),
    ).toBeInTheDocument();
  });

  it("counts them, so the learner does not have to", async () => {
    renderPage();

    expect(
      await screen.findByText(/2 of these have nothing to open yet/i),
    ).toBeInTheDocument();
  });
});

describe("an empty log", () => {
  it("says we have not seen enough, not that the learner is perfect", async () => {
    mocks.fetchErrorLog.mockResolvedValue(EMPTY);
    renderPage();

    expect(
      await screen.findByText(/not that you are making no mistakes/i),
    ).toBeInTheDocument();
  });
});
