"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  answerReview,
  fetchDueReviews,
  type ReviewAnswer,
  type ReviewCard,
  type ReviewGrade,
} from "@/lib/api";
import { reviewModeLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

/**
 * Review player.
 *
 * Two phases per card: recall, then reveal. The answer is not in the DOM until
 * the learner has committed — a card that shows its own answer is not a test
 * of retrieval, which is the entire point of spacing.
 *
 * Self-grading is deliberate. The learner knows whether recall was effortless
 * or a struggle, and that distinction drives the interval more than
 * correctness alone would (`docs/LEARNING_SCIENCE.md`).
 */
type Phase = "loading" | "recall" | "revealed" | "done";

const GRADES: { value: ReviewGrade; label: string; hint: string }[] = [
  { value: "forgot", label: "I didn't know it", hint: "Comes back very soon" },
  { value: "hard", label: "Hard, but I got there", hint: "Comes back soon" },
  { value: "good", label: "I knew it", hint: "Normal interval" },
  { value: "easy", label: "Instantly", hint: "Longer interval" },
];

export default function ReviewPage() {
  const router = useRouter();
  const { token, ready } = useSession();

  const [phase, setPhase] = useState<Phase>("loading");
  const [queue, setQueue] = useState<ReviewCard[]>([]);
  const [dueNow, setDueNow] = useState(0);
  const [completed, setCompleted] = useState(0);
  const [answer, setAnswer] = useState<ReviewAnswer | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    void (async () => {
      try {
        const due = await fetchDueReviews(token);
        if (cancelled) return;
        setQueue(due.cards);
        setDueNow(due.dueNow);
        setPhase(due.cards.length === 0 ? "done" : "recall");
      } catch (cause) {
        if (!cancelled) setError(cause);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, reloadKey]);

  const card = queue[0];

  async function grade(value: ReviewGrade) {
    if (!token || !card) return;
    setBusy(true);
    try {
      setAnswer(await answerReview(token, card.id, value));
      setPhase("revealed");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  function next() {
    const remaining = queue.slice(1);
    setQueue(remaining);
    setAnswer(null);
    setCompleted((count) => count + 1);
    setPhase(remaining.length === 0 ? "done" : "recall");
  }

  if (!ready || (phase === "loading" && !error)) {
    return (
      <main id="main" className="narrow">
        <Loading label="Loading your reviews…" />
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
            setPhase("loading");
            setReloadKey((key) => key + 1);
          }}
        />
      </main>
    );
  }

  if (phase === "done") {
    return (
      <main id="main" className="narrow">
        <p className="eyebrow">REVIEWS</p>
        <h1 className="page-title">
          {completed > 0 ? "That's your reviews done" : "Nothing due right now"}
        </h1>
        <p className="muted">
          {completed > 0
            ? `${completed} ${completed === 1 ? "card" : "cards"} reviewed. Each one comes back when it is most likely to be slipping.`
            : "Spacing means waiting. Cards reappear when they are due, not on demand."}
        </p>
        <Link className="button" href="/dashboard">
          Back to my profile
        </Link>
      </main>
    );
  }

  if (!card) return null;

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">
        REVIEW {completed + 1} OF {Math.min(dueNow, completed + queue.length)}
      </p>
      <p className="hint">{reviewModeLabel(card.reviewMode)}</p>

      <h1 className="question" key={card.id}>
        {card.lemma}
      </h1>
      <p className="muted">{card.pos.replace(/_/g, " ")}</p>

      {phase === "recall" ? (
        <>
          <p className="hint">
            Bring the meaning to mind before you grade yourself. The effort is
            what makes it stick.
          </p>
          <fieldset>
            <legend className="visually-hidden">
              How well did you recall it?
            </legend>
            <div className="choices choices-stack">
              {GRADES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className="button-quiet grade"
                  disabled={busy}
                  onClick={() => void grade(option.value)}
                >
                  <span>{option.label}</span>
                  <span className="hint">{option.hint}</span>
                </button>
              ))}
            </div>
          </fieldset>
        </>
      ) : null}

      {phase === "revealed" && answer ? (
        <div className="notice" role="status" aria-live="polite">
          <p>
            <strong>{answer.meaning}</strong>
          </p>
          <p className="muted">{answer.example}</p>
          <p className="hint">{answer.explanation}</p>
          <button type="button" onClick={next} disabled={busy}>
            {queue.length > 1 ? "Next card" : "Finish"}
          </button>
        </div>
      ) : null}
    </main>
  );
}
