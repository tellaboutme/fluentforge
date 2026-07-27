/**
 * Profile dashboard.
 *
 * The load-bearing test here is that no unearned CEFR level ever renders. The
 * API withholds `cefrEstimate` until evidence supports it; a client that
 * substituted a plausible-looking level would defeat the entire mastery model,
 * and that failure would be invisible to the type checker.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Profile } from "@fluentforge/contracts";

import { ApiError } from "@/lib/api";
import { SessionProvider } from "@/lib/session";
import { routerMock } from "@/test/setup";

import DashboardPage from "./page";

const fetchProfileMock = vi.hoisted(() => vi.fn());

// TodayPlan has its own test file; stubbing it keeps these assertions about
// the profile rather than about the plan.
vi.mock("@/components/TodayPlan", () => ({
  TodayPlan: () => null,
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchProfile: fetchProfileMock,
}));

const UNOBSERVED = {
  skillKey: "reading.signs_forms",
  domain: "reading" as const,
  title: "Signs forms",
  cefrEstimate: null,
  masteryProbability: 0,
  confidence: 0,
  evidenceCount: 0,
  distinctContexts: 0,
  lastObservedAt: null,
  status: "unobserved" as const,
};

const EMERGING = {
  ...UNOBSERVED,
  skillKey: "grammar.basic_clause",
  domain: "grammar" as const,
  title: "Basic clause",
  masteryProbability: 0.63,
  confidence: 0.25,
  evidenceCount: 3,
  distinctContexts: 2,
  lastObservedAt: "2026-07-26T10:00:00Z",
  status: "emerging" as const,
};

const INDEPENDENT = {
  ...EMERGING,
  skillKey: "vocabulary.everyday_topics",
  domain: "vocabulary" as const,
  title: "Everyday topics",
  cefrEstimate: "A2" as const,
  masteryProbability: 0.88,
  confidence: 0.8,
  evidenceCount: 7,
  distinctContexts: 4,
  status: "independent" as const,
};

function profile(overrides: Partial<Profile> = {}): Profile {
  return {
    userId: "u1",
    displayName: "Egor",
    targetLevel: "C2",
    dailyMinutes: 40,
    explanationLanguage: "en",
    timezone: "UTC",
    goals: {},
    interests: {},
    curriculumVersion: "0.2.0",
    skills: [UNOBSERVED, EMERGING],
    domainSummaries: [],
    ...overrides,
  };
}

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <DashboardPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  fetchProfileMock.mockReset();
});

describe("honest levels", () => {
  it("shows a dash, never a level, for an unobserved skill", async () => {
    fetchProfileMock.mockResolvedValue(profile());
    renderPage();

    const card = (await screen.findByText("Signs forms")).closest("article");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText("—")).toBeInTheDocument();
    expect(
      within(card as HTMLElement).getByText(/needs evidence/i),
    ).toBeInTheDocument();
  });

  it("shows no level for a skill that is only emerging", async () => {
    fetchProfileMock.mockResolvedValue(profile());
    renderPage();

    const card = (await screen.findByText("Basic clause")).closest("article");
    expect(within(card as HTMLElement).getByText("—")).toBeInTheDocument();
  });

  it("renders no CEFR level anywhere when nothing has been earned", async () => {
    fetchProfileMock.mockResolvedValue(profile());
    const { container } = renderPage();

    await screen.findByText("Signs forms");
    // The learner's *target* is C2 and is allowed; no A1/A2/B1/B2/C1 may appear.
    expect(container.textContent).not.toMatch(/\b(A1|A2|B1|B2|C1)\b/);
  });

  it("does show the level once a skill is independent", async () => {
    fetchProfileMock.mockResolvedValue(
      profile({ skills: [UNOBSERVED, INDEPENDENT] }),
    );
    renderPage();

    const card = (await screen.findByText("Everyday topics")).closest(
      "article",
    );
    expect(within(card as HTMLElement).getByText("A2")).toBeInTheDocument();
    expect(
      within(card as HTMLElement).getByText(/independent/i),
    ).toBeInTheDocument();
  });

  it("gives screen readers the same message as sighted users", async () => {
    fetchProfileMock.mockResolvedValue(profile());
    renderPage();

    await screen.findByText("Signs forms");
    expect(screen.getAllByLabelText("No level yet").length).toBeGreaterThan(0);
  });

  it("never presents confidence as a false-precision percentage", async () => {
    fetchProfileMock.mockResolvedValue(profile());
    const { container } = renderPage();

    await screen.findByText("Signs forms");
    expect(container.textContent).not.toMatch(/\d+\s?%/);
  });
});

describe("states", () => {
  it("shows a loading state first", () => {
    fetchProfileMock.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(
      /loading your profile/i,
    );
  });

  it("explains the empty case rather than showing bare zeroes", async () => {
    // A learner who has not started: no skill has any evidence.
    fetchProfileMock.mockResolvedValue(profile({ skills: [UNOBSERVED] }));
    renderPage();

    expect(
      await screen.findByText(/nothing measured yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /start the diagnostic/i }),
    ).toHaveAttribute("href", "/diagnostic");
  });

  it("summarises progress once there is evidence", async () => {
    fetchProfileMock.mockResolvedValue(
      profile({ skills: [UNOBSERVED, INDEPENDENT] }),
    );
    renderPage();

    expect(await screen.findByText(/what we know so far/i)).toBeInTheDocument();
    expect(
      screen.getByText(/1 of 2 skills have evidence/i),
    ).toBeInTheDocument();
  });

  it("groups skills under a heading per domain", async () => {
    fetchProfileMock.mockResolvedValue(profile());
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Reading" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Grammar" }),
    ).toBeInTheDocument();
  });

  it("retries after a transient failure", async () => {
    const user = userEvent.setup();
    fetchProfileMock
      .mockRejectedValueOnce(
        new ApiError(503, "curriculum_not_loaded", "Not loaded."),
      )
      .mockResolvedValue(profile());
    renderPage();

    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByText("Signs forms")).toBeInTheDocument();
  });
});

describe("session", () => {
  it("redirects a signed-out visitor to sign in", async () => {
    window.sessionStorage.clear();
    render(
      <SessionProvider>
        <DashboardPage />
      </SessionProvider>,
    );

    await waitFor(() =>
      expect(routerMock.replace).toHaveBeenCalledWith("/sign-in"),
    );
  });

  it("clears the stored token on sign out", async () => {
    const user = userEvent.setup();
    fetchProfileMock.mockResolvedValue(profile());
    renderPage();

    await screen.findByText("Signs forms");
    await user.click(screen.getByRole("button", { name: /sign out/i }));

    expect(window.sessionStorage.getItem("fluentforge.session")).toBeNull();
  });
});
