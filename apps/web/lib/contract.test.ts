/**
 * Contract test: the hand-written client must match what the API actually sends.
 *
 * `fixtures/api-payloads.json` is captured from the running FastAPI app
 * (`make capture-fixtures`). These tests fail if the API renames or drops a
 * field the web app depends on — the failure mode a typed client cannot catch
 * on its own, because the types describe an assumption, not the wire.
 */

import { describe, expect, it } from "vitest";

import type { Profile, SkillEstimate } from "@fluentforge/contracts";

import fixtures from "../fixtures/api-payloads.json";
import { camelise } from "./api";
import type {
  Activity,
  DailyPlan,
  DiagnosticReport,
  ItemPrompt,
  NextItem,
  ListeningActivity,
  ListeningResult,
  ReadingActivity,
  ReadingResult,
  StudyActivity,
  StudyResult,
  SubmitResult,
  WritingActivity,
  WritingResult,
} from "./api";

const payloads = fixtures as unknown as Record<string, unknown>;

describe("profile contract", () => {
  const profile = camelise<Profile>(payloads.profile);

  it("provides every field the dashboard renders", () => {
    for (const key of [
      "displayName",
      "targetLevel",
      "dailyMinutes",
      "curriculumVersion",
      "skills",
      "domainSummaries",
    ] satisfies (keyof Profile)[]) {
      expect(profile[key], `missing ${key}`).toBeDefined();
    }
  });

  it("gives each skill everything a card needs", () => {
    const skill: SkillEstimate = profile.skills[0];
    for (const key of [
      "skillKey",
      "domain",
      "title",
      "masteryProbability",
      "confidence",
      "evidenceCount",
      "distinctContexts",
      "status",
    ] satisfies (keyof SkillEstimate)[]) {
      expect(skill[key], `missing ${key}`).toBeDefined();
    }
    // Present but null is the meaningful case; `toBeDefined` would pass on a
    // missing key, so assert the property exists explicitly.
    expect(Object.hasOwn(skill, "cefrEstimate")).toBe(true);
  });

  it("does not carry a single overall level for the learner", () => {
    expect(Object.hasOwn(profile, "cefrEstimate")).toBe(false);
    expect(Object.hasOwn(profile, "level")).toBe(false);
  });

  it("withholds levels from unobserved skills", () => {
    const unobserved = profile.skills.filter(
      (skill) => skill.evidenceCount === 0,
    );
    expect(unobserved.length).toBeGreaterThan(0);
    for (const skill of unobserved) {
      expect(skill.cefrEstimate).toBeNull();
    }
  });

  it("uses status values the UI has wording for", () => {
    const known = ["unobserved", "emerging", "supported", "independent"];
    for (const skill of profile.skills) {
      expect(known).toContain(skill.status);
    }
  });
});

describe("diagnostic contract", () => {
  const next = camelise<NextItem>(payloads.next);
  const report = camelise<DiagnosticReport>(payloads.report);

  it("serves an item with the fields the player needs", () => {
    const item = next.item as ItemPrompt;
    for (const key of [
      "key",
      "itemType",
      "prompt",
      "instructions",
      "options",
    ] satisfies (keyof ItemPrompt)[]) {
      expect(item[key], `missing ${key}`).toBeDefined();
    }
  });

  it("never ships an answer key to the client", () => {
    const raw = JSON.stringify(payloads.next);
    expect(raw).not.toContain("answer_key");
    expect(raw).not.toContain("distractor");
  });

  it("only uses item types the player can render", () => {
    const renderable = [
      "multiple_choice",
      "gap_fill",
      "word_order",
      "self_assessment",
      "written_response",
    ];
    expect(renderable).toContain((next.item as ItemPrompt).itemType);
    expect(renderable).toContain(
      camelise<ItemPrompt>(payloads.writing_prompt).itemType,
    );
  });

  it("returns a report with caveats that must be shown", () => {
    expect(report.caveats.length).toBeGreaterThan(0);
    expect(report.outcomes).toBeDefined();
    expect(Object.hasOwn(report, "startingBand")).toBe(true);
  });
});

describe("written response contract", () => {
  const prompt = camelise<ItemPrompt>(payloads.writing_prompt);
  const result = camelise<SubmitResult>(payloads.writing_submit);

  it("states its length requirement before the learner writes", () => {
    expect(prompt.itemType).toBe("written_response");
    expect(prompt.minWords).toBeGreaterThan(0);
    expect(prompt.maxWords).toBeGreaterThan(prompt.minWords as number);
  });

  it("offers no options, so the UI must render a free-text field", () => {
    expect(prompt.options).toEqual([]);
  });

  it("is flagged provisional so the UI cannot present it as a verdict", () => {
    expect(result.provisional).toBe(true);
  });

  it("returns per-check detail the learner can act on", () => {
    expect(result.checks.length).toBeGreaterThan(0);
    for (const check of result.checks) {
      expect(typeof check.code).toBe("string");
      expect(typeof check.passed).toBe("boolean");
      expect(check.message.length).toBeGreaterThan(0);
    }
  });

  it("never sends an expected answer for free writing", () => {
    expect(result.expected).toEqual([]);
  });
});

describe("daily plan contract", () => {
  const plan = camelise<DailyPlan>(payloads.plan);

  it("provides everything the plan panel renders", () => {
    for (const key of [
      "requestedMinutes",
      "totalMinutes",
      "engineVersion",
      "items",
      "hasReceptive",
      "hasProductive",
      "unmetConstraints",
    ] satisfies (keyof DailyPlan)[]) {
      expect(plan[key], `missing ${key}`).toBeDefined();
    }
  });

  it("gives every item a reason the learner can read", () => {
    expect(plan.items.length).toBeGreaterThan(0);
    for (const item of plan.items) {
      expect(item.explanation.length).toBeGreaterThan(0);
      expect(Object.keys(item.components).length).toBeGreaterThan(0);
    }
  });

  it("keeps the plan inside the learner's time budget", () => {
    expect(plan.totalMinutes).toBeLessThanOrEqual(plan.requestedMinutes);
  });

  it("only uses activity kinds the UI has wording for", () => {
    const known = [
      "review",
      "input",
      "study",
      "output",
      "speaking",
      "reflection",
    ];
    for (const item of plan.items) {
      expect(known).toContain(item.kind);
    }
  });

  it("makes every working slot openable, not just reading", () => {
    // A plan full of names that go nowhere is the failure mode this milestone
    // existed to fix. Reading, focused study, and written output all resolve;
    // speaking and reflection have no activity behind them yet and stay
    // deliberately unlinked rather than pointing somewhere wrong.
    const openable = (key: string) =>
      ["read:", "study:", "write:", "listen:"].some((prefix) =>
        key.startsWith(prefix),
      );

    for (const item of plan.items) {
      if (!["input", "study", "output"].includes(item.kind)) continue;
      expect(
        openable(item.activityKey),
        `${item.kind} slot goes nowhere: ${item.activityKey}`,
      ).toBe(true);
    }

    const openableItems = plan.items.filter(
      (item) => openable(item.activityKey) || item.kind === "review",
    );
    expect(openableItems.length).toBeGreaterThan(0);
  });

  it("orders items by an explicit sequence", () => {
    const sequences = plan.items.map((item) => item.sequence);
    expect(sequences).toEqual([...sequences].sort((a, b) => a - b));
  });
});

describe("activity contract", () => {
  // One endpoint pair serves three kinds, discriminated on `activityType`.
  // The client models them as a union, so a rename in any one of them must
  // fail here rather than in the browser.
  function fixture(name: string): unknown {
    const payload = payloads[name];
    if (payload === undefined) {
      throw new Error(
        `Fixture "${name}" is missing. Run \`make capture-fixtures\` after ` +
          `changing an API response shape.`,
      );
    }
    return payload;
  }

  it("discriminates every kind on the same field", () => {
    expect(camelise<Activity>(fixture("reading_activity")).activityType).toBe(
      "reading_task",
    );
    expect(camelise<Activity>(fixture("study_activity")).activityType).toBe(
      "study_task",
    );
    expect(camelise<Activity>(fixture("writing_activity")).activityType).toBe(
      "writing_task",
    );
  });

  it("gives a reading task everything the player renders", () => {
    const activity = camelise<ReadingActivity>(fixture("reading_activity"));
    for (const key of [
      "activityKey",
      "title",
      "cefrLevel",
      "estimatedMinutes",
      "body",
      "wordCount",
      "questions",
    ] satisfies (keyof ReadingActivity)[]) {
      expect(activity[key], `missing ${key}`).toBeDefined();
    }
    expect(activity.questions.length).toBeGreaterThan(0);
  });

  it("gives a study unit its explanation and typed items", () => {
    const activity = camelise<StudyActivity>(fixture("study_activity"));
    expect(activity.explanation.length).toBeGreaterThan(0);
    expect(activity.examples.length).toBeGreaterThan(0);
    expect(activity.items.length).toBeGreaterThan(0);

    for (const item of activity.items) {
      expect(["choice", "gap_fill"]).toContain(item.itemType);
      // The label is what the learner sees; a raw code would leak the
      // taxonomy into the interface.
      expect(item.featureLabel.length).toBeGreaterThan(0);
      expect(item.featureLabel).not.toContain(".");
      if (item.itemType === "choice") {
        expect(item.options.length).toBeGreaterThan(1);
      } else {
        expect(item.options).toEqual([]);
      }
    }
  });

  it("never ships a study answer or note before the attempt", () => {
    const raw = JSON.stringify(fixture("study_activity"));
    expect(raw).not.toContain('"answer"');
    expect(raw).not.toContain('"note"');
    expect(raw).not.toContain('"accepted"');
  });

  it("shows a writing task its own requirements", () => {
    const activity = camelise<WritingActivity>(fixture("writing_activity"));
    expect(activity.prompt.length).toBeGreaterThan(0);
    expect(activity.guidance.length).toBeGreaterThan(0);
    expect(activity.maxWords).toBeGreaterThan(activity.minWords);
    expect(activity.minSentences).toBeGreaterThanOrEqual(2);
    // A word count the learner cannot see is a trap, not a requirement.
    expect(Object.hasOwn(activity, "requiredElements")).toBe(true);
  });

  it("returns the note only after the study attempt", () => {
    const result = camelise<StudyResult>(fixture("study_result"));
    expect(result.activityType).toBe("study_task");
    for (const outcome of result.results) {
      expect(outcome.note.length).toBeGreaterThan(0);
      expect(outcome.featureLabel.length).toBeGreaterThan(0);
    }
  });

  it("admits that study practice was scaffolded", () => {
    // The explanation was on screen. A perfect score here is not recall, and
    // the wire has to carry that or the UI cannot say it.
    const result = camelise<StudyResult>(fixture("study_result"));
    expect(result.independence).toBeGreaterThan(0);
    expect(result.independence).toBeLessThan(1);
    expect(Array.isArray(result.loggedFeatures)).toBe(true);
  });

  it("flags written feedback as provisional", () => {
    // Nothing has judged accuracy. The UI must be able to say so.
    const result = camelise<WritingResult>(fixture("writing_result"));
    expect(result.activityType).toBe("writing_task");
    expect(result.provisional).toBe(true);
    expect(result.checks.length).toBeGreaterThan(0);
    for (const check of result.checks) {
      expect(check.message.length).toBeGreaterThan(0);
    }
  });

  it("gives a listening clip its scene, transcript and pace", () => {
    const activity = camelise<ListeningActivity>(fixture("listening_activity"));
    expect(activity.activityType).toBe("listening_task");
    expect(activity.setting.length).toBeGreaterThan(0);
    // The transcript is the stimulus, not an answer key: the client speaks it,
    // and a learner who cannot use audio needs it.
    expect(activity.transcript.length).toBeGreaterThan(0);
    expect(activity.speechRate).toBeGreaterThan(0);
    expect(Object.hasOwn(activity, "audio")).toBe(true);
    expect(activity.questions.length).toBeGreaterThan(0);
  });

  it("never ships a listening answer key", () => {
    const raw = JSON.stringify(fixture("listening_activity"));
    expect(raw).not.toContain('"answer"');
  });

  it("reports how a clip was understood, not just whether", () => {
    const result = camelise<ListeningResult>(fixture("listening_result"));
    expect(result.activityType).toBe("listening_task");
    expect(result.plays).toBeGreaterThan(0);
    expect(result.independence).toBeGreaterThan(0);
    // Answered by ear in the fixture, so the evidence stands.
    expect(result.usedTranscript).toBe(false);
    expect(result.evidenceRecorded).toBe(true);
  });

  it("scores a reading task as comprehension, not a percentage", () => {
    const result = camelise<ReadingResult>(fixture("reading_result"));
    expect(result.activityType).toBe("reading_task");
    expect(result.total).toBe(result.results.length);
    expect(result.explanation).not.toContain("%");
  });
});

describe("auth contract", () => {
  it("returns a bearer token on registration", () => {
    const registered = camelise<{ token: { accessToken: string } }>(
      payloads.register,
    );
    expect(registered.token.accessToken).toBeTruthy();
  });

  it("never echoes a password or hash", () => {
    const raw = JSON.stringify(payloads.register);
    expect(raw).not.toContain("password");
    expect(raw).not.toContain("$2b$");
  });
});
