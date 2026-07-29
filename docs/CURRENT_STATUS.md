# Current Status

Last updated: 2026-07-27. **Milestones 0–6 are complete; 7 and 8 have
started.** The core learning loop now closes, and **no modality is evidenced by self-report any more**: a learner
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

Rubric judgement now has both a hosted and a self-hosted provider, so a
deployment can grade writing without a learner's text leaving it. The default
is still no AI at all, which is the path every test suite runs against.

The app is installable and readable offline. Submitting is not: everything is
scored on the server, and the honest thing to do without a network is refuse
and say so rather than queue work that would be recorded at a moment the
learner was not present for.

## What works

Verified by `make check` on Windows with Python 3.13: ruff, mypy strict,
curriculum validation, **907 Python tests**; eslint, tsc, and **337 web
tests**. On Windows without `make`, `scripts/check.ps1` runs the same gate and
stops at the first failure.

**All six CI jobs pass on `c34e3ae`** — Python 3.10 and 3.12, the web app,
PostgreSQL migrations, fixture drift, and the Playwright browser suite. The
commit named here is the last one verified before this file was written; CI
runs on every push regardless.

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

The Playwright suite has now **actually run and passed**: 44 tests across
desktop and mobile viewports, covering registration, the diagnostic, the
learning loop itself, reflection, a benchmark refusal, and an automated
accessibility gate. Its
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
(105 prerequisite, 14 supporting), each carrying a written reason; a **64-item diagnostic
bank, 55 of them closed and reaching C2**; a **56-entry
phrase-first lexical bank (129 review cards, 52 of them multiword)**; a **12-text reading library reaching C2**, two at every band; **27 study units with 115 practice items**, at least three at every band; **12 written output tasks across 8 genres**, two at every band; **12 listening clips reaching C2**, two at every band; **12 spoken output tasks**, two at every band; and **8 multi-source mediation tasks**, two at every band, across 7 kinds of source. All content-hashed
and immutable once published, all validated by `make test-curriculum`.

Four files that had been in the repository since the beginning are now
**actually read**: the communication-function map, the grammar map, the
pronunciation map, and the three learner tracks. They were hashed into every
curriculum version — so editing one minted a new version and froze the old —
while validation reported the curriculum sound without having looked at a
line of them. Among other things, the parser now refuses a pronunciation
policy that scores accent identity, which the whole speaking lab rests on.

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

### Offline and installable (Milestone 8 — new)

Offline support is easy to make dishonest, and the shape of this is the
argument for what it can and cannot be.

Everything a learner submits is scored on the server, against curriculum the
browser does not have and by a mastery model it does not run. So:

- **Reading works offline.** Today's plan, an activity already opened, the
  profile. A hand-written service worker caches page navigations and API
  reads.
- **A cached API response is served only while offline.** A cache answering
  while the network is up would show yesterday's plan with nothing on screen
  to say so. Offline is the one situation where a stale answer beats no
  answer.
- **Submitting offline fails immediately, with its own error code**, and the
  message says the work is still on screen and has not been sent. It is
  marked retryable, because it is the most retryable failure there is.
- **Nothing is queued or replayed.** A submission fired later would be
  scored at a moment the learner was not present for, and would need a
  timestamp the client chose — which is not something a client may be
  trusted with, since it feeds the review scheduler.
- **A banner says what still works before it says what does not.** "You are
  offline" alone leaves someone guessing whether their half-written essay is
  about to be lost.
- **Signing out clears the cache.** A shared browser must not hand the next
  person a cached profile.
- The app is installable: manifest, icons, theme colour. Zoom is not locked,
  because zooming is how a low-vision learner reads.

### Benchmarks (Milestone 7 — new)

`EvidenceType.BENCHMARK` had existed since the first commit, weighted 1.00 —
the joint-highest in the mastery model — and nothing had ever written one.
The strongest evidence the system can hold was a category with no producer.

- **Scheduled by the server, never chosen.** A learner who takes one when
  they feel ready measures their confidence. Asking early is refused with
  the reason.
- **Unaided, and the schema has nowhere to say otherwise.** The response
  body rejects unknown fields, so a client cannot report a hint and have it
  silently dropped while the result is recorded as unaided.
- **Every item unseen**, in any context, and closed-only: full evaluator
  confidence is defensible only where the answer is known in advance.
- **It can lower an estimate**, and the completion response names the skills
  that fell. Everything else in the product accumulates; a measurement that
  can only agree with the learner is not one.
- **One evidence context per skill**, so eight items in one sitting cannot
  satisfy the model's breadth requirement alone.
- Productive benchmarking waits for a judged deployment: writing and speaking
  stay provisional, and a provisional benchmark is not one.
- **The screen offers no hint control, no per-item feedback, and no way to
  start one that is not due.** Being told item three was wrong changes how
  item four is answered, and the measurement is of the whole set. A fall is
  reported as the benchmark working rather than as failure.
- The dashboard shows the invitation **only when one is due**. A permanent
  button would let a learner take one whenever they felt ready, which is the
  single thing the feature is arranged to avoid.
- **A due benchmark goes into the daily plan, first, and takes its minutes
  out of the budget** rather than being added on top. The plan promises a
  session of a stated length, and a benchmark arriving on top of a full plan
  would break that promise on the day the learner is asked to concentrate
  hardest. It is placed before the session template runs, because it should
  not have to out-score a reading task to appear.

### Reflection (new)

The last plan kind with nothing behind it. Every session template has
reserved four minutes for it since Milestone 1, and the slot rendered
unlinked the whole time.

- **The material is what the system actually noticed**: the errors that
  recurred, what has gone stale, the learner's previous note. A generic
  question produces nothing worth reading, and a learner asked it twice
  stops answering. Someone with no history gets empty lists, not invented
  material.
- **It reports how much of their own work went unjudged.** That is the
  product's blind spot, and reflecting on your progress should not mean
  reading silence as approval.
- **Nothing is scored and no evidence is recorded.** A stated intention is
  not a demonstrated skill. The API says `scored: false` out loud, because a
  client has no other way to know.
- **No minimum length.** Refusing an empty reflection would make the learner
  perform one.
- Writing the tests found a real defect: two reflections in one sitting
  collided on the attempt uniqueness constraint and crashed.

### A learner's own work (new)

`GET /attempts/{id}/feedback` had been in the API contract since the first
commit and unimplemented. Everything a learner wrote, said or answered was
stored and unreachable.

- **Feedback is returned as recorded, never recomputed.** The checks, the
  curriculum version and the evaluator can all have moved since. Re-deriving
  would show a verdict nobody ever gave, in the one place a learner comes to
  check what they were actually told.
- **It is dated and attributed on screen**, with the evaluator that produced
  it, and presented as a record rather than a current judgement.
- **Reading history records nothing.** No evidence, no attempt, no
  re-scoring — counting it would be counting rereading as practice.
- Reflections appear, marked unjudged and with no score. Hiding them would
  leave a gap in the learner's own record; showing a score would invent one.
- Reachable from the dashboard, because an endpoint with no way in is the
  same as no endpoint.

### Accessibility gate (new)

- **axe runs in the browser suite** against sign-in, register and the
  diagnostic, and **fails the build on serious or critical findings**. The
  two lower grades are reported rather than failed: they are largely
  advisory, and failing on them trains people to add exceptions, which is
  how a gate stops meaning anything.
- **Failures name the rule, the grade and the element**, so whoever reads
  one goes to the fix rather than back to the tool.
- Beyond axe: every learner-facing page is checked for a `lang` attribute
  (an English learning app read aloud in the wrong voice is unusable in a
  way nobody thinks to report), for exactly one `main` landmark, and for
  keyboard-only completion of the register form in a real browser.
- `CLAUDE.md` has always required this. Until now it was a standard the
  project asserted about itself and never measured.

### Error taxonomy (new)

- **Errors name a linguistic feature**, from a closed set of 47 codes in
  `apps/api/app/learning/taxonomy.py`, rather than the skill an item belonged
  to. `grammar.tense.perfect_vs_past` can be practised; "something in
  `grammar.connected_time_modality`" cannot.
- **Wrong study items are logged once per feature**, not once per item, so a
  single sitting cannot push a feature past the recurrence threshold alone.
- **A recurring error opens the study unit that drills it**, where one exists.
- **Legacy `item.<skill>` codes still render** and still schedule practice;
  they simply get no feature-based remedy, because none would be honest.
- **Comprehension is in the taxonomy**, as `reading.comprehension.*` and
  `listening.comprehension.*` keyed on the `gist | detail | inference` type
  every authored question already carries. Before this the error log had
  nothing at all to say about reading or listening.
- **A comprehension error opens another text or clip**, not a study unit.
  There is no rule to explain about missing what a passage implies.

### Two screens that had no way in

Both endpoints existed and neither was reachable, which is the same as not
existing. Both are now linked from the dashboard.

- **`/errors` — the whole error log.** Never the raw code; always the label.
  A missing remedy is explained in a sentence rather than rendered as a dash,
  because the three gaps behind it are three different promises.
- **`/skills` — the graph, as a list.** Fifty-odd nodes drawn as a diagram
  would be unreadable and would look like more precision than exists. The
  caveats render above the map rather than under it, with a test on the
  document order. A filter narrows to skills waiting on a weak prerequisite.

### Sittings (new)

- **`POST /sessions` opens a sitting deliberately** and is idempotent within a
  day. Sessions used to be opened implicitly by whichever activity a learner
  started, reused regardless of age, and never ended — one opened in March was
  still collecting attempts in July. Starting a sitting abandons what was left
  open on an earlier day.
- **`POST /sessions/{id}/complete` reports what was done, not how much better
  the learner got.** No mastery delta, no gain, no level-up: each skill carries
  the evidence recorded in the sitting and the distinct contexts it now stands
  on. A test asserts no field named for an improvement figure ever enters the
  shape.
- **`open_minutes` is elapsed time, and says so.** This product does not
  measure time on task, and a summary that presented wall-clock as study time
  would be the easiest lie in the feature.
- **`GET /sessions/current` is a read that starts nothing**, so that loading
  the dashboard does not begin a sitting and start counting a tab left open.
- **`/finish/{id}` shows the summary**, reachable from a control on the
  dashboard. A test asserts the words "improved", "gained", "streak",
  "points" and "xp" never reach the screen — the failure mode is not a bug,
  it is somebody later deciding the page looks bare.

### Tracks (new)

Three tracks had been in `curriculum/tracks/` since the beginning: parsed,
validated, hashed into every curriculum version, and chosen by nobody. A
junior engineer who needed to survive a standup and a postgraduate who needed
to summarise three papers were being offered the same plan.

- **A track raises `goal_match`**, a priority component that existed with a
  weight of 0.40 and had never once been non-zero.
- **It can never suppress a weak prerequisite.** The boost is additive and
  bounded and cannot reach `due_pressure`, `prerequisite_weakness` or
  `error_pressure`. Tests assert a blocked skill and a due review both still
  outrank on-track work.
- **Off-track work scores 0.25, not 0**, so a plan cannot narrow into the
  track and stay there.
- **`/track` shows what each one actually does**, not just its name, and the
  caveat that a track never removes anything renders above the choice.

### Confidence now actually decays

`CLAUDE.md` states the invariant: mastery decays in confidence when not
observed. The model implemented it and then the value was written to a row and
never touched again, so a state computed in March still carried March's
certainty in July — the profile said "confident" about a skill nobody had
looked at for four months.

- **Applied on read**, through `services.evidence.current_confidence`, which
  every reader now goes through: profile, skill map, plan scoring, session
  summary and the diagnostic report.
- **No worker needed.** A nightly job has a window during which every answer
  is stale and a failure mode where it stops silently. This has neither.
- **`mastery_probability` is untouched.** The learner has not become worse.
- A skill losing `independent` after a year of silence falls out of
  `classify_status` by itself rather than from a new rule.

### Export and deletion (new)

`docs/PRIVACY_SAFETY.md` has listed "Provide export and deletion" under data
minimisation since the beginning, and nothing implemented either — a worse gap
than an ordinary missing feature, because this product stores what a person
wrote and said.

- **`GET /account/export`** returns the stored rows, not a report, with a
  `not_included` list naming what it leaves out and why.
- **`POST /account/delete`** is real deletion, relying on the schema's
  `ondelete="CASCADE"` rather than a hand-written sweep. A test checks every
  learner-owned table afterwards, including `plan_items`, which has no
  `user_id`.
- **Both are reachable** from `/account`, which tells the learner to export
  before deleting — above the delete control, not after it.

### Auth rate limiting (new)

`docs/PRIVACY_SAFETY.md` lists rate limits under the security baseline and
none existed; `main.py` already mapped 429 to `rate_limited`, a code nothing
could raise.

- **Sliding window, never a lockout.** A latching counter would let an
  attacker deny service to any account whose address they know.
- **Keyed on caller and account, checked before the lookup**, so it cannot
  become an account-enumeration oracle.
- **In-process, and it says so.** Behind N replicas the effective limit is
  N times what is configured; Redis is the deployment answer.
- **Registration is the loosest limit on purpose** — a classroom shares one
  address, and an attacker does not.

### Reporting bad feedback (new)

`docs/AI_TUTOR_BEHAVIOR.md` calls AI judgement an accelerator rather than an
authority. That is a claim about how the product behaves, and it was not true
of anything: a learner marked wrong by a check that had misread them could
watch the verdict feed their profile with no way to object.

- **`POST /attempts/{id}/report`** lowers the confidence of the evidence that
  attempt produced and leaves the score alone.
- **Which makes it ungameable.** Disputing everything cannot inflate a
  profile; it can only make it say "we do not really know".
- **Nothing is deleted**, and the response always says the score did not
  change.

## What is not yet implemented

- **Pronunciation assessment.** The speaking lab evidences spoken production
  from a transcript and says plainly that it judges nothing about delivery.
  Acoustic analysis needs audio upload — `POST /speech/uploads` and its two
  companions in `docs/API_CONTRACTS.md` remain unimplemented — and until that
  exists, `pronunciation.segment.contrast` and `pronunciation.stress.word`
  have no honest route to evidence.
- **A judged deployment.** All three provider modes now exist, and the
  default is still `disabled`, so writing and mediation stay provisional out
  of the box and every test runs against the no-AI path. Nothing here has
  been run against a real model.
- **One diagnostic item still logs a legacy code.** `lexis.a1.days` asks
  which day follows Tuesday, which is a specific word rather than a
  practisable feature. The four reading items that were the bulk of this gap
  now name comprehension features, and a test pins the exception at one item
  so it cannot quietly grow.
- **A deployed instance.** Both container images now build and a compose
  stack describes the whole product, but nothing has been run end to end in
  containers, and `services/worker` is still a stub — nothing in the product
  needs asynchronous work yet, which is why it has stayed a stub honestly
  rather than accidentally.

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
8. **Accessibility is checked by a machine, which finds about a third of
   what matters.** axe runs against the sign-in, register and diagnostic
   pages in the browser suite and fails the build on serious or critical
   findings. It reliably catches a missing label, insufficient contrast, a
   skipped heading level or a broken landmark. It cannot tell whether a
   label is *helpful*, whether the reading order makes sense, or whether a
   screen-reader user could actually finish the diagnostic. Nobody has
   tried.
9. **Token in `sessionStorage`** is readable by any script on the page.

## Next three tasks

1. **Run a rubric provider against a real model.** Both `cloud` and `local`
   are tested against stub transports, which proves they survive every way
   the outside world can misbehave and proves nothing about whether a real
   model produces judgements worth having.
2. **Validate the constants.** Study independence 0.65, transcript
   confidence 0.35, the 21-day benchmark cadence, 119 graph weights — all
   defensible defaults and none of them findings. `docs/LEARNING_SCIENCE.md`
   asks for them to be checked against usage, and nothing has been.
3. **Run the compose stack end to end.** Both images build; nothing has yet
   started them together and walked a learner through the product in
   containers. That is where a wrong `NEXT_PUBLIC_API_URL`, a missing
   migration step or a CORS mismatch would show.
