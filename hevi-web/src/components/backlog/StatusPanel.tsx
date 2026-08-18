// StatusPanel.tsx - Displays run status metrics, event counts, and progress indicators
// File: hevi-web/src/components/backlog/StatusPanel.tsx

"use client";

import { useEffect, useState } from "react";

interface StatusProps {
  run_id: string;
}

export default function StatusPanel({ run_id }: StatusProps) {
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchStatus() {
      try {
        setLoading(true);
        const res = await fetch(`/api/backlog/runs/${run_id}/status`);
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const data = await res.json();
        setStatus(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    }

    if (run_id) {
      fetchStatus();
    }
  }, [run_id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-4 bg-gray-100 rounded-lg shadow">
        <div className="animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent" />
        <span className="text-sm text-gray-600 ml-2">正在加载状态数据...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center p-4 bg-red-50 rounded-lg border border-red-200">
        <div className="flex flex-col">
          <svg className="w-6 h-6 text-red-600" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M8.257 3.754a.25.25 0 0 1 .68-.19.25.25 0 0 0-.01-.82.25.25 0 0 0-.41-.66A.5.5 0 0 0 6.88 2h-2a.5.5 0 0 0-.5-.44H4a.5.5 0 0 0-.5.44v.75a.25.25 0 0 0 .25.25h.5a.25.25 0 0 0 .25-.25V2h7a.5.5 0 0 0 .5-.44v-.75a.25.25 0 0 0-asdf")
            />
          </svg>
        </div>
        <div className="text-red-600 ml-2">{error}</div>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="p-4 bg-gray-50 rounded-lg shadow">
        <p className="text-sm text-gray-600">无法获取状态数据</p>
      </div>
    );
  }

  const {
    event_count = 0,
    stages = {},
    cost_usd = 0,
    failed = false,
    last_heartbeat = Date.now() / 1000,
  } = status;

  // 颜色方案（使用现有样式库）
  return (
    <div className="bg-white rounded-lg shadow-lg p-4">
      <h3 className="text-lg font-medium mb-4 flex items-center">
        <span className="text-blue-600 mr-2">运行状态</span>
        <span className="text-xs text-gray-500 flex-none">
          {run_id || "当前运行"}
        </span>
      </h3>
      
      <div className="space-y-3">
        <div className="overflow-x-auto">
          <table className="min-w-full bg-white divide-y divide-gray-200">
            <thead className="bg-gray-100">
              <tr>
                <th className="px-6 py-2 text-left text-xs font-medium text-gray-700">指标</th>
                <th className="px-6 py-2 text-left text-xs font-medium text-gray-700">值</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              <tr className="bg-gray-50">
                <td className="px-6 py-2 text-sm text-gray-600">事件总数</td>
                <td className="px-6 py-2 font-medium">{event_count}</td>
              </tr>
              <tr className="bg-white">
                <td className="px-6 py-2 text-sm text-gray-600">预估成本</td>
                <td className="px-6 py-2 font-medium">${cost_usd.toFixed(2)}</td>
              </tr>
              <tr className="bg-gray-50">
                <td className="px-6 py-2 text-sm text-gray-600">是否失败</td>
                <td className="px-6 py-2 font-medium">
                  {failed ? (
                    <span className="text-red-600">是</span>
                  ) : (
                    <span className="text-green-600">否</span>
                  )}
                </td>
              </tr>
              <tr className="bg-white">
                <td className="px-6 py-2 text-sm text-gray-600">最后心跳</td>
                <td className="px-6 py-2 text-xs text-gray-500">
                  {new Date(last_heartbeat * 1000).toLocaleTimeString()}
                </td>
              </tr>
              {Object.entries(stages || {}).map(([stage, status]) => (
                <tr key={stage} className="striped:bg-white hover:bg-gray-50">
                  <td className="px-6 py-2 text-sm font-medium text-gray-900">
                    {stage} 进度
                  </td>
                  <td className="px-6 py-2">
                    <div className="flex">
                      <span className="w-16 text-xs text-left">{status}</span>
                      <div className="flex-1">
                        <div className="w-full bg-gray-200 rounded-full h-2">
                          <div 
                            className={`bg-${
                              status === "done" ? "green-500" : 
                              status === "failed" ? "red-500" : 
                              "yellow-500"
                            } rounded-full h-2`}
                            style={{ width: status === "done" ? "100%" : status === "failed" ? "0%" : "50%" }}
                          ></div>
                        </div>
                      </div>
                      <span className="w-16 text-xs text-right capitalize">
                        {status === "done" ? "完成" : status === "failed" ? "失败" : "进行中"}
                      </span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}