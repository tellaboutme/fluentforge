"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { fetchSkillMap, type SkillMap, type SkillMapNode } from "@/lib/api";
import { domainLabel, levelDisplay, statusLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

/**
 * The skill graph, as the learner sees it.
 *
 * `curriculum/graph.yml` holds 119 authored claims about what depends on
 * what. Until the endpoint existed the only thing that read them was the
 * planner, so a learner could be told an item was in their plan because a
 * prerequisite was weak and had no way to see which one or why anyone
 * believed it.
 *
 * Three decisions this screen makes.
 *
 * **It is a list, not a drawing.** Fifty-odd nodes and a hundred edges laid
 * out as a diagram would be unreadable, and — worse — would look like more
 * precision than exists. These are arguments, not measurements, and a
 * carefully routed graph would dress them up as a discovered structure.
 *
 * **The caveats are at the top, not in a footnote.** They are the point. The
 * first one is permanent.
 *
 * **Nothing shows a level the learner has not earned.** `cefrEstimate` stays
 * null until a skill is supported, and a grid of dashes is the honest render
 * of that even though it looks unfinished.
 */
export default function SkillsPage() {
  const router = useRouter();
  const { token, ready } = useSession();

  const [map, setMap] = useState<SkillMap | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [onlyBlocked, setOnlyBlocked] = useState(false);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    void (async () => {
      try {
        const found = await fetchSkillMap(token);
        if (!cancelled) {
          setMap(found);
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

  const titles = useMemo(() => {
    const lookup = new Map<string, string>();
    for (const node of map?.nodes ?? []) lookup.set(node.key, node.title);
    return lookup;
  }, [map]);

  const byDomain = useMemo(() => {
    const groups = new Map<string, SkillMapNode[]>();
    for (const node of map?.nodes ?? []) {
      if (onlyBlocked && node.blockedBy.length === 0) continue;
      const bucket = groups.get(node.domain) ?? [];
      bucket.push(node);
      groups.set(node.domain, bucket);
    }
    return [...groups.entries()].sort(([a], [b]) =>
      domainLabel(a).localeCompare(domainLabel(b)),
    );
  }, [map, onlyBlocked]);

  if (!ready || (loading && !error)) {
    return (
      <main id="main" className="narrow">
        <Loading label="Drawing out what depends on what…" />
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

  if (!token || !map) return null;

  const blockedCount = map.nodes.filter(
    (node) => node.blockedBy.length > 0,
  ).length;

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">YOUR SKILLS</p>
      <h1 className="page-title">What depends on what</h1>

      {/* The caveats come before the map, not after it. */}
      <div className="notice" role="note">
        {map.caveats.map((caveat) => (
          <p key={caveat} className="hint">
            {caveat}
          </p>
        ))}
      </div>

      {blockedCount > 0 ? (
        <p className="actions">
          <button
            type="button"
            className="button-quiet"
            aria-pressed={onlyBlocked}
            onClick={() => setOnlyBlocked((value) => !value)}
          >
            {onlyBlocked
              ? "Show every skill"
              : `Show only what is waiting on something (${blockedCount})`}
          </button>
        </p>
      ) : null}

      {byDomain.length === 0 ? (
        <p className="muted">Nothing is waiting on anything right now.</p>
      ) : (
        byDomain.map(([domain, nodes]) => (
          <section className="panel" key={domain}>
            <h2>{domainLabel(domain)}</h2>
            <ul className="plan-list">
              {nodes.map((node) => (
                <li key={node.key}>
                  <Skill node={node} titles={titles} />
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      <p className="actions">
        <Link className="button" href="/dashboard">
          Back to today&rsquo;s plan
        </Link>
      </p>
    </main>
  );
}

function Skill({
  node,
  titles,
}: {
  node: SkillMapNode;
  titles: Map<string, string>;
}) {
  const status = statusLabel(node.status);

  return (
    <>
      <div className="plan-main">
        <strong>{node.title}</strong>
        <span className="plan-kind">{status.short}</span>
      </div>

      <p className="plan-why">
        {node.level} · level shown: {levelDisplay(node.cefrEstimate)} ·{" "}
        {node.evidenceCount === 0
          ? "never looked at"
          : `${node.evidenceCount} pieces of evidence`}
      </p>

      {/* "We have never looked" and "you cannot do this" are different
          claims, and the second is the one a blank grid implies. */}
      {node.status === "unobserved" ? (
        <p className="plan-why">
          Nothing here says you cannot do this. It has not been looked at.
        </p>
      ) : null}

      {node.blockedBy.length > 0 ? (
        <p className="plan-why">
          Likely to be held up by{" "}
          {node.blockedBy.map((key) => titles.get(key) ?? key).join(", ")}.
        </p>
      ) : null}

      {node.blocking.length > 0 ? (
        <p className="plan-why">
          Working on this should help with{" "}
          {node.blocking.map((key) => titles.get(key) ?? key).join(", ")}.
        </p>
      ) : null}
    </>
  );
}
