import Link from "next/link";
import { getLeaderboard } from "@/lib/api";
import { generalClasses } from "@/lib/general-classes";
import { buildMajorMatrix } from "@/lib/explore-matrix";
import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";

export async function FacultyHome() {
  let board;
  try { board = await getLeaderboard(); }
  catch (cause) {
    return <ResultsUnavailable what="the course catalog and benchmark results" retryHref="/" cause={cause} />;
  }
  const matrix = buildMajorMatrix(board);
  const classes = generalClasses(board);
  return (
    <div className="faculty-home">
      <div className="faculty-title">
        <div><h1>AI benchmark results</h1><p>Compare tested performance by major or explore a general class.</p></div>
        <Link className="faculty-button" href="/recommend">Help me choose a model →</Link>
      </div>
      {matrix.demonstration.any && <p className="notice">{matrix.demonstration.notice}</p>}
      <section aria-labelledby="major-heading">
        <div className="faculty-section-heading"><h2 id="major-heading">By major</h2><p>Select a major to see its classes</p></div>
        {matrix.available ? <ExploreMatrixGrid matrix={matrix} columnKind="Major" overallLabel="All majors" compact /> :
          <p className="empty">{matrix.unavailable_reason ?? "The major catalog is not available."}</p>}
      </section>
      <section className="faculty-general" aria-labelledby="general-heading">
        <div className="faculty-section-heading"><div><h2 id="general-heading">General classes</h2><p>Shared business core</p></div><p>{classes.length} classes</p></div>
        {classes.length ? <div className="faculty-course-grid">{classes.map((course) => (
          <Link key={course.code} href={course.href} className="faculty-course">
            <span><strong>{course.code}</strong>{course.status === "measured" && <span className="faculty-available">{course.demonstration ? "Demonstration results" : "Results available"}</span>}<span className="faculty-course-name">{course.title}</span></span>
            <span aria-hidden="true">→</span>
          </Link>
        ))}</div> : <p className="empty">{board.curriculum.unavailable_reason ?? "The general class list has not been published."}</p>}
      </section>
    </div>
  );
}
