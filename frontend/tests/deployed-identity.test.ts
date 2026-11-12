/**
 * "What is deployed?" — and specifically the branches where it cannot be known.
 *
 * On the GB10 appliance the images are built on the box from the reconciled
 * commit rather than pulled as promoted Harbor digests, which loses the
 * registry's answer to "what is running". `/api/version` replaces it, so the
 * property under test is that it never ANSWERS CONFIDENTLY WHEN IT CANNOT TELL:
 * an unreachable api must read as unknown, not as agreement and not as
 * disagreement. A deploy-provenance endpoint that guesses is worse than none.
 */

import { describe, expect, it } from "vitest";

import { buildDeployedIdentity, resolveVersion } from "@/lib/version";

const identified = resolveVersion("9b6ca79abc12", "0.1.0");
const unidentified = resolveVersion(undefined, "0.1.0");

describe("buildDeployedIdentity", () => {
  it("reports both halves and agreement when the api echoes the same commit", () => {
    const d = buildDeployedIdentity(identified, {
      version: "1.0.1",
      git_sha: "9b6ca79abc12def4567890abcdef1234567890ab",
    });
    expect(d.frontend.label).toBe("9b6ca79abc12");
    expect(d.api.reachable).toBe(true);
    expect(d.api.version).toBe("1.0.1");
    expect(d.api.gitSha).toBe("9b6ca79abc12def4567890abcdef1234567890ab");
    expect(d.consistent).toBe(true);
  });

  it("flags a MISMATCH — the half-applied deploy this endpoint exists to catch", () => {
    // The reconciler builds and tags both images from one commit, so the
    // interesting failure is a rollback (or a failed build) moving one and not
    // the other.
    const d = buildDeployedIdentity(identified, {
      version: "1.0.1",
      git_sha: "ffffffffffffdeadbeef0000000000000000beef",
    });
    expect(d.consistent).toBe(false);
  });

  it("says UNKNOWN, not false, when the api is unreachable", () => {
    const d = buildDeployedIdentity(identified, null, "fetch failed");
    expect(d.api.reachable).toBe(false);
    expect(d.api.error).toBe("fetch failed");
    // The whole point: absence of evidence must not render as a mismatch.
    expect(d.consistent).toBeNull();
    // ...and the half that IS knowable is still reported, because an api outage
    // is exactly when someone asks what is deployed.
    expect(d.frontend.label).toBe("9b6ca79abc12");
  });

  it("still answers when the api responds but omits git_sha", () => {
    const d = buildDeployedIdentity(identified, { version: "1.0.1" });
    expect(d.api.reachable).toBe(true);
    expect(d.api.gitSha).toBeNull();
    expect(d.consistent).toBeNull();
  });

  it("says UNKNOWN when the frontend build cannot name itself", () => {
    // An unidentified frontend build (no IDA_VERSION build-arg) has a `-dev`
    // label that is not a SHA prefix, so comparing it would manufacture a
    // mismatch out of a missing build-arg.
    const d = buildDeployedIdentity(unidentified, {
      version: "1.0.1",
      git_sha: "9b6ca79abc12def4567890abcdef1234567890ab",
    });
    expect(d.frontend.identified).toBe(false);
    expect(d.consistent).toBeNull();
  });

  it("ignores non-string junk from the api rather than propagating it", () => {
    const d = buildDeployedIdentity(identified, { version: 17, git_sha: { nope: true } } as never);
    expect(d.api.reachable).toBe(true);
    expect(d.api.version).toBeUndefined();
    expect(d.api.gitSha).toBeNull();
    expect(d.consistent).toBeNull();
  });

  it("never reports agreement from an empty api body", () => {
    const d = buildDeployedIdentity(identified, {});
    expect(d.consistent).toBeNull();
  });
});
