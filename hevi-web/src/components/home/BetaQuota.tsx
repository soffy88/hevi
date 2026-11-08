'use client';

/**
 * 公测配额提示(S10)。后端强制执行：每天 5 条成片、单条 ≤60s、同时 1 个任务。
 * 这里只显示今日剩余次数，避免用户提交后才发现超限。
 */
import { useEffect, useState } from 'react';
import { quotaApi, USE_MOCK, type QuotaStatus } from '@/lib/api-client';
import { isAuthenticated } from '@/lib/auth-store';

export function BetaQuota({ refreshKey }: { refreshKey?: unknown }) {
  const [quota, setQuota] = useState<QuotaStatus | null>(null);

  useEffect(() => {
    if (USE_MOCK || !isAuthenticated()) return;
    let live = true;
    const load = () => {
      quotaApi.status()
        .then((q) => { if (live) setQuota(q); })
        .catch(() => { /* 未登录/网络失败时静默 */ });
    };
    load();
    const timer = window.setInterval(load, 20000);
    return () => { live = false; window.clearInterval(timer); };
  }, [refreshKey]);

  if (!quota) return null;

  return (
    <div className="hevi-beta-quota" role="status">
      <span className="hevi-beta-quota__tag">公测免费</span>
      <span>
        今日剩余 <strong>{quota.remaining}</strong>/{quota.daily_limit} 条
      </span>
      <span className="hevi-beta-quota__sep">·</span>
      <span>单条 ≤{quota.max_duration_s} 秒</span>
      <span className="hevi-beta-quota__sep">·</span>
      <span>同时 {quota.max_concurrent} 个任务</span>
      {quota.active_jobs > 0 && (
        <span className="hevi-beta-quota__busy">有任务进行中</span>
      )}
    </div>
  );
}
