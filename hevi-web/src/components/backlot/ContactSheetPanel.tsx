"use client";

/* ContactSheetPanel.tsx — Backlot 分镜联系表审批门
 *
 * 每个场景一格: 真实缩略图 / 生成提示词 / 花了多少 / 实测质量分 / 审批状态。
 * approve / reject 直接写回后端状态(reason 必填, 后端 400 也会拒绝空理由)。
 */

import { useCallback, useEffect, useState } from "react";

export interface ShotQuality {
  score?: number | null;
  partial_score?: number | null;
  components?: Record<string, number | null>;
  measured?: Record<string, number>;
  unmeasured?: string[];
  notes?: string[];
  weights?: Record<string, number>;
  error?: string;
}

export interface ShotDecision {
  scene_id: string;
  decision: string;
  reason: string;
  reviewer: string;
  ts: string;
}

export interface BoardShot {
  scene_id: string;
  index: number;
  title: string;
  prompt: string;
  thumbnail: string;
  source_path: string;
  duration_s: number;
  cost_usd: number;
  status: "pending" | "approved" | "rejected";
  quality: ShotQuality;
  declared_score: number | null;
  decisions: ShotDecision[];
}

export interface BoardSummary {
  run_id: string;
  total: number;
  approved: number;
  rejected: number;
  pending: number;
  total_cost_usd: number;
  approved_cost_usd: number;
  rejected_cost_usd: number;
  quality_scored: number;
  quality_unmeasured: number;
  mean_quality: number | null;
  gate: "empty" | "awaiting_review" | "open" | "resolved_with_rejects";
}

interface ContactSheetPanelProps {
  run_id: string;
  reviewer?: string;
  api_base?: string;
}

const STATUS_STYLE: Record<string, string> = {
  pending: "bg-amber-100 text-amber-900",
  approved: "bg-emerald-100 text-emerald-900",
  rejected: "bg-rose-100 text-rose-900",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "待批",
  approved: "已批",
  rejected: "已否",
};

export default function ContactSheetPanel({
  run_id,
  reviewer = "web",
  api_base = "",
}: ContactSheetPanelProps) {
  const [shots, setShots] = useState<BoardShot[]>([]);
  const [summary, setSummary] = useState<BoardSummary | null>(null);
  const [sheetUrl, setSheetUrl] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const base = `${api_base}/api/backlot/runs/${run_id}`;

  const load = useCallback(async () => {
    try {
      const [shotsRes, sheetRes] = await Promise.all([
        fetch(`${base}/shots`),
        fetch(`${base}/contact-sheet`),
      ]);
      if (shotsRes.ok) {
        const data = (await shotsRes.json()) as { shots: BoardShot[]; summary: BoardSummary };
        setShots(data.shots);
        setSummary(data.summary);
      }
      if (sheetRes.ok) {
        const data = (await sheetRes.json()) as { sheet?: { path: string } | null };
        // 联络表落在 backlot 目录里, 由板面媒体端点提供(路径受根目录限制)
        setSheetUrl(data.sheet ? `${api_base}/api/backlot/media/${run_id}/contact_sheet.png` : null);
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoaded(true);
    }
  }, [base, api_base, run_id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(shot: BoardShot, decision: "approved" | "rejected") {
    const reason = (reasons[shot.scene_id] ?? "").trim();
    if (decision === "rejected" && !reason) {
      setError("否掉一个镜头必须写理由");
      return;
    }
    setBusy(shot.scene_id);
    setError(null);
    try {
      const res = await fetch(`${base}/shots/${encodeURIComponent(shot.scene_id)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, reason, reviewer }),
      });
      if (!res.ok) {
        const detail = await res.text();
        setError(`审批失败 (${res.status}): ${detail}`);
        return;
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  if (!loaded) {
    return <div className="p-4 text-sm text-muted-foreground">加载分镜联系表...</div>;
  }

  return (
    <section className="bg-white rounded-lg shadow-sm p-6">
      <header className="mb-4 flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-lg font-semibold">分镜联系表审批门</h3>
        {summary && (
          <span
            className="text-xs px-2 py-1 rounded"
            style={{
              background: summary.gate === "open" ? "#dcfce7" : "#fef3c7",
            }}
          >
            {summary.gate === "empty"
              ? "尚无分镜"
              : summary.gate === "open"
                ? "全部通过"
                : summary.gate === "resolved_with_rejects"
                  ? "已裁决(含否决)"
                  : `${summary.pending} 个待批`}
          </span>
        )}
      </header>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5 text-sm">
          <Stat label="镜头" value={String(summary.total)} />
          <Stat
            label="通过 / 否决 / 待批"
            value={`${summary.approved} / ${summary.rejected} / ${summary.pending}`}
          />
          <Stat label="总花费" value={`$${summary.total_cost_usd.toFixed(2)}`} />
          <Stat
            label="浪费在否决上"
            value={`$${summary.rejected_cost_usd.toFixed(2)}`}
          />
          <Stat
            label="实测均分"
            value={summary.mean_quality === null ? "未量测" : summary.mean_quality.toFixed(2)}
          />
        </div>
      )}

      {error && (
        <p className="mb-4 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded p-2">
          {error}
        </p>
      )}

      {sheetUrl && (
        <figure className="mb-6">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={sheetUrl}
            alt="storyboard contact sheet"
            className="w-full rounded border"
          />
          <figcaption className="text-xs text-muted-foreground mt-1">
            联络表由各场景实测的代表帧拼接而成
          </figcaption>
        </figure>
      )}

      {shots.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          这条 run 还没有登记分镜。流水线分镜完成后调 POST /shots 即可上板。
        </p>
      ) : (
        <ul className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {shots.map((shot) => (
            <li key={shot.scene_id} className="border rounded p-3 flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">
                  #{shot.index} {shot.title || shot.scene_id}
                </span>
                <span className={`text-xs px-2 py-0.5 rounded ${STATUS_STYLE[shot.status]}`}>
                  {STATUS_LABEL[shot.status] ?? shot.status}
                </span>
              </div>

              {shot.thumbnail ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`${api_base}/api/backlot/media/${run_id}/${encodeURIComponent(
                    shot.thumbnail.split("/").pop() ?? "",
                  )}`}
                  alt={`${shot.scene_id} 缩略图`}
                  className="w-full rounded"
                />
              ) : (
                <div className="w-full h-28 bg-gray-100 rounded flex items-center justify-center text-xs text-muted-foreground">
                  无实测缩略图
                </div>
              )}

              {shot.prompt && (
                <p className="text-xs text-muted-foreground line-clamp-3">提示词: {shot.prompt}</p>
              )}

              <div className="text-xs flex flex-wrap gap-x-3 gap-y-1">
                <span>成本 ${shot.cost_usd.toFixed(2)}</span>
                <span>时长 {shot.duration_s ? `${shot.duration_s.toFixed(2)}s` : "未量"}</span>
              </div>

              <QualityRow quality={shot.quality} declared={shot.declared_score} />

              <input
                className="border rounded px-2 py-1 text-xs"
                placeholder={
                  shot.status === "rejected" ? "改稿/重渲的理由(必填)" : "裁决备注(否决时必填)"
                }
                value={reasons[shot.scene_id] ?? ""}
                onChange={(e) =>
                  setReasons((prev) => ({ ...prev, [shot.scene_id]: e.target.value }))
                }
              />

              <div className="flex gap-2 mt-1">
                <button
                  className="text-xs px-3 py-1 rounded bg-emerald-600 text-white disabled:opacity-50"
                  disabled={busy === shot.scene_id}
                  onClick={() => void decide(shot, "approved")}
                >
                  通过
                </button>
                <button
                  className="text-xs px-3 py-1 rounded bg-rose-600 text-white disabled:opacity-50"
                  disabled={busy === shot.scene_id}
                  onClick={() => void decide(shot, "rejected")}
                >
                  否决
                </button>
              </div>

              {shot.decisions.length > 0 && (
                <ul className="text-[11px] text-muted-foreground space-y-0.5">
                  {shot.decisions.map((d, i) => (
                    <li key={i}>
                      {d.ts} · {d.reviewer} · {d.decision}
                      {d.reason ? ` · ${d.reason}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

function QualityRow({
  quality,
  declared,
}: {
  quality: ShotQuality;
  declared: number | null;
}) {
  if (quality.error) {
    return <p className="text-xs text-rose-700">质量未量测: {quality.error}</p>;
  }
  const components = quality.components ?? {};
  const parts = Object.entries(components)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `${k} ${(v as number).toFixed(2)}`);
  const unmeasured = quality.unmeasured ?? [];
  return (
    <div className="text-xs">
      <span className="font-medium">
        实测质量 {quality.score === null || quality.score === undefined
          ? `未给总分(部分 ${quality.partial_score?.toFixed(2) ?? "—"})`
          : quality.score.toFixed(2)}
      </span>
      {parts.length > 0 && <span className="text-muted-foreground"> · {parts.join(" / ")}</span>}
      {unmeasured.length > 0 && (
        <span className="text-amber-700"> · 未量测: {unmeasured.join("、")}</span>
      )}
      {declared !== null && (
        <span className="text-muted-foreground"> · 自报 {declared.toFixed(2)}(不参与判定)</span>
      )}
    </div>
  );
}
