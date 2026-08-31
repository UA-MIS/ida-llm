/**
 * Why a model is shown but not ranked — the real reason, per model.
 *
 * ⚠ THE DEFECT THIS FILE EXISTS TO KILL. Every unranked model used to be
 * labelled "test stub", because the leaderboard read one boolean
 * (`recommendable`) that two different facts can turn off. Three models sat in
 * the drawer badged "test stubs and models nothing has scored yet" while each
 * one had 70 scored tasks and 328 samples, one of them scoring *above* the
 * model the page had just crowned. A wrong explanation attached to a higher
 * number is the exact shape of a cover-up, and this is the one site that cannot
 * afford to look like one.
 *
 * ⚠ THE TRUE REASON IS THE WORSE FACT, AND IT STILL GOES ON THE PAGE. Those
 * models are absent from the deployment's model registry, so nothing is known
 * about who runs them, where the data goes, or what they cost. That is a bigger
 * caveat than "it is a stub", not a smaller one — which is precisely why it has
 * to be the one printed.
 *
 * ⚠ DERIVED, NOT GUESSED. The API computes `recommendable = residency is not
 * not_a_real_model AND the model has a registry entry` (services/api/
 * ida_api/leaderboard.py). Residency is itself read off registry tags, so a
 * model with no entry lands on `unknown`. That makes the two arms separable
 * from the fields the frontend already has, with no new endpoint: a stub
 * announces itself through residency, and anything else unrecommendable is
 * unrecommendable because the registry has never heard of it.
 */

import type { DataResidency } from "./types";

export type ExclusionReason = "test_stub" | "not_in_registry" | "not_scored";

/** The minimum a model must expose for this file to explain it. */
export interface ExcludableModel {
  recommendable: boolean;
  data_residency: DataResidency;
  overall: { score: number | null };
}

/**
 * Why this model is not in the ranking, or `null` when it is.
 *
 * Order matters: a test stub with no score is a stub first. The provenance
 * question only arises for something we might otherwise have recommended.
 */
export function exclusionReason(model: ExcludableModel): ExclusionReason | null {
  if (!model.recommendable) {
    return model.data_residency === "not_a_real_model" ? "test_stub" : "not_in_registry";
  }
  if (model.overall.score === null) return "not_scored";
  return null;
}

/** The short form, for a badge or a row's sub-line. */
export function exclusionLabel(reason: ExclusionReason): string {
  switch (reason) {
    case "test_stub":
      return "test stub — never recommended";
    case "not_in_registry":
      return "not in the model registry";
    case "not_scored":
      return "nothing scored yet";
  }
}

/** The long form, for the tooltip behind the badge. Says what is missing, and what is not. */
export function exclusionDetail(reason: ExclusionReason): string {
  switch (reason) {
    case "test_stub":
      return (
        "A deterministic stub used to exercise the pipeline. Its numbers are real; " +
        "they are just not about a model, so it is never ranked and never recommended."
      );
    case "not_in_registry":
      return (
        "This deployment's model registry has no entry for this model, so we cannot " +
        "say who runs it, where your data would go, or what it costs. Its scores are " +
        "real measurements — what is missing is everything you would need to know " +
        "before acting on them, which is why it is not ranked."
      );
    case "not_scored":
      return "Nothing has produced a score for this model yet, so there is nothing to rank.";
  }
}

/**
 * The drawer's summary line, counted rather than assumed.
 *
 * The sentence it replaces ("test stubs and models nothing has scored yet") was
 * a guess at the contents of a list, written before the list could contain
 * anything else. This one reads the list.
 */
export function exclusionSummary(reasons: readonly (ExclusionReason | null)[]): string {
  const present = reasons.filter((reason): reason is ExclusionReason => reason !== null);
  const count = (reason: ExclusionReason) => present.filter((r) => r === reason).length;

  const parts: string[] = [];
  const stubs = count("test_stub");
  const unregistered = count("not_in_registry");
  const unscored = count("not_scored");

  if (unregistered > 0) {
    parts.push(
      `${unregistered} not in the model registry, so we cannot say where ${unregistered === 1 ? "it runs" : "they run"}`,
    );
  }
  if (stubs > 0) parts.push(`${stubs} test stub${stubs === 1 ? "" : "s"}`);
  if (unscored > 0) parts.push(`${unscored} with nothing scored yet`);

  const total = present.length;
  const head = `${total} more model${total === 1 ? "" : "s"} measured but not ranked`;
  return parts.length > 0 ? `${head} — ${joinList(parts)}. Shown, never ranked.` : `${head}. Shown, never ranked.`;
}

function joinList(parts: string[]): string {
  if (parts.length === 1) return parts[0]!;
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}
