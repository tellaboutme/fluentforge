"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  DELETE_CONFIRM_PHRASE,
  deleteAccount,
  downloadExport,
} from "@/lib/api";
import { useSession } from "@/lib/session";
import { ErrorNotice } from "@/components/Status";

/**
 * Taking your data with you, and making it stop existing.
 *
 * `docs/PRIVACY_SAFETY.md` has committed to both since the beginning and
 * neither had a way in. This product stores what a person wrote and said, and
 * that obliges it to make both of those things easy to reach.
 *
 * Two things this screen is careful about.
 *
 * **The export is offered before the deletion, and says why.** Someone who
 * arrives here intending to delete should be told, before the button, that
 * the export is their only chance to keep any of it. Putting that after would
 * be technically true and useless.
 *
 * **Deleting takes deliberate effort and no more.** The password and a typed
 * phrase, because a checkbox is one stray click. But the phrase is matched
 * case- and space-insensitively: it exists to stop an accident, not to test
 * someone's typing at the worst moment to do that.
 */
export default function AccountPage() {
  const router = useRouter();
  const { token, ready, signOut } = useSession();

  const [error, setError] = useState<unknown>(null);
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  if (!ready || !token) return null;

  async function runExport() {
    if (!token) return;
    setExporting(true);
    try {
      await downloadExport(token);
      setExported(true);
      setError(null);
    } catch (cause) {
      setError(cause);
    } finally {
      setExporting(false);
    }
  }

  async function runDelete(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    setDeleting(true);
    try {
      await deleteAccount(token, { password, confirm });
      // Sign out locally as well: the account is gone, and leaving a token in
      // storage would send the next request somewhere that no longer exists.
      signOut();
      router.replace("/");
    } catch (cause) {
      setError(cause);
      setDeleting(false);
    }
  }

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">YOUR DATA</p>
      <h1 className="page-title">Your data</h1>

      {error ? (
        <ErrorNotice error={error} onRetry={() => setError(null)} />
      ) : null}

      <section className="panel">
        <h2>Take a copy</h2>
        <p className="muted">
          Everything we hold: what you wrote and said, the feedback it was
          given, every observation behind your profile, and the reasoning behind
          every plan. It downloads as one file.
        </p>
        <p className="hint">
          The file says what it does not contain, so you can tell what was never
          collected from what was left out.
        </p>
        <p className="actions">
          <button
            type="button"
            className="button"
            disabled={exporting}
            onClick={() => void runExport()}
          >
            {exporting ? "Building your file…" : "Download my data"}
          </button>
        </p>
      </section>

      <section className="panel">
        <h2>Delete your account</h2>
        <p className="muted">
          This removes your account and everything attached to it: your writing,
          your recordings&rsquo; transcripts, your profile, your history. It
          cannot be undone and we cannot get any of it back for you.
        </p>

        {/* Before the button, not after it. Someone who arrived intending to
            delete needs this while it can still help them. */}
        {exported ? null : (
          <p className="hint">
            If you want to keep any of it, download your data first &mdash;
            afterwards there is nothing to download.
          </p>
        )}

        {showDelete ? (
          <form onSubmit={(event) => void runDelete(event)}>
            <label htmlFor="delete-password">
              Your password
              <input
                id="delete-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>

            <label htmlFor="delete-confirm">
              Type <strong>{DELETE_CONFIRM_PHRASE}</strong> to confirm
              <input
                id="delete-confirm"
                type="text"
                required
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
            </label>

            <p className="actions">
              <button type="submit" className="button" disabled={deleting}>
                {deleting ? "Deleting…" : "Delete everything"}
              </button>
              <button
                type="button"
                className="button-quiet"
                onClick={() => setShowDelete(false)}
              >
                Cancel
              </button>
            </p>
          </form>
        ) : (
          <p className="actions">
            <button
              type="button"
              className="button-quiet"
              onClick={() => setShowDelete(true)}
            >
              Delete my account
            </button>
          </p>
        )}
      </section>

      <p className="actions">
        <Link className="button" href="/dashboard">
          Back to today&rsquo;s plan
        </Link>
      </p>
    </main>
  );
}
