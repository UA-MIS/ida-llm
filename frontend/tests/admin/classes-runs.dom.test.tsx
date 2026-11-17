/**
 * Classes, units and the run launcher against the fake API. The claims that
 * matter: a family already in another unit cannot be picked, removing a
 * family a unit still uses is explained, and money is never spent past the
 * ceiling without the admin typing the figure.
 */

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const refresh = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh, replace }), usePathname: () => "/admin/classes" }));

import { ClassFamilies, UnitEditor } from "@/components/admin/class-editor";
import { ConfirmSpend, RunLauncher, spendFigure } from "@/components/admin/run-launcher";
import { StatusBadge } from "@/components/admin/run-bits";
import { entityHref, runStatus } from "@/lib/admin/format";

import { createFakeAdminApi, sampleClass, sampleModel, sampleTaskFamily, sampleUnit } from "./fake-api";

let fake: ReturnType<typeof createFakeAdminApi>;
beforeEach(() => {
  fake = createFakeAdminApi();
  vi.stubGlobal("fetch", fake.fetch);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  push.mockReset();
  refresh.mockReset();
  replace.mockReset();
});

const families = [
  sampleTaskFamily({ key: "a", title: "Family A" }),
  sampleTaskFamily({ key: "b", title: "Family B" }),
  sampleTaskFamily({ key: "c", title: "Family C", unit: { course: "OM 300", key: "x" } }),
];

describe("status and links", () => {
  it("labels cancelled like failed", () => {
    expect(runStatus("cancelled")).toEqual({ label: "Cancelled", tone: "bad" });
    expect(runStatus("failed").tone).toBe("bad");
    render(<StatusBadge status="cancelled" />);
    expect(screen.getByText("Cancelled").className).toContain("adm-badge-bad");
  });

  it("links audit rows to their entity", () => {
    expect(entityHref("task", "quiz/l1 add")).toBe("/admin/material/tasks/quiz/l1%20add");
    expect(entityHref("class", "MIS 200")).toBe("/admin/classes/MIS%20200");
    expect(entityHref("auth", "x")).toBeNull();
  });
});

describe("UnitEditor", () => {
  it("disables families already in another unit, in this class or another", () => {
    const klass = sampleClass({
      task_families: ["a", "b", "c"],
      units: [sampleUnit({ id: "u1", n: 1, title: "Intro", families: ["a"] })],
    });
    render(<UnitEditor klass={klass} families={families} />);
    fireEvent.click(screen.getByRole("button", { name: "Add a unit" }));
    const box = (name: RegExp) => screen.getByRole("checkbox", { name }) as HTMLInputElement;
    expect(box(/Family A/).disabled).toBe(true);
    expect(screen.getByText(/In unit 1: Intro/)).toBeTruthy();
    expect(box(/Family B/).disabled).toBe(false);
    expect(box(/Family C/).disabled).toBe(true);
    expect(screen.getByText(/In a unit of OM 300/)).toBeTruthy();
  });

  it("lets a unit keep its own families while editing", () => {
    const klass = sampleClass({ task_families: ["a", "b"], units: [sampleUnit({ id: "u1", families: ["a"] })] });
    render(<UnitEditor klass={klass} families={families} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const a = screen.getByRole("checkbox", { name: /Family A/ }) as HTMLInputElement;
    expect(a.disabled).toBe(false);
    expect(a.checked).toBe(true);
  });

  it("shows the API's refusal next to the families when the picture was stale", async () => {
    // Another admin put family b in a unit after this page loaded.
    fake.state.classes = [sampleClass({ task_families: ["a", "b"], units: [sampleUnit({ id: "u9", key: "other", families: ["b"] })] })];
    const stale = sampleClass({ task_families: ["a", "b"], units: [] });
    render(<UnitEditor klass={stale} families={families} />);
    fireEvent.click(screen.getByRole("button", { name: "Add a unit" }));
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "Databases" } });
    fireEvent.change(screen.getByLabelText(/^Short id/), { target: { value: "databases" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Family B/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add unit" }));
    expect(await screen.findByText("already in unit other")).toBeTruthy();
    expect(fake.calls.at(-1)).toMatchObject({ method: "POST", path: "/classes/MIS%20200/units", body: { n: 1, families: ["b"] } });
  });

  it("shows an empty state", () => {
    render(<UnitEditor klass={sampleClass()} families={families} />);
    expect(screen.getByText("This class has no units yet")).toBeTruthy();
  });
});

describe("ClassFamilies", () => {
  it("locks a family a unit uses, and explains the API's conflict", async () => {
    const klass = sampleClass({ task_families: ["a", "b"], units: [sampleUnit({ families: ["a"] })] });
    fake.state.classes = [{ ...klass, units: [sampleUnit({ families: ["a", "b"] })] }]; // server knows b is in a unit too
    render(<ClassFamilies klass={klass} families={families} />);
    expect((screen.getByRole("checkbox", { name: /Family A/ }) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /Family B/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save task families" }));
    expect(await screen.findByText(/still uses a family you removed/)).toBeTruthy();
    expect(fake.calls[0]).toMatchObject({ method: "PUT", path: "/classes/MIS%20200/task-families", ifMatch: "1", body: { families: ["a"] } });
  });
});

describe("spending confirmation", () => {
  it("rounds the figure up to the cent, so typing it always covers the estimate", () => {
    expect(spendFigure(25.001)).toBe("25.01");
    expect(spendFigure(30)).toBe("30.00");
    expect(spendFigure(0.4 + 0.2)).toBe("0.60");
  });

  it("ConfirmSpend asks for the exact figure", () => {
    const onChange = vi.fn();
    const est = { runs: 1, samples: 5, est_usd_high: 30, includes_judge: false, pairs: [], warnings: [], caps: { max_runs: 50, max_samples: 2000, max_estimated_usd: 25 }, needs_confirmation: true };
    const { rerender } = render(<ConfirmSpend estimate={est} value="" onChange={onChange} />);
    expect(screen.getByText(/more than the \$25.00 limit/)).toBeTruthy();
    rerender(<ConfirmSpend estimate={est} value="29" onChange={onChange} />);
    expect(screen.getByText("Type exactly 30.00.")).toBeTruthy();
  });
});

describe("RunLauncher", () => {
  const models = [
    sampleModel({ key: "cheap", display_name: "Cheap" }),
    sampleModel({ key: "pricey", display_name: "Pricey" }),
    sampleModel({ key: "luna", display_name: "Luna", tags: ["testing-only"] }),
    sampleModel({ key: "off", display_name: "Off", enabled: false }),
  ];
  const fams = [sampleTaskFamily({ key: "quiz", title: "Quiz" })];

  beforeEach(() => {
    fake.state.models = models;
  });

  async function choose(...names: string[]) {
    for (const n of names) fireEvent.click(screen.getByRole("checkbox", { name: new RegExp(n) }));
  }

  it("offers only enabled models and estimates before launching", async () => {
    render(<RunLauncher models={models} families={fams} />);
    expect(screen.queryByRole("checkbox", { name: /Off/ })).toBeNull();
    const launch = () => screen.getByRole("button", { name: /^Launch/ }) as HTMLButtonElement;
    expect(launch().disabled).toBe(true);
    await choose("Cheap", "Quiz");
    await screen.findByText("$0.40");
    expect(launch().disabled).toBe(false);
    fireEvent.click(launch());
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/sweeps/sweep-1?launched=1"));
    expect(fake.state.launches[0]).toMatchObject({ model_keys: ["cheap"], family_keys: ["quiz"] });
    expect(fake.state.launches[0]!.confirm_spend_usd).toBeUndefined();
  });

  it("will not launch past the ceiling until the figure is typed", async () => {
    render(<RunLauncher models={models} families={fams} />);
    await choose("Pricey", "Quiz");
    await screen.findByText("Confirm the spending");
    const launch = screen.getByRole("button", { name: /^Launch/ }) as HTMLButtonElement;
    expect(launch.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Type 30.00 to confirm"), { target: { value: "3.00" } });
    expect(launch.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Type 30.00 to confirm"), { target: { value: "$30.00" } });
    expect(launch.disabled).toBe(false);
    fireEvent.click(launch);
    await waitFor(() => expect(fake.state.launches).toHaveLength(1));
    expect(fake.state.launches[0]!.confirm_spend_usd).toBe(30);
  });

  it("always asks for confirmation for a testing-only model", async () => {
    render(<RunLauncher models={models} families={fams} />);
    await choose("Luna", "Quiz");
    expect(await screen.findByText(/includes a model that always needs confirmation/)).toBeTruthy();
  });

  it("clears the typed figure when the selection changes", async () => {
    render(<RunLauncher models={models} families={fams} />);
    await choose("Pricey", "Quiz");
    fireEvent.change(await screen.findByLabelText("Type 30.00 to confirm"), { target: { value: "30.00" } });
    await choose("Cheap");
    const typed = await screen.findByLabelText("Type 30.40 to confirm");
    expect((typed as HTMLInputElement).value).toBe("");
  });

  it("refuses an over-cap launch outright", async () => {
    const big = [...models, sampleModel({ key: "huge", display_name: "Huge" })];
    fake.state.models = big;
    render(<RunLauncher models={big} families={fams} />);
    await choose("Huge", "Quiz");
    expect(await screen.findByText(/more than one launch is allowed to do/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /^Launch/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("says what to do when no model is enabled", () => {
    render(<RunLauncher models={[models[3]!]} families={fams} />);
    expect(screen.getByText("No models are switched on")).toBeTruthy();
  });

  it("debounces: one estimate for a burst of clicks", async () => {
    vi.useFakeTimers();
    render(<RunLauncher models={models} families={fams} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Quiz/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Cheap/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Luna/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Luna/ }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(fake.calls.filter((c) => c.path === "/runs/estimate")).toHaveLength(1);
  });
});
