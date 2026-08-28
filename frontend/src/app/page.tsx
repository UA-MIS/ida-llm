/**
 * The results view — the front door of the product.
 *
 * **Task-first, deliberately** (direction B from the sprint-planning session).
 * A professor arrives asking *"can it grade my quizzes?"*, not *"rank these
 * seven models"*. So the page opens with a task chooser, and a cross-model
 * ranking is what you find *inside* a task rather than what you land on. The
 * raw run log still exists, one link away at `/runs`, as the "show me the data"
 * drill-down it always was.
 *
 * **Two rules this page never breaks.**
 *
 * 1. It never invents a number. With no runs in the database it says so in
 *    words and tells you how to start one — an empty table would read as a
 *    broken page, and a placeholder number would be a lie.
 * 2. Every score carries its trust tell and a link to the run that produced it.
 *    That pairing is the whole credibility argument; a score shown without it
 *    is the thing every other AI leaderboard already does.
 *
 * Server-rendered with the filter in the URL, so no client bundle is needed to
 * pick a task, and any view a professor is looking at is a link they can send
 * to a colleague.
 */

import Link from "next/link";

import { ModelResultCard } from "@/components/model-result-card";
import { TrustLegend } from "@/components/trust-badges";
import { getLeaderboard } from "@/lib/api";
import { FACET_LABEL, facetValueLabel, plainTags } from "@/lib/trust";
import type { LeaderboardResponse, TaskLeaderboard } from "@/lib/types";

/** Results change as runs land, so never statically render this page. */
export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/**
 * "I want help with: [ … ]" — the entry point, as links rather than a dropdown.
 *
 * A `<select>` would need client JS to navigate, and this page is otherwise
 * fully server-rendered. Links also mean each task view is addressable, which
 * is how a professor forwards "look at this" to a colleague.
 */
function TaskChooser({
  board,
  selected,
}: {
  board: LeaderboardResponse;
  selected?: string;
}) {
  const measured = board.tasks.filter((task) => task.has_results);
  const unmeasured = board.tasks.filter((task) => !task.has_results);

  return (
    <div className="chooser">
      <div className="chooser-label">I want help with</div>
      <div className="chips">
        <Link
          href="/"
          className={`chip${selected ? "" : " chip-active"}`}
          aria-current={selected ? undefined : "page"}
        >
          Everything
        </Link>
        {measured.map((task) => (
          <Link
            key={task.task_id}
            href={`/?task=${encodeURIComponent(task.task_id)}`}
            className={`chip${selected === task.task_id ? " chip-active" : ""}`}
            aria-current={selected === task.task_id ? "page" : undefined}
            title={task.description}
          >
            {task.title}
          </Link>
        ))}
      </div>
      {unmeasured.length > 0 ? (
        <details className="chooser-more">
          <summary className="muted">
            {unmeasured.length} more task{unmeasured.length === 1 ? "" : "s"} in the
            catalog that nothing has been measured on yet
          </summary>
          <div className="chips">
            {unmeasured.map((task) => (
              <Link
                key={task.task_id}
                href={`/?task=${encodeURIComponent(task.task_id)}`}
                className={`chip chip-empty${selected === task.task_id ? " chip-active" : ""}`}
                title={task.description}
              >
                {task.title}
              </Link>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}

/** The SLO / use-mode facets, shown only once tasks actually carry those tags. */
function FacetRow({ task }: { task: TaskLeaderboard }) {
  const entries = Object.entries(task.facets);
  const tags = plainTags(task.tags);
  return (
    <div className="facet-row">
      <span className="badge">{task.kind}</span>
      <span className="badge">{task.domain}</span>
      {entries.map(([facet, values]) =>
        values.map((value) => (
          <span
            key={`${facet}:${value}`}
            className="badge badge-facet"
            title={FACET_LABEL[facet] ?? facet}
          >
            {FACET_LABEL[facet] ?? facet}: {facetValueLabel(facet, value)}
          </span>
        )),
      )}
      {tags.map((tag) => (
        <span key={tag} className="badge badge-tag mono">
          {tag}
        </span>
      ))}
    </div>
  );
}

function TaskSection({ task }: { task: TaskLeaderboard }) {
  return (
    <section className="task-section">
      <h2 className="task-title">{task.title}</h2>
      <p className="muted task-description">{task.description}</p>
      <FacetRow task={task} />

      {task.has_results ? (
        <ol className="result-list">
          {task.results.map((result, index) => (
            <ModelResultCard
              key={result.model_key}
              result={result}
              rank={index + 1}
              isBest={result.model_key === task.best_model_key}
            />
          ))}
        </ol>
      ) : (
        /* Not a placeholder score, not an empty table — a sentence. */
        <div className="notice">
          <strong>Nothing measured on this task yet.</strong>{" "}
          {task.scorable
            ? "No model has a finished run against it, so there is no number to show — and we would rather show none than invent one."
            : (task.unscorable_reason ??
              "This task cannot be scored yet, so a run against it would produce no number.")}
        </div>
      )}
    </section>
  );
}

/** What a fresh install sees. Honest, and actionable. */
function NothingMeasuredYet({ taskCount }: { taskCount: number }) {
  return (
    <div className="empty">
      <h2>No benchmark results yet</h2>
      <p className="muted">
        {taskCount} task{taskCount === 1 ? " is" : "s are"} authored and ready to
        run, but nothing has been measured against them. Rather than show you a
        placeholder number, this page will stay empty until a run finishes.
      </p>
      <p className="muted">
        Start one with:
        <br />
        <code className="mono">
          curl -X POST localhost:8000/runs -H &apos;content-type:
          application/json&apos; -d &apos;
          {`{"task_ids":["demo/arithmetic-quiz-check"],"model_keys":["mock"]}`}
          &apos;
        </code>
      </p>
      <p className="muted">
        In the meantime, the{" "}
        <Link href="/recommend">recommendation flow</Link> still works — and it
        will tell you, honestly, that it has no evidence to recommend on.
      </p>
    </div>
  );
}

export default async function ResultsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const selected = one(params.task);
  const board = await getLeaderboard();

  const shown = selected
    ? board.tasks.filter((task) => task.task_id === selected)
    : board.tasks.filter((task) => task.has_results);

  return (
    <>
      <p className="subtitle">
        Which model does what you need — measured against real academic tasks,
        with the evidence behind every number one click away.
      </p>

      <div className="cta-row">
        <Link href="/recommend" className="cta">
          Not sure what you need? Answer a few questions ▸
        </Link>
      </div>

      <TaskChooser board={board} selected={selected} />
      <TrustLegend />

      {!board.has_any_results ? (
        <NothingMeasuredYet taskCount={board.task_count} />
      ) : shown.length === 0 ? (
        <div className="notice">
          <strong>No such task.</strong> Nothing in the catalog matches{" "}
          <code className="mono">{selected}</code>.{" "}
          <Link href="/">Show everything measured</Link>.
        </div>
      ) : (
        <>
          <p className="muted results-meta">
            Showing {shown.length} task{shown.length === 1 ? "" : "s"} ·{" "}
            {board.measured_task_count} of {board.task_count} tasks in the catalog
            have been measured · {board.runs_considered} run
            {board.runs_considered === 1 ? "" : "s"} read (the newest finished run
            per task and model) ·{" "}
            <Link href="/runs">see every run</Link>
          </p>
          {shown.map((task) => (
            <TaskSection key={task.task_id} task={task} />
          ))}
        </>
      )}
    </>
  );
}
