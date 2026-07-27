# Database Schema

## Identity and preferences

### users

- id UUID
- email / local identity fields
- created_at, updated_at
- status

### learner_profiles

- user_id
- display_name
- explanation_language
- timezone
- daily_minutes
- goals JSONB
- interests JSONB
- accessibility_preferences JSONB
- privacy_preferences JSONB

## Curriculum

### curriculum_versions

- id
- semantic_version
- status: draft/published/retired
- source_hash
- published_at

### skill_nodes

- id stable string
- curriculum_version_id
- domain
- subdomain
- title
- description
- cefr_min, cefr_max
- difficulty
- metadata JSONB

### skill_edges

- from_skill_id
- to_skill_id
- relation: prerequisite/supports/confusable/transfer
- weight

### learning_objectives

- id
- skill_node_id
- can_do
- evidence_requirements JSONB

## Content

### content_items

- id
- owner_id nullable
- source_type
- source_metadata JSONB
- license
- language
- title
- clean_text
- storage_key
- status
- content_version

### activities

- id
- curriculum_version_id
- content_item_id nullable
- activity_type
- target_skill_ids
- cefr_target
- instructions
- payload JSONB
- answer_key JSONB nullable
- rubric_id nullable
- generation_metadata JSONB
- status

## Learning records

### learning_sessions

- id
- user_id
- plan_id nullable
- started_at, ended_at
- context JSONB

### attempts

- id
- user_id
- session_id
- activity_id
- attempt_number
- response JSONB
- started_at, submitted_at
- duration_ms
- hints_used
- scaffolding_level
- evaluator_id nullable

### evidence_events

- id
- user_id
- skill_node_id
- attempt_id
- evidence_type
- score 0..1
- weight
- difficulty
- confidence
- independence
- novelty
- occurred_at
- metadata JSONB

### skill_states

- user_id
- skill_node_id
- mastery_probability
- confidence
- stability
- last_observed_at
- evidence_count
- model_version

### error_patterns

- id
- user_id
- taxonomy_code
- canonical_description
- first_seen_at, last_seen_at
- occurrence_count
- current_priority
- status
- examples JSONB

## Vocabulary memory

### lexical_entries

- id
- lemma
- part_of_speech
- sense_key
- cefr_estimate
- frequency_band
- forms JSONB
- pronunciations JSONB
- usage JSONB

### learner_lexical_states

- user_id
- lexical_entry_id
- recognition_state JSONB
- recall_state JSONB
- listening_state JSONB
- production_state JSONB
- next_review_at

### learner_phrases

Same concept as lexical entries but stores multiword units, collocations, frames, phrasal verbs, and idioms.

## Planning and reviews

### plans

- id
- user_id
- date
- requested_minutes
- rationale JSONB
- engine_version
- status

### plan_items

- plan_id
- sequence
- activity_id
- estimated_minutes
- reason_codes JSONB

### review_queue

- id
- user_id
- memory_object_type
- memory_object_id
- review_mode
- due_at
- stability
- difficulty
- scheduler_version

## Evaluation and prompts

### prompt_versions

- id
- prompt_key
- semantic_version
- template
- schema JSONB
- status

### evaluator_runs

- id
- evaluator_type
- prompt_version_id
- provider
- model
- input_hash
- output JSONB
- latency_ms
- cost_metadata JSONB
- confidence
- status

## Privacy

Raw recordings should use separate objects and retention metadata. Deletion must remove object storage content and identifying links while preserving only properly anonymised aggregate statistics when allowed.
