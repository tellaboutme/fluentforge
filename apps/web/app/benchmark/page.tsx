"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import {
  answerBenchmarkItem,
  completeBenchmark,
  fetchBenchmarkEligibility,
  startBenchmark,
  type BenchmarkEligibility,
  type BenchmarkItem,
  type BenchmarkResult,
  type BenchmarkSession,
} from "@/lib/api";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

/**
 * The benchmark screen.
 *
 * Deliberately unlike every other activity in the product, and the
 * differences are the feature rather than styling:
 *
 * - **No hint, and nothing to reveal.** Other screens offer an explanation
 *   or a transcript and record that it was taken. Here there is nothing to
 *   take, so there is no control for it.
 * - **No answer feedback between items.** Being told item three was wrong
 *   changes how item four is answered, and the measurement is of the set.
 * - **The result can be a fall, and says so.** Everything else in the
 *   product only ever adds. A screen that hid a drop would turn the one
 *   measurement into another form of encouragement.
 * - **It cannot be started on demand.** If it is not due, the page says what
 *   has to happen instead of offering a button that fails.
 */
export default function BenchmarkPage() {
  const router = useRouter();
  const { token, ready } = useSession();

  const [eligibility, setEligibility] = useState<BenchmarkEligibility | null>(
    null,
  );
  const [session, setSession] = useState<BenchmarkSession | null>(null);
  const [result, setResult] = useState<BenchmarkResult | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    void (async () => {
      try {
        const verdict = await fetchBenchmarkEligibility(token);
        if (!cancelled) {
          setEligibility(verdict);
          setError(null);
        }
      } catch (cause) {
        if (!cancelled) setError(cause);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token]);

  if (!ready || (loading && !error)) {
    return (
      <main id="main" className="narrow">
        <Loading label="Checking…" />
      </main>
    );
  }

  if (error) {
    return (
      <main id="main" className="narrow">
        <ErrorNotice error={error} onRetry={() => setError(null)} />
      </main>
    );
  }

  if (!token) return null;

  async function begin() {
    if (!token) return;
    setBusy(true);
    try {
      setSession(await startBenchmark(token));
      setIndex(0);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function answer(item: BenchmarkItem, response: string) {
    if (!token || !session) return;
    setBusy(true);
    try {
      const outcome = await answerBenchmarkItem(token, session.sessionId, {
        itemKey: item.key,
        response,
      });
      // Deliberately not shown. Being told item three was wrong changes how
      // item four is answered, and the measurement is of the whole set.
      if (outcome.remaining === 0) {
        setResult(await completeBenchmark(token, session.sessionId));
      } else {
        setIndex((current) => current + 1);
      }
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (result) return <Outcome result={result} />;
  if (session) {
    const item = session.items[index];
    if (!item) return <Loading label="Finishing…" />;
    return (
      <Question
        // Keyed on the item so React remounts between questions. The
        // alternative -- clearing the fields in an effect -- sets state
        // during render and can cascade; this way the component simply has
        // never seen a previous answer.
        key={item.key}
        item={item}
        position={index + 1}
        total={session.items.length}
        busy={busy}
        onAnswer={(response) => void answer(item, response)}
      />
    );
  }

  return (
    <Invitation
      eligibility={eligibility}
      busy={busy}
      onStart={() => void begin()}
    />
  );
}

function Invitation({
  eligibility,
  busy,
  onStart,
}: {
  eligibility: BenchmarkEligibility | null;
  busy: boolean;
  onStart: () => void;
}) {
  return (
    <main id="main" className="narrow">
      <p className="eyebrow">BENCHMARK</p>
      <h1 className="page-title">A check on what you can do unaided</h1>

      <article className="panel">
        <p>
          Everything else here records what you practised, usually with
          something to lean on &mdash; an explanation on screen, a text you had
          already read, a hint you took. A benchmark records what you can do
          with none of that.
        </p>
        <p>
          It uses questions you have never seen, and there is no help available.
          It is the only thing in this app that can move your profile{" "}
          <strong>down</strong> as well as up, and that is the point: a check
          that could only agree with you would not be a check.
        </p>
        {eligibility ? (
          <p className={eligibility.due ? "" : "muted"}>{eligibility.reason}</p>
        ) : null}
      </article>

      <p className="actions">
        {eligibility?.due ? (
          <button type="button" onClick={onStart} disabled={busy}>
            {busy ? "Preparing…" : "Start the benchmark"}
          </button>
        ) : null}{" "}
        <Link className="button" href="/dashboard">
          Back to today&rsquo;s plan
        </Link>
      </p>
    </main>
  );
}

function Question({
  item,
  position,
  total,
  busy,
  onAnswer,
}: {
  item: BenchmarkItem;
  position: number;
  total: number;
  busy: boolean;
  onAnswer: (response: string) => void;
}) {
  const [choice, setChoice] = useState("");
  const [typed, setTyped] = useState("");

  const closed = item.options.length > 0;
  const response = closed ? choice : typed;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!response.trim()) return;
    onAnswer(response);
  }

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">BENCHMARK</p>
      <h1 className="page-title">
        Question {position} of {total}
      </h1>
      {/* No score, and no "correct so far". Progress, not performance. */}
      <p className="hint" aria-live="polite">
        No help is available here, and you will see the result at the end.
      </p>

      <form onSubmit={submit}>
        <fieldset>
          <legend>{item.prompt}</legend>
          {item.instructions ? (
            <p className="muted">{item.instructions}</p>
          ) : null}

          {closed ? (
            item.options.map((option) => (
              <label key={option} className="choice">
                <input
                  type="radio"
                  name="response"
                  value={option}
                  checked={choice === option}
                  onChange={() => setChoice(option)}
                />
                {option}
              </label>
            ))
          ) : (
            <div className="field">
              <label htmlFor="typed">Your answer</label>
              <input
                id="typed"
                name="typed"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
              />
            </div>
          )}
        </fieldset>

        <button type="submit" disabled={busy || !response.trim()}>
          {busy ? "Saving…" : position === total ? "Finish" : "Next question"}
        </button>
      </form>
    </main>
  );
}

function Outcome({ result }: { result: BenchmarkResult }) {
  return (
    <main id="main" className="narrow">
      <p className="eyebrow">BENCHMARK</p>
      <h1 className="page-title">What this measured</h1>

      <div className="notice" role="status">
        <p>
          <strong>
            You answered {result.correct} of {result.answered} unaided, at{" "}
            {result.band}.
          </strong>
        </p>
        <p className="muted">
          This carries more weight than ordinary practice, because nothing was
          available to help and none of the questions were ones you had seen.
        </p>
      </div>

      {/* The part that makes this a measurement. Never hidden, never softened
          into "keep practising". */}
      {result.lowered.length > 0 ? (
        <div className="notice notice-warn">
          <p>
            <strong>
              Your estimate went down for{" "}
              {result.lowered.length === 1
                ? "one skill"
                : `${result.lowered.length} skills`}
              .
            </strong>
          </p>
          <ul>
            {result.lowered.map((skill) => (
              <li key={skill}>{skill}</li>
            ))}
          </ul>
          <p>
            That is the benchmark doing its job. Practice can only ever add to a
            profile; this is the one thing that can correct it, and a correction
            downwards is as useful as one upwards.
          </p>
        </div>
      ) : (
        <p className="muted">
          Nothing went down. Your profile held up under a harder test than it is
          usually given.
        </p>
      )}

      <p className="actions">
        <Link className="button" href="/dashboard">
          Back to today&rsquo;s plan
        </Link>
      </p>
    </main>
  );
}
