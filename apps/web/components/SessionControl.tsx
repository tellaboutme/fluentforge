"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { fetchCurrentSession, startSession } from "@/lib/api";

/**
 * Beginning and ending a sitting.
 *
 * Starting is explicit rather than automatic. The endpoint is idempotent, so
 * the dashboard *could* just call it on load — but then merely opening the
 * app would begin a sitting, and `openMinutes` would count a browser tab left
 * open on a page nobody was reading. `GET /sessions/current` exists so this
 * component can know which control to show without that side effect.
 *
 * Nothing here is required. A learner who never presses either button still
 * has every attempt recorded and every skill updated; what they lose is the
 * summary at the end, which is a nicety rather than the mechanism.
 */
export function SessionControl({ token }: { token: string }) {
  const router = useRouter();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const found = await fetchCurrentSession(token);
        if (!cancelled) setSessionId(found.sessionId);
      } catch {
        // A sitting is optional. Failing to read one must not stop the
        // learner reaching their plan, so this fails quietly and the
        // component renders the start control.
      } finally {
        if (!cancelled) setReady(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token]);

  if (!ready) return null;

  async function begin() {
    setBusy(true);
    try {
      const started = await startSession(token);
      setSessionId(started.sessionId);
    } catch {
      setBusy(false);
    }
  }

  if (sessionId === null) {
    return (
      <p className="actions">
        <button
          type="button"
          className="button-quiet"
          disabled={busy}
          onClick={() => void begin()}
        >
          Start a session
        </button>
      </p>
    );
  }

  return (
    <p className="actions">
      <button
        type="button"
        className="button-quiet"
        onClick={() => router.push(`/finish/${sessionId}`)}
      >
        Finish for today
      </button>
    </p>
  );
}
