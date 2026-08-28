/**
 * The version badge — and specifically its FALLBACK.
 *
 * The header used to print a hardcoded `v0.1.4`. Replacing it with a build-arg
 * chain is only an improvement if the chain fails visibly: an inlined
 * `NEXT_PUBLIC_APP_VERSION` that silently resolves to `""` renders a blank badge
 * and is harder to notice than the wrong constant it replaced.
 */

import { describe, expect, it } from "vitest";

import { resolveVersion } from "@/lib/version";

describe("resolveVersion", () => {
  it("prints the injected build tag when the build-arg was passed", () => {
    const v = resolveVersion("v0.1.1-3-gabc1234", "0.1.0");
    expect(v.label).toBe("v0.1.1-3-gabc1234");
    expect(v.identified).toBe(true);
    expect(v.detail).toContain("IDA_VERSION");
  });

  it("is NEVER empty when the build-arg is missing", () => {
    for (const missing of [undefined, "", "   "]) {
      const v = resolveVersion(missing, "0.1.0");
      expect(v.label).not.toBe("");
      expect(v.label.trim()).toBe(v.label);
      expect(v.identified).toBe(false);
    }
  });

  it("marks the fallback as not-a-release, so it cannot be read as one", () => {
    const v = resolveVersion(undefined, "0.1.0");
    expect(v.label).toBe("0.1.0-dev");
    // The exact regression the platform's provenance suite pins by value: an
    // image answering with a bare release-shaped literal it never earned.
    expect(v.label).not.toBe("0.1.0");
    expect(v.detail).toContain("without the IDA_VERSION build-arg");
  });

  it("trims a padded build-arg rather than rendering the padding", () => {
    expect(resolveVersion("  0.1.2  ", "0.1.0").label).toBe("0.1.2");
  });
});
