import Link from "next/link";

import { AuditTable } from "@/components/admin/audit-table";
import { EmptyState } from "@/components/admin/form-bits";
import { LoadError } from "@/components/admin/load-error";
import { adminGet } from "@/lib/admin/api";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { AuditList } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

const FILTERS = ["entity_type", "entity_id", "actor", "action", "since", "until"] as const;
const ENTITY_TYPES = ["model", "model_family", "credential", "task_family", "task", "major", "class", "unit", "curriculum_slo", "run", "sweep", "auth", "config"];

export default async function AuditPage({ searchParams }: { searchParams: Promise<Partial<Record<(typeof FILTERS)[number] | "cursor", string>>> }) {
  const admin = await requireAdmin("/admin/audit");
  const sp = await searchParams;
  const q = new URLSearchParams({ limit: "100" });
  for (const k of FILTERS) if (sp[k]) q.set(k, sp[k]!);
  if (sp.cursor) q.set("cursor", sp.cursor);
  let list: AuditList;
  try {
    list = await adminGet<AuditList>(`/admin/audit?${q}`, getActor(admin));
  } catch (error) {
    return (
      <>
        <h1>Activity log</h1>
        <LoadError error={error} retryHref="/admin/audit" />
      </>
    );
  }
  const filtered = FILTERS.some((k) => sp[k]);
  const next = new URLSearchParams();
  for (const k of FILTERS) if (sp[k]) next.set(k, sp[k]!);
  if (list.next_cursor) next.set("cursor", list.next_cursor);

  return (
    <>
      <h1>Activity log</h1>
      <p className="adm-lede">Every change made in this console, who made it and when, plus sign-ins and refused sign-ins. Entries can never be edited or deleted.</p>
      <form method="get" className="adm-actions" aria-label="Filter the activity log">
        <label className="adm-label" htmlFor="a-type">
          Kind
        </label>
        <select id="a-type" name="entity_type" defaultValue={sp.entity_type ?? ""} className="adm-select" style={{ width: "auto" }}>
          <option value="">Any</option>
          {ENTITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t.replace("_", " ")}
            </option>
          ))}
        </select>
        <label className="adm-label" htmlFor="a-actor">
          Person
        </label>
        <input id="a-actor" name="actor" placeholder="GitHub name" defaultValue={sp.actor ?? ""} className="adm-input" style={{ width: "10rem" }} />
        <label className="adm-label" htmlFor="a-since">
          From
        </label>
        <input id="a-since" name="since" type="date" defaultValue={sp.since ?? ""} className="adm-input" style={{ width: "auto" }} />
        <label className="adm-label" htmlFor="a-until">
          To
        </label>
        <input id="a-until" name="until" type="date" defaultValue={sp.until ?? ""} className="adm-input" style={{ width: "auto" }} />
        {sp.entity_id ? <input type="hidden" name="entity_id" value={sp.entity_id} /> : null}
        <button type="submit" className="adm-btn adm-btn-secondary">
          Filter
        </button>
        {filtered ? (
          <Link href="/admin/audit" className="adm-btn adm-btn-quiet">
            Clear
          </Link>
        ) : null}
      </form>
      {list.entries.length ? (
        <>
          <AuditTable entries={list.entries} />
          {list.next_cursor ? <Link href={`/admin/audit?${next}`}>Older entries →</Link> : null}
        </>
      ) : (
        <EmptyState title={filtered ? "Nothing matches these filters" : "Nothing has been recorded yet"} />
      )}
    </>
  );
}
