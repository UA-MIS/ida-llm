import Link from "next/link";

import { EmptyState } from "@/components/admin/form-bits";
import { LoadError } from "@/components/admin/load-error";
import { MajorForm } from "@/components/admin/major-form";
import { adminGet } from "@/lib/admin/api";
import { safeDecode } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { MajorsResponse } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function MajorPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ saved?: string }> }) {
  const id = safeDecode((await params).id);
  const here = `/admin/classes/majors/${encodeURIComponent(id)}`;
  const admin = await requireAdmin(here);
  const saved = (await searchParams).saved === "1";
  let data: MajorsResponse;
  try {
    data = await adminGet<MajorsResponse>("/admin/majors", getActor(admin));
  } catch (error) {
    return <LoadError error={error} retryHref={here} />;
  }
  const major = data.majors.find((m) => m.id === id);
  return (
    <>
      <Link href="/admin/classes" className="back">
        ← Majors and classes
      </Link>
      {major ? (
        <>
          <h1>{major.name}</h1>
          {saved ? (
            <p role="status" className="adm-panel adm-panel-ok">
              Saved.
            </p>
          ) : null}
          <MajorForm key={major.version} major={major} nextPosition={major.position} />
          <h2>Classes in this major</h2>
          {major.classes.length ? (
            <ul>
              {major.classes.map((c) => (
                <li key={c.course}>
                  <Link href={`/admin/classes/${encodeURIComponent(c.course)}`}>{c.course}</Link> {c.resolved_title ?? c.title ?? ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className="adm-hint">No classes yet.</p>
          )}
          <Link href={`/admin/classes/new?major=${encodeURIComponent(major.id)}`} className="adm-btn adm-btn-secondary">
            Add a class to this major
          </Link>
        </>
      ) : (
        <EmptyState title="That major does not exist">
          <p>It may have been removed.</p>
        </EmptyState>
      )}
    </>
  );
}
