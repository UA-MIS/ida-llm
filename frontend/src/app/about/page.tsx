/**
 * The front door.
 *
 * ⚠ THIS IS AN ARGUMENT, NOT A DASHBOARD, and the distinction is the whole
 * reason it exists. `/` used to be the leaderboard — a ranked table above a
 * task catalogue — which is the right page for someone who already believes
 * the numbers. It is the wrong page for the person this project has to reach:
 * a professor who does not work with AI, has been told to have a policy on it,
 * and has no reason yet to trust a website about it. That reader bounces off a
 * table of scores. The leaderboard now lives at `/leaderboard`, one click away
 * behind a door that says what is behind it.
 *
 * ⚠ THE DENSE DATA STAYS OFF THIS PAGE ON PURPOSE. There is exactly one number
 * anywhere below, and it appears only when a real finished run stands behind it.
 * Everything else is words, because the job here is comprehension, not
 * comparison.
 *
 * ⚠ WHAT KEEPS IT HONEST IS IN lib/specimen.ts, not here. Two of the three use
 * modes have no data and cannot yet have any; this file renders whatever
 * `buildSpecimen` returns and has no way to write a finding of its own.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { getLeaderboard } from "@/lib/api";
import { buildSpecimen, type SpecimenReading, type SpecimenResult } from "@/lib/specimen";

/** The findings reflect whatever has finished running, so never cache this. */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Which AI helps in your course — Capstone-IDA",
  description:
    "We measure AI models against the learning outcomes your programme publishes, on real coursework, and report what each is good for in your class — with the evidence behind every claim.",
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
 * One drawn mark per use mode, chosen to mean something:
 *   capability    — a straight arrow cutting across the long way round: a shortcut.
 *   assistive     — a rising stair: a student getting somewhere.
 *   instructional — a nib over ruled lines: someone marking work.
 *
 * Falls back to a neutral dot for a mode this file has not seen, because the
 * curriculum is allowed to grow a fourth one without breaking the page.
 */
function ModeGlyph({ modeId }: { modeId: string }) {
  const common = {
    width: 22,
    height: 22,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  if (modeId === "capability") {
    return (
      <svg {...common}>
        <path d="M3 19c2-9 8-14 18-14" strokeDasharray="2.6 3" />
        <path d="M3 19h15" />
        <path d="M14 15l4 4-4 4" />
      </svg>
    );
  }
  if (modeId === "assistive") {
    return (
      <svg {...common}>
        <path d="M3 20h5v-5h5V9.5h5V4" />
        <circle cx="18" cy="4" r="1.7" fill="currentColor" stroke="none" />
      </svg>
    );
  }
  if (modeId === "instructional") {
    return (
      <svg {...common}>
        <path d="M4 6h9M4 11h13M4 16h7" />
        <path d="M16.5 15.5l4-4 2 2-4 4-2.6.6z" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="3.2" />
    </svg>
  );
}

/**
 * One reading. The verdict word and the receipt appear only for a measured
 * mode; everything else renders identically either way, so a gap looks like a
 * finding rather than like a broken panel.
 */
function Reading({ reading }: { reading: SpecimenReading }) {
  const measured = reading.status === "measured";
  return (
    <div className={`ld-reading ld-reading-${reading.modeId}`}>
      <span className="ld-glyph">
        <ModeGlyph modeId={reading.modeId} />
      </span>
      <div>
        <p className="ld-q">{reading.question}</p>
        <p className="ld-a">
          <span className={measured ? "ld-verdict" : "ld-verdict-none"}>
            {reading.headline}.
          </span>{" "}
          {reading.detail}
        </p>
        {measured && reading.best ? (
          <Link
            className="ld-receipt"
            href={`/leaderboard?task=${encodeURIComponent(reading.best.taskId)}`}
          >
            {/* ⚠ NO NESTED, LOWER-CASED PARENTHESES. This used to render the
                API's raw tier label inside brackets inside a link —
                "See the runs behind this (subjective (ai-scored), low
                confidence — thin evidence)" — on the one receipt the front door
                has. It read like a build artefact on the page whose entire job
                is the first impression. `trustLabel` now arrives already
                translated (see `lib/specimen.ts`), and the qualification hangs
                off an em dash instead of nesting. */}
            See the runs behind this — {reading.best.trustLabel.toLowerCase()},{" "}
            {reading.best.confidenceLabel.toLowerCase()}
          </Link>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The specimen: one outcome, quoted, with what we can say about it.
 *
 * When the API is unreachable or the deployment has no curriculum map, this
 * says which of those happened instead of rendering an empty frame. A front
 * door that silently loses its central exhibit is worse than one that explains
 * itself.
 */
function Specimen({ specimen }: { specimen: SpecimenResult }) {
  if (!specimen.available) {
    return (
      <div className="ld-specimen">
        <p className="ld-slo-src">The example, unavailable</p>
        <p className="ld-lede">
          One of the programme&rsquo;s published outcomes normally sits here,
          with what we have measured against it.
        </p>
        <p className="ld-specimen-foot">{specimen.reason}</p>
      </div>
    );
  }

  return (
    <div className="ld-specimen">
      <p className="ld-slo-src">
        {[specimen.program, `${specimen.outcome.id} · ${specimen.outcome.title}`]
          .filter(Boolean)
          .join(" · ")}{" "}
        · as published
      </p>

      {/* Quoted verbatim from curriculum/slo.yaml — the registrar's wording,
          not ours. That quotation IS the credibility claim of the SLO framing,
          and paraphrasing it would give the whole argument away. */}
      <blockquote className="ld-slo">&ldquo;{specimen.outcome.statement}&rdquo;</blockquote>

      <div className="ld-readings">
        {specimen.readings.map((reading) => (
          <Reading key={reading.modeId} reading={reading} />
        ))}
      </div>

      <p className="ld-specimen-foot">
        {specimen.anyMeasured ? (
          <>
            Three questions, one outcome, answered only where we have measured.
            This runs for every outcome in the programme.
          </>
        ) : (
          <>
            Nothing has finished running against this outcome yet, so all three
            read the same.
          </>
        )}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* The page                                                                  */
/* ------------------------------------------------------------------------ */

export default async function LandingPage() {
  // ⚠ THE PITCH MUST SURVIVE THE API BEING DOWN. Every other page on this site
  // is meaningless without data and is right to fail loudly. This one is an
  // argument made of sentences; only the specimen needs the API. A 500 here is
  // a front door that will not open, shown to the exact visitor least willing
  // to try again.
  let specimen: SpecimenResult;
  try {
    specimen = buildSpecimen(await getLeaderboard());
  } catch {
    specimen = {
      available: false,
      reason:
        "The benchmark service is not reachable from this page right now, so " +
        "there are no measured findings to show.",
    };
  }

  return (
    <div className="ld">
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

      {/* ⚠ QA-25: NO `<main>` LANDMARK ON THIS PAGE AT ALL — everything below
          was reachable only by reading through the whole DOM, never by
          jumping to it. `.ld-content` in globals.css cancels out the generic
          `main { max-width }` rule so this stays visually identical. */}
      <main id="main-content" className="ld-content">
      {/* ---------------------------- hero ---------------------------- */}
      <section className="ld-hero">
        <div className="ld-wrap">
          <div className="ld-grid">
            <div className="ld-rail ld-reveal ld-d1">A benchmark for teaching</div>
            <div className="ld-col">
              <h1 className="ld-reveal ld-d1">
                Your syllabus already says what students should be able to do.
                <span className="ld-turn">We test whether AI can.</span>
              </h1>

              <p className="ld-lede ld-reveal ld-d2">
                We measure AI models against the learning outcomes your own
                programme publishes — on real coursework, not trivia — and report
                what each is good for in your class, with the evidence attached.
              </p>

              <div className="ld-cta-row ld-reveal ld-d3">
                <Link className="ld-btn" href="/leaderboard">
                  See what we found
                  <Arrow />
                </Link>
                <a className="ld-link" href="#how">
                  How the testing works
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* -------------------------- specimen -------------------------- */}
      <section className="ld-section" style={{ paddingTop: 0 }}>
        <div className="ld-wrap">
          <div className="ld-grid ld-grid-wide">
            <div className="ld-rail ld-reveal ld-d4">One outcome</div>
            <div className="ld-col ld-reveal ld-d4">
              <p className="ld-lede" style={{ marginBottom: "1.75rem" }}>
                One outcome, quoted from the programme&rsquo;s own map — and
                everything we can{" "}
                <span className="ld-mark">
                  honestly say
                  <svg viewBox="0 0 400 12" preserveAspectRatio="none" aria-hidden="true">
                    <path d="M3 8.5C64 4.2 143 3.1 208 5.4c62 2.2 121 4.1 189 1.6" />
                  </svg>
                </span>{" "}
                about it.
              </p>
              <Specimen specimen={specimen} />
            </div>
          </div>
        </div>
      </section>

      {/* ----------------------------- why ----------------------------- */}
      <section className="ld-section">
        <div className="ld-wrap">
          <div className="ld-grid">
            <div className="ld-rail">Why this exists</div>
            {/* The one pure-argument section. `ld-split` puts the heading beside
                the prose on a wide screen, which fills the width without ever
                widening a line of body text past its measure. */}
            <div className="ld-col ld-split">
              <h2 className="ld-h2">
                You are being asked to have a position on AI, without being given
                anything to base it on.
              </h2>
              <div className="ld-stack">
              <p>
                The advice on offer is mostly two slogans —{" "}
                <strong>ban it</strong> or <strong>embrace it</strong> — and
                neither knows anything about what you teach. The benchmarks that
                exist mostly measure whether a model can write software, not
                whether it can explain a concept, mark a short answer fairly, or
                coach a student who is stuck.
              </p>
              <p>
                So faculty guess. Some assume every assignment is compromised;
                some assume none are. Both are working from impressions, and
                students can tell.
              </p>
              <p>
                <strong>The honest version is measurable.</strong> Your programme
                already publishes, in plain language, what a student who passes
                should be able to do. That list is not our opinion of what
                matters — it is yours, already written down. So we test against
                it and publish what we find, including the inconvenient parts.
              </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ----------------------------- how ----------------------------- */}
      <section className="ld-section ld-band" id="how">
        <div className="ld-wrap">
          <div className="ld-grid ld-grid-wide">
            <div className="ld-rail">How it works</div>
            <div className="ld-col">
              <h2 className="ld-h2">Three steps, and only the first needs you.</h2>
              <div className="ld-steps">
                <div className="ld-step">
                  <span className="ld-step-n">1</span>
                  <div>
                    <h3>We start from your outcomes</h3>
                    <p>
                      We take the learning outcomes your department already
                      publishes — the &ldquo;students will be able to…&rdquo;
                      list — and treat each as a separate question. Nothing is
                      invented, and nothing is marked against our taste.
                    </p>
                  </div>
                </div>
                <div className="ld-step">
                  <span className="ld-step-n">2</span>
                  <div>
                    <h3>We test the models on real work</h3>
                    <p>
                      Each outcome becomes a set of real academic tasks — the
                      kind of thing you would assign. Models run them under
                      recorded conditions. Where an answer is checkable, a
                      program checks it; where it takes judgement, we use
                      anchored rubrics and say so.
                    </p>
                  </div>
                </div>
                <div className="ld-step">
                  <span className="ld-step-n">3</span>
                  <div>
                    <h3>You get an answer for your situation</h3>
                    <p>
                      Not a leaderboard to interpret. For this course, this
                      outcome, and the way you want to use it: what we suggest,
                      what to watch for, and every result it rests on.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------------------------- doors ---------------------------- */}
      <section className="ld-section" id="doors">
        <div className="ld-wrap">
          <div className="ld-grid ld-grid-wide">
            <div className="ld-rail">Two ways in</div>
            <div className="ld-col">
              <h2 className="ld-h2" style={{ marginBottom: "2.1rem" }}>
                Start with the evidence, or with the answer.
              </h2>

              <div className="ld-doors">
                <Link className="ld-door ld-door-primary" href="/leaderboard">
                  <span className="ld-eyebrow">The results</span>
                  <h3>How AI does on your outcomes</h3>
                  <p>
                    Every outcome tested, model by model, with the evidence
                    behind each number one click away — including the outcomes
                    nothing has measured yet.
                  </p>
                  <span className="ld-go">
                    Open the results
                    <Arrow className="ld-arrow" />
                  </span>
                </Link>

                <Link className="ld-door" href="/recommend">
                  <span className="ld-eyebrow">A recommendation</span>
                  <h3>Get a recommendation for my class</h3>
                  <p>
                    A few questions about what you teach and who will use it,
                    then an answer that says what it rests on.
                  </p>
                  <span className="ld-go">
                    Start the questions
                    <Arrow className="ld-arrow" />
                  </span>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------------------------- trust ---------------------------- */}
      <section className="ld-section ld-band">
        <div className="ld-wrap">
          <div className="ld-grid ld-grid-wide">
            <div className="ld-rail">Method</div>
            <div className="ld-col">
              <h2 className="ld-h2">How these numbers are made.</h2>

              <div className="ld-trust">
                <div className="ld-trust-item">
                  <b>Every number opens.</b>
                  <span>
                    Each result links to the run behind it: the prompts, the
                    model settings, the date it ran, and the raw output.
                  </span>
                </div>
                {/* ⚠ THE RULE, NOT A QUANTITY. This read "Most of this benchmark
                    is not measured yet" and "Two of the three questions … have
                    no data at all today" — both true the day they were written
                    and both false the day a run lands, with nothing to catch
                    the turn. This page renders no counts by design (see the
                    header comment: exactly one number anywhere, and only behind
                    a finished run), so the version that cannot rot states the
                    rule the specimen above already demonstrates. */}
                <div className="ld-trust-item">
                  <b>Gaps are shown, not filled.</b>
                  <span>
                    Outcomes we have not run are shown as gaps. Nothing
                    unmeasured is counted as a zero.
                  </span>
                </div>
                <div className="ld-trust-item">
                  <b>A failed run is not a wrong answer.</b>
                  <span>
                    Failed attempts are excluded from a score, never counted as
                    zero. An outage must not be able to make a model look
                    incompetent.
                  </span>
                </div>
                <div className="ld-trust-item">
                  <b>Every score carries its evidence.</b>
                  <span>
                    A program checking against a known answer and an AI marking
                    against a written guide are different kinds of evidence. A
                    judged score is never labelled high confidence.
                  </span>
                </div>
                <div className="ld-trust-item">
                  <b>The yardstick is yours, not ours.</b>
                  <span>
                    We measure against published programme outcomes. A model
                    that falls short falls short of something your own
                    department wrote down.
                  </span>
                </div>
              </div>

              <div className="ld-audiences">
                <p>
                  <strong>Teaching or research — both count.</strong> About half
                  of faculty spend most of their time on scholarship rather than
                  the classroom, and &ldquo;which model marks quizzes best&rdquo;
                  is useless to them.
                </p>
                <p>
                  The same method covers research: literature review, drafting,
                  analysis, and the question nobody enjoys asking — which models
                  can safely be shown unpublished data. Choose your hat when you
                  start; the evidence underneath is the same.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------------------------- close ---------------------------- */}
      <section className="ld-section" style={{ paddingBottom: "3.5rem" }}>
        <div className="ld-wrap">
          <div className="ld-grid">
            <div className="ld-rail">Start anywhere</div>
            <div className="ld-col">
              <h2 className="ld-h2" style={{ maxWidth: "20ch" }}>
                Nothing here assumes you work with AI.
              </h2>
              <p className="ld-lede">
                Bring a course; leave with a position you can defend to a
                colleague, a dean, or a room full of students.
              </p>
              <div className="ld-cta-row">
                <Link className="ld-btn" href="/leaderboard">
                  See what we found
                  <Arrow />
                </Link>
                <Link className="ld-btn ld-btn-quiet" href="/recommend">
                  Get a recommendation
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>
      </main>

      <footer className="ld-foot">
        <div className="ld-wrap">
          <div className="ld-foot-inner">
            <span>
              ida·llm · Institute of Data Analytics, University of Alabama
            </span>
            <nav className="ld-foot-links">
              <Link href="/leaderboard">Results</Link>
              <Link href="/recommend">Get a recommendation</Link>
              <Link href="/runs">Every run</Link>
            </nav>
          </div>
        </div>
      </footer>
    </div>
  );
}
