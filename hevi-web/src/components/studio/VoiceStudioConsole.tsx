'use client';

import { useState, useEffect } from 'react';
import {
  voiceStudioApi,
  productionApi,
  taskApi,
  proStudioApi,
  type VoiceEffectPreset,
  type VoicePersonalityPreset,
  type VoiceTTSEngine,
} from '@/lib/api-client';
import type { CapabilityDescriptor } from '@/types/api';
import { TabBar, SectionHeader, type TabItem } from '@/components/shared';

type VoiceTab = 'effects' | 'personality' | 'engines' | 'emotion';

type EffectPreviewResult = {
  preset: string;
  effects_count: number;
  effects: Array<{ type: string; params: Record<string, unknown> }>;
};

type RewriteResult = {
  original: string;
  rewritten: string;
  persona: string;
  model_used: string;
  confidence: number;
};

const VOICE_TABS: Array<TabItem<VoiceTab>> = [
  { key: 'effects', label: '音频效果', icon: '🎚️' },
  { key: 'personality', label: '语音人格', icon: '🎭' },
  { key: 'engines', label: 'TTS 引擎', icon: '🔊' },
  { key: 'emotion', label: '情感配音', icon: '❤️‍🔥' },
];

export function VoiceStudioConsole() {
  const [activeTab, setActiveTab] = useState<VoiceTab>('effects');

  // Effects state
  const [effectPresets, setEffectPresets] = useState<VoiceEffectPreset[]>([]);
  const [selectedEffect, setSelectedEffect] = useState<string>('');
  const [effectPreviewText, setEffectPreviewText] = useState('This is a test of the audio effects.');
  const [effectPreviewResult, setEffectPreviewResult] = useState<EffectPreviewResult | null>(null);

  // Personality state
  const [personalityPresets, setPersonalityPresets] = useState<VoicePersonalityPreset[]>([]);
  const [selectedPersona, setSelectedPersona] = useState<string>('');
  const [rewriteInput, setRewriteInput] = useState('');
  const [rewriteResult, setRewriteResult] = useState<RewriteResult | null>(null);

  // TTS Engines state
  const [ttsEngines, setTtsEngines] = useState<VoiceTTSEngine[]>([]);
  const [selectedEngine, setSelectedEngine] = useState<string>('');
  const [synthesisText, setSynthesisText] = useState('');
  const [synthesisTaskId, setSynthesisTaskId] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<Record<string, CapabilityDescriptor>>({});

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load data on mount
  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [effectsRes, personasRes, enginesRes, capabilitiesRes] = await Promise.all([
        voiceStudioApi.listEffectPresets(),
        voiceStudioApi.listPersonalityPresets(),
        voiceStudioApi.listTTSEngines(),
        productionApi.capabilities(),
      ]);
      setEffectPresets(effectsRes.presets);
      setPersonalityPresets(personasRes.presets);
      setTtsEngines(enginesRes.engines);
      setCapabilities(Object.fromEntries(capabilitiesRes.capabilities.map((item) => [item.id, item])));
    } catch (err) {
      console.error('Failed to load voice studio data:', err);
      setError('加载数据失败，请确保后端服务正在运行');
    } finally {
      setLoading(false);
    }
  };

  const previewEffect = async () => {
    if (!selectedEffect) return;
    try {
      const result = await voiceStudioApi.previewEffect(selectedEffect, effectPreviewText);
      setEffectPreviewResult(result);
    } catch (err) {
      console.error('Failed to preview effect:', err);
    }
  };

  const rewriteWithPersonality = async () => {
    if (!selectedPersona || !rewriteInput || !capabilities.voice_studio_rewrite?.available) return;
    try {
      const result = await voiceStudioApi.rewriteWithPersonality(rewriteInput, selectedPersona);
      setRewriteResult(result);
    } catch (err) {
      console.error('Failed to rewrite with personality:', err);
    }
  };

  const synthesizeVoice = async () => {
    const selectedEngineInfo = ttsEngines.find((engine) => engine.id === selectedEngine);
    if (!selectedEngineInfo?.available || !synthesisText) return;
    setLoading(true);
    setError(null);
    try {
      const result = await voiceStudioApi.synthesizeTTS(synthesisText, selectedEngine);
      setSynthesisTaskId(result.task_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : '语音任务创建失败');
    } finally {
      setLoading(false);
    }
  };

  if (loading && effectPresets.length === 0) {
    return <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--muted-foreground)' }}>加载中…</div>;
  }

  if (error) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0' }}>
        <p style={{ color: 'var(--destructive, #e53e3e)', marginBottom: '12px' }}>{error}</p>
        <button onClick={loadData} style={{ color: 'var(--primary)', textDecoration: 'underline', cursor: 'pointer', background: 'none', border: 'none' }}>
          重试
        </button>
      </div>
    );
  }

  const selectedEngineInfo = ttsEngines.find((engine) => engine.id === selectedEngine);

  return (
    <div>
      <SectionHeader icon="🎙️" title="声音工作室" subtitle="VoiceBox 驱动的音频效果、人格改写、TTS 引擎与情感配音（原专业工作室情感TTS能力已归集于此）" />

      <TabBar items={VOICE_TABS} active={activeTab} onChange={setActiveTab} />

      {!capabilities.voice_studio_tts?.available && (
        <div style={{ margin: '16px 0', padding: '12px 16px', borderRadius: '8px', background: '#fffbeb', color: '#92400e', border: '1px solid #fcd34d' }}>
          <strong>语音生成暂不可用：</strong> {capabilities.voice_studio_tts?.message ?? '正在检查能力状态'}
          {capabilities.voice_studio_tts?.setup && <span> {capabilities.voice_studio_tts.setup}</span>}
        </div>
      )}

      {/* Effects Tab */}
      {activeTab === 'effects' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ background: 'var(--card, #fff)', borderRadius: '8px', border: '1px solid var(--border, #e2e8f0)', padding: '24px' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '8px' }}>音频效果预设</h2>
            <p style={{ fontSize: '13px', color: 'var(--muted-foreground)', marginBottom: '16px' }}>
              对对白和音频应用后处理效果。这些效果已集成到生产管线中。
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px', marginBottom: '20px' }}>
              {effectPresets.map((preset) => (
                <div
                  key={preset.name}
                  onClick={() => setSelectedEffect(preset.name)}
                  style={{
                    padding: '16px',
                    borderRadius: '8px',
                    border: selectedEffect === preset.name ? '2px solid var(--primary, #3b82f6)' : '1px solid var(--border, #e2e8f0)',
                    background: selectedEffect === preset.name ? 'var(--primary-bg, #eff6ff)' : 'transparent',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  <h3 style={{ fontWeight: 500, fontSize: '14px', textTransform: 'capitalize' }}>
                    {preset.name.replace(/_/g, ' ')}
                  </h3>
                  <p style={{ fontSize: '12px', color: 'var(--muted-foreground)', marginTop: '4px' }}>
                    {preset.effects.length} 个效果
                  </p>
                </div>
              ))}
            </div>

            {selectedEffect && (
              <div style={{ borderTop: '1px solid var(--border, #e2e8f0)', paddingTop: '16px' }}>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: 500, marginBottom: '8px' }}>
                  预览文本
                </label>
                <textarea
                  value={effectPreviewText}
                  onChange={(e) => setEffectPreviewText(e.target.value)}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border, #e2e8f0)', fontSize: '13px' }}
                  rows={2}
                />
                <button
                  onClick={previewEffect}
                  style={{ marginTop: '12px', padding: '8px 16px', background: 'var(--primary, #3b82f6)', color: '#fff', borderRadius: '6px', border: 'none', cursor: 'pointer', fontSize: '13px' }}
                >
                  预览效果
                </button>

                {effectPreviewResult && (
                  <div style={{ marginTop: '16px', padding: '16px', background: 'var(--muted, #f7fafc)', borderRadius: '8px' }}>
                    <h4 style={{ fontWeight: 500, fontSize: '14px', marginBottom: '8px' }}>效果配置</h4>
                    <pre style={{ fontSize: '12px', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
                      {JSON.stringify(effectPreviewResult, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Personality Tab */}
      {activeTab === 'personality' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ background: 'var(--card, #fff)', borderRadius: '8px', border: '1px solid var(--border, #e2e8f0)', padding: '24px' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '8px' }}>语音人格预设</h2>
            <p style={{ fontSize: '13px', color: 'var(--muted-foreground)', marginBottom: '16px' }}>
              用 LLM 将对白文本改写为匹配角色人格和说话风格。
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px', marginBottom: '20px' }}>
              {personalityPresets.map((persona) => (
                <div
                  key={persona.name}
                  onClick={() => setSelectedPersona(persona.name)}
                  style={{
                    padding: '16px',
                    borderRadius: '8px',
                    border: selectedPersona === persona.name ? '2px solid var(--primary, #3b82f6)' : '1px solid var(--border, #e2e8f0)',
                    background: selectedPersona === persona.name ? 'var(--primary-bg, #eff6ff)' : 'transparent',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  <h3 style={{ fontWeight: 500, fontSize: '14px', textTransform: 'capitalize' }}>
                    {persona.name.replace(/_/g, ' ')}
                  </h3>
                  <p style={{ fontSize: '13px', color: 'var(--muted-foreground)', marginTop: '4px' }}>{persona.description}</p>
                  <p style={{ fontSize: '12px', color: 'var(--muted-foreground)', marginTop: '8px' }}>
                    风格：{persona.speaking_style}
                  </p>
                  {persona.vocabulary.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '8px' }}>
                      {persona.vocabulary.slice(0, 3).map((word, i) => (
                        <span
                          key={i}
                          style={{ padding: '2px 8px', background: 'var(--muted, #f1f5f9)', fontSize: '12px', borderRadius: '4px' }}
                        >
                          {word}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {selectedPersona && (
              <div style={{ borderTop: '1px solid var(--border, #e2e8f0)', paddingTop: '16px' }}>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: 500, marginBottom: '8px' }}>
                  输入文本（改写为角色语音风格）
                </label>
                <textarea
                  value={rewriteInput}
                  onChange={(e) => setRewriteInput(e.target.value)}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border, #e2e8f0)', fontSize: '13px' }}
                  rows={3}
                  placeholder="输入需要对白文本进行改写…"
                />
                <button
                  onClick={rewriteWithPersonality}
                  disabled={!rewriteInput || !capabilities.voice_studio_rewrite?.available}
                  style={{
                    marginTop: '12px',
                    padding: '8px 16px',
                    background: rewriteInput && capabilities.voice_studio_rewrite?.available ? 'var(--primary, #3b82f6)' : 'var(--muted, #cbd5e1)',
                    color: '#fff',
                    borderRadius: '6px',
                    border: 'none',
                    cursor: rewriteInput && capabilities.voice_studio_rewrite?.available ? 'pointer' : 'not-allowed',
                    fontSize: '13px',
                  }}
                >
                  人格改写
                </button>
                {!capabilities.voice_studio_rewrite?.available && (
                  <p style={{ marginTop: '8px', fontSize: '12px', color: '#92400e' }}>
                    {capabilities.voice_studio_rewrite?.message ?? '正在检查改写能力状态'}
                  </p>
                )}

                {rewriteResult && (
                  <div style={{ marginTop: '16px', padding: '16px', background: 'var(--muted, #f7fafc)', borderRadius: '8px' }}>
                    <h4 style={{ fontWeight: 500, fontSize: '14px', marginBottom: '8px' }}>改写结果</h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      <div>
                        <span style={{ fontSize: '12px', color: 'var(--muted-foreground)' }}>原文：</span>
                        <p style={{ fontSize: '13px' }}>{rewriteResult.original}</p>
                      </div>
                      <div>
                        <span style={{ fontSize: '12px', color: 'var(--muted-foreground)' }}>改写后：</span>
                        <p style={{ fontSize: '13px', fontWeight: 500 }}>{rewriteResult.rewritten}</p>
                      </div>
                      <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: 'var(--muted-foreground)' }}>
                        <span>模型：{rewriteResult.model_used}</span>
                        <span>置信度：{(rewriteResult.confidence * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Emotion TTS Tab — 原专业工作室情感TTS归位(SPEC v5.0 §2.1) */}
      {activeTab === 'emotion' && <EmotionTTSTab />}
      {activeTab === 'engines' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ background: 'var(--card, #fff)', borderRadius: '8px', border: '1px solid var(--border, #e2e8f0)', padding: '24px' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '8px' }}>TTS 引擎</h2>
            <p style={{ fontSize: '13px', color: 'var(--muted-foreground)', marginBottom: '16px' }}>
              为生产管线选择和配置文本转语音引擎。
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
              {ttsEngines.map((engine) => (
                <div
                  key={engine.id}
                  onClick={() => setSelectedEngine(engine.id)}
                  style={{
                    padding: '16px',
                    borderRadius: '8px',
                    border: selectedEngine === engine.id ? '2px solid var(--primary, #3b82f6)' : '1px solid var(--border, #e2e8f0)',
                    background: selectedEngine === engine.id ? 'var(--primary-bg, #eff6ff)' : 'transparent',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <h3 style={{ fontWeight: 500, fontSize: '14px' }}>{engine.name}</h3>
                    <span
                      style={{
                        padding: '2px 8px',
                        fontSize: '12px',
                        borderRadius: '4px',
                        background: engine.type === 'cloud' ? '#f3e8ff' : '#dcfce7',
                        color: engine.type === 'cloud' ? '#7c3aed' : '#16a34a',
                      }}
                    >
                      {engine.type}
                    </span>
                  </div>
                  <p style={{ fontSize: '13px', color: 'var(--muted-foreground)', marginTop: '8px' }}>{engine.description}</p>
                  <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {engine.requires_gpu && (
                      <p style={{ fontSize: '12px', color: '#d97706' }}>⚠️ 需要 GPU</p>
                    )}
                    {engine.languages && (
                      <p style={{ fontSize: '12px', color: 'var(--muted-foreground)' }}>
                        语言：{engine.languages.length} 种
                      </p>
                    )}
                    {engine.voice_categories && (
                      <p style={{ fontSize: '12px', color: 'var(--muted-foreground)' }}>
                        音色：{Object.values(engine.voice_categories).reduce((a, b) => a + b, 0)} 个
                      </p>
                    )}
                    {engine.paralinguistic_tags && (
                      <p style={{ fontSize: '12px', color: 'var(--muted-foreground)' }}>
                        副语言标签：{engine.paralinguistic_tags.length} 个
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {selectedEngine && (
              <div style={{ marginTop: '20px', padding: '16px', background: 'var(--primary-bg, #eff6ff)', borderRadius: '8px', border: '1px solid #bfdbfe' }}>
                <h4 style={{ fontWeight: 500, color: '#1e40af', marginBottom: '8px' }}>
                  已选择：{ttsEngines.find((e) => e.id === selectedEngine)?.name}
                </h4>
                <p style={{ fontSize: '13px', color: '#1e40af' }}>
                  此引擎将在生产管线中使用，当 <code style={{ background: '#dbeafe', padding: '2px 4px', borderRadius: '4px' }}>tts_engine</code> 设为{' '}
                  <code style={{ background: '#dbeafe', padding: '2px 4px', borderRadius: '4px' }}>{selectedEngine}</code> 时生效。
                </p>
                <textarea
                  value={synthesisText}
                  onChange={(event) => setSynthesisText(event.target.value)}
                  rows={3}
                  placeholder="输入要合成的文案…"
                  style={{ width: '100%', marginTop: '12px', padding: '8px', borderRadius: '6px', border: '1px solid #93c5fd' }}
                />
                <button
                  onClick={synthesizeVoice}
                  disabled={loading || !synthesisText || !selectedEngineInfo?.available}
                  style={{ marginTop: '8px', padding: '8px 16px', color: '#fff', background: '#2563eb', border: 'none', borderRadius: '6px', cursor: 'pointer' }}
                >
                  {loading ? '正在创建任务…' : '创建语音任务'}
                </button>
                {synthesisTaskId && (
                  <div style={{ marginTop: '12px' }}>
                    <p style={{ fontSize: '12px', color: '#1e40af' }}>任务已创建：{synthesisTaskId}</p>
                    <audio controls src={taskApi.audioUrl(synthesisTaskId)} style={{ width: '100%', marginTop: '6px' }} />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function EmotionTTSTab() {
  const [text, setText] = useState('');
  const [speaker, setSpeaker] = useState('');
  const [emotions, setEmotions] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function detectEmotion() {
    if (!text) return;
    setLoading(true); setError(null);
    try {
      const data = await proStudioApi.indexttsEmotionFromText({ text });
      setEmotions(data.emo_vector);
    } catch (e) { setError(e instanceof Error ? e.message : '情感分析失败'); }
    setLoading(false);
  }

  async function synthesize() {
    if (!speaker || !text) return;
    setLoading(true); setError(null);
    try {
      const data = await proStudioApi.indexttsSynthesize({ speaker, text, emo_vector: emotions ?? undefined });
      setResult(data);
    } catch (e) { setError(e instanceof Error ? e.message : '语音合成失败'); }
    setLoading(false);
  }

  return (
    <div style={{ background: 'var(--card, #fff)', borderRadius: '8px', border: '1px solid var(--border, #e2e8f0)', padding: '24px' }}>
      <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '8px' }}>❤️‍🔥 情绪化配音 (Emotion-aware Voiceover)</h2>
      <p style={{ fontSize: '13px', color: 'var(--muted-foreground)', marginBottom: '16px' }}>
        逐行推断情绪并调整语速/音高,支持多说话人与声线克隆。
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <label style={{ display: 'block', fontSize: '13px', fontWeight: 500 }}>
          说话人 (speaker path)
          <input value={speaker} onChange={(e) => setSpeaker(e.target.value)}
            placeholder="/path/to/speaker.wav"
            style={{ display: 'block', width: '100%', marginTop: '6px', padding: '8px', borderRadius: '6px', border: '1px solid var(--border, #e2e8f0)', fontSize: '13px' }} />
        </label>
        <label style={{ display: 'block', fontSize: '13px', fontWeight: 500 }}>
          合成文本
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4}
            style={{ display: 'block', width: '100%', marginTop: '6px', padding: '8px', borderRadius: '6px', border: '1px solid var(--border, #e2e8f0)', fontSize: '13px' }} />
        </label>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button onClick={detectEmotion} disabled={loading || !text}
            style={{ padding: '8px 16px', borderRadius: '6px', border: '1px solid var(--border, #e2e8f0)', background: 'var(--muted, #f1f5f9)', cursor: 'pointer', fontSize: '13px' }}>
            🎭 从文本推断情感
          </button>
          <button onClick={synthesize} disabled={loading || !speaker || !text}
            style={{ padding: '8px 16px', borderRadius: '6px', border: 'none', background: 'var(--primary, #3b82f6)', color: '#fff', cursor: 'pointer', fontSize: '13px' }}>
            🔊 合成语音
          </button>
        </div>
        {emotions && (
          <div style={{ padding: '12px', background: 'var(--muted, #f7fafc)', borderRadius: '8px' }}>
            <p style={{ fontSize: '12px', color: 'var(--muted-foreground)', marginBottom: '6px' }}>情感向量:</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {Object.entries(emotions).map(([k, v]) => (
                <span key={k} style={{ padding: '3px 8px', background: 'var(--primary-bg, #eff6ff)', borderRadius: '4px', fontSize: '12px' }}>
                  {k}: {v.toFixed(2)}
                </span>
              ))}
            </div>
          </div>
        )}
        {result && (
          <div style={{ padding: '12px', background: 'var(--muted, #f7fafc)', borderRadius: '8px' }}>
            <p style={{ fontSize: '13px', fontWeight: 500, color: '#16a34a' }}>✅ 合成任务已提交</p>
            <pre style={{ fontSize: '12px', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(result, null, 2)}</pre>
          </div>
        )}
        {error && <p style={{ fontSize: '13px', color: 'var(--destructive, #e53e3e)' }}>⚠ {error}</p>}
      </div>
    </div>
  );
}
