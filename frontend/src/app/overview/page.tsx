/**
 * The candidate front door: what we found, and what it costs you.
 *
 * ⚠ THIS IS NOT A RESKIN OF THE LEADERBOARD, AND IT IS NOT A SECOND LANDING
 * PAGE. `/` argues that the question is worth asking — it is a page of reasons,
 * with a single measured number on it. `/leaderboard` answers the question in
 * full, for a reader who already believes the method. Between the two there was
 * nothing for the visitor who believes us enough to keep reading but will not
 * work through a table: someone who wants to know, in about fifteen seconds,
 * *which of these is actually good, and can I afford it*.
 *
 * That reader is most of the audience. They are faculty and students at one
 * university, many of them not technical, and they arrived from a link in an
 * email. This page is for them.
 *
 * ⚠ COST IS A FIRST-CLASS AXIS HERE, WHICH IT IS NOWHERE ELSE IN THE PRODUCT.
 * "Which is best" is only half of a decision a professor can act on; the other
 * half is whether it is a few dollars a semester or a line item they have to
 * defend to a department head. The prices come from `lib/value.ts`, which reads
 * the provider's published rate card — NOT our own measurement spend, which is
 * zero on seeded data and would render every model as free. That distinction is
 * the single most load-bearing thing on this page and it is documented at
 * length where it is implemented.
 *
 * ⚠ EVERY CLAIM IS EARNED IN `lib/overview.ts` AND `lib/value.ts`, NOT HERE.
 * This file renders whatever those return and has no way to write a finding of
 * its own — the same arrangement `/` has with `lib/specimen.ts`, for the same
 * reason. In particular this page CANNOT crown a universal "#1": the strength
 * label is scoped by the module that produces it, and the "your field may
 * differ" nudge is a required field on the result rather than a paragraph
 * someone might delete.
 *
 * ⚠ IT IS A CANDIDATE, NOT A REPLACEMENT. `/` is untouched. This ships on its
 * own route so the two can be reviewed side by side before either becomes the
 * front door.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { ConfidenceTell } from "@/components/trust-badges";
import { getLeaderboard } from "@/lib/api";
import { formatScoreValue } from "@/lib/format";
import { buildOverview, type Overview, type Standout } from "@/lib/overview";
import { formatQuote, type PriceReading } from "@/lib/value";

/** The reading reflects whatever has finished running, so never cache this. */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Which AI is worth it — and what it costs — Capstone-IDA",
  description:
    "A plain-language read on which AI models actually do academic work well, what each one costs to run, and how much of that we have genuinely measured.",
};

/* ------------------------------------------------------------------------ */
/* Small presentational pieces                                              */
/* ------------------------------------------------------------------------ */

function Arrow({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.1"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 12h13M13 6l6 6-6 6" />
    </svg>
  );
}

/**
 * The price, as a figure a person can picture.
 *
 * ⚠ FOUR RENDERINGS, AND NONE OF THEM IS "$0.00" BY ACCIDENT. A campus model
 * costing nothing and a model whose price we do not know must not look the
 * same: the first is a genuine advantage and the second is a gap in what we
 * know. `lib/value.ts` keeps them apart; this only has to not collapse them.
 */
function Price({ price }: { price: PriceReading }) {
  if (price.kind === "free_on_campus") {
    return (
      <div className="ov-price ov-price-free">
        <span className="ov-price-figure">Free</span>
        <span className="ov-price-unit">to you — runs on campus hardware</span>
      </div>
    );
  }
  if (price.kind === "priced") {
    return (
      <div className="ov-price">
        <span className="ov-price-figure">{formatQuote(price.usdPerHundredAnswers)}</span>
        <span className="ov-price-unit">
          per 100 answers, at the length we measured
        </span>
      </div>
    );
  }
  // Both remaining cases are absences, and they say so rather than showing a
  // zero. A zero here would be read as "free", which is the opposite claim.
  return (
    <div className="ov-price ov-price-unknown">
      <span className="ov-price-figure">Not priced</span>
      <span className="ov-price-unit">
        {price.kind === "priced_unsized"
          ? "this model bills per use, but we have not run it enough to say how much"
          : "no published rate for this model"}
      </span>
    </div>
  );
}

/**
 * One standout.
 *
 * ⚠ THE SCORE AND ITS CONFIDENCE ARE SIBLINGS IN ONE BLOCK, DELIBERATELY. This
 * product's rule is that a number never travels without the statement of what
 * it is worth, and the way that rule has broken before was a stylesheet hiding
 * the qualifier at a narrow width. `.ov-confidence` is never inside anything a
 * breakpoint drops — see `tests/breakpoints.test.ts`.
 */
function StandoutCard({ standout }: { standout: Standout }) {
  return (
    <article className={`ov-card ov-card-${standout.role}`}>
      <p className="ov-role">{standout.roleLabel}</p>
      <h3 className="ov-name">{standout.display_name}</h3>

      <div className="ov-figures">
        <div className="ov-score">
          <span className="ov-score-figure">{formatScoreValue(standout.score)}</span>
          <span className="ov-score-unit">out of 1.00 overall</span>
          <span className="ov-confidence">
            <ConfidenceTell
              confidence={standout.confidence}
              label={standout.confidenceLabel}
              reason={standout.confidenceReason}
            />
          </span>
        </div>
        <Price price={standout.price} />
      </div>

      <p className="ov-reading">{standout.reading}</p>

      {standout.demonstration ? (
        <p className="ov-card-demo">
          Illustrative — these figures were generated to show the shape of the
          finished benchmark. This model has not actually been measured here yet.
        </p>
      ) : null}

      <Link className="ov-card-link" href={standout.reportHref}>
        See {standout.display_name}&rsquo;s full report card
        <Arrow className="ov-arrow" />
      </Link>
    </article>
  );
}

/**
 * The trade-off, drawn.
 *
 * One row per ranked model: how well it did, and what it costs. It is the same
 * arithmetic as the cards above, laid out so the shape of the field is visible
 * at a glance — which is the thing a list of three cards cannot show.
 *
 * ⚠ THE BAR IS CAPABILITY, NOT VALUE. A "value" bar would be a ratio with a
 * zero denominator for every campus model, and it would encode a weighting of
 * quality against money that is the READER's to make, not ours. Two honest
 * columns beat one invented index.
 */
function TradeOff({ overview }: { overview: Overview }) {
  const rows = overview.value.readings;
  if (rows.length < 2) return null;

  return (
    <div className="ov-tradeoff">
      <div className="ov-tradeoff-head" aria-hidden="true">
        <span>Model</span>
        <span>How well it did</span>
        <span>What it costs you</span>
      </div>
      <ul className="ov-tradeoff-rows">
        {rows.map((row) => (
          <li key={row.model_key} className="ov-tradeoff-row">
            <span className="ov-tradeoff-name">{row.display_name}</span>
            <span className="ov-tradeoff-bar">
              {/* Width is the score. `aria-hidden` because the figure and the
                  confidence beside it already carry the claim to a screen
                  reader; a decorative bar repeating it is noise. */}
              <span className="ov-bar-track" aria-hidden="true">
                <span className="ov-bar-fill" style={{ width: `${row.score * 100}%` }} />
              </span>
              <span className="ov-tradeoff-figure">
                {formatScoreValue(row.score)}
                {/* ⚠ NOT OPTIONAL, NOT DROPPABLE. The one number on this row
                    keeps the word that says how much it is worth. */}
                <span className="ov-tradeoff-conf"> · {row.confidence} confidence</span>
              </span>
            </span>
            <span className="ov-tradeoff-cost">
              {row.price.kind === "priced"
                ? formatQuote(row.price.usdPerHundredAnswers)
                : row.price.kind === "free_on_campus"
                  ? "Free"
                  : "Not priced"}
              <span className="ov-tradeoff-cost-unit">
                {row.price.kind === "priced" ? "per 100 answers" : ""}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* The page                                                                  */
/* ------------------------------------------------------------------------ */

export default async function OverviewPage() {
  // ⚠ THE PAGE MUST SURVIVE THE API BEING DOWN, for the same reason `/` does:
  // it is a front door, shown to the visitor least willing to try again. The
  // doors below and the argument around them do not need the API; only the
  // reading does, and a missing reading says so.
  let overview: Overview | null = null;
  try {
    overview = buildOverview(await getLeaderboard());
  } catch {
    overview = null;
  }

  return (
    <div className="ld ov">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>

      <header className="ld-mast">
        <div className="ld-wrap">
          <div className="ld-mast-inner">
            <Link href="/" className="ld-logo">
              ida<span className="ld-logo-dot">·</span>llm
            </Link>
            <span className="ld-mast-meta">
              Institute of Data Analytics · University of Alabama
            </span>
          </div>
        </div>
      </header>

      <main id="main-content" className="ld-content">
        {/* ------------------------------ hero ------------------------------ */}
        <section className="ld-hero">
          <div className="ld-wrap">
            <div className="ld-grid">
              <div className="ld-rail ld-reveal ld-d1">Where to start</div>
              <div className="ld-col">
                <h1 className="ld-reveal ld-d1">
                  Which AI is actually good at academic work
                  <span className="ld-turn">— and what it costs you.</span>
                </h1>

                <p className="ld-lede ld-reveal ld-d2">
                  We run AI models against the learning outcomes this programme
                  already publishes, and report what we find — including how much
                  of it we have genuinely measured. Here is the short version.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* --------------------- the demonstration tell --------------------- */}
        {/* ⚠ HIGH ON THE PAGE, NOT IN THE FOOTER. A disclosure a reader meets
            after forming an impression has not disclosed anything. It renders
            only when it is true of this deployment's data — see
            `is_demonstration` in the API for why that is per row. */}
        {overview && overview.demonstration.any ? (
          <section className="ld-section ov-section-tight">
            <div className="ld-wrap">
              <div className="ld-grid ld-grid-wide">
                <div className="ld-rail">Read this first</div>
                <div className="ld-col">
                  <p
                    className={`ov-demo-notice${overview.demonstration.all ? " ov-demo-notice-all" : ""}`}
                  >
                    {overview.demonstration.notice}
                  </p>
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {/* ---------------------------- the read ---------------------------- */}
        <section className="ld-section ov-section-tight">
          <div className="ld-wrap">
            <div className="ld-grid ld-grid-wide">
              <div className="ld-rail">
                The short version
                <span className="ld-note">
                  One sentence, then the models it is about. Everything under it
                  is one click away.
                </span>
              </div>
              <div className="ld-col">
                {overview === null ? (
                  <p className="ov-headline ov-headline-down">
                    We cannot reach the benchmark service from this page right
                    now, so the findings are missing rather than stale.
                    Everything else here still stands, and the results
                    themselves are one click away below.
                  </p>
                ) : (
                  <>
                    <p className="ov-headline">{overview.headline}</p>

                    {overview.standouts.length > 0 ? (
                      <div className="ov-cards">
                        {overview.standouts.map((standout) => (
                          <StandoutCard key={standout.model_key} standout={standout} />
                        ))}
                      </div>
                    ) : null}

                    <TradeOff overview={overview} />

                    {/* ⚠ REQUIRED FIELD, NOT A PARAGRAPH SOMEBODY MIGHT DELETE.
                        A global ranking across a whole programme is not an
                        answer for one professor's course, and this is where the
                        page says so before offering the door that is. */}
                    <p className="ov-nudge">{overview.scopeNudge}</p>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* --------------------------- the caveats --------------------------- */}
        {overview && overview.anyMeasured ? (
          <section className="ld-section ld-band">
            <div className="ld-wrap">
              <div className="ld-grid ld-grid-wide">
                <div className="ld-rail">
                  What this does not say
                  <span className="ld-note">
                    The qualifiers travel with the claim. They are not
                    small print.
                  </span>
                </div>
                <div className="ld-col">
                  <h2 className="ld-h2">Before you repeat any of this.</h2>
                  <ul className="ov-caveats">
                    {[...overview.value.caveats, ...overview.findings.caveats].map(
                      (caveat, index) => (
                        <li key={index}>{caveat}</li>
                      ),
                    )}
                  </ul>
                  <p className="ov-coverage">
                    So far this covers{" "}
                    <strong>
                      {overview.outcomesMeasured} of the {overview.outcomeCount}
                    </strong>{" "}
                    learning outcomes the programme publishes. The rest is not a
                    poor result — it has not been run yet.
                  </p>
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {/* ---------------------------- the doors ---------------------------- */}
        <section className="ld-section" id="doors">
          <div className="ld-wrap">
            <div className="ld-grid ld-grid-wide">
              <div className="ld-rail">
                Three ways deeper
                <span className="ld-note">
                  Only if you want to. The reading above is the whole story at
                  the level most people need it.
                </span>
              </div>
              <div className="ld-col">
                <h2 className="ld-h2">Where would you like to go next?</h2>

                <div className="ov-doors">
                  <Link className="ld-door ld-door-primary" href="/recommend">
                    <span className="ld-eyebrow">For your situation</span>
                    <h3>Get a recommendation for what you actually do</h3>
                    <p>
                      A few questions about what you teach or research, and
                      whether you are asking for yourself or for your students —
                      then a specific answer, with what it is based on and what
                      to watch out for.
                    </p>
                    <span className="ld-go">
                      Start the questions
                      <Arrow className="ld-arrow" />
                    </span>
                  </Link>

                  <Link className="ld-door" href="/leaderboard">
                    <span className="ld-eyebrow">The method</span>
                    <h3>See what we actually tested</h3>
                    <p>
                      Every task we wrote, what it asks, how it was marked, and
                      which of those were checked by a program rather than
                      judged by another AI. Every number opens onto the run
                      behind it.
                    </p>
                    <span className="ld-go">
                      Open the evidence
                      <Arrow className="ld-arrow" />
                    </span>
                  </Link>

                  {/* ⚠ THE THIRD DOOR IS THE POINT OF THE NUDGE ABOVE, and it
                      is wired to a filter that genuinely exists: `/compare` is
                      models × outcomes, so a reader lands on the per-outcome
                      breakdown rather than on a promise. A per-DISCIPLINE view
                      is the follow-up; outcomes are the axis the benchmark
                      actually has today, and pointing at a page we have not
                      built would be the one dishonesty this page cannot
                      afford. */}
                  <Link className="ld-door" href="/compare">
                    <span className="ld-eyebrow">Your field</span>
                    <h3>See the outcome you care about, on its own</h3>
                    <p>
                      An overall winner can be the wrong pick for your subject.
                      This breaks every model down outcome by outcome, so you
                      can look at the one you teach instead of the average
                      across all of them.
                    </p>
                    <span className="ld-go">
                      Compare by outcome
                      <Arrow className="ld-arrow" />
                    </span>
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ---------------------------- how to trust ------------------------- */}
        <section className="ld-section ld-band">
          <div className="ld-wrap">
            <div className="ld-grid ld-grid-wide">
              <div className="ld-rail">How to trust this</div>
              <div className="ld-col">
                <h2 className="ld-h2">What we will and will not claim.</h2>
                <div className="ld-trust">
                  <div className="ld-trust-item">
                    <b>There is no overall winner, and we will not invent one.</b>
                    <span>
                      A model that leads on quantitative work can be mediocre at
                      ethical reasoning. Every strength above is named with the
                      outcome it belongs to, because a single ranking across a
                      whole degree is not a fact about your course.
                    </span>
                  </div>
                  <div className="ld-trust-item">
                    <b>Prices are the provider&rsquo;s, not our bill.</b>
                    <span>
                      The figures above come from each provider&rsquo;s published
                      rates applied to the answer lengths we actually observed —
                      not from what our own testing happened to spend, which
                      would tell you about our benchmark rather than about the
                      model.
                    </span>
                  </div>
                  <div className="ld-trust-item">
                    <b>We say how much each number is worth.</b>
                    <span>
                      A score a program checked against a known answer and one
                      another AI judged against a written guide are different
                      kinds of evidence. Every figure here carries which one it
                      is, and a judged score is never called high confidence.
                    </span>
                  </div>
                  <div className="ld-trust-item">
                    <b>Gaps are shown as loudly as findings.</b>
                    <span>
                      Most of this benchmark has not been run yet, and the page
                      says so where it is true rather than filling the space.
                      Nothing unmeasured is quietly counted as a zero.
                    </span>
                  </div>
                  <div className="ld-trust-item">
                    <b>Every number opens up.</b>
                    <span>
                      Each result links to the run behind it — what we asked,
                      what the model answered, how it was marked, and when. If
                      you disagree with a score, you can see exactly what
                      produced it.
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="ld-foot">
        <div className="ld-wrap">
          <div className="ld-foot-inner">
            <span>ida·llm · Institute of Data Analytics, University of Alabama</span>
            <nav className="ld-foot-links">
              <Link href="/leaderboard">Results</Link>
              <Link href="/compare">Compare by outcome</Link>
              <Link href="/recommend">Get a recommendation</Link>
              <Link href="/">the introduction</Link>
            </nav>
          </div>
        </div>
      </footer>
    </div>
  );
}
