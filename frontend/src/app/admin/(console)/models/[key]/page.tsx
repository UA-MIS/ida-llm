import Link from "next/link";

import { LoadError } from "@/components/admin/load-error";
import { ModelActions } from "@/components/admin/model-actions";
import { ModelForm } from "@/components/admin/model-form";
import { adminGet } from "@/lib/admin/api";
import { formatWhen } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { AdminModel, Credential, ModelFamily } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function EditModelPage({
  params,
  searchParams,
}: {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ created?: string; saved?: string }>;
}) {
  const { key } = await params;
  const admin = await requireAdmin(`/admin/models/${encodeURIComponent(key)}`);
  const actor = getActor(admin);
  const sp = await searchParams;
  const created = sp.created === "1";
  const saved = sp.saved === "1";
  let model: AdminModel;
  let families: ModelFamily[];
  let credentials: Credential[];
  try {
    [model, families, credentials] = await Promise.all([
      adminGet<AdminModel>(`/admin/models/${encodeURIComponent(key)}`, actor),
      adminGet<ModelFamily[]>("/admin/model-families", actor).catch(() => [] as ModelFamily[]),
      adminGet<Credential[]>("/admin/credentials", actor).catch(() => [] as Credential[]),
    ]);
  } catch (error) {
    return (
      <>
        <Link href="/admin/models" className="back">
          ← Models
        </Link>
        <h1>Model</h1>
        <LoadError error={error} retryHref={`/admin/models/${encodeURIComponent(key)}`} />
      </>
    );
  }

  return (
    <>
      <Link href="/admin/models" className="back">
        ← Models
      </Link>
      <h1>{model.display_name}</h1>
      <p className="adm-lede">
        <span className="mono">{model.key}</span>
        {model.updated_by ? ` · last changed by @${model.updated_by}` : ""} · {formatWhen(model.updated_at)}
      </p>
      {created ? (
        <p role="status" className="adm-panel adm-panel-ok">
          Model added. It is switched {model.enabled ? "on" : "off"}; use “Test connection” below to check it can be reached.
        </p>
      ) : null}
      {saved ? (
        <p role="status" className="adm-panel adm-panel-ok">
          Changes saved. They reach the public site within a few seconds.
        </p>
      ) : null}
      <ModelForm key={model.version} model={model} families={families} credentials={credentials} />
      <ModelActions model={model} />
    </>
  );
}
