import Link from "next/link";

import { TaskFamilyForm } from "@/components/admin/task-family-form";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { SystemInfo } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function NewTaskFamilyPage() {
  const admin = await requireAdmin("/admin/material/families/new");
  const system = await adminGet<SystemInfo>("/admin/system", getActor(admin)).catch(() => null);
  return (
    <>
      <Link href="/admin/material" className="back">
        ← Course material
      </Link>
      <h1>New task family</h1>
      <TaskFamilyForm family={null} privateAllowed={system?.tasks_spec_gated === true} />
    </>
  );
}
