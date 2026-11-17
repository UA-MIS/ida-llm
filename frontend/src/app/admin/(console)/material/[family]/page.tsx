import Link from "next/link";

import { EmptyState } from "@/components/admin/form-bits";
import { LoadError } from "@/components/admin/load-error";
import { TaskFamilyForm } from "@/components/admin/task-family-form";
import { adminGet } from "@/lib/admin/api";
import { formatWhen } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import { taskPath } from "@/lib/admin/tasks";
import type { AdminTaskSummary, SystemInfo, TaskFamily } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function TaskFamilyPage({
  params,
  searchParams,
}: {
  params: Promise<{ family: string }>;
  searchParams: Promise<{ created?: string; archived?: string; saved?: string }>;
}) {
  const { family: key } = await params;
  const here = `/admin/material/${encodeURIComponent(key)}`;
  const admin = await requireAdmin(here);
  const actor = getActor(admin);
  const sp = await searchParams;
  let families: TaskFamily[];
  let tasks: AdminTaskSummary[];
  let system: SystemInfo | null;
  try {
    [families, tasks, system] = await Promise.all([
      adminGet<TaskFamily[]>("/admin/task-families", actor),
      adminGet<AdminTaskSummary[]>(`/admin/tasks?family=${encodeURIComponent(key)}`, actor),
      adminGet<SystemInfo>("/admin/system", actor).catch(() => null),
    ]);
  } catch (error) {
    return (
      <>
        <Link href="/admin/material" className="back">
          ← Course material
        </Link>
        <h1>Task family</h1>
        <LoadError error={error} retryHref={here} />
      </>
    );
  }
  const family = families.find((f) => f.key === key);
  if (!family) {
    return (
      <>
        <Link href="/admin/material" className="back">
          ← Course material
        </Link>
        <EmptyState title="That task family does not exist">
          <p>It may have been removed. Go back to the list to find it.</p>
        </EmptyState>
      </>
    );
  }
  const active = tasks.filter((t) => !t.archived_at);
  return (
    <>
      <Link href="/admin/material" className="back">
        ← Course material
      </Link>
      <h1>{family.title}</h1>
      {sp.created === "1" ? (
        <p role="status" className="adm-panel adm-panel-ok">
          Family created. Add its first task below.
        </p>
      ) : null}
      {sp.archived === "done" ? (
        <p role="status" className="adm-panel adm-panel-ok">
          The task was archived. Its past results are kept.
        </p>
      ) : null}
      <h2>Tasks</h2>
      <div className="adm-toolbar">
        <Link href={`/admin/material/tasks/new?family=${encodeURIComponent(key)}`} className="adm-btn adm-btn-primary">
          New task
        </Link>
        <Link href="/admin/material/upload" className="adm-btn adm-btn-quiet">
          Upload a task file
        </Link>
      </div>
      {active.length ? (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th scope="col">Task</th>
                <th scope="col">Marking</th>
                <th scope="col" className="num">
                  Questions
                </th>
                <th scope="col">Last changed</th>
              </tr>
            </thead>
            <tbody>
              {active.map((t) => (
                <tr key={t.id}>
                  <td>
                    <Link href={`/admin/material/tasks/${taskPath(t.id)}`}>
                      <strong>{t.title}</strong>
                    </Link>
                    <div className="mono muted">{t.id}</div>
                  </td>
                  <td>{t.kind === "verifiable" ? "Automatic" : "Judge + rubric"}</td>
                  <td className="num">{t.sample_count}</td>
                  <td>
                    {formatWhen(t.updated_at)}
                    {t.updated_by ? <div className="muted">by @{t.updated_by}</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No tasks in this family yet">
          <p>Create one with the form, or upload a YAML file.</p>
        </EmptyState>
      )}
      <h2>Family details</h2>
      {sp.saved === "1" ? (
        <p role="status" className="adm-panel adm-panel-ok">
          Family details saved.
        </p>
      ) : null}
      <TaskFamilyForm key={family.version} family={family} privateAllowed={system?.tasks_spec_gated === true} />
    </>
  );
}
