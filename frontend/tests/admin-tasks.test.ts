/** Form fields ↔ task documents, for the material editor. */

import { describe, expect, it } from "vitest";

import { applyDetails, detailsOf, newTaskDocument, sampleFieldsOf, sampleFromFields, taskPath, type NewTask } from "@/lib/admin/tasks";
import type { TaskDocument } from "@/lib/admin/types";

const doc: TaskDocument = {
  version: 1,
  id: "quiz/l1-add",
  title: "Adding",
  kind: "verifiable",
  rubric: { keep: "me" },
  scorer: { kind: "numeric_match", tolerance: 0.01, normalisation: { strip: true } },
  tags: ["quiz"],
  samples: [{ id: "q1", input: "2+2?", target: "4", extra_field: "kept" }],
};

describe("task documents", () => {
  it("encodes each id segment but keeps the slash", () => {
    expect(taskPath("quiz/l1 add")).toBe("quiz/l1%20add");
  });

  it("applies form fields without dropping keys the form does not show", () => {
    const d = { ...detailsOf(doc), title: "Adding up", scorer_kind: "exact_match", tags: "quiz, ladder-l1" };
    const next = applyDetails(doc, d);
    expect(next.title).toBe("Adding up");
    expect(next.rubric).toEqual({ keep: "me" });
    expect(next.scorer).toEqual({ kind: "exact_match", normalisation: { strip: true } });
    expect(next.tags).toEqual(["quiz", "ladder-l1"]);
    expect(next.samples).toBe(doc.samples);
  });

  it("drafts a verifiable task with the family tag and a first sample", () => {
    const t: NewTask = {
      family: "quiz", name: "l2-sub", kind: "verifiable", title: "Subtracting", description: "", domain: "", system_prompt: "",
      scorer_kind: "numeric_match", tolerance: "0.5", tags: "ladder-l2", rubric_description: "", sample_id: "q1", sample_input: "5-3?", sample_target: "2",
    };
    const d = newTaskDocument(t);
    expect(d).toMatchObject({ version: 1, id: "quiz/l2-sub", kind: "verifiable", tags: ["quiz", "ladder-l2"], samples: [{ id: "q1", input: "5-3?", target: "2" }] });
    expect(d.scorer).toMatchObject({ kind: "numeric_match", tolerance: 0.5 });
    expect(d).not.toHaveProperty("rubric");
  });

  it("drafts a subjective task with a judge scorer and a one-criterion rubric", () => {
    const d = newTaskDocument({
      family: "essays", name: "l1-thesis", kind: "subjective", title: "Thesis", description: "", domain: "", system_prompt: "",
      scorer_kind: "", tolerance: "", tags: "", rubric_description: "1.0 -- states a thesis", sample_id: "e1", sample_input: "Write…", sample_target: "",
    });
    expect(d.scorer).toEqual({ kind: "llm_judge", rubric_id: "l1-thesis-v1" });
    expect(d.rubric).toMatchObject({ id: "l1-thesis-v1", criteria: [{ name: "overall", description: "1.0 -- states a thesis", weight: 1 }] });
    expect(d.samples[0]).not.toHaveProperty("target");
  });

  it("edits a sample, keeping fields the editor does not show, and catches mistakes", () => {
    const original = doc.samples[0]!;
    const f = { ...sampleFieldsOf(original), input: "2+3?", target: "5", metadata: '{"skill":"add"}' };
    expect(sampleFromFields(f, original, "verifiable").sample).toEqual({ id: "q1", input: "2+3?", target: "5", extra_field: "kept", metadata: { skill: "add" } });
    const bad = sampleFromFields({ id: "has space", input: "", target: "", metadata: "{nope" }, null, "verifiable").problems;
    expect(Object.keys(bad).sort()).toEqual(["id", "input", "metadata", "target"]);
    expect(sampleFromFields({ id: "q", input: "x", target: "", metadata: "[1]" }, null, "subjective").problems.metadata).toMatch(/object/);
  });
});
