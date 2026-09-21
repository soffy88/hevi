import { describe, expect, it } from 'vitest';
import {
  BACKEND_API_CONTRACT,
  capabilityQualification,
  normalizeTaskStatus,
  TASK_STATUSES,
} from './backend-contract';

describe('canonical backend contract guard', () => {
  it('keeps task statuses exact and fails closed for an adapter-only alias', () => {
    expect(TASK_STATUSES).toEqual([
      'pending', 'queued', 'claimed', 'running', 'completed', 'failed',
      'blocked', 'cancelled', 'paused', 'interrupted',
    ]);
    expect(normalizeTaskStatus('completed')).toBe('completed');
    expect(normalizeTaskStatus('succeeded')).toBe('unknown');
    expect(normalizeTaskStatus('made_up')).toBe('unknown');
  });

  it('keeps V2V blocked regardless of provider advertising', () => {
    expect(capabilityQualification({ id: 'v2v', available: true, production_ready: true })).toBe(
      'WIRING_QUALIFIED_PROVIDER_BLOCKED',
    );
    expect(capabilityQualification({ id: 'motion_graphics', available: true, production_ready: true })).toBe(
      'PRODUCTION_QUALIFIED',
    );
  });

  it('pins the frontend to the backend endpoint authorities', () => {
    expect(BACKEND_API_CONTRACT.productionCreate).toMatchObject({
      method: 'POST', path: '/api/pipeline/productions', success: 201,
    });
    expect(BACKEND_API_CONTRACT.healthLive.path).toBe('/api/health/live');
    expect(BACKEND_API_CONTRACT.healthReady.notReady).toBe(503);
    expect(BACKEND_API_CONTRACT.realtime.event).toBe('task_update');
  });
});
