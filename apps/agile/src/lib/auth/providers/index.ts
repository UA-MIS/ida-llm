import { config } from '@/lib/env';
import type { AuthProvider } from './types';
import { OidcProvider } from './oidc';
import { GitHubProvider } from './github';

export * from './types';

/**
 * Resolves the configured identity provider. Swapping providers is a config
 * change (`AUTH_PROVIDER`), never a code change.
 */
export function authProvider(): AuthProvider {
  return config.authProvider === 'oidc' ? new OidcProvider() : new GitHubProvider();
}
