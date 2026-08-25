import { config } from '@/lib/env';
import type { AuthProvider } from './types';
import { OidcProvider } from './oidc';
import { GitHubProvider } from './github';

export * from './types';

/**
 * Resolves an identity provider. Swapping providers is a config change
 * (`AUTH_PROVIDER`), never a code change.
 *
 * `which` overrides the configured default so an existing session is always
 * revalidated by the provider that ISSUED it — otherwise flipping
 * AUTH_PROVIDER would silently invalidate everyone still holding a session
 * from the previous one.
 */
export function authProvider(which?: 'oidc' | 'github'): AuthProvider {
  const id = which ?? config.authProvider;
  return id === 'oidc' ? new OidcProvider() : new GitHubProvider();
}
