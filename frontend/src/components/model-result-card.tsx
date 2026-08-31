/**
 * One model's standing on one task — the row a professor actually reads.
 *
 * Every element here answers a question the sprint-planning session raised:
 * what is the number, what kind of evidence is it, how sure are we, where does
 * the data go, and — one click away, always — *why*.
 */

import Link from "next/link";

import { Caveats, ConfidenceMeter, ResidencyBadge, TrustBadge } from "@/components/trust-badges";
import { formatScore, formatTimestamp } from "@/lib/format";
import { plainLanguage } from "@/lib/plain";
import { isDeEmphasised } from "@/lib/trust";
import type { ModelResult } from "@/lib/types";

/**
 * The score, or an honest sentence instead of one.
 *
 * ⚠ NEVER renders a null as `0.00`. A model with no score has not failed; it
 * has not been measured, or its samples errored, or the task cannot be graded
 * yet — three different facts, and `trust.confidence_reason` says which.
 */
function Score({ result }: { result: ModelResult }) {
  if (result.mean_score === null) {
    return (
      <div className="score-block">
        <div className="score-value muted">—</div>
        <div className="muted score-sub">{result.trust.confidence_label}</div>
      </div>
    );
  }
  return (
    <div className="score-block">
      <div className="score-value">{formatScore(result.mean_score)}</div>
      <div className="muted score-sub">
        {result.scored_count}/{result.sample_count} samples
      </div>
    </div>
  );
}

export function ModelResultCard({
  result,
  rank,
  isBest,
}: {
  result: ModelResult;
  rank: number;
  isBest: boolean;
}) {
  return (
    <li className={`result-card${isDeEmphasised(result) ? " result-card-muted" : ""}`}>
      <div className="result-head">
        <div className="result-identity">
          <div className="result-name">
            {isBest ? (
              <span className="star" title="Best measured score on this task">
                ★
              </span>
            ) : (
              <span className="rank muted">{rank}</span>
            )}
            <strong>{result.display_name}</strong>
            <span className="mono muted"> {result.model_key}</span>
          </div>
          <div className="result-badges">
            <TrustBadge trust={result.trust} />
            <ConfidenceMeter trust={result.trust} />
            <ResidencyBadge
              residency={result.data_residency}
              label={result.data_residency_label}
            />
            {!result.enabled ? (
              <span
                className="badge"
                title="This measurement stands — it happened — but the registry has since disabled the model, so it cannot be run today."
              >
                not currently runnable
              </span>
            ) : null}
          </div>
        </div>
        <Score result={result} />
      </div>

      {/* Same boundary as `Caveats`: the API writes this sentence for an
          operator as well as for a reader, so it is translated on the way in.
          See `lib/plain.ts`. */}
      <p className="muted result-reason">{plainLanguage(result.trust.confidence_reason)}</p>
      <Caveats caveats={result.trust.caveats} />

      {/* D-3, made concrete: the evidence is one click from the number, always. */}
      <div className="result-foot">
        <Link href={`/runs/${result.run_id}`}>
          See the proof ▸
        </Link>
        <span className="muted">
          what we asked, what it answered, and how it was marked
        </span>
        <span className="muted" style={{ marginLeft: "auto" }}>
          measured {formatTimestamp(result.measured_at)}
        </span>
      </div>
    </li>
  );
}
