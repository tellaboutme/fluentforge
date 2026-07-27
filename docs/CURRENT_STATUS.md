# Current Status

Last updated: 2026-07-27. **Milestones 0–6 are complete, and Milestone 7 has started.** The core learning loop now
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

The dependency graph behind the plan is now hand-authored rather than derived
from CEFR levels, so the planner reasons about what actually blocks what
instead of about which band a skill sits in.

The newest lab is multi-source mediation, which is the advanced work
`docs/ROADMAP.md` Milestone 7 asks for rather than the harder vocabulary quiz
it warns against: several sources go in, one account comes out, and the
learner has to notice that the sources disagree.

## What works

Verified by `make check` on Windows with Python 3.13: ruff, mypy strict,
curriculum validation, **618 Python tests**; eslint, tsc, and **232 web
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

### Curriculum 0.6.0

55 objectives across A1–C2 with a **hand-authored skill graph of 119 edges**
(105 prerequisite, 14 supporting), each carrying a written reason; a 36-item diagnostic
bank (23 items tagged with the linguistic feature they exercise); a 14-entry
phrase-first lexical bank (34 review cards); a 5-text reading library reaching
C1; **22 study units with 95 practice items spanning A1–C2**; 9 written output
tasks across 8 genres reaching C2; 7 listening clips reaching C2; **7
spoken output tasks reaching C2**; and **4 multi-source mediation tasks
reaching C2, across 6 kinds of source**. All content-hashed
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

### Skill graph (Milestone 6 — new)

- **Edges are authored, not derived.** `curriculum/graph.yml` replaces the
  rule that level N depends on level N-1 in the same domain — one true claim
  repeated 45 times, which could not express any cross-domain dependency at
  all.
- **Every edge states why it exists**, in at least a sentence, enforced by
  the parser. An edge nobody can justify is a guess with a weight attached.
- **`supports` is a real relation and never gates.** Pronunciation helps
  spoken production and must not block it; grammar helps speech and must not
  block it. Inflating those into prerequisites is how a graph like this goes
  wrong, so the distinction is enforced.
- **Pronunciation gates nothing outside its own domain.** Making
  intelligibility a prerequisite would encode an accent standard this product
  does not hold. Tested, not merely intended.
- **Prerequisite importance is a real graph walk.** It used to be
  `1 - difficulty`, which scored A2 vocabulary and A2 pronunciation
  identically despite one gating production, interaction and mediation and
  the other gating nothing.
- **Six shapes are refused outright**: cycles, backwards prerequisites,
  orphans above a domain floor, unjustified edges, rules that match nothing,
  and duplicate triples. Each of those failures is otherwise silent.
- `make test-curriculum` prints the five most load-bearing skills every run,
  so a change in what the planner pushes learners towards shows up in a diff.

### Mediation lab (Milestone 7 — new)

The mediation objectives had prerequisites pointing at them and nothing
behind them. They now have the hardest task in the product.

- **Several sources in, one account out**, written for a reader who has seen
  none of them. Four tasks B1–C2, across articles, emails, report extracts,
  chart summaries, notices and forum posts. The sources deliberately
  disagree: reconciling two agreeing sources is summarising twice.
- **The parser refuses a single-source task.** One source is a summary, and
  the writing bank already has those.
- **A brief must name its reader.** Mediation without an audience is
  paraphrase — who the account is for decides which details survive.
- **Source coverage is inferred from anchors** — names, figures and dates
  that survive paraphrase, proven present in their own source and absent
  from every other. An approximation, and the result screen says so: a
  missing source is offered as a suggestion, not a mark.
- **Copying is measured exactly**, as the longest run shared with a source,
  with *marked quotations removed first*. Quoting and attributing is
  legitimate mediation; counting it would teach a learner to stop
  attributing. The limit is stated before they write, not after they break
  it.
- **Anchors are never sent to the client.** Publishing them would turn the
  task into a word hunt. The source texts are sent in full: they are the
  material, not an answer key.
- **The weakest deterministic evidence in the system (0.40)**, despite having
  more checks than writing. The extra checks make it a stricter test of
  writing and a weaker test of mediation: whether the sources were conveyed
  *faithfully* is exactly what no countable check can reach.
- **Five C-level features added to the taxonomy**: hedging, source
  attribution, irony, figurative language, and information flow. The
  original 36 had nothing between "wrong tense" and "wrong register".
- **And five study units to answer them.** A feature with no unit behind it
  is a category the error log can name and the plan can never answer, so the
  gap closed in the same milestone that opened it: 39 of 41 features are now
  covered, and the two that are not need acoustic analysis rather than
  content.

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

- **All six working slots open.** `read:`, `study:`, `write:`, `listen:`,
  `speak:` and `mediate:` keys resolve at `GET /activities/{key}`; the
  response is a discriminated union on `activity_type`, so the web player
  handles all six exhaustively.
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
- **`ai_provider=local` judges writing without the text leaving the
  deployment.** It speaks the OpenAI chat-completions shape, so Ollama,
  vLLM, llama.cpp and LM Studio all work. Same versioned prompt, same
  schema, same fabricated-quotation check as `cloud`: two providers that
  disagreed about what counts as a usable judgement would make the mastery
  numbers incomparable between deployments.
- Three deliberate differences in `local`: no key is required (a model on a
  private network usually has no auth), the timeout is six times longer (a
  7B model on a CPU is slow, and the learner already has their deterministic
  feedback on screen), and the hosted default address is never used — that
  would defeat the only reason to run a model yourself.
- **A rubric dimension must now cite evidence, enforced in the schema.** The
  rule was written in a comment and in `docs/DECISION_LOG.md` and enforced
  nowhere: an uncited score validated cleanly and reached the mastery model.
  Writing the local provider's tests is what found it.
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
- **A judged deployment.** All three provider modes now exist, and the
  default is still `disabled`, so writing and mediation stay provisional out
  of the box and every test runs against the no-AI path. Nothing here has
  been run against a real model.
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
3. **The skill graph is expert judgement, not measurement.** 119 authored
   claims about what depends on what, each defensible and none validated
   against learner outcomes. The structure now makes them reviewable — one
   claim, one reason, one weight, in a versioned file — which is a real
   improvement on an assumption buried in a loop, but it is still nobody's
   data. Milestone 6's exit criterion, beating fixed sequencing in offline
   simulation, has not been demonstrated.
4. **Writing and mediation accuracy are never judged.** Both record evidence
   from countable checks alone, and mediation's central claim — that the
   sources were conveyed faithfully — is the furthest of any of them from
   what a countable check can reach.
5. **Two features have no remedy, and no lab in the product can give them
   one.** `pronunciation.segment.contrast` and `pronunciation.stress.word`
   need acoustic analysis, not a transcript. Every other feature now has a
   study unit. `make test-curriculum` reports these two separately from
   genuinely missing content, so nobody is tempted to write a fake text
   drill for a sound.
6. **Hints, replays, transcript use, spoken duration and `typed_instead` are
   self-reported by the client.** A dishonest or buggy client can overstate
   independence. The blast radius is one mis-weighted observation, except for
   `used_transcript` and `typed_instead`, where the failure mode is recording
   evidence of a modality the learner never used.
7. **Scheduler, mastery, and plan constants are defensible defaults, not
   findings.** Study independence 0.65, hint penalty 0.15, two free replays,
   replay penalty 0.1, transcript confidence 0.35 — all documented guesses.
8. **No automated colour-contrast or screen-reader check.**
9. **Token in `sessionStorage`** is readable by any script on the page.

## Next three tasks

1. **Finish Milestone 7.** Mediation has landed and the speaking bank now
   reaches C2. The academic and professional tracks, literature and advanced
   media, and advanced benchmark portfolios have not been started.
2. **Run a provider against a real model.** Both `cloud` and `local` are
   built and tested against stub transports, which proves they handle every
   way the outside world can misbehave and proves nothing about whether a
   real model produces judgements worth having. The abstention rate on a
   small local model is the number to look at first.
3. **Offline/PWA** (Milestone 8), the last unstarted milestone.
