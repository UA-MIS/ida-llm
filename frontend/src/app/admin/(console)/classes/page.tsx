import Link from "next/link";

import { EmptyState } from "@/components/admin/form-bits";
import { LoadError } from "@/components/admin/load-error";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { AdminClass, MajorsResponse } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

function ClassRows({ classes }: { classes: AdminClass[] }) {
  if (!classes.length) return <p className="adm-hint">No classes yet.</p>;
  return (
    <div className="adm-table-wrap">
      <table className="adm-table">
        <thead>
          <tr>
            <th scope="col">Class</th>
            <th scope="col" className="num">
              Task families
            </th>
            <th scope="col" className="num">
              Units
            </th>
          </tr>
        </thead>
        <tbody>
          {classes.map((c) => (
            <tr key={c.course}>
              <td>
                <Link href={`/admin/classes/${encodeURIComponent(c.course)}`}>
                  <strong>{c.course}</strong>
                </Link>{" "}
                {c.resolved_title ?? c.title ?? ""}
              </td>
              <td className="num">{c.task_families.length || <span className="adm-badge adm-badge-warn">none yet</span>}</td>
              <td className="num">{c.units.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function ClassesPage({ searchParams }: { searchParams: Promise<{ deleted?: string }> }) {
  const admin = await requireAdmin("/admin/classes");
  const deleted = (await searchParams).deleted === "1";
  let data: MajorsResponse;
  try {
    data = await adminGet<MajorsResponse>("/admin/majors", getActor(admin));
  } catch (error) {
    return (
      <>
        <h1>Majors and classes</h1>
        <LoadError error={error} retryHref="/admin/classes" />
      </>
    );
  }
  return (
    <>
      <h1>Majors and classes</h1>
      <p className="adm-lede">
        The majors and classes the public site is organised by. Open a class to choose which task families measure it and
        to arrange its units.
      </p>
      {deleted ? (
        <p role="status" className="adm-panel adm-panel-ok">
          Deleted.
        </p>
      ) : null}
      <div className="adm-toolbar">
        <span className="adm-actions" style={{ margin: 0 }}>
          <Link href="/admin/classes/new" className="adm-btn adm-btn-primary">
            Add a class
          </Link>
          <Link href="/admin/classes/majors/new" className="adm-btn adm-btn-quiet">
            Add a major
          </Link>
        </span>
        <Link href="/admin/classes/outcomes" className="adm-btn adm-btn-quiet">
          Edit learning outcomes
        </Link>
      </div>
      {data.majors.length || data.unassigned.length ? (
        <>
          {data.majors.map((m) => (
            <section key={m.id} aria-labelledby={`major-${m.id}`}>
              <h2 id={`major-${m.id}`}>
                <Link href={`/admin/classes/majors/${encodeURIComponent(m.id)}`}>{m.name}</Link>{" "}
                <span className="muted" style={{ fontWeight: 400, fontSize: "0.9rem" }}>
                  {m.department}
                </span>
              </h2>
              <ClassRows classes={m.classes} />
            </section>
          ))}
          {data.unassigned.length ? (
            <section aria-labelledby="major-unassigned">
              <h2 id="major-unassigned">Not part of a major</h2>
              <ClassRows classes={data.unassigned} />
            </section>
          ) : null}
        </>
      ) : (
        <EmptyState title="No majors or classes yet">
          <p>Add a major, then add its classes.</p>
        </EmptyState>
      )}
    </>
  );
}
