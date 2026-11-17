/**
 * The material screens against the fake API: families (with the private
 * gate), the task editor's three tabs, the question list, and the upload
 * check-then-save flow.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const refresh = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh, replace }), usePathname: () => "/admin/material" }));

import { NewTaskForm } from "@/components/admin/new-task-form";
import { TaskEditor } from "@/components/admin/task-editor";
import { TaskFamilyForm } from "@/components/admin/task-family-form";
import { UploadForm } from "@/components/admin/upload-form";

import { createFakeAdminApi, sampleTask, sampleTaskFamily } from "./fake-api";

let fake: ReturnType<typeof createFakeAdminApi>;
beforeEach(() => {
  fake = createFakeAdminApi();
  vi.stubGlobal("fetch", fake.fetch);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
  refresh.mockReset();
  replace.mockReset();
});

const input = (label: RegExp | string) => screen.getByLabelText(label) as HTMLInputElement;

describe("TaskFamilyForm", () => {
  it("blocks private material until the API says private tasks are protected", () => {
    render(<TaskFamilyForm family={null} privateAllowed={false} />);
    const radio = screen.getByRole("radio", { name: /Private/ }) as HTMLInputElement;
    expect(radio.disabled).toBe(true);
    expect(screen.getByText(/Not available yet/)).toBeTruthy();
  });

  it("allows private once gated", () => {
    render(<TaskFamilyForm family={null} privateAllowed />);
    expect((screen.getByRole("radio", { name: /Private/ }) as HTMLInputElement).disabled).toBe(false);
  });

  it("refuses a key the console's own routes would shadow", async () => {
    render(<TaskFamilyForm family={null} privateAllowed={false} />);
    fireEvent.change(input(/^Title/), { target: { value: "Uploads" } });
    fireEvent.change(input(/^Short id/), { target: { value: "upload" } });
    fireEvent.click(screen.getByRole("button", { name: "Create family" }));
    expect(await screen.findByText(/is reserved by the console/)).toBeTruthy();
    expect(fake.calls).toHaveLength(0);
  });

  it("creates a family and opens it", async () => {
    render(<TaskFamilyForm family={null} privateAllowed={false} />);
    fireEvent.change(input(/^Title/), { target: { value: "MIS 200: databases" } });
    fireEvent.change(input(/^Short id/), { target: { value: "mis200-databases" } });
    fireEvent.click(screen.getByRole("button", { name: "Create family" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/material/mis200-databases?created=1"));
    expect(fake.calls[0]).toMatchObject({ method: "POST", path: "/task-families", body: { key: "mis200-databases", provenance: "synthetic" } });
  });

  it("explains why a family in use cannot be archived", async () => {
    fake.state.taskFamilies = [sampleTaskFamily({ classes: ["MIS 200"] })];
    render(<TaskFamilyForm family={fake.state.taskFamilies[0]!} privateAllowed={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Archive this family" }));
    fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "quiz" } });
    fireEvent.click(screen.getByRole("button", { name: "Archive family", hidden: true }));
    expect(await screen.findByText("The family is used by MIS 200.")).toBeTruthy();
  });
});

describe("TaskEditor", () => {
  it("saves the details with the task's version and keeps the rest of the document", async () => {
    render(<TaskEditor task={sampleTask()} />);
    fireEvent.change(input(/^Title/), { target: { value: "Adding numbers" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText("Saved.");
    const put = fake.calls[0]!;
    expect(put).toMatchObject({ method: "PUT", path: "/tasks/quiz/l1-add", ifMatch: "1" });
    const sent = (put.body as { document: Record<string, unknown> }).document;
    expect(sent.title).toBe("Adding numbers");
    expect(sent.scorer).toEqual({ kind: "numeric_match", tolerance: 0.01, normalisation: { strip: true } });
    expect((sent.samples as unknown[]).length).toBe(2);
  });

  it("adds, edits and deletes questions, each with the latest version", async () => {
    render(<TaskEditor task={sampleTask()} />);
    fireEvent.click(screen.getByRole("tab", { name: /Questions/ }));
    expect(screen.getByText("2+2?")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Add a question" }));
    fireEvent.change(input("Question id"), { target: { value: "q3" } });
    fireEvent.change(input(/^Question$/), { target: { value: "5+5?" } });
    fireEvent.click(screen.getByRole("button", { name: "Add question" }));
    expect(await screen.findByText("Please fix the following:", { exact: false }).catch(() => null)).toBeNull();
    expect(await screen.findByText("Give the correct answer, so the answer can be checked automatically.")).toBeTruthy();
    fireEvent.change(input(/Correct answer/), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Add question" }));
    await screen.findByText("5+5?");
    expect(fake.calls.at(-1)).toMatchObject({ method: "POST", path: "/tasks/quiz/l1-add/samples", ifMatch: "1" });

    const row = screen.getByText("2+2?").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    fireEvent.change(input(/Correct answer/), { target: { value: "four" } });
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));
    await waitFor(() => expect(fake.calls.at(-1)).toMatchObject({ method: "PUT", path: "/tasks/quiz/l1-add/samples/q1", ifMatch: "2" }));

    const row2 = (await screen.findByText("3+4?")).closest("tr")!;
    fireEvent.click(within(row2).getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Delete question", hidden: true }).find((b) => b.closest("dialog")?.hasAttribute("open"))!);
    await waitFor(() => expect(fake.calls.at(-1)).toMatchObject({ method: "DELETE", path: "/tasks/quiz/l1-add/samples/q2", ifMatch: "3" }));
    await waitFor(() => expect(screen.queryByText("3+4?")).toBeNull());
  });

  it("pins the API's sample issue to the right field", async () => {
    // A verifiable sample with no target gets past the client only if the
    // client check is bypassed; simulate an API-side rule instead.
    render(<TaskEditor task={sampleTask({ kind: "subjective" })} />);
    fireEvent.click(screen.getByRole("tab", { name: /Questions/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add a question" }));
    fireEvent.change(input("Question id"), { target: { value: "e1" } });
    fireEvent.change(input(/^Question$/), { target: { value: "Write…" } });
    fake.state.tasks[0]!.kind = "verifiable"; // the server disagrees
    fireEvent.click(screen.getByRole("button", { name: "Add question" }));
    const msg = await screen.findByText("verifiable sample needs a target");
    expect(msg.closest(".adm-field")?.querySelector("input")?.id).toBe("s-target");
  });

  it("checks YAML and replaces the task only after a preview and a confirmation", async () => {
    render(<TaskEditor task={sampleTask()} />);
    fireEvent.click(screen.getByRole("tab", { name: "YAML" }));
    const editor = screen.getByLabelText("Task YAML") as HTMLTextAreaElement;
    expect(editor.value).toContain("id: quiz/l1-add");
    expect(editor.value).toContain("tolerance: 0.01");

    fireEvent.change(editor, { target: { value: editor.value + "\nBROKEN" } });
    fireEvent.click(screen.getByRole("button", { name: "Check for problems" }));
    expect(await screen.findByText("could not parse")).toBeTruthy();

    fireEvent.change(editor, { target: { value: editor.value.replace("\nBROKEN", "") } });
    fireEvent.click(screen.getByRole("button", { name: "Review and save…" }));
    expect(await screen.findByText(/1 question\(s\) added, 2 changed, 0 removed/)).toBeTruthy();
    expect(fake.state.stored).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Save this YAML" }));
    fireEvent.click(screen.getByRole("button", { name: "Replace task", hidden: true }));
    await waitFor(() => expect(fake.state.stored).toHaveLength(1));
    expect(fake.calls.filter((c) => c.path === "/material/upload").map((c) => (c.body as { mode: string; commit: boolean }))).toEqual([
      expect.objectContaining({ mode: "replace", commit: false }),
      expect.objectContaining({ mode: "replace", commit: true }),
    ]);
  });
});

describe("NewTaskForm", () => {
  it("pins API issues to the first question and tags", async () => {
    render(<NewTaskForm family="quiz" familyTitle="Quiz" />);
    fireEvent.change(input(/^Title/), { target: { value: "Leaky" } });
    fireEvent.change(input(/^Short id/), { target: { value: "l9-leak" } });
    fireEvent.change(input(/^Question$/), { target: { value: "What?" } });
    fireEvent.change(input(/^Correct answer/), { target: { value: "leak" } });
    fireEvent.change(input(/^Tags/), { target: { value: "quiz, slo:typo" } });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    const leak = await screen.findByText("target leaks into metadata");
    expect(leak.closest(".adm-field")?.querySelector("input")?.id).toBe("nt-sample_target");
    expect(screen.getByText("unknown slo tag").closest(".adm-field")?.querySelector("input")?.id).toBe("nt-tags");
  });

  it("creates a task and opens it", async () => {
    render(<NewTaskForm family="quiz" familyTitle="Quiz" />);
    fireEvent.change(input(/^Title/), { target: { value: "Subtracting" } });
    fireEvent.change(input(/^Short id/), { target: { value: "l2-sub" } });
    fireEvent.change(input(/^Question$/), { target: { value: "5-3?" } });
    fireEvent.change(input(/^Correct answer/), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/material/tasks/quiz/l2-sub?created=1"));
  });
});

describe("UploadForm", () => {
  const file = (text: string, name = "task.yaml") => new File([text], name, { type: "application/yaml" });

  it("refuses non-YAML and oversized files before sending anything", () => {
    render(<UploadForm maxBytes={10} />);
    fireEvent.change(input("Task file"), { target: { files: [file("x", "notes.txt")] } });
    expect(screen.getByText("Choose a .yaml or .yml file.")).toBeTruthy();
    fireEvent.change(input("Task file"), { target: { files: [file("x".repeat(2048))] } });
    expect(screen.getByText(/the limit is/)).toBeTruthy();
    expect(fake.calls).toHaveLength(0);
  });

  it("shows problems and stores nothing for a bad file", async () => {
    render(<UploadForm maxBytes={1024 * 1024} />);
    fireEvent.change(input("Task file"), { target: { files: [file("id: x\nBROKEN")] } });
    fireEvent.click(screen.getByRole("button", { name: "Check the file" }));
    expect(await screen.findByText("could not parse")).toBeTruthy();
    expect(screen.getByText(/Nothing was saved/)).toBeTruthy();
    expect(fake.state.stored).toHaveLength(0);
  });

  it("checks, then saves", async () => {
    render(<UploadForm maxBytes={1024 * 1024} />);
    fireEvent.change(input("Task file"), { target: { files: [file("id: quiz/l1-add\n")] } });
    fireEvent.click(screen.getByRole("button", { name: "Check the file" }));
    fireEvent.click(await screen.findByRole("button", { name: "Save as a new task" }));
    expect(await screen.findByText("Saved")).toBeTruthy();
    expect(fake.state.stored).toEqual(["id: quiz/l1-add\n"]);
  });
});
