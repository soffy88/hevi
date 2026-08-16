/** 大盘顶部统计概览:全部 / 进行中 / 已完成 / 失败。 */

'use client';

import type { ReactNode } from 'react';

export interface TaskStatsProps {
  total: number;
  counts: Record<string, number>;
}

const CARD_ORDER: Array<{ key: string; label: string; hint: string; tone: string }> = [
  { key: '', label: '全部任务', hint: '累计提交', tone: 'slate' },
  { key: 'running', label: '进行中', hint: '实时渲染中', tone: 'blue' },
  { key: 'completed', label: '已完成', hint: '可下载成片', tone: 'emerald' },
  { key: 'failed', label: '失败', hint: '需排查日志', tone: 'rose' },
];

function valueFor(key: string, total: number, counts: Record<string, number>): number {
  if (key === '') return total;
  return counts[key] ?? 0;
}

export function TaskStats({ total, counts }: TaskStatsProps) {
  return (
    <section className="tdash__stats" aria-label="任务统计概览">
      {CARD_ORDER.map(card => (
        <div key={card.key || 'all'} className={`tdash__stat is-${card.tone}`}>
          <strong>{valueFor(card.key, total, counts)}</strong>
          <span>{card.label}</span>
          <em>{card.hint}</em>
        </div>
      ))}
    </section>
  );
}

export function StatsSkeleton(): ReactNode {
  return (
    <div className="tdash__stats" aria-busy="true">
      {[0, 1, 2, 3].map(i => (
        <div key={i} className="tdash__stat is-skeleton" />
      ))}
    </div>
  );
}
