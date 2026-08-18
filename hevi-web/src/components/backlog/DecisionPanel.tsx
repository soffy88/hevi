// DecisionPanel.tsx - Stage approval/rejection buttons
"use client";

import { useState } from "react";

interface DecisionPanelProps {
  onDecision: (stage: string, comment: string) => Promise<any>;
  isPending?: boolean;
  stages?: string[]; // optional: list of stages to show buttons for
}

export default function DecisionPanel({ onDecision, isPending = false, stages = [] }: DecisionPanelProps) {
  const [localPending, setLocalPending] = useState(false);
  const [lastAction, setLastAction] = useState<{ stage: string; action: string; time: Date } | null>(null);

  const handleDecision = async (stage: string, action: "approve" | "reject") => {
    const comment = window.prompt(`${action === "approve" ? "批准" : "拒绝"} ${stage}？(可选备注)`) || "";
    
    setLocalPending(true);
    try {
      await onDecision(stage, comment);
      setLastAction({ stage, action, time: new Date() });
    } catch (error) {
      console.error("Decision failed:", error);
      alert("决策失败: " + (error instanceof Error ? error.message : String(error)));
    } finally {
      setLocalPending(false);
    }
  };

  // Default stages if not provided
  const stageList = stages.length > 0 ? stages : [
    "剧本", "分镜", "资源", "渲染", "审核", "发布"
  ];

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-medium mb-4 flex items-center">
        <span className="text-purple-600 mr-2">审批门</span>
      </h3>
      
      <div className="space-y-3">
        {stageList.map((stage) => (
          <div key={stage} className="flex items-center justify-between p-3 bg-gray-50 rounded">
            <span className="text-sm font-medium">{stage}</span>
            <div className="flex gap-2">
              <button
                onClick={() => handleDecision(stage, "approve")}
                disabled={isPending || localPending}
                className="px-3 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                批准
              </button>
              <button
                onClick={() => handleDecision(stage, "reject")}
                disabled={isPending || localPending}
                className="px-3 py-1 text-xs bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                拒绝
              </button>
            </div>
          </div>
        ))}
      </div>

      {lastAction && (
        <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded">
          <p className="text-xs text-green-800 flex items-center">
            <span className="mr-2">最近操作:</span>
            <strong className="capitalize">{lastAction.stage}</strong>{" "}
            {lastAction.action === "approve" ? "已批准" : "已拒绝"}
            <span className="ml-2 text-xs text-gray-500">
              （{lastAction.time.toLocaleTimeString()}）
            </span>
          </p>
        </div>
      )}
    </div>
  );
}