/**
 * The content categories that define a class — the axis the class page now
 * shows in place of a Student Learning Outcome breakdown.
 *
 * ⚠ WHY A CLASS IS SHOWN BY CATEGORY, NOT BY SLO. An SLO (SLO2 Quantitative
 * Literacy, SLO9 General Business Knowledge) is the registrar's cross-programme
 * outcome vocabulary. It is the right axis for "how does a model do on an
 * outcome the whole college teaches" — and the wrong axis for a professor who
 * asked "what is MY class made of, and how does AI do on each part". A class is
 * made of CONTENT: the concepts, the frameworks, the skills the course actually
 * covers. Those are its categories. The SLO data stays intact and still groups
 * results internally (see `curriculum/slo.yaml` and `lib/explore.ts`); this file
 * is the presentation grouping the class page reads instead.
 *
 * ⚠ WHY THIS IS A FRONTEND DATA MODULE AND NOT A SERVED curriculum FILE. The two
 * things the registrar actually owns — which majors and classes exist
 * (`majors.yaml`), and which outcomes each class teaches (`slo.yaml`) — are
 * served by the API precisely so no client transcribes a registrar's list. A
 * class's content CATEGORIES are not a registrar fact: they are our editorial
 * analysis of what the ingested material covers (the same analysis recorded in
 * `tasks/mis200-exam1-mapping.md`, provenance `synthetic`). The class-page axis
 * this replaces — assignment formats — was already a frontend data map for the
 * same reason. Keeping categories here keeps that boundary honest: a served
 * taxonomy would dress our content analysis up as the catalog. It is still
 * data-driven and still generalises the way `majors.yaml` does: a second class
 * gets categories by adding a row below, never by editing a component.
 *
 * ⚠ TWO INVARIANTS THAT KEEP A CATEGORY FROM FABRICATING A SCORE:
 *
 *   1. A CATEGORY MAPS TO TASK FAMILIES; A FAMILY MAPS TO EXACTLY ONE CATEGORY.
 *      Results are a (model, task) mean per family. If one family fed two
 *      categories, the SAME number would appear under both headings — the "one
 *      exam's score under a dozen courses" fabrication `lib/explore.ts` is built
 *      to prevent, one level down. So the family→category map is a partition:
 *      every family of a class lands in one and only one category.
 *   2. A CATEGORY'S FAMILIES ARE A SUBSET OF THE CLASS'S OWN `task_families`.
 *      A category can only ever show results that are already attributable to
 *      the class. `categories.test.ts` pins both invariants against
 *      `curriculum/majors.yaml`.
 *
 * A category with no families is honest, not broken: it is a part of the class
 * nothing has been authored for yet, and it reads "not measured yet" — never a
 * blank, never a zero. The exam was 32 forced-choice/fill-in items across five
 * content areas; three of those areas have a task family today and two do not.
 */

/** One content category of one class. The class page's column; the evidence
 * level's subject. */
export interface ClassCategory {
  /** URL segment and React key. Stable; the title may be reworded. */
  key: string;
  /** What the professor reads at the top of the column. */
  title: string;
  /** One line under it: what this part of the class is. */
  blurb: string;
  /**
   * The task families whose results define this category. Empty means nothing
   * has been authored for this part of the class yet — "not measured yet", by
   * construction, not by a remembered caveat.
   */
  families: string[];
  /**
   * An honesty caveat shown on the category's evidence page, when the results
   * under it need one the score alone cannot carry — e.g. that they come from a
   * synthetic extension rather than an ingest of the real instrument. Absent
   * when the category is exactly what it looks like.
   */
  caveat?: string;
}

/**
 * The taxonomy, keyed by course code — the same join key `majors.yaml` and
 * `slo.yaml` use. A class absent here has no category breakdown and the class
 * page says so rather than inventing one.
 *
 * MIS 200 — the one populated class in the product. Its five categories are the
 * five content areas of the real Exam 1, as analysed in
 * `tasks/mis200-exam1-mapping.md`. The mapping of the three authored families:
 *
 *   mis200-is-concepts        → IS concepts & business models   (SLO9 items)
 *   mis200-spreadsheet-formulas → Spreadsheet & Excel skills     (SLO2 items)
 *   mis200-is-problem-solving → Competitive-strategy frameworks  (SLO1 extension)
 *
 * ⚠ THE is-problem-solving PLACEMENT IS A JUDGEMENT CALL, RECORDED HERE. That
 * family is not an Exam 1 ingest — it is a synthetic extension raising the
 * course's technology-investment material to SLO1's problem-solving level
 * (appraise an initiative, recommend a course of action, say what would change
 * it). Of the five content areas, strategic appraisal of a technology
 * initiative sits closest to competitive-strategy frameworks, so that is where
 * it is filed. Its evidence page carries the synthetic-extension caveat so the
 * number is not misread as exam-derived.
 *
 * ⚠ TWO CATEGORIES READ "NOT MEASURED YET" AND THAT IS CONSERVATIVE, NOT WRONG.
 * Platform & network economics and Levels of IS use have no dedicated family,
 * so they are empty. Some items inside `mis200-is-concepts` do touch those
 * topics, but that family carries one aggregate score; splitting it across three
 * categories would print one number three times (invariant 1). Separating those
 * areas honestly needs task- or sample-level content tags — a follow-up, noted
 * in the exam-mapping doc.
 */
const TAXONOMY: Record<string, ClassCategory[]> = {
  "MIS 200": [
    {
      key: "is-concepts-business-models",
      title: "IS concepts & business models",
      blurb:
        "The vocabulary of information systems and the business models they enable — the breadth the first course is built on.",
      families: ["mis200-is-concepts"],
    },
    {
      key: "competitive-strategy",
      title: "Competitive-strategy frameworks",
      blurb:
        "Appraising a proposed technology initiative and recommending a course of action — strategy applied to an IS investment.",
      families: ["mis200-is-problem-solving"],
      caveat:
        "These items are a synthetic extension, not an ingest of Exam 1. Every item on that paper is forced-choice, and MIS 200 reinforces problem-solving without examining it there; this raises the course's technology-investment material to the level of appraising and recommending. A score here is not comparable to a student cohort's Exam 1 performance, because no such performance exists.",
    },
    {
      key: "platform-network-economics",
      title: "Platform & network economics",
      blurb:
        "Direct and indirect network effects, and what a platform does and does not do.",
      families: [],
    },
    {
      key: "levels-of-is-use",
      title: "Levels of IS use in organizations",
      blurb:
        "Strategic, tactical and operational use of information systems — decided by the scope and horizon of a decision, not the seniority of whoever makes it.",
      families: [],
    },
    {
      key: "spreadsheet-excel",
      title: "Spreadsheet & Excel skills",
      blurb:
        "Authoring formulas over a supplied layout — the one content area MIS 200 is a programme assessment point for.",
      families: ["mis200-spreadsheet-formulas"],
    },
  ],
};

/** The categories a class defines, in presentation order. Empty for a class
 * with no taxonomy yet — the class page renders that honestly. */
export function categoriesFor(course: string): ClassCategory[] {
  return TAXONOMY[course] ?? [];
}

/** Does this class have a content-category breakdown at all? */
export function hasCategories(course: string): boolean {
  return (TAXONOMY[course]?.length ?? 0) > 0;
}

/** One category of one class, by its URL key. Case-insensitive on the key so a
 * hand-typed URL still resolves. */
export function findCategory(course: string, key: string): ClassCategory | undefined {
  const wanted = key.toLowerCase();
  return categoriesFor(course).find((category) => category.key.toLowerCase() === wanted);
}

/** The category's title, or the raw key when the class defines no such
 * category — never a thrown error on a bad URL segment. */
export function categoryTitle(course: string, key: string): string {
  return findCategory(course, key)?.title ?? key;
}

/** Every course code that carries a category taxonomy. For tests and guards. */
export function coursesWithCategories(): string[] {
  return Object.keys(TAXONOMY);
}
