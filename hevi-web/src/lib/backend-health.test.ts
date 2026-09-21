import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkBackendHealth } from './backend-health';

afterEach(() => vi.unstubAllGlobals());

function response(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
}

describe('live/readiness separation', () => {
  it('reports live while worker-stale readiness is false', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/live')
      ? response(200, { status: 'ok' })
      : response(503, {
        status: 'not_ready',
        worker_heartbeat: { status: 'unavailable' },
        readiness_requires_worker: 'YES',
      })));

    const health = await checkBackendHealth({ apiBase: 'http://api.test', useMock: false });
    expect(health.live).toBe(true);
    expect(health.ready).toBe(false);
    expect(health.state).toBe('degraded');
    expect(health.readyReport?.readiness_requires_worker).toBe('YES');
  });

  it('requires both probes for healthy', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/live')
      ? response(200, { status: 'ok' })
      : response(200, { status: 'ready', worker_heartbeat: { status: 'ok' } })));
    const health = await checkBackendHealth({ apiBase: 'http://api.test', useMock: false });
    expect(health).toMatchObject({ live: true, ready: true, state: 'healthy' });
  });
});
