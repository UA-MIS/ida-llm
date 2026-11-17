import { CredentialsManager } from "@/components/admin/credentials-manager";
import { LoadError } from "@/components/admin/load-error";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { Credential, SystemInfo } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function CredentialsPage() {
  const admin = await requireAdmin("/admin/credentials");
  const actor = getActor(admin);
  let credentials: Credential[];
  let system: SystemInfo | null;
  try {
    [credentials, system] = await Promise.all([
      adminGet<Credential[]>("/admin/credentials", actor),
      adminGet<SystemInfo>("/admin/system", actor).catch(() => null),
    ]);
  } catch (error) {
    return (
      <>
        <h1>API keys</h1>
        <LoadError error={error} retryHref="/admin/credentials" />
      </>
    );
  }
  return (
    <>
      <h1>API keys</h1>
      <p className="adm-lede">
        Provider API keys stored for models to use. Keys are encrypted, and nobody (including you) can view a key after it
        has been saved: to change one, replace it.
      </p>
      <CredentialsManager credentials={credentials} kekConfigured={system?.kek_configured ?? true} />
    </>
  );
}
