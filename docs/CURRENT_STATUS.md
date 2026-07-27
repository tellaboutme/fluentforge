# Current Status

Last updated: 2026-07-26. **Milestones 0–3 are complete.** The core learning loop now closes,
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

Version control starts at commit `d503861`, which captures this passing state
as the baseline. 221 files tracked; `.venv`, `node_modules`, and `local-data`
correctly excluded. `scripts/git-init.ps1` created it.

CI runs on every push to `github.com/tellaboutme/fluentforge`: six jobs
covering Python on 3.10 and 3.12, the web app, PostgreSQL migrations, fixture
drift, and the Playwright browser suite. The first push exposed a real defect
in the `fixtures` job — see "Fixed by CI" below.

The Playwright suite has now **actually run and passed**: 14 tests across
desktop and mobile viewports, on the development machine via the runner. Its
first-ever execution found four real defects — a bash-only launcher that
failed on Windows, hydration blocked by Next 16's cross-origin default (which
made the register form fall back to a native GET submit, password in the URL),
keystrokes lost to a pre-hydration race, and two flaky-by-construction
locators in the spec itself.

### Fixed by CI's first run

The `fixtures` job re-captures the API payloads and diffs them against the
committed copy. It failed immediately, for two reasons that had been latent
since the job was written — it could never have passed:

- The capture contained five generated UUIDs and two timestamps, all new on
  every run. These are now replaced with stable placeholders that preserve
  identity: fields sharing a real identifier still share a placeholder.
- The file was written with CRLF on Windows and regenerated with LF on Linux,
  so every line differed. The capture pins `newline="\n"` and
  `.gitattributes` stores LF.

### Bootstrap

A clean clone runs with no Docker, no PostgreSQL, and no AI key. SQLite for
development, PostgreSQL opt-in and proven in CI. Both lockfiles committed. CI
runs five jobs. The API refuses to start in production with development
defaults. Tests run in parallel.

### Curriculum 0.5.0

55 objectives across A1–C2 with 45 prerequisite edges; a 36-item diagnostic
bank (23 items tagged with the linguistic feature they exercise); a 14-entry
phrase-first lexical bank (34 review cards); a 5-text reading library reaching
C1; **12 study units with 52 practice items spanning A1–C2**; 9 written output
tasks across 8 genres reaching C2; and 5 listening clips. All content-hashed
and immutable once published, all validated by `make test-curriculum`.

The C1/C2 material teaches what actually distinguishes those levels —
information flow, hedging and stance, register shifting, irony and
understatement — rather than harder vocabulary quizzes, which is the trap
`docs/ROADMAP.md` Milestone 7 warns against.

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
- **A rubric provider.** The evaluator is now *wired in* — writing calls it,
  a usable judgement adds evidence, and the UI renders dimensions, citations
  and corrections. What does not exist yet is a provider that actually calls a
  model: `local` and `cloud` still raise at startup, so the shipped default
  abstains and writing stays provisional. The wiring is the part that was
  missing and is fully tested; the provider is a afternoon's work behind a
  contract that now has a caller.
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
4. **Listening still stops at B2**, and 16 of 36 features have no study
   unit, which `make test-curriculum` reports explicitly. Study, writing and
   reading now reach C1/C2; clips do not yet.
5. **Hints, replays, and transcript use are self-reported by the client.** A
   dishonest or buggy client can overstate independence. The blast radius is
   one mis-weighted observation, except for `used_transcript`, where the
   failure mode is recording listening evidence that was really reading.
7. **Scheduler, mastery, and plan constants are defensible defaults, not
   findings.** Study independence 0.65, hint penalty 0.15, two free replays,
   replay penalty 0.1 — all documented guesses.
7. **No automated colour-contrast or screen-reader check.**
8. **Token in `sessionStorage`** is readable by any script on the page.

## Next three tasks

1. **Implement a concrete rubric provider** (`local` or `cloud`) behind the
   now-wired evaluator contract, so writing accuracy is actually judged. The
   wiring, capping, and UI all exist and are tested against a fake.
2. **Add C1/C2 listening clips**, the one bank still stopping at B2.
3. **Cover more features with study units** — 16 of 36 still have no unit, so
   errors logged against them schedule practice but offer no remedy.
