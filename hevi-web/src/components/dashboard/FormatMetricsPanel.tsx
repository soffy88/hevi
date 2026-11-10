'use client';

import { useEffect, useState } from 'react';
import { studioApi } from '@/lib/api-client';

type Row = { format: string; selected: number; auto_changed: number; storyboard_edits: number; render_started: number; render_completed: number; completion_rate: number | null };

const LABELS: Record<string, string> = {
  auto: '自动', history_scene: '历史现场', digital_human: '数字人口播', live_drama: '真人短剧',
  comic_drama: '漫剧', animation: '动画', explainer: '知识讲解', material_cut: '素材剪辑', unknown: '未标注',
};

export function FormatMetricsPanel() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [totals, setTotals] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    studioApi.formatMetrics()
      .then((data) => { setRows(data.formats as Row[]); setTotals(data.totals); })
      .catch(() => setRows(null));
  }, []);

  if (!rows) return null;

  return (
    <section className="hevi-task-section" aria-label="出品形式数据">
      <div className="hevi-task-section__head">
        <div>
          <h2>出品形式数据</h2>
          <p>形式选择、自动被改选、分镜确认前修改次数与完成率（仅管理员）。</p>
        </div>
        <span>{String(totals?.selections ?? 0)} 次选择 · 完成率 {totals?.completion_rate == null ? '—' : `${Math.round(Number(totals.completion_rate) * 100)}%`}</span>
      </div>
      {rows.length === 0 ? <div className="hevi-task-empty">还没有形式选择数据。</div> : (
        <div className="hevi-task-table-wrap">
          <table className="hevi-task-table">
            <thead><tr><th>形式</th><th>选择</th><th>自动被改选</th><th>分镜修改</th><th>开始渲染</th><th>完成</th><th>完成率</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.format}>
                  <td>{LABELS[row.format] ?? row.format}</td>
                  <td>{row.selected}</td>
                  <td>{row.auto_changed}</td>
                  <td>{row.storyboard_edits}</td>
                  <td>{row.render_started}</td>
                  <td>{row.render_completed}</td>
                  <td>{row.completion_rate == null ? '—' : `${Math.round(row.completion_rate * 100)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
