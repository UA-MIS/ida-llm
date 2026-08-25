import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { generateKeyPairSync } from 'node:crypto';
import {
  credentialSummary,
  githubReadToken,
  githubActionCredential,
  attributionNote,
  missingCredentialMessage,
} from '@/lib/github/credential';
import { resetInstallationTokenCache, setInstallationTokenFetch } from '@/lib/github/app';
import { config } from '@/lib/env';

const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const PEM = privateKey.export({ type: 'pkcs1', format: 'pem' }).toString();

/** Installs a fetch double for the App path so no test touches the network. */
function appMints(token: string | null): { calls: number } {
  const state = { calls: 0 };
  setInstallationTokenFetch((async () => {
    state.calls++;
    if (token === null) return new Response('{"message":"nope"}', { status: 401 });
    return new Response(
      JSON.stringify({ token, expires_at: new Date(Date.now() + 3600_000).toISOString() }),
      { status: 201, headers: { 'content-type': 'application/json' } },
    );
  }) as unknown as typeof fetch);
  return state;
}

function enableApp(): void {
  process.env.GITHUB_APP_ID = '4097147';
  process.env.GITHUB_APP_PRIVATE_KEY = PEM;
  process.env.GITHUB_APP_INSTALLATION_ID = '141394298';
}

beforeEach(() => {
  resetInstallationTokenCache();
  setInstallationTokenFetch(null);
  delete process.env.GITHUB_APP_ID;
  delete process.env.GITHUB_APP_PRIVATE_KEY;
  delete process.env.GITHUB_APP_INSTALLATION_ID;
  delete process.env.GITHUB_POLL_TOKEN;
  delete process.env.AUTH_PROVIDER;
  process.env.OIDC_ISSUER = 'https://id.capstone.uamishub.com';
  process.env.APP_URL = 'https://ida-agile.capstone.uamishub.com';
});

afterEach(() => {
  setInstallationTokenFetch(null);
  vi.restoreAllMocks();
});

describe('precedence: the acting user first, then the App, then a static token', () => {
  it("prefers the USER's own token, so the action stays genuinely theirs", async () => {
    enableApp();
    process.env.GITHUB_POLL_TOKEN = 'ghp_shared';
    const mint = appMints('ghs_app');

    const cred = await githubActionCredential({ githubToken: 'gho_alice' });
    expect(cred).toEqual({ token: 'gho_alice', source: 'user' });
    // The App is never called when the user brought a credential.
    expect(mint.calls).toBe(0);
  });

  it('falls back to the App installation token when the session carries none (Dex)', async () => {
    enableApp();
    appMints('ghs_app');

    const cred = await githubActionCredential({ githubToken: null });
    expect(cred).toEqual({ token: 'ghs_app', source: 'app' });
  });

  it('prefers the App over GITHUB_POLL_TOKEN when both are configured', async () => {
    enableApp();
    process.env.GITHUB_POLL_TOKEN = 'ghp_legacy';
    appMints('ghs_app');

    expect(await githubActionCredential({ githubToken: null })).toEqual({
      token: 'ghs_app',
      source: 'app',
    });
  });

  it('still honours GITHUB_POLL_TOKEN for deployments that only set that', async () => {
    process.env.GITHUB_POLL_TOKEN = 'ghp_legacy';

    expect(await githubActionCredential({ githubToken: null })).toEqual({
      token: 'ghp_legacy',
      source: 'poll-token',
    });
  });

  it('falls through to GITHUB_POLL_TOKEN when the App is configured but minting FAILS', async () => {
    enableApp();
    process.env.GITHUB_POLL_TOKEN = 'ghp_legacy';
    appMints(null);

    expect(await githubActionCredential({ githubToken: null })).toEqual({
      token: 'ghp_legacy',
      source: 'poll-token',
    });
  });

  it('degrades to no credential rather than throwing when nothing is configured', async () => {
    expect(await githubActionCredential({ githubToken: null })).toEqual({
      token: null,
      source: 'none',
    });
    expect(await githubActionCredential(null)).toEqual({ token: null, source: 'none' });
    expect(await githubActionCredential(undefined)).toEqual({ token: null, source: 'none' });
  });

  it('degrades to no credential when the App is configured but unreachable', async () => {
    enableApp();
    appMints(null);
    expect(await githubActionCredential({ githubToken: null })).toEqual({
      token: null,
      source: 'none',
    });
  });

  it('treats an empty-string user token as absent, not as a credential', async () => {
    enableApp();
    appMints('ghs_app');
    expect((await githubActionCredential({ githubToken: '' })).source).toBe('app');
  });
});

describe('githubReadToken — the same precedence, for callers that only need the token', () => {
  it("returns the user's token when there is one", async () => {
    expect(await githubReadToken({ githubToken: 'gho_alice' })).toBe('gho_alice');
  });

  it('returns the App token for a Dex session — THE assignee-picker fix', async () => {
    enableApp();
    appMints('ghs_app');
    expect(await githubReadToken({ githubToken: null })).toBe('ghs_app');
  });

  it('returns the static token when that is all there is', async () => {
    process.env.GITHUB_POLL_TOKEN = 'ghp_legacy';
    expect(await githubReadToken({ githubToken: null })).toBe('ghp_legacy');
  });

  it('returns null when nothing is available', async () => {
    expect(await githubReadToken({ githubToken: null })).toBeNull();
    expect(await githubReadToken(null)).toBeNull();
  });
});

describe('attribution — history must not imply a person did what the board did', () => {
  it('marks an App-credential action as performed with the board credential', () => {
    expect(attributionNote('app')).toBeTruthy();
    expect(attributionNote('app')!.toLowerCase()).toContain('board');
  });

  it('marks a static-token action too — it is equally not the user', () => {
    expect(attributionNote('poll-token')).toBeTruthy();
  });

  it("adds NOTHING when the user's own credential was used", () => {
    expect(attributionNote('user')).toBeUndefined();
    expect(attributionNote('none')).toBeUndefined();
  });
});

describe('the message shown when there is genuinely no credential', () => {
  it('names the App variables an owner has to set, under Dex', () => {
    process.env.AUTH_PROVIDER = 'oidc';
    const msg = missingCredentialMessage('Creating a branch');
    expect(msg).toContain('Creating a branch');
    expect(msg).toContain('GITHUB_APP_ID');
    expect(msg).toContain('Dex');
  });

  it('suggests signing in with GitHub when that is the provider', () => {
    process.env.AUTH_PROVIDER = 'github';
    expect(missingCredentialMessage('Creating a branch')).toContain('Sign in with GitHub');
  });

  it('never leaks a configured credential into a user-facing message', () => {
    process.env.AUTH_PROVIDER = 'oidc';
    process.env.GITHUB_POLL_TOKEN = 'ghp_do_not_show_me';
    process.env.GITHUB_APP_PRIVATE_KEY = PEM;
    const msg = missingCredentialMessage('Posting a comment');
    expect(msg).not.toContain('ghp_do_not_show_me');
    expect(msg).not.toContain('PRIVATE KEY');
  });
});

describe('background reconciliation is enabled by the App, not only by a PAT', () => {
  it('is off when neither is configured', () => {
    process.env.POLL_INTERVAL_SECONDS = '300';
    expect(config.backgroundPollEnabled).toBe(false);
  });

  it('is on with only the App configured — no PAT required any more', () => {
    process.env.POLL_INTERVAL_SECONDS = '300';
    enableApp();
    expect(config.backgroundPollEnabled).toBe(true);
  });

  it('stays off when the interval is 0, however the credential is supplied', () => {
    process.env.POLL_INTERVAL_SECONDS = '0';
    enableApp();
    expect(config.backgroundPollEnabled).toBe(false);
    delete process.env.POLL_INTERVAL_SECONDS;
  });
});

describe('the startup credential summary — how the next silent failure gets caught', () => {
  it('names the App and its installation when the App is configured', () => {
    enableApp();
    const summary = credentialSummary();
    expect(summary).toContain('GitHub App');
    expect(summary).toContain('4097147');
    expect(summary).toContain('141394298');
  });

  it('says plainly that the static token is the legacy path', () => {
    process.env.GITHUB_POLL_TOKEN = 'ghp_legacy';
    expect(credentialSummary()).toContain('GITHUB_POLL_TOKEN');
    expect(credentialSummary()).toContain('legacy');
  });

  it('is UNMISSABLE when there is no credential — the original failure was silent', () => {
    const summary = credentialSummary();
    expect(summary).toContain('NONE');
    expect(summary).toContain('assignee picker');
    expect(summary).toContain('GITHUB_APP_ID');
  });

  it('never contains the private key or a token value', () => {
    enableApp();
    process.env.GITHUB_POLL_TOKEN = 'ghp_do_not_print_me';
    const summary = credentialSummary();
    expect(summary).not.toContain('PRIVATE KEY');
    expect(summary).not.toContain('ghp_do_not_print_me');
    expect(summary).not.toContain(PEM.split('\n')[1]);
  });
});
