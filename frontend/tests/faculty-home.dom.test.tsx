import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { board, result, task, trust } from "./fixtures";
import { generalClasses } from "@/lib/general-classes";

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ getLeaderboard, ApiError: class extends Error {} }));
const { FacultyHome } = await import("@/components/faculty-home");

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function sampleBoard() {
  const data = board([task({ has_results: true, results: [result({
    mean_score: .9958, trust: trust({ confidence: "low", confidence_label: "Low confidence" }),
  })] })]);
  data.curriculum = { ...data.curriculum, coverage: [
    ...data.curriculum.coverage,
    { course: "LGS 200", title: "Legal Environment of Business", outcomes: { SLO4: "R" } },
  ] };
  return data;
}

describe("faculty homepage", () => {
  it("shows every shared-core class, with catalog titles and correct destinations", async () => {
    const data = sampleBoard();
    getLeaderboard.mockResolvedValue(data);
    const { container } = render(await FacultyHome());
    expect(container.querySelectorAll(".faculty-course").length).toBe(data.curriculum.coverage.length);
    expect(screen.getByRole("link", { name: /MIS 200.*Fundamentals of Management Information Systems/ }).getAttribute("href"))
      .toBe("/explore/management-information-systems/mis-200");
    expect(screen.getByRole("link", { name: /LGS 200/ }).getAttribute("href")).toBe("/classes/lgs-200");
    const classes = generalClasses(data);
    expect(classes.find(c => c.code === "MIS 200")?.status).toBe("measured");
    expect(classes.find(c => c.code === "GBA 300")?.status).toBe("not_measured");
    expect(classes.find(c => c.code === "LGS 200")?.status).toBe("not_measured");
  });

  it("shows confidence beside whole scores without rounding a near-perfect result to 100", async () => {
    getLeaderboard.mockResolvedValue(sampleBoard());
    const { container } = render(await FacultyHome());
    expect(container.querySelector(".cg-score")?.textContent).toBe("99 out of 100");
    expect(container.querySelector(".cg-confidence-compact-label")?.textContent).toBe("Low confidence");
    expect(container.querySelector(".xp-summary")).toBeNull();
    expect(container.querySelector(".cg-col-overall")).toBeNull();
    expect(container.querySelector(".faculty-matrix-details")?.hasAttribute("open")).toBe(false);
  });

  it("keeps unmeasured data empty and distinguishes a failed service from an empty catalog", async () => {
    getLeaderboard.mockResolvedValue(board([]));
    const { container, unmount } = render(await FacultyHome());
    expect(container.querySelector(".cg-measured")).toBeNull();
    expect(screen.getByText("General classes")).toBeTruthy();
    unmount();
    getLeaderboard.mockRejectedValue(new Error("offline"));
    render(await FacultyHome());
    expect(screen.getByRole("link", { name: /try again/i }).getAttribute("href")).toBe("/");
    expect(screen.queryByText("0 classes")).toBeNull();
  });
});
