/**
 * The models, families and API-keys screens, rendered against the fake API.
 * What matters to non-technical staff: errors appear next to the field they
 * are about, a concurrent edit is explained rather than silently overwritten,
 * destructive actions ask first, and a stored key is never shown back.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const refresh = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh, replace }), usePathname: () => "/admin/models" }));

import { bffUrl, partitionIssues } from "@/lib/admin/client";
import { ConfirmButton } from "@/components/admin/confirm-button";
import { CredentialsManager } from "@/components/admin/credentials-manager";
import { ModelFamiliesManager } from "@/components/admin/model-families";
import { ModelForm, stateFromModel, toInput } from "@/components/admin/model-form";
import { ModelsTable } from "@/components/admin/models-table";

import { createFakeAdminApi, sampleModel } from "./fake-api";

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

const field = (label: RegExp | string) => screen.getByLabelText(label) as HTMLInputElement;

describe("client helpers", () => {
  it("maps API paths onto the BFF", () => {
    expect(bffUrl("/admin/models/x")).toBe("/admin/api/models/x");
    expect(() => bffUrl("/runs")).toThrow();
  });

  it("pins dotted and indexed issue paths to their field, the rest to the top", () => {
    const { byField, other } = partitionIssues(
      [
        { path: "serving.model_id", message: "a", severity: "error" },
        { path: "tags[0]", message: "b", severity: "error" },
        { path: "mystery", message: "c", severity: "error" },
      ],
      ["tags", "serving.model_id"],
    );
    expect(byField["serving.model_id"]?.[0]?.message).toBe("a");
    expect(byField.tags?.[0]?.message).toBe("b");
    expect(other.map((i) => i.message)).toEqual(["c"]);
  });
});

describe("ModelForm", () => {
  it("round-trips a model into the API shape, keeping fields it does not edit", () => {
    const m = sampleModel({ serving: { ...sampleModel().serving, extra: { reasoning: "low" }, revision: "r1" } });
    const { input, issues } = toInput(stateFromModel(m), m);
    expect(issues).toEqual([]);
    expect(input?.serving.extra).toEqual({ reasoning: "low" });
    expect(input?.serving.revision).toBe("r1");
    expect(input?.cost).toEqual({ input_usd_per_mtok: 0.25, output_usd_per_mtok: 2 });
    expect(input?.api_key_env).toBe("OPENAI_API_KEY");
    expect(input?.credential_ref).toBeNull();
  });

  it("catches obvious mistakes before sending, next to the field", async () => {
    render(<ModelForm model={null} families={[]} credentials={[]} />);
    fireEvent.change(field(/^Short id/), { target: { value: "Bad Key" } });
    fireEvent.change(field(/Timeout/), { target: { value: "soon" } });
    fireEvent.click(screen.getByRole("button", { name: "Add model" }));
    expect(await screen.findByText(/Use lowercase letters, digits and dashes/)).toBeTruthy();
    expect(screen.getByText("Enter a number.")).toBeTruthy();
    expect(field(/^Short id/).getAttribute("aria-invalid")).toBe("true");
    expect(fake.calls).toHaveLength(0);
  });

  it("shows the API's validation issue next to the matching field", async () => {
    const m = sampleModel();
    render(<ModelForm model={m} families={[]} credentials={[]} />);
    fireEvent.change(field(/Provider model id/), { target: { value: "rejected-by-api" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const msg = await screen.findByText("unknown model id for this provider");
    expect(msg.closest(".adm-field")?.querySelector("input")?.id).toBe("m-serving.model_id");
    expect(fake.calls[0]).toMatchObject({ method: "PUT", path: "/models/gpt-5-mini", ifMatch: "1" });
  });

  it("saves and comes back to the page with a confirmation that survives the reload", async () => {
    render(<ModelForm model={sampleModel()} families={[]} credentials={[]} />);
    fireEvent.change(field(/^Name/), { target: { value: "GPT-5 mini (OpenAI)" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin/models/gpt-5-mini?saved=1"));
    expect(fake.state.models[0]!.display_name).toBe("GPT-5 mini (OpenAI)");
  });

  it("explains a concurrent edit instead of overwriting it", async () => {
    fake.state.models[0]!.version = 2; // someone saved after this page loaded version 1
    render(<ModelForm model={sampleModel({ version: 1 })} families={[]} credentials={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Someone else changed this while you were editing")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload the latest version" })).toBeTruthy();
    expect(fake.state.models[0]!.version).toBe(2);
  });

  it("creates a model and goes to its page", async () => {
    render(<ModelForm model={null} families={[]} credentials={[]} />);
    fireEvent.change(field(/^Name/), { target: { value: "Mistral Large" } });
    fireEvent.change(field(/^Short id/), { target: { value: "mistral-large" } });
    fireEvent.change(field(/Web address/), { target: { value: "https://api.mistral.example/v1" } });
    fireEvent.change(field(/Provider model id/), { target: { value: "mistral-large-latest" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "none" } });
    fireEvent.click(screen.getByRole("button", { name: "Add model" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/models/mistral-large?created=1"));
    expect(fake.calls[0]).toMatchObject({ method: "POST", path: "/models", ifMatch: null });
    expect(fake.state.models.find((m) => m.key === "mistral-large")?.enabled).toBe(false);
  });
});

describe("ModelsTable", () => {
  it("toggles visibility with the row's version, and reorders", async () => {
    fake.state.models = [sampleModel({ key: "a", display_name: "A" }), sampleModel({ key: "b", display_name: "B", version: 4 })];
    render(<ModelsTable models={fake.state.models.map((m) => ({ ...m }))} families={[]} />);
    fireEvent.click(screen.getByLabelText("Show B on the public site"));
    await waitFor(() => expect(fake.calls[0]).toMatchObject({ method: "PATCH", path: "/models/b", ifMatch: "4", body: { hidden: true } }));
    fireEvent.click(screen.getByLabelText("Move B up"));
    await waitFor(() => expect(fake.calls[1]).toMatchObject({ method: "POST", path: "/models/reorder", body: { order: ["b", "a"] } }));
  });

  it("flags a model whose key is missing", () => {
    render(<ModelsTable models={[sampleModel({ key_present: false })]} families={[]} />);
    expect(screen.getByText("missing")).toBeTruthy();
  });
});

describe("ConfirmButton", () => {
  it("does nothing until the typed word matches", async () => {
    const onConfirm = vi.fn(async () => undefined);
    render(<ConfirmButton label="Archive" title="Archive it?" body="Body" confirmLabel="Yes, archive" typeToConfirm="gpt-5" onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    const confirm = screen.getByRole("button", { name: "Yes, archive", hidden: true }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "gpt-4" } });
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Type/), { target: { value: "gpt-5" } });
    expect(confirm.disabled).toBe(false);
    fireEvent.click(confirm);
    await waitFor(() => expect(onConfirm).toHaveBeenCalledOnce());
  });

  it("keeps the dialog open and shows the reason when the action fails", async () => {
    render(<ConfirmButton label="Delete" title="Delete?" body="" confirmLabel="Delete it" onConfirm={async () => "It is still in use."} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete it", hidden: true }));
    expect(await screen.findByText("It is still in use.")).toBeTruthy();
  });
});

describe("ModelFamiliesManager", () => {
  it("shows an empty state, and pins a server-side key error to the key field", async () => {
    fake.state.families = [];
    const { rerender } = render(<ModelFamiliesManager families={[]} />);
    expect(screen.getByText("No model families yet")).toBeTruthy();
    fake.state.families.push({ key: "taken", display_name: "Taken", member_keys: [], version: 1 });
    rerender(<ModelFamiliesManager families={[]} />);
    fireEvent.change(field(/^Name/), { target: { value: "Again" } });
    fireEvent.change(field(/^Short id/), { target: { value: "taken" } });
    fireEvent.click(screen.getByRole("button", { name: "Add family" }));
    const msg = await screen.findByText("that id is taken");
    expect(msg.closest(".adm-field")?.querySelector("input")?.id).toBe("fam-new-key");
  });

  it("will not offer to delete a family that still has models", () => {
    render(<ModelFamiliesManager families={[{ key: "f", display_name: "F", member_keys: ["a"], version: 1 }]} />);
    const row = screen.getByText("F").closest("tr")!;
    expect((within(row).getByRole("button", { name: "Delete" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("CredentialsManager", () => {
  // Deliberately not shaped like a real provider key.
  const PLANTED = "PLANTED-TEST-VALUE-not-a-real-key-42";

  it("sends the key once, clears the field, and never renders it", async () => {
    const { container } = render(<CredentialsManager credentials={[]} kekConfigured />);
    expect(screen.getByText("No API keys stored yet")).toBeTruthy();
    const secret = field(/^API key/);
    expect(secret.type).toBe("password");
    expect(secret.getAttribute("autocomplete")).toBe("off");
    fireEvent.change(field(/^Name/), { target: { value: "mistral-prod" } });
    fireEvent.change(field(/^Provider/), { target: { value: "Mistral" } });
    fireEvent.change(secret, { target: { value: PLANTED } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    expect(await screen.findByText(/The key itself is now hidden for good/)).toBeTruthy();
    expect(fake.state.receivedSecrets).toEqual([PLANTED]);
    expect(secret.value).toBe("");
    expect(container.innerHTML).not.toContain(PLANTED);
  });

  it("explains that keys cannot be saved without the encryption key", () => {
    render(<CredentialsManager credentials={[]} kekConfigured={false} />);
    expect(screen.getByText("New keys cannot be saved yet")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save key" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("will not delete a key a model uses", () => {
    render(
      <CredentialsManager
        kekConfigured
        credentials={[{ name: "k", provider: "P", kek_id: "k1", created_at: "2026-11-17T12:00:00Z", created_by: null, rotated_at: null, last_used_at: null, used_by_models: ["m"], version: 1 }]}
      />,
    );
    expect((screen.getByRole("button", { name: "Delete" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
