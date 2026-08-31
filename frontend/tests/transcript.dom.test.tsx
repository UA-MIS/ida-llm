/**
 * QA-25: the transcript toggle carried its open/closed state only in the
 * glyph ("▾" vs "▸"), which a screen reader has no way to read as a state
 * change — it announced "transcript" identically either way.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Transcript } from "@/app/(site)/runs/[runId]/transcript";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the transcript toggle", () => {
  it("carries its state on aria-expanded, not just in the glyph", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ messages: [], completion: "" }) }),
    );

    render(<Transcript runId="run-1" sampleId="sample-1" />);
    const toggle = screen.getByRole("button", { name: /transcript/i });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });
});
