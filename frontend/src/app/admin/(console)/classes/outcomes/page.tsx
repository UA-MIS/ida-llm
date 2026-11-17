import Link from "next/link";

import { LoadError } from "@/components/admin/load-error";
import { SloEditor } from "@/components/admin/slo-editor";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { SloDocument } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function OutcomesPage() {
  const admin = await requireAdmin("/admin/classes/outcomes");
  let doc: SloDocument;
  try {
    doc = await adminGet<SloDocument>("/admin/curriculum/slo", getActor(admin));
  } catch (error) {
    return <LoadError error={error} retryHref="/admin/classes/outcomes" />;
  }
  return (
    <>
      <Link href="/admin/classes" className="back">
        ← Majors and classes
      </Link>
      <h1>Learning outcomes</h1>
      <p className="adm-lede">
        The college&apos;s student learning outcomes and how each class covers them, as YAML. Your changes are checked
        before they are saved; if something would break, nothing is saved and the problem is listed below.
      </p>
      <SloEditor key={doc.version} doc={doc} />
    </>
  );
}
