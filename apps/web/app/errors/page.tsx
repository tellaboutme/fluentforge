"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { fetchErrorLog, type ErrorLog, type ErrorPattern } from "@/lib/api";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

/**
 * Everything the system believes about a learner's recurring mistakes.
 *
 * The reflection screen shows the top three. This is the whole list, because
 * a learner should be able to see the working rather than the conclusion —
 * the same reason `docs/ADAPTIVE_ENGINE.md` forbids an opaque priority score.
 *
 * Two things this screen is careful about.
 *
 * **It never shows the raw code.** `grammar.tense.perfect_vs_past` is a
 * machine identifier and reads as one. The label is what a person can act on.
 *
 * **It says why an error has no practice, in words.** Three different gaps
 * hide behind a missing remedy — nobody has written the unit yet, the code
 * names a skill rather than a practisable feature, or the thing needs sound
 * and this product cannot teach it by reading and typing. A dash would
 * suggest all three were the same kind of backlog. The third is not: it needs
 * an audio pipeline that does not exist.
 */
export default function ErrorsPage() {
  const router = useRouter();
  const { token, ready } = useSession();

  const [log, setLog] = useState<ErrorLog | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    void (async () => {
      try {
        const found = await fetchErrorLog(token);
        if (!cancelled) {
          setLog(found);
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
        <Loading label="Gathering what keeps coming up…" />
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

  if (!token || !log) return null;

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">YOUR ERRORS</p>
      <h1 className="page-title">What keeps coming up</h1>

      {log.items.length === 0 ? (
        <p className="muted">
          Nothing recorded yet. This fills up as you work, and an empty list
          this early means we have not seen enough to say anything &mdash; not
          that you are making no mistakes.
        </p>
      ) : (
        <>
          <p className="hint">
            These are patterns, not individual slips. Something appears here
            when the same kind of mistake has happened more than once.
          </p>

          <ul className="plan-list">
            {log.items.map((pattern) => (
              <li key={pattern.code}>
                <Pattern pattern={pattern} />
              </li>
            ))}
          </ul>

          {log.withoutRemedy > 0 ? (
            <p className="hint">
              {log.withoutRemedy === 1
                ? "One of these has nothing to open yet."
                : `${log.withoutRemedy} of these have nothing to open yet.`}{" "}
              Each one says why below. It is a gap in what we have built, not a
              judgement about whether you could fix it.
            </p>
          ) : null}
        </>
      )}

      <p className="actions">
        <Link className="button" href="/dashboard">
          Back to today&rsquo;s plan
        </Link>
      </p>
    </main>
  );
}

function Pattern({ pattern }: { pattern: ErrorPattern }) {
  return (
    <>
      <div className="plan-main">
        {/* Never `pattern.code`. */}
        <strong>{pattern.label}</strong>
        {pattern.blocksMeaning ? (
          <span className="plan-kind">Changes the meaning</span>
        ) : null}
      </div>

      <p className="plan-why">{pattern.description}</p>

      <p className="plan-why">
        {pattern.occurrences === 1
          ? "Seen once"
          : `Seen ${pattern.occurrences} times`}
        {" · most recently "}
        {new Date(pattern.lastSeenAt).toLocaleDateString()}
        {/* A learner who sees something in this list that never appears in
            their plan deserves to know that is deliberate. */}
        {pattern.scheduled
          ? " · in your practice queue"
          : " · not being drilled yet"}
      </p>

      {pattern.remedyKey ? (
        <p className="actions">
          <Link
            className="button"
            href={`/activity/${encodeURIComponent(pattern.remedyKey)}`}
          >
            {openLabel(pattern)}
          </Link>
        </p>
      ) : (
        <p className="hint">{whyNothing(pattern)}</p>
      )}
    </>
  );
}

/**
 * What the button does, honestly.
 *
 * A comprehension error opens another text or clip rather than an
 * explanation, and calling that "practise this" would misdescribe it: nothing
 * is being explained, the learner is meeting the same kind of question on a
 * passage they have not seen.
 */
function openLabel(pattern: ErrorPattern): string {
  if (pattern.remedyType === "reading_task") return "Read another one";
  if (pattern.remedyType === "listening_task") return "Listen to another one";
  return `Practise: ${pattern.remedyTitle ?? "this"}`;
}

/** Three different gaps, and they are not interchangeable. */
function whyNothing(pattern: ErrorPattern): string {
  switch (pattern.noRemedyReason) {
    case "needs_speech":
      return "There is nothing to open for this one. Practice here is read and typed, and that cannot teach a sound — it would need recording and listening back, which this product does not do yet.";
    case "no_feature":
      return "This was recorded before we could name mistakes precisely, so it says an item went wrong without saying what about it. It still counts towards practice; it just cannot point anywhere specific.";
    default:
      return "Nothing has been written that practises this yet. It is on the list.";
  }
}
