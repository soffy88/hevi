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

export type FrontendEnvironment = 'development' | 'demo' | 'staging' | 'production';

/** The only production API origin accepted by a production artifact. */
export const PRODUCTION_API_BASE = 'https://api-prod.sxueji.com';

function normaliseBase(value: string): string {
  return value.trim().replace(/\/$/, '');
}

function assertSafeApiBase(value: string, environment: FrontendEnvironment): string {
  const base = normaliseBase(value);
  let parsed: URL;
  try {
    parsed = new URL(base);
  } catch {
    throw new Error(`[HEVI] Invalid NEXT_PUBLIC_API_BASE for ${environment}`);
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new Error(`[HEVI] Unsafe NEXT_PUBLIC_API_BASE for ${environment}`);
  }
  const hostParts = parsed.hostname.split('.');
  if (environment !== 'development' && hostParts[0] === 'api' && hostParts.length >= 3) {
    throw new Error('[HEVI] Shared API origin is forbidden; use an environment-specific route');
  }
  if (environment === 'production' && base !== PRODUCTION_API_BASE) {
    throw new Error(`[HEVI] Production API must be ${PRODUCTION_API_BASE}`);
  }
  return base;
}

/**
 * Resolve the browser API origin.  NEXT_PUBLIC_* values are build-time in
 * Next.js; the explicit environment is kept in the same contract so demo and
 * staging builds cannot silently inherit production routing.
 */
export function resolveApiBase(
  environment: FrontendEnvironment,
  configured: string | undefined,
): string {
  const explicit = configured?.trim();
  if (explicit) {
    return assertSafeApiBase(explicit, environment);
  }
  if (environment === 'production') {
    return PRODUCTION_API_BASE;
  }
  if (environment === 'development') {
    return 'http://127.0.0.1:8000';
  }
  throw new Error(`[HEVI] NEXT_PUBLIC_API_BASE is required for ${environment} builds`);
}

export function resolveFrontendEnvironment(
  configured: string | undefined,
  nodeEnvironment: string | undefined,
): FrontendEnvironment {
  const value = configured?.trim().toLowerCase();
  if (
    value === 'development' ||
    value === 'demo' ||
    value === 'staging' ||
    value === 'production'
  ) {
    return value;
  }
  if (value) {
    throw new Error(`[HEVI] Unsupported NEXT_PUBLIC_DEPLOY_ENV: ${value}`);
  }
  return nodeEnvironment === 'production' ? 'production' : 'development';
}

/** Canonical runtime config — read once at module load, never changes. */
export const runtimeConfig: RuntimeConfig = (() => {
  const environment = resolveFrontendEnvironment(
    process.env.NEXT_PUBLIC_DEPLOY_ENV,
    process.env.NODE_ENV,
  );
  const apiBase = resolveApiBase(environment, process.env.NEXT_PUBLIC_API_BASE);

  // Detect mock mode — defaults to 'false' when unset, only true when explicitly set
  const useMock = (process.env.NEXT_PUBLIC_USE_MOCK ?? 'false')
    .trim()
    .toLowerCase() === 'true';

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
