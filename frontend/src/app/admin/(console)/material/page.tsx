import Link from "next/link";

import { EmptyState } from "@/components/admin/form-bits";
import { LoadError } from "@/components/admin/load-error";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { TaskFamily } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function MaterialPage({ searchParams }: { searchParams: Promise<{ archived?: string }> }) {
  const admin = await requireAdmin("/admin/material");
  const archived = (await searchParams).archived === "done";
  let families: TaskFamily[];
  try {
    families = await adminGet<TaskFamily[]>("/admin/task-families", getActor(admin));
  } catch (error) {
    return (
      <>
        <h1>Course material</h1>
        <LoadError error={error} retryHref="/admin/material" />
      </>
    );
  }
  const active = families.filter((f) => !f.archived_at);
  return (
    <>
      <h1>Course material</h1>
      <p className="adm-lede">
        The questions models are tested on, grouped into task families. A family is usually one topic of one class, split
        into tasks of increasing difficulty.
      </p>
      {archived ? (
        <p role="status" className="adm-panel adm-panel-ok">
          The family was archived. Its past results are kept.
        </p>
      ) : null}
      <div className="adm-toolbar">
        <Link href="/admin/material/families/new" className="adm-btn adm-btn-primary">
          New task family
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
                <th scope="col">Family</th>
                <th scope="col">Material</th>
                <th scope="col" className="num">
                  Tasks
                </th>
                <th scope="col" className="num">
                  Questions
                </th>
                <th scope="col">Used by</th>
              </tr>
            </thead>
            <tbody>
              {active.map((f) => (
                <tr key={f.key}>
                  <td>
                    <Link href={`/admin/material/${encodeURIComponent(f.key)}`}>
                      <strong>{f.title}</strong>
                    </Link>
                    <div className="mono muted">{f.key}</div>
                  </td>
                  <td>
                    {f.provenance === "private" ? (
                      <span className="adm-badge adm-badge-warn">Private</span>
                    ) : (
                      <span className="adm-badge adm-badge-neutral">Written for the benchmark</span>
                    )}
                  </td>
                  <td className="num">{f.task_count}</td>
                  <td className="num">{f.sample_count}</td>
                  <td>
                    {f.classes.length ? f.classes.join(", ") : <span className="muted">No class yet</span>}
                    {f.unit ? <div className="muted">Unit: {f.unit.key} ({f.unit.course})</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No task families yet">
          <p>Create a family, then add tasks to it with the form or by uploading a YAML file.</p>
        </EmptyState>
      )}
    </>
  );
}
