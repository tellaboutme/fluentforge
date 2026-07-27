# ADR 0001: Use a skill graph instead of a linear course

## Status

Accepted

## Context

Language skills develop unevenly. Linear course progress cannot represent prerequisites, confusable concepts, transfer, or skill-specific evidence.

## Decision

Model curriculum as versioned skill nodes connected by prerequisite, support, confusable, and transfer edges. Plans select activities from current states and graph relationships.

## Consequences

- More complex authoring and validation.
- Better diagnostics and explanations.
- Historical versions must remain reproducible.
