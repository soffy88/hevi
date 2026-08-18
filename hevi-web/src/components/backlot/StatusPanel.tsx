// StatusPanel.tsx - Displays run status: progress, event counts, etc.

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
        const res = await fetch(`/api/backlot/runs/${run_id}/status`);
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
      <div className="p-4 bg-white rounded-lg shadow">
        <div className="flex items-center space-x-2">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
          <span className="text-sm text-gray-500">Loading status...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
        <h3 className="text-sm font-medium text-red-800">Error loading status</h3>
        <p className="mt-1 text-xs text-red-600">{error}</p>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="p-4 bg-white rounded-lg shadow">
        <p className="text-sm text-gray-500">No status data available.</p>
      </div>
    );
  }

  // Assuming status has fields: event_count, stages, cost_usd, failed, last_heartbeat, etc.
  const { event_count = 0, stages = {}, cost_usd = 0, failed = false, last_heartbeat } = status;

  return (
    <div className="p-4 bg-white rounded-lg shadow">
      <h3 className="text-lg font-medium mb-4">Run Status</h3>
      <div className="space-y-3">
        <div className="flex justify-between">
          <span className="text-sm text-gray-600">Event Count:</span>
          <span className="font-medium">{event_count}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-sm text-gray-600">Estimated Cost:</span>
          <span className="font-medium">${cost_usd.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-sm text-gray-600">Failed:</span>
          <span className={`font-medium ${failed ? "text-red-600" : "text-green-600"}`}>
            {failed ? "Yes" : "No"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-sm text-gray-600">Last Heartbeat:</span>
          <span className="text-xs text-gray-500">
            {new Date(last_heartbeat * 1000).toLocaleTimeString()}
          </span>
        </div>
        {/* Stages progress */}
        <div className="mt-2">
          <span className="block text-sm font-medium mb-1">Stage Progress:</span>
          <div className="space-y-1">
            {Object.entries(stages).map(([stage, status]) => (
              <div key={stage} className="flex items-center">
                <span className="w-20 text-xs">{stage}:</span>
                <span className="flex-1 bg-gray-200 rounded-full h-2">
                  <div
                    className={`bg-${status === "done" ? "green-500" : status === "failed" ? "red-500" : "yellow-500"} h-2 rounded-full`}
                    style={{ width: status === "done" ? "100%" : status === "failed" ? "0%" : "50%" }}
                  ></div>
                </span>
                <span className="w-20 text-xs text-center">
                  {status === "done" ? "Done" : status === "failed" ? "Failed" : "In Progress"}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}