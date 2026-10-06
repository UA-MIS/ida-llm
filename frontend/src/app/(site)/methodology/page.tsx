/**
 * How we test — the method, and the honesty rules the numbers are made under.
 *
 * ⚠ THIS CONTENT USED TO LIVE ON THE LANDING PAGE, inline, as its "how it
 * works" and "how these numbers are made" sections. The landing is a grid now,
 * with no room and no appetite for an essay — the client's whole point was that
 * a screen you must explain has failed. But the explanation still has to exist
 * somewhere a sceptic can find it, so it moved here, one quiet nav click away
 * ("How we test"). Nothing on this page reads a score, by design: it is the
 * method, not the results, so it has no `getLeaderboard` call and no number to
 * disclose.
 */

import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "How we test — Capstone-IDA",
  description:
    "The method behind the numbers: we start from your programme's own learning outcomes, test models on real academic tasks under recorded conditions, and show the evidence behind every score.",
};

export default function MethodologyPage() {
  return (
    <>
      <section className="hero">
        <h2 className="xp-title">How we test</h2>
        <p className="subtitle">
          The benchmark starts from the outcomes your programme already publishes, runs
          real academic tasks against the models under recorded conditions, and shows the
          evidence behind every number. Three steps, and only the first needs you.
        </p>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>The method</h2>
        </div>
        <ol className="method-steps">
          <li>
            <h3>We start from your outcomes</h3>
            <p className="muted">
              We take the learning outcomes your department already publishes — the
              &ldquo;students will be able to…&rdquo; list — and treat each as a separate
              question. Nothing is invented, and nothing is marked against our taste.
            </p>
          </li>
          <li>
            <h3>We test the models on real work</h3>
            <p className="muted">
              Each outcome becomes a set of real academic tasks — the kind of thing you
              would assign. Models run them under recorded conditions. Where an answer is
              checkable, a program checks it; where it takes judgement, we use anchored
              rubrics and say so.
            </p>
          </li>
          <li>
            <h3>You get an answer for your situation</h3>
            <p className="muted">
              Not a leaderboard to interpret. For this class, this part of it, and the way
              you want to use it: what we suggest, what to watch for, and every result it
              rests on.
            </p>
          </li>
        </ol>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>How these numbers are made</h2>
        </div>
        <dl className="method-rules">
          <div>
            <dt>Every number opens.</dt>
            <dd className="muted">
              Each result links to the run behind it: the prompts, the model settings, the
              date it ran, and the raw output.
            </dd>
          </div>
          <div>
            <dt>Gaps are shown, not filled.</dt>
            <dd className="muted">
              Parts of a class we have not run are shown as gaps. Nothing unmeasured is
              counted as a zero.
            </dd>
          </div>
          <div>
            <dt>A failed run is not a wrong answer.</dt>
            <dd className="muted">
              Failed attempts are excluded from a score, never counted as zero. An outage
              must not be able to make a model look incompetent.
            </dd>
          </div>
          <div>
            <dt>Every score carries its evidence.</dt>
            <dd className="muted">
              A program checking against a known answer and an AI marking against a written
              guide are different kinds of evidence. A judged score is never labelled high
              confidence.
            </dd>
          </div>
          <div>
            <dt>The yardstick is yours, not ours.</dt>
            <dd className="muted">
              We measure against published programme outcomes. A model that falls short
              falls short of something your own department wrote down.
            </dd>
          </div>
        </dl>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Teaching or research — both count</h2>
        </div>
        <p className="muted">
          About half of faculty spend most of their time on scholarship rather than the
          classroom, and &ldquo;which model marks quizzes best&rdquo; is useless to them.
          The same method covers research: literature review, drafting, analysis, and the
          question nobody enjoys asking — which models can safely be shown unpublished
          data. The evidence underneath is the same.
        </p>
        <div className="cta-row">
          <Link className="cta" href="/recommend">
            Help me choose a model →
          </Link>
          <Link className="muted" href="/">
            Back to all majors
          </Link>
        </div>
      </section>
    </>
  );
}
