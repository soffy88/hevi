/**
 * The former ViMax UI called endpoints that are not registered by the current HEVI API.
 * Keep the prototype in ViMaxConsole.legacy-20261018.tsx; do not submit requests to
 * nonexistent endpoints until the backend contract and capability gates are implemented.
 */
'use client';

import Link from 'next/link';

export function ViMaxConsole() {
  return (
    <section className="vimax-console space-y-4" aria-labelledby="vimax-unavailable-title">
      <div className="dp-card">
        <h1 id="vimax-unavailable-title" className="text-xl font-semibold">ViMax 高级功能暂不可用</h1>
        <p className="text-sm text-zinc-400">
          当前部署未注册 ViMax 的创意转视频、小说转视频、照片入戏和 Provider Presets API。
          为避免把任务提交到不存在的后端端点，这个入口已安全停用；原 UI 原型已保留，待后端契约补齐后再恢复。
        </p>
        <div className="flex flex-wrap gap-3">
          <Link className="tj-btn tj-btn--primary" href="/studio">打开标准生产台</Link>
          <Link className="tj-btn" href="/director-pipeline">打开导演流水线</Link>
        </div>
      </div>
    </section>
  );
}
