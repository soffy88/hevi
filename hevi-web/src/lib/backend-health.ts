/** Runtime health probes. Liveness and production readiness are separate authorities. */
import { resolveApiBase, resolveFrontendEnvironment } from './runtime-config';

type HealthRuntimeConfig = {
  apiBase: string;
  useMock: boolean;
  environment?: string;
};

export type ReadyReport = {
  status?: string;
  database?: string;
  redis?: { status?: string; [key: string]: unknown };
  minio?: { status?: string; [key: string]: unknown };
  worker_heartbeat?: { status?: string; [key: string]: unknown };
  scheduler?: { status?: string; [key: string]: unknown };
  readiness_requires_worker?: string;
  [key: string]: unknown;
};

export type BackendHealth = {
  state: 'healthy' | 'degraded' | 'offline';
  live: boolean;
  ready: boolean;
  apiBase: string;
  latencyMs?: number;
  liveStatusCode?: number;
  readyStatusCode?: number;
  readyReport?: ReadyReport;
  message?: string;
};

async function probe(url: string, signal: AbortSignal): Promise<{ ok: boolean; status: number; body: ReadyReport | null }> {
  const response = await fetch(url, {
    method: 'GET',
    signal,
    headers: { Accept: 'application/json' },
  });
  let body: ReadyReport | null = null;
  try {
    const parsed: unknown = await response.json();
    if (parsed && typeof parsed === 'object') body = parsed as ReadyReport;
  } catch {
    // Probe status remains authoritative when a proxy returns non-JSON.
  }
  return { ok: response.ok, status: response.status, body };
}

export async function checkBackendHealth(
  config: HealthRuntimeConfig = (() => {
    const environment = resolveFrontendEnvironment(
      process.env.NEXT_PUBLIC_DEPLOY_ENV,
      process.env.NODE_ENV,
    );
    const base = resolveApiBase(environment, process.env.NEXT_PUBLIC_API_BASE);
    const mock = (process.env.NEXT_PUBLIC_USE_MOCK ?? 'false').trim().toLowerCase() === 'true';
    return { apiBase: base, useMock: mock, environment };
  })(),
): Promise<BackendHealth> {
  const start = Date.now();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);
  try {
    const [live, ready] = await Promise.all([
      probe(`${config.apiBase}/api/health/live`, controller.signal),
      probe(`${config.apiBase}/api/health/ready`, controller.signal),
    ]);
    const readyReport = ready.body ?? undefined;
    const isReady = ready.ok && readyReport?.status === 'ready';
    const isLive = live.ok;
    return {
      state: isLive && isReady ? 'healthy' : isLive ? 'degraded' : 'offline',
      live: isLive,
      ready: isReady,
      apiBase: config.apiBase,
      latencyMs: Date.now() - start,
      liveStatusCode: live.status,
      readyStatusCode: ready.status,
      readyReport,
      message: isReady ? undefined : String(readyReport?.status ?? `readiness ${ready.status}`),
    };
  } catch (err) {
    return {
      state: 'offline',
      live: false,
      ready: false,
      apiBase: config.apiBase,
      latencyMs: Date.now() - start,
      message: err instanceof Error ? err.message : 'Failed to reach backend',
    };
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function checkHealthWithConfig(): Promise<BackendHealth> {
  const environment = resolveFrontendEnvironment(
    process.env.NEXT_PUBLIC_DEPLOY_ENV,
    process.env.NODE_ENV,
  );
  const base = resolveApiBase(environment, process.env.NEXT_PUBLIC_API_BASE);
  const mock = (process.env.NEXT_PUBLIC_USE_MOCK ?? 'false').trim().toLowerCase() === 'true';
  return checkBackendHealth({ apiBase: base, useMock: mock, environment });
}
