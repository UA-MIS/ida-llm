/**
 * The trust tell, drawn.
 *
 * The differentiator of this whole project is that a number here comes with an
 * honest statement of what kind of evidence it is. A badge that only said
 * "subjective" would tell a professor a fact about our taxonomy; these say what
 * to *do* with the number, and every one of them is one hover from the
 * reasoning behind it.
 *
 * Server components — no client JS. The tooltips are native `title` attributes
 * on purpose: they work before hydration, they work for keyboard users, and a
 * results page should not need a bundle to explain itself.
 */

import { plainTaskKind } from "@/lib/glossary";
import { plainCaveats, plainLanguage } from "@/lib/plain";
import { confidenceColorVar, confidencePips, residencyGlyph, trustGlyph } from "@/lib/trust";
import type { Confidence, DataResidency, TrustTell } from "@/lib/types";

/**
 * Verifiable or AI-judged. The single most important thing on the page.
 *
 * Colour is NOT used to encode this: a green "verifiable" and an amber
 * "subjective" would read as good-vs-bad, and a subjective task is not a worse
 * task — it is a differently-evidenced one. The distinction is carried by the
 * glyph and the words, and colour is left to say something else (confidence).
 *
 * ⚠ THE WORDS COME FROM `plainTaskKind`, NOT FROM `trust.tier_label`. The API's
 * label is "Subjective (AI-scored)", and `lib/glossary.ts` exists in part to
 * keep that exact word off the page: "subjective" reads as "this result is a
 * matter of opinion" when what it means is "this work has no single right
 * answer, so a second AI marked it". The word was carefully removed from the
 * product and then let straight back in here, by the one component that renders
 * on almost every row. The glossary owns both strings; this renders the one it
 * chose.
 */
export function TrustBadge({ trust }: { trust: TrustTell }) {
  return (
    <span className="badge badge-trust" title={trust.headline}>
      <span aria-hidden="true">{trustGlyph(trust.kind)}</span> {plainTaskKind(trust.kind)}
    </span>
  );
}

/**
 * How sure we are about *this measurement* — pips plus a word.
 *
 * Pips because "moderate" alone reads as an opinion, while one filled pip of
 * three reads as a position on a scale, which is what lets a reader compare two
 * numbers correctly.
 */
export function ConfidenceMeter({ trust }: { trust: TrustTell }) {
  return (
    <ConfidenceTell
      confidence={trust.confidence}
      label={trust.confidence_label}
      reason={plainLanguage(trust.confidence_reason)}
    />
  );
}

/**
 * The same meter, from a bare tier.
 *
 * An AGGREGATE confidence has no `TrustTell` behind it — it is the weakest tier
 * among several measurements (see `lib/rollup.ts`), and there is no single
 * server-computed sentence to quote. Drawing it with the identical pips is the
 * point: a reader must not have to learn two scales, one for a task row and one
 * for a model's overall standing.
 */
export function ConfidenceTell({
  confidence,
  label,
  reason,
}: {
  confidence: Confidence;
  label: string;
  reason: string;
}) {
  const { filled, total } = confidencePips(confidence);
  const color = confidenceColorVar(confidence);
  return (
    // ⚠ `role="img"`, NOT A BARE SPAN. QA-24: an unstyled `<span>` is
    // `role="generic"` in the accessibility tree, and `role="generic"`
    // PROHIBITS an author-supplied name — conforming assistive technology is
    // required to drop `aria-label` here and fall back to nothing, since the
    // pips carry no text of their own (`score-bar.tsx`'s `.scorebar-track`
    // already gets this right the same way).
    <span className="confidence" title={reason} role="img" aria-label={`${label}. ${reason}`}>
      <span className="confidence-pips" aria-hidden="true">
        {Array.from({ length: total }, (_, index) => (
          <span
            key={index}
            className="pip"
            style={{
              background: index < filled ? color : "transparent",
              borderColor: color,
            }}
          />
        ))}
      </span>
      <span style={{ color }}>{label}</span>
    </span>
  );
}

/**
 * Where the data goes. The FERPA move, surfaced as a property of the model.
 *
 * Read off the registry's tags rather than typed into this page, so standing up
 * the campus deployment makes the lock appear with no frontend change.
 */
export function ResidencyBadge({
  residency,
  label,
}: {
  residency: DataResidency;
  label: string;
}) {
  const title =
    residency === "on_campus"
      ? "Runs on university hardware. Nothing you send reaches a third party — this is what makes it usable with student work."
      : residency === "third_party"
        ? "Hosted by an outside vendor. Anything you send leaves the university."
        : residency === "not_a_real_model"
          ? "A deterministic stub used to test the pipeline. It is shown because it is real data, and it is never recommended."
          : "The registry does not say where this model is hosted.";
  return (
    <span className={`badge badge-residency badge-residency-${residency}`} title={title}>
      <span aria-hidden="true">{residencyGlyph(residency)}</span> {label}
    </span>
  );
}

/**
 * Every caveat attached to a number, listed rather than summarised away.
 *
 * ⚠ EVERY STRING GOES THROUGH `plainCaveats` FIRST. These arrive from the API,
 * which writes them for two readers at once, and the operator half was reaching
 * the page: an environment variable name and a filename rendered verbatim on
 * hundreds of professor-facing result cards. See `lib/plain.ts` — the
 * translation belongs at the render boundary so no caller can forget it.
 */
export function Caveats({ caveats }: { caveats: string[] }) {
  const plain = plainCaveats(caveats);
  if (plain.length === 0) return null;
  return (
    <ul className="caveats">
      {plain.map((caveat) => (
        <li key={caveat}>{caveat}</li>
      ))}
    </ul>
  );
}

/**
 * The standing legend.
 *
 * Always visible rather than on-demand: the sprint planning session left "how
 * prominent is the credibility layer?" open, and for a first-time skeptical
 * reader the answer has to be "you cannot miss it". It costs one strip of the
 * page and it is the strip that earns the rest of it.
 */
export function TrustLegend() {
  return (
    <div className="legend">
      {/* ⚠ THE HEADINGS ARE THE BADGES' OWN WORDS, NOT OUR TAXONOMY. These
          read "Verifiable" and "Subjective" — the two raw `TaskKind` values
          that `plainTaskKind` exists to keep off the page, and that this file's
          own `TrustBadge` comment above spends a paragraph explaining we do not
          print. Neither word appears on a single badge, so the standing legend
          was a key to a vocabulary the product had already removed. */}
      <div>
        <strong>
          <span aria-hidden="true">✓</span> Checked by a program
        </strong>
        <p className="muted">
          The work had one right answer, and a program compared what the model
          said to it. No AI judged it — the strongest evidence here.
        </p>
      </div>
      <div>
        <strong>
          <span aria-hidden="true">⚖</span> Marked by another AI
        </strong>
        <p className="muted">
          No single right answer, so a second AI marked it against a written
          guide. An informed second opinion, not a measurement, and never
          labelled high confidence.
        </p>
      </div>
      <div>
        <strong>Confidence</strong>
        <p className="muted">
          About the <em>measurement</em>, never about the model: how it was
          marked, over how many attempts, and whether anything failed. A high
          score with low confidence is not yet a verdict.
        </p>
      </div>
      <div>
        <strong>
          <span aria-hidden="true">🔒</span> On campus
        </strong>
        <p className="muted">
          Runs on university hardware, so student work never leaves campus.
          Anything else sends what you type to an outside company.
        </p>
      </div>
    </div>
  );
}
