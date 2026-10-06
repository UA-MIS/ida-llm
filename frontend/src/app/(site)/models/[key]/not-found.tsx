import Link from "next/link";

/**
 * A model key nothing has been run against.
 *
 * Deliberately NOT an empty report card. A page of em-dashes under a model's
 * name reads as "we measured it and it scored nothing", which is a different and
 * false claim from "this benchmark has never run that key".
 */
export default function ModelNotFound() {
  return (
    <div className="empty">
      <h2>No such model in the benchmark</h2>
      <p className="muted">
        Nothing has been measured under that model key — it may be a typo, or a
        model in the registry that no run has used yet.
      </p>
      <p className="muted">
        <Link href="/">Back to all majors</Link>.
      </p>
    </div>
  );
}
