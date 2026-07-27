"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchTodayPlan, type DailyPlan, type PlanItem } from "@/lib/api";
import { kindLabel } from "@/lib/labels";

import { ErrorNotice, Loading } from "./Status";

/**
 * Today's plan.
 *
 * Every item shows why it is there. `docs/ADAPTIVE_ENGINE.md` requires the UI
 * to answer "why is this in today's plan?", and a learner who cannot see the
 * reasoning has no way to disagree with it.
 */
export function TodayPlan({ token }: { token: string }) {
  const [plan, setPlan] = useState<DailyPlan | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const next = await fetchTodayPlan(token);
        if (!cancelled) {
          setPlan(next);
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
  }, [token, reloadKey]);

  if (loading) return <Loading label="Building today's plan…" />;

  if (error) {
    return (
      <ErrorNotice
        error={error}
        onRetry={() => {
          setLoading(true);
          setError(null);
          setReloadKey((key) => key + 1);
        }}
      />
    );
  }

  if (!plan || plan.items.length === 0) {
    return (
      <section className="panel" aria-labelledby="plan-title">
        <p className="eyebrow">TODAY</p>
        <h2 id="plan-title">No plan yet</h2>
        <p className="muted">
          Once the diagnostic has given us something to work from, a plan will
          appear here.
        </p>
      </section>
    );
  }

  return (
    <section className="panel" aria-labelledby="plan-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">TODAY</p>
          <h2 id="plan-title">{planHeading(plan)}</h2>
        </div>
        <span>
          {plan.totalMinutes} of {plan.requestedMinutes} min
        </span>
      </div>

      <ol className="plan-list">
        {plan.items.map((item) => (
          <PlanRow key={item.activityKey} item={item} />
        ))}
      </ol>

      {plan.items.some((item) => item.kind === "review") ? (
        <p className="actions">
          <Link className="button" href="/review">
            Start your reviews
          </Link>
        </p>
      ) : null}

      {plan.unmetConstraints.length > 0 ? (
        <div className="notice notice-warn">
          <p>
            <strong>This plan is thinner than it should be</strong>
          </p>
          <ul>
            {plan.unmetConstraints.map((constraint) => (
              <li key={constraint}>{constraint}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="hint">
        Plans are built from what you have actually shown, not from how long you
        have been here.
      </p>
    </section>
  );
}

/** Prefixes the activity player can open. Kept beside the router that reads
 * them so adding a kind is one change, not two. */
const OPENABLE_PREFIXES = [
  "read:",
  "study:",
  "write:",
  "listen:",
  "speak:",
  "mediate:",
];

function openableHref(item: PlanItem): string | null {
  if (OPENABLE_PREFIXES.some((prefix) => item.activityKey.startsWith(prefix))) {
    return `/activity/${encodeURIComponent(item.activityKey)}`;
  }
  if (item.kind === "review") return "/review";
  return null;
}

function planHeading(plan: DailyPlan): string {
  if (plan.hasReceptive && plan.hasProductive) {
    return "From understanding to using";
  }
  if (plan.hasProductive) return "Producing language today";
  return "Taking things in today";
}

function PlanRow({ item }: { item: PlanItem }) {
  // Only some activity kinds can be opened yet. A link that goes nowhere is
  // worse than plain text, so the rest stay unlinked until they exist.
  const href = openableHref(item);

  return (
    <li>
      <div className="plan-main">
        {href ? (
          <Link href={href}>
            <strong>{item.title}</strong>
          </Link>
        ) : (
          <strong>{item.title}</strong>
        )}
        <span className="plan-kind">{kindLabel(item.kind)}</span>
      </div>
      <p className="plan-why">{item.explanation}</p>
      <span className="plan-minutes">{item.estimatedMinutes} min</span>
    </li>
  );
}
