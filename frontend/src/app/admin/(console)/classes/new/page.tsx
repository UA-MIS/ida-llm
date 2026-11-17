import Link from "next/link";

import { ClassForm } from "@/components/admin/class-editor";
import { LoadError } from "@/components/admin/load-error";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { MajorsResponse } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function NewClassPage({ searchParams }: { searchParams: Promise<{ major?: string }> }) {
  const admin = await requireAdmin("/admin/classes/new");
  const { major } = await searchParams;
  let data: MajorsResponse;
  try {
    data = await adminGet<MajorsResponse>("/admin/majors", getActor(admin));
  } catch (error) {
    return <LoadError error={error} retryHref="/admin/classes/new" />;
  }
  return (
    <>
      <Link href="/admin/classes" className="back">
        ← Majors and classes
      </Link>
      <h1>Add a class</h1>
      <ClassForm klass={null} majors={data.majors} defaultMajor={major} />
    </>
  );
}
