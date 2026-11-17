/** Path rule for the BFF (`app/admin/api/[...path]/route.ts`), kept here because route files may only export handlers. */

/** `/admin/<seg>/<seg>…` with each segment re-encoded, or `null` if any segment could escape. */
export function upstreamPath(segments: string[] | undefined): string | null {
  if (!segments?.length) return null;
  for (const seg of segments) {
    if (seg === "" || seg === "." || seg === ".." || seg.includes("/") || seg.includes("\\")) return null;
  }
  return "/admin/" + segments.map(encodeURIComponent).join("/");
}
