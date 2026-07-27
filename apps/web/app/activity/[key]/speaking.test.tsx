/**
 * Activity player: the speaking kind.
 *
 * The browser listens, and what reaches the server is a transcript. Every test
 * here defends one of the three consequences of that:
 *
 * - The transcript is shown and editable. A recogniser mishears accented
 *   speech more often, and correcting a machine is not cheating.
 * - Recognition confidence is displayed as a fact about the software, never
 *   as a mark against the learner.
 * - Typing is always available and always reported as typing. A learner with
 *   no microphone must be able to finish; a profile that quietly counted it
 *   as speaking would be lying.
 *
 * And the one the whole lab is shaped by: no screen ever claims to have
 * judged pronunciation.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SpeakingActivity, SpeakingResult } from "@/lib/api";
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
    useParams: () => ({ key: "speak:speak.a2.weekend" }),
  };
});

const ACTIVITY: SpeakingActivity = {
  activityKey: "speak:speak.a2.weekend",
  activityType: "speaking_task",
  title: "Tell someone about your weekend",
  cefrLevel: "A2",
  skillKey: "speaking.simple_description",
  estimatedMinutes: 7,
  format: "narrative",
  prompt:
    "A colleague asks what you did at the weekend.\n\nTell them. Say where you went, who you were with, and whether you enjoyed it.",
  guidance: ["Use past forms: went, saw, had, was.", "Say why you enjoyed it."],
  preparationSeconds: 45,
  minSeconds: 35,
  maxSeconds: 120,
  minWords: 55,
  requiredElements: ["because"],
};

const SPOKEN: SpeakingResult = {
  activityType: "speaking_task",
  activityKey: ACTIVITY.activityKey,
  score: 1,
  explanation:
    "These are automatic checks on length and content, made from what the browser heard.",
  checks: [
    {
      code: "length",
      passed: true,
      message: "Long enough to show a sequence.",
    },
    { code: "element", passed: true, message: "You explained why." },
  ],
  wordCount: 71,
  evidenceRecorded: true,
  provisional: true,
  spokenSeconds: 52,
  transcript: "On Saturday I went to the market with my brother…",
  recognitionConfidence: 0.82,
  typedInstead: false,
};

const TYPED: SpeakingResult = {
  ...SPOKEN,
  explanation:
    "You typed this rather than saying it, so it tells us about your writing, not your speaking.",
  evidenceRecorded: false,
  spokenSeconds: 0,
  recognitionConfidence: null,
  typedInstead: true,
};

/**
 * A speech recogniser stub.
 *
 * `latest.hear(text, confidence)` plays a final result through whatever
 * instance the component constructed, which is how the tests below simulate
 * someone actually speaking.
 */
function stubRecognition() {
  const started = vi.fn();
  const stopped = vi.fn();
  const control: { hear?: (text: string, confidence?: number) => void } = {};

  class FakeRecognition {
    lang = "";
    continuous = false;
    interimResults = false;
    onresult: ((event: unknown) => void) | null = null;
    onerror: (() => void) | null = null;
    onend: (() => void) | null = null;

    start() {
      started();
      control.hear = (text: string, confidence = 0.82) => {
        this.onresult?.({
          resultIndex: 0,
          results: [
            Object.assign([{ transcript: text, confidence }], {
              isFinal: true,
            }),
          ],
        });
      };
    }

    stop() {
      stopped();
      this.onend?.();
    }

    abort() {}
  }

  vi.stubGlobal("SpeechRecognition", FakeRecognition);
  return {
    started,
    stopped,
    // Wrapped, because a real recogniser fires this from outside React and
    // the state updates it causes have to be flushed before assertions.
    hear: (text: string, confidence?: number) =>
      act(() => control.hear?.(text, confidence)),
  };
}

/** A browser with no speech recognition at all — Firefox, for instance. */
function stubNoRecognition() {
  vi.stubGlobal("SpeechRecognition", undefined);
  vi.stubGlobal("webkitSpeechRecognition", undefined);
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
  mocks.completeActivity.mockResolvedValue(SPOKEN);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("before speaking", () => {
  it("shows the prompt and the guidance", async () => {
    stubRecognition();
    renderPage();

    expect(
      await screen.findByText(/a colleague asks what you did/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/use past forms/i)).toBeInTheDocument();
  });

  it("states the thinking time before the speaking time", async () => {
    // Planning time changes what a speaking task measures, so the learner is
    // told about it rather than being timed from the first click.
    stubRecognition();
    renderPage();

    expect(
      await screen.findByText(/45 seconds to think first/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/at least 35 seconds/i)).toBeInTheDocument();
  });

  it("says nothing has been recorded yet", async () => {
    stubRecognition();
    renderPage();
    expect(
      await screen.findByText(/nothing recorded yet/i),
    ).toBeInTheDocument();
  });

  it("cannot be submitted empty", async () => {
    stubRecognition();
    renderPage();

    const submit = await screen.findByRole("button", { name: /submit/i });
    expect(submit).toBeDisabled();
  });
});

describe("while speaking", () => {
  it("puts what it heard on screen", async () => {
    // Hiding it would leave the learner submitting something they never saw.
    const recogniser = stubRecognition();
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /start/i }));
    recogniser.hear("On Saturday I went to the market.");

    expect(await screen.findByRole("textbox")).toHaveValue(
      "On Saturday I went to the market.",
    );
  });

  it("lets the learner correct what it heard", async () => {
    // Correcting a machine that misheard an accent is not cheating.
    const recogniser = stubRecognition();
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /start/i }));
    recogniser.hear("On Saturday I went to the market.");

    const box = await screen.findByRole("textbox");
    await user.clear(box);
    await user.type(box, "On Sunday I went to the museum.");

    expect(box).toHaveValue("On Sunday I went to the museum.");
  });

  it("stops when asked", async () => {
    const recogniser = stubRecognition();
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /start/i }));
    await user.click(await screen.findByRole("button", { name: /^stop$/i }));

    expect(recogniser.stopped).toHaveBeenCalled();
  });
});

describe("a browser that cannot listen", () => {
  it("says so plainly rather than failing silently", async () => {
    stubNoRecognition();
    renderPage();

    expect(
      await screen.findByText(/cannot transcribe speech/i),
    ).toBeInTheDocument();
  });

  it("still lets the task be finished", async () => {
    stubNoRecognition();
    const user = userEvent.setup();
    renderPage();

    const box = await screen.findByRole("textbox");
    await user.type(box, "I stayed at home and read a book.");
    await user.click(screen.getByRole("button", { name: /submit/i }));

    expect(mocks.completeActivity).toHaveBeenCalled();
  });

  it("reports the answer as typed, not spoken", async () => {
    // The honesty rule. The submission says what actually happened, so the
    // server can decline to record speaking evidence.
    stubNoRecognition();
    mocks.completeActivity.mockResolvedValue(TYPED);
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByRole("textbox"),
      "I stayed at home and read a book.",
    );
    await user.click(screen.getByRole("button", { name: /submit/i }));

    const [, , submission] = mocks.completeActivity.mock.calls[0];
    expect(submission.typedInstead).toBe(true);
    expect(submission.spokenSeconds).toBe(0);
    expect(submission.recognitionConfidence).toBeNull();
  });
});

describe("typing by choice", () => {
  it("is offered even when the browser can listen", async () => {
    // Someone on a train, or in an office, or without a microphone.
    stubRecognition();
    renderPage();

    expect(
      await screen.findByRole("button", { name: /let me type/i }),
    ).toBeInTheDocument();
  });

  it("says up front that it will not count as speaking", async () => {
    stubRecognition();
    renderPage();

    expect(
      await screen.findByText(/counts as writing rather than speaking/i),
    ).toBeInTheDocument();
  });

  it("is reported honestly when chosen", async () => {
    stubRecognition();
    mocks.completeActivity.mockResolvedValue(TYPED);
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: /let me type/i }),
    );
    await user.type(screen.getByRole("textbox"), "I stayed at home.");
    await user.click(screen.getByRole("button", { name: /submit/i }));

    const [, , submission] = mocks.completeActivity.mock.calls[0];
    expect(submission.typedInstead).toBe(true);
  });
});

describe("after submitting", () => {
  async function speakAndSubmit(result: SpeakingResult = SPOKEN) {
    mocks.completeActivity.mockResolvedValue(result);
    const recogniser = stubRecognition();
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /start/i }));
    recogniser.hear("On Saturday I went to the market with my brother.", 0.82);
    await user.click(await screen.findByRole("button", { name: /^stop$/i }));
    await user.click(screen.getByRole("button", { name: /submit/i }));
  }

  it("never claims to have judged pronunciation", async () => {
    // The single most important assertion in this file. A learner who
    // believed this had assessed their accent would be misled about the one
    // thing a transcript cannot show.
    await speakAndSubmit();

    expect(
      await screen.findByText(/nothing here has judged your pronunciation/i),
    ).toBeInTheDocument();
  });

  it("explains why pronunciation is out of reach", async () => {
    // A refusal without a reason reads as a missing feature.
    await speakAndSubmit();

    expect(
      await screen.findByText(/cannot tell a clearly spoken word/i),
    ).toBeInTheDocument();
  });

  it("frames recognition confidence as a fact about the software", async () => {
    // Not a mark. Recognisers are worse on accented speech, which is this
    // product's whole audience.
    await speakAndSubmit();

    expect(
      await screen.findByText(/not about you, and it does not affect/i),
    ).toBeInTheDocument();
  });

  it("shows the checks it did make", async () => {
    await speakAndSubmit();
    expect(
      await screen.findByText(/long enough to show a sequence/i),
    ).toBeInTheDocument();
  });

  it("says how long the learner spoke for", async () => {
    await speakAndSubmit();
    expect(
      await screen.findByText(/spoke for 52 seconds/i),
    ).toBeInTheDocument();
  });

  it("says plainly when nothing was recorded, without blame", async () => {
    await speakAndSubmit(TYPED);

    expect(
      await screen.findByText(/your speaking profile is unchanged/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/nothing is lost/i)).toBeInTheDocument();
  });

  it("does not report a spoken duration for a typed answer", async () => {
    await speakAndSubmit(TYPED);

    await screen.findByText(/your speaking profile is unchanged/i);
    expect(screen.queryByText(/you spoke for/i)).not.toBeInTheDocument();
  });
});
