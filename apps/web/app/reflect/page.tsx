"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import {
  fetchReflectionPrompt,
  saveReflection,
  type ReflectionPrompt,
} from "@/lib/api";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

/**
 * Reflection: the last plan kind to get a screen.
 *
 * Every session template has reserved four minutes for this since Milestone
 * 1, and the slot has rendered unlinked ever since because nothing existed
 * to open.
 *
 * The material is the point. "How do you feel your learning is going?"
 * produces nothing worth reading, and a learner asked it twice stops
 * answering. So the page shows what the system has actually noticed --
 * the errors that keep recurring, what has not been touched lately, and how
 * much of their own work nothing has judged -- and asks what they make of
 * it.
 *
 * Nothing here is scored, and the page says so. This is the one place in
 * the product where a learner writes and nothing at all checks it. Running
 * the writing checks over a reflection would teach them to write reflections
 * that pass checks.
 */
export default function ReflectPage() {
  const router = useRouter();
  const { token, ready } = useSession();

  const [prompt, setPrompt] = useState<ReflectionPrompt | null>(null);
  const [note, setNote] = useState("");
  const [saved, setSaved] = useState(false);
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
        const next = await fetchReflectionPrompt(token);
        if (!cancelled) {
          setPrompt(next);
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
        <Loading label="Gathering what we noticed…" />
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

  if (!token || !prompt) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setBusy(true);
    try {
      await saveReflection(token, note);
      setSaved(true);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  const nothingNoticed =
    prompt.recurringErrors.length === 0 &&
    prompt.untouchedSkills.length === 0 &&
    prompt.unjudgedCount === 0;

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">REFLECT</p>
      <h1 className="page-title">What we noticed</h1>

      <article className="panel">
        {prompt.recurringErrors.length > 0 ? (
          <>
            <h2 className="subheading">Coming up more than once</h2>
            <ul className="checks">
              {prompt.recurringErrors.map((item) => (
                <li key={item.code}>
                  <strong>{item.label}</strong>
                  {item.blocksMeaning ? (
                    <span className="question-type"> gets in the way</span>
                  ) : null}
                  <br />
                  <span className="muted">
                    {item.description} &mdash; {item.occurrences} times.
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : null}

        {prompt.untouchedSkills.length > 0 ? (
          <>
            <h2 className="subheading">Not looked at for a while</h2>
            <ul>
              {prompt.untouchedSkills.map((skill) => (
                <li key={skill}>{skill}</li>
              ))}
            </ul>
          </>
        ) : null}

        {/* The product's own blind spot, said out loud. Someone reflecting
            on their progress should not read silence as approval. */}
        {prompt.unjudgedCount > 0 ? (
          <p className="muted">
            {prompt.unjudgedCount} piece
            {prompt.unjudgedCount === 1 ? "" : "s"} of your writing or speech
            went unjudged &mdash; the checks confirmed you produced the
            language, and nothing assessed how good it was. That is a limit of
            this app, not a verdict on the work.
          </p>
        ) : null}

        {nothingNoticed ? (
          <p className="muted">
            Nothing has recurred and nothing has gone stale. There may be less
            to say than usual, and that is a fine answer.
          </p>
        ) : null}
      </article>

      {prompt.previousNote ? (
        <article className="panel">
          <h2 className="subheading">Last time you wrote</h2>
          <blockquote>{prompt.previousNote}</blockquote>
        </article>
      ) : null}

      {!saved ? (
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="note">What do you make of it?</label>
            <textarea
              id="note"
              name="note"
              rows={8}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
            {/* Non-negotiable. This is the one place a learner writes and
                nothing judges it, and they have to be able to trust that. */}
            <p className="hint">
              Nothing here is checked, corrected, or counted towards any skill.
              It is for you. There is no minimum &mdash; &ldquo;nothing new this
              week&rdquo; is a real answer.
            </p>
          </div>

          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save this"}
          </button>
        </form>
      ) : (
        <div className="notice" role="status">
          <p>
            <strong>Saved.</strong> Nothing was scored and your profile is
            unchanged &mdash; that is what this is for.
          </p>
          <p className="actions">
            <Link className="button" href="/dashboard">
              Back to today&rsquo;s plan
            </Link>
          </p>
        </div>
      )}
    </main>
  );
}
