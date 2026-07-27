/**
 * Learner-facing wording for model states.
 *
 * Centralised because the wording is a product commitment, not decoration: an
 * unassessed skill must read as "needs evidence" and never as a low level.
 * `docs/API_CONTRACTS.md` requires this of every client.
 */

export type SkillStatus =
  "unobserved" | "emerging" | "supported" | "independent";

interface StatusLabel {
  short: string;
  explanation: string;
}

export const STATUS_LABELS: Record<SkillStatus, StatusLabel> = {
  unobserved: {
    short: "Needs evidence",
    explanation:
      "You have not practised this yet, so there is nothing to show.",
  },
  emerging: {
    short: "Emerging",
    explanation:
      "Some evidence so far. More practice in different situations will confirm it.",
  },
  supported: {
    short: "Supported",
    explanation: "You have shown this across several different tasks.",
  },
  independent: {
    short: "Independent",
    explanation:
      "Shown confidently and repeatedly, in several different situations.",
  },
};

export function statusLabel(status: string): StatusLabel {
  return (
    STATUS_LABELS[status as SkillStatus] ?? {
      short: "Needs evidence",
      explanation: "Not enough information yet.",
    }
  );
}

/**
 * What to display in the level slot.
 *
 * Returns a dash, never an invented level, when the API withheld an estimate.
 */
export function levelDisplay(cefrEstimate: string | null): string {
  return cefrEstimate ?? "—";
}

export const DOMAIN_LABELS: Record<string, string> = {
  listening: "Listening",
  spoken_production: "Speaking",
  spoken_interaction: "Conversation",
  pronunciation: "Pronunciation",
  reading: "Reading",
  written_production: "Writing",
  written_interaction: "Messages and email",
  vocabulary: "Vocabulary",
  grammar: "Grammar",
  fluency: "Fluency",
  discourse: "Structure and cohesion",
  pragmatics: "Register and tone",
  mediation: "Explaining and summarising",
  learning_strategies: "Learning strategies",
};

export function domainLabel(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain.replace(/_/g, " ");
}

/** What kind of work a plan item is, in words a learner recognises. */
export const KIND_LABELS: Record<string, string> = {
  review: "Review",
  input: "Read or listen",
  study: "Focused practice",
  output: "Write",
  speaking: "Speak",
  reflection: "Reflect",
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

/**
 * What a review card is asking for.
 *
 * Recognising a word and producing it are different memories, scheduled
 * separately, so the learner has to know which one is being tested.
 */
export const REVIEW_MODE_LABELS: Record<string, string> = {
  meaning_recognition: "Do you know what this means?",
  form_recognition: "Do you recognise this form?",
  listening_recognition: "Would you catch this when spoken?",
  meaning_recall: "Say the meaning from memory",
  form_recall: "Produce the exact wording from memory",
  pronunciation_production: "Say it aloud",
  contextual_production: "Use it in a sentence of your own",
};

export function reviewModeLabel(mode: string): string {
  return REVIEW_MODE_LABELS[mode] ?? "Recall this";
}

/** What a comprehension question is testing. */
export const QUESTION_TYPE_LABELS: Record<string, string> = {
  gist: "Main idea",
  detail: "Detail",
  inference: "Reading between the lines",
};

export function questionTypeLabel(questionType: string): string {
  return QUESTION_TYPE_LABELS[questionType] ?? questionType;
}

/** Confidence as plain words. Percentages imply precision we do not have. */
export function confidenceLabel(confidence: number): string {
  if (confidence <= 0) return "No evidence yet";
  if (confidence < 0.35) return "Low confidence";
  if (confidence < 0.75) return "Moderate confidence";
  return "High confidence";
}
