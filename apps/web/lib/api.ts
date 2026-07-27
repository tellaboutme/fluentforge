/**
 * Typed API client.
 *
 * The API serialises snake_case; this module is the single place where that is
 * translated, so no component ever touches a raw wire shape.
 *
 * Errors always arrive as `{code, message, details, request_id}` with stable
 * machine codes, so the UI branches on `code` and never on message text.
 */

import type { ApiErrorCode, Profile } from "@fluentforge/contracts";

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
    return this.status >= 500 || this.code === "curriculum_not_loaded";
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
  "reading_task" | "study_task" | "writing_task" | "listening_task";

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

export type Activity =
  ReadingActivity | StudyActivity | WritingActivity | ListeningActivity;

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

export type ActivityResult =
  ReadingResult | StudyResult | WritingResult | ListeningResult;

/** What the client sends back, by kind. */
export type ActivitySubmission =
  | { answers: Record<string, string>; hintsUsed?: number }
  | { answers: Record<string, string>; plays: number; usedTranscript: boolean }
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
  if ("text" in submission) {
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
