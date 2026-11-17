import Link from "next/link";

import { ModelForm } from "@/components/admin/model-form";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { Credential, ModelFamily } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function NewModelPage() {
  const admin = await requireAdmin("/admin/models/new");
  const actor = getActor(admin);
  const [families, credentials] = await Promise.all([
    adminGet<ModelFamily[]>("/admin/model-families", actor).catch(() => [] as ModelFamily[]),
    adminGet<Credential[]>("/admin/credentials", actor).catch(() => [] as Credential[]),
  ]);
  return (
    <>
      <Link href="/admin/models" className="back">
        ← Models
      </Link>
      <h1>Add a model</h1>
      <p className="adm-lede">New models start switched off, so nothing is launched against them until you are ready.</p>
      <ModelForm model={null} families={families} credentials={credentials} />
    </>
  );
}
