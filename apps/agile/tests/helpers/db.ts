/**
 * Integration tests run against a real Postgres. They are skipped when
 * TEST_DATABASE_URL is not set, so `npm test` still works on a laptop with no
 * database, while CI runs the full suite.
 */
export const TEST_DATABASE_URL = process.env.TEST_DATABASE_URL;
export const hasDb = Boolean(TEST_DATABASE_URL);

export function installTestEnv(schema: string): void {
  if (TEST_DATABASE_URL) process.env.DATABASE_URL = TEST_DATABASE_URL;
  process.env.AGILE_DB_SCHEMA = schema;
  process.env.GITHUB_CLIENT_ID = 'test-client-id';
  process.env.GITHUB_CLIENT_SECRET = 'test-client-secret';
  process.env.SESSION_SECRET = 'x'.repeat(48);
  process.env.APP_URL = 'http://localhost:3000';
  process.env.GITHUB_ORG = 'UA-MIS';
  process.env.GITHUB_TEAM = 'ida-llm';
  process.env.GITHUB_REPOS = 'UA-MIS/ida-llm';
  process.env.BOARD_INSTANCE = 'test-instance';
}
