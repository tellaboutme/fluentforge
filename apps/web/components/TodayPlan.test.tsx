/**
 * Today's plan.
 *
 * The load-bearing assertion: every item shows *why* it is there.
 * `docs/ADAPTIVE_ENGINE.md` requires the UI to answer "why is this in today's
 * plan?", and a learner who cannot see the reasoning cannot disagree with it.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type DailyPlan } from "@/lib/api";

import { TodayPlan } from "./TodayPlan";

const fetchTodayPlanMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchTodayPlan: fetchTodayPlanMock,
}));

function planItem(overrides: Partial<DailyPlan["items"][number]> = {}) {
  return {
    sequence: 0,
    activityKey: "skill:reading.signs_forms",
    activityType: "skill_practice",
    estimatedMinutes: 10,
    title: "Signs and forms",
    kind: "input",
    skillKey: "reading.signs_forms",
    domain: "reading",
    reasonCodes: ["EXPECTED_GAIN"],
    explanation: "Right at the edge of what you can already do.",
    priority: 1.47,
    components: { expected_gain: 0.7, uncertainty: 0.58 },
    ...overrides,
  };
}

function plan(overrides: Partial<DailyPlan> = {}): DailyPlan {
  return {
    id: "p1",
    planDate: "2026-07-27",
    requestedMinutes: 40,
    totalMinutes: 32,
    status: "active",
    engineVersion: "0.1.0",
    hasReceptive: true,
    hasProductive: true,
    unmetConstraints: [],
    items: [
      planItem(),
      planItem({
        sequence: 1,
        activityKey: "skill:writing.linked_messages",
        title: "Linked messages",
        kind: "output",
        reasonCodes: ["UNCERTAINTY"],
        explanation: "We do not have much evidence here yet.",
        estimatedMinutes: 10,
      }),
    ],
    ...overrides,
  };
}

beforeEach(() => {
  fetchTodayPlanMock.mockReset();
});

describe("explainability", () => {
  it("shows a reason for every item", async () => {
    fetchTodayPlanMock.mockResolvedValue(plan());
    render(<TodayPlan token="t" />);

    await screen.findByText("Signs and forms");
    expect(
      screen.getByText(/right at the edge of what you can already do/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/we do not have much evidence here yet/i),
    ).toBeInTheDocument();
  });

  it("never leaves an item unexplained", async () => {
    fetchTodayPlanMock.mockResolvedValue(plan());
    render(<TodayPlan token="t" />);

    await screen.findByText("Signs and forms");
    const rows = screen.getAllByRole("listitem");
    for (const row of rows) {
      expect(within(row).getByText(/\./)).toBeInTheDocument();
    }
  });

  it("says what kind of work each item is", async () => {
    fetchTodayPlanMock.mockResolvedValue(plan());
    render(<TodayPlan token="t" />);

    await screen.findByText("Signs and forms");
    expect(screen.getByText("Read or listen")).toBeInTheDocument();
    expect(screen.getByText("Write")).toBeInTheDocument();
  });

  it("states the time budget rather than implying an open-ended session", async () => {
    fetchTodayPlanMock.mockResolvedValue(plan());
    render(<TodayPlan token="t" />);

    expect(await screen.findByText(/32 of 40 min/i)).toBeInTheDocument();
  });

  it("makes clear the plan comes from evidence, not attendance", async () => {
    fetchTodayPlanMock.mockResolvedValue(plan());
    render(<TodayPlan token="t" />);

    await screen.findByText("Signs and forms");
    expect(
      screen.getByText(/not from how long you have been here/i),
    ).toBeInTheDocument();
  });
});

describe("states", () => {
  it("shows a loading state first", () => {
    fetchTodayPlanMock.mockReturnValue(new Promise(() => {}));
    render(<TodayPlan token="t" />);
    expect(screen.getByRole("status")).toHaveTextContent(
      /building today's plan/i,
    );
  });

  it("explains an empty plan instead of showing a bare list", async () => {
    fetchTodayPlanMock.mockResolvedValue(plan({ items: [] }));
    render(<TodayPlan token="t" />);

    expect(await screen.findByText(/no plan yet/i)).toBeInTheDocument();
  });

  it("surfaces constraints the planner could not meet", async () => {
    fetchTodayPlanMock.mockResolvedValue(
      plan({
        hasProductive: false,
        unmetConstraints: ["no productive activity was available"],
      }),
    );
    render(<TodayPlan token="t" />);

    expect(
      await screen.findByText(/thinner than it should be/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no productive activity was available/i),
    ).toBeInTheDocument();
  });

  it("recovers from a transient failure", async () => {
    const user = userEvent.setup();
    fetchTodayPlanMock
      .mockRejectedValueOnce(
        new ApiError(503, "curriculum_not_loaded", "Not loaded."),
      )
      .mockResolvedValue(plan());
    render(<TodayPlan token="t" />);

    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByText("Signs and forms")).toBeInTheDocument();
  });
});

describe("structure", () => {
  it("presents the plan as an ordered list", async () => {
    fetchTodayPlanMock.mockResolvedValue(plan());
    render(<TodayPlan token="t" />);

    await screen.findByText("Signs and forms");
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("gives the section an accessible heading", async () => {
    fetchTodayPlanMock.mockResolvedValue(plan());
    render(<TodayPlan token="t" />);

    expect(
      await screen.findByRole("heading", {
        name: /from understanding to using/i,
      }),
    ).toBeInTheDocument();
  });

  it("describes a plan with no productive work honestly", async () => {
    fetchTodayPlanMock.mockResolvedValue(plan({ hasProductive: false }));
    render(<TodayPlan token="t" />);

    expect(
      await screen.findByRole("heading", { name: /taking things in today/i }),
    ).toBeInTheDocument();
  });
});

describe("opening an item", () => {
  it("links every kind the activity player can open", async () => {
    fetchTodayPlanMock.mockResolvedValue(
      plan({
        items: [
          planItem({
            activityKey: "read:text.a1.noticeboard",
            title: "Noticeboard",
          }),
          planItem({
            sequence: 1,
            activityKey: "study:study.a2.past_simple",
            title: "Finished time",
            kind: "study",
          }),
          planItem({
            sequence: 2,
            activityKey: "write:write.a2.late_email",
            title: "Running late",
            kind: "output",
          }),
        ],
      }),
    );
    render(<TodayPlan token="t" />);

    expect(
      await screen.findByRole("link", { name: "Noticeboard" }),
    ).toHaveAttribute("href", "/activity/read%3Atext.a1.noticeboard");
    expect(screen.getByRole("link", { name: "Finished time" })).toHaveAttribute(
      "href",
      "/activity/study%3Astudy.a2.past_simple",
    );
    expect(screen.getByRole("link", { name: "Running late" })).toHaveAttribute(
      "href",
      "/activity/write%3Awrite.a2.late_email",
    );
  });

  it("leaves a kind with no activity behind it unlinked", async () => {
    // A link that goes nowhere is worse than plain text.
    fetchTodayPlanMock.mockResolvedValue(
      plan({
        items: [
          planItem({
            activityKey: "skill:speaking.basic_identity",
            title: "Introducing yourself",
            kind: "speaking",
          }),
        ],
      }),
    );
    render(<TodayPlan token="t" />);

    await screen.findByText("Introducing yourself");
    expect(
      screen.queryByRole("link", { name: "Introducing yourself" }),
    ).not.toBeInTheDocument();
  });
});
