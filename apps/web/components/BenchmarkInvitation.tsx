"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  fetchBenchmarkEligibility,
  type BenchmarkEligibility,
} from "@/lib/api";

/**
 * A benchmark, offered on the dashboard when one is due.
 *
 * Only when one is due. A permanent "take a benchmark" button would let a
 * learner take one whenever they felt ready, which measures confidence
 * rather than level -- the single thing the whole feature is arranged to
 * avoid.
 *
 * When one is not due, this renders nothing at all rather than a disabled
 * button with an explanation. A control that is visible but unusable invites
 * someone to work out how to make it usable, and there is nothing here worth
 * gaming: the benchmark exists to be accurate, not to be earned.
 *
 * A failure to check is also silent. The dashboard is the learner's plan for
 * the day; an error about a feature they were not asking for would be noise.
 */
export function BenchmarkInvitation({ token }: { token: string }) {
  const [eligibility, setEligibility] = useState<BenchmarkEligibility | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const verdict = await fetchBenchmarkEligibility(token);
        if (!cancelled) setEligibility(verdict);
      } catch {
        // Deliberately silent. See above.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token]);

  if (!eligibility?.due) return null;

  return (
    <section className="panel" aria-labelledby="benchmark-title">
      <p className="eyebrow">DUE</p>
      <h2 id="benchmark-title">A benchmark is due</h2>
      <p>
        Questions you have never seen, with no help available. It is the only
        thing here that can move your profile down as well as up.
      </p>
      <p className="actions">
        <Link className="button" href="/benchmark">
          Take the benchmark
        </Link>
      </p>
    </section>
  );
}
