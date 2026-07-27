# Current Status

Last updated: 2026-07-27. **Milestones 0–3 are complete.** The core learning loop now closes,
and **every plan-item kind that has an activity behind it can be opened**: a
learner registers, takes an adaptive diagnostic including a written task,
receives a daily plan that explains itself, opens and completes reading,
listening, focused study, and written output from that plan, works through
spaced reviews, and sees a profile built only from evidence they actually
produced.

## What works

Verified by `make check` on Windows with Python 3.13: ruff, mypy strict,
curriculum validation, **420 Python tests**; eslint, tsc, and **188 web
tests**. On Windows without `make`, `scripts/check.ps1` runs the same gate and
stops at the first failure.

> **This repository is not under version control.** There is no `.git`
> directory, so there is no history, no way to review a change as a diff, and
> no way to undo one. `.gitignore` and `.github/workflows/ci.yml` both exist,
> so this was clearly intended — but until `git init` happens, CI has never
> run and cannot run, which is also why the Playwright suite in risk #4 has
> never executed.

A Playwright suite (`make e2e`) covers the browser journey. It runs in CI; it
could not be executed in the sandbox this work was done in, because
Playwright's browser download is blocked there.

### Bootstrap

A clean clone runs with no Docker, no PostgreSQL, and no AI key. SQLite for
development, PostgreSQL opt-in and proven in CI. Both lockfiles committed. CI
runs five jobs. The API refuses to start in production with development
defaults. Tests run in parallel.

### Curriculum 0.5.0

55 objectives across A1–C2 with 45 prerequisite edges; a 36-item diagnostic
bank; a 14-entry phrase-first lexical bank (34 review cards); a 4-text reading
library with 11 comprehension questions; 8 study units with 36 practice items;
7 written output tasks across 6 genres; and **5 listening clips with 15
comprehension questions**. All content-hashed and immutable once published,
all validated by `make test-curriculum`.

### Diagnostic, mastery, and writing (Milestone 1)

Five deterministic item types scored locally. Beta-Bernoulli mastery model
weighting each observation by evidence type, independence, novelty, difficulty
relevance, evaluator confidence, and repetition damping. Written responses
scored by countable checks at reduced confidence and flagged provisional.

### Daily plan (Milestone 1)

Ten named priority components, all persisted per item. Constraints applied
after scoring: session template, time budget, receptive/productive balance, and
a cap on consecutive heavy work. Every item explains itself.

### Spaced review (Milestone 2)

Stability/difficulty scheduler, deterministic, with separate cards and interval
factors per retrieval mode. Reviews write evidence of a mode-appropriate type.
A due card never ships its own answer.

### Reading lab (Milestone 3)

- Gist, detail, and inference questions over original short texts at A1–B2,
  scored deterministically so the reading lab works with AI disabled.
- The text stays visible while answering — comprehension, not recall.
- Reading records `comprehension` evidence, and each text is its own context.

### Listening lab (new — completes Milestone 3)

- **Listening is evidenced by something the learner did**, not by a self
  rating. Clips at A1–B2 with gist, detail, and inference questions, scored
  deterministically.
- **No audio files ship.** Each clip carries a transcript and the browser
  speaks it, so the lab works offline, with no key, and with no licensing
  question. `audio` exists on every clip so a deployment can point at real
  recordings without a schema change.
- **The transcript is hidden, inverting the reading rule.** Reading keeps its
  text on screen because hiding it would test memory; listening hides its
  transcript because showing it would test reading.
- **The transcript is always one click away**, because a learner who cannot
  use audio has no other route. Taking that click is reported, and the API
  then records *no listening evidence at all* and says why. Honest and
  accessible, rather than secret.
- **Replays cost independence only past two free passes**, and never fall
  below a floor. Replaying is normal listening, not cheating.
- **Comprehension questions are now defined once** in
  `curriculum/questions.py` and shared by both receptive labs.

### Study and output activities

- **All three working slots open.** `read:`, `study:`, and `write:` keys
  resolve at `GET /activities/{key}`; the response is a discriminated union on
  `activity_type`, so the web player handles all three exhaustively.
- **Study units** explain one point, then practise it. The explanation stays
  on screen, so evidence is recorded as `controlled_recall` at independence
  0.65, reduced further by self-reported hints. The result page says why a
  perfect study score does not settle the skill.
- **Written output tasks** carry their own requirements — length, sentences,
  linking, required content — checked deterministically. Evidence is
  `contextual_production` at evaluator confidence 0.45, always flagged
  provisional. A response too short to judge records *no* evidence rather than
  a bad score.
- **Each slot is filled only from its own source.** A study slot is never
  filled with a reading text, which would have quietly broken the
  receptive/productive balance.
- **A parser invariant makes an unfair task impossible**: a writing task may
  not require wording its own prompt and guidance never use.

### Error taxonomy (new)

- **Errors name a linguistic feature**, from a closed set of 36 codes in
  `apps/api/app/learning/taxonomy.py`, rather than the skill an item belonged
  to. `grammar.tense.perfect_vs_past` can be practised; "something in
  `grammar.connected_time_modality`" cannot.
- **Wrong study items are logged once per feature**, not once per item, so a
  single sitting cannot push a feature past the recurrence threshold alone.
- **A recurring error opens the study unit that drills it**, where one exists.
- **Legacy `item.<skill>` codes still render** and still schedule practice;
  they simply get no feature-based remedy, because none would be honest.

## What is not yet implemented

- **Speaking.** No recorder, transcription, or acoustic analysis. The
  `speaking` slot is the last plan-item kind with nothing behind it, and
  speaking skills are still evidenced only by self-rating.
- **Rubric evaluation.** The provider contract has no implementation, so
  writing accuracy is still never judged. Every writing task already names the
  features a rubric should look at, so the gap is recorded rather than hidden.
- **Diagnostic errors still use legacy codes.** `services/diagnostics.py` logs
  `item.<skill_key>`; the taxonomy exists but the diagnostic does not use it
  yet. Study activities do.
- **Worker and deployment.** `services/worker` is a stub; no container images.

## Current risks

1. **Listening is measured against synthetic speech.** Browser speech
   synthesis under-represents weak forms, elision, and assimilation — the
   things that actually make listening hard — and voices differ by platform,
   so two learners do not hear quite the same thing. A learner who copes here
   has not proved they cope with a recording of two people in a cafe. Evidence
   is flagged `synthesised: true` so this is auditable, and `audio` on each
   clip accepts real recordings with no schema change.
2. **The speaking slot still has nothing behind it**, and renders unlinked.
3. **Writing accuracy is never judged.**
4. **The Playwright suite has never actually run.** Its browser download is
   blocked in the sandbox this work was done in.
5. **Content banks are thin above B2.** C1 has no study units, writing tasks,
   or clips; C2 has no coverage at all. 18 of 36 features have no study unit,
   which `make test-curriculum` reports explicitly.
6. **Hints, replays, and transcript use are self-reported by the client.** A
   dishonest or buggy client can overstate independence. The blast radius is
   one mis-weighted observation, except for `used_transcript`, where the
   failure mode is recording listening evidence that was really reading.
7. **Scheduler, mastery, and plan constants are defensible defaults, not
   findings.** Study independence 0.65, hint penalty 0.15, two free replays,
   replay penalty 0.1 — all documented guesses.
8. **No automated colour-contrast or screen-reader check.**
9. **Token in `sessionStorage`** is readable by any script on the page.

## Next three tasks

1. **Implement a rubric evaluator** behind the existing provider contract, so
   writing accuracy is judged rather than merely flagged as unjudged.
   Milestone 4, and the largest remaining honesty gap in the product.
2. **Move the diagnostic onto the feature taxonomy**, so a mistake made during
   assessment is as actionable as one made during study. The taxonomy and the
   remedy lookup already exist; only `services/diagnostics.py` still writes
   legacy codes.
3. **Deepen the content banks at C1 and C2**, where the curriculum currently
   promises levels it has nothing to teach at.
