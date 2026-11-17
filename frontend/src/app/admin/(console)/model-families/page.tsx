import { LoadError } from "@/components/admin/load-error";
import { ModelFamiliesManager } from "@/components/admin/model-families";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { ModelFamily } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function ModelFamiliesPage() {
  const admin = await requireAdmin("/admin/model-families");
  let families: ModelFamily[];
  try {
    families = await adminGet<ModelFamily[]>("/admin/model-families", getActor(admin));
  } catch (error) {
    return (
      <>
        <h1>Model families</h1>
        <LoadError error={error} retryHref="/admin/model-families" />
      </>
    );
  }
  return (
    <>
      <h1>Model families</h1>
      <p className="adm-lede">A family groups the versions of one model, so the public site shows them as a single row with the newest first.</p>
      <ModelFamiliesManager families={families} />
    </>
  );
}
