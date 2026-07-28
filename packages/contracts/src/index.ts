/**
 * Shared API contracts.
 *
 * Mirrors `apps/api/app/schemas`. Changing a shape here without changing it
 * there (or vice versa) is a breaking change: bump the API version.
 *
 * The API serialises snake_case; clients are expected to camelise at the
 * fetch boundary.
 */

export type CefrLevel = "A1" | "A2" | "B1" | "B2" | "C1" | "C2";

export type SkillDomain =
  | "listening"
  | "spoken_production"
  | "spoken_interaction"
  | "pronunciation"
  | "reading"
  | "written_production"
  | "written_interaction"
  | "vocabulary"
  | "grammar"
  | "fluency"
  | "discourse"
  | "pragmatics"
  | "mediation"
  | "learning_strategies";

/**
 * A skill is only placed at a CEFR level once evidence supports it.
 * `unobserved` and `emerging` must render as "needs evidence", never as a level.
 */
export type SkillStatus = "unobserved" | "emerging" | "supported" | "independent";

export interface SkillEstimate {
  skillKey: string;
  domain: SkillDomain;
  title: string;
  /** Null until the skill reaches `supported`. */
  cefrEstimate: CefrLevel | null;
  masteryProbability: number;
  /** Independent of `masteryProbability`: how much the estimate can be trusted. */
  confidence: number;
  evidenceCount: number;
  distinctContexts: number;
  lastObservedAt: string | null;
  status: SkillStatus;
}

export interface DomainSummary {
  domain: SkillDomain;
  trackedSkills: number;
  observedSkills: number;
  meanConfidence: number;
}

/**
 * There is deliberately no single current level on the profile.
 * `targetLevel` is the learner's goal, not an assessment.
 */
export interface Profile {
  userId: string;
  displayName: string;
  targetLevel: CefrLevel;
  dailyMinutes: number;
  explanationLanguage: string;
  timezone: string;
  goals: Record<string, unknown>;
  interests: Record<string, unknown>;
  /** What the learner is studying English for. Raises the priority of its
   * domains; it can never suppress a weak prerequisite. */
  trackKey: string;
  /** Null when the curriculum no longer defines the stored key. Null is the
   * honest answer: offer the choice again rather than invent a name. */
  trackName: string | null;
  curriculumVersion: string;
  skills: SkillEstimate[];
  domainSummaries: DomainSummary[];
}

export interface TokenResponse {
  accessToken: string;
  tokenType: "bearer";
  expiresIn: number;
}

export interface Account {
  id: string;
  email: string;
}

export type PlanReasonCode =
  | "DUE_REVIEW"
  | "WEAK_PREREQUISITE"
  | "GOAL_RELEVANCE"
  | "UNCERTAINTY"
  | "SKILL_BALANCE"
  | "ERROR_FOLLOW_UP"
  | "MODALITY_DIVERSITY"
  | "TRANSFER_CHECK";

export interface PlanReason {
  code: PlanReasonCode;
  explanation: string;
}

/** Stable machine codes returned by the API. Never reuse or rename one. */
export type ApiErrorCode =
  | "invalid_credentials"
  | "not_authenticated"
  | "account_inactive"
  | "email_already_registered"
  | "weak_password"
  | "profile_not_found"
  | "curriculum_not_loaded"
  | "validation_error"
  | "http_error"
  | "internal_error";

export interface ApiError {
  code: ApiErrorCode;
  message: string;
  details: Record<string, unknown>;
  requestId: string | null;
}
