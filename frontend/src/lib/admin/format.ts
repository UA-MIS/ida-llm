/**
 * Display helpers for the admin console. Times are shown in US Central (the
 * University of Alabama's zone) with the zone named, so "06:40" is never
 * ambiguous between the server, the browser and the reader.
 */

const WHEN = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago",
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${WHEN.format(date)} CT`;
}

export function formatUsd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `$${value.toFixed(digits)}`;
}

const STATUS: Record<string, { label: string; tone: "ok" | "bad" | "warn" | "neutral" }> = {
  queued: { label: "Waiting", tone: "warn" },
  running: { label: "Running", tone: "warn" },
  succeeded: { label: "Finished", tone: "ok" },
  partial: { label: "Partly finished", tone: "warn" },
  failed: { label: "Failed", tone: "bad" },
  // Styled like `failed` (design §4.6): it measured nothing it can stand behind.
  cancelled: { label: "Cancelled", tone: "bad" },
};

export function runStatus(status: string): { label: string; tone: "ok" | "bad" | "warn" | "neutral" } {
  return STATUS[status] ?? { label: status, tone: "neutral" };
}

export const TERMINAL_STATUSES = ["succeeded", "partial", "failed", "cancelled"];

/** Decode a route segment; leaves it alone if it is not valid percent-encoding. */
export function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** Where an audit row's entity can be looked at in the console, if anywhere. */
export function entityHref(type: string, id: string): string | null {
  const e = encodeURIComponent(id);
  const task = id.split("/").map(encodeURIComponent).join("/");
  switch (type) {
    case "model":
      return `/admin/models/${e}`;
    case "model_family":
      return "/admin/model-families";
    case "credential":
      return "/admin/credentials";
    case "task_family":
      return `/admin/material/${e}`;
    case "task":
      return `/admin/material/tasks/${task}`;
    case "major":
      return `/admin/classes/majors/${e}`;
    case "class":
      return `/admin/classes/${e}`;
    case "unit":
      return "/admin/classes";
    case "curriculum_slo":
      return "/admin/classes/outcomes";
    case "run":
      return `/admin/runs/${e}`;
    case "sweep":
      return `/admin/sweeps/${e}`;
    default:
      return null;
  }
}
