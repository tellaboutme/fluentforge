"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type { Profile, SkillEstimate } from "@fluentforge/contracts";

import { fetchProfile } from "@/lib/api";
import {
  confidenceLabel,
  domainLabel,
  levelDisplay,
  statusLabel,
} from "@/lib/labels";
import { useSession } from "@/lib/session";
import { Empty, ErrorNotice, Loading } from "@/components/Status";
import { SessionControl } from "@/components/SessionControl";
import { BenchmarkInvitation } from "@/components/BenchmarkInvitation";
import { TodayPlan } from "@/components/TodayPlan";

export default function DashboardPage() {
  const router = useRouter();
  const { token, ready, signOut } = useSession();

  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    // The request is awaited before any setState, so nothing updates state
    // synchronously during the effect. `cancelled` guards against a response
    // arriving after unmount or after the token changed.
    let cancelled = false;

    void (async () => {
      try {
        const next = await fetchProfile(token);
        if (!cancelled) {
          setProfile(next);
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

  const grouped = useMemo(
    () => groupByDomain(profile?.skills ?? []),
    [profile],
  );
  const observed = useMemo(
    () => (profile?.skills ?? []).filter((skill) => skill.evidenceCount > 0),
    [profile],
  );

  function retry() {
    setLoading(true);
    setError(null);
    setReloadKey((key) => key + 1);
  }

  if (!ready || loading) {
    return (
      <main id="main">
        <Loading label="Loading your profile…" />
      </main>
    );
  }

  if (error) {
    return (
      <main id="main">
        <ErrorNotice error={error} onRetry={retry} />
      </main>
    );
  }

  if (!profile) return null;

  return (
    <main id="main">
      <header className="hero hero-compact">
        <p className="eyebrow">YOUR PROFILE</p>
        <h1>{profile.displayName}</h1>
        <p className="lede">
          Working towards {profile.targetLevel}, {profile.dailyMinutes} minutes
          a day. Curriculum {profile.curriculumVersion}.
        </p>
        <div className="actions">
          <Link className="button" href="/diagnostic">
            {observed.length === 0
              ? "Start the diagnostic"
              : "Continue practising"}
          </Link>
          {/* Reachable from the dashboard because an endpoint with no way
              in is the same as no endpoint. */}
          <Link className="button-quiet" href="/history">
            Your past work
          </Link>
          <Link className="button-quiet" href="/errors">
            What keeps coming up
          </Link>
          <Link className="button-quiet" href="/skills">
            What depends on what
          </Link>
          <Link className="button-quiet" href="/track">
            {profile.trackName ?? "Choose a track"}
          </Link>
          <Link className="button-quiet" href="/account">
            Your data
          </Link>
          <button type="button" className="button-quiet" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      {token ? <SessionControl token={token} /> : null}

      {token ? <TodayPlan token={token} /> : null}

      {token ? <BenchmarkInvitation token={token} /> : null}

      {observed.length === 0 ? (
        <section className="panel">
          <h2>Nothing measured yet</h2>
          <Empty>
            Your skills are listed below with no levels, because you have not
            shown them yet. The diagnostic takes about ten minutes and gives you
            a starting point.
          </Empty>
        </section>
      ) : (
        <section className="panel">
          <h2>What we know so far</h2>
          <p className="muted">
            {observed.length} of {profile.skills.length} skills have evidence.
            Levels appear only once a skill has been shown across several
            different tasks &mdash; that is why most of these still say
            &ldquo;needs evidence&rdquo;.
          </p>
        </section>
      )}

      {grouped.map(([domain, skills]) => (
        <section key={domain} aria-labelledby={`domain-${domain}`}>
          <div className="section-heading">
            <h2 id={`domain-${domain}`}>{domainLabel(domain)}</h2>
            <span>
              {skills.filter((skill) => skill.evidenceCount > 0).length} of{" "}
              {skills.length} observed
            </span>
          </div>
          <div className="skill-grid">
            {skills.map((skill) => (
              <SkillCard key={skill.skillKey} skill={skill} />
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}

function SkillCard({ skill }: { skill: SkillEstimate }) {
  const label = statusLabel(skill.status);
  const unplaced = skill.cefrEstimate === null;

  return (
    <article className="skill-card">
      <div>
        <h3>{skill.title}</h3>
        <strong
          aria-label={unplaced ? "No level yet" : `Level ${skill.cefrEstimate}`}
        >
          {levelDisplay(skill.cefrEstimate)}
        </strong>
      </div>
      <p className={`pill pill-${skill.status}`}>{label.short}</p>
      <p>{label.explanation}</p>
      <small>
        {confidenceLabel(skill.confidence)}
        {skill.evidenceCount > 0
          ? ` · ${skill.evidenceCount} observation${
              skill.evidenceCount === 1 ? "" : "s"
            } across ${skill.distinctContexts} context${
              skill.distinctContexts === 1 ? "" : "s"
            }`
          : ""}
      </small>
    </article>
  );
}

function groupByDomain(skills: SkillEstimate[]): [string, SkillEstimate[]][] {
  const groups = new Map<string, SkillEstimate[]>();
  for (const skill of skills) {
    const bucket = groups.get(skill.domain);
    if (bucket) bucket.push(skill);
    else groups.set(skill.domain, [skill]);
  }
  return [...groups.entries()];
}
