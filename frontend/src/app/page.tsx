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
import {
  groupByOutcome,
  outcomeHeading,
  outcomeOf,
  plainTags,
  titleForUseMode,
} from "@/lib/trust";
import type {
  CurriculumView,
  LeaderboardResponse,
  TaskLeaderboard,
} from "@/lib/types";

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

/**
 * A task's axes and descriptive tags.
 *
 * The use mode is captioned from the curriculum, never from a table in this
 * file — `assistive` is the programme's word, and an invented caption is a
 * caption that disagrees with it.
 */
function FacetRow({
  task,
  curriculum,
}: {
  task: TaskLeaderboard;
  curriculum: CurriculumView;
}) {
  return (
    <div className="facet-row">
      <span className="badge">{task.kind}</span>
      <span className="badge">{task.domain}</span>
      {task.use_mode ? (
        <span
          className="badge badge-facet"
          title={
            curriculum.use_modes.find((mode) => mode.id === task.use_mode)
              ?.statement ?? "What is being asked of the model."
          }
        >
          {titleForUseMode(curriculum, task.use_mode)}
        </span>
      ) : null}
      {plainTags(task.tags).map((tag) => (
        <span key={tag} className="badge badge-tag mono">
          {tag}
        </span>
      ))}
    </div>
  );
}

/**
 * The heading for one Student Learning Outcome, with the programme's own words.
 *
 * This is the credibility claim of the whole SLO framing rendered: we are not
 * measuring against *our* opinion of what matters, we are measuring against the
 * outcome the programme published — so the outcome is quoted, not paraphrased,
 * and it comes off the wire rather than out of this component.
 */
function OutcomeHeading({
  slo,
  curriculum,
}: {
  slo: string | null;
  curriculum: CurriculumView;
}) {
  if (slo === null) {
    return (
      <div className="outcome-heading">
        <h2>Not part of the SLO benchmark</h2>
        <p className="muted">
          These families predate the curriculum-anchored benchmark. They are real
          measurements; they are just not filed under an outcome.
        </p>
      </div>
    );
  }
  const outcome = outcomeOf(curriculum, slo);
  return (
    <div className="outcome-heading">
      <h2>{outcomeHeading(curriculum, slo)}</h2>
      {outcome ? (
        <>
          <blockquote className="outcome-statement">{outcome.statement}</blockquote>
          <p className="muted outcome-note">
            The programme&rsquo;s own published outcome
            {curriculum.program ? ` for ${curriculum.program}` : ""}. Everything
            below asks: how well can a model do what this outcome says a student
            should be able to do?
          </p>
        </>
      ) : (
        /* Never invent a statement. An id we cannot look up is a tagging error
           the task-schema CI gate reports — surfacing it is how it gets fixed. */
        <p className="muted">
          {curriculum.available
            ? `No outcome ${slo} in the curriculum map — this is a tagging error, and \`make lint-tasks\` will name it.`
            : "Outcome statements are unavailable in this deployment, so this group is shown by id."}
        </p>
      )}
    </div>
  );
}

function TaskSection({
  task,
  curriculum,
}: {
  task: TaskLeaderboard;
  curriculum: CurriculumView;
}) {
  return (
    <section className="task-section">
      <h3 className="task-title">{task.title}</h3>
      <p className="muted task-description">{task.description}</p>
      <FacetRow task={task} curriculum={curriculum} />

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

/**
 * The outcome filter — one link per SLO, plus the whole-benchmark filter.
 *
 * Rendered from the ids the API found in the catalog and captioned from the
 * curriculum. Nine outcomes are never listed here: a task tagged to an outcome
 * nobody has benchmarked would produce a filter chip leading to an empty page.
 */
function OutcomeFilter({
  board,
  selectedSlo,
  benchmarkOnly,
}: {
  board: LeaderboardResponse;
  selectedSlo?: string;
  benchmarkOnly: boolean;
}) {
  if (board.slos.length === 0) return null;
  return (
    <div className="chooser">
      <div className="chooser-label">Or by learning outcome</div>
      <div className="chips">
        <Link
          href="/"
          className={`chip${!selectedSlo && !benchmarkOnly ? " chip-active" : ""}`}
        >
          Any
        </Link>
        {board.benchmark_task_count > 0 ? (
          <Link
            href="/?benchmark=1"
            className={`chip${benchmarkOnly && !selectedSlo ? " chip-active" : ""}`}
            title="Every task in the curriculum-anchored benchmark — one tag, one filter."
          >
            The whole SLO benchmark ({board.benchmark_task_count})
          </Link>
        ) : null}
        {board.slos.map((slo) => (
          <Link
            key={slo}
            href={`/?slo=${encodeURIComponent(slo)}`}
            className={`chip${selectedSlo === slo ? " chip-active" : ""}`}
            title={outcomeOf(board.curriculum, slo)?.statement ?? slo}
          >
            {outcomeHeading(board.curriculum, slo)}
          </Link>
        ))}
      </div>
      {!board.curriculum.available ? (
        <p className="muted" style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
          {board.curriculum.unavailable_reason}
        </p>
      ) : null}
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
  const selectedSlo = one(params.slo);
  const selectedUseMode = one(params.use_mode);
  const benchmarkOnly = one(params.benchmark) === "1";

  // Filtering happens in the API, on the same parsed axes the CI gate
  // validates — never by re-deriving tags in the browser.
  const board = await getLeaderboard({
    slo: selectedSlo,
    useMode: selectedUseMode,
    benchmark: benchmarkOnly,
  });

  const shown = selected
    ? board.tasks.filter((task) => task.task_id === selected)
    : selectedSlo || selectedUseMode || benchmarkOnly
      ? board.tasks
      : board.tasks.filter((task) => task.has_results);
  const groups = groupByOutcome(shown, board.slos);
  const filtered = Boolean(selectedSlo || selectedUseMode || benchmarkOnly || selected);

  return (
    <>
      <p className="subtitle">
        Which model does what you need — measured against your programme&rsquo;s
        own learning outcomes, with the evidence behind every number one click
        away.
      </p>

      <div className="cta-row">
        <Link href="/recommend" className="cta">
          Not sure what you need? Answer a few questions ▸
        </Link>
      </div>

      <TaskChooser board={board} selected={selected} />
      <OutcomeFilter
        board={board}
        selectedSlo={selectedSlo}
        benchmarkOnly={benchmarkOnly}
      />
      <TrustLegend />

      {!board.has_any_results && !filtered ? (
        <NothingMeasuredYet taskCount={board.task_count} />
      ) : shown.length === 0 ? (
        <div className="notice">
          <strong>Nothing matches that.</strong> No task in the catalog matches
          this filter.{" "}
          <Link href="/">Show everything measured</Link>.
        </div>
      ) : (
        <>
          <p className="muted results-meta">
            Showing {shown.length} task{shown.length === 1 ? "" : "s"} ·{" "}
            {board.measured_task_count} of {board.task_count} measured ·{" "}
            {board.runs_considered} run
            {board.runs_considered === 1 ? "" : "s"} read (the newest finished run
            per task and model) · <Link href="/runs">see every run</Link>
          </p>
          {groups.map((group) => (
            <section key={group.slo ?? "untagged"} className="outcome-group">
              {/* Only worth a heading when there is more than one group, or
                  when the reader explicitly asked for one outcome. */}
              {groups.length > 1 || selectedSlo ? (
                <OutcomeHeading slo={group.slo} curriculum={board.curriculum} />
              ) : null}
              {group.tasks.map((task) => (
                <TaskSection
                  key={task.task_id}
                  task={task}
                  curriculum={board.curriculum}
                />
              ))}
            </section>
          ))}
        </>
      )}
    </>
  );
}
