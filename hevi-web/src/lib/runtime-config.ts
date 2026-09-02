/**
 * HEVI Frontend Runtime Configuration
 *
 * Single source of truth for all runtime configuration.
 * All API, SSE, and media URLs must be derived from this module.
 *
 * Default behavior:
 *   - development/production: REAL backend (no mock)
 *   - mock can only be explicitly enabled via NEXT_PUBLIC_USE_MOCK=true
 *
 * Production build warning:
 *   If NEXT_PUBLIC_USE_MOCK=true in production, a console warning is emitted.
 */

import type { RuntimeConfig } from './runtime-config-type';

/** Canonical runtime config — read once at module load, never changes. */
export const runtimeConfig: RuntimeConfig = (() => {
  // API base from env or default to localhost
  const apiBase = process.env.NEXT_PUBLIC_API_BASE
    ? process.env.NEXT_PUBLIC_API_BASE.trim()
    : 'http://127.0.0.1:8000';

  // Detect mock mode — defaults to 'false' when unset, only true when explicitly set
  const useMock = (process.env.NEXT_PUBLIC_USE_MOCK ?? 'false')
    .trim()
    .toLowerCase() === 'true';

  // Determine environment
  const environment = process.env.NODE_ENV === 'production' ? 'production' : 'development';

  // Warn in production builds if mock is enabled
  if (environment === 'production' && useMock) {
    console.warn(
      '[HEVI] WARNING: NEXT_PUBLIC_USE_MOCK=true in production build! ' +
        'Mock mode is enabled. Set NEXT_PUBLIC_USE_MOCK=false for real backend.',
    );
  }

  return { apiBase, useMock, environment };
})();

/** Shortcuts for convenience */
export const API_BASE = runtimeConfig.apiBase;
export const USE_MOCK = runtimeConfig.useMock;
export const IS_MOCK = runtimeConfig.useMock;
export const IS_PRODUCTION = runtimeConfig.environment === 'production';

/** Build an authenticated SSE/streaming URL from a relative path.
 *  EventSource cannot send Authorization headers, so token is passed as query param.
 *  Token is URL-encoded for safety.
 */
export function buildAuthenticatedStreamUrl(path: string, token: string | null): string {
  const base = API_BASE.endsWith('/') ? API_BASE.slice(0, -1) : API_BASE;
  const encodedPath = path.startsWith('/') ? path : `/${path}`;
  if (token) {
    return `${base}${encodedPath}?token=${encodeURIComponent(token)}`;
  }
  return `${base}${encodedPath}`;
}

/** Build a media URL (video/image/audio/download) that works in <video>, <img>, <a>.
 *  These elements cannot send Authorization headers, so token is passed as query param.
 */
export function mediaUrl(path: string, token: string | null): string {
  return buildAuthenticatedStreamUrl(path, token);
}

/** Export the type for use by api-client and other modules */
export type { RuntimeConfig };
