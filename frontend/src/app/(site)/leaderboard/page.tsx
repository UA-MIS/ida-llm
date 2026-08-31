/**
 * The front door — MODEL-FIRST, with the task catalogue one control below it.
 *
 * ⚠ THIS PAGE USED TO BE TASK-FIRST AND IT DID NOT SURVIVE CONTACT. The chooser
 * rendered one chip per task (~70 of them) above a second chip row for the nine
 * outcomes, so the first two screens of the product were pills. The single most
 * common question — "which model is best?" — had no answer anywhere on the site,
 * and the leaderboard a visitor came for was something you assembled yourself by
 * clicking a chip and reading one task at a time.
 *
 * The fix is not smaller chips. It is: LEAD WITH THE ANSWER, and demote browsing
 * to a compact control.
 *
 *   1. Models ranked across the whole benchmark, immediately, above the fold.
 *   2. One dropdown and one search box where the chip wall was.
 *   3. Each model's name links to `/models/<key>` — its whole report card in one
 *      place, which is the thing that genuinely did not exist before.
 *
 * ⚠ THE TWO RULES THIS PAGE STILL NEVER BREAKS, and an overall ranking is where
 * they are easiest to break:
 *
 *   1. It never invents a number. A model with no measurement on a task
 *      contributes nothing to its mean — not a zero — and the ranking says how
 *      many tasks and outcomes each model actually covers, so a strong score on
 *      two tasks cannot pass for a strong score on twenty.
 *   2. Every number keeps its trust tell and its receipt. The overall score
 *      carries the WEAKEST confidence of the measurements inside it, because an
 *      aggregate is exactly as good as its shakiest constituent.
 *
 * ONE FETCH. `/leaderboard` with no filters already returns every task × model
 * pairing, which is what the rollup needs; the outcome and search filters are
 * applied to that same response in this file rather than as a second round trip.
 * The filter still lives in the URL, so every view is a link you can send.
 */

import Link from "next/link";

import { GlossaryPanel, Term } from "@/components/glossary";
import { HowToRead, ReadStep } from "@/components/how-to-read";
import { ModelResultCard } from "@/components/model-result-card";
import { PlainSummary } from "@/components/plain-summary";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { ScoreBar } from "@/components/score-bar";
import { ConfidenceMeter, ConfidenceTell, ResidencyBadge, TrustLegend } from "@/components/trust-badges";
import { getLeaderboard } from "@/lib/api";
import { exclusionReason, exclusionSummary } from "@/lib/exclusion";
import { summariseBoard } from "@/lib/findings";
import { LEADERBOARD_TERMS, plainTaskKind } from "@/lib/glossary";
import { formatCost, formatScore } from "@/lib/format";
import {
  confidenceLabel,
  filterTasks,
  isRanked,
  rollupByModel,
  WEIGHTING_NOTE,
  type ModelRollup,
} from "@/lib/rollup";
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

/** Why an aggregate carries the confidence it does — never a server sentence. */
function aggregateReason(rollup: ModelRollup): string {
  const { measured_tasks, scored_samples, verifiable_share } = rollup.overall;
  if (measured_tasks === 0) {
    return "Nothing has been measured for this model yet, so there is no number to be confident about.";
  }
  const checked = Math.round(verifiable_share * 100);
  return (
    `The weakest confidence among the ${measured_tasks} measurement` +
    `${measured_tasks === 1 ? "" : "s"} behind this number, not an average of them — ` +
    `an overall score is only as good as its shakiest part. ${scored_samples} scored ` +
    `sample${scored_samples === 1 ? "" : "s"} in total, ${checked}% of that weight ` +
    `from programmatically-checked tasks.`
  );
}

/**
 * The lead: every model, ranked across the whole benchmark.
 *
 * Test stubs and unmeasured models appear BELOW the ranking rather than inside
 * it. They are real rows in the database and hiding them would be the thing this
 * project exists to replace — but a leaderboard whose #1 is a deterministic mock
 * is the same lie one row higher, and `best_model_key` already excludes stubs
 * for exactly that reason.
 */
function OverallLeaderboard({
  rollups,
  outcomeCount,
}: {
  rollups: ModelRollup[];
  outcomeCount: number;
}) {
  const ranked = rollups.filter(isRanked);
  const unranked = rollups.filter((rollup) => !isRanked(rollup));

  return (
    <section className="panel panel-lead">
      <div className="panel-head">
        <h2>Models, ranked across the whole benchmark</h2>
        {/* ⚠ THE COLUMN GLOSSARY LIVES HERE, ABOVE THE TABLE, AND NOT IN THE
            `<th>`s. The table sits inside `.table-scroll`, whose `overflow-x:
            auto` clips an absolutely-positioned card — a "?" in a header would
            be an affordance that opens nothing. Explaining the columns in the
            note above the table costs a line and works everywhere, including
            on a phone where the optional columns are hidden entirely. */}
        <p className="muted panel-note">
          One row per model. <Term id="overall-score">Overall</Term> is its average
          across everything measured; <Term id="confidence">Confidence</Term> says
          how much weight that average can bear; and{" "}
          <Term id="sample">Samples</Term> is how many attempts stand behind it.
        </p>
        <p className="muted panel-note">{WEIGHTING_NOTE}</p>
      </div>

      {ranked.length === 0 ? (
        <div className="notice">
          <strong>No model has a rankable score yet.</strong> Every measured
          pairing so far is either a test stub or produced no score, so there is
          nothing honest to rank.
        </div>
      ) : (
        <div className="table-scroll">
          <table className="leaderboard">
            <thead>
              <tr>
                <th className="col-rank">#</th>
                <th>Model</th>
                <th className="col-score">Overall</th>
                <th className="num col-optional">Outcomes</th>
                <th className="num col-optional">Tasks</th>
                <th className="num col-optional">Samples</th>
                {/* ⚠ `col-trust`, NOT `col-optional`. Confidence is the one
                    column that must survive the breakpoint: this page's own
                    rule is that every number keeps its trust tell, and dropping
                    it below 760px meant a phone read "0.88" where a desktop
                    read "0.88 · Low confidence". A high score with low
                    confidence is not a verdict, and the phone was showing the
                    score without the half that says so. */}
                <th className="col-trust">Confidence</th>
                <th className="num col-optional">Cost</th>
                {/* ⚠ `col-go` HERE TOO. Without it the header row rendered four
                    cells below 760px while every body row rendered three, and
                    the whole table shifted by one column. */}
                <th className="col-go" aria-label="Report card" />
              </tr>
            </thead>
            <tbody>
              {ranked.map((rollup, index) => (
                <ModelRow
                  key={rollup.model_key}
                  rollup={rollup}
                  rank={index + 1}
                  outcomeCount={outcomeCount}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {unranked.length > 0 ? (
        <details className="also-measured">
          {/* ⚠ COUNTED, NOT ASSUMED. This line used to read "test stubs and
              models nothing has scored yet" whatever the drawer held — and it
              held three models with 70 scored tasks each, one of them scoring
              above the model this page had just crowned. They are unranked
              because the registry has no entry for them, which is a worse fact
              than the one being shown, and therefore the one to show. See
              `lib/exclusion.ts`. */}
          <summary className="muted">
            {exclusionSummary(unranked.map(exclusionReason))}
          </summary>
          <div className="table-scroll">
            <table className="leaderboard leaderboard-muted">
              {/* ⚠ QA-24: THIS TABLE USED TO HAVE NO `<thead>` AT ALL — nine
                  columns of numbers with zero header association, reachable
                  only by sight. Same columns as the ranked table above, so
                  the same headers, each with `scope="col"` so a screen
                  reader can announce which column a cell belongs to when
                  navigating cell-by-cell rather than row-by-row. */}
              <thead>
                <tr>
                  <th scope="col" className="col-rank">#</th>
                  <th scope="col">Model</th>
                  <th scope="col" className="col-score">Overall</th>
                  <th scope="col" className="num col-optional">Outcomes</th>
                  <th scope="col" className="num col-optional">Tasks</th>
                  <th scope="col" className="num col-optional">Samples</th>
                  <th scope="col" className="col-trust">Confidence</th>
                  <th scope="col" className="num col-optional">Cost</th>
                  <th scope="col" className="col-go" aria-label="Report card" />
                </tr>
              </thead>
              <tbody>
                {unranked.map((rollup) => (
                  <ModelRow
                    key={rollup.model_key}
                    rollup={rollup}
                    rank={null}
                    outcomeCount={outcomeCount}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </section>
  );
}

function ModelRow({
  rollup,
  rank,
  outcomeCount,
}: {
  rollup: ModelRollup;
  rank: number | null;
  outcomeCount: number;
}) {
  const { overall } = rollup;
  return (
    <tr className={rank === null ? "row-muted" : undefined}>
      <td className="col-rank num mono">{rank ?? "—"}</td>
      <td>
        <Link href={`/models/${encodeURIComponent(rollup.model_key)}`} className="model-link">
          {rollup.display_name}
        </Link>
        <div className="model-sub">
          <span className="mono muted">{rollup.model_key}</span>
          <ResidencyBadge
            residency={rollup.data_residency}
            label={rollup.data_residency_label}
          />
          {!rollup.enabled ? (
            <span className="badge" title="These measurements stand, but the registry has since disabled the model.">
              not currently runnable
            </span>
          ) : null}
        </div>
      </td>
      <td className="col-score">
        <ScoreBar
          score={overall.score}
          note={
            overall.score === null
              ? "nothing scored yet"
              : `${overall.scored_samples} scored samples`
          }
        />
      </td>
      <td className="num col-optional">
        {rollup.slos_measured.length}
        <span className="muted"> / {outcomeCount}</span>
      </td>
      <td className="num col-optional">
        {overall.measured_tasks}
        <span className="muted"> / {overall.covered_tasks}</span>
      </td>
      <td className="num col-optional">{overall.scored_samples}</td>
      <td className="col-trust">
        <ConfidenceTell
          confidence={overall.confidence}
          label={confidenceLabel(overall.confidence)}
          reason={aggregateReason(rollup)}
        />
      </td>
      <td className="num col-optional">{formatCost(overall.total_cost_usd)}</td>
      <td className="col-go">
        <Link href={`/models/${encodeURIComponent(rollup.model_key)}`}>
          Report card ▸
        </Link>
      </td>
    </tr>
  );
}

/**
 * What replaced the chip wall: one dropdown, one search box.
 *
 * A plain GET form, submitted by a button — no client bundle, and the result is
 * still an addressable URL a professor can forward. A `<select>` that navigated
 * on change would need JS for what a submit button does for free.
 */
function FilterBar({
  board,
  task,
  slo,
  useMode,
  benchmarkOnly,
  query,
  includeUnmeasured,
  active,
}: {
  board: LeaderboardResponse;
  task?: string;
  slo?: string;
  useMode?: string;
  benchmarkOnly: boolean;
  query?: string;
  includeUnmeasured: boolean;
  active: boolean;
}) {
  return (
    <form className="filter-bar" method="get" action="/leaderboard">
      {/* ⚠ HIDDEN INPUTS FOR PARAMS THIS FORM DOES NOT OWN. The form only
          exposes three controls (outcome, search, "include unmeasured"), but
          a GET submit replaces the ENTIRE query string — so without these, a
          reader who arrived via a task deep link (`?task=…`) or a future
          `use_mode`/`benchmark` link and then touches any control here would
          silently lose that selection. `use_mode` and `benchmark` are read by
          this page but not yet produced by any link in the app; they are
          carried forward anyway so a future entry point does not regress. */}
      {task ? <input type="hidden" name="task" value={task} /> : null}
      {useMode ? <input type="hidden" name="use_mode" value={useMode} /> : null}
      {benchmarkOnly ? <input type="hidden" name="benchmark" value="1" /> : null}
      <div className="field">
        <label htmlFor="slo">Learning outcome</label>
        <select id="slo" name="slo" defaultValue={slo ?? ""}>
          <option value="">Every outcome</option>
          {board.slos.map((id) => (
            <option key={id} value={id}>
              {outcomeHeading(board.curriculum, id)}
            </option>
          ))}
        </select>
      </div>
      <div className="field field-grow">
        <label htmlFor="q">Search tasks</label>
        <input
          id="q"
          name="q"
          type="search"
          placeholder="break-even, ethics, citation…"
          defaultValue={query ?? ""}
        />
      </div>
      <div className="field field-check">
        <label htmlFor="unmeasured">
          <input
            id="unmeasured"
            name="unmeasured"
            type="checkbox"
            value="1"
            defaultChecked={includeUnmeasured}
          />{" "}
          Include tasks nothing has measured
        </label>
      </div>
      <div className="field field-actions">
        <button type="submit">Apply</button>
        {active ? (
          <Link href="/leaderboard" className="clear-filter">
            Clear
          </Link>
        ) : null}
      </div>
    </form>
  );
}

/** A task's axes and descriptive tags. Captioned from the curriculum, never a table here. */
function FacetRow({
  task,
  curriculum,
}: {
  task: TaskLeaderboard;
  curriculum: CurriculumView;
}) {
  return (
    <div className="facet-row">
      <span className="badge" title="How this task is marked.">
        {plainTaskKind(task.kind)}
      </span>
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

/** The programme's own words, quoted — that quotation IS the SLO claim. */
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
        <h3>Not part of the SLO benchmark</h3>
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
      <h3>{outcomeHeading(curriculum, slo)}</h3>
      {outcome ? (
        <blockquote className="outcome-statement">{outcome.statement}</blockquote>
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

/** One task, expanded: every model ranked on it. Reached by picking a task. */
function TaskSection({
  task,
  curriculum,
}: {
  task: TaskLeaderboard;
  curriculum: CurriculumView;
}) {
  return (
    <section className="task-section">
      {/* ⚠ `<h4>`, NOT `<h3>`. This section always renders inside
          `<OutcomeHeading>`, whose heading is an `<h3>` — a task title one
          level deeper than its outcome keeps heading navigation (one of the
          two ways a screen-reader user skims a long page) a real hierarchy
          instead of a sibling-shaped nesting. */}
      <h4 className="task-title">{task.title}</h4>
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

/**
 * The catalogue as ONE table rather than seventy chips.
 *
 * ⚠ ONE TABLE, NOT ONE PER OUTCOME. A table per group repeats its header nine
 * times down the page, which reads as nine unrelated widgets rather than one
 * catalogue — the chip wall's problem in a different shape. The outcome becomes
 * a spanning row inside a single table instead, which also lets the outcome
 * column disappear: printing the heading again on every row under it said the
 * same thing twice.
 *
 * The programme's own statement is quoted in that spanning row rather than
 * paraphrased. That quotation IS the credibility claim of the SLO framing.
 */
function TaskTable({
  groups,
  curriculum,
}: {
  groups: { slo: string | null; tasks: TaskLeaderboard[] }[];
  curriculum: CurriculumView;
}) {
  return (
    <div className="table-scroll">
      <table className="task-table">
        <thead>
          <tr>
            <th>Task</th>
            <th className="col-optional">Evidence</th>
            <th>Best measured</th>
            <th className="num">Score</th>
          </tr>
        </thead>
        {groups.map((group) => (
          <tbody key={group.slo ?? "untagged"}>
            <tr className="group-row">
              <th colSpan={4} scope="colgroup">
                <span className="group-row-heading">
                  {group.slo ? outcomeHeading(curriculum, group.slo) : "Outside the SLO benchmark"}
                </span>
                <span className="muted group-row-statement">
                  {group.slo
                    ? (outcomeOf(curriculum, group.slo)?.statement ??
                      (curriculum.available
                        ? `No outcome ${group.slo} in the curriculum map — a tagging error \`make lint-tasks\` will name.`
                        : "Outcome statements are unavailable in this deployment."))
                    : "Real measurements, from families that predate the curriculum-anchored benchmark."}
                </span>
              </th>
            </tr>
            {group.tasks.map((task) => {
              const best = task.results.find(
                (result) => result.model_key === task.best_model_key,
              );
              return (
                <tr key={task.task_id}>
                  <td>
                    <Link href={`/leaderboard?task=${encodeURIComponent(task.task_id)}`}>
                      {task.title}
                    </Link>
                    <div className="mono muted task-id">{task.task_id}</div>
                  </td>
                  {/* ⚠ NOT `{task.kind}`. The raw value is our vocabulary
                      ("subjective"), and it reads as "this result is a matter of
                      opinion" rather than "no single right answer, so an AI
                      marked it". Inside `.table-scroll` a definition card would
                      be clipped, so the words carry it alone. */}
                  <td className="col-optional muted">{plainTaskKind(task.kind)}</td>
                  <td>
                    {best ? (
                      <Link href={`/models/${encodeURIComponent(best.model_key)}`}>
                        {best.display_name}
                      </Link>
                    ) : (
                      <span className="muted">
                        {task.has_results ? "no scored result" : "not measured yet"}
                      </span>
                    )}
                  </td>
                  {/* Every number keeps its trust tell — including this one.
                      The catalogue used to be the one table on the site that
                      showed a bare score, which made it the easiest place to
                      read a thin result as a settled one. */}
                  <td className="num">
                    {best?.mean_score !== undefined && best.mean_score !== null ? (
                      <>
                        {formatScore(best.mean_score)}{" "}
                        <span className="muted score-of">
                          ({best.scored_count}/{best.sample_count})
                        </span>
                        <div className="score-trust">
                          <ConfidenceMeter trust={best.trust} />
                        </div>
                      </>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        ))}
      </table>
    </div>
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
  const selectedSlo = one(params.slo);
  const selectedUseMode = one(params.use_mode);
  const benchmarkOnly = one(params.benchmark) === "1";
  const query = one(params.q);
  const includeUnmeasured = one(params.unmeasured) === "1";

  // ONE fetch, unfiltered. The model rollup needs the whole board anyway, and
  // the filters below are the same field equality the API applies — a second
  // round trip would buy latency and a chance to disagree with itself.
  //
  // ⚠ CAUGHT, NOT THROWN, AND THE REASON IS THE READER RATHER THAN THE UPTIME.
  // Letting this reject reaches `app/error.tsx`, and what a professor gets is a
  // page that reads as "this whole thing is broken" — from which they do not
  // come back. `components/service-unavailable.tsx` sets out the full argument;
  // the short version is that an outage should cost us ten minutes of a
  // reader's patience, not the reader.
  //
  // The landing page has degraded this way since it shipped. This is the same
  // move, on the page the front door's primary button actually points at.
  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return (
      <ResultsUnavailable
        what="the benchmark results"
        retryHref="/leaderboard"
        cause={cause}
      />
    );
  }

  const rollups = rollupByModel(board);
  const outcomeCount = board.curriculum.available
    ? board.curriculum.outcomes.length
    : board.slos.length;

  const filtered = selected
    ? board.tasks.filter((task) => task.task_id === selected)
    : filterTasks(board.tasks, {
        slo: selectedSlo,
        useMode: selectedUseMode,
        benchmark: benchmarkOnly,
        query,
        // Asking for one outcome means wanting to see its gaps too.
        includeUnmeasured: includeUnmeasured || Boolean(selectedSlo),
      });

  const filterActive = Boolean(
    selectedSlo || selectedUseMode || benchmarkOnly || query || includeUnmeasured,
  );
  const groups = groupByOutcome(filtered, board.slos);

  return (
    <>
      {/* ⚠ THE PITCH MOVED. This section used to carry the whole product
          proposition ("Which model does what you need — measured against your
          programme's own learning outcomes…") because this page was `/`. The
          landing page makes that argument now, at length and to someone who has
          not yet decided to trust it. A visitor arriving HERE has already been
          convinced and clicked through, so repeating the pitch would make them
          read the sales copy twice to reach the table they came for. What stays
          is orientation: what this page is, and how much stands behind it. */}
      <section className="hero">
        <p className="subtitle">
          Every model measured against every outcome, ranked. The evidence behind
          each number is one click away.
        </p>
        <div className="cta-row">
          <Link href="/recommend" className="cta">
            Not sure what you need? Answer a few questions ▸
          </Link>
          <span className="muted hero-meta">
            {board.measured_task_count} of {board.task_count} tasks measured ·{" "}
            {board.runs_considered} run{board.runs_considered === 1 ? "" : "s"}{" "}
            read (the newest finished run per task and model) ·{" "}
            <Link href="/runs">see every run</Link>
          </span>
        </div>
      </section>

      {!board.has_any_results ? (
        <NothingMeasuredYet taskCount={board.task_count} />
      ) : (
        <>
          {/* ⚠ SHORT → VISUAL → DETAIL, IN THAT ORDER, AND THE ORDER IS THE
              FEATURE. This page's own header comment sets the rule — LEAD WITH
              THE ANSWER — and until now the answer it led with was a ranked
              table, which is an answer only to a reader who already knows what
              a score is. The sentence and the bars come first; the table is
              unchanged, one scroll down, for the reader who wants it. */}
          <PlainSummary findings={summariseBoard(board)} rollups={rollups} />

          <HowToRead title="This page is evidence, not advice. Here is how to read it.">
            <ReadStep n={1} heading="Start with the paragraph above">
              It is the honest summary of everything measured so far, caveats
              included. If you read nothing else on this page, that is the part
              to read.
            </ReadStep>
            <ReadStep n={2} heading="Scores run from 0.00 to 1.00">
              They are averages over several attempts, not marks out of a
              hundred. Beside each one is a{" "}
              <Term id="confidence">confidence</Term> — how much weight that
              average can bear. A high score with low confidence is a promising
              sign, not a verdict.
            </ReadStep>
            <ReadStep n={3} heading="A blank is a blank, never a nought">
              Most of this benchmark is{" "}
              <Term id="not-measured">not measured yet</Term>, and we show the
              gaps rather than filling them. Nothing here is scored zero for
              having gone untested.
            </ReadStep>
            <ReadStep n={4} heading="Every number opens">
              Follow any &ldquo;see the proof&rdquo; link to the full record —
              what we asked, what the model answered, and how it was marked. If
              you disagree with a score, that is where to look.
            </ReadStep>
            <ReadStep n={5} heading="If you would rather just be told">
              The <Link href="/recommend">recommendation questions</Link> ask
              about your actual situation and give you an answer for it, rather
              than a table to interpret.
            </ReadStep>
          </HowToRead>

          {/* The words this project invented, all in one place, one click from
              wherever a reader first met one. */}
          <GlossaryPanel terms={LEADERBOARD_TERMS} />

          <OverallLeaderboard rollups={rollups} outcomeCount={outcomeCount} />

          <TrustLegend />

          <section className="panel">
            <div className="panel-head">
              <h2>Browse the benchmark</h2>
              <p className="muted panel-note">
                {board.task_count} <Term id="task">tasks</Term> in the catalogue,
                grouped by the{" "}
                <Term id="learning-outcome">learning outcome</Term> each one
                measures. Pick a task to see every model ranked on it — or{" "}
                <Link href="/compare">
                  compare every model by outcome in one grid
                </Link>
                .
              </p>
            </div>

            <FilterBar
              board={board}
              task={selected}
              slo={selectedSlo}
              useMode={selectedUseMode}
              benchmarkOnly={benchmarkOnly}
              query={query}
              includeUnmeasured={includeUnmeasured}
              active={filterActive || Boolean(selected)}
            />

            {selected ? (
              filtered.length === 0 ? (
                <div className="notice">
                  <strong>No such task.</strong> Nothing in the catalogue has the
                  id <span className="mono">{selected}</span>.{" "}
                  <Link href="/leaderboard">Back to everything measured</Link>.
                </div>
              ) : (
                groups.map((group) => (
                  <section key={group.slo ?? "untagged"} className="outcome-group">
                    <OutcomeHeading slo={group.slo} curriculum={board.curriculum} />
                    {group.tasks.map((task) => (
                      <TaskSection
                        key={task.task_id}
                        task={task}
                        curriculum={board.curriculum}
                      />
                    ))}
                  </section>
                ))
              )
            ) : filtered.length === 0 ? (
              <div className="notice">
                <strong>Nothing matches that.</strong> No task in the catalogue
                matches this filter. <Link href="/leaderboard">Show everything measured</Link>.
              </div>
            ) : (
              <>
                <p className="muted results-meta">
                  {filtered.length} task{filtered.length === 1 ? "" : "s"}
                  {filterActive ? " match this filter" : " measured so far"}.
                </p>
                <TaskTable groups={groups} curriculum={board.curriculum} />
              </>
            )}
          </section>
        </>
      )}
    </>
  );
}
