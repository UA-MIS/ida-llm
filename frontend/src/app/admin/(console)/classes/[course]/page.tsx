import Link from "next/link";

import { ClassFamilies, ClassForm, UnitEditor } from "@/components/admin/class-editor";
import { EmptyState } from "@/components/admin/form-bits";
import { LoadError } from "@/components/admin/load-error";
import { adminGet } from "@/lib/admin/api";
import { safeDecode } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { MajorsResponse, TaskFamily } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

const SAVED: Record<string, string> = {
  "1": "Class details saved.",
  created: "Class added. Now choose the task families that measure it.",
  families: "Task families saved.",
  unit: "Unit saved.",
};

export default async function ClassPage({ params, searchParams }: { params: Promise<{ course: string }>; searchParams: Promise<{ saved?: string }> }) {
  const course = safeDecode((await params).course);
  const here = `/admin/classes/${encodeURIComponent(course)}`;
  const admin = await requireAdmin(here);
  const actor = getActor(admin);
  const saved = SAVED[(await searchParams).saved ?? ""];
  let data: MajorsResponse;
  let families: TaskFamily[];
  try {
    [data, families] = await Promise.all([
      adminGet<MajorsResponse>("/admin/majors", actor),
      adminGet<TaskFamily[]>("/admin/task-families", actor).catch(() => [] as TaskFamily[]),
    ]);
  } catch (error) {
    return <LoadError error={error} retryHref={here} />;
  }
  const klass = [...data.majors.flatMap((m) => m.classes), ...data.unassigned].find((c) => c.course === course);
  if (!klass) {
    return (
      <>
        <Link href="/admin/classes" className="back">
          ← Majors and classes
        </Link>
        <EmptyState title={`There is no class ${course}`}>
          <p>It may have been removed.</p>
        </EmptyState>
      </>
    );
  }
  return (
    <>
      <Link href="/admin/classes" className="back">
        ← Majors and classes
      </Link>
      <h1>
        {klass.course} {klass.resolved_title ?? klass.title ?? ""}
      </h1>
      {saved ? (
        <p role="status" className="adm-panel adm-panel-ok">
          {saved}
        </p>
      ) : null}
      <h2>Task families</h2>
      <ClassFamilies key={`f${klass.version}`} klass={klass} families={families} />
      <h2>Units</h2>
      <UnitEditor key={`u${klass.version}:${klass.units.map((u) => u.version).join(".")}`} klass={klass} families={families} />
      <h2>Class details</h2>
      <ClassForm key={`c${klass.version}`} klass={klass} majors={data.majors} />
    </>
  );
}
