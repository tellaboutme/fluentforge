import { describe, expect, it } from "vitest";

import {
  confidenceLabel,
  domainLabel,
  levelDisplay,
  statusLabel,
} from "./labels";

describe("levelDisplay", () => {
  it("never invents a level when the API withheld one", () => {
    expect(levelDisplay(null)).toBe("—");
  });

  it("shows the level once one is earned", () => {
    expect(levelDisplay("B1")).toBe("B1");
  });
});

describe("statusLabel", () => {
  it("reads an unobserved skill as needing evidence, not as a low level", () => {
    const label = statusLabel("unobserved");
    expect(label.short).toBe("Needs evidence");
    expect(label.short).not.toMatch(/A1|A2|beginner/i);
  });

  it("distinguishes supported from independent", () => {
    expect(statusLabel("supported").short).not.toBe(
      statusLabel("independent").short,
    );
  });

  it("falls back safely on an unknown status", () => {
    expect(statusLabel("something-new").short).toBe("Needs evidence");
  });
});

describe("confidenceLabel", () => {
  it("uses words rather than false precision", () => {
    expect(confidenceLabel(0)).toBe("No evidence yet");
    expect(confidenceLabel(0.2)).toBe("Low confidence");
    expect(confidenceLabel(0.5)).toBe("Moderate confidence");
    expect(confidenceLabel(0.9)).toBe("High confidence");
  });

  it("never renders a percentage", () => {
    for (const value of [0, 0.25, 0.5, 0.75, 1]) {
      expect(confidenceLabel(value)).not.toMatch(/%|\d/);
    }
  });
});

describe("domainLabel", () => {
  it("uses learner-facing wording", () => {
    expect(domainLabel("spoken_interaction")).toBe("Conversation");
    expect(domainLabel("written_production")).toBe("Writing");
  });

  it("degrades readably for an unmapped domain", () => {
    expect(domainLabel("some_new_domain")).toBe("some new domain");
  });
});
