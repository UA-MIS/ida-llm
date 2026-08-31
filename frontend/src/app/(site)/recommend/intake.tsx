"use client";

/**
 * The intake — the site interrogating a professor, nicely.
 *
 * **The design decision.** Not a fixed ten-question form (a busy professor
 * bounces), not a free chat (impossible to keep on rails). This is direction D
 * from the sprint-planning session: one question at a time, the tree branches
 * on what you answer, and every question shows *why it is being asked* — which
 * is what buys the patience for the next one.
 *
 * **The mechanism that makes it a product rather than a form.** The engine
 * refuses. If it does not have enough, it comes back with the specific gaps
 * rather than a mushy best guess; if a constraint you stated rules out every
 * model, it says so and recommends nothing. Those refusals are rendered here as
 * first-class answers, not as errors — see `Refusal`.
 *
 * Branch logic here is for the *form* only. The server re-derives it before it
 * will answer (`applicable_questions`), so a client that skipped a question
 * cannot skip the gate.
 */

import Link from "next/link";
import { useMemo, useState } from "react";

// ⚠ A SERVER COMPONENT IMPORTED INTO A CLIENT ONE, WHICH IS FINE HERE AND IS
// WORTH SAYING WHY. `Term` uses no hooks, no async and no server-only API — it
// is pure JSX over a pure lookup — so React simply renders it on the client
// alongside this file. The alternative, leaving the result card's own invented
// labels ("evidence score", "guardrails") undefined, fails exactly the reader
// this flow was built for at the moment they finally get an answer.
import { Term } from "@/components/glossary";

import {
  applicableQuestions,
  missingRequired,
  nextQuestion,
  progress,
  pruneAnswers,
  type Answers,
} from "@/lib/intake";
import type {
  IntakeQuestion,
  Recommendation,
  RecommendationResponse,
} from "@/lib/types";

function QuestionCard({
  question,
  value,
  onAnswer,
}: {
  question: IntakeQuestion;
  value: string | undefined;
  onAnswer: (value: string) => void;
}) {
  return (
    <fieldset className="question">
      <legend>
        <h2 className="question-prompt">{question.prompt}</h2>
      </legend>
      {question.detail ? <p className="muted">{question.detail}</p> : null}

      {/* The branch explains itself. A question that appears out of nowhere
          feels like an interrogation; one that says "because you told me student
          work is involved..." feels like a colleague thinking. */}
      {question.branch_note ? (
        <div className="notice notice-branch">{question.branch_note}</div>
      ) : null}

      <div className="options">
        {question.options.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`option${value === option.value ? " option-selected" : ""}`}
            aria-pressed={value === option.value}
            onClick={() => onAnswer(option.value)}
          >
            <span className="option-label">{option.label}</span>
            {option.detail ? (
              <span className="muted option-detail">{option.detail}</span>
            ) : null}
          </button>
        ))}
      </div>

      <p className="muted why">
        <strong>Why we ask:</strong> {question.why_it_matters}
        {!question.required ? " (Optional.)" : null}
      </p>
    </fieldset>
  );
}

function Receipts({ recommendation }: { recommendation: Recommendation }) {
  if (recommendation.receipts.length === 0) return null;
  return (
    <div className="receipts">
      <h4>The evidence</h4>
      <p className="muted">
        Every claim above traces to a <Term id="run">run</Term> you can open and
        read. Nobody else does recommendations with{" "}
        <Term id="receipt">receipts</Term>.
      </p>
      <ul>
        {recommendation.receipts.map((receipt) => (
          <li key={`${receipt.task_id}:${receipt.run_id}`}>
            <strong>
              {receipt.mean_score === null ? "—" : receipt.mean_score.toFixed(2)}
            </strong>{" "}
            on <em>{receipt.task_title}</em>{" "}
            <span className="muted">
              ({receipt.scored_count}/{receipt.sample_count} samples ·{" "}
              {receipt.trust_label} · {receipt.confidence} confidence)
            </span>{" "}
            <Link href={`/runs/${receipt.run_id}`}>see the run ▸</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RecommendationCard({
  recommendation,
  primary,
}: {
  recommendation: Recommendation;
  primary: boolean;
}) {
  return (
    <div className={`card rec-card${primary ? " rec-primary" : ""}`}>
      <h3>{recommendation.headline}</h3>

      <ul className="why-list">
        {recommendation.why.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>

      <dl className="grid">
        <div>
          <dt>Where to use it</dt>
          <dd>
            {recommendation.surface_label}
            <div className="muted" style={{ fontSize: "0.8rem" }}>
              {recommendation.surface_rationale}
            </div>
          </dd>
        </div>
        <div>
          <dt>
            <Term id="cost">Cost</Term>
          </dt>
          <dd>
            {recommendation.cost.label}
            <div className="muted" style={{ fontSize: "0.8rem" }}>
              {recommendation.cost.detail}
            </div>
          </dd>
        </div>
        <div>
          <dt>Where your data goes</dt>
          <dd>{recommendation.data_residency_label}</dd>
        </div>
        <div>
          <dt>
            <Term id="evidence-score">Evidence score</Term>
          </dt>
          <dd>
            {recommendation.evidence_score === null
              ? "—"
              : recommendation.evidence_score.toFixed(2)}
            <div className="muted" style={{ fontSize: "0.8rem" }}>
              {recommendation.verifiable_evidence
                ? "Backed by at least one piece of work a program checked, not just an AI."
                : "Every piece of work behind this was marked by another AI, not checked by a program."}
            </div>
          </dd>
        </div>
      </dl>

      {recommendation.guardrails.length > 0 ? (
        <div className="notice">
          <strong>
            <Term id="guardrail">Guardrails</Term>
          </strong>
          <ul>
            {recommendation.guardrails.map((guardrail) => (
              <li key={guardrail}>{guardrail}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {recommendation.caveats.length > 0 ? (
        <div className="notice">
          <strong>What to know before you rely on this</strong>
          <ul>
            {recommendation.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <h4>
        A <Term id="prompt">prompt</Term> to start from
      </h4>
      <p className="muted">
        Copy this, paste it into the tool, and replace the parts in [square
        brackets] with your own. It is a starting point that already asks for
        the things that make the answer checkable.
      </p>
      <pre>{recommendation.prompt_template}</pre>

      <Receipts recommendation={recommendation} />
    </div>
  );
}

/**
 * A refusal, rendered as an answer.
 *
 * "I can't answer this well yet — here is exactly what is missing" IS the
 * product. Rendering it as an error state would throw away the one behaviour
 * that separates this from every other "which AI should I use" page.
 */
function Refusal({ result }: { result: RecommendationResponse }) {
  return (
    <div className="notice notice-refusal">
      <h2 style={{ marginTop: 0 }}>
        {result.status === "need_more_context"
          ? "I need a bit more before I answer"
          : result.status === "no_eligible_model"
            ? "I'm not going to recommend anything here"
            : "We haven't measured this yet"}
      </h2>
      <p>{result.message}</p>

      {result.gaps.length > 0 ? (
        <ul>
          {result.gaps.map((gap) => (
            <li key={gap.question_id}>
              <strong>{gap.prompt}</strong>
              <div className="muted">{gap.why_it_matters}</div>
            </li>
          ))}
        </ul>
      ) : null}

      {result.missing_benchmarks.length > 0 ? (
        <>
          <p className="muted">
            Tasks we would need to benchmark before we could answer this well:
          </p>
          <ul className="mono">
            {result.missing_benchmarks.map((taskId) => (
              <li key={taskId}>{taskId}</li>
            ))}
          </ul>
        </>
      ) : null}

      {result.what_would_change_this.length > 0 ? (
        <>
          <p>
            <strong>What would change this:</strong>
          </p>
          <ul>
            {result.what_would_change_this.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

function Result({ result }: { result: RecommendationResponse }) {
  return (
    <div className="rec-result">
      {result.context_summary.length > 0 ? (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>What we understood</h3>
          <dl className="grid">
            {result.context_summary.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      {result.constraints.length > 0 ? (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>What narrowed the field</h3>
          <ul>
            {result.constraints.map((constraint) => (
              <li key={constraint.label}>
                <strong>{constraint.label}</strong>
                {constraint.hard ? (
                  <span className="badge badge-hard"> hard requirement</span>
                ) : null}
                <div className="muted">{constraint.detail}</div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {result.status === "ok" && result.primary ? (
        <>
          <p className="subtitle">{result.message}</p>
          <RecommendationCard recommendation={result.primary} primary />
          {result.alternatives.length > 0 ? (
            <>
              <h2>Alternatives</h2>
              {result.alternatives.map((alternative) => (
                <RecommendationCard
                  key={alternative.model_key}
                  recommendation={alternative}
                  primary={false}
                />
              ))}
            </>
          ) : null}
          {result.what_would_change_this.length > 0 ? (
            <ul className="muted">
              {result.what_would_change_this.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : (
        <Refusal result={result} />
      )}
    </div>
  );
}

export function Intake({ questions }: { questions: IntakeQuestion[] }) {
  const [answers, setAnswers] = useState<Answers>({});
  const [result, setResult] = useState<RecommendationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const applicable = useMemo(
    () => applicableQuestions(questions, answers),
    [questions, answers],
  );
  const missing = useMemo(
    () => missingRequired(questions, answers),
    [questions, answers],
  );
  const current = useMemo(
    () => nextQuestion(questions, answers),
    [questions, answers],
  );
  const { answered, total } = progress(questions, answers);

  function answer(questionId: string, value: string) {
    // Prune, don't just set: retracting "student work is involved" must retract
    // the FERPA answer too, because that answer sets a HARD constraint and a
    // stale one would silently change the recommendation.
    setAnswers((previous) =>
      pruneAnswers(questions, { ...previous, [questionId]: value }),
    );
    setResult(null);
    setError(null);
  }

  async function ask() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/recommend", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ answers }),
      });
      if (!response.ok) {
        throw new Error(
          `Could not get a recommendation (${response.status} ${response.statusText}).`,
        );
      }
      setResult((await response.json()) as RecommendationResponse);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPending(false);
    }
  }

  if (result) {
    return (
      <>
        <Result result={result} />
        <p>
          <button
            type="button"
            className="secondary"
            onClick={() => setResult(null)}
          >
            ← Change my answers
          </button>
        </p>
      </>
    );
  }

  return (
    <>
      <div className="progress" aria-hidden="true">
        <div
          className="progress-fill"
          style={{ width: `${total ? (answered / total) * 100 : 0}%` }}
        />
      </div>
      <p className="muted">
        {answered} of {total} question{total === 1 ? "" : "s"} answered
        {missing.length > 0
          ? ` · ${missing.length} still needed before we will answer`
          : " · ready"}
      </p>

      {current ? (
        <QuestionCard
          question={current}
          value={answers[current.id]}
          onAnswer={(value) => answer(current.id, value)}
        />
      ) : (
        <p className="muted">That is everything we ask. Nothing is missing.</p>
      )}

      {/* Answered questions stay visible and changeable. A wizard that hides
          what you already said makes you distrust what it will do with it. */}
      {applicable.some((question) => answers[question.id]) ? (
        <details className="answered">
          <summary className="muted">Your answers so far</summary>
          {applicable
            .filter((question) => answers[question.id])
            .map((question) => (
              <QuestionCard
                key={question.id}
                question={question}
                value={answers[question.id]}
                onAnswer={(value) => answer(question.id, value)}
              />
            ))}
        </details>
      ) : null}

      {error ? (
        <div className="notice notice-error">
          <p className="mono">{error}</p>
        </div>
      ) : null}

      <div className="cta-row">
        <button type="button" onClick={ask} disabled={pending}>
          {pending ? "Looking…" : "Recommend something"}
        </button>
        {missing.length > 0 ? (
          <span className="muted">
            You can ask now — we will tell you exactly what is still missing
            rather than guess.
          </span>
        ) : null}
      </div>
    </>
  );
}
