import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RampLegend, ScoreCell } from "@/components/score-grid";
import type { MatrixCell } from "@/lib/matrix";

const measured: MatrixCell = {
  slo: "SLO2",
  status: "measured",
  score: 0.99,
  step: 5,
  confidence: "high",
  measuredTasks: 9,
  tasksAvailable: 10,
  scoredSamples: 9,
  runId: "run-1",
  reason: "A finished run measured this outcome.",
};

afterEach(() => cleanup());

describe("score grid display scales", () => {
  it("shows a measured score as a whole-number percentage with accessible units", () => {
    render(<ScoreCell cell={measured} rowLabel="Luna" columnLabel="Quantitative" scale={100} />);

    const cell = document.querySelector("td")!;
    expect(cell.querySelector(".cg-score")?.textContent).toContain("99");
    expect(cell.textContent).toContain("out of 100");
    expect(cell.textContent).not.toContain("99.00");
  });

  it("keeps an absent score as a dash rather than displaying zero", () => {
    render(
      <ScoreCell
        cell={{ ...measured, status: "not_measured", score: null, reason: "Nothing has run yet." }}
        rowLabel="Luna"
        columnLabel="Quantitative"
        scale={100}
      />,
    );

    expect(document.querySelector("td")?.textContent).toContain("–");
    expect(document.querySelector("td")?.textContent).not.toContain("0");
  });

  it("shows the confidence label in compact cells and omits task fractions", () => {
    render(<ScoreCell cell={measured} rowLabel="Luna" columnLabel="Quantitative" compact />);

    const cell = document.querySelector("td")!;
    expect(cell.querySelector(".cg-confidence-compact-label")?.textContent).toBe("High confidence");
    expect(cell.querySelector(".cg-sub")).toBeNull();
    expect(cell.querySelector(".sr-only")?.textContent).toMatch(/9 of 10 tasks measured/);
    expect(cell.querySelector(".sr-only")?.textContent).toMatch(/A finished run measured/);
  });

  it("retains the default 0–1 score and legend display", () => {
    render(
      <>
        <ScoreCell cell={measured} rowLabel="Luna" columnLabel="Quantitative" />
        <RampLegend />
      </>,
    );

    expect(document.querySelector(".cg-score")?.textContent).toBe("0.99");
    expect(document.querySelector(".cg-sub")?.textContent).toBe("9/10");
    expect(document.querySelector(".cg-legend-ends")?.textContent).toContain("0.0");
    expect(document.querySelector(".cg-legend-ends")?.textContent).toContain("1.0");
  });
});
