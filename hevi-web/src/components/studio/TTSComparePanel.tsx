/* TTS 试听对比 UI (已落实 B11) */

import { useState, useRef } from "react";

interface TTSComparePanelProps {
  text: string;
  engines: {
    id: string;
    name: string;
    description: string;
    languages: string[];
  }[];
  availableEngines?: string[];
  onCompare?: (engineA: string, engineB: string, text: string) => Promise<{
    [engineId: string]: { audioUrl: string; status: string; message?: string };
  }>;
}

export default function TTSComparePanel({ text, engines, availableEngines = [], onCompare }: TTSComparePanelProps) {
  const [engineA, setEngineA] = useState<string>(engines[0]?.id ?? "");
  const [engineB, setEngineB] = useState<string>(engines[1]?.id ?? engines[0]?.id ?? "");
  const [comparisonText, setComparisonText] = useState<string>(text);
  const [result, setResult] = useState<{
    [engineId: string]: { audioUrl: string; status: string; message?: string };
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const handleCompare = async () => {
    if (!engineA || !engineB || !comparisonText.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = onCompare
        ? await onCompare(engineA, engineB, comparisonText)
        : null;
      setResult(result ?? {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "对比失败");
    } finally {
      setLoading(false);
    }
  };

  const handlePlay = (engineId: string, audioUrl: string) => {
    if (!audioRef.current) return;
    if (playing === engineId) {
      audioRef.current.pause();
      setPlaying(null);
    } else {
      audioRef.current.src = audioUrl;
      audioRef.current.play().then(() => setPlaying(engineId)).catch(() => {
        setError("音频播放失败");
      });
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-sm p-6">
      <h2 className="text-xl font-bold mb-4">TTS 试听对比</h2>
      <p className="text-sm text-muted-foreground mb-6">
        选择两个 TTS 引擎，对比同一段文本的不同音色效果
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div>
          <label className="block text-sm font-medium text-muted-foreground mb-2">
            引擎 A
          </label>
          <select
            value={engineA}
            onChange={(e) => setEngineA(e.target.value)}
            className="w-full p-3 rounded-lg border border-gray-200 bg-gray-50 text-sm"
          >
            {engines.map((engine) => (
              <option key={engine.id} value={engine.id}>
                {engine.name} {availableEngines.includes(engine.id) ? "(可用)" : ""}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-muted-foreground mb-2">
            引擎 B
          </label>
          <select
            value={engineB}
            onChange={(e) => setEngineB(e.target.value)}
            className="w-full p-3 rounded-lg border border-gray-200 bg-gray-50 text-sm"
          >
            {engines.map((engine) => (
              <option key={engine.id} value={engine.id}>
                {engine.name} {availableEngines.includes(engine.id) ? "(可用)" : ""}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mb-6">
        <label className="block text-sm font-medium text-muted-foreground mb-2">
          对比文本
        </label>
        <textarea
          value={comparisonText}
          onChange={(e) => setComparisonText(e.target.value)}
          rows={3}
          className="w-full p-3 rounded-lg border border-gray-200 bg-gray-50 text-sm"
          placeholder="输入要对比的文本…"
        />
      </div>

      <button
        onClick={handleCompare}
        disabled={loading || !engineA || !engineB || !comparisonText.trim()}
        className="w-full py-3 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? "对比中…" : "开始对比"}
      </button>

      {error && (
        <p className="text-sm text-red-600 mt-4">{error}</p>
      )}

      {result && (
        <div className="mt-6 space-y-4">
          {Object.entries(result).map(([engineId, data]) => {
            const engine = engines.find((e) => e.id === engineId);
            return (
              <div
                key={engineId}
                className="border border-gray-200 rounded-lg p-4 flex items-center justify-between"
              >
                <div>
                  <h4 className="font-medium text-sm">
                    {engine?.name ?? engineId}
                  </h4>
                  <p className="text-xs text-muted-foreground mt-1">
                    {data.status === "published" ? "已生成" : data.message ?? "处理中"}
                  </p>
                </div>
                {data.audioUrl && (
                  <button
                    onClick={() => handlePlay(engineId, data.audioUrl)}
                    className="px-4 py-2 rounded bg-primary/10 text-primary text-sm hover:bg-primary/20 transition-colors"
                  >
                    {playing === engineId ? "⏸ 暂停" : "▶ 试听"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      <audio ref={audioRef} className="hidden" controls />
    </div>
  );
}