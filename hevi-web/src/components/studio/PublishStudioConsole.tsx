'use client';

import { useState, useEffect } from 'react';
import { publishStudioApi } from '@/lib/api-client';
import { TabBar, type TabItem } from '@/components/shared';

type Tab = 'publish' | 'motion' | 'html-video' | 'voice' | 'dance';

const TABS: Array<TabItem<Tab>> = [
  { key: 'publish',    label: '多平台发布', icon: '📤' },
  { key: 'motion',     label: '动效合成',   icon: '✨' },
  { key: 'html-video', label: 'HTML 视频',  icon: '🌐' },
  { key: 'voice',      label: '语音工作室', icon: '🎙️' },
  { key: 'dance',      label: '编舞生成',   icon: '💃' },
];

const MOTION_CATEGORIES = ['转场', '字幕', '片头', '片尾', '特效'];

const VOICE_OPERATIONS = [
  { key: 'clone', label: '声音克隆',   endpoint: '/voice/clone',   fields: [{ name: 'reference_audio', label: '参考音频路径', placeholder: '/path/to/audio.wav' }, { name: 'text', label: '合成文本', placeholder: '要合成的文字内容' }] },
  { key: 'dub',   label: '视频配音',   endpoint: '/voice/dub',     fields: [{ name: 'video_path', label: '视频路径', placeholder: '/path/to/video.mp4' }, { name: 'target_language', label: '目标语言', placeholder: 'zh / en / ja' }] },
  { key: 'tts',   label: 'TTS 合成',   endpoint: '/voice/tts',     fields: [{ name: 'text', label: '合成文本', placeholder: '要合成的文字' }, { name: 'speaker', label: '说话人', placeholder: 'speaker_id' }] },
  { key: 'asr',   label: '语音识别',   endpoint: '/voice/asr',     fields: [{ name: 'audio_path', label: '音频路径', placeholder: '/path/to/audio.wav' }] },
];

const voiceApiMap: Record<string, (body: Record<string, string>) => Promise<unknown>> = {
  '/voice/clone': (body) => publishStudioApi.voiceClone({ reference_audio: body.reference_audio, text: body.text }),
  '/voice/dub':   (body) => publishStudioApi.voiceDub({ video_path: body.video_path, target_language: body.target_language }),
};

export function PublishStudioConsole() {
  const [activeTab, setActiveTab] = useState<Tab>('publish');

  // ── 多平台发布 ──────────────────────────────────────────────────────────────
  const [platforms, setPlatforms] = useState<Array<Record<string, unknown>>>([]);
  const [selectedPlatform, setSelectedPlatform] = useState('');
  const [pubForm, setPubForm] = useState({ video_path: '', title: '', description: '', tags: '' });
  const [pubTaskId, setPubTaskId] = useState<string | null>(null);
  const [pubStatus, setPubStatus] = useState('');
  const [pubError, setPubError] = useState('');

  // ── 动效合成 ────────────────────────────────────────────────────────────────
  const [motionCat, setMotionCat] = useState(MOTION_CATEGORIES[0]);
  const [motionTemplates, setMotionTemplates] = useState<Array<Record<string, unknown>>>([]);
  const [selectedMotionTpl, setSelectedMotionTpl] = useState('');
  const [motionParams, setMotionParams] = useState('');
  const [motionStatus, setMotionStatus] = useState('');
  const [motionError, setMotionError] = useState('');

  // ── HTML 视频 ───────────────────────────────────────────────────────────────
  const [htmlVideoTemplates, setHtmlVideoTemplates] = useState<Array<Record<string, unknown>>>([]);
  const [selectedHtmlTpl, setSelectedHtmlTpl] = useState('');
  const [htmlContent, setHtmlContent] = useState('');
  const [htmlVideoStatus, setHtmlVideoStatus] = useState('');
  const [htmlVideoError, setHtmlVideoError] = useState('');

  // ── 语音工作室 ──────────────────────────────────────────────────────────────
  const [voiceOp, setVoiceOp] = useState(VOICE_OPERATIONS[0]);
  const [voiceForm, setVoiceForm] = useState<Record<string, string>>({});
  const [voiceStatus, setVoiceStatus] = useState('');
  const [voiceError, setVoiceError] = useState('');

  // ── 编舞生成 ────────────────────────────────────────────────────────────────
  const [danceGpu, setDanceGpu] = useState<Record<string, unknown> | null>(null);
  const [danceForm, setDanceForm] = useState({ audio_path: '', dance_type: 'urban', duration_s: '' });
  const [danceStatus, setDanceStatus] = useState('');
  const [danceError, setDanceError] = useState('');

  // 加载平台列表
  useEffect(() => {
    publishStudioApi.listPlatforms()
      .then((res) => {
        const list = (res as { platforms: Array<Record<string, unknown>> }).platforms;
        setPlatforms(list.filter((p) => p.enabled));
      })
      .catch(() => setPlatforms([]));
  }, []);

  // 动效模板列表
  useEffect(() => {
    publishStudioApi.motionTemplates(motionCat)
      .then((res) => {
        const list = (res as { templates: Array<Record<string, unknown>> }).templates;
        setMotionTemplates(list);
        if (list.length > 0 && !selectedMotionTpl) {
          setSelectedMotionTpl(list[0].id as string);
        }
      })
      .catch(() => setMotionTemplates([]));
  }, [motionCat]);

  // HTML 视频模板列表
  useEffect(() => {
    publishStudioApi.htmlVideoTemplates()
      .then((res) => {
        const list = (res as { templates: Array<Record<string, unknown>> }).templates;
        setHtmlVideoTemplates(list);
        if (list.length > 0 && !selectedHtmlTpl) {
          setSelectedHtmlTpl(list[0].id as string);
        }
      })
      .catch(() => setHtmlVideoTemplates([]));
  }, []);

  // 编舞 GPU 检查
  useEffect(() => {
    if (activeTab === 'dance') {
      publishStudioApi.danceGpuCheck()
        .then((res) => setDanceGpu(res as Record<string, unknown>))
        .catch(() => setDanceGpu({ available: false }));
    }
  }, [activeTab]);

  // ── 发布流程 ────────────────────────────────────────────────────────────────
  const handlePublish = async () => {
    setPubError('');
    setPubStatus('');
    if (!selectedPlatform) {
      setPubError('请选择发布平台');
      return;
    }
    if (!pubForm.video_path || !pubForm.title) {
      setPubError('视频路径和标题为必填');
      return;
    }
    try {
      const res = await publishStudioApi.publish({
        platform: selectedPlatform,
        video_path: pubForm.video_path,
        title: pubForm.title,
        description: pubForm.description || undefined,
        tags: pubForm.tags ? pubForm.tags.split(',').map((t) => t.trim()).filter(Boolean) : undefined,
      });
      const taskId = (res as { task_id: string }).task_id;
      setPubTaskId(taskId);
      setPubStatus(`任务已提交: ${taskId}`);
    } catch (e) {
      setPubError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleConfirmPublish = async () => {
    if (!pubTaskId) return;
    setPubError('');
    try {
      const res = await publishStudioApi.confirmPublish({ task_id: pubTaskId });
      const status = (res as Record<string, unknown>).status as string;
      setPubStatus(`发布状态: ${status}`);
    } catch (e) {
      setPubError(e instanceof Error ? e.message : String(e));
    }
  };

  // ── 动效渲染 ────────────────────────────────────────────────────────────────
  const handleMotionRender = async () => {
    setMotionError('');
    setMotionStatus('');
    if (!selectedMotionTpl) {
      setMotionError('请选择动效模板');
      return;
    }
    try {
      const params = motionParams ? JSON.parse(motionParams) : {};
      const res = await publishStudioApi.motionRender({ template_id: selectedMotionTpl, params });
      setMotionStatus(`动效任务已提交: ${(res as { task_id: string }).task_id}`);
    } catch (e) {
      setMotionError(e instanceof Error ? e.message : String(e));
    }
  };

  // ── HTML 视频渲染 ──────────────────────────────────────────────────────────
  const handleHtmlVideoRender = async () => {
    setHtmlVideoError('');
    setHtmlVideoStatus('');
    if (!selectedHtmlTpl) {
      setHtmlVideoError('请选择 HTML 视频模板');
      return;
    }
    if (!htmlContent) {
      setHtmlVideoError('HTML 内容不能为空');
      return;
    }
    try {
      const res = await publishStudioApi.htmlVideoRender({
        template_id: selectedHtmlTpl,
        content: { html: htmlContent },
      });
      setHtmlVideoStatus(`HTML 视频任务已提交: ${(res as { task_id: string }).task_id}`);
    } catch (e) {
      setHtmlVideoError(e instanceof Error ? e.message : String(e));
    }
  };

  // ── 语音操作 ────────────────────────────────────────────────────────────────
  const handleVoiceSubmit = async () => {
    setVoiceError('');
    setVoiceStatus('');
    try {
      const apiFn = voiceApiMap[voiceOp.endpoint];
      if (!apiFn) {
        setVoiceError(`未找到语音操作: ${voiceOp.endpoint}`);
        return;
      }
      const res = await apiFn(voiceForm);
      setVoiceStatus(`语音任务已提交: ${(res as { task_id: string }).task_id}`);
    } catch (e) {
      setVoiceError(e instanceof Error ? e.message : String(e));
    }
  };

  // ── 编舞生成 ────────────────────────────────────────────────────────────────
  const handleDanceGenerate = async () => {
    setDanceError('');
    setDanceStatus('');
    if (!danceForm.audio_path) {
      setDanceError('音频路径为必填');
      return;
    }
    try {
      const res = await publishStudioApi.danceGenerate({
        audio_path: danceForm.audio_path,
        dance_type: danceForm.dance_type,
        duration_s: danceForm.duration_s ? Number(danceForm.duration_s) : undefined,
      });
      setDanceStatus(`编舞任务已提交: ${(res as { task_id: string }).task_id}`);
    } catch (e) {
      setDanceError(e instanceof Error ? e.message : String(e));
    }
  };

  // ── UI ──────────────────────────────────────────────────────────────────────
  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-6">🚀 发布工作室</h1>

      <TabBar items={TABS} active={activeTab} onChange={setActiveTab} variant="pill" />

      {/* ── 多平台发布 Tab ─────────────────────────────────────────────────── */}
      {activeTab === 'publish' && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">选择平台</label>
            <div className="flex gap-2 flex-wrap">
              {platforms.length === 0 && <span className="text-gray-400 text-sm">加载中...</span>}
              {platforms.map((p) => (
                <button
                  key={p.id as string}
                  onClick={() => setSelectedPlatform(p.id as string)}
                  className={`px-3 py-1.5 rounded text-sm border ${
                    selectedPlatform === p.id
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {p.name as string}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">视频路径 *</label>
            <input
              type="text"
              value={pubForm.video_path}
              onChange={(e) => setPubForm((f) => ({ ...f, video_path: e.target.value }))}
              placeholder="/path/to/video.mp4"
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">标题 *</label>
            <input
              type="text"
              value={pubForm.title}
              onChange={(e) => setPubForm((f) => ({ ...f, title: e.target.value }))}
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">描述</label>
            <textarea
              value={pubForm.description}
              onChange={(e) => setPubForm((f) => ({ ...f, description: e.target.value }))}
              rows={3}
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">标签 (逗号分隔)</label>
            <input
              type="text"
              value={pubForm.tags}
              onChange={(e) => setPubForm((f) => ({ ...f, tags: e.target.value }))}
              placeholder="tag1, tag2, tag3"
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          {pubError && <div className="text-red-500 text-sm">{pubError}</div>}
          {pubStatus && <div className="text-green-600 text-sm">{pubStatus}</div>}
          <div className="flex gap-2">
            <button onClick={handlePublish} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
              提交发布
            </button>
            {pubTaskId && (
              <button onClick={handleConfirmPublish} className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700">
                确认发布
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── 动效合成 Tab ─────────────────────────────────────────────────── */}
      {activeTab === 'motion' && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">模板分类</label>
            <div className="flex gap-2 flex-wrap">
              {MOTION_CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setMotionCat(cat)}
                  className={`px-3 py-1.5 rounded text-sm border ${
                    motionCat === cat
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">选择模板</label>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {motionTemplates.length === 0 && <span className="text-gray-400 text-sm">加载中...</span>}
              {motionTemplates.map((tpl) => (
                <button
                  key={tpl.id as string}
                  onClick={() => setSelectedMotionTpl(tpl.id as string)}
                  className={`p-3 rounded-lg border text-left text-sm ${
                    selectedMotionTpl === tpl.id
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="font-medium">{tpl.name as string}</div>
                  {tpl.desc ? <div className="text-gray-500 text-xs mt-1">{String(tpl.desc)}</div> : null}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">模板参数 (JSON)</label>
            <textarea
              value={motionParams}
              onChange={(e) => setMotionParams(e.target.value)}
              rows={4}
              placeholder='{"text": "示例文字", "color": "#ffffff"}'
              className="w-full px-3 py-2 border rounded-lg text-sm font-mono"
            />
          </div>
          {motionError && <div className="text-red-500 text-sm">{motionError}</div>}
          {motionStatus && <div className="text-green-600 text-sm">{motionStatus}</div>}
          <button onClick={handleMotionRender} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
            渲染动效
          </button>
        </div>
      )}

      {/* ── HTML 视频 Tab ────────────────────────────────────────────────── */}
      {activeTab === 'html-video' && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">选择模板</label>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {htmlVideoTemplates.length === 0 && <span className="text-gray-400 text-sm">加载中...</span>}
              {htmlVideoTemplates.map((tpl) => (
                <button
                  key={tpl.id as string}
                  onClick={() => setSelectedHtmlTpl(tpl.id as string)}
                  className={`p-3 rounded-lg border text-left text-sm ${
                    selectedHtmlTpl === tpl.id
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="font-medium">{tpl.name as string}</div>
                  {tpl.desc ? <div className="text-gray-500 text-xs mt-1">{String(tpl.desc)}</div> : null}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">HTML 内容</label>
            <textarea
              value={htmlContent}
              onChange={(e) => setHtmlContent(e.target.value)}
              rows={8}
              placeholder="<div>...</div>"
              className="w-full px-3 py-2 border rounded-lg text-sm font-mono"
            />
          </div>
          {htmlVideoError && <div className="text-red-500 text-sm">{htmlVideoError}</div>}
          {htmlVideoStatus && <div className="text-green-600 text-sm">{htmlVideoStatus}</div>}
          <button onClick={handleHtmlVideoRender} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
            渲染 HTML 视频
          </button>
        </div>
      )}

      {/* ── 语音工作室 Tab ───────────────────────────────────────────────── */}
      {activeTab === 'voice' && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">选择操作</label>
            <div className="flex gap-2 flex-wrap">
              {VOICE_OPERATIONS.map((op) => (
                <button
                  key={op.key}
                  onClick={() => {
                    setVoiceOp(op);
                    setVoiceForm({});
                    setVoiceStatus('');
                    setVoiceError('');
                  }}
                  className={`px-3 py-1.5 rounded text-sm border ${
                    voiceOp.key === op.key
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {op.label}
                </button>
              ))}
            </div>
          </div>
          {voiceOp.fields.map((field) => (
            <div key={field.name}>
              <label className="block text-sm font-medium mb-1">{field.label}</label>
              <input
                type="text"
                value={voiceForm[field.name] || ''}
                onChange={(e) => setVoiceForm((f) => ({ ...f, [field.name]: e.target.value }))}
                placeholder={field.placeholder}
                className="w-full px-3 py-2 border rounded-lg text-sm"
              />
            </div>
          ))}
          {voiceError && <div className="text-red-500 text-sm">{voiceError}</div>}
          {voiceStatus && <div className="text-green-600 text-sm">{voiceStatus}</div>}
          <button onClick={handleVoiceSubmit} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
            提交
          </button>
        </div>
      )}

      {/* ── 编舞生成 Tab ─────────────────────────────────────────────────── */}
      {activeTab === 'dance' && (
        <div className="space-y-4">
          {danceGpu && (
            <div className={`text-sm ${danceGpu.available ? 'text-green-600' : 'text-red-500'}`}>
              {danceGpu.available
                ? `✓ GPU 可用: ${danceGpu.gpu_name || '未知'}`
                : '✗ GPU 不可用,编舞功能需要 GPU 支持'}
            </div>
          )}
          <div>
            <label className="block text-sm font-medium mb-1">音频路径 *</label>
            <input
              type="text"
              value={danceForm.audio_path}
              onChange={(e) => setDanceForm((f) => ({ ...f, audio_path: e.target.value }))}
              placeholder="/path/to/audio.mp3"
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">舞蹈类型</label>
            <input
              type="text"
              value={danceForm.dance_type}
              onChange={(e) => setDanceForm((f) => ({ ...f, dance_type: e.target.value }))}
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">时长 (秒)</label>
            <input
              type="text"
              value={danceForm.duration_s}
              onChange={(e) => setDanceForm((f) => ({ ...f, duration_s: e.target.value }))}
              placeholder="留空则自动匹配音频时长"
              className="w-full px-3 py-2 border rounded-lg text-sm"
            />
          </div>
          {danceError && <div className="text-red-500 text-sm">{danceError}</div>}
          {danceStatus && <div className="text-green-600 text-sm">{danceStatus}</div>}
          <button onClick={handleDanceGenerate} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
            生成编舞
          </button>
        </div>
      )}
    </div>
  );
}
