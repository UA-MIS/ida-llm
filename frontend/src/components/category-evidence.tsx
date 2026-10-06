/**
 * The "why" behind one content category of one class: the single category as a
 * one-column grid, then every task behind it with the runs that produced the
 * numbers.
 *
 * ⚠ NOTHING NEW IS COMPUTED HERE. The grid is `buildCategoryMatrix` narrowed to
 * one category — the same `aggregate()` and the same `classifyCell` the class
 * page above it drew from — and the task list is the existing `ModelResultCard`
 * pointed at the same run records. A second "what does this model score here"
 * would eventually disagree with the first, on the one page whose whole job is
 * to be checkable.
 */

import { Breadcrumbs, ExploreHelp, ModelFocus } from "./explore-chrome";
import { ExploreMatrixGrid } from "./explore-matrix";
import { ModelResultCard } from "./model-result-card";
import type { ClassCategory } from "@/lib/categories";
import { buildCategoryMatrix } from "@/lib/explore-matrix";
import type { ClassTile, MajorTile } from "@/lib/explore";
import type { LeaderboardResponse } from "@/lib/types";

export function CategoryEvidence({
  board,
  klass,
  major,
  category,
  wanted,
}: {
  board: LeaderboardResponse;
  klass: ClassTile;
  major: MajorTile;
  category: ClassCategory;
  wanted: string | null;
}) {
  const matrix = buildCategoryMatrix(board, klass, major.slug, category.key);
  const focus = matrix.models.find((model) => model.model_key === wanted);
  const families = category.families.filter((family) => klass.task_families.includes(family));
  const tasks = board.tasks.filter((task) => families.includes(task.family));
  const here = `/explore/${major.slug}/${klass.slug}/${encodeURIComponent(category.key)}`;

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: "Majors", href: "/" },
          { label: major.name, href: `/explore/${major.slug}` },
          { label: klass.code, href: `/explore/${major.slug}/${klass.slug}` },
        ]}
        here={category.title}
      />
      <ExploreHelp explain="One part of this class, opened. The table is how each model reads on it; the tasks below are what produced those numbers, and every row opens the run behind it." />

      {matrix.demonstration.any ? <div className="notice">{matrix.demonstration.notice}</div> : null}

      <section className="hero">
        <h2 className="xp-title">{category.title}</h2>
        <p className="subtitle">{category.blurb}</p>
        <p className="muted">
          {klass.code} · {tasks.length} benchmark {tasks.length === 1 ? "task" : "tasks"}
        </p>
      </section>

      {/* The curriculum's own words, when the results under this category need a
          caveat the score cannot carry — e.g. a synthetic extension rather than
          an exam ingest. Quoted from the taxonomy, not paraphrased at the call
          site. */}
      {category.caveat ? (
        <section className="panel">
          <div className="panel-head">
            <h2>How to read this</h2>
          </div>
          <p className="outcome-note">{category.caveat}</p>
        </section>
      ) : null}

      {focus ? <ModelFocus displayName={focus.display_name} clearHref={here} /> : null}

      {tasks.length === 0 ? (
        <div className="empty">
          <h2>Not measured yet</h2>
          <p className="muted">
            No task in the catalogue is about this part of {klass.code} yet, so nothing has
            been run for it. That is a gap in what we have authored, not a reading of any model.
          </p>
        </div>
      ) : (
        <>
          <ExploreMatrixGrid
            matrix={matrix}
            columnKind="Category"
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
