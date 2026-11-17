import Link from "next/link";

import { MajorForm } from "@/components/admin/major-form";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { MajorsResponse } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function NewMajorPage() {
  const admin = await requireAdmin("/admin/classes/majors/new");
  const data = await adminGet<MajorsResponse>("/admin/majors", getActor(admin)).catch(() => null);
  const next = Math.max(0, ...(data?.majors ?? []).map((m) => m.position)) + 1;
  return (
    <>
      <Link href="/admin/classes" className="back">
        ← Majors and classes
      </Link>
      <h1>Add a major</h1>
      <MajorForm major={null} nextPosition={next} />
    </>
  );
}
