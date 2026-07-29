"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  REPORT_REASONS,
  fetchAttemptFeedback,
  fetchHistory,
  reportFeedback,
  type AttemptFeedback,
  type HistoryItem,
  type ReportReason,
  type ReportResult,
} from "@/lib/api";
import { kindLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

/**
 * A learner's own past work.
 *
 * Everything they have written, said or answered was stored and unreachable:
 * feedback appeared once, on the screen that produced it, and then it was
 * gone. For a product whose central claim is that the profile is built from
 * evidence the learner actually produced, that is a strange thing for them
 * not to be able to look at.
 *
 * What this screen is careful about: the feedback shown is what was
 * *recorded*, not what would be produced today, and it says so with a date.
 * The checks, the curriculum version and the evaluator may all have moved
 * since. Presenting an old verdict as current would be quietly dishonest in
 * the one place a learner comes to check what they were told.
 */
export default function HistoryPage() {
  const router = useRouter();
  const { token, ready } = useSession();

  const [items, setItems] = useState<HistoryItem[]>([]);
  const [open, setOpen] = useState<AttemptFeedback | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [reporting, setReporting] = useState(false);
  const [reason, setReason] = useState<ReportReason>("wrong_verdict");
  const [note, setNote] = useState("");
  const [reported, setReported] = useState<ReportResult | null>(null);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    void (async () => {
      try {
        const page = await fetchHistory(token);
        if (!cancelled) {
          setItems(page.items);
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
        <Loading label="Finding your work…" />
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

  async function show(attemptId: string) {
    if (!token) return;
    try {
      setOpen(await fetchAttemptFeedback(token, attemptId));
      // A fresh attempt means a fresh disagreement, not the previous one's
      // outcome left on screen under someone else's work.
      setReporting(false);
      setReported(null);
      setNote("");
      setReason("wrong_verdict");
    } catch (cause) {
      setError(cause);
    }
  }

  async function submitReport(event: React.FormEvent) {
    event.preventDefault();
    if (!token || !open) return;
    try {
      setReported(
        await reportFeedback(token, open.attemptId, { reason, note }),
      );
      setReporting(false);
      setError(null);
    } catch (cause) {
      setError(cause);
    }
  }

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">YOUR WORK</p>
      <h1 className="page-title">What you have done</h1>

      {items.length === 0 ? (
        <p className="muted">
          Nothing yet. Anything you write, say or answer will appear here, with
          the feedback it was given at the time.
        </p>
      ) : (
        <ol className="plan-list">
          {items.map((item) => (
            <li key={item.attemptId}>
              <div className="plan-main">
                <button
                  type="button"
                  className="link-button"
                  onClick={() => void show(item.attemptId)}
                >
                  <strong>{item.summary}</strong>
                </button>
                <span className="plan-kind">
                  {kindLabel(item.activityType)}
                </span>
              </div>
              <p className="plan-why">
                {new Date(item.submittedAt).toLocaleString()}
                {/* No score for unjudged work. Showing a blank one would
                    invent a verdict nobody gave. */}
                {item.wasJudged && item.score !== null
                  ? ` · checks passed: ${Math.round(item.score * 100)}%`
                  : " · nothing judged this"}
              </p>
            </li>
          ))}
        </ol>
      )}

      {open ? (
        <div className="notice" role="status">
          <h2 className="subheading">
            {new Date(open.submittedAt).toLocaleString()}
          </h2>

          {/* The honesty this screen exists for. */}
          {open.isStale ? (
            <p className="hint">
              This is the feedback as it was recorded
              {open.evaluatorId ? ` by ${open.evaluatorId}` : ""}. The checks
              may have changed since, so read it as a record of what you were
              told rather than as a verdict on your work today.
            </p>
          ) : (
            <p className="hint">
              Nothing judged this, so there is no feedback to show &mdash; only
              what you wrote.
            </p>
          )}

          <pre className="transcript">
            {JSON.stringify(open.response, null, 2)}
          </pre>

          {/* `docs/AI_TUTOR_BEHAVIOR.md` calls AI judgement an accelerator
              rather than an authority. That is only true if the
              disagreement has somewhere to go. */}
          {reported ? (
            <div role="status">
              {reported.notes.map((line) => (
                <p key={line} className="hint">
                  {line}
                </p>
              ))}
            </div>
          ) : reporting ? (
            <form onSubmit={(event) => void submitReport(event)}>
              <fieldset>
                <legend>What is wrong with this?</legend>
                {REPORT_REASONS.map((option) => (
                  <label key={option.key} htmlFor={`reason-${option.key}`}>
                    <input
                      id={`reason-${option.key}`}
                      type="radio"
                      name="reason"
                      value={option.key}
                      checked={reason === option.key}
                      onChange={() => setReason(option.key)}
                    />
                    {option.label}
                  </label>
                ))}
              </fieldset>

              <label htmlFor="report-note">
                Anything you want to add (optional)
                <textarea
                  id="report-note"
                  rows={3}
                  maxLength={2000}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </label>

              <p className="actions">
                <button type="submit" className="button">
                  Send
                </button>
                <button
                  type="button"
                  className="button-quiet"
                  onClick={() => setReporting(false)}
                >
                  Never mind
                </button>
              </p>
            </form>
          ) : (
            <p className="actions">
              <button
                type="button"
                className="button-quiet"
                onClick={() => setReporting(true)}
              >
                This feedback is wrong
              </button>
            </p>
          )}

          <button type="button" onClick={() => setOpen(null)}>
            Close
          </button>
        </div>
      ) : null}

      <p className="actions">
        <Link className="button" href="/dashboard">
          Back to today&rsquo;s plan
        </Link>
      </p>
    </main>
  );
}
