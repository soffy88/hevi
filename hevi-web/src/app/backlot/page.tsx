"use client";

/* Backlot 看板页面(已落实 B7) */

import DashboardPanel from "@/components/backlot/DashboardPanel";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";

function BacklotContent() {
  const params = useParams();
  const searchParams = useSearchParams();

  // 支持 ?run_id=xxx 或 /backlot/<id>
  const routeRunId = params.run_id;
  const run_id = (Array.isArray(routeRunId) ? routeRunId[0] : routeRunId) || searchParams.get("run_id");

  if (!run_id) {
    return (
      <div className="p-6 text-center">
        <h2 className="text-xl font-bold mb-4">Backlot 运行状态看板</h2>
        <p className="text-muted-foreground">缺少 run_id 参数</p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <header className="mb-6">
        <h1 className="text-3xl font-bold">Backlot 状态看板</h1>
        <p className="text-sm text-muted-foreground mt-1">
          运行 ID: <code className="bg-gray-100 px-2 py-1 rounded">{run_id}</code>
        </p>
      </header>
      <DashboardPanel run_id={run_id} />
    </div>
  );
}

export default function BacklotPage() {
  return (
    <Suspense fallback={<div className="p-6 text-center">加载状态看板...</div>}>
      <BacklotContent />
    </Suspense>
  );
}
