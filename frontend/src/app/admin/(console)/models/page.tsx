import Link from "next/link";

import { EmptyState } from "@/components/admin/form-bits";
import { LoadError } from "@/components/admin/load-error";
import { ModelsTable } from "@/components/admin/models-table";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { AdminModel, ModelFamily } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function ModelsPage({ searchParams }: { searchParams: Promise<{ show?: string; archived?: string }> }) {
  const admin = await requireAdmin("/admin/models");
  const params = await searchParams;
  const showArchived = params.show === "archived";
  const actor = getActor(admin);
  let models: AdminModel[];
  let families: ModelFamily[];
  try {
    [models, families] = await Promise.all([
      adminGet<AdminModel[]>(`/admin/models${showArchived ? "?include_archived=true" : ""}`, actor),
      adminGet<ModelFamily[]>("/admin/model-families", actor).catch(() => [] as ModelFamily[]),
    ]);
  } catch (error) {
    return (
      <>
        <h1>Models</h1>
        <LoadError error={error} retryHref="/admin/models" />
      </>
    );
  }

  return (
    <>
      <h1>Models</h1>
      <p className="adm-lede">
        The AI models the benchmark measures. Use the arrows to change the order they appear in, and the checkboxes to
        switch a model on or off, or hide it from the public site. Changes save immediately.
      </p>
      {params.archived === "done" ? (
        <p role="status" className="adm-panel adm-panel-ok">
          The model was archived. Its past results are kept.
        </p>
      ) : null}
      <div className="adm-toolbar">
        <Link href="/admin/models/new" className="adm-btn adm-btn-primary">
          Add a model
        </Link>
        <Link href={showArchived ? "/admin/models" : "/admin/models?show=archived"} className="adm-btn adm-btn-quiet">
          {showArchived ? "Hide archived models" : "Show archived models"}
        </Link>
      </div>
      {models.length ? (
        <ModelsTable models={models} families={families} />
      ) : (
        <EmptyState title="No models yet">
          <p>Add the first model to start measuring it.</p>
        </EmptyState>
      )}
    </>
  );
}
