/**
 * ClipperConsole — 智能拆条(Frontend SPEC v5.0 §1/§3)
 * 从 /production-tools 独立为二创工具页 /studio/clipper:
 * Whisper 转写 + LLM 病毒评分 + FFmpeg 裁剪,长视频 → 高光短视频。
 */
'use client';

import { useEffect, useState } from 'react';
import { productionApi, productionV2Api } from '@/lib/api-client';
import type { CapabilityDescriptor } from '@/types/api';

interface ClipResult {
  num_clips?: number;
  total_duration_s?: number;
  error?: string;
  clips?: Array<{
    title: string;
    category: string;
    score: number;
    start_time?: number;
    end_time?: number;
    hook_sentence?: string;
    virality_reason?: string;
  }>;
}

export function ClipperConsole() {
  const [videoPath, setVideoPath] = useState('');
  const [numClips, setNumClips] = useState(5);
  const [aspectRatio, setAspectRatio] = useState('9:16');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ClipResult | null>(null);
  const [capability, setCapability] = useState<CapabilityDescriptor | null>(null);

  useEffect(() => {
    void productionApi.capabilities()
      .then(({ capabilities }) => setCapability(capabilities.find(({ id }) => id === 'production_tools') ?? null))
      .catch(() => setCapability({
        id: 'production_tools', name: 'Clipper', routes: [], available: false,
        status: 'unavailable', message: '无法确认智能拆条的真实可用状态，已禁用生成动作。', setup: null,
      }));
  }, []);

  const clip = async () => {
    if (!videoPath) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await productionV2Api.clipVideo({
        video_path: videoPath,
        max_clips: numClips,
      });
      setResult(res as unknown as ClipResult);
    } catch (e: unknown) {
      setResult({ error: (e instanceof Error ? e.message : String(e)) });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 hevi-clipper">
      <div className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-2">✂️ 智能拆条</h1>
        <p className="text-gray-600 mb-6">
          长视频 → 短视频二创独立工具:Whisper 转写 + LLM 病毒评分 + FFmpeg 裁剪,自动提取高光片段
        </p>

        {capability && !capability.available && (
          <div className="my-4 rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-900">
            <p className="font-medium">拆条动作暂不可用：{capability.message}</p>
            {capability.setup && <p className="mt-1 text-sm">{capability.setup}</p>}
          </div>
        )}

        <fieldset disabled={!capability?.available} className="disabled:opacity-60">
          <div className="space-y-4">
            <div className="bg-white p-6 rounded-lg shadow">
              <h2 className="text-xl font-semibold mb-4">长视频→短视频智能拆条</h2>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium mb-1" htmlFor="clipper-video-path">视频路径</label>
                  <input
                    id="clipper-video-path"
                    type="text"
                    value={videoPath}
                    onChange={(e) => setVideoPath(e.target.value)}
                    className="w-full border rounded px-3 py-2"
                    placeholder="/path/to/long_video.mp4"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium mb-1" htmlFor="clipper-num">提取数量</label>
                    <input
                      id="clipper-num"
                      type="number"
                      min={1}
                      max={20}
                      value={numClips}
                      onChange={(e) => setNumClips(Number(e.target.value))}
                      className="w-full border rounded px-3 py-2"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1" htmlFor="clipper-ratio">目标比例</label>
                    <select
                      id="clipper-ratio"
                      value={aspectRatio}
                      onChange={(e) => setAspectRatio(e.target.value)}
                      className="w-full border rounded px-3 py-2"
                    >
                      <option value="9:16">9:16 竖屏 (TikTok/Reels)</option>
                      <option value="1:1">1:1 方形 (Instagram)</option>
                      <option value="4:5">4:5 竖版 (Pinterest)</option>
                    </select>
                  </div>
                </div>

                <button
                  onClick={clip}
                  disabled={loading || !videoPath}
                  className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:bg-gray-400"
                >
                  {loading ? '分析中...' : '开始拆条'}
                </button>
              </div>
            </div>

            {result && (
              <div className="bg-white p-6 rounded-lg shadow">
                <h3 className="font-semibold mb-3">
                  结果: {result.num_clips} 个片段
                  <span className="text-sm text-gray-500 ml-2">
                    (总时长 {result.total_duration_s?.toFixed(1)}s)
                  </span>
                </h3>
                {result.error ? (
                  <p className="text-red-600">{result.error}</p>
                ) : (
                  <div className="space-y-3">
                    {result.clips?.map((clip, i) => (
                      <div key={i} className="border rounded p-3">
                        <div className="flex justify-between items-start">
                          <div>
                            <span className="font-medium">#{i + 1} {clip.title}</span>
                            <span className="ml-2 text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded">
                              {clip.category}
                            </span>
                          </div>
                          <span className="text-lg font-bold text-blue-600">{clip.score}</span>
                        </div>
                        <p className="text-sm text-gray-600 mt-1">
                          {clip.start_time?.toFixed(1)}s - {clip.end_time?.toFixed(1)}s
                        </p>
                        {clip.hook_sentence && (
                          <p className="text-sm mt-1 italic">&ldquo;{clip.hook_sentence}&rdquo;</p>
                        )}
                        {clip.virality_reason && (
                          <p className="text-xs text-gray-500 mt-1">{clip.virality_reason}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </fieldset>
      </div>
    </div>
  );
}
