'use client';

import { useState, useEffect } from 'react';
import {
  voiceStudioApi,
  type VoiceEffectPreset,
  type VoicePersonalityPreset,
  type VoiceTTSEngine,
} from '@/lib/api-client';
import { TabBar, SectionHeader, type TabItem } from '@/components/shared';

type VoiceTab = 'effects' | 'personality' | 'engines';

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
      const [effectsRes, personasRes, enginesRes] = await Promise.all([
        voiceStudioApi.listEffectPresets(),
        voiceStudioApi.listPersonalityPresets(),
        voiceStudioApi.listTTSEngines(),
      ]);
      setEffectPresets(effectsRes.presets);
      setPersonalityPresets(personasRes.presets);
      setTtsEngines(enginesRes.engines);
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
    if (!selectedPersona || !rewriteInput) return;
    try {
      const result = await voiceStudioApi.rewriteWithPersonality(rewriteInput, selectedPersona);
      setRewriteResult(result);
    } catch (err) {
      console.error('Failed to rewrite with personality:', err);
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

  return (
    <div>
      <SectionHeader icon="🎙️" title="声音工作室" subtitle="VoiceBox 驱动的音频效果、人格改写与 TTS 引擎管理" />

      <TabBar items={VOICE_TABS} active={activeTab} onChange={setActiveTab} />

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
                  disabled={!rewriteInput}
                  style={{
                    marginTop: '12px',
                    padding: '8px 16px',
                    background: rewriteInput ? 'var(--primary, #3b82f6)' : 'var(--muted, #cbd5e1)',
                    color: '#fff',
                    borderRadius: '6px',
                    border: 'none',
                    cursor: rewriteInput ? 'pointer' : 'not-allowed',
                    fontSize: '13px',
                  }}
                >
                  人格改写
                </button>

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

      {/* TTS Engines Tab */}
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
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
