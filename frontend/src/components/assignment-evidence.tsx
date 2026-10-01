import { Breadcrumbs, ExploreHelp, ModelFocus } from "./explore-chrome";
import { ExploreMatrixGrid } from "./explore-matrix";
import { ModelResultCard } from "./model-result-card";
import { assignmentFamilies, assignmentTitle, buildAssignmentMatrix } from "@/lib/explore-matrix";
import type { ClassTile, MajorTile } from "@/lib/explore";
import type { LeaderboardResponse } from "@/lib/types";

export function AssignmentEvidence({ board, klass, major, family, wanted }: {
  board: LeaderboardResponse; klass: ClassTile; major: MajorTile;
  family: string; wanted: string | null;
}) {
  const title = assignmentTitle(family);
  const matrix = buildAssignmentMatrix(board, klass, major.slug, family);
  const focus = matrix.models.find((model) => model.model_key === wanted);
  const families = assignmentFamilies(klass, family);
  const tasks = board.tasks.filter((task) => families.includes(task.family));
  const here = `/explore/${major.slug}/${klass.slug}/${encodeURIComponent(family)}`;
  return <>
    <Breadcrumbs trail={[
      { label: "Majors", href: "/explore" },
      { label: major.name, href: `/explore/${major.slug}` },
      { label: klass.code, href: `/explore/${major.slug}/${klass.slug}` },
    ]} here={title} />
    <ExploreHelp explain="Results for one assignment type. The tasks below show what was asked and link to the runs behind each score." />
    {matrix.demonstration.any ? <div className="notice">{matrix.demonstration.notice}</div> : null}
    <section className="hero">
      <h2 className="xp-title">{title}</h2>
      <p className="subtitle">{klass.code} ? {tasks.length} benchmark tasks</p>
      {families.includes("mis200-is-problem-solving") ? <p className="muted">Synthetic problem-solving cases extending beyond Exam 1; these were not assessed by that exam.</p> : null}
    </section>
    {focus ? <ModelFocus displayName={focus.display_name} clearHref={here} /> : null}
    <ExploreMatrixGrid matrix={matrix} columnKind="Assignment type" overallLabel="All tasks" focusModel={focus?.model_key ?? null} />
    <section className="panel">
      <div className="panel-head"><h2>What was asked</h2></div>
      {tasks.length === 0 ? <p>No tasks have been added for this assignment type yet.</p> : null}
      {tasks.map((task) => <div className="task-section" key={task.task_id}>
        <h3 className="task-title">{task.title}</h3>
        <p className="task-description muted">{task.description}</p>
        {task.results.length === 0 ? <p className="muted">Not measured ? no model has a finished run against this task.</p> :
          <ul className="result-list">{task.results.map((result, index) =>
            <ModelResultCard key={result.model_key} result={result} rank={index + 1} isBest={result.model_key === task.best_model_key} />
          )}</ul>}
      </div>)}
    </section>
  </>;
}
