import { buildClasses, buildIndex, slugify } from "@/lib/explore";
import type { LeaderboardResponse } from "@/lib/types";

/** The published coverage map defines the shared core, not one major's list. */
export function generalClasses(board: LeaderboardResponse) {
  const index = buildIndex(board);
  const owned = new Map(index.majors.flatMap((major) =>
    buildClasses(board, major).map((course) => [course.code, { course, major }] as const),
  ));
  return board.curriculum.coverage.map((row) => {
    const owner = owned.get(row.course);
    return {
      code: row.course,
      title: owner?.course.title ?? row.title,
      href: owner
        ? `/explore/${encodeURIComponent(owner.major.slug)}/${encodeURIComponent(owner.course.slug)}`
        : `/classes/${encodeURIComponent(slugify(row.course))}`,
      status: owner?.course.status ?? "not_measured",
      demonstration: owner?.course.demonstration.any ?? false,
    };
  }).sort((a, b) => a.code.localeCompare(b.code, "en", { numeric: true }));
}
