"use client";

/* DashboardPanel.tsx - Backlot 实时状态看板(已落实 B7) */

import { useEffect, useState } from "react";

interface DashboardProps {
  run_id: string;
  refresh_interval_ms?: number;
}

interface RunStatus {
  event_count: number | null;
  stages: Record<string, string>;
  cost_usd: number | null;
  last_heartbeat: string | null;
  failed: boolean | null;
  updated_at: string | null;
}

interface RunEvent {
  event_type: string;
  stage: string;
  payload: Record<string, unknown>;
  ts: string;
}

export default function DashboardPanel({ run_id, refresh_interval_ms = 3000 }: DashboardProps) {
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [events, setEvents] = useState<RunEvent[] | null>(null);
  const [mounted, setMounted] = useState(true);

  useEffect(() => {
    let timer: NodeJS.Timeout;

    async function fetchStatus() {
      if (!mounted) return;
      try {
        const statusRes = await fetch(`/api/backlot/runs/${run_id}/status`);
        if (statusRes.ok) {
          const data = await statusRes.json() as RunStatus;
          setStatus(data);
        }
        const eventsRes = await fetch(`/api/backlot/runs/${run_id}/events?limit=200`);
        if (eventsRes.ok) {
          const data = await eventsRes.json() as { events: RunEvent[] };
          setEvents(data.events);
        }
      } catch (e) {
        console.error("backlot dashboard fetch error:", e);
      }
    }

    fetchStatus();
    timer = setInterval(fetchStatus, refresh_interval_ms);

    return () => {
      setMounted(false);
      clearInterval(timer);
    };
  }, [run_id, refresh_interval_ms, mounted]);

  if (!status && !events) {
    return (
      <div className="bg-white rounded-lg p-6 text-center">
        <div className="animate-spin rounded-full h-12 w-12 mx-auto mb-4 border-b-2 border-primary"></div>
        <p className="text-muted-foreground">加载状态...</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow-sm p-6 min-h-[400px]">
      {/* 状态概览卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {status && (
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-2">事件总计</h4>
            <p className="text-3xl font-bold">{status.event_count ?? 0}</p>
          </div>
        )}
        {status && (
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-2">花费</h4>
            <p className="text-3xl font-bold">
              {status.cost_usd !== null ? `$${status.cost_usd}` : "未知"}
            </p>
          </div>
        )}
        {status && (
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-2">最后心跳</h4>
            <p className="text-sm text-muted-foreground">
              {status.last_heartbeat ? new Date(status.last_heartbeat).toLocaleTimeString() : "从未"}
            </p>
          </div>
        )}
        {status && (
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-2">状态</h4>
            <p className={status.failed ? "text-red-600" : "text-green-600"}>
              {status.failed ? "失败" : "正常"}
            </p>
          </div>
        )}
      </div>

      {/* 阶段亮灯情况 */}
      {status && status.stages && Object.keys(status.stages).length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
          {Object.entries(status.stages).map(([stage, event_type]) => (
            <div
              key={stage}
              className="p-3 rounded bg-primary/5 text-sm"
              style={{ borderColor: event_type === "stage_fail" ? "red" : "var(--primary)" }}
            >
              <span className="font-medium capitalize">{stage}</span>
              <span className="ml-2 text-xs capitalize">{event_type}</span>
            </div>
          ))}
        </div>
      )}

      {/* 最近事件流 */}
      <div>
        <h4 className="text-sm font-medium text-muted-foreground mb-3">最近事件</h4>
        {events && events.length > 0 ? (
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {events.map((ev, i) => (
              <div
                key={i}
                className="p-2 rounded bg-gray-50 text-xs"
                style={{ color: ev.event_type === "note" ? "inherit" : "var(--primary)" }}
              >
                <span className="font-medium capitalize">{ev.event_type}</span>
                <span className="ml-2">@{ev.stage}</span>
                <span className="ml-2 text-muted-foreground">{new Date(ev.ts).toLocaleTimeString()}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">暂无事件</p>
        )}
      </div>
    </div>
  );
}
