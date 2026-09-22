import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { getLeaderboard } from "@/lib/api";
import { generalClasses } from "@/lib/general-classes";
import { slugify } from "@/lib/explore";
import { ResultsUnavailable } from "@/components/service-unavailable";

export const dynamic = "force-dynamic";

/** Core classes without an owning major still have a stable, honest destination. */
export default async function GeneralClassPage({ params }: { params: Promise<{ course: string }> }) {
  const { course } = await params;
  let board;
  try { board = await getLeaderboard(); }
  catch (cause) { return <ResultsUnavailable what="this class" singular retryHref={`/classes/${encodeURIComponent(course)}`} cause={cause} />; }
  const row = generalClasses(board).find((entry) => slugify(entry.code) === course);
  if (!row) notFound();
  if (row.href.startsWith("/explore/")) redirect(row.href);
  const coverage = board.curriculum.coverage.find((entry) => entry.course === row.code)!;
  const outcomes = board.curriculum.outcomes.filter((entry) => entry.id in coverage.outcomes);
  return <article className="faculty-methodology">
    <Link href="/" style={{ color: "inherit" }}>← General classes</Link>
    <h1>{row.code} · {row.title}</h1>
    <h2>Not measured yet</h2>
    <p>This class is in the shared core. No course-specific benchmark results are available.</p>
    <details><summary>Published learning outcomes</summary>
      <ul>{outcomes.map((outcome) => <li key={outcome.id}>{outcome.title}{!outcome.text_benchmarkable ? " — Not text-measurable" : ""}</li>)}</ul>
    </details>
  </article>;
}
