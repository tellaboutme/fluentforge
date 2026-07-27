/**
 * Activity player: the mediation kind.
 *
 * Several sources in, one account out, for a reader who has not seen them.
 * Three things this screen does that no other kind does, and each has tests:
 *
 * - The sources stay available while the account is written. Mediation is
 *   not a memory test, and hiding them would make it one.
 * - The verbatim limit is stated before the learner writes. Being told
 *   afterwards that eleven consecutive words matched a source reads as an
 *   accusation; being told in advance is a rule.
 * - The result never claims the sources were reported accurately. Coverage
 *   is inferred from names and figures, so it shows a source was mentioned,
 *   not that it was conveyed correctly — and the screen says so.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MediationActivity, MediationResult } from "@/lib/api";
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
    useParams: () => ({ key: "mediate:mediate.b1.moving_the_meeting" }),
  };
});

const ACTIVITY: MediationActivity = {
  activityKey: "mediate:mediate.b1.moving_the_meeting",
  activityType: "mediation_task",
  title: "Two messages, one answer",
  cefrLevel: "B1",
  skillKey: "mediation.basic_summary",
  estimatedMinutes: 18,
  brief:
    "Two people have written to you about Thursday.\n\nWrite one message for your colleague Dan, who has read neither.",
  sources: [
    {
      key: "rosa",
      title: "Message from Rosa",
      kind: "email",
      text: "Could we move the meeting to nine in the morning?",
      wordCount: 10,
    },
    {
      key: "idris",
      title: "Message from Idris",
      kind: "email",
      text: "I am at the warehouse until lunchtime every Thursday.",
      wordCount: 9,
    },
  ],
  guidance: ["Say who wants what.", "Name the disagreement openly."],
  minWords: 90,
  maxWords: 300,
  minSentences: 5,
  requiredElements: ["decide"],
  maxVerbatimWords: 7,
};

const CLEAN: MediationResult = {
  activityType: "mediation_task",
  activityKey: ACTIVITY.activityKey,
  score: 1,
  explanation:
    "These are automatic checks on length, structure, source coverage and whether you restated rather than copied.",
  checks: [
    { code: "length", passed: true, message: "120 words — a good length." },
    { code: "sources", passed: true, message: "You drew on every source." },
    {
      code: "restated",
      passed: true,
      message:
        "The longest run you share with a source is 4 words — this is your account, not a copy of theirs.",
    },
  ],
  wordCount: 120,
  usedSources: ["rosa", "idris"],
  unusedSources: [],
  longestCopiedRun: 4,
  copiedFrom: null,
  evidenceRecorded: true,
  provisional: true,
  rubric: [],
  priorityFeedback: [],
  evaluatedBy: null,
};

const MISSED_A_SOURCE: MediationResult = {
  ...CLEAN,
  score: 0.66,
  usedSources: ["rosa"],
  unusedSources: ["idris"],
  checks: [
    { code: "length", passed: true, message: "120 words — a good length." },
    {
      code: "sources",
      passed: false,
      message:
        "These sources do not seem to appear in your account: Message from Idris",
    },
  ],
};

const COPIED: MediationResult = {
  ...CLEAN,
  score: 0.66,
  longestCopiedRun: 11,
  copiedFrom: "rosa",
  checks: [
    { code: "length", passed: true, message: "120 words — a good length." },
    {
      code: "restated",
      passed: false,
      message:
        "11 consecutive words match 'Message from Rosa' exactly. Mediation means restating, not transcribing. Quote it and mark the quotation, or say it in your own words.",
    },
  ],
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
  mocks.completeActivity.mockResolvedValue(CLEAN);
});

describe("before writing", () => {
  it("gives the brief, which names who the account is for", async () => {
    // Mediation without an audience is paraphrase.
    renderPage();
    expect(
      await screen.findByText(/for your colleague dan/i),
    ).toBeInTheDocument();
  });

  it("lists every source with its kind", async () => {
    // Reconciling an email against a chart is a different task from
    // reconciling two articles, so the kind is not decoration.
    renderPage();

    await screen.findByRole("heading", { name: /two messages/i });
    expect(
      screen.getByRole("button", { name: /message from rosa/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /message from idris/i }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("email").length).toBe(2);
  });

  it("states the verbatim limit before the learner writes", async () => {
    // A rule you learn by breaking it is a trap.
    renderPage();
    expect(
      await screen.findByText(/longer than 7 words copied/i),
    ).toBeInTheDocument();
  });

  it("says marked quotations are allowed", async () => {
    // Otherwise the rule reads as "never touch the sources", which would
    // teach the learner to stop attributing.
    renderPage();
    expect(
      await screen.findByText(/mark it as a quotation/i),
    ).toBeInTheDocument();
  });

  it("shows a source's text when it is opened", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: /message from idris/i }),
    );
    expect(screen.getByText(/at the warehouse until lunchtime/i)).toBeVisible();
  });

  it("cannot be submitted empty", async () => {
    renderPage();
    expect(
      await screen.findByRole("button", { name: /check my account/i }),
    ).toBeDisabled();
  });

  it("counts words towards the target as the learner types", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText(/your account/i), "One two.");
    expect(await screen.findByText(/2 words/i)).toBeInTheDocument();
  });
});

describe("while writing", () => {
  it("keeps a source readable, because this is not a memory test", async () => {
    // The reading lab keeps its text visible for the same reason. Hiding
    // the sources here would turn mediation into recall.
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByLabelText(/your account/i),
      "Rosa wants the morning.",
    );
    expect(screen.getByText(/nine in the morning/i)).toBeVisible();
  });

  it("sends the account as text", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByLabelText(/your account/i),
      "They disagree about Thursday.",
    );
    await user.click(screen.getByRole("button", { name: /check my account/i }));

    const [, , submission] = mocks.completeActivity.mock.calls[0];
    expect(submission.text).toContain("They disagree");
  });
});

describe("after submitting", () => {
  async function submit(result: MediationResult = CLEAN) {
    mocks.completeActivity.mockResolvedValue(result);
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByLabelText(/your account/i),
      "They disagree about Thursday and someone has to decide.",
    );
    await user.click(screen.getByRole("button", { name: /check my account/i }));
  }

  it("never claims the sources were reported accurately", async () => {
    // The most important assertion here. A learner who believed this had
    // checked their fidelity to the sources would be misled about the one
    // thing the task is actually for.
    await submit();

    expect(
      await screen.findByText(/nothing here has judged whether you reported/i),
    ).toBeInTheDocument();
  });

  it("explains why fidelity is out of reach", async () => {
    await submit();

    expect(
      await screen.findByText(/name a figure and still describe it wrongly/i),
    ).toBeInTheDocument();
  });

  it("shows the checks it did make", async () => {
    await submit();
    expect(
      await screen.findByText(/you drew on every source/i),
    ).toBeInTheDocument();
  });

  it("names a source that seems to be missing, by title", async () => {
    // A key like "idris" means nothing to the learner. It appears twice —
    // once in the check, once in the caveat below it — which is the point:
    // the title is what is shown, never the key.
    await submit(MISSED_A_SOURCE);

    const notice = await screen.findByRole("status");
    expect(
      within(notice).getAllByText(/message from idris/i).length,
    ).toBeGreaterThan(0);
    expect(within(notice).queryByText(/\bidris\b(?!\s)/)).toBeNull();
  });

  it("presents missing coverage as a suggestion, not a verdict", async () => {
    // It is inferred from names and figures. A learner who covered a source
    // without naming anything in it did nothing wrong.
    await submit(MISSED_A_SOURCE);

    expect(await screen.findByText(/it can be wrong/i)).toBeInTheDocument();
    expect(screen.getByText(/rather than a mark/i)).toBeInTheDocument();
  });

  it("tells a learner who copied what to do instead", async () => {
    await submit(COPIED);

    const message = await screen.findByText(/11 consecutive words match/i);
    expect(message).toBeInTheDocument();
    expect(message.textContent?.toLowerCase()).toContain("own words");
  });

  it("reports the shared run even when nothing was copied", async () => {
    // So the learner can see they were nowhere near the limit, rather than
    // only hearing about it the moment they cross it.
    await submit();

    expect(
      await screen.findByText(
        /longest run you share with a source is 4 words/i,
      ),
    ).toBeInTheDocument();
  });

  it("says plainly when nothing was recorded, without blame", async () => {
    await submit({ ...CLEAN, evidenceRecorded: false });

    expect(
      await screen.findByText(/has not changed your profile/i),
    ).toBeInTheDocument();
  });
});
