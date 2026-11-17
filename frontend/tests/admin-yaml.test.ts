/**
 * The task editor's YAML emitter. Its one job is to produce text that
 * PyYAML's `safe_load` reads back as exactly the same value (verified against
 * every task file in the repo when this was written); these pin the cases
 * where a naive emitter silently changes the data.
 */

import { describe, expect, it } from "vitest";

import { toYaml } from "@/lib/admin/yaml";

describe("toYaml", () => {
  it("emits block YAML for a task-shaped document", () => {
    expect(toYaml({ version: 1, id: "quiz/l1-add", tags: ["quiz", "ladder-l1"], samples: [{ id: "q1", input: "2+2?", target: "4" }] })).toBe(
      ["version: 1", "id: quiz/l1-add", "tags:", "  - quiz", "  - ladder-l1", "samples:", "  - id: q1", '    input: "2+2?"', '    target: "4"', ""].join("\n"),
    );
  });

  it("quotes strings YAML would read as something else", () => {
    const out = toYaml({ a: "yes", b: "null", c: "123", d: "", e: "#x", f: "- x", g: "a: b", h: "on" });
    for (const line of ['a: "yes"', 'b: "null"', 'c: "123"', 'd: ""', 'e: "#x"', 'f: "- x"', 'g: "a: b"', 'h: "on"']) expect(out).toContain(line);
  });

  it("uses literal blocks with the right chomping for multi-line text", () => {
    expect(toYaml({ p: "one\ntwo" })).toBe("p: |-\n  one\n  two\n");
    expect(toYaml({ p: "one\ntwo\n" })).toBe("p: |\n  one\n  two\n");
    expect(toYaml({ p: "one\n\n" })).toBe("p: |+\n  one\n\n");
  });

  it("falls back to a quoted string when a block would not round-trip", () => {
    expect(toYaml({ p: "  lead\nx" })).toBe('p: "  lead\\nx"\n');
    expect(toYaml({ p: "trail \nx" })).toBe('p: "trail \\nx"\n');
    expect(toYaml({ p: "tab\there\nx" })).toBe('p: "tab\\there\\nx"\n');
  });

  it("writes exponent floats in a form PyYAML reads as numbers", () => {
    expect(toYaml({ big: 1e21, tiny: 1e-7, half: 0.5 })).toBe("big: 1.0e+21\ntiny: 1.0e-7\nhalf: 0.5\n");
  });

  it("handles empty containers and nested lists", () => {
    expect(toYaml({ a: [], b: {}, c: [[1, 2], { d: [] }] })).toBe("a: []\nb: {}\nc:\n  - - 1\n    - 2\n  - d: []\n");
  });
});
