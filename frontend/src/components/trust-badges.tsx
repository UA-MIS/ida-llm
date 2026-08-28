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

import { confidenceColorVar, confidencePips, residencyGlyph, trustGlyph } from "@/lib/trust";
import type { DataResidency, TrustTell } from "@/lib/types";

/**
 * Verifiable or AI-judged. The single most important thing on the page.
 *
 * Colour is NOT used to encode this: a green "verifiable" and an amber
 * "subjective" would read as good-vs-bad, and a subjective task is not a worse
 * task — it is a differently-evidenced one. The distinction is carried by the
 * glyph and the words, and colour is left to say something else (confidence).
 */
export function TrustBadge({ trust }: { trust: TrustTell }) {
  return (
    <span className="badge badge-trust" title={trust.headline}>
      <span aria-hidden="true">{trustGlyph(trust.kind)}</span> {trust.tier_label}
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
  const { filled, total } = confidencePips(trust.confidence);
  const color = confidenceColorVar(trust.confidence);
  return (
    <span
      className="confidence"
      title={trust.confidence_reason}
      aria-label={`${trust.confidence_label}. ${trust.confidence_reason}`}
    >
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
      <span style={{ color }}>{trust.confidence_label}</span>
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

/** Every caveat attached to a number, listed rather than summarised away. */
export function Caveats({ caveats }: { caveats: string[] }) {
  if (caveats.length === 0) return null;
  return (
    <ul className="caveats">
      {caveats.map((caveat) => (
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
      <div>
        <strong>
          <span aria-hidden="true">✓</span> Verifiable
        </strong>
        <p className="muted">
          A program compared the answer to a known correct one. No AI judged it.
        </p>
      </div>
      <div>
        <strong>
          <span aria-hidden="true">⚖</span> Subjective
        </strong>
        <p className="muted">
          No single right answer, so another language model graded it against a
          written rubric. An informed second opinion, not a measurement.
        </p>
      </div>
      <div>
        <strong>Confidence</strong>
        <p className="muted">
          About the <em>measurement</em>, never about the model: how it was
          scored, on how many samples, and whether anything failed.
        </p>
      </div>
      <div>
        <strong>
          <span aria-hidden="true">🔒</span> On campus
        </strong>
        <p className="muted">
          Runs on university hardware, so student work never leaves campus.
        </p>
      </div>
    </div>
  );
}
