import Link from "next/link";

import { LoadError } from "@/components/admin/load-error";
import { TaskEditor } from "@/components/admin/task-editor";
import { adminGet } from "@/lib/admin/api";
import { safeDecode } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import { taskPath } from "@/lib/admin/tasks";
import type { AdminTask } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

/**
 * ⚠ UNREDACTED: prompts, correct answers and rubrics are shown here. That is
 * the point of an authoring screen, and it is safe only because
 * `requireAdmin()` runs first (pinned by admin-isolation.test.ts).
 */
export default async function TaskPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string[] }>;
  searchParams: Promise<{ created?: string }>;
}) {
  const id = (await params).id.map(safeDecode).join("/");
  const here = `/admin/material/tasks/${taskPath(id)}`;
  const admin = await requireAdmin(here);
  const created = (await searchParams).created === "1";
  let task: AdminTask;
  try {
    task = await adminGet<AdminTask>(`/admin/tasks/${taskPath(id)}`, getActor(admin));
  } catch (error) {
    return (
      <>
        <Link href="/admin/material" className="back">
          ← Course material
        </Link>
        <h1>Task</h1>
        <LoadError error={error} retryHref={here} />
      </>
    );
  }
  return (
    <>
      <Link href={`/admin/material/${encodeURIComponent(task.family_key)}`} className="back">
        ← Back to the family
      </Link>
      <h1>{task.title}</h1>
      {created ? (
        <p role="status" className="adm-panel adm-panel-ok">
          Task created. Add more questions in the Questions tab.
        </p>
      ) : null}
      <TaskEditor key={task.version} task={task} />
    </>
  );
}
