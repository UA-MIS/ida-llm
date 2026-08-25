import { runMigrations } from './migrate';
import { closePool } from './pool';

runMigrations()
  .then((applied) => {
    console.log(
      applied.length ? `[migrate] ${applied.length} migration(s) applied.` : '[migrate] up to date.',
    );
  })
  .catch((err) => {
    console.error('[migrate] FAILED', err);
    process.exitCode = 1;
  })
  .finally(closePool);
