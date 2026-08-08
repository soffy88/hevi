/** v9.1 任务大盘:SQLite TaskRun 历史 + WebSocket 实时进度。
 *
 * 数据流:
 *   1. 挂载 → REST 拉取第一批历史(骨架屏 Skeleton 直至完成);
 *   2. 快照交给 useTaskWebSocket.seedTasks() 作为实时融合基线;
 *   3. WS 广播按 task_id 就地融合(新任务插队首), React.memo 保证只重绘变化行;
 *   4. 「加载更多」把更早分页 append 到队尾(去重), 统计卡片计数实时增减。
 */

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { dashboardApi } from '@/lib/api-client';
import { syncAuthToken } from '@/lib/auth-store';
import { useTaskWebSocket } from '@/hooks/useTaskWebSocket';
import { TaskRow } from '@/components/dashboard/TaskRow';
import { StatsSkeleton, TaskStats } from '@/components/dashboard/TaskStats';
import type { DashboardTask } from '@/types/api';

const PAGE_SIZE = 20;

const FILTER_TABS: Array<{ key: string; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '进行中' },
  { key: 'completed', label: '已完成' },
  { key: 'failed', label: '失败' },
];

export function TaskDashboard() {
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});

  // WS 融合回调:统计卡片精确增减(旧状态 -1, 新状态 +1, 新任务 +1)。
  const onTaskUpdate = useCallback(
    (_payload: { task_id: string; status: string }, prevStatus: string | null) => {
      const payload = _payload as unknown as { status: string };
      setCounts(previous => {
        const next = { ...previous };
        if (prevStatus && prevStatus !== payload.status) {
          next[prevStatus] = Math.max(0, (next[prevStatus] ?? 0) - 1);
        }
        next[payload.status] = (next[payload.status] ?? 0) + 1;
        return next;
      });
    },
    [],
  );

  const ws = useTaskWebSocket<DashboardTask>([], { onTaskUpdate });
  const { tasks, seedTasks, appendTasks } = ws;

  const loadFirstPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await dashboardApi.listTasks({ limit: PAGE_SIZE, offset: 0 });
      setTotal(page.total);
      setOffset(page.items.length);
      setCounts(previous => ({ ...(page.status_counts ?? {}), ...previous }));
      seedTasks(page.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '任务大盘加载失败');
    } finally {
      setLoading(false);
    }
  }, [seedTasks]);

  useEffect(() => {
    syncAuthToken();
    void loadFirstPage();
  }, [loadFirstPage]);

  const loadMore = useCallback(async () => {
    if (loadingMore || offset >= total) return;
    setLoadingMore(true);
    try {
      const page = await dashboardApi.listTasks({ limit: PAGE_SIZE, offset });
      setTotal(page.total);
      setOffset(previous => previous + page.items.length);
      appendTasks(page.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '加载更多失败');
    } finally {
      setLoadingMore(false);
    }
  }, [appendTasks, loadingMore, offset, total]);

  const visible = useMemo(
    () => (statusFilter === 'all' ? tasks : tasks.filter(item => item.status === statusFilter)),
    [tasks, statusFilter],
  );

  const loadedAll = total > 0 && tasks.length >= total;

  return (
    <div className="ex-v6">
      <header className="ex-v6__hero">
        <p className="ex-v6__eyebrow">HEVI · TASK DASHBOARD v9.1</p>
        <h1>生成任务大盘</h1>
        <p>SQLite TaskRun 全量历史 + WebSocket 实时进度：提交装配后无需刷新，进度条平滑跳动。</p>
      </header>

      {ws.connected
        ? <div className="ex-v6__restore">🔌 实时进度通道已连接</div>
        : <div className="ex-v6__restore is-offline">⟳ 实时通道{ws.reconnecting ? '重连中' : '未连接'}，将自动恢复</div>}

      {loading ? <StatsSkeleton /> : <TaskStats total={total} counts={counts} />}

      <div className="tdash__filters" role="tablist" aria-label="状态过滤">
        {FILTER_TABS.map(tab => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={statusFilter === tab.key}
            className={statusFilter === tab.key ? 'is-active' : ''}
            onClick={() => setStatusFilter(tab.key)}
          >
            {tab.label}
            {tab.key !== 'all' && <span>{(counts[tab.key] ?? 0)}</span>}
          </button>
        ))}
      </div>

      {error && <div className="ex-v6__error" role="alert">{error}</div>}

      {loading && tasks.length === 0 && (
        <div className="tdash__skeleton-list" aria-busy="true">
          {[0, 1, 2, 3].map(i => <div key={i} className="tdash__skeleton-row" />)}
        </div>
      )}

      {!loading && tasks.length === 0 && !error && (
        <p className="tdash__empty">还没有生成任务 —— 去解说中心/导演台提交一条装配任务吧。</p>
      )}

      {visible.length > 0 && (
        <div className="tdash__list">
          {visible.map(task => <TaskRow key={task.task_id} task={task} />)}
        </div>
      )}

      {statusFilter !== 'all' && visible.length === 0 && !loading && tasks.length > 0 && (
        <p className="tdash__empty">当前过滤条件下暂无任务。</p>
      )}

      {!loadedAll && tasks.length > 0 && (
        <div className="tdash__pager">
          <button
            type="button"
            className="ex-v6__secondary"
            disabled={loadingMore}
            onClick={() => void loadMore()}
          >
            {loadingMore ? '加载中…' : '加载更早任务'}
          </button>
          <span>{tasks.length} / {total}</span>
        </div>
      )}
    </div>
  );
}
