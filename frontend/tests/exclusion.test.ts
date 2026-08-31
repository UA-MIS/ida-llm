/**
 * Why a model is not ranked — and why the answer must be per-model.
 *
 * Three models were shown badged "test stub" while each carried 70 scored
 * tasks and 328 samples, one of them scoring above the model the page had just
 * crowned. The true reason — absent from the model registry, so nothing is
 * known about who runs them — is a worse fact than the one displayed, which is
 * exactly why it has to be the one displayed.
 */

import { describe, expect, it } from "vitest";

import {
  exclusionDetail,
  exclusionLabel,
  exclusionReason,
  exclusionSummary,
  type ExcludableModel,
} from "@/lib/exclusion";

function model(overrides: Partial<ExcludableModel> = {}): ExcludableModel {
  return {
    recommendable: true,
    data_residency: "third_party",
    overall: { score: 0.88 },
    ...overrides,
  };
}

describe("exclusionReason", () => {
  it("calls a genuine stub a stub", () => {
    // `mock` — tagged in the registry, residency `not_a_real_model`.
    expect(
      exclusionReason(model({ recommendable: false, data_residency: "not_a_real_model" })),
    ).toBe("test_stub");
  });

  it("does NOT call an unregistered model a stub", () => {
    // `demo-orion` — 328 scored samples, not in models.yaml, residency
    // `unknown`. The whole defect, in one assertion.
    expect(
      exclusionReason(model({ recommendable: false, data_residency: "unknown" })),
    ).toBe("not_in_registry");
  });

  it("separates a registered model with nothing scored from both", () => {
    expect(exclusionReason(model({ overall: { score: null } }))).toBe("not_scored");
  });

  it("returns null for a model that is ranked", () => {
    expect(exclusionReason(model())).toBeNull();
  });
});

describe("exclusionLabel / exclusionDetail", () => {
  it("never describes an unregistered model as a stub", () => {
    expect(exclusionLabel("not_in_registry")).not.toMatch(/stub/i);
    expect(exclusionDetail("not_in_registry")).not.toMatch(/stub/i);
  });

  it("says what is missing rather than implying the numbers are fake", () => {
    // The scores ARE real measurements; the provenance is what is absent.
    const detail = exclusionDetail("not_in_registry");
    expect(detail).toMatch(/real measurements/i);
    expect(detail).toMatch(/registry/i);
  });
});

describe("exclusionSummary", () => {
  it("describes the live drawer honestly: three unregistered, one stub", () => {
    const summary = exclusionSummary([
      "not_in_registry",
      "not_in_registry",
      "not_in_registry",
      "test_stub",
    ]);
    expect(summary).toContain("4 more models");
    expect(summary).toContain("3 not in the model registry");
    expect(summary).toContain("1 test stub");
  });

  it("does not claim a stub when the drawer holds none", () => {
    const summary = exclusionSummary(["not_in_registry"]);
    expect(summary).not.toMatch(/stub/i);
  });

  it("does not claim 'nothing scored' when everything in it was scored", () => {
    // The sentence it replaced said this of models with 328 samples each.
    const summary = exclusionSummary(["not_in_registry", "test_stub"]);
    expect(summary).not.toMatch(/nothing has scored|nothing scored/i);
  });

  it("counts only real exclusions", () => {
    expect(exclusionSummary([null, null, "test_stub"])).toContain("1 more model ");
  });
});
