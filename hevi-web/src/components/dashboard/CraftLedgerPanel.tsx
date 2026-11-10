'use client';

import { useEffect, useState } from 'react';
import { studioApi } from '@/lib/api-client';

type RouteRow = { key: string; shots: number; seconds: number; cny: number; elapsed_s?: number };
type ModelRow = { key: string; shots: number; seconds: number; cny: number };
type RecentRow = {
  ts: number; kind: string; plan_id: string; format: string; shot: number;
  route: string; model: string; seconds: number; cny: number; status: string;
};

const ROUTE_LABELS: Record<string, string> = {
  code: '代码动画', blender: 'Blender', generation: '生成', user_media: '用户素材',
  mixed: '代码+生成', overhead: '合成/配音', unknown: '未标注',
};

type Ledger = {
  rows: number; plans: number; total_seconds: number; total_cny: number;
  by_route: RouteRow[]; by_model: ModelRow[]; recent: RecentRow[];
};

export function CraftLedgerPanel() {
  const [data, setData] = useState<Ledger | null>(null);

  useEffect(() => {
    studioApi.craftLedger(200).then((data) => setData(data as unknown as Ledger)).catch(() => setData(null));
  }, []);

  if (!data) return null;

  return (
    <section className="hevi-task-section" aria-label="成本账本">
      <div className="hevi-task-section__head">
        <div>
          <h2>成本账本</h2>
          <p>每个镜头的路线、模型、秒数与金额（报价按公开单价估算；本地/离线 ¥0）。仅管理员。</p>
        </div>
        <span>{data.plans} 个计划 · {Math.round(data.total_seconds)} 秒 · ¥{data.total_cny.toFixed(2)}</span>
      </div>
      {data.rows === 0 ? <div className="hevi-task-empty">还没有镜头报价。</div> : (
        <>
          <div className="hevi-task-table-wrap">
            <table className="hevi-task-table">
              <thead><tr><th>路线</th><th>镜头</th><th>秒数</th><th>金额</th><th>预计渲染</th></tr></thead>
              <tbody>
                {data.by_route.map((row) => (
                  <tr key={row.key}>
                    <td>{ROUTE_LABELS[row.key] ?? row.key}</td>
                    <td>{row.shots}</td>
                    <td>{row.seconds}</td>
                    <td>¥{row.cny.toFixed(2)}</td>
                    <td>{row.elapsed_s == null ? '—' : `${row.elapsed_s}s`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="hevi-task-table-wrap">
            <table className="hevi-task-table">
              <thead><tr><th>时间</th><th>计划</th><th>镜头</th><th>模型</th><th>秒数</th><th>金额</th></tr></thead>
              <tbody>
                {data.recent.slice(-12).reverse().map((row, index) => (
                  <tr key={`${row.plan_id}-${row.shot}-${index}`}>
                    <td>{new Date(row.ts * 1000).toLocaleString('zh-CN')}</td>
                    <td>{row.plan_id || '—'}</td>
                    <td>{row.shot || '—'}</td>
                    <td>{row.model || ROUTE_LABELS[row.route] || row.route}</td>
                    <td>{row.seconds}</td>
                    <td>¥{row.cny.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
