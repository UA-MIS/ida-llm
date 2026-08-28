import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty">
      <h2>Run not found</h2>
      <p className="muted">
        No run with that id exists. It may have been deleted, or the id may be
        mistyped.
      </p>
      <Link href="/runs">← All runs</Link>
    </div>
  );
}
