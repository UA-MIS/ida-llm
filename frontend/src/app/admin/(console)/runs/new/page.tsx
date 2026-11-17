import Link from "next/link";

import { LoadError } from "@/components/admin/load-error";
import { RunLauncher } from "@/components/admin/run-launcher";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { AdminModel, TaskFamily } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function LaunchPage() {
  const admin = await requireAdmin("/admin/runs/new");
  const actor = getActor(admin);
  let models: AdminModel[];
  let families: TaskFamily[];
  try {
    [models, families] = await Promise.all([adminGet<AdminModel[]>("/admin/models", actor), adminGet<TaskFamily[]>("/admin/task-families", actor)]);
  } catch (error) {
    return <LoadError error={error} retryHref="/admin/runs/new" />;
  }
  return (
    <>
      <Link href="/admin/runs" className="back">
        ← Runs
      </Link>
      <h1>Launch runs</h1>
      <p className="adm-lede">
        Choose which models to test on which course material. Every model answers every question in every chosen task. You
        will see the cost before anything starts.
      </p>
      <RunLauncher models={models} families={families.filter((f) => !f.archived_at && f.task_count > 0)} />
    </>
  );
}
