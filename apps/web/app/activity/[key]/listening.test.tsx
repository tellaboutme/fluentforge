/**
 * Activity player: the listening kind.
 *
 * This kind inverts the reading rule. Reading keeps its text on screen because
 * hiding it would turn comprehension into a memory test; listening hides its
 * transcript because showing it would turn listening into reading.
 *
 * The transcript is still one click away, and must be: a learner who cannot
 * use audio has no other route through the exercise. What keeps the profile
 * honest is not secrecy but disclosure — taking that click is reported to the
 * API, which then records no listening evidence at all and says why.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ListeningActivity, ListeningResult } from "@/lib/api";
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
    useParams: () => ({ key: "listen:listen.a2.voicemail" }),
  };
});

const ACTIVITY: ListeningActivity = {
  activityKey: "listen:listen.a2.voicemail",
  activityType: "listening_task",
  title: "A voicemail from a friend",
  cefrLevel: "A2",
  skillKey: "listening.routine_messages",
  estimatedMinutes: 5,
  setting: "A message left on your phone by a friend, Nadia.",
  transcript: "Hi, it's Nadia. I can't make lunch on Saturday after all.",
  wordCount: 58,
  speechRate: 0.85,
  audio: null,
  questions: [
    {
      key: "gist",
      questionType: "gist",
      prompt: "Why is Nadia calling?",
      options: ["To change the day of their meeting.", "To book a table."],
    },
    {
      key: "detail",
      questionType: "detail",
      prompt: "Who is Nadia meeting on Saturday?",
      options: ["Her sister", "Nobody"],
    },
  ],
};

const HEARD: ListeningResult = {
  activityType: "listening_task",
  activityKey: ACTIVITY.activityKey,
  score: 1,
  correctCount: 2,
  total: 2,
  explanation: "You caught all of it, and quickly.",
  results: [
    {
      key: "gist",
      questionType: "gist",
      correct: true,
      expected: "To change the day of their meeting.",
    },
    {
      key: "detail",
      questionType: "detail",
      correct: true,
      expected: "Her sister",
    },
  ],
  evidenceRecorded: true,
  plays: 1,
  independence: 1,
  usedTranscript: false,
};

const READ: ListeningResult = {
  ...HEARD,
  explanation:
    "You read the transcript, so this tells us about your reading rather than your listening.",
  evidenceRecorded: false,
  plays: 0,
  usedTranscript: true,
};

/** A speech synthesis stub that finishes the moment it is asked to speak. */
function stubSpeech() {
  const speak = vi.fn((utterance: { onend?: (() => void) | null }) => {
    utterance.onend?.();
  });
  const cancel = vi.fn();

  class FakeUtterance {
    rate = 1;
    lang = "";
    onend: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(public text: string) {}
  }

  vi.stubGlobal("speechSynthesis", { speak, cancel });
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  return { speak, cancel };
}

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
  mocks.completeActivity.mockResolvedValue(HEARD);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("before listening", () => {
  it("sets the scene, because real listening always has context", async () => {
    stubSpeech();
    renderPage();
    expect(
      await screen.findByText(/a message left on your phone/i),
    ).toBeInTheDocument();
  });

  it("hides the transcript", async () => {
    // The whole point: a visible transcript makes this a reading exercise.
    stubSpeech();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    expect(screen.queryByText(/it's nadia/i)).not.toBeInTheDocument();
  });

  it("asks no questions until the clip has been heard", async () => {
    // Answering blind would measure guessing.
    stubSpeech();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
  });

  it("says the clip can be replayed freely", async () => {
    stubSpeech();
    renderPage();
    expect(
      await screen.findByText(/replay it as often as you need/i),
    ).toBeInTheDocument();
  });
});

describe("playing", () => {
  it("speaks the transcript at the clip's own pace", async () => {
    const { speak } = stubSpeech();
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    await user.click(screen.getByRole("button", { name: /play the clip/i }));

    expect(speak).toHaveBeenCalledTimes(1);
    const utterance = speak.mock.calls[0][0] as unknown as {
      text: string;
      rate: number;
    };
    expect(utterance.text).toContain("Nadia");
    expect(utterance.rate).toBe(ACTIVITY.speechRate);
  });

  it("reveals the questions once it has been played", async () => {
    stubSpeech();
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    await user.click(screen.getByRole("button", { name: /play the clip/i }));

    expect(screen.getAllByRole("radio").length).toBeGreaterThan(0);
    // Still no transcript: playing it does not reveal the words.
    expect(screen.queryByText(/it's nadia/i)).not.toBeInTheDocument();
  });

  it("counts replays and reports them", async () => {
    stubSpeech();
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    await user.click(screen.getByRole("button", { name: /play the clip/i }));
    await user.click(screen.getByRole("button", { name: /play it again/i }));

    expect(screen.getByText(/played 2 times/i)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /change the day/i }));
    await user.click(screen.getByRole("radio", { name: "Her sister" }));
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    expect(mocks.completeActivity).toHaveBeenCalledWith(
      "test-token",
      "listen:listen.a2.voicemail",
      {
        answers: {
          gist: "To change the day of their meeting.",
          detail: "Her sister",
        },
        plays: 2,
        usedTranscript: false,
      },
    );
  });

  it("cancels any previous playback rather than overlapping", async () => {
    const { cancel } = stubSpeech();
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    await user.click(screen.getByRole("button", { name: /play the clip/i }));
    await user.click(screen.getByRole("button", { name: /play it again/i }));

    expect(cancel).toHaveBeenCalled();
  });
});

describe("the transcript escape hatch", () => {
  it("is always offered", async () => {
    // A learner who cannot use audio must still be able to take part.
    stubSpeech();
    renderPage();

    expect(
      await screen.findByRole("button", { name: /show the transcript/i }),
    ).toBeInTheDocument();
  });

  it("warns what it costs before it is taken", async () => {
    stubSpeech();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    expect(
      screen.getByText(/counts as reading rather than listening/i),
    ).toBeInTheDocument();
  });

  it("shows the words and opens the questions", async () => {
    stubSpeech();
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    await user.click(
      screen.getByRole("button", { name: /show the transcript/i }),
    );

    expect(screen.getByText(/it's nadia/i)).toBeInTheDocument();
    expect(screen.getAllByRole("radio").length).toBeGreaterThan(0);
  });

  it("reports that it was used, so the API can refuse the evidence", async () => {
    stubSpeech();
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    await user.click(
      screen.getByRole("button", { name: /show the transcript/i }),
    );
    await user.click(screen.getByRole("radio", { name: /change the day/i }));
    await user.click(screen.getByRole("radio", { name: "Her sister" }));
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    expect(mocks.completeActivity).toHaveBeenCalledWith(
      "test-token",
      "listen:listen.a2.voicemail",
      expect.objectContaining({ usedTranscript: true, plays: 0 }),
    );
  });
});

describe("a browser that cannot speak", () => {
  it("says so and points at the transcript instead of failing silently", async () => {
    // jsdom has no speech synthesis, which is exactly the case under test.
    renderPage();

    expect(
      await screen.findByText(/this browser cannot play the clip/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /play the clip/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /show the transcript/i }),
    ).toBeInTheDocument();
  });
});

describe("feedback", () => {
  async function submitHeard() {
    stubSpeech();
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: /a voicemail/i });
    await user.click(screen.getByRole("button", { name: /play the clip/i }));
    await user.click(screen.getByRole("radio", { name: /change the day/i }));
    await user.click(screen.getByRole("radio", { name: "Her sister" }));
    await user.click(screen.getByRole("button", { name: /check my answers/i }));
    return user;
  }

  it("frames the result as understanding, not a mark", async () => {
    await submitHeard();

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/you caught all of it/i);
    expect(status.textContent).not.toMatch(/\d+\s?%/);
  });

  it("marks each outcome with text, not colour alone", async () => {
    await submitHeard();

    const status = await screen.findByRole("status");
    const items = within(status).getAllByRole("listitem");
    expect(within(items[0]).getByText(/^Correct:$/)).toBeInTheDocument();
  });

  it("reveals the transcript afterwards, once it can do no harm", async () => {
    await submitHeard();

    await screen.findByRole("status");
    expect(screen.getByText(/it's nadia/i)).toBeInTheDocument();
  });

  it("says plainly when nothing was recorded, without scolding", async () => {
    mocks.completeActivity.mockResolvedValue(READ);
    stubSpeech();
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: /a voicemail/i });
    await user.click(
      screen.getByRole("button", { name: /show the transcript/i }),
    );
    await user.click(screen.getByRole("radio", { name: /change the day/i }));
    await user.click(screen.getByRole("radio", { name: "Her sister" }));
    await user.click(screen.getByRole("button", { name: /check my answers/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(/listening profile is unchanged/i);
    expect(status).toHaveTextContent(/nothing is lost/i);
  });

  it("offers a way back to the plan", async () => {
    await submitHeard();

    expect(
      await screen.findByRole("link", { name: /back to today.s plan/i }),
    ).toHaveAttribute("href", "/dashboard");
  });
});
