/**
 * Is this request the DEV demonstration preview?
 *
 * ⚠ THE ONE SIGNAL, AND IT IS A PROPERTY OF THE DEPLOYMENT, NOT OF A ROW. The
 * `demonstration` flag on a result stays exactly where it was — per row, in the
 * data, self-clearing the moment a real run replaces a seeded one (see
 * `is_demonstration` in the API and `summariseDemonstration` here). This asks a
 * different question: "are we the dev preview, where everyone already knows the
 * grid is filled with illustrative data, so the per-row/column/banner tells are
 * just noise?" — and it answers it from the SAME gate that loads the demo
 * curriculum in the first place.
 *
 * `IDA_DEMO_CURRICULUM=1` is set by exactly one place: the dev overlay
 * (`.devops/chart/overlays/dev/kustomization.yaml`). Staging and prod never set
 * it, so this is `false` there — which is the whole prod-safety contract:
 *
 *   • In the DEV preview the demo curriculum is loaded AND the visual tells are
 *     suppressed, so the grid reads clean, the way it will once real data fills
 *     it. The data still carries every `demonstration` flag.
 *   • ANYWHERE ELSE (prod, staging, a plain `getLeaderboard()` with no gate) a
 *     seeded row is a prod-reachable surprise and MUST still disclose. This
 *     returns `false`, so every badge and banner renders exactly as before.
 *
 * So the ONLY data exempt from a visual tell is the data that is provably
 * dev-only: it rides in behind the same flag that gates the demo curriculum, and
 * it cannot reach prod without that flag, which prod does not set.
 *
 * Read at call time, in a try/catch, because this runs during SSR where
 * `process.env` exists but must never throw if it does not. `tests/
 * demonstration-guard.dom.test.tsx` pins both directions: discloses with the
 * flag off, clean with it on.
 */
export function isDevDemoPreview(): boolean {
  try {
    return process.env.IDA_DEMO_CURRICULUM === "1";
  } catch {
    return false;
  }
}
