import Link from "next/link";

import { EmptyState } from "@/components/admin/form-bits";
import { NewTaskForm } from "@/components/admin/new-task-form";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { TaskFamily } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function NewTaskPage({ searchParams }: { searchParams: Promise<{ family?: string }> }) {
  const { family: key } = await searchParams;
  const admin = await requireAdmin(`/admin/material/tasks/new${key ? `?family=${encodeURIComponent(key)}` : ""}`);
  const families = await adminGet<TaskFamily[]>("/admin/task-families", getActor(admin)).catch(() => [] as TaskFamily[]);
  const family = families.find((f) => f.key === key && !f.archived_at);
  return (
    <>
      <Link href={family ? `/admin/material/${encodeURIComponent(family.key)}` : "/admin/material"} className="back">
        ← {family ? family.title : "Course material"}
      </Link>
      <h1>New task</h1>
      {family ? (
        <NewTaskForm family={family.key} familyTitle={family.title} />
      ) : (
        <EmptyState title="Choose a task family first">
          <p>
            Every task belongs to a family. <Link href="/admin/material">Open a family</Link> and use its “New task” button.
          </p>
        </EmptyState>
      )}
    </>
  );
}
