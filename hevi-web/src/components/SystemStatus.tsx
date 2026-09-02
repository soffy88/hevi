/**
 * SystemStatus — 后端连接状态诊断组件
 *
 * 显示:
 *   - Backend 连接状态 (Connected / Offline)
 *   - API base URL
 *   - 运行模式 (REAL / MOCK)
 *   - Latency (ms)
 *   - Authentication 状态
 *
 * 位置: TopNav / Account / System Status
 */

'use client';

import { useEffect, useState } from 'react';
import { checkBackendHealth } from '@/lib/backend-health';
import { USE_MOCK, API_BASE } from '@/lib/runtime-config';

export function SystemStatus() {
  const [health, setHealth] = useState<{ state: string; latencyMs?: number } | null>(null);
  const [authStatus, setAuthStatus] = useState<'logged in' | 'logged out'>('logged out');
  const [lastCheck, setLastCheck] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Initial health check on mount
  useEffect(() => {
    async function initialCheck() {
      try {
        const result = await checkBackendHealth();
        setHealth({
          state: result.state,
          latencyMs: result.latencyMs,
        });
        setLastCheck(new Date());
        setError(null);
      } catch (err: unknown) {
        setError(
          (err as Error).message ||
            'Failed to check backend health'
        );
        setHealth({
          state: 'offline' as const,
        });
        setLastCheck(new Date());
      }
    }

    initialCheck();
  }, []);

  // Periodic health re-check every 30 seconds
  useEffect(() => {
    let alive = true;
    const intervalId = setInterval(async () => {
      if (!alive) return;
      try {
        const result = await checkBackendHealth();
        setHealth({
          state: result.state,
          latencyMs: result.latencyMs,
        });
        setLastCheck(new Date());
        setError(null);
      } catch (err: unknown) {
        setError(
          (err as Error).message ||
            'Failed to check backend health'
        );
        setHealth({
          state: 'offline' as const,
        });
        setLastCheck(new Date());
      }
    }, 30_000);

    return () => {
      alive = false;
      clearInterval(intervalId);
    };
  }, []);

  // Auth status from auth store
  useEffect(() => {
    import('@/lib/auth-store').then(({ isAuthenticated }) => {
      setAuthStatus(isAuthenticated() ? 'logged in' : 'logged out');
    });
  }, []);

  const mode = USE_MOCK ? 'MOCK' : 'REAL';

  const statusClass =
    health?.state === 'healthy' ? 'status-healthy'
    : health?.state === 'degraded' ? 'status-degraded'
    : 'status-offline';

  const modeClass = mode === 'REAL' ? 'mode-real' : 'mode-mock';

  return (
    <div className="system-status">
      <div className="system-status__row">
        <span className="system-status__label">Backend</span>
        <span className={statusClass}>
          {health?.state === 'healthy' ? 'Connected' : health?.state === 'degraded' ? 'Degraded' : 'Offline'}
        </span>
      </div>

      <div className="system-status__row">
        <span className="system-status__label">API</span>
        <span className="system-status__url">{API_BASE}</span>
      </div>

      <div className="system-status__row">
        <span className="system-status__label">Mode</span>
        <span className={modeClass}>{mode}</span>
      </div>

      {health?.latencyMs !== undefined && (
        <div className="system-status__row">
          <span className="system-status__label">Latency</span>
          <span>{health.latencyMs} ms</span>
        </div>
      )}

      {authStatus && (
        <div className="system-status__row">
          <span className="system-status__label">Authentication</span>
          <span>{authStatus}</span>
        </div>
      )}

      {error && (
        <div className="system-status__row system-status__row--error">
          <span className="system-status__label">Error</span>
          <span>{error}</span>
        </div>
      )}

      {lastCheck && (
        <div className="system-status__row">
          <span className="system-status__label">Last Check</span>
          <span>{lastCheck.toLocaleTimeString()}</span>
        </div>
      )}
    </div>
  );
}