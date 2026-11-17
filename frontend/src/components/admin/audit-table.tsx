import Link from "next/link";

import { entityHref, formatWhen } from "@/lib/admin/format";
import type { AuditEntry } from "@/lib/admin/types";

/** Audit rows, newest first. Each links to the thing it changed. Server-rendered; no client code. */
export function AuditTable({ entries, compact = false }: { entries: AuditEntry[]; compact?: boolean }) {
  return (
    <div className="adm-table-wrap">
      <table className="adm-table">
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Who</th>
            <th scope="col">What</th>
            <th scope="col">Item</th>
            {compact ? null : <th scope="col">Details</th>}
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => {
            const href = entityHref(e.entity_type, e.entity_id);
            return (
              <tr key={e.id}>
                <td>{formatWhen(e.at)}</td>
                <td>{e.actor_login.startsWith("system") ? <span className="muted">{e.actor_login}</span> : `@${e.actor_login}`}</td>
                <td className="mono">{e.action}</td>
                <td>
                  {href ? <Link href={href}>{e.entity_id || e.entity_type}</Link> : e.entity_id || e.entity_type}
                  {e.config_revision !== null ? <div className="muted">revision {e.config_revision}</div> : null}
                </td>
                {compact ? null : (
                  <td>
                    {e.before !== null || e.after !== null ? (
                      <details className="adm-detail">
                        <summary>Before and after</summary>
                        <pre>{JSON.stringify({ before: e.before, after: e.after }, null, 2)}</pre>
                      </details>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
