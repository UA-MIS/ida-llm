/**
 * The "proof" behind one UNIT of one class: what the unit covers, how every
 * model does on it as a one-column grid, then every task behind it with the runs
 * that produced the numbers.
 *
 * ⚠ NOTHING NEW IS COMPUTED HERE. The grid is `buildUnitMatrix` narrowed to one
 * unit — the same `aggregate()` and the same `classifyCell` the class page above
 * it drew from — and the task list is the existing `ModelResultCard` pointed at
 * the same run records. A second "what does this model score here" would
 * eventually disagree with the first, on the one page whose whole job is to be
 * checkable.
 *
 * ⚠ THE RECEIPT IS ONE CLICK DEEPER, DELIBERATELY. The mockup inlines every
 * question with the model's answer and the answer key. We keep the answer key
 * where `GET /tasks/{id}` already guards it — behind the run receipt each result
 * row opens — rather than publishing it on an SSO-gated-but-still-shared page.
 * Every score still opens to its proof: the model result card, then the run, then
 * the transcript. The unit's topics and its source sit here so the reader knows
 * what was asked before they open what was answered.
 */

import { Breadcrumbs, ExploreHelp, ModelFocus } from "./explore-chrome";
import { ExploreMatrixGrid } from "./explore-matrix";
import { ModelResultCard } from "./model-result-card";
import type { ClassUnit } from "@/lib/units";
import { buildUnitMatrix } from "@/lib/explore-matrix";
import type { ClassTile, MajorTile } from "@/lib/explore";
import type { LeaderboardResponse } from "@/lib/types";

export function UnitEvidence({
  board,
  klass,
  major,
  unit,
  wanted,
}: {
  board: LeaderboardResponse;
  klass: ClassTile;
  major: MajorTile;
  unit: ClassUnit;
  wanted: string | null;
}) {
  const matrix = buildUnitMatrix(board, klass, major.slug, unit.key);
  const focus = matrix.models.find((model) => model.model_key === wanted);
  const families = unit.families.filter((family) => klass.task_families.includes(family));
  const tasks = board.tasks.filter((task) => families.includes(task.family));
  const here = `/explore/${major.slug}/${klass.slug}/${encodeURIComponent(unit.key)}`;

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: "Majors", href: "/" },
          { label: major.name, href: `/explore/${major.slug}` },
          { label: klass.code, href: `/explore/${major.slug}/${klass.slug}` },
        ]}
        here={`Unit ${unit.n}`}
      />
      <ExploreHelp explain="One unit of this class, opened. The table is how each model reads on it; the tasks below are what produced those numbers, and every row opens the run behind it — the prompts, the answers and how they were marked." />

      {matrix.demonstration.any ? <div className="notice">{matrix.demonstration.notice}</div> : null}

      <section className="hero">
        <p className="xp-kicker">
          {klass.code} · Unit {unit.n}
        </p>
        <h2 className="xp-title">{unit.title}</h2>
        <p className="subtitle">{unit.blurb}</p>
        {/* ⚠ WHAT THIS UNIT COVERS — content about the class, true whether or not
            anything has run, so it shows here just as it does on the class grid. */}
        <ul className="xp-chips" aria-label="What this unit covers">
          {unit.covers.map((topic) => (
            <li key={topic} className="xp-chip">
              {topic}
            </li>
          ))}
        </ul>
        {unit.source ? (
          <p className="xp-source muted">Source: {unit.source}</p>
        ) : null}
      </section>

      {/* The unit's own words, when the results under it need a caveat the score
          cannot carry — e.g. a synthetic extension rather than an exam ingest.
          Quoted from the taxonomy, not paraphrased at the call site. */}
      {unit.caveat ? (
        <section className="panel">
          <div className="panel-head">
            <h2>How to read this</h2>
          </div>
          <p className="outcome-note">{unit.caveat}</p>
        </section>
      ) : null}

      {focus ? <ModelFocus displayName={focus.display_name} clearHref={here} /> : null}

      {tasks.length === 0 ? (
        <div className="empty">
          <h2>Not measured yet</h2>
          <p className="muted">
            No task in the catalogue is about this unit of {klass.code} yet, so nothing has
            been run for it. That is a gap in what we have authored, not a reading of any model.
          </p>
        </div>
      ) : (
        <>
          <ExploreMatrixGrid
            matrix={matrix}
            columnKind="Unit"
            overallLabel="All tasks"
            focusModel={focus?.model_key ?? null}
          />

          <section className="panel">
            <div className="panel-head">
              <h2>What was asked</h2>
              <p className="muted panel-note">
                Every row opens the run behind it — the prompts, the answers and how they
                were marked.
              </p>
            </div>
            {tasks.map((task) => (
              <div className="task-section" key={task.task_id}>
                <h3 className="task-title">{task.title}</h3>
                <p className="task-description muted">{task.description}</p>
                {task.results.length === 0 ? (
                  <p className="muted">
                    Not measured yet — no model has a finished run against this task.
                  </p>
                ) : (
                  <ul className="result-list">
                    {task.results.map((result, index) => (
                      <ModelResultCard
                        key={result.model_key}
                        result={result}
                        rank={index + 1}
                        isBest={result.model_key === task.best_model_key}
                      />
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </section>
        </>
      )}
    </>
  );
}
