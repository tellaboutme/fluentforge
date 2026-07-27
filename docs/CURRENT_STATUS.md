# Current Status

Last updated: 2026-07-27. **Milestones 0–5 are complete.** The core learning loop now
closes, and **no modality is evidenced by self-report any more**: a learner
registers, takes an adaptive diagnostic including a written task, receives a
daily plan that explains itself, opens and completes reading, listening,
focused study, written output, **and spoken output** from that plan, works
through spaced reviews, and sees a profile built only from evidence they
actually produced.

Speaking is the newest and the most carefully bounded. What the system sees is
a transcript, so it says what a transcript can support — that connected spoken
language was produced, at length, covering what was asked — and refuses, in the
parser, in the service, and on screen, to claim anything about how the learner
sounded.

## What works

Verified by `make check` on Windows with Python 3.13: ruff, mypy strict,
curriculum validation, **486 Python tests**; eslint, tsc, and **212 web
tests**. On Windows without `make`, `scripts/check.ps1` runs the same gate and
stops at the first failure.

**All six CI jobs pass on `01e48c6`** — Python 3.10 and 3.12, the web app,
PostgreSQL migrations, fixture drift, and the Playwright browser suite.

Version control starts at commit `d503861`, which captures this passing state
as the baseline. 221 files tracked; `.venv`, `node_modules`, and `local-data`
correctly excluded. `scripts/git-init.ps1` created it.

CI runs on every push to `github.com/tellaboutme/fluentforge`. The first push
exposed a real defect in the `fixtures` job — see "Fixed by CI" below.

Because the sandbox this work is written in cannot reach PyPI or npm,
verification goes through `scripts/runner.ps1`: a job runner on the
development machine, driven through the shared project folder. The protocol is
documented in `CLAUDE.md`. Every slice since it existed has been gated before
being committed.

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
C1; **17 study units with 75 practice items spanning A1–C2**; 9 written output
tasks across 8 genres reaching C2; 7 listening clips reaching C2; and **5
spoken output tasks reaching C1**. All content-hashed
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

### Speaking lab (Milestone 5 — new)

The last modality resting on self-report. Three refusals define it, and each
is enforced in more than one place.

- **Speaking is evidenced by something the learner did.** Five tasks A1–C1,
  each with a preparation time, a speaking time, and countable content
  requirements. The browser transcribes; the transcript is checked by the
  same machinery writing uses. Evidence is `contextual_production` against a
  speaking skill.
- **Nothing claims to judge pronunciation.** A transcript cannot tell a
  clearly spoken word from a badly spoken one the recogniser guessed
  correctly. The curriculum parser *refuses* a task targeting a
  `pronunciation.*` skill, every evidence event carries
  `pronunciation_unassessed: true`, and the result screen says so in as many
  words.
- **Recognition confidence is stored and never scored.** Browser recognition
  is measurably worse on accented speech — this product's entire audience —
  so the same answer scores identically however well it was heard. It is
  shown as a fact about the software and kept for audit.
- **Typing is always available and always reported as typing.** A learner
  with no microphone, or a browser that cannot listen, can still finish. The
  attempt is kept and no speaking evidence is recorded, exactly as reading a
  listening transcript records no listening evidence.
- **A transcript is weaker evidence than typed writing** — confidence 0.35
  against 0.45. Independence is full in both: the learner composed it. The
  extra doubt is in the record, not the performance.
- **The learner sees and can edit what was heard.** Correcting a machine that
  misheard an accent is not cheating.

### Study and output activities

- **All five working slots open.** `read:`, `study:`, `write:`, `listen:` and
  `speak:` keys resolve at `GET /activities/{key}`; the response is a
  discriminated union on `activity_type`, so the web player handles all five
  exhaustively.
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

### Rubric evaluation (Milestone 4)

- **`ai_provider=cloud` judges writing** against the versioned prompt in
  `prompts/evaluators/writing.md`, adding a second evidence event beside the
  deterministic one rather than replacing it.
- **Fabricated evidence is rejected.** Every cited quotation is checked
  against the learner's actual text. A schema-valid judgement that invents
  what it quotes is discarded — it is not a judgement about this writing.
- **Every failure abstains**: no key, timeout, quota, HTTP error, malformed
  body, unparseable JSON, schema violation, more than three corrections. The
  learner keeps exactly the deterministic feedback they would have had. 27
  tests, one per way the outside world can misbehave.
- **Confidence is capped at 0.85** before reaching the mastery model.
- The default is still `disabled`, so the whole suite proves the product
  works with no AI configured.

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

- **Pronunciation assessment.** The speaking lab evidences spoken production
  from a transcript and says plainly that it judges nothing about delivery.
  Acoustic analysis needs audio upload — `POST /speech/uploads` and its two
  companions in `docs/API_CONTRACTS.md` remain unimplemented — and until that
  exists, `pronunciation.segment.contrast` and `pronunciation.stress.word`
  have no honest route to evidence.
- **`reflect:` plan items**, the last kind with nothing behind them. They
  render unlinked rather than pointing somewhere wrong.
- **A self-hosted (`local`) provider.** `cloud` now exists and works; `local`
  still raises at startup. The default remains `disabled`, so writing stays
  provisional out of the box and every test runs against the no-AI path.
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
2. **Speaking is measured through a recogniser that is worse on the accents
   this product serves.** A dropped or mangled word costs the learner content
   marks it should not. Mitigated three ways — the transcript is shown and
   editable, recognition confidence is never scored, and evaluator confidence
   is the lowest in the system — but not eliminated. Recognition quality is
   stored on every event so the correlation can actually be checked.
3. **Writing accuracy is never judged.**
4. **Two features have no remedy, and the speaking lab cannot give them one.**
   `pronunciation.segment.contrast` and `pronunciation.stress.word` need
   acoustic analysis, not a transcript. `make test-curriculum` reports them
   separately from genuinely missing content, so nobody is tempted to write a
   fake text drill for a sound.
5. **Hints, replays, transcript use, spoken duration and `typed_instead` are
   self-reported by the client.** A dishonest or buggy client can overstate
   independence. The blast radius is one mis-weighted observation, except for
   `used_transcript` and `typed_instead`, where the failure mode is recording
   evidence of a modality the learner never used.
6. **Scheduler, mastery, and plan constants are defensible defaults, not
   findings.** Study independence 0.65, hint penalty 0.15, two free replays,
   replay penalty 0.1, transcript confidence 0.35 — all documented guesses.
7. **No automated colour-contrast or screen-reader check.**
8. **Token in `sessionStorage`** is readable by any script on the page.

## Next three tasks

1. **Hand-author the prerequisite graph** (Milestone 6). Edges are currently
   derived across adjacent CEFR levels within a domain — a documented
   stand-in, not a claim about acquisition order, and now the largest piece
   of guesswork left in the adaptive engine.
2. **B2–C2 depth** (Milestone 7): long-form synthesis and multi-source
   mediation, the tasks that actually separate the top three levels. The
   content bank reaches C2 in reading and writing but stops at C1 in
   speaking.
3. **A self-hosted (`local`) rubric provider**, so writing accuracy can be
   judged without sending a learner's text to a third party. `cloud` exists
   and works; `local` still raises at startup.
