"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  completeDiagnostic,
  fetchNextItem,
  startDiagnostic,
  submitResponse,
  type DiagnosticReport,
  type ItemPrompt,
  type SubmitResult,
} from "@/lib/api";
import { statusLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

type Phase = "loading" | "answering" | "feedback" | "finished";

export default function DiagnosticPage() {
  const router = useRouter();
  const { token, ready } = useSession();

  const [phase, setPhase] = useState<Phase>("loading");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [item, setItem] = useState<ItemPrompt | null>(null);
  const [answered, setAnswered] = useState(0);
  const [answer, setAnswer] = useState("");
  const [feedback, setFeedback] = useState<SubmitResult | null>(null);
  const [report, setReport] = useState<DiagnosticReport | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [startKey, setStartKey] = useState(0);

  // Focus moves to each new question so keyboard and screen-reader users are
  // not left at the top of the document after every answer.
  const questionRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    void (async () => {
      try {
        const session = await startDiagnostic(token);
        if (cancelled) return;
        setSessionId(session.id);

        const next = await fetchNextItem(token, session.id);
        if (cancelled) return;
        setAnswered(next.answered);

        if (next.finished || next.item === null) {
          const finalReport = await completeDiagnostic(token, session.id);
          if (cancelled) return;
          setReport(finalReport);
          setPhase("finished");
          return;
        }
        setItem(next.item);
        setPhase("answering");
      } catch (cause) {
        if (!cancelled) setError(cause);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, startKey]);

  useEffect(() => {
    if (phase === "answering") questionRef.current?.focus();
  }, [phase, item?.key]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!token || !sessionId || !item) return;
    setBusy(true);
    setError(null);
    try {
      const result = await submitResponse(token, sessionId, {
        itemKey: item.key,
        response: answer,
      });
      setFeedback(result);
      setAnswered(result.answered);
      setPhase("feedback");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function onContinue() {
    if (!token || !sessionId) return;
    setBusy(true);
    try {
      const next = await fetchNextItem(token, sessionId);
      setAnswered(next.answered);
      if (next.finished || next.item === null) {
        setReport(await completeDiagnostic(token, sessionId));
        setPhase("finished");
        return;
      }
      setItem(next.item);
      setAnswer("");
      setFeedback(null);
      setPhase("answering");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  function restart() {
    setError(null);
    setPhase("loading");
    setStartKey((key) => key + 1);
  }

  if (!ready || (phase === "loading" && !error)) {
    return (
      <main id="main" className="narrow">
        <Loading label="Preparing your diagnostic…" />
      </main>
    );
  }

  if (error) {
    return (
      <main id="main" className="narrow">
        <ErrorNotice error={error} onRetry={restart} />
      </main>
    );
  }

  if (phase === "finished" && report) {
    return <Report report={report} />;
  }

  if (!item) return null;

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">QUESTION {answered + 1}</p>
      <p className="hint">
        This is not a test. Getting something wrong is useful information too.
      </p>

      <h1 className="question" tabIndex={-1} ref={questionRef}>
        {item.prompt}
      </h1>
      {item.instructions ? <p className="muted">{item.instructions}</p> : null}

      <form onSubmit={onSubmit}>
        <fieldset disabled={phase === "feedback"}>
          <legend className="visually-hidden">Your answer</legend>
          {item.itemType === "written_response" ? (
            <WritingAnswer item={item} value={answer} onChange={setAnswer} />
          ) : item.itemType === "self_assessment" ? (
            <Choices options={RATINGS} value={answer} onChange={setAnswer} />
          ) : item.options.length > 0 ? (
            <Choices
              options={item.options.map((option) => ({
                value: option,
                label: option,
              }))}
              value={answer}
              onChange={setAnswer}
            />
          ) : (
            <div className="field">
              <label htmlFor="answer">Your answer</label>
              <input
                id="answer"
                name="answer"
                type="text"
                autoComplete="off"
                autoCapitalize="none"
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
              />
            </div>
          )}
        </fieldset>

        {phase === "answering" ? (
          <button type="submit" disabled={busy || answer.trim() === ""}>
            {busy
              ? "Checking…"
              : item.itemType === "written_response"
                ? "Submit my answer"
                : "Check answer"}
          </button>
        ) : null}
      </form>

      {phase === "feedback" && feedback ? (
        <Feedback feedback={feedback} busy={busy} onContinue={onContinue} />
      ) : null}
    </main>
  );
}

/** Counts words the same way the API does, so the two never disagree. */
export function countWords(text: string): number {
  return (text.match(/[A-Za-z][A-Za-z'’-]*/g) ?? []).length;
}

function WritingAnswer({
  item,
  value,
  onChange,
}: {
  item: ItemPrompt;
  value: string;
  onChange: (next: string) => void;
}) {
  const words = countWords(value);
  const min = item.minWords ?? 0;
  const max = item.maxWords ?? Infinity;
  const short = words < min;
  const long = words > max;

  return (
    <div className="field">
      <label htmlFor="answer">Your answer</label>
      <textarea
        id="answer"
        name="answer"
        rows={10}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby="word-count"
        spellCheck={false}
      />
      {/* A live region, but deliberately not role="status": the feedback panel
          owns that role, and two competing status regions make announcements
          unpredictable. Polite so it never interrupts mid-keystroke. */}
      <p id="word-count" className="hint" aria-live="polite">
        {words} {words === 1 ? "word" : "words"}
        {min > 0 ? ` · aim for at least ${min}` : ""}
        {short && words > 0 ? " · keep going" : ""}
        {long ? " · a little long, but you can still submit" : ""}
      </p>
      <p className="hint">
        You can submit at any point. Nothing here is graded for grammar.
      </p>
    </div>
  );
}

function Feedback({
  feedback,
  busy,
  onContinue,
}: {
  feedback: SubmitResult;
  busy: boolean;
  onContinue: () => Promise<void>;
}) {
  // A provisional result is not a verdict, so it must not render as one.
  const tone = feedback.provisional
    ? "notice"
    : feedback.correct
      ? "notice notice-ok"
      : "notice notice-warn";

  const heading = feedback.provisional
    ? "Thanks — here is what we could check"
    : feedback.correct
      ? "Correct"
      : "Not quite";

  return (
    <div className={tone} role="status" aria-live="polite">
      <p>
        <strong>{heading}</strong>
      </p>
      <p>{feedback.explanation}</p>

      {feedback.checks.length > 0 ? (
        <ul className="checks">
          {feedback.checks.map((check) => (
            <li
              key={check.code}
              className={check.passed ? "check-ok" : "check-todo"}
            >
              <span aria-hidden="true">{check.passed ? "✓" : "•"}</span>
              <span className="visually-hidden">
                {check.passed ? "Met:" : "To work on:"}
              </span>{" "}
              {check.message}
            </li>
          ))}
        </ul>
      ) : null}

      <button type="button" onClick={() => void onContinue()} disabled={busy}>
        {busy ? "Loading…" : "Next question"}
      </button>
    </div>
  );
}

const RATINGS = [
  { value: "0", label: "Not at all" },
  { value: "1", label: "With difficulty" },
  { value: "2", label: "Sometimes" },
  { value: "3", label: "Usually" },
  { value: "4", label: "Easily" },
];

function Choices({
  options,
  value,
  onChange,
}: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <div className="choices choices-stack">
      {options.map((option) => (
        <label key={option.value} className="choice">
          <input
            type="radio"
            name="answer"
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </div>
  );
}

function Report({ report }: { report: DiagnosticReport }) {
  return (
    <main id="main" className="narrow">
      <p className="eyebrow">DIAGNOSTIC COMPLETE</p>
      <h1 className="page-title">Here is what we can say so far</h1>

      <div className="panel">
        <p className="muted">Starting level for your content</p>
        <p className="big">{report.startingBand ?? "Not enough answers yet"}</p>
        <p className="hint">
          This decides which material you see first. It is not a score, and not
          a level you have been awarded.
        </p>
      </div>

      <h2>What the answers showed</h2>
      <p className="muted">
        {report.itemsAnswered} questions answered across {report.skillsObserved}{" "}
        skills.
      </p>

      <ul className="outcomes">
        {report.outcomes.map((outcome) => (
          <li key={outcome.skillKey}>
            <div>
              <strong>{outcome.title}</strong>
              <span className="muted"> · {outcome.cefrLevel}</span>
            </div>
            <span className={`pill pill-${outcome.status}`}>
              {statusLabel(outcome.status).short}
            </span>
          </li>
        ))}
      </ul>

      <div className="notice">
        <p>
          <strong>Worth knowing</strong>
        </p>
        <ul>
          {report.caveats.map((caveat) => (
            <li key={caveat}>{caveat}</li>
          ))}
        </ul>
      </div>

      <Link className="button" href="/dashboard">
        Go to my profile
      </Link>
    </main>
  );
}
