import Link from "next/link";

import { GlossaryPanel, Term } from "@/components/glossary";
import { HowToRead, ReadStep } from "@/components/how-to-read";
import { getIntakeQuestions } from "@/lib/api";
import { RECOMMEND_TERMS } from "@/lib/glossary";
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

      {/* ⚠ THE ANXIETIES COME FIRST, BEFORE THE FIRST QUESTION. A professor who
          has never used a chatbot and is about to be asked eleven questions by
          a website wants to know three things straight away: how long this
          takes, whether they need to know anything to answer, and what happens
          to what they type. Answering those before question one is what buys
          the patience for question two. */}
      <HowToRead title="A few plain questions, then an answer for your situation.">
        {/* ⚠ THREE STEPS, NOT FOUR, AND THE CUT WAS THE RIGHT CALL. A fourth
            step here said "nothing you type is stored" — which the card
            directly below already says, in its own words. Stacking a panel, a
            card and a glossary in front of question one is exactly the wall
            that makes a busy professor close the tab, and the sprint note
            behind this flow is explicit that a fixed multi-question form is
            what it was designed to avoid. The one thing that step said and the
            card does not — do not paste student work — moved into step one,
            where it is more use anyway. */}
        <ReadStep n={1} heading="No AI knowledge needed">
          Every question is about your teaching or your research, not about
          technology. There is no wrong answer, and &ldquo;I&rsquo;m not
          sure&rdquo; is a real option — we handle it by giving you the cautious
          answer rather than the optimistic one. You will never be asked to paste
          in student work, and you should not.
        </ReadStep>
        <ReadStep n={2} heading="About two minutes, one question at a time">
          Roughly ten questions, and you will not see all of them — the ones you
          get depend on your earlier answers. Each says why it is being asked,
          because a question that changes nothing does not deserve your time.
        </ReadStep>
        <ReadStep n={3} heading="You may get a refusal, and that is the product">
          If we have not measured enough to answer well, we will say exactly what
          is missing instead of guessing. A confident answer we cannot back is
          worth less to you than an honest gap.
        </ReadStep>
      </HowToRead>

      <div className="card">
        <p style={{ marginTop: 0 }}>
          &ldquo;What&rsquo;s the best AI?&rdquo; has no useful answer, so we
          will ask you some questions first. Each one is here because it{" "}
          <em>changes</em> the recommendation — and each says why. If we still
          do not have enough, we will say what is missing rather than guess.
        </p>
        <p className="muted" style={{ marginBottom: 0 }}>
          Nothing you answer here is stored. Every recommendation links back to
          the benchmark <Term id="run">runs</Term> behind it, which you can read
          at <Link href="/leaderboard">the leaderboard</Link>.
        </p>
      </div>

      {/* ⚠ ABOVE THE QUESTIONS, NOT BELOW THEM. A few of the questions
          unavoidably name things a non-technical reader may not know — FERPA,
          an LMS, wiring something in with code. The place to put those
          definitions is where they will be met, not in a footer nobody scrolls
          to mid-form. */}
      <GlossaryPanel
        terms={RECOMMEND_TERMS}
        title="Any of these words unfamiliar?"
        intro="A few of the questions below mention things you may not have had reason to learn. None of them are complicated, and you can come back to this at any point."
      />

      <Intake questions={questions} />
    </>
  );
}
