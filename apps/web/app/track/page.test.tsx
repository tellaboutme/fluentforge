/**
 * Choosing a track.
 *
 * The failure this screen has to avoid is presenting a track as a name with
 * unstated consequences. That is the opaque personalisation
 * `docs/ADAPTIVE_ENGINE.md` refuses everywhere else, and the learner is the
 * only person who can tell us the choice is wrong for them — which they
 * cannot do if they are picking between four words.
 *
 * The second is reassurance that is actually true: a track never removes
 * anything, and switching resets nothing. Both are on the screen because
 * someone deciding will assume the opposite.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Profile } from "@fluentforge/contracts";

import type { TrackOptions } from "@/lib/api";
import { SessionProvider } from "@/lib/session";

import TrackPage from "./page";

const mocks = vi.hoisted(() => ({
  fetchTracks: vi.fn(),
  fetchProfile: vi.fn(),
  chooseTrack: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return { useRouter: () => setup.routerMock };
});

const OPTIONS: TrackOptions = {
  tracks: [
    {
      key: "academic",
      name: "Academic English",
      levels: ["B1", "B2", "C1", "C2"],
      scenarios: ["summarise_source", "compare_sources", "build_argument"],
      priorityDomains: ["reading", "written_production", "mediation"],
    },
    {
      key: "general",
      name: "General English",
      levels: ["A1", "A2", "B1", "B2", "C1", "C2"],
      scenarios: [],
      priorityDomains: ["listening", "reading"],
    },
  ],
  caveats: [
    "A track changes what gets offered first. It never removes anything.",
    "You can change track whenever you like. Nothing you have already shown is lost.",
  ],
};

const PROFILE = {
  userId: "u1",
  displayName: "Egor",
  targetLevel: "C2",
  dailyMinutes: 40,
  explanationLanguage: "en",
  timezone: "UTC",
  goals: {},
  interests: {},
  trackKey: "general",
  trackName: "General English",
  curriculumVersion: "0.6.0",
  skills: [],
  domainSummaries: [],
} as unknown as Profile;

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <TrackPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mocks.fetchTracks.mockReset();
  mocks.fetchProfile.mockReset();
  mocks.chooseTrack.mockReset();
  mocks.fetchTracks.mockResolvedValue(OPTIONS);
  mocks.fetchProfile.mockResolvedValue(PROFILE);
  mocks.chooseTrack.mockResolvedValue({
    ...PROFILE,
    trackKey: "academic",
    trackName: "Academic English",
  });
});

describe("what a track means", () => {
  it("says what choosing it actually does, not only its name", async () => {
    // The point. A name with unstated consequences cannot be disagreed with.
    renderPage();

    expect(
      await screen.findByText(/puts more reading, writing, explaining/i),
    ).toBeInTheDocument();
  });

  it("names the situations a scenario-led track is for", async () => {
    renderPage();

    expect(await screen.findByText(/summarise source/i)).toBeInTheDocument();
  });

  it("says plainly that the general track is for no particular situation", async () => {
    // Inventing a purpose for someone who has not chosen one would be worse
    // than admitting there is none.
    renderPage();

    expect(
      await screen.findByText(/for no particular situation/i),
    ).toBeInTheDocument();
  });

  it("shows the caveats above the options", async () => {
    renderPage();

    const caveat = await screen.findByText(/never removes anything/i);
    const firstTrack = screen.getByText("Academic English");

    expect(
      caveat.compareDocumentPosition(firstTrack) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

describe("choosing", () => {
  it("marks the one the learner is on and offers no switch to it", async () => {
    renderPage();

    expect(await screen.findByText("Your track")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /switch to general english/i }),
    ).toBeNull();
  });

  it("switches, and the marker moves", async () => {
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", {
        name: /switch to academic english/i,
      }),
    );

    expect(mocks.chooseTrack).toHaveBeenCalledWith("test-token", "academic");
    expect(
      await screen.findByRole("button", { name: /switch to general english/i }),
    ).toBeInTheDocument();
  });
});

describe("a withdrawn track", () => {
  it("says so rather than showing the stored key as a name", async () => {
    // Curriculum is versioned and tracks can be retired. The learner's work
    // is untouched and the screen has to say that.
    mocks.fetchProfile.mockResolvedValue({
      ...PROFILE,
      trackKey: "retired-track",
      trackName: null,
    });

    renderPage();

    expect(
      await screen.findByText(/no longer part of the curriculum/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("retired-track")).toBeNull();
  });
});
