/**
 * What build is this? — the other half of a two-file wiring.
 *
 * ⚠ THE BUG THIS REPLACES. The header rendered a hardcoded `v0.1.4` that no
 * release step ever wrote to. It was wrong the moment it was typed and it got
 * wronger with every deploy: a version string that cannot change is a version
 * string that lies, and it is exactly the failure `.devops/ci/build-provenance
 * .test.sh` was written for after `/healthz` on the 0.1.1 image answered
 * "0.1.0".
 *
 * ⚠ AND THE BUG THE OBVIOUS FIX INTRODUCES. `NEXT_PUBLIC_APP_VERSION` is
 * inlined at BUILD time, so if `frontend/Dockerfile` ever stops receiving
 * `--build-arg=IDA_VERSION`, the substitution silently yields `""` — a header
 * with an empty badge, or worse a `v` on its own, which reads as a rendering
 * glitch rather than as a broken build. A chain that fails to nothing is worse
 * than the constant it replaced, because nobody can see it fail.
 *
 * So the fallback is EXPLICIT and it is LABELLED. An image built without the
 * build-arg reports the package version with a `-dev` suffix and a tooltip
 * saying why — non-empty, obviously not a release, and impossible to mistake
 * for the tag an environment is pinned to.
 *
 * The value itself is the resolved image TAG (`v0.1.1-3-gabc1234` off main,
 * `0.1.2` off a release tag) — the SAME string the overlays pin as `newTag`,
 * which is what makes "what does the header say" and "what does the overlay
 * say" directly comparable. See `.devops/ci/build-provenance.test.sh`.
 */

import pkg from "../../package.json";

/**
 * Inlined by Next at build time from the Docker build-arg. Read as a whole
 * `process.env.X` expression on purpose — destructuring or dynamic indexing
 * defeats the static replacement and always yields undefined in the browser.
 */
const INJECTED = process.env.NEXT_PUBLIC_APP_VERSION;

export interface BuildVersion {
  /** What the badge prints. Never empty. */
  label: string;
  /** The `title` explaining where that string came from. */
  detail: string;
  /** False when the build-arg was missing and we fell back. */
  identified: boolean;
}

/**
 * Resolve the badge text.
 *
 * Exported with its inputs as parameters so the fallback path is testable
 * without rebuilding the app with a different environment — the untested half
 * of a fallback is the half that ships broken.
 */
export function resolveVersion(
  injected: string | undefined = INJECTED,
  packageVersion: string = pkg.version,
): BuildVersion {
  const tag = (injected ?? "").trim();
  if (tag) {
    return {
      label: tag,
      identified: true,
      detail: `Build ${tag} — the image tag this frontend was built at, baked in by the Docker build-arg IDA_VERSION. The same string the environment's overlay pins as newTag.`,
    };
  }
  return {
    label: `${packageVersion}-dev`,
    identified: false,
    detail:
      `Unidentified build. This image was built without the IDA_VERSION build-arg, so it cannot name its release; ` +
      `shown is frontend/package.json's version (${packageVersion}) with a -dev suffix, which is deliberately not a release string.`,
  };
}
