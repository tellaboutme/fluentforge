/**
 * Typed API client.
 *
 * The API serialises snake_case; this module is the single place where that is
 * translated, so no component ever touches a raw wire shape.
 *
 * Errors always arrive as `{code, message, details, request_id}` with stable
 * machine codes, so the UI branches on `code` and never on message text.
 */

import type {
  ApiErrorCode,
  Profile,
  SkillStatus,
} from "@fluentforge/contracts";

import { isOffline } from "./online";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly code: ApiErrorCode | string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** True when retrying could plausibly succeed. */
  get isTransient(): boolean {
    return (
      this.status >= 500 ||
      this.code === "curriculum_not_loaded" ||
      // Offline is the most transient failure there is: the same request
      // will work unchanged the moment the network returns.
      this.code === "offline" ||
      this.code === "network_unavailable"
    );
  }
}

type Json = Record<string, unknown>;

function toCamel(key: string): string {
  return key.replace(/_([a-z0-9])/g, (_, char: string) => char.toUpperCase());
}

/** Recursively camelise object keys. Arrays and primitives pass through. */
export function camelise<T>(value: unknown): T {
  if (Array.isArray(value)) {
    return value.map((entry) => camelise(entry)) as T;
  }
  if (value !== null && typeof value === "object") {
    const result: Json = {};
    for (const [key, entry] of Object.entries(value as Json)) {
      result[toCamel(key)] = camelise(entry);
    }
    return result as T;
  }
  return value as T;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
}

export async function request<T>(
  path: string,
  { method = "GET", body, token, signal }: RequestOptions = {},
): Promise<T> {
  // Refuse to start a mutation with no network, rather than letting it fail
  // as a generic connection error.
  //
  // Everything the learner submits is scored on the server, against
  // curriculum the browser does not have and by a mastery model it does not
  // run. So there is no honest way to complete an activity offline: scoring
  // locally would give a mark the server would not have given, and queuing
  // the submission to fire later would record evidence at a moment the
  // learner was not present for -- and would need a timestamp the client
  // chose, which is not a thing a client may be trusted with.
  //
  // Reads are still attempted: the service worker may have a saved copy, and
  // it is the one that decides whether it does.
  if (method !== "GET" && isOffline()) {
    throw new ApiError(
      0,
      "offline",
      "You are offline, so this cannot be checked yet.",
      {},
    );
  }

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    // A network failure is not a protocol error; give it its own code so the UI
    // can say "can't reach the server" rather than "something went wrong".
    throw new ApiError(
      0,
      "network_unavailable",
      "Could not reach the server.",
      {
        cause: String(cause),
      },
    );
  }

  if (response.status === 204) return undefined as T;

  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const error = (payload ?? {}) as Json;
    throw new ApiError(
      response.status,
      typeof error.code === "string" ? error.code : "http_error",
      typeof error.message === "string"
        ? error.message
        : "Something went wrong.",
      (error.details as Record<string, unknown>) ?? {},
      typeof error.request_id === "string" ? error.request_id : null,
    );
  }

  return camelise<T>(payload);
}

// --- Endpoints -------------------------------------------------------------

export interface AuthResult {
  accessToken: string;
  expiresIn: number;
}

export async function register(input: {
  email: string;
  password: string;
  displayName: string;
  dailyMinutes: number;
}): Promise<AuthResult> {
  const result = await request<{ token: AuthResult }>("/api/v1/auth/register", {
    method: "POST",
    body: {
      email: input.email,
      password: input.password,
      display_name: input.displayName,
      daily_minutes: input.dailyMinutes,
    },
  });
  return result.token;
}

export async function login(input: {
  email: string;
  password: string;
}): Promise<AuthResult> {
  return request<AuthResult>("/api/v1/auth/login", {
    method: "POST",
    body: input,
  });
}

export async function fetchProfile(token: string): Promise<Profile> {
  return request<Profile>("/api/v1/profile", { token });
}

export interface DiagnosticSession {
  id: string;
  status: string;
  answered: number;
}

export type ItemTypeName =
  | "multiple_choice"
  | "gap_fill"
  | "word_order"
  | "self_assessment"
  | "written_response";

export interface ItemPrompt {
  key: string;
  itemType: ItemTypeName;
  skillKey: string;
  cefrLevel: string;
  prompt: string;
  instructions: string;
  options: string[];
  difficulty: number;
  /** Written responses only; null for closed items. */
  minWords: number | null;
  maxWords: number | null;
}

export interface ResponseCheck {
  code: string;
  passed: boolean;
  message: string;
}

export interface NextItem {
  sessionId: string;
  finished: boolean;
  answered: number;
  item: ItemPrompt | null;
}

export interface SubmitResult {
  correct: boolean;
  score: number;
  explanation: string;
  expected: string[];
  answered: number;
  finished: boolean;
  checks: ResponseCheck[];
  /**
   * True when scoring is deterministic-only and cannot judge accuracy.
   * The UI must not present a provisional score as a verdict.
   */
  provisional: boolean;
}

export interface DiagnosticOutcome {
  skillKey: string;
  title: string;
  cefrLevel: string;
  masteryProbability: number;
  confidence: number;
  evidenceCount: number;
  distinctContexts: number;
  status: string;
}

export interface DiagnosticReport {
  sessionId: string;
  itemsAnswered: number;
  skillsObserved: number;
  startingBand: string | null;
  outcomes: DiagnosticOutcome[];
  caveats: string[];
}

export interface PlanItem {
  sequence: number;
  activityKey: string;
  activityType: string;
  estimatedMinutes: number;
  title: string;
  kind: string;
  skillKey: string;
  domain: string;
  reasonCodes: string[];
  /** A one-line, learner-facing reason for this item's presence. */
  explanation: string;
  priority: number;
  /** Every priority component, so a plan decision can be audited. */
  components: Record<string, number>;
}

export interface DailyPlan {
  id: string;
  planDate: string;
  requestedMinutes: number;
  totalMinutes: number;
  status: string;
  engineVersion: string;
  items: PlanItem[];
  hasReceptive: boolean;
  hasProductive: boolean;
  /** Constraints the planner could not satisfy. Shown, not hidden. */
  unmetConstraints: string[];
}

export async function fetchTodayPlan(token: string): Promise<DailyPlan> {
  return request<DailyPlan>("/api/v1/plans/today", { token });
}

export async function regeneratePlan(token: string): Promise<DailyPlan> {
  return request<DailyPlan>("/api/v1/plans/generate", {
    method: "POST",
    token,
    body: { regenerate: true },
  });
}

// --- Activities ------------------------------------------------------------
//
// Four kinds share one pair of endpoints, discriminated on `activityType`.
// Modelled as a union rather than one shape with optional fields so the
// compiler forces every consumer to handle all four: a reading task has no
// word limit and a writing task has no options, and a type that admits both
// lets a component render nonsense.

/** The stable machine values the API discriminates on. */
export type ActivityType =
  | "reading_task"
  | "study_task"
  | "writing_task"
  | "listening_task"
  | "speaking_task";

export interface ActivityQuestion {
  key: string;
  questionType: "gist" | "detail" | "inference";
  prompt: string;
  options: string[];
}

interface ActivityBase {
  activityKey: string;
  title: string;
  cefrLevel: string;
  skillKey: string;
  estimatedMinutes: number;
}

export interface ReadingActivity extends ActivityBase {
  activityType: "reading_task";
  body: string;
  wordCount: number;
  questions: ActivityQuestion[];
}

export interface StudyItemPrompt {
  key: string;
  itemType: "choice" | "gap_fill";
  feature: string;
  /** What this item practises, in words a learner recognises. */
  featureLabel: string;
  prompt: string;
  /** Empty for gap-fill items, which are typed rather than chosen. */
  options: string[];
}

export interface StudyActivity extends ActivityBase {
  activityType: "study_task";
  explanation: string;
  examples: string[];
  items: StudyItemPrompt[];
}

export interface WritingActivity extends ActivityBase {
  activityType: "writing_task";
  genre: string;
  prompt: string;
  guidance: string[];
  minWords: number;
  maxWords: number;
  minSentences: number;
  /** Shown, not hidden: this is a task requirement, not a trick. */
  requiredElements: string[];
}

export interface ListeningActivity extends ActivityBase {
  activityType: "listening_task";
  /** Who is speaking and where. Real listening always has context. */
  setting: string;
  /**
   * The words of the clip.
   *
   * Sent because the client speaks them, and because a learner who cannot use
   * audio must still be able to take part. Keep it hidden until asked:
   * revealing it is reported back and costs the listening evidence.
   */
  transcript: string;
  wordCount: number;
  /** Playback speed for synthesised speech, relative to normal. */
  speechRate: number;
  /** A recording to prefer over synthesis, when the deployment has one. */
  audio: string | null;
  questions: ActivityQuestion[];
}

export interface SpeakingActivity extends ActivityBase {
  activityType: "speaking_task";
  format: string;
  prompt: string;
  guidance: string[];
  /** Planning time is part of the task: it changes what is measured. */
  preparationSeconds: number;
  minSeconds: number;
  maxSeconds: number;
  minWords: number;
  requiredElements: string[];
}

export interface MediationSource {
  key: string;
  title: string;
  /** `article`, `email`, `chart_summary`… Mediating across different kinds
   * of source is harder than across three articles, so the kind is shown. */
  kind: string;
  /** The source itself. Sent in full: it is the material, not an answer key. */
  text: string;
  wordCount: number;
}

export interface MediationActivity extends ActivityBase {
  activityType: "mediation_task";
  /** Who the account is for and why. It decides which details matter. */
  brief: string;
  sources: MediationSource[];
  guidance: string[];
  minWords: number;
  maxWords: number;
  minSentences: number;
  requiredElements: string[];
  /** Longest run of words an account may share with a source. Shown in
   * advance, so the learner is told the rule before breaking it. */
  maxVerbatimWords: number;
}

export type Activity =
  | ReadingActivity
  | StudyActivity
  | WritingActivity
  | ListeningActivity
  | SpeakingActivity
  | MediationActivity;

export interface QuestionOutcome {
  key: string;
  questionType: string;
  correct: boolean;
  expected: string;
}

export interface ReadingResult {
  activityType: "reading_task";
  activityKey: string;
  score: number;
  correctCount: number;
  total: number;
  explanation: string;
  results: QuestionOutcome[];
  evidenceRecorded: boolean;
}

export interface StudyItemOutcome {
  key: string;
  feature: string;
  featureLabel: string;
  correct: boolean;
  expected: string;
  /** The teaching moment. Shown right or wrong. */
  note: string;
}

export interface StudyResult {
  activityType: "study_task";
  activityKey: string;
  score: number;
  correctCount: number;
  total: number;
  explanation: string;
  results: StudyItemOutcome[];
  evidenceRecorded: boolean;
  /** Below 1.0: the explanation was on screen while you practised. */
  independence: number;
  loggedFeatures: string[];
}

export interface WritingCheckOutcome {
  code: string;
  passed: boolean;
  message: string;
}

export interface RubricDimensionOutcome {
  name: string;
  score: number;
  confidence: number;
  /** Quotations from the learner's own text. A score without evidence is a guess. */
  evidence: string[];
}

export interface PriorityFeedbackOutcome {
  category: string;
  original: string;
  improved: string;
  explanation: string;
}

export interface WritingResult {
  activityType: "writing_task";
  activityKey: string;
  score: number;
  explanation: string;
  checks: WritingCheckOutcome[];
  wordCount: number;
  sentenceCount: number;
  lexicalVariety: number;
  connectivesUsed: string[];
  missingElements: string[];
  evidenceRecorded: boolean;
  /** True while nothing has judged accuracy. The UI must not hide this. */
  provisional: boolean;
  /** Empty unless a rubric actually ran and was trusted. */
  rubric: RubricDimensionOutcome[];
  /** At most three. Correcting everything teaches nothing. */
  priorityFeedback: PriorityFeedbackOutcome[];
  /** Which evaluator judged this, or null. */
  evaluatedBy: string | null;
}

export interface ListeningResult {
  activityType: "listening_task";
  activityKey: string;
  score: number;
  correctCount: number;
  total: number;
  explanation: string;
  results: QuestionOutcome[];
  evidenceRecorded: boolean;
  plays: number;
  /** Lower when the clip took many passes to understand. */
  independence: number;
  /** True when the transcript was read, in which case nothing was recorded. */
  usedTranscript: boolean;
}

export interface SpeakingResult {
  activityType: "speaking_task";
  activityKey: string;
  score: number;
  explanation: string;
  checks: WritingCheckOutcome[];
  wordCount: number;
  spokenSeconds: number;
  /** What the browser heard. Shown so the learner can judge it themselves. */
  transcript: string;
  /** Displayed, never scored: recognisers are worse on accented speech. */
  recognitionConfidence: number | null;
  evidenceRecorded: boolean;
  typedInstead: boolean;
  /** Always true: nothing judged delivery. The UI must not hide this. */
  provisional: boolean;
}

export interface MediationResult {
  activityType: "mediation_task";
  activityKey: string;
  score: number;
  explanation: string;
  checks: WritingCheckOutcome[];
  wordCount: number;
  /** Which sources left a trace. An approximation, shown as one. */
  usedSources: string[];
  unusedSources: string[];
  /** Longest run shared with any source, after marked quotations are removed.
   * Reported either way, so a learner can see they were nowhere near it. */
  longestCopiedRun: number;
  copiedFrom: string | null;
  evidenceRecorded: boolean;
  /** True while nothing has judged whether the sources were conveyed
   * faithfully — which is the whole point. The UI must not hide this. */
  provisional: boolean;
  rubric: RubricDimensionOutcome[];
  priorityFeedback: PriorityFeedbackOutcome[];
  evaluatedBy: string | null;
}

export type ActivityResult =
  | ReadingResult
  | StudyResult
  | WritingResult
  | ListeningResult
  | SpeakingResult
  | MediationResult;

/** What the client sends back, by kind. */
export type ActivitySubmission =
  | { answers: Record<string, string>; hintsUsed?: number }
  | { answers: Record<string, string>; plays: number; usedTranscript: boolean }
  | {
      text: string;
      spokenSeconds: number;
      recognitionConfidence: number | null;
      typedInstead: boolean;
    }
  | { text: string };

export async function fetchActivity(
  token: string,
  activityKey: string,
): Promise<Activity> {
  return request<Activity>(`/api/v1/activities/${activityKey}`, { token });
}

export async function completeActivity(
  token: string,
  activityKey: string,
  submission: ActivitySubmission,
): Promise<ActivityResult> {
  let body: Record<string, unknown>;
  if ("spokenSeconds" in submission) {
    body = {
      text: submission.text,
      spoken_seconds: submission.spokenSeconds,
      recognition_confidence: submission.recognitionConfidence,
      typed_instead: submission.typedInstead,
    };
  } else if ("text" in submission) {
    body = { text: submission.text };
  } else if ("plays" in submission) {
    body = {
      answers: submission.answers,
      plays: submission.plays,
      used_transcript: submission.usedTranscript,
    };
  } else {
    body = {
      answers: submission.answers,
      hints_used: submission.hintsUsed ?? 0,
    };
  }

  return request<ActivityResult>(`/api/v1/activities/${activityKey}/complete`, {
    method: "POST",
    token,
    body,
  });
}

export type ReviewGrade = "forgot" | "hard" | "good" | "easy";

export interface ReviewCard {
  id: string;
  memoryObjectKey: string;
  reviewMode: string;
  lemma: string;
  pos: string;
  cefrLevel: string;
  /** Withheld until the learner has committed to an answer. */
  meaning: string | null;
  example: string | null;
  repetitions: number;
  lapses: number;
}

export interface DueReviews {
  dueNow: number;
  returned: number;
  cards: ReviewCard[];
}

export interface ReviewAnswer {
  id: string;
  intervalDays: number;
  dueAt: string;
  explanation: string;
  repetitions: number;
  lapses: number;
  meaning: string;
  example: string;
}

export async function fetchDueReviews(token: string): Promise<DueReviews> {
  return request<DueReviews>("/api/v1/reviews/due", { token });
}

export async function seedReviews(
  token: string,
): Promise<{ created: number; dueNow: number }> {
  return request("/api/v1/reviews/seed", { method: "POST", token });
}

export async function answerReview(
  token: string,
  reviewId: string,
  grade: ReviewGrade,
): Promise<ReviewAnswer> {
  return request<ReviewAnswer>(`/api/v1/reviews/${reviewId}/answer`, {
    method: "POST",
    token,
    body: { grade },
  });
}

export async function startDiagnostic(
  token: string,
): Promise<DiagnosticSession> {
  return request<DiagnosticSession>("/api/v1/diagnostics", {
    method: "POST",
    token,
  });
}

export async function fetchNextItem(
  token: string,
  sessionId: string,
): Promise<NextItem> {
  return request<NextItem>(`/api/v1/diagnostics/${sessionId}/next`, { token });
}

export async function submitResponse(
  token: string,
  sessionId: string,
  input: { itemKey: string; response: string; hintsUsed?: number },
): Promise<SubmitResult> {
  return request<SubmitResult>(`/api/v1/diagnostics/${sessionId}/responses`, {
    method: "POST",
    token,
    body: {
      item_key: input.itemKey,
      response: input.response,
      hints_used: input.hintsUsed ?? 0,
    },
  });
}

export async function completeDiagnostic(
  token: string,
  sessionId: string,
): Promise<DiagnosticReport> {
  return request<DiagnosticReport>(
    `/api/v1/diagnostics/${sessionId}/complete`,
    {
      method: "POST",
      token,
    },
  );
}

// --- Benchmarks ------------------------------------------------------------

export interface BenchmarkEligibility {
  due: boolean;
  /** Always says what has to happen next, never "you are not allowed". */
  reason: string;
  nextDueAt: string | null;
}

export interface BenchmarkItem {
  key: string;
  itemType: string;
  skillKey: string;
  cefrLevel: string;
  prompt: string;
  instructions: string;
  options: string[];
}

export interface BenchmarkSession {
  sessionId: string;
  band: string;
  items: BenchmarkItem[];
  /** Always true. The UI must not present a benchmark as ordinary practice. */
  unaided: true;
}

export interface BenchmarkAnswerOutcome {
  itemKey: string;
  correct: boolean;
  score: number;
  remaining: number;
}

export interface BenchmarkResult {
  sessionId: string;
  band: string;
  answered: number;
  correct: number;
  score: number;
  /** Skills this benchmark moved *down*. Shown, never buried. */
  lowered: string[];
}

export async function fetchBenchmarkEligibility(
  token: string,
): Promise<BenchmarkEligibility> {
  return request<BenchmarkEligibility>("/api/v1/benchmarks/eligibility", {
    token,
  });
}

export async function startBenchmark(token: string): Promise<BenchmarkSession> {
  return request<BenchmarkSession>("/api/v1/benchmarks", {
    method: "POST",
    token,
  });
}

/** No `hintsUsed`, and its absence is the contract. See `docs/API_CONTRACTS.md`. */
export async function answerBenchmarkItem(
  token: string,
  sessionId: string,
  input: { itemKey: string; response: string },
): Promise<BenchmarkAnswerOutcome> {
  return request<BenchmarkAnswerOutcome>(
    `/api/v1/benchmarks/${sessionId}/responses`,
    {
      method: "POST",
      token,
      body: { item_key: input.itemKey, response: input.response },
    },
  );
}

export async function completeBenchmark(
  token: string,
  sessionId: string,
): Promise<BenchmarkResult> {
  return request<BenchmarkResult>(`/api/v1/benchmarks/${sessionId}/complete`, {
    method: "POST",
    token,
  });
}

// --- Reflection ------------------------------------------------------------

export interface RecurringError {
  code: string;
  /** Rendered, never the raw code. */
  label: string;
  description: string;
  occurrences: number;
  blocksMeaning: boolean;
}

export interface ReflectionPrompt {
  recurringErrors: RecurringError[];
  untouchedSkills: string[];
  /** How much of the learner's own work nothing has judged. */
  unjudgedCount: number;
  previousNote: string | null;
}

export interface ReflectionSaved {
  saved: boolean;
  /** Always false. Nothing here was checked, corrected, or counted. */
  scored: boolean;
  evidenceRecorded: boolean;
}

export async function fetchReflectionPrompt(
  token: string,
): Promise<ReflectionPrompt> {
  return request<ReflectionPrompt>("/api/v1/reflection", { token });
}

export async function saveReflection(
  token: string,
  note: string,
): Promise<ReflectionSaved> {
  return request<ReflectionSaved>("/api/v1/reflection", {
    method: "POST",
    token,
    body: { note },
  });
}

// --- History ---------------------------------------------------------------

export interface HistoryItem {
  attemptId: string;
  activityKey: string;
  activityType: string;
  submittedAt: string;
  /** The learner's own words where there are any. */
  summary: string;
  score: number | null;
  /** False for reflection, and anything else nothing assessed. */
  wasJudged: boolean;
}

export interface HistoryPage {
  items: HistoryItem[];
  nextBefore: string | null;
}

export interface AttemptFeedback {
  attemptId: string;
  activityKey: string;
  activityType: string;
  submittedAt: string;
  evaluatorId: string | null;
  /** The stored response, verbatim. Never recomputed. */
  response: Record<string, unknown>;
  wasJudged: boolean;
  /** True when this might be judged differently today. Date it, do not
   * present it as current. */
  isStale: boolean;
}

export async function fetchHistory(
  token: string,
  before?: string | null,
): Promise<HistoryPage> {
  const query = before ? `?before=${encodeURIComponent(before)}` : "";
  return request<HistoryPage>(`/api/v1/attempts${query}`, { token });
}

export async function fetchAttemptFeedback(
  token: string,
  attemptId: string,
): Promise<AttemptFeedback> {
  return request<AttemptFeedback>(`/api/v1/attempts/${attemptId}/feedback`, {
    token,
  });
}

// --- The error log ---------------------------------------------------------

/**
 * Why an error has no openable practice. Stable machine values; the wording
 * lives in the screen, not on the wire.
 */
export type NoRemedyReason = "no_feature" | "needs_speech" | "not_written";

export interface ErrorPattern {
  code: string;
  /** Rendered. Never show `code`: it is a machine identifier and reads as
   * one. */
  label: string;
  description: string;
  occurrences: number;
  firstSeenAt: string;
  lastSeenAt: string;
  blocksMeaning: boolean;
  priority: number;
  /** Whether this has recurred often enough to be in the review queue. A
   * single slip is recorded and not yet drilled, and the learner should be
   * able to see that is deliberate. */
  scheduled: boolean;
  remedyKey: string | null;
  remedyTitle: string | null;
  /** Which kind of activity the remedy opens. A comprehension error opens
   * another text, not a study unit. */
  remedyType: string | null;
  noRemedyReason: NoRemedyReason | null;
}

export interface ErrorLog {
  items: ErrorPattern[];
  withoutRemedy: number;
}

export async function fetchErrorLog(token: string): Promise<ErrorLog> {
  return request<ErrorLog>("/api/v1/profile/errors", { token });
}

// --- The skill map ---------------------------------------------------------

export interface SkillMapNode {
  key: string;
  title: string;
  domain: string;
  level: string;
  status: SkillStatus;
  masteryProbability: number;
  confidence: number;
  evidenceCount: number;
  /** Null until the skill reaches `supported`. Render as "needs evidence",
   * never as a low level. */
  cefrEstimate: string | null;
  /** Skills this one is holding back. Populated only where the learner is
   * actually weak at it. */
  blocking: string[];
  /** Prerequisites of this skill the learner is weak at. */
  blockedBy: string[];
}

export interface SkillMapEdge {
  source: string;
  target: string;
  relation: "prerequisite" | "supports";
  /** How strongly the claim is believed, not how important the skill is. */
  weight: number;
}

export interface SkillMap {
  nodes: SkillMapNode[];
  edges: SkillMapEdge[];
  /** Always non-empty, and the client must surface it: the graph is expert
   * judgement, not measurement. */
  caveats: string[];
}

export async function fetchSkillMap(token: string): Promise<SkillMap> {
  return request<SkillMap>("/api/v1/profile/skill-map", { token });
}
