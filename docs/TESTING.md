# Testing FluentForge

Everything here runs on your machine. Nothing needs a deployment, and only
part 4 needs an API key.

Read part 0 first — it says what each layer can and cannot tell you, which
matters more than the commands.

---

## 0. What each layer actually proves

| Layer | Proves | Does **not** prove |
|---|---|---|
| `make test` (916 Python tests) | The domain logic behaves as designed | That the design is right |
| `pnpm test` (337 web tests) | Screens render and refuse what they should | That anyone can use them |
| `make e2e` (44 Playwright tests) | The whole loop works in a real browser | That it works on a real network |
| `make test-curriculum` | The content is well-formed and complete | That the content teaches anything |
| Manual walkthrough (part 3) | The product makes sense to a person | Anything about a *second* person |
| AI evaluator (part 4) | A real model can produce usable judgements | That its judgements are correct |

The honest summary: **the code is well tested, the product is unvalidated.**
No learner has used it, no constant has been checked against outcomes, and
until you do part 4, no AI model has ever been called.

---

## 1. The automated gate

Start the runner in one PowerShell window and leave it open:

```powershell
cd C:\Users\tellmemore\Documents\FluentForge\FluentForge
powershell -ExecutionPolicy Bypass -File scripts\runner.ps1
```

Then, in a second window:

```powershell
# The full gate: format, lint, typecheck, tests, curriculum, fixtures, build
make check          # or: powershell -ExecutionPolicy Bypass -File scripts\check.ps1

# Individual pieces, if you want to narrow something down
make test               # Python
make test-web           # web unit tests
make test-curriculum    # content validation
make typecheck          # mypy + tsc
make e2e                # Playwright, needs `make e2e-install` once
```

Expected: **All 12 steps passed.** Anything else is a real failure — the
gate has no known-flaky steps.

`make e2e` takes about 3.5 minutes and runs every test twice, once in
desktop Chromium and once at a mobile viewport.

### Database migrations

Worth running separately, because SQLite (the dev default) compares schemas
far more loosely than PostgreSQL does — that difference has already caused one
CI failure that passed everything locally.

```powershell
$env:DATABASE_URL = "sqlite+pysqlite:///./local-data/drift-check.db"
uv run alembic upgrade head
uv run alembic check          # must say: No new upgrade operations detected
uv run alembic downgrade base
Remove-Item .\local-data\drift-check.db
```

---

## 2. Running it for real

```powershell
make dev
```

That starts the API on `http://localhost:8000` and the web app on
`http://localhost:3000`. Open the web app.

Health checks, if something looks wrong:

```powershell
Invoke-RestMethod http://localhost:8000/health   # is the process alive
Invoke-RestMethod http://localhost:8000/ready    # database + provider modes
```

`/ready` will report `ai_provider: disabled` until you do part 4. That is the
default and everything works without it.

---

## 3. The manual walkthrough

This is the part that finds things tests do not. Do it as a learner would,
not as someone checking a list — and write down anything that made you pause,
because that hesitation is the finding.

### 3.1 Signing up and the diagnostic

1. Register. Note the daily-minutes choice.
2. You land on the diagnostic. **Check:** no item ever shows the answer before
   you submit.
3. Finish it. Read the report.
   - **Check:** the caveats are visible, not hidden behind a link.
   - **Check:** the starting band is described as where to *begin*, not as
     your level.
   - **Check:** no skill claims a CEFR level yet. Most should say "needs
     evidence".

*The thing to be suspicious of:* anywhere the product sounds more certain
than ten minutes of answers could justify.

### 3.2 Today's plan

4. Go to the dashboard. **Check:** every plan item has a reason under it, in
   words.
5. Open one. Finish it. **Check:** the feedback tells you something specific,
   not "well done".
6. Go back. **Check:** the plan is the same plan — it must not reshuffle
   because you completed one thing.

### 3.3 Each activity kind

Work through the plan until you have done at least one of each. If a kind
never appears, generate a new plan (`Regenerate` on the dashboard) — the mix
depends on your diagnostic.

- **Reading** — a text with gist/detail/inference questions.
- **Listening** — the clip plays through the browser's speech synthesis.
  **Check:** the transcript stays hidden until you ask for it, and asking is
  recorded rather than punished silently.
- **Study** — an explanation, then practice. **Check:** the explanation stays
  on screen, and the result says the evidence was recorded at reduced
  independence.
- **Writing** — **Check:** the feedback is labelled provisional, and says the
  checks are countable ones.
- **Speaking** — needs Chrome or Edge (Web Speech API). **Check:** the
  transcript is shown and editable, and the screen says plainly that nothing
  judges your accent.
- **Mediation** — several sources in, one account out. **Check:** it tells you
  if you copied rather than restated.

### 3.4 The things I built most recently

7. **Sittings.** Dashboard → *Start a session* → do something → *Finish for
   today*.
   - **Check:** the summary reports what you did and **never** a score, a
     streak, or an improvement percentage.
   - **Check:** the minutes are labelled elapsed, with a line saying time on
     task is not measured.
   - **Check:** reload the finish page. Same summary, same end time.
8. **Your past work** (`/history`). Open an attempt.
   - **Check:** the feedback is dated and says it may be stale.
   - Click *This feedback is wrong*. **Check:** the response says your score
     has not changed.
9. **What keeps coming up** (`/errors`).
   - **Check:** no raw codes like `grammar.tense.past_simple_form` on screen.
   - **Check:** anything with no practice explains *why* in a sentence.
10. **What depends on what** (`/skills`).
    - **Check:** the caveat that the graph is judgement, not measurement, is
      above the map.
    - **Check:** unmeasured skills say so rather than looking weak.
11. **Your track** (`/track`).
    - **Check:** each track says what it actually changes, not just its name.
    - Switch tracks, then look at the plan. **Check:** it still offers a full
      plan — a track must never empty it.
12. **Your data** (`/account`).
    - Download the export. Open the JSON. **Check:** your own writing is in
      there verbatim, and `not_included` explains the gaps.
    - Do **not** test deletion on the account you want to keep. Register a
      throwaway one for that.

### 3.5 Things that should refuse

- Try to log in with a wrong password ~10 times. **Check:** you get a 429 with
  a wait time, and the *correct* password is also refused until it expires.
- Turn off your network mid-activity. **Check:** it says you are offline
  rather than failing with a generic error.
- Ask for a benchmark before one is due. **Check:** it says why, not just no.

---

## 4. Turning on the AI evaluator

Everything above works with no AI. This part turns on the rubric evaluator for
writing and mediation, which is the one thing in the product that has never
run against a real model.

### Which provider

**Groq.** Reasons, in order:

1. **It is OpenAI-compatible**, so it needs no new code — the `compatible`
   provider mode already speaks that protocol.
2. **No credit card**, and the free tier is generous enough to run the whole
   fixture suite repeatedly.
3. **It is fast**, which matters because you will be re-running the same
   evaluation while tuning.

Alternatives that would also work with the same settings: Cerebras, Together,
OpenRouter, Mistral. Any endpoint ending in `/v1/chat/completions` does.

### Getting a key

1. Go to <https://console.groq.com> and sign up (Google/GitHub login works).
2. **API Keys** → **Create API Key**. Copy it — it is shown once.
3. Put it **straight into `.env`**. Do not paste it into a terminal or a chat
   window: anything typed at a PowerShell prompt lands in `PSReadLine`'s
   history file in plain text, where it stays.

Create or edit `.env` in the repository root:

```ini
AI_PROVIDER=compatible
AI_BASE_URL=https://api.groq.com/openai/v1
AI_API_KEY=gsk_your_key_here
AI_MODEL=leave-this-blank-for-now
```

`.env` is git-ignored. No other file in this repository should ever contain
the key.

### Choosing a model

Availability moves, so ask the API rather than trusting a name written down
here. This reads the key back out of `.env`, so it never appears on a command
line:

```powershell
# PowerShell's `curl` is an alias for Invoke-WebRequest, which wants -Headers
# as a hashtable rather than a string. Use Invoke-RestMethod, or `curl.exe`
# if you want the real curl.
$key = (Select-String -Path .env -Pattern '^AI_API_KEY=(.+)$').Matches.Groups[1].Value
(Invoke-RestMethod -Uri "https://api.groq.com/openai/v1/models" `
    -Headers @{ Authorization = "Bearer $key" }).data |
    Select-Object id | Sort-Object id
```

Pick the largest general instruct model on the free tier — Llama 70B or Qwen
32B class. The evaluator has to return strict JSON **and** quote the learner's
text accurately, and small models fail both often enough to abstain on
everything. Put the id in `AI_MODEL`.

**Why `compatible` and not `local`:** `local` promises the learner's writing
never leaves the machine, and `evaluator_id` is recorded on every attempt and
shown back to them. Using `local` for Groq would stamp "local" on text that
was sent to a third party. `compatible` says what actually happened.

Restart the API, then:

```powershell
Invoke-RestMethod http://localhost:8000/ready    # ai_provider: compatible
```

### Testing it

```powershell
uv run python scripts/ai_smoke.py
```

That sends six deliberately uneven writing samples — two competent, two weak,
one off-task, one too short to judge — and prints what the model said beside
what a competent marker would have said. It exits non-zero if everything
abstained.

Then the fixture regression and the real thing:

```powershell
make fixtures    # the versioned prompts against recorded cases
make dev         # then submit a writing task through the UI and read it
```

If a sample abstains, the script re-sends that exact request and reports why:
the finish reason, the token usage, and how many of those tokens went on
reasoning rather than output. It uses the provider's own payload builder, so
what it explains is what the product actually sends.

**Reasoning models need a bigger budget.** Thinking and answering share one
`max_tokens` allowance, so a model that spends 1,200 tokens reasoning about a
rubric has 300 left to write JSON in — and a truncated JSON object parses as
nothing, which the provider correctly reports as an abstention and which looks
from outside exactly like a model that cannot do the task. If you see
`finish=length`, raise it:

```ini
AI_MAX_OUTPUT_TOKENS=4000
```

Or pick a model that answers without thinking first. Both are legitimate; the
second is cheaper and faster, the first keeps the better model.

**What to look for, in order of importance:**

1. **Does it abstain more than it judges?** Some abstention is correct and
   designed for. Constant abstention means the model cannot hold the output
   schema, and you need a bigger one.
2. **Are the quoted sentences real?** The provider refuses any judgement
   quoting text the learner did not write, so invented quotes show up as
   abstentions rather than as bad feedback. A high abstention rate with an
   otherwise capable model usually means it is inventing quotations.
3. **Is the feedback specific?** "Good use of past tense" is worthless.
   "You wrote *have visited* where the time is finished" is the standard.
4. **Does it stay provisional?** The UI must still label AI feedback as
   provisional and the evidence must still be recorded at reduced evaluator
   confidence. If a model's judgement ever reads as authoritative, that is a
   bug in the product, not the model.

**Write down the abstention rate.** It is the number that decides whether the
model is usable, and nobody has ever measured it.

### Turning it off

Delete the `AI_PROVIDER` line, or set it back to `disabled`, and restart.
Nothing else changes — the deterministic path is the one every test runs
against.

---

## 5. What you cannot test yet, and why

- **Pronunciation.** There is no audio upload. The speaking lab evidences
  spoken production from a browser transcript and says so; acoustic analysis
  needs `POST /speech/uploads`, which does not exist.
- **The container stack.** Both images build. Nothing has been run end to end
  in containers, because Docker Desktop is not running on this machine.
- **Anything about learning.** Whether the plan helps, whether the thresholds
  are right, whether the graph's 119 dependency claims are true — none of it
  can be tested without learners. Every constant in the system is a defensible
  guess.

---

## 6. If something breaks

- **The gate fails at a step:** the output names the step and stops. Nothing
  after it ran, so fix that one and re-run.
- **`make e2e` times out:** the dev server may still be starting. Run
  `make dev` first, leave it, then run the suite.
- **The AI provider does nothing:** check `/ready` says `compatible`, then
  check the key. The provider abstains silently by design — a missing key
  degrades to deterministic feedback rather than erroring, which is correct
  behaviour and does look like nothing happening.
- **CI is red but local is green:** almost always PostgreSQL vs SQLite. Run
  the migration check in part 1.
