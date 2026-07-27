"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
} from "react";

import {
  completeActivity,
  fetchActivity,
  type Activity,
  type ActivityResult,
  type ActivitySubmission,
  type ListeningActivity,
  type ListeningResult,
  type ReadingActivity,
  type SpeakingActivity,
  type SpeakingResult,
  type ReadingResult,
  type StudyActivity,
  type StudyResult,
  type WritingActivity,
  type WritingResult,
} from "@/lib/api";
import { confidenceLabel, questionTypeLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

/**
 * Activity player.
 *
 * One route, three kinds, each with a different contract with the learner:
 *
 * - **Reading** keeps the text on screen while the questions are answered.
 *   `docs/LEARNING_SCIENCE.md` asks for meaning-focused input, and hiding the
 *   text would quietly turn comprehension into a memory test.
 * - **Study** keeps the explanation on screen for the same reason, and says
 *   plainly that practice with the rule visible is not yet proof.
 * - **Writing** shows the requirements up front and, afterwards, states that
 *   only countable properties were checked. Claiming a piece of writing is
 *   fine when nothing judged its accuracy is the dishonesty
 *   `docs/AI_TUTOR_BEHAVIOR.md` forbids.
 * - **Speaking** records what the browser hears and checks the transcript for
 *   length and content. It never claims anything about pronunciation, and it
 *   never scores recognition confidence: recognisers are measurably worse on
 *   accented speech, which is this product's whole audience.
 * - **Listening** inverts the reading rule: the transcript is *hidden*, because
 *   a visible transcript turns listening into reading. It stays one click
 *   away, because a learner who cannot use audio must still be able to take
 *   part -- and taking that click is reported, so the profile never claims
 *   they understood by ear when they read it.
 */
export default function ActivityPage() {
  const router = useRouter();
  const params = useParams<{ key: string }>();
  const { token, ready } = useSession();
  const activityKey = decodeURIComponent(String(params.key ?? ""));

  const [activity, setActivity] = useState<Activity | null>(null);
  const [result, setResult] = useState<ActivityResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token || !activityKey) return;
    let cancelled = false;

    void (async () => {
      try {
        const next = await fetchActivity(token, activityKey);
        if (cancelled) return;
        setActivity(next);
        setError(null);
      } catch (cause) {
        if (!cancelled) setError(cause);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, activityKey, reloadKey]);

  if (!ready || (loading && !error)) {
    return (
      <main id="main" className="narrow">
        <Loading label="Opening…" />
      </main>
    );
  }

  if (error) {
    return (
      <main id="main" className="narrow">
        <ErrorNotice
          error={error}
          onRetry={() => {
            setError(null);
            setLoading(true);
            setReloadKey((key) => key + 1);
          }}
        />
      </main>
    );
  }

  if (!activity || !token) return null;

  async function submit(submission: ActivitySubmission) {
    if (!token) return;
    setResult(await completeActivity(token, activityKey, submission));
  }

  // Exhaustive by construction: adding a fourth kind becomes a compile error
  // at `assertNever`, not a blank screen in production.
  switch (activity.activityType) {
    case "reading_task":
      return (
        <Reading
          activity={activity}
          result={result?.activityType === "reading_task" ? result : null}
          onSubmit={submit}
          onError={setError}
        />
      );
    case "study_task":
      return (
        <Study
          activity={activity}
          result={result?.activityType === "study_task" ? result : null}
          onSubmit={submit}
          onError={setError}
        />
      );
    case "writing_task":
      return (
        <Writing
          activity={activity}
          result={result?.activityType === "writing_task" ? result : null}
          onSubmit={submit}
          onError={setError}
        />
      );
    case "listening_task":
      return (
        <Listening
          activity={activity}
          result={result?.activityType === "listening_task" ? result : null}
          onSubmit={submit}
          onError={setError}
        />
      );
    case "speaking_task":
      return (
        <Speaking
          activity={activity}
          result={result?.activityType === "speaking_task" ? result : null}
          onSubmit={submit}
          onError={setError}
        />
      );
    default:
      return assertNever(activity);
  }
}

function assertNever(value: never): never {
  throw new Error(`Unhandled activity type: ${JSON.stringify(value)}`);
}

interface KindProps<A, R> {
  activity: A;
  result: R | null;
  onSubmit: (submission: ActivitySubmission) => Promise<void>;
  onError: (cause: unknown) => void;
}

function BackToPlan() {
  return (
    <Link className="button" href="/dashboard">
      Back to today&rsquo;s plan
    </Link>
  );
}

// --- Reading ---------------------------------------------------------------

function Reading({
  activity,
  result,
  onSubmit,
  onError,
}: KindProps<ReadingActivity, ReadingResult>) {
  const [reading, setReading] = useState(true);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const answered = activity.questions.filter((q) => answers[q.key]).length;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit({ answers });
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">READING · {activity.cefrLevel}</p>
      <h1 className="page-title">{activity.title}</h1>
      <p className="hint">
        {activity.wordCount} words · about {activity.estimatedMinutes} minutes
      </p>

      {/* The text stays visible throughout: this measures comprehension,
          not memory. */}
      <article className="panel reading-text">
        <pre>{activity.body}</pre>
      </article>

      {reading && !result ? (
        <>
          <p className="muted">
            Read it once for the overall message. You can look back at it while
            you answer.
          </p>
          <button type="button" onClick={() => setReading(false)}>
            I&rsquo;ve read it
          </button>
        </>
      ) : null}

      {!reading && !result ? (
        <form onSubmit={submit}>
          {activity.questions.map((question) => (
            <fieldset key={question.key} className="field">
              <legend>
                {question.prompt}
                <span className="question-type">
                  {questionTypeLabel(question.questionType)}
                </span>
              </legend>
              <div className="choices choices-stack">
                {question.options.map((option) => (
                  <label key={option} className="choice">
                    <input
                      type="radio"
                      name={question.key}
                      value={option}
                      checked={answers[question.key] === option}
                      onChange={() =>
                        setAnswers((current) => ({
                          ...current,
                          [question.key]: option,
                        }))
                      }
                    />
                    <span>{option}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          ))}

          <button
            type="submit"
            disabled={busy || answered < activity.questions.length}
          >
            {busy
              ? "Checking…"
              : answered < activity.questions.length
                ? `Answer all ${activity.questions.length} questions`
                : "Check my answers"}
          </button>
        </form>
      ) : null}

      {result ? (
        <div className="notice" role="status" aria-live="polite">
          <p>
            <strong>{result.explanation}</strong>
          </p>
          <ul className="checks">
            {result.results.map((outcome) => (
              <li
                key={outcome.key}
                className={outcome.correct ? "check-ok" : "check-todo"}
              >
                <span aria-hidden="true">{outcome.correct ? "✓" : "•"}</span>
                <span className="visually-hidden">
                  {outcome.correct ? "Correct:" : "Missed:"}
                </span>{" "}
                {questionTypeLabel(outcome.questionType)}
                {outcome.correct ? "" : ` — ${outcome.expected}`}
              </li>
            ))}
          </ul>
          <BackToPlan />
        </div>
      ) : null}
    </main>
  );
}

// --- Study -----------------------------------------------------------------

function Study({
  activity,
  result,
  onSubmit,
  onError,
}: KindProps<StudyActivity, StudyResult>) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);

  const hintsUsed = Object.values(revealed).filter(Boolean).length;
  const answered = activity.items.filter((item) =>
    (answers[item.key] ?? "").trim(),
  ).length;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit({ answers, hintsUsed });
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }

  const loggedLabels = result
    ? Array.from(
        new Set(
          result.results
            .filter((outcome) =>
              result.loggedFeatures.includes(outcome.feature),
            )
            .map((outcome) => outcome.featureLabel),
        ),
      )
    : [];

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">FOCUSED PRACTICE · {activity.cefrLevel}</p>
      <h1 className="page-title">{activity.title}</h1>
      <p className="hint">About {activity.estimatedMinutes} minutes</p>

      {/* The explanation stays visible while practising. That is the point of
          a study unit — and it is why the result says the evidence is
          scaffolded rather than pretending otherwise. */}
      <article className="panel">
        {activity.explanation.split("\n\n").map((paragraph) => (
          <p key={paragraph.slice(0, 40)}>{paragraph}</p>
        ))}
        <ul className="examples">
          {activity.examples.map((example) => (
            <li key={example}>
              <em>{example}</em>
            </li>
          ))}
        </ul>
      </article>

      {!result ? (
        <form onSubmit={submit}>
          {activity.items.map((item) => (
            <fieldset key={item.key} className="field">
              <legend>
                {item.prompt}
                <span className="question-type">{item.featureLabel}</span>
              </legend>

              {item.itemType === "choice" ? (
                <div className="choices choices-stack">
                  {item.options.map((option) => (
                    <label key={option} className="choice">
                      <input
                        type="radio"
                        name={item.key}
                        value={option}
                        checked={answers[item.key] === option}
                        onChange={() =>
                          setAnswers((current) => ({
                            ...current,
                            [item.key]: option,
                          }))
                        }
                      />
                      <span>{option}</span>
                    </label>
                  ))}
                </div>
              ) : (
                <input
                  type="text"
                  name={item.key}
                  autoComplete="off"
                  aria-label={item.prompt}
                  value={answers[item.key] ?? ""}
                  onChange={(event) =>
                    setAnswers((current) => ({
                      ...current,
                      [item.key]: event.target.value,
                    }))
                  }
                />
              )}

              {/* Revealing help is allowed and recorded. Hiding that a
                  learner needed the rule would overstate what they showed. */}
              {revealed[item.key] ? (
                <p className="hint">
                  Look again at the explanation above — this one is about{" "}
                  {item.featureLabel.toLowerCase()}.
                </p>
              ) : (
                <button
                  type="button"
                  className="link-button"
                  onClick={() =>
                    setRevealed((current) => ({ ...current, [item.key]: true }))
                  }
                >
                  I need a hint
                </button>
              )}
            </fieldset>
          ))}

          <button
            type="submit"
            disabled={busy || answered < activity.items.length}
          >
            {busy
              ? "Checking…"
              : answered < activity.items.length
                ? `Answer all ${activity.items.length}`
                : "Check my answers"}
          </button>
        </form>
      ) : null}

      {result ? (
        <div className="notice" role="status" aria-live="polite">
          <p>
            <strong>{result.explanation}</strong>
          </p>
          <ul className="checks">
            {result.results.map((outcome) => (
              <li
                key={outcome.key}
                className={outcome.correct ? "check-ok" : "check-todo"}
              >
                <span aria-hidden="true">{outcome.correct ? "✓" : "•"}</span>
                <span className="visually-hidden">
                  {outcome.correct ? "Correct:" : "Missed:"}
                </span>{" "}
                <strong>{outcome.featureLabel}</strong>
                {outcome.correct ? "" : ` — ${outcome.expected}`}
                <br />
                <span className="muted">{outcome.note}</span>
              </li>
            ))}
          </ul>

          {/* Say why a perfect score here does not settle the skill. */}
          <p className="hint">
            You had the explanation in front of you, so this counts as guided
            practice rather than recall. A spaced review without the notes is
            what confirms it.
          </p>

          {loggedLabels.length > 0 ? (
            <p className="muted">
              Added to your practice queue: {loggedLabels.join(", ")}.
            </p>
          ) : null}

          <BackToPlan />
        </div>
      ) : null}
    </main>
  );
}

// --- Writing ---------------------------------------------------------------

function Writing({
  activity,
  result,
  onSubmit,
  onError,
}: KindProps<WritingActivity, WritingResult>) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  // Counted the way the server counts, so the number the learner watches is
  // the number they are checked against.
  const wordCount = useMemo(
    () => (text.match(/[A-Za-z][A-Za-z'’-]*/g) ?? []).length,
    [text],
  );
  const short = wordCount < activity.minWords;
  const long = wordCount > activity.maxWords;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit({ text });
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">
        WRITING · {activity.cefrLevel} · {activity.genre.toUpperCase()}
      </p>
      <h1 className="page-title">{activity.title}</h1>
      <p className="hint">About {activity.estimatedMinutes} minutes</p>

      <article className="panel">
        {activity.prompt.split("\n\n").map((paragraph) => (
          <p key={paragraph.slice(0, 40)}>{paragraph}</p>
        ))}
        <h2 className="subheading">Before you send it</h2>
        <ul>
          {activity.guidance.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
        <p className="muted">
          {activity.minWords}&ndash;{activity.maxWords} words, at least{" "}
          {activity.minSentences} sentences.
          {activity.requiredElements.length > 0
            ? ` The task asks you to mention: ${activity.requiredElements.join(", ")}.`
            : ""}
        </p>
      </article>

      {!result ? (
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="response">Your response</label>
            <textarea
              id="response"
              name="response"
              rows={14}
              value={text}
              onChange={(event) => setText(event.target.value)}
              aria-describedby="word-count"
            />
            <p id="word-count" className="hint" aria-live="polite">
              {wordCount} words
              {short ? ` — ${activity.minWords - wordCount} more to go` : ""}
              {long ? " — a little over the limit" : ""}
            </p>
          </div>

          <button type="submit" disabled={busy || wordCount === 0}>
            {busy ? "Checking…" : "Check my writing"}
          </button>
        </form>
      ) : null}

      {result ? (
        <div className="notice" role="status" aria-live="polite">
          <p>
            <strong>{result.explanation}</strong>
          </p>
          <ul className="checks">
            {result.checks.map((check) => (
              <li
                key={check.code}
                className={check.passed ? "check-ok" : "check-todo"}
              >
                <span aria-hidden="true">{check.passed ? "✓" : "•"}</span>
                <span className="visually-hidden">
                  {check.passed ? "Met:" : "Not yet:"}
                </span>{" "}
                {check.message}
              </li>
            ))}
          </ul>

          {/* A rubric ran. Show what it looked at and what it cited, so the
              learner can disagree with a judgement rather than just receive
              it. `docs/AI_TUTOR_BEHAVIOR.md`: an evaluator that cannot cite
              evidence is guessing. */}
          {result.rubric.length > 0 ? (
            <>
              <h2 className="subheading">Assessed against a rubric</h2>
              <ul className="checks">
                {result.rubric.map((dimension) => (
                  <li key={dimension.name}>
                    <strong>{dimension.name}</strong>{" "}
                    <span className="muted">
                      {confidenceLabel(dimension.confidence).toLowerCase()}
                    </span>
                    {dimension.evidence.length > 0 ? (
                      <ul>
                        {dimension.evidence.map((quote) => (
                          <li key={quote}>
                            <em>&ldquo;{quote}&rdquo;</em>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ul>
              {result.evaluatedBy ? (
                <p className="hint">
                  Judged by an automatic evaluator ({result.evaluatedBy}), not
                  by a teacher. It can be wrong, and it is weighted lower than a
                  task with a known answer.
                </p>
              ) : null}
            </>
          ) : null}

          {/* At most three. Correcting everything teaches nothing. */}
          {result.priorityFeedback.length > 0 ? (
            <>
              <h2 className="subheading">Worth fixing first</h2>
              <ul className="checks">
                {result.priorityFeedback.map((item) => (
                  <li key={`${item.category}-${item.original}`}>
                    <span className="question-type">{item.category}</span>
                    <br />
                    <s>{item.original}</s> &rarr;{" "}
                    <strong>{item.improved}</strong>
                    <br />
                    <span className="muted">{item.explanation}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {/* Non-negotiable: never imply the writing was judged good. */}
          {result.provisional ? (
            <div className="notice notice-warn">
              <p>
                <strong>
                  Nothing here has judged your grammar or word choice.
                </strong>
              </p>
              <p>
                These are automatic checks on length, structure, and whether you
                covered the task. Detailed feedback on accuracy arrives with the
                writing lab.
              </p>
            </div>
          ) : null}

          {!result.evidenceRecorded ? (
            <p className="muted">
              This was too short to tell us anything, so it has not changed your
              profile. It is saved, and you can write more whenever you like.
            </p>
          ) : null}

          <BackToPlan />
        </div>
      ) : null}
    </main>
  );
}

// --- Listening -------------------------------------------------------------

/**
 * Speech synthesis is a static browser capability, not reactive state, so it
 * never notifies. The subscribe function is defined once at module scope
 * because `useSyncExternalStore` re-subscribes whenever it changes identity.
 */
const subscribeToNothing = () => () => {};
const speechIsAvailable = () =>
  typeof window !== "undefined" && "speechSynthesis" in window;
const speechIsUnavailableOnTheServer = () => false;

function Listening({
  activity,
  result,
  onSubmit,
  onError,
}: KindProps<ListeningActivity, ListeningResult>) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [plays, setPlays] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  const [busy, setBusy] = useState(false);

  // Whether this browser can speak at all. Read through `useSyncExternalStore`
  // rather than set from an effect: the server snapshot is `false` and the
  // client snapshot is the real capability, which is exactly the hydration
  // guarantee that hook exists to give. Setting it from an effect would work
  // but costs a second render on every mount, which is why the lint rule
  // objects.
  const canSpeak = useSyncExternalStore(
    subscribeToNothing,
    speechIsAvailable,
    speechIsUnavailableOnTheServer,
  );

  // Stop any playback when the learner navigates away mid-clip.
  useEffect(() => {
    return () => {
      if (speechIsAvailable()) window.speechSynthesis.cancel();
    };
  }, []);

  function play() {
    if (!canSpeak) return;
    const synth = window.speechSynthesis;
    // Cancel first: pressing play twice should replay, not overlap.
    synth.cancel();

    const utterance = new SpeechSynthesisUtterance(activity.transcript);
    utterance.rate = activity.speechRate;
    utterance.lang = "en-GB";
    utterance.onend = () => setPlaying(false);
    utterance.onerror = () => setPlaying(false);

    setPlaying(true);
    setPlays((count) => count + 1);
    synth.speak(utterance);
  }

  function revealTranscript() {
    if (speechIsAvailable()) window.speechSynthesis.cancel();
    setPlaying(false);
    setShowTranscript(true);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit({ answers, plays, usedTranscript: showTranscript });
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }

  const answered = activity.questions.filter((q) => answers[q.key]).length;
  // Nothing to answer until the clip has been heard or the transcript read.
  // Answering blind would measure guessing.
  const started = plays > 0 || showTranscript;

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">LISTENING · {activity.cefrLevel}</p>
      <h1 className="page-title">{activity.title}</h1>
      <p className="hint">About {activity.estimatedMinutes} minutes</p>

      <article className="panel">
        <p>{activity.setting}</p>

        {activity.audio ? (
          // A deployment with real recordings should always prefer them:
          // synthesised speech is missing the connected speech that makes
          // listening hard.
          <audio
            controls
            src={activity.audio}
            onPlay={() => setPlays((c) => c + 1)}
          >
            <track kind="captions" />
          </audio>
        ) : canSpeak ? (
          <>
            <button type="button" onClick={play} disabled={playing}>
              {playing
                ? "Playing…"
                : plays === 0
                  ? "Play the clip"
                  : "Play it again"}
            </button>
            <p className="hint" aria-live="polite">
              {plays === 0
                ? "You can replay it as often as you need."
                : `Played ${plays} ${plays === 1 ? "time" : "times"}.`}
            </p>
          </>
        ) : (
          <div className="notice notice-warn">
            <p>
              <strong>This browser cannot play the clip.</strong>
            </p>
            <p>
              Read the transcript instead — the questions work the same way. It
              will be recorded as reading rather than listening.
            </p>
          </div>
        )}
      </article>

      {!showTranscript && !result ? (
        <p className="muted">
          <button
            type="button"
            className="link-button"
            onClick={revealTranscript}
          >
            I can&rsquo;t follow it — show the transcript
          </button>{" "}
          This is always available. It means the exercise counts as reading
          rather than listening, and we will say so.
        </p>
      ) : null}

      {showTranscript || result ? (
        <article className="panel reading-text">
          <h2 className="subheading">Transcript</h2>
          <pre>{activity.transcript}</pre>
        </article>
      ) : null}

      {started && !result ? (
        <form onSubmit={submit}>
          {activity.questions.map((question) => (
            <fieldset key={question.key} className="field">
              <legend>
                {question.prompt}
                <span className="question-type">
                  {questionTypeLabel(question.questionType)}
                </span>
              </legend>
              <div className="choices choices-stack">
                {question.options.map((option) => (
                  <label key={option} className="choice">
                    <input
                      type="radio"
                      name={question.key}
                      value={option}
                      checked={answers[question.key] === option}
                      onChange={() =>
                        setAnswers((current) => ({
                          ...current,
                          [question.key]: option,
                        }))
                      }
                    />
                    <span>{option}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          ))}

          <button
            type="submit"
            disabled={busy || answered < activity.questions.length}
          >
            {busy
              ? "Checking…"
              : answered < activity.questions.length
                ? `Answer all ${activity.questions.length} questions`
                : "Check my answers"}
          </button>
        </form>
      ) : null}

      {result ? (
        <div className="notice" role="status" aria-live="polite">
          <p>
            <strong>{result.explanation}</strong>
          </p>
          <ul className="checks">
            {result.results.map((outcome) => (
              <li
                key={outcome.key}
                className={outcome.correct ? "check-ok" : "check-todo"}
              >
                <span aria-hidden="true">{outcome.correct ? "✓" : "•"}</span>
                <span className="visually-hidden">
                  {outcome.correct ? "Correct:" : "Missed:"}
                </span>{" "}
                {questionTypeLabel(outcome.questionType)}
                {outcome.correct ? "" : ` — ${outcome.expected}`}
              </li>
            ))}
          </ul>

          {!result.evidenceRecorded ? (
            <p className="muted">
              Your listening profile is unchanged, because this one was read
              rather than heard. Nothing is lost — try the next clip by ear.
            </p>
          ) : null}

          <BackToPlan />
        </div>
      ) : null}
    </main>
  );
}

// --- Speaking --------------------------------------------------------------

/** Whether this browser can transcribe speech. Static, like `speechSynthesis`. */
const recognitionConstructor = (): (new () => SpeechRecognition) | null => {
  if (typeof window === "undefined") return null;
  // Both prefixed and unprefixed: Safari and older Chromium only expose the
  // `webkit` one. Typed in `types/speech-recognition.d.ts`, which declares
  // them optional because absence is the normal case, not an error.
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
};
const recognitionIsAvailable = () => recognitionConstructor() !== null;
const recognitionUnavailableOnTheServer = () => false;

function Speaking({
  activity,
  result,
  onSubmit,
  onError,
}: KindProps<SpeakingActivity, SpeakingResult>) {
  const [transcript, setTranscript] = useState("");
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [typed, setTyped] = useState(false);
  const [busy, setBusy] = useState(false);

  const canRecord = useSyncExternalStore(
    subscribeToNothing,
    recognitionIsAvailable,
    recognitionUnavailableOnTheServer,
  );

  const recogniser = useRef<SpeechRecognition | null>(null);
  const startedAt = useRef<number | null>(null);

  // A ticking counter while recording, so the learner can see whether they
  // have reached the length the task asks for.
  useEffect(() => {
    if (!recording) return;
    const timer = window.setInterval(() => {
      if (startedAt.current !== null) {
        setSeconds(Math.round((Date.now() - startedAt.current) / 1000));
      }
    }, 500);
    return () => window.clearInterval(timer);
  }, [recording]);

  // Stop listening if the learner navigates away mid-answer.
  useEffect(() => {
    return () => recogniser.current?.abort();
  }, []);

  function start() {
    const Recogniser = recognitionConstructor();
    if (!Recogniser) return;

    const instance = new Recogniser();
    instance.lang = "en-GB";
    instance.continuous = true;
    instance.interimResults = true;

    let settled = "";
    let best: number | null = null;

    instance.onresult = (event: SpeechRecognitionEvent) => {
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const alternative = result[0];
        if (result.isFinal) {
          settled += alternative.transcript;
          // Kept for display and audit only. Scoring it would penalise an
          // accent the recogniser was not trained on.
          if (typeof alternative.confidence === "number") {
            best =
              best === null
                ? alternative.confidence
                : Math.max(best, alternative.confidence);
          }
        } else {
          pending += alternative.transcript;
        }
      }
      setTranscript((settled + pending).trim());
      setConfidence(best);
    };
    instance.onerror = () => stop();
    instance.onend = () => setRecording(false);

    recogniser.current = instance;
    startedAt.current = Date.now();
    setSeconds(0);
    setTyped(false);
    setRecording(true);
    instance.start();
  }

  function stop() {
    recogniser.current?.stop();
    recogniser.current = null;
    setRecording(false);
    if (startedAt.current !== null) {
      setSeconds(Math.round((Date.now() - startedAt.current) / 1000));
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit({
        text: transcript,
        spokenSeconds: typed ? 0 : seconds,
        recognitionConfidence: typed ? null : confidence,
        typedInstead: typed,
      });
    } catch (cause) {
      onError(cause);
    } finally {
      setBusy(false);
    }
  }

  const shortOfTime = !typed && seconds < activity.minSeconds;

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">
        SPEAKING · {activity.cefrLevel} · {activity.format.toUpperCase()}
      </p>
      <h1 className="page-title">{activity.title}</h1>
      <p className="hint">About {activity.estimatedMinutes} minutes</p>

      <article className="panel">
        {activity.prompt.split("\n\n").map((paragraph) => (
          <p key={paragraph.slice(0, 40)}>{paragraph}</p>
        ))}
        <h2 className="subheading">Before you start</h2>
        <ul>
          {activity.guidance.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
        <p className="muted">
          Take about {activity.preparationSeconds} seconds to think first. Then
          speak for at least {activity.minSeconds} seconds.
        </p>
      </article>

      {!result ? (
        <form onSubmit={submit}>
          {canRecord ? (
            <>
              <button type="button" onClick={recording ? stop : start}>
                {recording
                  ? "Stop"
                  : seconds > 0
                    ? "Record again"
                    : "Start speaking"}
              </button>
              <p className="hint" aria-live="polite">
                {recording
                  ? `Listening… ${seconds}s`
                  : seconds > 0
                    ? `You spoke for ${seconds}s.`
                    : "Nothing recorded yet."}
                {shortOfTime && seconds > 0
                  ? ` The task asks for at least ${activity.minSeconds}s.`
                  : ""}
              </p>
            </>
          ) : (
            <div className="notice notice-warn">
              <p>
                <strong>This browser cannot transcribe speech.</strong>
              </p>
              <p>
                Type your answer below instead. It will be recorded as writing
                rather than speaking, and we will say so.
              </p>
            </div>
          )}

          {/* Always available. A learner with no microphone, or one the
              recogniser mishears badly, must still be able to finish -- and
              editing what was heard is not cheating, it is correcting a
              machine. Typing from scratch is reported honestly. */}
          <div className="field">
            <label htmlFor="transcript">
              {canRecord ? "What we heard (you can correct it)" : "Your answer"}
            </label>
            <textarea
              id="transcript"
              name="transcript"
              rows={8}
              value={transcript}
              onChange={(event) => {
                setTranscript(event.target.value);
                if (!canRecord) setTyped(true);
              }}
            />
            <p className="hint">
              {(transcript.match(/[A-Za-z][A-Za-z'’-]*/g) ?? []).length} words ·
              the task asks for about {activity.minWords}
            </p>
          </div>

          {canRecord && seconds === 0 ? (
            <p className="muted">
              <button
                type="button"
                className="link-button"
                onClick={() => setTyped(true)}
              >
                I can&rsquo;t speak right now — let me type
              </button>{" "}
              This is always available. It counts as writing rather than
              speaking, and we will say so.
            </p>
          ) : null}

          <button
            type="submit"
            disabled={busy || recording || !transcript.trim()}
          >
            {busy ? "Checking…" : "Submit"}
          </button>
        </form>
      ) : null}

      {result ? (
        <div className="notice" role="status" aria-live="polite">
          <p>
            <strong>{result.explanation}</strong>
          </p>
          <ul className="checks">
            {result.checks.map((check) => (
              <li
                key={check.code}
                className={check.passed ? "check-ok" : "check-todo"}
              >
                <span aria-hidden="true">{check.passed ? "✓" : "•"}</span>
                <span className="visually-hidden">
                  {check.passed ? "Met:" : "Not yet:"}
                </span>{" "}
                {check.message}
              </li>
            ))}
          </ul>

          {!result.typedInstead ? (
            <p className="muted">
              You spoke for {result.spokenSeconds} seconds.
              {result.recognitionConfidence !== null
                ? ` The recogniser was ${confidenceLabel(result.recognitionConfidence).toLowerCase()} about what it heard — that is a fact about the software, not about you, and it does not affect your profile.`
                : ""}
            </p>
          ) : null}

          {/* Non-negotiable, and the reason the whole lab is shaped this way. */}
          <div className="notice notice-warn">
            <p>
              <strong>Nothing here has judged your pronunciation.</strong>
            </p>
            <p>
              These checks read a transcript, which cannot tell a clearly spoken
              word from one the software guessed correctly. Feedback on how you
              sound needs acoustic analysis, which this does not do.
            </p>
          </div>

          {!result.evidenceRecorded ? (
            <p className="muted">
              Your speaking profile is unchanged. Nothing is lost — the attempt
              is saved, and the next one can count.
            </p>
          ) : null}

          <BackToPlan />
        </div>
      ) : null}
    </main>
  );
}
