/** v9.1 实时任务进度 + 状态融合:useTaskWebSocket。
 *
 * 连接 ``ws://<host>/api/ws/tasks``,订阅服务端广播的 task_update 事件
 * (每个 TaskRun 状态变更都会广播,见 hevi/core/ws_manager.py),替换
 * 确稿台/大盘的 3 秒轮询。与旧版的关键差异 —— 状态融合在 Hook 内完成:
 *
 *   * **输入**: 接收初始任务列表(来自 ``GET /api/dashboard/tasks`` 的 REST 快照),
 *     通过 ``seedTasks()`` 以权威快照替换,通过 ``appendTasks()`` 追加更早分页;
 *   * **融合**: 收到 WS 广播时按 task_id 精准命中行并就地更新(新对象引用,
 *     配合 React.memo 只重绘变化行); 新 task_id 动态插入列表最前方;
 *   * **连接管理**: 指数退避重连(1s→2s→…→15s 封顶),页面隐藏时暂停,
 *     心跳 25s "ping" 保活。
 */

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

const WS_PATH = '/api/ws/tasks';
const HEARTBEAT_MS = 25_000;
const MAX_BACKOFF_MS = 15_000;

export interface TaskUpdatePayload {
  type: 'task_update';
  task_id: string;
  status: string;
  progress: number;
  /** 附加字段(如 error/stage)。 */
  [key: string]: unknown;
}

/** 任意与大盘任务行兼容的结构(task_id 为融合主键)。 */
export interface RealtimeTaskLike {
  task_id: string;
}

export interface TaskWebSocketOptions<T extends RealtimeTaskLike> {
  /** 每次融合回调(prevStatus 为 null 表示新任务):统计卡片据此增减计数。 */
  onTaskUpdate?: (payload: TaskUpdatePayload, prevStatus: string | null) => void;
}

export interface TaskWebSocketState<T extends RealtimeTaskLike> {
  /** 连接状态:已连接时任务更新实时到达;reconnecting 时仍保留旧数据。 */
  connected: boolean;
  reconnecting: boolean;
  lastError: string | null;
  /** 融合后的实时任务列表(按创建序, 新任务在队首)。 */
  tasks: T[];
  /** 按 task_id 的最新广播(保留供排障/测试)。 */
  updates: Record<string, TaskUpdatePayload>;
  /** 以权威 REST 快照替换列表(分页/过滤切换后调用)。 */
  seedTasks: (tasks: T[]) => void;
  /** 追加更早的历史分页(去重)。 */
  appendTasks: (older: T[]) => void;
}

function resolveWsUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_WS_URL;
  if (explicit) return explicit;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${WS_PATH}`;
}

export function useTaskWebSocket<T extends RealtimeTaskLike>(
  initialTasks: T[] = [],
  options: TaskWebSocketOptions<T> = {},
): TaskWebSocketState<T> {
  const [tasks, setTasks] = useState<T[]>(() => [...initialTasks]);
  const [updates, setUpdates] = useState<Record<string, TaskUpdatePayload>>({});
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(0);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const closedByCleanup = useRef(false);

  /** WS 广播 → 就地融合:命中行替换(新引用), 新 task_id 插到队首。 */
  const applyUpdate = useCallback((payload: TaskUpdatePayload) => {
    if (payload.type !== 'task_update') return;
    setUpdates(previous => ({ ...previous, [payload.task_id]: payload }));

    const patch: Record<string, unknown> = {
      status: payload.status,
      progress: payload.progress,
      updated_at: new Date().toISOString(),
      ...(typeof payload.error === 'string' ? { error_log: payload.error } : {}),
    };
    setTasks(previous => {
      const index = previous.findIndex(item => item.task_id === payload.task_id);
      if (index >= 0) {
        const prevStatus = (previous[index] as { status?: unknown }).status as
          | string
          | undefined;
        options.onTaskUpdate?.(payload, prevStatus ?? null);
        const next = [...previous];
        // 只重建命中行, 其余行保持引用稳定 → React.memo 跳过未变化行。
        next[index] = { ...next[index], ...patch };
        return next;
      }
      options.onTaskUpdate?.(payload, null);
      const fresh = {
        ...patch,
        task_id: payload.task_id,
        created_at: new Date().toISOString(),
      } as unknown as T;
      return [fresh, ...previous];
    });
  }, []);

  /** 权威 REST 快照替换(过滤/翻页后调用), 同时清空广播回放表。 */
  const seedTasks = useCallback((next: T[]) => {
    setTasks([...next]);
    setUpdates({});
  }, []);

  /** 追加更早分页, 按 task_id 去重(新任务保留在队首)。 */
  const appendTasks = useCallback((older: T[]) => {
    setTasks(previous => {
      const known = new Set(previous.map(item => item.task_id));
      const added = older.filter(item => !known.has(item.task_id));
      if (added.length === 0) return previous;
      return [...previous, ...added];
    });
  }, []);

  useEffect(() => {
    let disposed = false;
    closedByCleanup.current = false;

    const clearHeartbeat = () => {
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
    };

    const connect = () => {
      if (disposed || closedByCleanup.current) return;
      setReconnecting(backoffRef.current > 0);
      setLastError(null);
      let socket: WebSocket;
      try {
        socket = new WebSocket(resolveWsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        backoffRef.current = 0;
        setConnected(true);
        setReconnecting(false);
        clearHeartbeat();
        heartbeatRef.current = setInterval(() => {
          if (socketRef.current?.readyState === WebSocket.OPEN) {
            socketRef.current.send('ping');
          }
        }, HEARTBEAT_MS);
      };

      socket.onmessage = (event: MessageEvent<string>) => {
        try {
          const payload = JSON.parse(event.data as string) as TaskUpdatePayload;
          applyUpdate(payload);
        } catch {
          // 非 JSON(如 "pong")忽略。
        }
      };

      socket.onerror = () => {
        setLastError('实时进度通道异常,将自动重连');
      };

      socket.onclose = () => {
        clearHeartbeat();
        if (disposed || closedByCleanup.current) return;
        setConnected(false);
        setReconnecting(true);
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (disposed || closedByCleanup.current) return;
      const delay = Math.min(
        MAX_BACKOFF_MS,
        backoffRef.current === 0 ? 1000 : backoffRef.current * 2,
      );
      backoffRef.current = delay;
      window.setTimeout(() => {
        if (!disposed && !closedByCleanup.current) connect();
      }, delay);
    };

    connect();

    // 页面隐藏时暂停重连与心跳,节省资源;恢复后立即补连。
    const onVisibility = () => {
      if (document.hidden) {
        closedByCleanup.current = true;
        clearHeartbeat();
        socketRef.current?.close();
      } else {
        closedByCleanup.current = false;
        if (socketRef.current?.readyState !== WebSocket.OPEN) connect();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      disposed = true;
      closedByCleanup.current = true;
      clearHeartbeat();
      document.removeEventListener('visibilitychange', onVisibility);
      socketRef.current?.close();
    };
  }, [applyUpdate]);

  return { connected, reconnecting, lastError, tasks, updates, seedTasks, appendTasks };
}
