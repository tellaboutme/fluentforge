"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { completeSession, type SessionSummary } from "@/lib/api";
import { kindLabel, statusLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

/**
 * The end of a sitting.
 *
 * This is the screen most likely to lie. The end of a session is where every
 * learning product reaches for a number — points, a streak, a percentage
 * gained — and every one of those would be invented here: derived from a
 * handful of attempts, presented as measured, and impossible to argue with.
 * `docs/ADAPTIVE_ENGINE.md` forbids exactly that.
 *
 * So this screen reports what happened and stops. Each skill shows the
 * evidence recorded and how many different situations it now stands on, which
 * is the quantity the mastery model actually gates on and the one a learner
 * can do something about. The notes say plainly that one sitting proves
 * nothing on its own, and they render at the top.
 *
 * Reloading is safe: completing a completed sitting returns the original
 * summary with the original end time. That idempotency is why this can be a
 * page with an address rather than a modal that must not be dismissed.
 */
export default function FinishPage() {
  const router = useRouter();
  const params = useParams<{ sessionId: string }>();
  const { token, ready } = useSession();

  const [summary, setSummary] = useState<SessionSummary | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const sessionId = params?.sessionId;

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token || !sessionId) return;
    let cancelled = false;

    void (async () => {
      try {
        const found = await completeSession(token, sessionId);
        if (!cancelled) {
          setSummary(found);
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
  }, [token, sessionId]);

  if (!ready || (loading && !error)) {
    return (
      <main id="main" className="narrow">
        <Loading label="Wrapping up…" />
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

  if (!token || !summary) return null;

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">SESSION FINISHED</p>
      <h1 className="page-title">What you did</h1>

      {/* Before the numbers, not after them. */}
      <div className="notice" role="note">
        {summary.notes.map((note) => (
          <p key={note} className="hint">
            {note}
          </p>
        ))}
      </div>

      {summary.activities.length > 0 ? (
        <section className="panel">
          <h2>
            {summary.activities.length === 1
              ? "One thing finished"
              : `${summary.activities.length} things finished`}
          </h2>

          <ul className="plan-list">
            {summary.activities.map((activity) => (
              <li key={`${activity.activityKey}-${activity.submittedAt}`}>
                <div className="plan-main">
                  <strong>{activity.activityKey}</strong>
                  <span className="plan-kind">
                    {kindLabel(activity.activityType)}
                  </span>
                </div>
                <p className="plan-why">
                  {activity.wasJudged && activity.score !== null
                    ? `Checks passed: ${Math.round(activity.score * 100)}%`
                    : "Nothing judged this"}
                  {activity.onPlan ? "" : " · not on today's plan"}
                </p>
              </li>
            ))}
          </ul>

          {/* Named for what it is. Someone who started a sitting and made
              lunch did not study for forty minutes, and this product does
              not measure time on task at all. */}
          <p className="hint">
            The session was open for {summary.openMinutes} minutes. That is
            elapsed time, not time spent working &mdash; we do not measure that.
          </p>
        </section>
      ) : null}

      {summary.skills.length > 0 ? (
        <section className="panel">
          <h2>What this told us</h2>

          <ul className="plan-list">
            {summary.skills.map((skill) => (
              <li key={skill.key}>
                <div className="plan-main">
                  <strong>{skill.title}</strong>
                  <span className="plan-kind">
                    {statusLabel(skill.status).short}
                  </span>
                </div>
                <p className="plan-why">
                  {skill.evidenceRecorded === 1
                    ? "One piece of evidence just now"
                    : `${skill.evidenceRecorded} pieces of evidence just now`}
                  {" · seen in "}
                  {skill.distinctContexts === 1
                    ? "1 different situation so far"
                    : `${skill.distinctContexts} different situations so far`}
                </p>
                {/* The model's own terms, in words. Not a percentage: a
                    number here would read as a score to beat. */}
                {skill.needs ? <p className="plan-why">{skill.needs}</p> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="actions">
        <Link className="button" href="/dashboard">
          Back to today&rsquo;s plan
        </Link>
        <Link className="button-quiet" href="/reflect">
          Write a reflection
        </Link>
      </p>
    </main>
  );
}
