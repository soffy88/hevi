/**
 * useBackendStatus — 轻量级后端连接状态钩子
 *
 * - 仅判断后端是否在线 (HTTP 200 即 online)
 * - 定期重新检测 (30s)
 * - 提供 recheck() 手动重试
 * - 用于 TopNav 的 "Online/Offline" 指示
 */
'use client';

import { useEffect, useState, useCallback } from 'react';
import { checkBackendHealth } from '@/lib/backend-health';

export function useBackendStatus(pollIntervalMs = 30_000) {
  const [online, setOnline] = useState(false);
  const [checking, setChecking] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  const recheck = useCallback(async () => {
    setChecking(true);
    try {
      const health = await checkBackendHealth();
      setOnline(health.state === 'healthy' || health.state === 'degraded');
      setLastError(null);
    } catch (err) {
      setOnline(false);
      setLastError((err as Error)?.message || 'unknown error');
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    recheck();
    const interval = setInterval(recheck, pollIntervalMs);
    return () => clearInterval(interval);
  }, [recheck, pollIntervalMs]);

  return { online, checking, lastError, recheck };
}
