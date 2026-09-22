import Link from "next/link";

export const metadata = { title: "How we test — Capstone-IDA" };

export default function MethodologyPage() {
  return <article className="faculty-methodology">
    <h1>How we test</h1>
    <p>We evaluate AI responses to academic tasks and keep the evidence behind each result.</p>
    <details open><summary>What does the score mean?</summary>
      <p>Course exploration shows scores out of 100. Higher means better performance on the tasks tested. Scores are weighted by the number of scored samples; unmeasured tasks are not treated as zero.</p>
      <p>A model completing coursework does not establish that it improves student learning, tutors effectively, or grades fairly. These uses need separate evaluations.</p>
    </details>
    <details><summary>How much should I trust it?</summary>
      <p>Read confidence alongside the score. It reflects how responses were scored, how much evidence is available, and whether anything failed. A high score can have low confidence.</p>
      <p>Open a major, a class, and an outcome to inspect its tasks and responses. Demonstration data and test models are labeled separately.</p>
    </details>
    <details><summary>Why are some results blank?</summary>
      <p>“Not measured yet” means no results are available for that pairing. “Not text-measurable” means a text benchmark cannot measure the outcome. Neither is a zero score.</p>
    </details>
    <details><summary>How are responses evaluated?</summary>
      <p>Verifiable tasks compare responses with known answers. Subjective tasks use a written rubric and a model judge; those scores are judgments rather than objective answer checks.</p>
    </details>
    <p><Link href="/runs">Inspect evaluation runs →</Link></p>
  </article>;
}
