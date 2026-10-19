// @ts-nocheck
/* Preserved prototype; backend endpoints are not registered in this deployment. */
/**
 * ViMaxConsole — ViMax 高级功能控制台
 *
 * 提供四个主要功能:
 * 1. Idea2Video — 一句话创意生成完整视频
 * 2. Novel2Video — 长文本/小说生成视频
 * 3. AutoCameo — 参考照片人物插入视频
 * 4. Provider Presets — 预置 provider 配置管理
 */
'use client';

import { useState, useEffect } from 'react';
import { vimaxApi } from '@/lib/api-client';
import type {
  VimMaxPreset, VimMaxIdea2VideoResponse, VimMaxNovel2VideoResponse,
  VimMaxAutoCameoResponse,
} from '@/types/api';

type TabKey = 'idea2video' | 'novel2video' | 'autocameo' | 'presets';

const TAB_LABELS: Record<TabKey, string> = {
  idea2video: '💡 创意转视频',
  novel2video: '📖 小说转视频',
  autocameo: '🎭 照片入戏',
  presets: '⚙️ Provider 配置',
};

export function ViMaxConsole() {
  const [activeTab, setActiveTab] = useState<TabKey>('idea2video');
  const [presets, setPresets] = useState<VimMaxPreset[]>([]);
  const [presetsLoading, setPresetsLoading] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState<string>('');

  // 加载 presets
  useEffect(() => {
    if (activeTab === 'presets' && presets.length === 0) {
      setPresetsLoading(true);
      vimaxApi.listPresets()
        .then(r => setPresets(r.presets))
        .catch(() => setPresets([]))
        .finally(() => setPresetsLoading(false));
    }
  }, [activeTab, presets.length]);

  return (
    <div className="vimax-console">
      {/* Tab 导航 */}
      <div className="vimax-tabs">
        {(Object.keys(TAB_LABELS) as TabKey[]).map(key => (
          <button
            key={key}
            className={`vimax-tab ${activeTab === key ? 'active' : ''}`}
            onClick={() => setActiveTab(key)}
          >
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      <div className="vimax-content">
        {activeTab === 'idea2video' && (
          <Idea2VideoPanel preset={selectedPreset} />
        )}
        {activeTab === 'novel2video' && (
          <Novel2VideoPanel preset={selectedPreset} />
        )}
        {activeTab === 'autocameo' && (
          <AutoCameoPanel />
        )}
        {activeTab === 'presets' && (
          <PresetsPanel
            presets={presets}
            loading={presetsLoading}
            selected={selectedPreset}
            onSelect={setSelectedPreset}
          />
        )}
      </div>
    </div>
  );
}

// ── Idea2Video 面板 ──────────────────────────────────────────────────────────

function Idea2VideoPanel({ preset }: { preset: string }) {
  const [idea, setIdea] = useState('');
  const [style, setStyle] = useState('realistic');
  const [maxScenes, setMaxScenes] = useState(5);
  const [maxShots, setMaxShots] = useState(8);
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<VimMaxIdea2VideoResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function handleSubmit() {
    if (!idea.trim()) { setErr('请输入创意描述'); return; }
    setBusy(true); setErr(null); setResult(null);
    try {
      const r = await vimaxApi.idea2Video({
        idea: idea.trim(),
        style, max_scenes: maxScenes, max_shots_per_scene: maxShots,
        aspect_ratio: aspectRatio,
        provider_preset: preset || null,
      });
      setResult(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '生成失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="vimax-panel">
      <h3>Idea2Video — 一句话创意转视频</h3>
      <p className="vimax-desc">
        输入一句话创意,自动拆解场景、生成图像和视频、拼接成片。
      </p>

      <div className="vimax-form">
        <label>
          创意描述
          <textarea
            value={idea}
            onChange={e => setIdea(e.target.value)}
            placeholder="例如:一个孤独的旅行者穿越沙漠,寻找失落的文明"
            rows={3}
          />
        </label>

        <div className="vimax-row">
          <label>
            风格
            <select value={style} onChange={e => setStyle(e.target.value)}>
              <option value="realistic">写实</option>
              <option value="cinematic">电影感</option>
              <option value="anime">动漫</option>
              <option value="noir">黑色电影</option>
              <option value="inkwash">水墨</option>
            </select>
          </label>

          <label>
            画幅
            <select value={aspectRatio} onChange={e => setAspectRatio(e.target.value)}>
              <option value="16:9">16:9 横屏</option>
              <option value="9:16">9:16 竖屏</option>
              <option value="1:1">1:1 方形</option>
            </select>
          </label>
        </div>

        <div className="vimax-row">
          <label>
            最大场景数
            <input type="number" value={maxScenes} min={1} max={20}
              onChange={e => setMaxScenes(parseInt(e.target.value) || 5)} />
          </label>
          <label>
            每场景镜头数
            <input type="number" value={maxShots} min={1} max={15}
              onChange={e => setMaxShots(parseInt(e.target.value) || 8)} />
          </label>
        </div>

        <button className="vimax-submit" onClick={handleSubmit} disabled={busy}>
          {busy ? '⏳ 处理中…' : '🎬 生成视频'}
        </button>
      </div>

      {err && <div className="vimax-error">{err}</div>}
      {result && (
        <div className="vimax-result">
          <div className="result-status">✓ {result.status}</div>
          <div className="result-message">{result.message}</div>
          <details>
            <summary>管线配置</summary>
            <pre>{JSON.stringify(result.config, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}

// ── Novel2Video 面板 ─────────────────────────────────────────────────────────

function Novel2VideoPanel({ preset }: { preset: string }) {
  const [text, setText] = useState('');
  const [maxBeats, setMaxBeats] = useState(8);
  const [maxEvents, setMaxEvents] = useState(20);
  const [maxScenes, setMaxScenes] = useState(30);
  const [targetDuration, setTargetDuration] = useState(120);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<VimMaxNovel2VideoResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function handleSubmit() {
    if (!text.trim()) { setErr('请输入文本内容'); return; }
    setBusy(true); setErr(null); setResult(null);
    try {
      const r = await vimaxApi.novel2Video({
        text: text.trim(),
        max_beats_per_chapter: maxBeats,
        max_events: maxEvents,
        max_scenes: maxScenes,
        target_duration_s: targetDuration,
        provider_preset: preset || null,
      });
      setResult(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '生成失败');
    } finally {
      setBusy(false);
    }
  }

  const charCount = text.length;
  const wordCount = text.trim().split(/\s+/).filter(Boolean).length;

  return (
    <div className="vimax-panel">
      <h3>Novel2Video — 长文本/小说转视频</h3>
      <p className="vimax-desc">
        输入长文本或小说,自动拆分章节、压缩叙事、提取事件、逐事件生成视频。
      </p>

      <div className="vimax-form">
        <label>
          文本内容
          <span className="vimax-count">{charCount} 字 / {wordCount} 词</span>
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="粘贴小说章节、故事文本、或长篇叙事内容…"
            rows={10}
          />
        </label>

        <div className="vimax-row">
          <label>
            每章最大节拍
            <input type="number" value={maxBeats} min={3} max={15}
              onChange={e => setMaxBeats(parseInt(e.target.value) || 8)} />
          </label>
          <label>
            最大事件数
            <input type="number" value={maxEvents} min={5} max={50}
              onChange={e => setMaxEvents(parseInt(e.target.value) || 20)} />
          </label>
        </div>

        <div className="vimax-row">
          <label>
            最大场景数
            <input type="number" value={maxScenes} min={5} max={100}
              onChange={e => setMaxScenes(parseInt(e.target.value) || 30)} />
          </label>
          <label>
            目标时长 (秒)
            <input type="number" value={targetDuration} min={30} max={600}
              onChange={e => setTargetDuration(parseInt(e.target.value) || 120)} />
          </label>
        </div>

        <button className="vimax-submit" onClick={handleSubmit} disabled={busy}>
          {busy ? '⏳ 处理中…' : '📖 生成视频'}
        </button>
      </div>

      {err && <div className="vimax-error">{err}</div>}
      {result && (
        <div className="vimax-result">
          <div className="result-status">✓ {result.status}</div>
          <div className="result-message">{result.message}</div>
          <div className="result-preview">
            <strong>文本预览:</strong> {result.text_preview}…
          </div>
          <details>
            <summary>管线配置</summary>
            <pre>{JSON.stringify(result.config, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}

// ── AutoCameo 面板 ───────────────────────────────────────────────────────────

function AutoCameoPanel() {
  const [videoPath, setVideoPath] = useState('');
  const [photoPath, setPhotoPath] = useState('');
  const [charName, setCharName] = useState('');
  const [charDesc, setCharDesc] = useState('');
  const [role, setRole] = useState<'background' | 'supporting' | 'main'>('background');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<VimMaxAutoCameoResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function handleSubmit() {
    if (!videoPath.trim() || !photoPath.trim()) {
      setErr('请填写视频路径和照片路径'); return;
    }
    setBusy(true); setErr(null); setResult(null);
    try {
      const r = await vimaxApi.autocameo({
        video_path: videoPath.trim(),
        reference_photo_path: photoPath.trim(),
        character_name: charName.trim(),
        character_description: charDesc.trim(),
        role,
      });
      setResult(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '处理失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="vimax-panel">
      <h3>AutoCameo — 照片人物入戏</h3>
      <p className="vimax-desc">
        上传参考照片,自动提取人物特征、生成肖像三联画、确定角色定位、整合入视频。
      </p>

      <div className="vimax-form">
        <label>
          视频路径
          <input type="text" value={videoPath}
            onChange={e => setVideoPath(e.target.value)}
            placeholder="/path/to/video.mp4" />
        </label>

        <label>
          参考照片路径
          <input type="text" value={photoPath}
            onChange={e => setPhotoPath(e.target.value)}
            placeholder="/path/to/photo.jpg" />
        </label>

        <div className="vimax-row">
          <label>
            角色名称 (可选)
            <input type="text" value={charName}
              onChange={e => setCharName(e.target.value)}
              placeholder="例如: Alice" />
          </label>
          <label>
            角色定位
            <select value={role} onChange={e => setRole(e.target.value as typeof role)}>
              <option value="background">背景人物</option>
              <option value="supporting">配角</option>
              <option value="main">主角</option>
            </select>
          </label>
        </div>

        <label>
          角色描述 (可选)
          <textarea value={charDesc}
            onChange={e => setCharDesc(e.target.value)}
            placeholder="描述角色特征、性格、在故事中的作用…"
            rows={2} />
        </label>

        <button className="vimax-submit" onClick={handleSubmit} disabled={busy}>
          {busy ? '⏳ 处理中…' : '🎭 处理客串'}
        </button>
      </div>

      {err && <div className="vimax-error">{err}</div>}
      {result && (
        <div className="vimax-result">
          <div className="result-status">✓ {result.status}</div>
          <div className="result-message">{result.message}</div>
          <div className="result-details">
            <span>角色: <strong>{result.character_name || '(未命名)'}</strong></span>
            <span>定位: <strong>{result.role}</strong></span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Presets 面板 ─────────────────────────────────────────────────────────────

function PresetsPanel({
  presets, loading, selected, onSelect,
}: {
  presets: VimMaxPreset[];
  loading: boolean;
  selected: string;
  onSelect: (name: string) => void;
}) {
  const [detail, setDetail] = useState<VimMaxPreset & { resolved_config?: Record<string, string> } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  async function showDetail(name: string) {
    setDetailLoading(true);
    try {
      const d = await vimaxApi.getPreset(name);
      setDetail(d);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }

  const categoryColors: Record<string, string> = {
    llm: '#4a9eff',
    image: '#ff9f4a',
    video: '#9f4aff',
  };

  return (
    <div className="vimax-panel">
      <h3>Provider Presets — 预置配置</h3>
      <p className="vimax-desc">
        选择预设 provider,自动填充 base_url / context_window / API key 环境变量。
        选中的 preset 将用于 Idea2Video 和 Novel2Video 生成。
      </p>

      {loading ? (
        <div className="vimax-loading">加载中…</div>
      ) : presets.length === 0 ? (
        <div className="vimax-empty">暂无可用 preset</div>
      ) : (
        <div className="presets-grid">
          {presets.map(p => (
            <div
              key={p.name}
              className={`preset-card ${selected === p.name ? 'selected' : ''}`}
              onClick={() => { onSelect(p.name); showDetail(p.name); }}
            >
              <div className="preset-header">
                <span className="preset-name">{p.name}</span>
                <span
                  className="preset-badge"
                  style={{ background: categoryColors[p.category] || '#666' }}
                >
                  {p.category}
                </span>
              </div>
              <div className="preset-meta">
                <span>🔗 {p.base_url || '(本地)'}</span>
                <span>📦 {p.context_window.toLocaleString()} tokens</span>
              </div>
              <div className="preset-env">
                <code>{p.api_key_env}</code>
              </div>
            </div>
          ))}
        </div>
      )}

      {selected && detail && (
        <div className="preset-detail">
          <h4>配置详情: {detail.name}</h4>
          <div className="detail-grid">
            <div><strong>名称:</strong> {detail.name}</div>
            <div><strong>类别:</strong> {detail.category}</div>
            <div><strong>Base URL:</strong> {detail.base_url || '(本地)'}</div>
            <div><strong>Context Window:</strong> {detail.context_window.toLocaleString()}</div>
            <div><strong>API Key 环境变量:</strong> <code>{detail.api_key_env}</code></div>
          </div>
          {detail.resolved_config && (
            <details>
              <summary>完整配置</summary>
              <pre>{JSON.stringify(detail.resolved_config, null, 2)}</pre>
            </details>
          )}
        </div>
      )}

      {selected && !detail && !detailLoading && (
        <div className="preset-detail">
          <p>已选择: <strong>{selected}</strong></p>
          <p className="vimax-hint">
            此 preset 将自动应用于后续 Idea2Video / Novel2Video 生成。
          </p>
        </div>
      )}
    </div>
  );
}
