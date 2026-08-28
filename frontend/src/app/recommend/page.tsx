import Link from "next/link";

import { getIntakeQuestions } from "@/lib/api";
import { Intake } from "./intake";

/**
 * The recommendation flow.
 *
 * The question tree is fetched here, server-side, and handed to the client
 * component — so the questions the form asks are the same objects the engine
 * gates on, and adding a question is a change in exactly one Python file.
 */
export const dynamic = "force-dynamic";

export default async function RecommendPage() {
  const questions = await getIntakeQuestions();

  return (
    <>
      <p className="subtitle">
        Tell us your actual situation and we will tell you what to use — or tell
        you honestly that we do not know yet.
      </p>

      <div className="card">
        <p style={{ marginTop: 0 }}>
          &ldquo;What&rsquo;s the best AI?&rdquo; has no useful answer, so we
          will ask you some questions first. Each one is here because it{" "}
          <em>changes</em> the recommendation — and each says why. If we still
          do not have enough, we will say what is missing rather than guess.
        </p>
        <p className="muted" style={{ marginBottom: 0 }}>
          Nothing you answer here is stored. Every recommendation links back to
          the benchmark runs behind it, which you can read at{" "}
          <Link href="/">the results view</Link>.
        </p>
      </div>

      <Intake questions={questions} />
    </>
  );
}
