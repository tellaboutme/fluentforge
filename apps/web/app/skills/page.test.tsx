/**
 * The skill map screen.
 *
 * The thing this screen is most likely to get wrong is looking authoritative.
 * A map of dependencies reads as a discovered structure, and these are 119
 * authored arguments — each defensible, none checked against how people
 * actually learn. So the caveats are part of the deliverable, not decoration
 * around it, and the tests treat them that way.
 *
 * The rest is the two refusals carried over from the profile: no level a
 * learner has not earned, and an unmeasured skill reported as unmeasured
 * rather than as weak.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SkillMap } from "@/lib/api";
import { SessionProvider } from "@/lib/session";

import SkillsPage from "./page";

const mocks = vi.hoisted(() => ({ fetchSkillMap: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return { useRouter: () => setup.routerMock };
});

const MAP: SkillMap = {
  nodes: [
    {
      key: "vocab.everyday",
      title: "Everyday vocabulary",
      domain: "vocabulary",
      level: "A2",
      status: "emerging",
      masteryProbability: 0.4,
      confidence: 0.3,
      evidenceCount: 5,
      cefrEstimate: null,
      blocking: ["writing.short_messages"],
      blockedBy: [],
    },
    {
      key: "writing.short_messages",
      title: "Short written messages",
      domain: "written_production",
      level: "A2",
      status: "emerging",
      masteryProbability: 0.35,
      confidence: 0.3,
      evidenceCount: 2,
      cefrEstimate: null,
      blocking: [],
      blockedBy: ["vocab.everyday"],
    },
    {
      key: "reading.complex",
      title: "Complex contemporary prose",
      domain: "reading",
      level: "C1",
      status: "unobserved",
      masteryProbability: 0,
      confidence: 0,
      evidenceCount: 0,
      cefrEstimate: null,
      blocking: [],
      blockedBy: [],
    },
    {
      key: "listening.gist",
      title: "Getting the gist",
      domain: "listening",
      level: "B1",
      status: "supported",
      masteryProbability: 0.82,
      confidence: 0.7,
      evidenceCount: 11,
      cefrEstimate: "B1",
      blocking: [],
      blockedBy: [],
    },
  ],
  edges: [
    {
      source: "vocab.everyday",
      target: "writing.short_messages",
      relation: "prerequisite",
      weight: 0.8,
    },
  ],
  caveats: [
    "The dependencies here are expert judgement, not measurement.",
    "1 of 4 skills have no evidence at all yet.",
  ],
};

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <SkillsPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mocks.fetchSkillMap.mockReset();
  mocks.fetchSkillMap.mockResolvedValue(MAP);
});

describe("the caveats", () => {
  it("shows every one the API sent", async () => {
    renderPage();

    expect(
      await screen.findByText(/expert judgement, not measurement/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/no evidence at all yet/i)).toBeInTheDocument();
  });

  it("puts them before the map rather than after it", async () => {
    // A caveat under a hundred rows is a caveat nobody reads.
    renderPage();

    const caveat = await screen.findByText(
      /expert judgement, not measurement/i,
    );
    const firstSkill = screen.getByText("Everyday vocabulary");

    expect(
      caveat.compareDocumentPosition(firstSkill) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

describe("what the map says", () => {
  it("names the prerequisite that is holding something up", async () => {
    // The answer to "why can I not get anywhere with this?". Naming the
    // skill rather than the key is the whole point.
    renderPage();

    expect(
      await screen.findByText(/held up by Everyday vocabulary/i),
    ).toBeInTheDocument();
  });

  it("says what working on a weak skill would unlock", async () => {
    renderPage();

    expect(
      await screen.findByText(/should help with Short written messages/i),
    ).toBeInTheDocument();
  });

  it("groups skills by domain in words a learner recognises", async () => {
    renderPage();

    expect(await screen.findByText("Writing")).toBeInTheDocument();
    expect(screen.getByText("Vocabulary")).toBeInTheDocument();
  });
});

describe("what it refuses to say", () => {
  it("shows a dash rather than a level the learner has not earned", async () => {
    renderPage();

    await screen.findByText("Everyday vocabulary");
    expect(screen.getAllByText(/level shown: —/i).length).toBeGreaterThan(0);
  });

  it("shows an earned level where there is one", async () => {
    renderPage();

    expect(await screen.findByText(/level shown: B1/i)).toBeInTheDocument();
  });

  it("says an unmeasured skill is unmeasured, not weak", async () => {
    renderPage();

    expect(
      await screen.findByText(/nothing here says you cannot do this/i),
    ).toBeInTheDocument();
  });
});

describe("finding what matters", () => {
  it("can filter to only what is waiting on something", async () => {
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: /waiting on something/i }),
    );

    expect(screen.getByText("Short written messages")).toBeInTheDocument();
    expect(screen.queryByText("Getting the gist")).toBeNull();
  });
});
