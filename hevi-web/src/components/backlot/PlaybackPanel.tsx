"use client";

/* PlaybackPanel.tsx — Backlot REPLAY 回放
 *
 * 回放回答"这条片子是怎么长出来的": 每个片段的时长都是 ffprobe 实测的,
 * 裁决以注解卡插在对应镜头后面, 没量到媒体的片段显式标出来而不是补一段假画面。
 * 可渲染时按顺序用 ffmpeg 拼成一条真 mp4 供播放器播放。
 */

import { useCallback, useEffect, useState } from "react";

type ReplaySegment = {
  kind: "shot" | "decision_card" | "unmeasured";
  scene_id: string;
  index?: number;
  title?: string;
  status?: string;
  at_s: number;
  duration_s: number | null;
  source_path?: string;
  thumbnail?: string;
  cost_usd?: number;
  quality_score?: number | null;
  decision?: string;
  reason?: string;
  reviewer?: string;
  ts?: string;
  decisions?: { decision: string; reason: string; reviewer: string; ts: string }[];
};

interface ReplayPayload {
  run_id: string;
  include: string;
  segments: ReplaySegment[];
  total_s: number;
  segment_count: number;
  unmeasured: { scene_id: string; reason: string }[];
  renderable: boolean;
  summary: { approved: number; rejected: number; pending: number };
}

interface PlaybackPanelProps {
  run_id: string;
  api_base?: string;
}

export default function PlaybackPanel({ run_id, api_base = "" }: PlaybackPanelProps) {
  const [include, setInclude] = useState<"approved" | "rejected" | "all">("approved");
  const [replay, setReplay] = useState<ReplayPayload | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const base = `${api_base}/api/backlot/runs/${run_id}`;

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${base}/replay?include=${include}`);
      if (res.ok) {
        setReplay((await res.json()) as ReplayPayload);
        setError(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoaded(true);
    }
  }, [base, include]);

  useEffect(() => {
    void load();
  }, [load]);

  async function render() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${base}/replay/render?include=${include}`, { method: "POST" });
      if (!res.ok) {
        setError(`渲染失败 (${res.status}): ${await res.text()}`);
        return;
      }
      const data = (await res.json()) as { render: { ok: boolean; reason?: string } };
      if (!data.render.ok) {
        setError(`不可渲染: ${data.render.reason ?? "未知原因"}`);
        setVideoUrl(null);
        return;
      }
      setVideoUrl(`${api_base}/api/backlot/media/${run_id}/replay_${include}.mp4`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) {
    return <div className="p-4 text-sm text-muted-foreground">加载回放时间线...</div>;
  }

  return (
    <section className="bg-white rounded-lg shadow-sm p-6">
      <header className="mb-4 flex items-center justify-between flex-wrap gap-3">
        <h3 className="text-lg font-semibold">REPLAY 回放</h3>
        <div className="flex items-center gap-2">
          <select
            className="border rounded px-2 py-1 text-xs"
            value={include}
            onChange={(e) => setInclude(e.target.value as typeof include)}
          >
            <option value="approved">只回放通过的</option>
            <option value="rejected">只回放被否的</option>
            <option value="all">全部</option>
          </select>
          <button
            className="text-xs px-3 py-1 rounded bg-slate-800 text-white disabled:opacity-50"
            disabled={busy || !replay?.renderable}
            onClick={() => void render()}
            title={replay?.renderable ? "用 ffmpeg 拼一条真回放片" : "有片段没量到真实媒体, 不可渲染"}
          >
            {busy ? "拼接中..." : "渲染回放片"}
          </button>
        </div>
      </header>

      {error && (
        <p className="mb-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded p-2">
          {error}
        </p>
      )}

      {replay && replay.unmeasured.length > 0 && (
        <p className="mb-3 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
          {replay.unmeasured.length} 个片段没有可读的真实媒体, 时长未量测:
          {replay.unmeasured.map((u) => u.scene_id).join("、")}
        </p>
      )}

      {videoUrl && (
        <video
          controls
          src={videoUrl}
          className="w-full rounded mb-4"
          data-testid="backlot-replay-video"
        />
      )}

      {!replay || replay.segments.length === 0 ? (
        <p className="text-sm text-muted-foreground">这条 run 还没有可回放的分镜。</p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground mb-2">
            共 {replay.segment_count} 段 / {replay.total_s.toFixed(2)}s(时长均为 ffprobe 实测)
          </p>
          <ol className="space-y-1">
            {replay.segments.map((seg, i) => (
              <li
                key={`${seg.scene_id}-${i}`}
                className="text-xs flex items-start gap-3 rounded px-2 py-1"
                style={{
                  background:
                    seg.kind === "decision_card"
                      ? seg.decision === "approved"
                        ? "#ecfdf5"
                        : "#fff1f2"
                      : seg.kind === "unmeasured"
                        ? "#fef3c7"
                        : "#f8fafc",
                }}
              >
                <span className="tabular-nums text-muted-foreground w-24 shrink-0">
                  {seg.at_s.toFixed(2)}s
                  {seg.duration_s !== null ? ` +${seg.duration_s.toFixed(2)}` : " ?"}
                </span>
                <span className="flex-1">
                  {seg.kind === "decision_card" ? (
                    <>
                      裁决 · {seg.decision} · {seg.reviewer} · {seg.ts}
                      {seg.reason ? ` · ${seg.reason}` : ""}
                    </>
                  ) : seg.kind === "unmeasured" ? (
                    <>未量测片段 · {seg.scene_id}(无可读媒体)</>
                  ) : (
                    <>
                      #{seg.index} {seg.title || seg.scene_id} · {seg.status} · 成本 $
                      {(seg.cost_usd ?? 0).toFixed(2)} · 实测质量{" "}
                      {seg.quality_score === null || seg.quality_score === undefined
                        ? "未量"
                        : seg.quality_score.toFixed(2)}
                    </>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
