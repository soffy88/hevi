/**
 * §6.2 UX 回归 —— 首页生成中心自动化出片流程(§2)。
 * 校验点:切「🎙️ 头像解说」→ 输入文本 → 选「⚡ 极速」档 → 开始自动出片
 * → 提交到 /api/pipeline/generate 的统一契约(source_channel=hub_quick + adapter_type
 * + config 参数映射,含字幕样式)。同时校验通鉴适配器的风格提示。
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { push, generateMock, presenterListMock } = vi.hoisted(() => ({
  push: vi.fn(),
  generateMock: vi.fn(),
  presenterListMock: vi.fn().mockResolvedValue([{ id: 'presenter_001', name: '刘畊宏' }]),
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

vi.mock('@/lib/auth-store', () => ({ isAuthenticated: () => true, logout: vi.fn() }));

vi.mock('@/lib/api-client', () => ({
  USE_MOCK: false,
  API_BASE: 'http://test',
  presenterApi: { list: presenterListMock },
  productionApi: { generate: generateMock },
  taskApi: {
    estimate: vi.fn().mockResolvedValue({ credits: 12, usd: 0.01 }),
    progressUrl: (id: string) => `/api/tasks/${id}/progress`,
    videoUrl: (id: string) => `/api/tasks/${id}/video`,
    resume: vi.fn(),
    cancel: vi.fn(),
  },
  subjectApi: { list: vi.fn().mockResolvedValue([]), fromPhoto: vi.fn() },
  providerApi: {
    listPresets: vi.fn().mockResolvedValue({
      presets: [
        { name: 'wan_local', level: 'economy', category: 'video', provider: 'wan_local', description: '本地 Wan·零成本', base_url: null, context_window: 0, api_key_env: null, strategy: {} },
        { name: 'autocameo_cloud', level: 'balanced', category: 'video', provider: 'happyhorse_1_1_maas_lock', description: '云端锁脸·AutoCameo', base_url: null, context_window: 0, api_key_env: 'ALIBABA_MAAS_API_KEY', strategy: { face_lock: true } },
      ],
      total: 2, levels: ['economy', 'balanced'],
    }),
    getPreset: vi.fn(),
  },
}));

vi.mock('@helios/oui', () => ({
  OCostConfirmDialog: (p: { open: boolean; onConfirm: () => void }) =>
    p.open ? <button onClick={p.onConfirm}>确认生成</button> : null,
  OTaskProgress: () => null,
  useSSEProgress: () => null,
}));

vi.mock('./Gallery', () => ({ Gallery: () => null }));
vi.mock('./ProviderSelector', () => ({ ProviderSelector: () => null }));

import { SimpleGenerate } from './SimpleGenerate';

describe('首页生成中心 · 自动化出片流程(§6.2 flow 1)', () => {
  beforeEach(() => {
    generateMock.mockClear();
    push.mockClear();
  });

  it('切「头像解说」→ 显示数字人预设 + 字幕样式(§2.2 适配器契约)', async () => {
    const user = userEvent.setup();
    render(<SimpleGenerate />);

    await user.click(screen.getByRole('button', { name: /🎙️ 头像解说/ }));
    expect(screen.getByLabelText('数字人预设')).toBeInTheDocument();
    expect(screen.getByLabelText('字幕样式')).toBeInTheDocument();
  });

  it('切「资治通鉴」→ 显示水墨/古风风格提示(§2.2 通鉴适配器契约)', async () => {
    const user = userEvent.setup();
    render(<SimpleGenerate />);

    await user.click(screen.getByRole('button', { name: /📜 资治通鉴/ }));
    expect(screen.getByText(/水墨\/古风风格预设/)).toBeInTheDocument();
  });

  it('解说流程:输入文本 + 极速档 → 开始出片 → 提交统一契约', async () => {
    const user = userEvent.setup();
    render(<SimpleGenerate />);

    await user.click(screen.getByRole('button', { name: /🎙️ 头像解说/ }));
    await user.type(screen.getByPlaceholderText(/输入解说文案或主题/), '三分钟讲透明朝那些事');
    await user.click(screen.getByRole('button', { name: /⚡ 极速/ }));
    await user.click(screen.getByRole('button', { name: /▶ 开始自动出片/ }));
    await user.click(screen.getByRole('button', { name: '确认生成' }));

    expect(generateMock).toHaveBeenCalledTimes(1);
    const payload = generateMock.mock.calls[0]?.[0];
    expect(payload).toMatchObject({
      source_channel: 'hub_quick',
      adapter_type: 'explainer',
      config: {
        prompt: '三分钟讲透明朝那些事',
        execution_preset: 'fast',
        presenter_id: null,
        character_references: [],
        options: { subtitle_style: 'default' },
      },
    });
  });

  it('创意极速(Idea2Video):增强预览 + Provider Preset → 扩展 prompt 出片(§6.0 §2.1)', async () => {
    const user = userEvent.setup();
    render(<SimpleGenerate />);

    await user.click(screen.getByRole('button', { name: /💡 创意极速/ }));
    await user.type(screen.getByPlaceholderText(/一句话创意/), '一个孤独的旅行者穿越沙漠');
    // 增强预览出现
    expect(await screen.findByText(/增强预览/)).toBeInTheDocument();
    // Provider Preset 选单可用(obase 预置)
    const presetSelect = screen.getByLabelText(/Provider Preset/) as HTMLSelectElement;
    expect(presetSelect).toBeInTheDocument();
    expect(presetSelect.options.length).toBeGreaterThanOrEqual(2);

    await user.click(screen.getByRole('button', { name: /▶ 开始自动出片/ }));
    await user.click(screen.getByRole('button', { name: '确认生成' }));

    expect(generateMock).toHaveBeenCalledTimes(1);
    const payload = generateMock.mock.calls[0]?.[0];
    expect(payload.source_channel).toBe('hub_idea2video');
    expect(payload.config.prompt).toContain('分镜');
    expect(payload.config.prompt).toContain('一个孤独的旅行者穿越沙漠');
    expect(payload.config.options.provider_preset).toBe('wan_local');
    expect(Array.isArray(payload.config.options.idea_scenes)).toBe(true);
  });
});
