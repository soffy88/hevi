'use client';

import { useState } from 'react';
import { productionV2Api } from '@/lib/api-client';
import { TabBar, type TabItem } from '@/components/shared';

type Tab = 'seedance' | 'clipper' | 'recipes' | 'digital-human';

// API response types
interface SeedanceResult {
  request_id?: string;
  mode?: string;
  duration_s?: number;
  cost_usd?: number;
  video_url?: string;
  audio_url?: string;
  error?: string;
}

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

interface RecipeDetail {
  name: string;
  description: string;
  error?: string;
  inputs?: Record<string, string>;
  outputs?: Record<string, string>;
  steps?: Array<{
    step_type: string;
    description: string;
    optional?: boolean;
  }>;
  tags?: string[];
}

interface PreflightResult {
  ok?: boolean;
  errors?: string[];
  warnings?: string[];
  script_chars?: number;
}

interface PreviewResult {
  status?: string;
  preview_duration_s?: number;
  cost_usd?: number;
  preview_video_path?: string;
  error?: string;
}

export function ProductionToolsConsole() {
  const [activeTab, setActiveTab] = useState<Tab>('seedance');

  const prodTabs: Array<TabItem<Tab>> = [
    { key: 'seedance', label: 'Seedance 2', icon: '🎥' },
    { key: 'clipper', label: '智能拆条', icon: '✂️' },
    { key: 'recipes', label: '工作流配方', icon: '📋' },
    { key: 'digital-human', label: '数字人预览', icon: '👤' },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-2">🎬 生产工具 V2</h1>
        <p className="text-gray-600 mb-6">
          Seedance 2 视频生成 · 智能拆条 · 工作流配方 · 数字人预览
        </p>

        <TabBar items={prodTabs} active={activeTab} onChange={setActiveTab} />

        {/* Tab Content */}
        {activeTab === 'seedance' && <SeedanceTab />}
        {activeTab === 'clipper' && <ClipperTab />}
        {activeTab === 'recipes' && <RecipesTab />}
        {activeTab === 'digital-human' && <DigitalHumanTab />}
      </div>
    </div>
  );
}

// ─── Seedance 2 Tab ─────────────────────────────────────────────────────

function SeedanceTab() {
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<'t2v' | 'i2v' | 'extend'>('t2v');
  const [duration, setDuration] = useState(5);
  const [resolution, setResolution] = useState('720p');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [imageUrl, setImageUrl] = useState('');
  const [extendId, setExtendId] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SeedanceResult | null>(null);

  const generate = async () => {
    if (!prompt && mode !== 'extend') return;
    setLoading(true);
    setResult(null);
    try {
      const res = await productionV2Api.seedanceGenerate({
        prompt,
        duration_s: duration,
        aspect_ratio: aspectRatio,
        image_url: imageUrl || undefined,
      });
      setResult(res as unknown as SeedanceResult);
    } catch (e: unknown) {
      setResult({ error: (e instanceof Error ? e.message : String(e)) });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">Seedance 2 视频生成</h2>
        <p className="text-sm text-gray-600 mb-4">
          字节跳动豆包视频模型:文生视频 / 图生视频 / 视频续写，支持音画同步
        </p>

        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium mb-1">模式</label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as 't2v' | 'i2v' | 'extend')}
              className="w-full border rounded px-3 py-2"
            >
              <option value="t2v">文生视频 (Text-to-Video)</option>
              <option value="i2v">图生视频 (Image-to-Video)</option>
              <option value="extend">视频续写 (Extend)</option>
            </select>
          </div>

          {mode !== 'extend' && (
            <div>
              <label className="block text-sm font-medium mb-1">描述</label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                className="w-full border rounded px-3 py-2"
                placeholder="A dragon breathing fire in slow motion..."
              />
            </div>
          )}

          {mode === 'i2v' && (
            <div>
              <label className="block text-sm font-medium mb-1">参考图 URL</label>
              <input
                type="text"
                value={imageUrl}
                onChange={(e) => setImageUrl(e.target.value)}
                className="w-full border rounded px-3 py-2"
                placeholder="https://..."
              />
            </div>
          )}

          {mode === 'extend' && (
            <div>
              <label className="block text-sm font-medium mb-1">续写 Request ID</label>
              <input
                type="text"
                value={extendId}
                onChange={(e) => setExtendId(e.target.value)}
                className="w-full border rounded px-3 py-2"
                placeholder="之前生成的 request_id"
              />
              <label className="block text-sm font-medium mb-1 mt-2">续写描述（可选）</label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={2}
                className="w-full border rounded px-3 py-2"
                placeholder="Camera continues pulling back..."
              />
            </div>
          )}

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1">时长</label>
              <select
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="w-full border rounded px-3 py-2"
              >
                <option value={5}>5 秒</option>
                <option value={10}>10 秒</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">分辨率</label>
              <select
                value={resolution}
                onChange={(e) => setResolution(e.target.value)}
                className="w-full border rounded px-3 py-2"
              >
                <option value="480p">480p</option>
                <option value="720p">720p</option>
                <option value="1080p">1080p</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">比例</label>
              <select
                value={aspectRatio}
                onChange={(e) => setAspectRatio(e.target.value)}
                className="w-full border rounded px-3 py-2"
              >
                <option value="16:9">16:9 横屏</option>
                <option value="9:16">9:16 竖屏</option>
                <option value="1:1">1:1 方形</option>
              </select>
            </div>
          </div>

          <button
            onClick={generate}
            disabled={loading || (!prompt && mode !== 'extend')}
            className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:bg-gray-400"
          >
            {loading ? '生成中...' : '生成视频'}
          </button>
        </div>
      </div>

      {result && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="font-semibold mb-2">结果</h3>
          {result.error ? (
            <p className="text-red-600">{result.error}</p>
          ) : (
            <div className="space-y-2 text-sm">
              <p><strong>Request ID:</strong> {result.request_id}</p>
              <p><strong>模式:</strong> {result.mode}</p>
              <p><strong>时长:</strong> {result.duration_s}s</p>
              <p><strong>成本:</strong> ${result.cost_usd}</p>
              {result.video_url && (
                <div>
                  <strong>视频:</strong>
                  <video src={result.video_url} controls className="mt-2 max-h-64 rounded" />
                </div>
              )}
              {result.audio_url && (
                <div>
                  <strong>音频:</strong>
                  <audio src={result.audio_url} controls className="mt-1" />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── 智能拆条 Tab ──────────────────────────────────────────────────────

function ClipperTab() {
  const [videoPath, setVideoPath] = useState('');
  const [numClips, setNumClips] = useState(5);
  const [aspectRatio, setAspectRatio] = useState('9:16');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ClipResult | null>(null);

  const clip = async () => {
    if (!videoPath) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await productionV2Api.clipVideo({
        video_path: videoPath,
        max_clips: numClips,
      });
      setResult(res as unknown as SeedanceResult);
    } catch (e: unknown) {
      setResult({ error: (e instanceof Error ? e.message : String(e)) });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">✂️ 长视频→短视频智能拆条</h2>
        <p className="text-sm text-gray-600 mb-4">
          Whisper 转写 + LLM 病毒评分 + FFmpeg 裁剪，自动提取高光片段
        </p>

        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium mb-1">视频路径</label>
            <input
              type="text"
              value={videoPath}
              onChange={(e) => setVideoPath(e.target.value)}
              className="w-full border rounded px-3 py-2"
              placeholder="/path/to/long_video.mp4"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1">提取数量</label>
              <input
                type="number"
                min={1}
                max={20}
                value={numClips}
                onChange={(e) => setNumClips(Number(e.target.value))}
                className="w-full border rounded px-3 py-2"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">目标比例</label>
              <select
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
              {result.clips?.map((clip: NonNullable<ClipResult["clips"]>[number], i: number) => (
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
  );
}

// ─── 工作流配方 Tab ──────────────────────────────────────────────────────

function RecipesTab() {
  const [recipes, setRecipes] = useState<Array<{ name: string; description: string; category?: string; steps_count?: number; estimated_duration_s?: number; estimated_cost_usd?: number }>>([]);
  const [selectedRecipe, setSelectedRecipe] = useState<RecipeDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useState(() => {
    loadRecipes();
  });

  const loadRecipes = async () => {
    try {
      const res = await productionV2Api.listRecipes();
      setRecipes(res.recipes || []);
    } catch {
      setRecipes([]);
    }
  };

  const viewRecipe = async (name: string) => {
    try {
      const res = await productionV2Api.getRecipe(name);
      setSelectedRecipe(res as unknown as RecipeDetail);
    } catch (e: unknown) {
      setSelectedRecipe({ name: '', description: '', error: (e instanceof Error ? e.message : String(e)) });
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">📋 工作流配方 (Recipe Pack)</h2>
        <p className="text-sm text-gray-600 mb-4">
          命名工作流配方:声明 inputs → 串联多步骤 → 端到端输出
        </p>

        <div className="grid grid-cols-2 gap-3">
          {recipes.map((recipe) => (
            <button
              key={recipe.name}
              onClick={() => viewRecipe(recipe.name)}
              className="text-left border rounded p-4 hover:border-blue-500 transition-colors"
            >
              <div className="font-medium">{recipe.name}</div>
              <div className="text-sm text-gray-600 mt-1">{recipe.description}</div>
              <div className="flex gap-2 mt-2">
                <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{recipe.category}</span>
                <span className="text-xs text-gray-500">
                  {recipe.steps_count} 步 · ~{recipe.estimated_duration_s}s · ~${recipe.estimated_cost_usd}
                </span>
              </div>
            </button>
          ))}
        </div>

        {recipes.length === 0 && (
          <p className="text-gray-500 text-center py-8">加载配方中...</p>
        )}
      </div>

      {selectedRecipe && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="font-semibold text-lg mb-3">{selectedRecipe.name}</h3>
          {selectedRecipe.error ? (
            <p className="text-red-600">{selectedRecipe.error}</p>
          ) : (
            <div className="space-y-4">
              <p className="text-gray-700">{selectedRecipe.description}</p>

              <div>
                <h4 className="font-medium text-sm mb-1">输入</h4>
                <div className="bg-gray-50 rounded p-3 text-sm">
                  {Object.entries(selectedRecipe.inputs || {}).map(([key, desc]) => (
                    <div key={key}><code className="text-blue-600">{key}</code>: {desc as string}</div>
                  ))}
                </div>
              </div>

              <div>
                <h4 className="font-medium text-sm mb-1">步骤 ({selectedRecipe.steps?.length})</h4>
                <ol className="space-y-1">
                  {selectedRecipe.steps?.map((step: NonNullable<RecipeDetail["steps"]>[number], i: number) => (
                    <li key={i} className="text-sm flex gap-2">
                      <span className="text-gray-400">{i + 1}.</span>
                      <span className="text-xs bg-gray-100 px-1.5 rounded">{step.step_type}</span>
                      <span>{step.description}</span>
                      {step.optional && <span className="text-xs text-orange-600">(可选)</span>}
                    </li>
                  ))}
                </ol>
              </div>

              <div>
                <h4 className="font-medium text-sm mb-1">输出</h4>
                <div className="bg-gray-50 rounded p-3 text-sm">
                  {Object.entries(selectedRecipe.outputs || {}).map(([key, desc]) => (
                    <div key={key}><code className="text-green-600">{key}</code>: {desc as string}</div>
                  ))}
                </div>
              </div>

              {(selectedRecipe.tags?.length ?? 0) > 0 && (
                <div className="flex gap-1 flex-wrap">
                  {selectedRecipe.tags!.map((tag: string) => (
                    <span key={tag} className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── 数字人预览 Tab ──────────────────────────────────────────────────────

function DigitalHumanTab() {
  const [project, setProject] = useState('');
  const [script, setScript] = useState('');
  const [portraitPath, setPortraitPath] = useState('');
  const [preflightResult, setPreflightResult] = useState<PreflightResult | null>(null);
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState('');

  const preflight = async () => {
    setLoading('preflight');
    try {
      const res = await productionV2Api.digitalHumanPreflight({ script, avatar_id: project || undefined });
      setPreflightResult(res as unknown as PreflightResult);
    } catch (e: unknown) {
      setPreflightResult({ ok: false, errors: [(e instanceof Error ? e.message : String(e))] });
    } finally {
      setLoading('');
    }
  };

  const preview = async () => {
    if (!portraitPath || !script) return;
    setLoading('preview');
    try {
      const res = await productionV2Api.digitalHumanPreview({
        script,
        avatar_id: portraitPath || undefined,
      });
      setPreviewResult(res as unknown as PreviewResult);
    } catch (e: unknown) {
      setPreviewResult({ error: (e instanceof Error ? e.message : String(e)) });
    } finally {
      setLoading('');
    }
  };

  const approve = async () => {
    setLoading('approve');
    try {
      await productionV2Api.digitalHumanApprove({ task_id: project });
      setPreviewResult((prev: PreviewResult | null) => ({ ...prev, status: 'preview_approved' }));
    } catch (e: unknown) {
      alert((e instanceof Error ? e.message : String(e)));
    } finally {
      setLoading('');
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-semibold mb-4">👤 数字人预览→确认流程</h2>
        <p className="text-sm text-gray-600 mb-4">
          先 15s 低成本预览，确认再生成 1080p 完整版。对标 rachel-digital-human-production。
        </p>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1">项目名</label>
              <input
                type="text"
                value={project}
                onChange={(e) => setProject(e.target.value)}
                className="w-full border rounded px-3 py-2"
                placeholder="my-digital-human"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">肖像图路径</label>
              <input
                type="text"
                value={portraitPath}
                onChange={(e) => setPortraitPath(e.target.value)}
                className="w-full border rounded px-3 py-2"
                placeholder="/path/to/portrait.jpg"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">脚本</label>
            <textarea
              value={script}
              onChange={(e) => setScript(e.target.value)}
              rows={4}
              className="w-full border rounded px-3 py-2"
              placeholder="大家好，欢迎来到我们的直播间..."
            />
          </div>

          <div className="flex gap-2">
            <button
              onClick={preflight}
              disabled={loading === 'preflight' || !script}
              className="flex-1 bg-gray-600 text-white py-2 rounded hover:bg-gray-700 disabled:bg-gray-400"
            >
              {loading === 'preflight' ? '检查中...' : '① 资产预检'}
            </button>
            <button
              onClick={preview}
              disabled={loading === 'preview' || !portraitPath || !script}
              className="flex-1 bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:bg-gray-400"
            >
              {loading === 'preview' ? '生成中...' : '② 生成 15s 预览'}
            </button>
          </div>
        </div>
      </div>

      {preflightResult && (
        <div className={`p-4 rounded-lg ${preflightResult.ok ? 'bg-green-50' : 'bg-red-50'}`}>
          <h3 className={`font-semibold ${preflightResult.ok ? 'text-green-800' : 'text-red-800'}`}>
            预检{preflightResult.ok ? '通过 ✓' : '失败 ✗'}
          </h3>
          {(preflightResult.errors?.length ?? 0) > 0 && (
            <ul className="text-sm text-red-700 mt-2 list-disc list-inside">
              {preflightResult.errors!.map((e: string, i: number) => <li key={i}>{e}</li>)}
            </ul>
          )}
          {(preflightResult.warnings?.length ?? 0) > 0 && (
            <ul className="text-sm text-yellow-700 mt-2 list-disc list-inside">
              {preflightResult.warnings!.map((w: string, i: number) => <li key={i}>{w}</li>)}
            </ul>
          )}
          {(preflightResult.script_chars ?? 0) > 0 && (
            <p className="text-sm text-gray-600 mt-2">脚本长度: {preflightResult.script_chars} 字</p>
          )}
        </div>
      )}

      {previewResult && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="font-semibold mb-3">预览结果</h3>
          {previewResult.error ? (
            <p className="text-red-600">{previewResult.error}</p>
          ) : (
            <div className="space-y-2 text-sm">
              <p><strong>状态:</strong> {previewResult.status}</p>
              <p><strong>预览时长:</strong> {previewResult.preview_duration_s}s</p>
              <p><strong>成本:</strong> ${previewResult.cost_usd}</p>
              {previewResult.preview_video_path && (
                <video
                  src={`/api/files?path=${encodeURIComponent(previewResult.preview_video_path)}`}
                  controls
                  className="mt-2 max-h-64 rounded"
                />
              )}
              {previewResult.status === 'preview_ready' && (
                <button
                  onClick={approve}
                  disabled={loading === 'approve'}
                  className="mt-3 bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 disabled:bg-gray-400"
                >
                  {loading === 'approve' ? '确认中...' : '✓ 确认预览，准备生成完整视频'}
                </button>
              )}
              {previewResult.status === 'preview_approved' && (
                <p className="text-green-600 font-medium mt-2">
                  ✓ 已确认，可以调用 generate 端点生成完整 1080p 视频
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
