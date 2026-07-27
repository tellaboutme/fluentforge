/**
 * The reflection screen.
 *
 * Two things to guard, pulling in opposite directions.
 *
 * The material must be real: a page that asked "how do you feel your
 * learning is going?" would produce nothing worth reading, and a learner
 * asked it twice stops answering.
 *
 * And nothing may look like it was judged. This is the one place in the
 * product where a learner writes and nothing checks it, and they have to be
 * able to trust that — a screen that implied otherwise would teach them to
 * write reflections that pass checks.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReflectionPrompt } from "@/lib/api";
import { SessionProvider } from "@/lib/session";

import ReflectPage from "./page";

const mocks = vi.hoisted(() => ({
  fetchReflectionPrompt: vi.fn(),
  saveReflection: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return { useRouter: () => setup.routerMock };
});

const RICH: ReflectionPrompt = {
  recurringErrors: [
    {
      code: "grammar.word_order.question",
      label: "Word order in questions",
      description: "Questions built in statement order.",
      occurrences: 4,
      blocksMeaning: true,
    },
    {
      code: "mechanics.spelling.common",
      label: "Spelling",
      description: "Frequent misspellings.",
      occurrences: 2,
      blocksMeaning: false,
    },
  ],
  untouchedSkills: ["listening.routine_messages"],
  unjudgedCount: 3,
  previousNote: "Last week I said I would read more.",
};

const EMPTY: ReflectionPrompt = {
  recurringErrors: [],
  untouchedSkills: [],
  unjudgedCount: 0,
  previousNote: null,
};

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <ReflectPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mocks.fetchReflectionPrompt.mockReset();
  mocks.saveReflection.mockReset();
  mocks.fetchReflectionPrompt.mockResolvedValue(RICH);
  mocks.saveReflection.mockResolvedValue({
    saved: true,
    scored: false,
    evidenceRecorded: false,
  });
});

describe("the material", () => {
  it("shows what actually recurred, by its readable label", async () => {
    // A raw taxonomy code on screen is a machine identifier leaking into
    // the interface.
    renderPage();

    expect(
      await screen.findByText(/word order in questions/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("grammar.word_order.question")).toBeNull();
  });

  it("marks the errors that get in the way of being understood", async () => {
    renderPage();
    expect(await screen.findByText(/gets in the way/i)).toBeInTheDocument();
  });

  it("says how often each one happened", async () => {
    // "You keep doing this" is an accusation; "four times" is a fact.
    renderPage();
    expect(await screen.findByText(/4 times/i)).toBeInTheDocument();
  });

  it("names what has not been looked at lately", async () => {
    renderPage();
    expect(
      await screen.findByText("listening.routine_messages"),
    ).toBeInTheDocument();
  });

  it("admits how much of the learner's work nothing judged", async () => {
    // The product's own blind spot. Someone reflecting on their progress
    // should not read silence as approval.
    renderPage();
    expect(await screen.findByText(/went unjudged/i)).toBeInTheDocument();
    expect(screen.getByText(/limit of this app/i)).toBeInTheDocument();
  });

  it("shows what the learner said last time", async () => {
    // Reflection that never refers back is a diary nobody rereads.
    renderPage();
    expect(
      await screen.findByText(/i said i would read more/i),
    ).toBeInTheDocument();
  });

  it("invents nothing when there is nothing to say", async () => {
    mocks.fetchReflectionPrompt.mockResolvedValue(EMPTY);
    renderPage();

    expect(
      await screen.findByText(
        /nothing has recurred and nothing has gone stale/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/that is a fine answer/i)).toBeInTheDocument();
  });
});

describe("writing one", () => {
  it("says plainly that nothing is checked or counted", async () => {
    // The most important assertion here.
    renderPage();
    expect(
      await screen.findByText(
        /nothing here is checked, corrected, or counted/i,
      ),
    ).toBeInTheDocument();
  });

  it("says there is no minimum", async () => {
    renderPage();
    expect(await screen.findByText(/no minimum/i)).toBeInTheDocument();
  });

  it("can be saved empty", async () => {
    // Refusing would make the learner perform reflection.
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /save this/i }));
    expect(mocks.saveReflection).toHaveBeenCalledWith("test-token", "");
  });

  it("sends what was written", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByLabelText(/what do you make of it/i),
      "Questions are the problem.",
    );
    await user.click(screen.getByRole("button", { name: /save this/i }));

    expect(mocks.saveReflection).toHaveBeenCalledWith(
      "test-token",
      "Questions are the problem.",
    );
  });

  it("confirms afterwards that the profile is unchanged", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /save this/i }));
    expect(
      await screen.findByText(/your profile is unchanged/i),
    ).toBeInTheDocument();
  });

  it("offers no score, mark, or feedback after saving", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /save this/i }));
    await screen.findByText(/your profile is unchanged/i);

    expect(screen.queryByText(/well done/i)).toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
  });
});
