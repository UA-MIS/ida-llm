import Link from "next/link";

import { UploadForm } from "@/components/admin/upload-form";
import { adminEnv } from "@/lib/admin/env";
import { requireAdmin } from "@/lib/admin/session";

export const dynamic = "force-dynamic";

export default async function UploadPage() {
  await requireAdmin("/admin/material/upload");
  return (
    <>
      <Link href="/admin/material" className="back">
        ← Course material
      </Link>
      <h1>Upload a task file</h1>
      <p className="adm-lede">
        Check the file first: you will see any problems, and how it differs from the current version, before anything is
        saved. The task&apos;s family must already exist.
      </p>
      <UploadForm maxBytes={adminEnv().UPLOAD_MAX_BYTES} />
    </>
  );
}
