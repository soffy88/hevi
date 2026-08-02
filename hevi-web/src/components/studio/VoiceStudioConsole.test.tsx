/**
 * VoiceStudioConsole 回归测试 — Frontend SPEC v5.0 §2.1
 * 语音工作室接收情感 TTS(原专业工作室归位):情绪化配音控制
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { VoiceStudioConsole } from './VoiceStudioConsole';

const hoisted = vi.hoisted(() => ({
  listEffectPresets: vi.fn().mockResolvedValue({ presets: [] }),
  listPersonalityPresets: vi.fn().mockResolvedValue({ presets: [] }),
  listTTSEngines: vi.fn().mockResolvedValue({ engines: [] }),
  capabilities: vi.fn().mockResolvedValue({ capabilities: [] }),
  emotionFromText: vi.fn().mockResolvedValue({ emo_vector: { happy: 0.7, sad: 0.1 } }),
  synthesize: vi.fn().mockResolvedValue({ task_id: 't1', status: 'queued' }),
}));

vi.mock('@/lib/api-client', () => ({
  voiceStudioApi: {
    listEffectPresets: hoisted.listEffectPresets,
    listPersonalityPresets: hoisted.listPersonalityPresets,
    listTTSEngines: hoisted.listTTSEngines,
    previewEffect: vi.fn(),
    rewriteWithPersonality: vi.fn(),
    synthesizeTTS: vi.fn(),
  },
  productionApi: { capabilities: hoisted.capabilities },
  taskApi: { audioUrl: (id: string) => `/api/tasks/${id}/audio` },
  proStudioApi: {
    indexttsEmotionFromText: hoisted.emotionFromText,
    indexttsSynthesize: hoisted.synthesize,
  },
}));

vi.mock('@/components/shared', async (importOriginal) => {
  const orig = await importOriginal<typeof import('@/components/shared')>();
  return { ...orig };
});

describe('语音工作室情感配音(SPEC v5.0 §2.1)', () => {
  it('提供情绪化配音控制:从文本推断情感 + 情感合成', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<VoiceStudioConsole />);
    // 等异步能力/预设加载完成(加载中… → Tab 渲染)
    const emotionTab = await screen.findByRole('button', { name: /情感配音/ }, { timeout: 3000 });
    await user.click(emotionTab);
    expect(screen.getByText(/情绪化配音 \(Emotion-aware Voiceover\)/)).toBeInTheDocument();
    await user.type(screen.getByLabelText('合成文本'), '太棒了，我们赢了！');
    await user.click(screen.getByRole('button', { name: '🎭 从文本推断情感' }));
    expect(await screen.findByText(/happy: 0.70/)).toBeInTheDocument();
    expect(hoisted.emotionFromText).toHaveBeenCalledWith({ text: '太棒了，我们赢了！' });
  });
});
