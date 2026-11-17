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
