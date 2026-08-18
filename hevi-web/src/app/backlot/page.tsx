// hevi-web/src/app/backlot/page.tsx - 活态制片状态板主页面
"use client";

import { useState, useEffect } from "react";
import StatusPanel from "@/components/backlog/StatusPanel";
import DecisionPanel from "@/components/backlog/DecisionPanel";
import PlaybackPanel from "@/components/backlog/PlaybackPanel";

interface PageProps {
  searchParams: {
    run_id?: string;
  };
}

export default function BacklotDashboard({ searchParams }: PageProps) {
  const { run_id } = searchParams;
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchEvents() {
      if (!run_id) return;
      try {
        const res = await fetch(`/api/backlog/runs/${run_id}/events?limit=50`);
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const data = await res.json();
        setEvents(data.events || []);
      } catch (err) {
        console.error("Failed to fetch events:", err);
      } finally {
        setLoading(false);
      }
    }

    if (run_id) {
      fetchEvents();
    }
  }, [run_id]);

  const handleDecision = async (stage: string, comment: string) => {
    try {
      const res = await fetch(`/api/backlog/runs/${run_id}/events`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          stage,
          event_type: "stage_done",
          payload: { comment },
        }),
      });
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      const data = await res.json();
      // Refresh events after decision
      const eventsRes = await fetch(`/api/backlog/runs/${run_id}/events?limit=50`);
      if (eventsRes.ok) {
        const eventsData = await eventsRes.json();
        setEvents(eventsData.events || []);
      }
      return data;
    } catch (error) {
      console.error("Decision error:", error);
      throw error;
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-4 font-sans">
      <div className="max-w-7xl mx-auto">
        <nav className="flex justify-between items-center mb-8">
          <a href="/backlot" className="text-xl font-bold text-gray-900">
            Hevi 活态制片状态板
          </a>
          {run_id && (
            <div className="text-sm text-gray-500">
              当前 Run: {run_id}
            </div>
          )}
        </nav>

        <div className="grid md:grid-cols-3 gap-6">
          {/* 状态仪表盘 + 事件流 */}
          <div className="col-span-1 md:col-span-2 space-y-6">
            <StatusPanel run_id={run_id || ""} />
            
            <div className="bg-white rounded-lg shadow p-4">
              <h3 className="text-lg font-medium mb-4 flex items-center">
                <span className="text-blue-600 mr-2">事件流</span>
                <span className="text-xs text-gray-500 flex-none">
                  {events.length} 条事件
                </span>
              </h3>
              {loading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent" />
                  <span className="text-sm text-gray-600 ml-2">正在加载事件...</span>
                </div>
              ) : events.length === 0 ? (
                <p className="text-sm text-gray-500">暂无事件</p>
              ) : (
                <div className="max-h-96 overflow-y-auto">
                  {events.map((event, index) => (
                    <div
                      key={index}
                      className="event-item mb-2 p-3 bg-gray-50 rounded flex justify-between items-center"
                    >
                      <div>
                        <span className="font-medium text-sm">
                          {event.event_type}
                        </span>
                        {event.payload?.comment && (
                          <span className="text-xs text-gray-600 ml-2">
                            {event.payload.comment}
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-gray-500">
                        {new Date(event.created_at * 1000).toLocaleTimeString()}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* 审批门面板 + 回放面板 */}
          <div className="space-y-6">
            <DecisionPanel
              onDecision={handleDecision}
              stages={["剧本", "分镜", "资源", "渲染", "审核", "发布"]}
            />
            <PlaybackPanel run_id={run_id || ""} />
          </div>
        </div>
      </div>
    </div>
  );
}